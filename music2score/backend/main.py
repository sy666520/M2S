"""music2score Web 服务。

上传音频 -> 自动转谱 -> 输出五线谱 / 简谱 / 吉他六线谱。
"""
import io
import json
import os
import shutil
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from urllib.parse import quote

import qrcode
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import ads as ads_mod
from . import license as lic
from .models import QuantNote, Score
from .pipeline import transcribe_audio
from .transcribe.base import available_transcribers
from .urlload import (FetchError, ensure_public, extract_url, fetch_audio,
                      public_config)
from .renderers.staff import render_staff_pages
from .renderers.jianpu import render_jianpu_pages
from .renderers.tab import render_tab_pages
from .renderers.musicxml import build_musicxml
from .renderers.midi import build_midi

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif"}

# 手动拍号白名单：自动推断不准时用得上
METER_CHOICES = {
    "auto": None,
    "4/4": (4, 4), "3/4": (3, 4), "2/4": (2, 4),
    "6/8": (6, 8), "3/8": (3, 8), "12/8": (12, 8),
}

# 手动调性："C major" / "A minor" -> Key
def parse_key(s: Optional[str]):
    if not s or s == "auto":
        return None
    parts = s.strip().split()
    if len(parts) != 2:
        return None
    names = {n: i for i, n in enumerate(
        ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}
    pc = names.get(parts[0])
    mode = parts[1]
    if pc is None or mode not in ("major", "minor"):
        return None
    from .models import Key
    return Key(tonic_pc=pc, mode=mode)


KEY_OPTIONS = [{"id": "auto", "label": "自动判断", "group": ""}] + [
    {"id": f"{n} major", "label": f"{n} 大调", "group": "大调"}
    for n in ["C", "G", "D", "A", "E", "B", "F#", "C#", "F", "Bb", "Eb", "Ab"]
] + [
    {"id": f"{n} minor", "label": f"{n} 小调", "group": "小调"}
    for n in ["A", "E", "B", "F#", "C#", "G#", "D#", "A#", "D", "G", "C", "F"]
]

app = FastAPI(title="music2score", version="0.1.0")

JOBS: dict = {}
_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=2)

VIEWS = {
    "staff": render_staff_pages,
    "jianpu": render_jianpu_pages,
    "tab": render_tab_pages,
}


def _safe_name(name: str) -> str:
    name = os.path.basename(name or "audio")
    keep = [c for c in name if c.isalnum() or c in "._- "]
    return ("".join(keep) or "audio")[:120]


def _quota_blocked(st: dict) -> JSONResponse:
    """额度用尽：402 让前端弹「看推广 / 输激活码」，而不是报一个干巴巴的错误。"""
    return JSONResponse(status_code=402, content={
        "detail": "今日免费额度已用完",
        "code": "QUOTA_EXCEEDED",
        "license": st,
    })


# ---------------------------------------------------------------- 授权 / 推广位

@app.get("/api/license")
def license_state():
    return lic.status()


@app.post("/api/license/redeem")
def license_redeem(payload: dict = Body(...)):
    ok, msg, st = lic.redeem(str(payload.get("code") or ""))
    return JSONResponse(status_code=200 if ok else 400,
                        content={"ok": ok, "message": msg, "license": st})


@app.post("/api/license/ad/start")
def license_ad_start(payload: Optional[dict] = Body(None)):
    ok, data = lic.start_ad(str((payload or {}).get("slot") or "unlock"))
    return JSONResponse(status_code=200 if ok else 429,
                        content={"ok": ok, **data})


@app.post("/api/license/ad/claim")
def license_ad_claim(payload: dict = Body(...)):
    ok, msg, st = lic.claim_ad(str(payload.get("session_id") or ""))
    return JSONResponse(status_code=200 if ok else 400,
                        content={"ok": ok, "message": msg, "license": st})


@app.get("/api/ads")
def ads_list(slot: str = ""):
    if slot:
        return {"item": ads_mod.pick(slot)}
    return ads_mod.public_list()


@app.post("/api/ads/event")
def ads_event(payload: dict = Body(...)):
    ads_mod.record(str(payload.get("id") or ""),
                   str(payload.get("slot") or "banner"),
                   str(payload.get("type") or "impression"))
    return {"ok": True}


@app.get("/api/ads/stats")
def ads_stats():
    """招商对账用：按推广位统计曝光与点击。"""
    return ads_mod.stats()


