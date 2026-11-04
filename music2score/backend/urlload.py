"""从视频 / 音频链接导入音源。

两种取音方式，按站点自动选择：

1. **yt-dlp**：B 站、YouTube、快手、西瓜、微博、网易云，以及任意音频直链。
   纯解析 + HTTP 下载，速度快。
2. **浏览器兜底**：抖音（douyin.com / v.douyin.com）对没有浏览器指纹的请求一律
   返回 403 或要求 Cookie，因此用 Playwright 打开真实页面，等 <video> 元素拿到
   CDN 直链后再下载。需要：
       pip install playwright
       playwright install chromium

取到音源后统一转成 44.1k 单声道 WAV 交给流水线。**转谱本身仍然全在本地完成**，
音频不会上传到任何第三方服务；这里联网只是为了把用户指定的视频取下来。

安全约束：只接受 http/https 公网地址（拒绝内网/回环，避免本机被当成任意下载器），
并限制体积与时长。
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from .audio import ffmpeg_path

MAX_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 20 * 60

# 站点 -> 展示名。命中不了就用域名本身，yt-dlp 的 generic 提取器仍会尝试。
PLATFORMS = [
    ("douyin.com", "抖音"),
    ("iesdouyin.com", "抖音"),
    ("bilibili.com", "B站"),
    ("b23.tv", "B站"),
    ("youtube.com", "YouTube"),
    ("youtu.be", "YouTube"),
    ("kuaishou.com", "快手"),
    ("ixigua.com", "西瓜视频"),
    ("xiaohongshu.com", "小红书"),
    ("xhslink.com", "小红书"),
    ("weibo.com", "微博"),
    ("weibo.cn", "微博"),
    ("music.163.com", "网易云音乐"),
    ("y.qq.com", "QQ音乐"),
]

_DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")

# 分享文案里常混着中文说明，只抠第一个 URL
_URL_RE = re.compile(r"https?://[^\s<>\"'，。、；：！？）】」』]+", re.I)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

Progress = Optional[Callable[[float, str], None]]


class FetchError(Exception):
    """下载失败，message 直接展示给用户。"""


# ---------------------------------------------------------------- URL 处理

def extract_url(text: str) -> str:
    """从用户粘贴的内容里取出链接（抖音分享文案通常带一堆说明文字）。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("请先粘贴视频链接")
    m = _URL_RE.search(text)
    if not m:
        raise ValueError("没有找到有效链接，请粘贴以 http:// 或 https:// 开头的地址")
    return m.group(0).rstrip(".,;)]}'~")


