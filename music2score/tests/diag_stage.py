"""逐阶段测 RPA：定位「帧→音符」解码环节的损失。

A 原始 f0 → B 八度纠正 → C Viterbi 量化（帧级）→ D 成音符（重建曲线）
用法：
    py -3.10 tests/diag_stage.py --model htdemucs_ft --stem vocals
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.crepe import predict_f0  # noqa: E402
from backend.transcribe.segment import (harmonic_octave_fix, notes_from_viterbi,  # noqa: E402
                                        split_notes_at_onsets, viterbi_quantize)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
CACHE = os.path.join(DATA, "_stems")
HOP_SEC = 0.02
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]


def load_pv_midi(path):
    vals = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                vals.append(float(line.split()[0]))
            except ValueError:
                vals.append(0.0)
    return np.asarray(vals, dtype=np.float64)


def rpa_midi(est, ref, cents=50.0):
    """est 为浮点 MIDI（非浊音 NaN），ref 为 MIDI（0 表示静音）。"""
    n = min(len(est), len(ref))
    est, ref = est[:n], ref[:n]
    voiced = ref > 0
    nv = int(voiced.sum())
    if nv == 0:
        return 0.0
    d = 100.0 * (est - ref)
    valid = voiced & np.isfinite(d)
    return float((valid & (np.abs(d) <= cents)).sum() / nv)


def curve_of(notes, n_frames):
    curve = np.full(n_frames, np.nan)
    for n in notes:
        i0 = max(0, int(round(n.start / HOP_SEC)))
        i1 = min(n_frames, int(round((n.start + n.duration) / HOP_SEC)))
        if i1 > i0:
            curve[i0:i1] = float(n.midi)
    return curve


def medfilt_voiced(midi_f, k=5):
    """只在中值窗内取浊音帧的中位数，避免静音把浊音帧带成 NaN。"""
    if k < 3:
        return midi_f
    out = midi_f.copy()
    half = k // 2
    for i in range(len(midi_f)):
        if not np.isfinite(midi_f[i]):
            continue
        seg = midi_f[max(0, i - half): i + half + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size:
            out[i] = float(np.median(seg))
    return out


def f0_cache_path(model, stem, song):
    """缓存键带版本号：f0 提取方案一改，旧缓存就会失效而不是被误用。"""
    d = os.path.join(CACHE, "f0")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"v2_{song}_{model}_{stem}.npz")


def get_f0(song, model, stem, thr):
    p = f0_cache_path(model, stem, song)
    if os.path.exists(p):
        z = np.load(p)
        return z["midi_f"], z["conf"]
    z = np.load(os.path.join(CACHE, f"{song}_{model}.npz"))
    track, sr = z[stem], int(z["sr"])
    midi_f, conf, _ = predict_f0(track, sr, periodicity_threshold=thr)
    np.savez_compressed(p, midi_f=midi_f, conf=conf)
    return midi_f, conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--thr", type=float, default=0.21)
    ap.add_argument("--sigma", type=float, default=30.0)
    ap.add_argument("--switch", type=float, default=3.0)
    ap.add_argument("--min-dur", type=float, default=0.05)
    ap.add_argument("--rel-floor", type=float, default=0.12)
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    print(f"逐阶段 RPA | {args.model}/{args.stem} | thr={args.thr} "
          f"sigma={args.sigma} switch={args.switch}\n")
    print(f"{'歌曲':<14}{'A原始':>8}{'A0取整':>8}{'A1中值':>8}{'CViterbi':>9}"
          f"{'救回':>7}{'弄坏':>7}{'D音符':>8}")
    acc = [[] for _ in range(7)]
    for s in songs:
        ref = load_pv_midi(os.path.join(DATA, f"{s}.pv"))
        midi_f, conf = get_f0(s, args.model, args.stem, args.thr)
        n = min(len(ref), len(midi_f))
        ref = ref[:n]
        midi_f, conf = midi_f[:n], conf[:n]
        a = rpa_midi(midi_f, ref)

        fixed = harmonic_octave_fix(midi_f, conf)
        b = rpa_midi(fixed, ref)

        # A0：逐帧直接取整（完全不做时序平滑）——衡量「取整」本身的代价
        snap = np.round(np.where(np.isfinite(fixed), fixed, np.nan))
        b0 = rpa_midi(snap, ref)

        # A1：5 帧中值滤波后取整——衡量简单平滑的效果
        med = medfilt_voiced(fixed, 5)
        b1 = rpa_midi(np.round(med), ref)

        quant, _ = viterbi_quantize(fixed, conf, sigma_cents=args.sigma,
                                    switch_penalty=args.switch)
        quant = quant[:n]
        c = rpa_midi(quant, ref)

        # Viterbi 相对原始 f0 到底救了多少、又弄坏了多少
        ea = np.abs(100.0 * (midi_f - ref)) <= 50.0
        ec = np.abs(100.0 * (quant - ref)) <= 50.0
        vv = ref > 0
        gain = float((vv & ec & ~ea).sum() / max(int(vv.sum()), 1))
        loss = float((vv & ~ec & ea).sum() / max(int(vv.sum()), 1))

        notes = notes_from_viterbi(quant, np.arange(len(quant)) * HOP_SEC, conf,
                                   min_dur=args.min_dur, rel_floor=args.rel_floor)
        d = rpa_midi(curve_of(notes, n), ref)

        import librosa
        z = np.load(os.path.join(CACHE, f"{s}_{args.model}.npz"))
        try:
            ons = librosa.onset.onset_detect(y=z[args.stem], sr=int(z["sr"]),
                                             hop_length=512, units="time",
                                             backtrack=True, delta=0.06, wait=2)
        except Exception:
            ons = np.empty(0)
        e = rpa_midi(curve_of(split_notes_at_onsets(notes, ons), n), ref)

        for k, v in enumerate([a, b0, b1, c, gain, loss, d]):
            acc[k].append(v)
        print(f"{s:<14}{a*100:>7.1f}%{b0*100:>7.1f}%{b1*100:>7.1f}%{c*100:>8.1f}%"
              f"{gain*100:>6.1f}%{loss*100:>6.1f}%{d*100:>7.1f}%")

    m = [np.mean(x) for x in acc]
    print(f"\n{'平均':<14}{m[0]*100:>7.1f}%{m[1]*100:>7.1f}%{m[2]*100:>7.1f}%"
          f"{m[3]*100:>8.1f}%{m[4]*100:>6.1f}%{m[5]*100:>6.1f}%{m[6]*100:>7.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