@app.get("/api/meta")
def meta():
    return {
        "transcribers": available_transcribers(),
        "views": [
            {"id": "staff", "label": "五线谱"},
            {"id": "jianpu", "label": "简谱"},
            {"id": "tab", "label": "吉他六线谱"},
        ],
        "meters": [{"id": k, "label": "自动判断" if k == "auto" else k}
                   for k in METER_CHOICES],
        "keys": KEY_OPTIONS,
        "max_upload_mb": 200,
        # 链接导入：picker 里的站点、是否装了浏览器组件、时长/体积上限
        "url_import": public_config(),
        # 授权状态：免费额度、是否买断、今日还能看几次推广
        "license": lic.status(),
        "billing": {
            "enabled": lic.billing_enabled(),
            "free_per_day": lic.FREE_PER_DAY,
            "bonus_per_ad": lic.BONUS_PER_AD,
            "max_ad_per_day": lic.MAX_AD_PER_DAY,
        },
        "desktop": os.environ.get("M2S_DESKTOP") == "1",
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...),
                     transcriber: str = Form("pyin"),
                     title: str = Form(""),
                     meter: str = Form("auto"),
                     key: str = Form("auto")):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext and ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的音频格式：{ext}")

    allowed, lic_state = lic.consume()
    if not allowed:
        return _quota_blocked(lic_state)

    job_id = uuid.uuid4().hex[:12]
    dest_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, _safe_name(file.filename or "audio"))

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job = {
        "id": job_id,
        "status": "processing",
        "progress": 0.0,
        "stage": "排队中…",
        "error": None,
        "score": None,
        "meta": None,
        "audio_path": dest,
        "source_url": None,
        "source_meta": None,
        "title": (title or "").strip() or os.path.splitext(_safe_name(file.filename))[0],
        "transcriber": transcriber,
        "licensed": True,
        "meter": METER_CHOICES.get(meter, None),
        "key": parse_key(key),
        "created": time.time(),
    }
    with _LOCK:
        JOBS[job_id] = job

    _EXECUTOR.submit(_run_job, job_id)
    return {"job_id": job_id}


@app.post("/api/transcribe-url")
async def transcribe_url(url: str = Form(...),
                         transcriber: str = Form("crepe"),
                         title: str = Form(""),
                         meter: str = Form("auto"),
                         key: str = Form("auto")):
    """从抖音 / B 站等视频链接导入音频并转谱。"""
    try:
        clean = extract_url(url)
        ensure_public(clean)
    except ValueError as e:
        raise HTTPException(400, str(e))

    allowed, lic_state = lic.consume()
    if not allowed:
        return _quota_blocked(lic_state)

    job_id = uuid.uuid4().hex[:12]
    dest_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(dest_dir, exist_ok=True)

    job = {
        "id": job_id,
        "status": "processing",
        "progress": 0.0,
        "stage": "准备下载…",
        "error": None,
        "score": None,
        "meta": None,
        # 下载完成后会被真实路径覆盖
        "audio_path": os.path.join(dest_dir, "source.wav"),
        "source_url": clean,
        "source_meta": None,
        "title": (title or "").strip(),
        "transcriber": transcriber,
        "licensed": True,
        "meter": METER_CHOICES.get(meter, None),
        "key": parse_key(key),
        "created": time.time(),
    }
    with _LOCK:
        JOBS[job_id] = job

    _EXECUTOR.submit(_run_job, job_id)
    return {"job_id": job_id, "source": clean}


