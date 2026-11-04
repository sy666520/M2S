"""真实流行歌曲测试。

两个子集，回答两个不同的问题：

A 全混音流行歌（人声 + 伴奏 + 鼓）
    -> 端到端能不能出谱、出什么谱、结构指标是否合理
    没有逐帧真值，所以量化的是「谱面结构合理性」与「对人声轨的忠实度」

B 真实独唱（Vocadito，40 段真人演唱，含 f0 标注）
    -> 识别前端在真实人声上的 RPA（±50 音分）

用法：
    py -3.10 tests/eval_pop.py --pop E:/tmp/pop90.wav --vocadito E:/tmp/vocadito
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backend.transcribe.song as song_mod                  # noqa: E402
from backend.audio import load_audio                        # noqa: E402
from backend.pipeline import transcribe_audio               # noqa: E402
from backend.transcribe.base import REGISTRY                # noqa: E402
from backend.transcribe.crepe import predict_f0             # noqa: E402
from backend.transcribe.song import pick_melody_stem        # noqa: E402

MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)


# ---------------------------------------------------------------- A 全混音

def pop_metrics(score, notes_sec, vocal_midi, vocal_conf, frame_times):
    """结构指标 + 对人声轨的忠实度。"""
    durs = [n.duration for n in notes_sec]
    n = len(notes_sec)
    dur_total = score.source_duration

    # 短音比例：<100ms 的多半是颤音/噪声误检
    short = sum(1 for d in durs if d < 0.10) / n

    # 调内音比例
    steps = MAJOR_STEPS if score.key.mode == "major" else MINOR_STEPS
    in_key = sum(1 for x in notes_sec if (x.midi - score.key.tonic_pc) % 12 in steps) / n

    # 八度跳变：相邻音符恰好差 ±12 半音（真实旋律里很少连续出现）
    srt = sorted(notes_sec, key=lambda x: x.start)
    oct_jumps = sum(1 for a, b in zip(srt, srt[1:]) if abs(b.midi - a.midi) == 12)
    oct_rate = oct_jumps / max(1, len(srt) - 1)

    # 音域
    pitches = [x.midi for x in notes_sec]
    span = max(pitches) - min(pitches)

    # 对人声轨的忠实度：浊音帧被音符覆盖的比例、音符内音高偏差
    voiced = (vocal_conf >= 0.21) & ~np.isnan(vocal_midi)
    if voiced.any():
        cov = np.zeros(int(voiced.sum()), dtype=bool)
        vt = frame_times[voiced]
        for x in srt:
            cov |= (vt >= x.start) & (vt < x.start + x.duration)
        coverage = float(cov.mean())
    else:
        coverage = float("nan")

    devs = []
    for x in srt:
        m = (frame_times >= x.start) & (frame_times < x.start + x.duration) & voiced
        if m.sum() >= 3:
            devs.append((float(np.median(vocal_midi[m])) - x.midi) * 100.0)
    devs = np.abs(np.array(devs)) if devs else np.array([np.nan])

    return {
        "notes": n,
        "notes_per_sec": round(n / dur_total, 2),
        "short_ratio": round(short, 3),
        "in_key_ratio": round(in_key, 3),
        "octave_jump_rate": round(oct_rate, 3),
        "pitch_span_semitones": span,
        "coverage_of_voiced": round(coverage, 3),
        "note_pitch_dev_median_cents": round(float(np.nanmedian(devs)), 1),
        "note_pitch_dev_p90_cents": round(float(np.nanpercentile(devs, 90)), 1),
    }


def run_pop(path, engine):
    print(f"\n{'='*64}\nA 全混音流行歌：{os.path.basename(path)}  [{engine}]\n{'='*64}")
    y, sr = load_audio(path, sr=44100)
    print(f"时长 {len(y)/sr:.1f}s  采样率 {sr}")

    # 指定引擎：song 识别器的模型 / 内部识别器可配置，这里按 "模型+识别器" 注入
    # 不带 "+" 表示「不做分离，直接识别混音」（基线）
    sep_engine = "+" in engine
    model, inner = (engine.split("+") + [""])[:2] if sep_engine else ("", engine)
    song_cls = REGISTRY["song"]
    if sep_engine:
        REGISTRY["song"] = lambda: song_cls(model=model, inner=inner)

    # 监听一次分离结果，避免为了算指标再跑一遍 demucs
    captured = {}
    orig_sep = song_mod.separate_stems

    def spy(y_, sr_, *a, **kw):
        stems = orig_sep(y_, sr_, *a, **kw)
        captured.update(stems=stems, sr=sr_, mix=y_)
        return stems

    if sep_engine:
        song_mod.separate_stems = spy
    t0 = time.time()
    try:
        score = transcribe_audio(path, transcriber_name="song" if sep_engine else engine)
    finally:
        song_mod.separate_stems = orig_sep
        REGISTRY["song"] = song_cls
    elapsed = time.time() - t0
    print(f"出谱耗时 {elapsed:.1f}s（{elapsed/(len(y)/sr):.2f}× 实时）")
    print(f"音符 {len(score.notes)}  速度 {score.tempo} BPM  "
          f"拍号 {score.meter[0]}/{score.meter[1]}  调性 {score.key.name}")

    # 基线跑法没有分离，指标需要一条人声轨作为参照
    if not sep_engine:
        captured.update(stems=orig_sep(y, sr, model="htdemucs_ft"), sr=sr, mix=y)

    # 用分离出的人声轨逐帧音高，衡量「音符化」阶段是否忠实于人声
    name, track = pick_melody_stem(captured["stems"], captured["mix"])
    vm, vc, vt = predict_f0(track, captured["sr"])
    print(f"主旋律轨：{name}")

    spb = 60.0 / score.tempo
    notes_sec = [type("N", (), {"midi": q.midi, "start": q.beat * spb,
                                "duration": q.dur * spb}) for q in score.notes]
    m = pop_metrics(score, notes_sec, vm, vc, vt)
    print("\n结构指标")
    print(f"  音符密度        {m['notes_per_sec']:>7} 音/秒")
    print(f"  短音比例(<100ms){m['short_ratio']*100:>7.1f}%")
    print(f"  调内音比例      {m['in_key_ratio']*100:>7.1f}%")
    print(f"  八度跳变率      {m['octave_jump_rate']*100:>7.1f}%")
    print(f"  音域跨度        {m['pitch_span_semitones']:>7} 半音")
    print(f"  人声浊音覆盖率  {m['coverage_of_voiced']*100:>7.1f}%")
    print(f"  音符音高偏差    {m['note_pitch_dev_median_cents']:>7.1f} 音分（中位）"
          f" / {m['note_pitch_dev_p90_cents']:.0f} 音分（P90）")
    return {"file": os.path.basename(path), "engine": engine, "seconds": round(elapsed, 1),
            "tempo": score.tempo, "meter": list(score.meter), "key": score.key.name,
            "metrics": m, "score": score}


# ---------------------------------------------------------------- B 独唱 RPA

def run_vocadito(root):
    print(f"\n{'='*64}\nB 真实独唱（Vocadito）：{root}\n{'='*64}")
    wavs = sorted(glob.glob(os.path.join(root, "Audio", "*.wav")))
    rpas, meds, octs = [], [], []
    rows = []
    t0 = time.time()
    for w in wavs:
        name = os.path.splitext(os.path.basename(w))[0]
        gt_path = os.path.join(root, "Annotations", "F0", f"{name}_f0.csv")
        if not os.path.exists(gt_path):
            continue
        gt = np.loadtxt(gt_path, delimiter=",")
        gt_t, gt_f0 = gt[:, 0], gt[:, 1]

        y, sr = load_audio(w, sr=22050)
        est, conf, times = predict_f0(y, sr)

        # 把真值插值到估计帧上；真值 0 表示无声
        gt_on_est = np.interp(times, gt_t, gt_f0, left=0.0, right=0.0)
        mask = (gt_on_est > 0) & (conf >= 0.21) & ~np.isnan(est)
        if mask.sum() < 50:
            continue
        gt_midi = 69 + 12 * np.log2(gt_on_est[mask] / 440.0)
        err = np.abs(est[mask] - gt_midi) * 100.0
        rpa = float((err <= 50).mean())
        med = float(np.median(err))
        oct_err = float(((err >= 1150) & (err <= 1250)).mean())
        rpas.append(rpa); meds.append(med); octs.append(oct_err)
        rows.append({"id": name, "rpa": round(rpa, 4), "median_cents": round(med, 1)})

    print(f"{len(rpas)} 段，用时 {time.time()-t0:.0f}s")
    print(f"  RPA(±50音分)  {np.mean(rpas)*100:.1f}%   "
          f"中位误差 {np.median(meds):.1f} 音分   "
          f"八度错误率 {np.mean(octs)*100:.1f}%")
    worst = sorted(rows, key=lambda r: r["rpa"])[:3]
    print("  最差三段：" + "，".join(f"{r['id']} {r['rpa']*100:.0f}%" for r in worst))
    return {"clips": len(rpas), "rpa": round(float(np.mean(rpas)), 4),
            "median_cents": round(float(np.median(meds)), 1),
            "octave_error_rate": round(float(np.mean(octs)), 4), "rows": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", default="", help="全混音流行歌音频路径")
    ap.add_argument("--vocadito", default="", help="Vocadito 数据集根目录")
    ap.add_argument("--engines", default="htdemucs_ft+crepe",
                    help="逗号分隔；不带 + 表示不分离直接识别混音（基线）")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    report = {}
    if args.pop:
        report["pop"] = [run_pop(args.pop, e.strip())
                         for e in args.engines.split(",") if e.strip()]
    if args.vocadito:
        report["vocadito"] = run_vocadito(args.vocadito)

    if args.out:
        payload = json.loads(json.dumps(report, default=str))
        for item in payload.get("pop", []):
            item.pop("score", None)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"\n报告已写入 {args.out}")


if __name__ == "__main__":
    main()