def platform_label(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for suffix, name in PLATFORMS:
        if host == suffix or host.endswith("." + suffix):
            return name
    return host or "链接"


def is_douyin(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _DOUYIN_HOSTS)


def ensure_public(url: str) -> None:
    """只允许公网 http(s)，防止把本机当成内网探测器。"""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError("只支持 http / https 链接")
    host = p.hostname
    if not host:
        raise ValueError("链接里没有域名")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValueError(f"域名无法解析：{host}")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError("不支持内网 / 本机地址")


def browser_ready() -> bool:
    """抖音兜底需要 Playwright + Chromium。"""
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    return True


def cookie_file() -> Optional[str]:
    """可选：项目 data/cookies.txt（Netscape 格式），给需要登录的站点用。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "data", "cookies.txt")
    return path if os.path.exists(path) else None


def public_config() -> dict:
    names: list = []
    for _, n in PLATFORMS:
        if n not in names:
            names.append(n)
    return {
        "enabled": True,
        "browser": browser_ready(),
        "platforms": names,
        "max_seconds": MAX_SECONDS,
        "max_mb": MAX_BYTES // (1024 * 1024),
    }


# ---------------------------------------------------------------- 主入口

def fetch_audio(url: str, dest_dir: str, progress: Progress = None) -> dict:
    """下载并转成 WAV。返回 {path, title, duration, platform, method}。"""
    def emit(v: float, msg: str) -> None:
        if progress:
            progress(max(0.0, min(1.0, v)), msg)

    clean = extract_url(url)
    ensure_public(clean)
    platform = platform_label(clean)
    os.makedirs(dest_dir, exist_ok=True)

    emit(0.02, f"解析{platform}链接…")

    # 抖音直接走浏览器：yt-dlp 现在必须带新鲜 Cookie，成功率低且报错晦涩
    if is_douyin(clean):
        if not browser_ready():
            raise FetchError("抖音链接需要浏览器组件：pip install playwright && "
                             "playwright install chromium")
        result = _via_browser(clean, dest_dir, emit, platform)
    else:
        try:
            result = _via_ytdlp(clean, dest_dir, emit, platform)
        except FetchError as e:
            # 站点被 yt-dlp 卡住时再试浏览器（对普通网页播放器有效）
            if not browser_ready():
                raise e
            emit(0.02, "常规解析失败，改用浏览器…")
            try:
                result = _via_browser(clean, dest_dir, emit, platform)
            except Exception:
                raise e

    wav = _to_wav(result["path"], dest_dir, emit)
    result["path"] = wav
    emit(1.0, "音源就绪")
    return result


# ---------------------------------------------------------------- yt-dlp

def _via_ytdlp(url: str, dest_dir: str, emit: Callable, platform: str) -> dict:
    try:
        import yt_dlp
    except ImportError:
        raise FetchError("未安装 yt-dlp：pip install yt-dlp")

    def hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            if total:
                emit(0.05 + 0.75 * min(1.0, got / total),
                     f"下载音频 {int(got * 100 / max(total, 1))}%")
        elif status == "finished":
            emit(0.85, "下载完成，转换中…")

    exe = ffmpeg_path()
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(dest_dir, "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "socket_timeout": 25,
        "retries": 2,
        "max_filesize": MAX_BYTES,
        "progress_hooks": [hook],
    }
    if exe:
        opts["ffmpeg_location"] = os.path.dirname(exe)
    cf = cookie_file()
    if cf:
        opts["cookiefile"] = cf

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and info.get("entries"):
                info = next((e for e in info["entries"] if e), {}) or {}
            path = ydl.prepare_filename(info) if info else ""
    except Exception as e:  # yt-dlp 的异常类型很杂，统一转成人话
        raise FetchError(_humanize(e, platform))

    if not path or not os.path.exists(path):
        cands = [os.path.join(dest_dir, f) for f in os.listdir(dest_dir)
                 if f.startswith("source.")]
        if not cands:
            raise FetchError(f"{platform}没有返回可下载的音频")
        path = max(cands, key=os.path.getsize)

    size = os.path.getsize(path)
    if size == 0:
        raise FetchError("下载到的文件是空的，换一个链接试试")
    if size > MAX_BYTES:
        os.remove(path)
        raise FetchError(f"音频超过 {MAX_BYTES // (1024 * 1024)}MB 上限")

    duration = float(info.get("duration") or 0) if info else 0.0
    if duration and duration > MAX_SECONDS:
        raise FetchError(f"视频长 {duration / 60:.0f} 分钟，超过 "
                         f"{MAX_SECONDS // 60} 分钟上限，请剪短后再试")

    return {
        "path": path,
        "title": _clean_title(info.get("title") if info else ""),
        "duration": round(duration, 1),
        "platform": platform,
        "method": "yt-dlp",
    }


def _humanize(err: Exception, platform: str) -> str:
    msg = str(err)
    low = msg.lower()
    if "cookies" in low or "login" in low or "sign in" in low:
        return (f"{platform}要求登录凭据。可在项目 data/cookies.txt 放一份 "
                f"Netscape 格式的 cookies 后重试（浏览器插件「Get cookies.txt」可导出）")
    if "private" in low or "unavailable" in low or "removed" in low:
        return f"这个{platform}视频不可访问（已删除 / 私密 / 地区限制）"
    if "unsupported url" in low:
        return f"暂不支持这个链接：{msg[:120]}"
    if "timed out" in low or "timeout" in low:
        return "连接超时，检查网络后重试"
    return f"{platform}提取失败：{msg[:200]}"


# ---------------------------------------------------------------- 浏览器兜底

def _via_browser(url: str, dest_dir: str, emit: Callable, platform: str) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise FetchError("缺少浏览器组件：pip install playwright && playwright install chromium")

    emit(0.15, f"打开{platform}页面…")
    page_title = ""
    duration = 0.0
    body = b""

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--mute-audio", "--autoplay-policy=no-user-gesture-required"])
        try:
            ctx = browser.new_context(user_agent=_UA, locale="zh-CN",
                                      viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            captured: list = []
            page.on("response", lambda r: captured.append(r.url)
                    if "video/mp4" in (r.headers or {}).get("content-type", "") else None)

            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("video", timeout=25000)
            emit(0.45, "读取视频流…")

            picked = _pick_video(page)
            src = picked["src"] if picked else ""
            duration = float(picked["dur"]) if picked else 0.0
            # 抖音的标题是脚本后填的，等视频元素出来后再读才有值
            page_title = page.title()
            if not page_title.strip():
                page.wait_for_timeout(1200)
                page_title = page.title()

            if not src:
                # 有些站点用 MSE，<video> 只有 blob:，退而取抓到的最长 mp4 直链
                cand = [u for u in captured if "video/tos" in u or u.endswith(".mp4")]
                src = cand[-1] if cand else ""
            if not src:
                raise FetchError("页面里没有找到可下载的视频流，换个链接试试")
            if duration > MAX_SECONDS:
                raise FetchError(f"视频长 {duration / 60:.0f} 分钟，超过 "
                                 f"{MAX_SECONDS // 60} 分钟上限")

            emit(0.7, "下载音频…")
            resp = ctx.request.get(src, headers={"Referer": url, "Range": "bytes=0-"},
                                   timeout=180000)
            if resp.status >= 400:
                raise FetchError(f"视频流下载失败（HTTP {resp.status}）")
            body = resp.body()
            emit(0.95, "转换音轨…")
        finally:
            browser.close()

    if not body:
        raise FetchError("下载到的内容是空的，换一个链接试试")
    if len(body) > MAX_BYTES:
        raise FetchError(f"视频超过 {MAX_BYTES // (1024 * 1024)}MB 上限")

    path = os.path.join(dest_dir, "source.mp4")
    with open(path, "wb") as f:
        f.write(body)

    return {
        "path": path,
        "title": _clean_title(page_title),
        "duration": round(duration, 1),
        "platform": platform,
        "method": "browser",
    }


def _pick_video(page) -> Optional[dict]:
    """挑时长最长、且不是 blob: 的那个 video（抖音页里有个预览小视频）。"""
    deadline = time.time() + 20
    while time.time() < deadline:
        vids = page.evaluate(
            """() => Array.from(document.querySelectorAll('video')).map(v => ({
                   src: v.currentSrc || v.src || '',
                   dur: Number.isFinite(v.duration) ? v.duration : 0 }))""")
        good = [v for v in vids
                if v.get("src") and not v["src"].startswith("blob:") and v.get("dur", 0) > 0]
        if good:
            return max(good, key=lambda v: v["dur"])
        page.wait_for_timeout(500)
    return None


# ---------------------------------------------------------------- 转码

def _to_wav(src: str, dest_dir: str, emit: Callable) -> str:
    if os.path.splitext(src)[1].lower() == ".wav":
        return src
    exe = ffmpeg_path()
    if not exe:
        raise FetchError("缺少 ffmpeg，无法把视频里的音轨抽出来（pip install imageio-ffmpeg）")

    out = os.path.join(dest_dir, "source.wav")
    cmd = [exe, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "44100",
           "-loglevel", "error", out]
    try:
        subprocess.run(cmd, check=True, timeout=300,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "ignore")[:200]
        raise FetchError(f"音轨转换失败：{detail or '文件可能没有音轨'}")
    except subprocess.TimeoutExpired:
        raise FetchError("音轨转换超时")
    return out


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    title = re.sub(r"\s*[-–—_|]\s*(抖音|哔哩哔哩|bilibili|YouTube|快手).*$", "",
                   title, flags=re.I)
    title = re.sub(r"\s*#\S+", "", title).strip()
    return title[:80]