def _run_job(job_id: str):
    with _LOCK:
        job = JOBS.get(job_id)
    if not job:
        return

    def on_progress(v: float, msg: str):
        with _LOCK:
            job["progress"] = round(float(v), 3)
            job["stage"] = msg

    try:
        progress = on_progress
        # 链接导入：先下载音源，再跑转谱；进度 0~12% 归下载
        if job.get("source_url"):
            def download_progress(v: float, msg: str):
                on_progress(0.12 * v, msg)

            info = fetch_audio(job["source_url"],
                               os.path.dirname(job["audio_path"]),
                               download_progress)
            with _LOCK:
                job["audio_path"] = info["path"]
                job["source_meta"] = {
                    "platform": info.get("platform"),
                    "duration": info.get("duration"),
                    "method": info.get("method"),
                }
                if not job.get("title"):
                    job["title"] = info.get("title") or "未命名"

            def pipeline_progress(v: float, msg: str):
                on_progress(0.12 + 0.88 * v, msg)

            progress = pipeline_progress

        score = transcribe_audio(
            job["audio_path"],
            transcriber_name=job.get("transcriber") or "pyin",
            title=job["title"],
            meter=job.get("meter"),
            key=job.get("key"),
            progress=progress,
        )
        with _LOCK:
            job["score"] = score
            job["meta"] = _score_meta(score)
            job["status"] = "done"
            job["progress"] = 1.0
            job["stage"] = "完成"
    except Exception as e:
        with _LOCK:
            job["status"] = "error"
            # 链接导入的错误已经是给用户看的中文，不再加异常类名前缀
            job["error"] = str(e) if isinstance(e, FetchError) else f"{type(e).__name__}: {e}"
            job["stage"] = "失败"
            refundable = bool(job.get("licensed"))
            job["licensed"] = False
        # 失败了不该扣用户额度；放在锁外避免和 license 的锁嵌套
        if refundable:
            try:
                lic.refund()
            except Exception:
                pass


def _score_meta(score: Score) -> dict:
    pitches = [n.midi for n in score.notes]
    return {
        "title": score.title,
        "tempo": score.tempo,
        "meter": list(score.meter),
        "key": score.key.name,
        "key_mode": score.key.mode,
        "tonic_pc": score.key.tonic_pc,
        "note_count": len(score.notes),
        "source_duration": score.source_duration,
        "total_beats": score.total_beats,
        "grid": score.grid,
        "transcriber": score.transcriber,
        "range_low": min(pitches) if pitches else None,
        "range_high": max(pitches) if pitches else None,
    }


def _get_job(job_id: str) -> dict:
    with _LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在或已过期")
    return job


def _done_score(job_id: str) -> Score:
    job = _get_job(job_id)
    if job["status"] != "done":
        raise HTTPException(409, f"任务状态：{job['status']}")
    return job["score"]


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = _get_job(job_id)
    return {
        "id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "stage": job["stage"],
        "error": job["error"],
        "meta": job["meta"],
        "title": job["title"],
        "source_url": job.get("source_url"),
        "source_meta": job.get("source_meta"),
    }


@app.get("/api/jobs/{job_id}/score/{view}")
def job_score(job_id: str, view: str):
    if view not in VIEWS:
        raise HTTPException(400, f"未知视图：{view}")
    score = _done_score(job_id)
    job = _get_job(job_id)
    try:
        pages = VIEWS[view](score, job["title"])
    except Exception as e:
        raise HTTPException(500, f"渲染失败：{type(e).__name__}: {e}")
    return {"view": view, "pages": pages, "meta": _score_meta(score)}


@app.get("/api/jobs/{job_id}/notes")
def job_notes(job_id: str):
    score = _done_score(job_id)
    return {
        "tempo": score.tempo,
        "meter": list(score.meter),
        "key": score.key.name,
        "notes": [
            {"beat": round(n.beat, 4), "dur": round(n.dur, 4), "midi": n.midi}
            for n in score.notes
        ],
    }


@app.post("/api/jobs/{job_id}/notes/edit")
async def job_notes_edit(job_id: str, payload: dict = Body(...)):
    """保存人工校对结果：替换音符列表，可同时修正速度 / 拍号 / 调性。

    校对只改内存中的 Score —— 各视图按请求即时渲染，保存后无需重跑识别。
    """
    score = _done_score(job_id)
    job = _get_job(job_id)

    notes_in = payload.get("notes")
    if not isinstance(notes_in, list) or not notes_in:
        raise HTTPException(400, "notes 列表不能为空")
    out = []
    for i, n in enumerate(notes_in):
        try:
            midi = int(n["midi"])
            beat = float(n["beat"])
            dur = float(n["dur"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, f"第 {i + 1} 个音符缺少 midi / beat / dur")
        if not 0 <= midi <= 127:
            raise HTTPException(400, f"第 {i + 1} 个音符音高超出范围（{midi}）")
        if beat < 0 or dur <= 0:
            raise HTTPException(400, f"第 {i + 1} 个音符时间不合法（beat={beat}, dur={dur}）")
        out.append(QuantNote(midi=midi, beat=round(beat, 4),
                             dur=round(max(dur, 0.05), 4)))
    out.sort(key=lambda x: (x.beat, x.midi))

    tempo = payload.get("tempo")
    if tempo is not None:
        try:
            tempo = float(tempo)
        except (TypeError, ValueError):
            raise HTTPException(400, "tempo 不是数字")
        if not 20 <= tempo <= 300:
            raise HTTPException(400, "tempo 需在 20–300 之间")
        score.tempo = tempo

    meter = payload.get("meter")
    if meter:
        try:
            num, den = int(meter[0]), int(meter[1])
        except (TypeError, ValueError):
            raise HTTPException(400, "meter 格式不正确")
        if not (1 <= num <= 32 and den in (1, 2, 4, 8, 16)):
            raise HTTPException(400, "meter 数值不合法")
        score.meter = (num, den)

    key = payload.get("key")
    if key:
        k = parse_key(str(key))
        if not k:
            raise HTTPException(400, f"无法识别的调性：{key}")
        score.key = k

    score.notes = out
    score.total_beats = max((n.beat + n.dur for n in out), default=0.0)
    with _LOCK:
        job["meta"] = _score_meta(score)
    return {"ok": True, "meta": job["meta"]}


@app.get("/api/jobs/{job_id}/audio")
def job_audio(job_id: str):
    job = _get_job(job_id)
    path = job["audio_path"]
    if not os.path.exists(path):
        raise HTTPException(404, "音频已失效")
    return FileResponse(path, media_type="audio/*")


def _content_disposition(name: str, ext: str) -> str:
    """HTTP 头不允许非 ASCII，中文标题走 RFC 5987 的 filename*。"""
    ascii_name = name.encode("ascii", "ignore").decode().strip() or "score"
    return (f'attachment; filename="{ascii_name}.{ext}"; '
            f"filename*=UTF-8''{quote(name)}.{ext}")


@app.get("/api/jobs/{job_id}/export/{fmt}")
def job_export(job_id: str, fmt: str):
    score = _done_score(job_id)
    job = _get_job(job_id)
    name = _safe_name(job["title"] or "score")
    if fmt == "midi":
        data = build_midi(score)
        return Response(content=data, media_type="audio/midi",
                        headers={"Content-Disposition": _content_disposition(name, "mid")})
    if fmt == "musicxml":
        xml = build_musicxml(score, job["title"])
        return Response(content=xml.encode("utf-8"), media_type="application/xml",
                        headers={"Content-Disposition": _content_disposition(name, "musicxml")})
    if fmt == "json":
        import json
        payload = {"meta": _score_meta(score),
                   "notes": [{"beat": n.beat, "dur": n.dur, "midi": n.midi} for n in score.notes]}
        return JSONResponse(payload)
    raise HTTPException(400, f"未知导出格式：{fmt}")


# 静态前端放最后挂载，避免抢占 /api 路由
DOWNLOADS_FILE = os.path.join(FRONTEND_DIR, "downloads.json")


def _lan_ip() -> str:
    """取局域网源地址（UDP connect 不发包，只是查路由表）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("223.5.5.5", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _load_downloads() -> dict:
    """原生安装包配置。填好 apk_url / appstore_url 并置 available 后页面自动出现下载按钮。"""
    try:
        with open(DOWNLOADS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"android": {"available": False}, "ios": {"available": False}}


@app.get("/install")
@app.get("/install/")
def install_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "install.html"), media_type="text/html")


@app.get("/api/install-info")
def install_info(request: Request):
    host_header = request.headers.get("host") or ""
    port = host_header.rsplit(":", 1)[-1] if ":" in host_header else ""
    if not port.isdigit():
        port = "8173"
    ip = _lan_ip()
    return {
        "lan_url": f"http://{ip}:{port}/install",
        "app_url": f"http://{ip}:{port}/",
        "lan_ip": ip,
        "port": port,
        "downloads": _load_downloads(),
    }


@app.get("/api/qr")
def qr_code(text: str, size: int = 7):
    if not text or len(text) > 300:
        raise HTTPException(400, "缺少或过长的 text 参数")
    qr = qrcode.QRCode(box_size=max(2, min(size, 12)), border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1e1c19", back_color="#f7f3e9").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=300"})


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0：让同一 Wi-Fi 下的手机能通过局域网 IP 访问
    uvicorn.run(app, host="0.0.0.0", port=8173, log_level="info")
