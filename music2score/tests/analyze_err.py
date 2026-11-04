"""误差拆解：把 RPA 的损失归因到「漏检/八度/半音」，定位优化方向。

用法：
    py -3.10 tests/analyze_err.py --model htdemucs_ft --stem vocals
"""
import argparse
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.crepe import predict_f0  # noqa: E402
from backend.transcribe.segment import harmonic_octave_fix, viterbi_quantize  # noqa: E402

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


def cents_err(est_midi, ref_midi):
    """真值文件存的是 MIDI 音高号（不是 Hz），误差直接按半音差换算音分。"""
    return 100.0 * (est_midi - ref_midi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--thr", type=float, default=0.21)
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    rows = []
    print(f"误差拆解 | {args.model}/{args.stem} | thr={args.thr}\n")
    print(f"{'歌曲':<14}{'真值浊音':>8}{'检出率':>8}{'≤50¢':>8}{'半音错':>8}"
          f"{'八度错':>8}{'其他错':>8}{'RPA':>8}{'上限':>8}")
    for s in songs:
        z = np.load(os.path.join(CACHE, f"{s}_{args.model}.npz"))
        track = z[args.stem]
        sr = int(z["sr"])
        dur = track.size / sr
        ref = load_pv_midi(os.path.join(DATA, f"{s}.pv"))
        n_ref = len(ref)

        midi_f, conf, times = predict_f0(track, sr, periodicity_threshold=args.thr)
        # 真值帧移也是 20ms，逐帧直接对齐
        n = min(n_ref, len(midi_f))
        ref = ref[:n]
        est = midi_f[:n]

        ref_v = ref > 0
        est_v = np.isfinite(est)
        nv = int(ref_v.sum())
        if nv == 0:
            continue
        both = ref_v & est_v
        d = np.where(both, cents_err(est, ref), np.nan)
        ok = np.nansum(np.abs(d) <= 50)
        semi = np.nansum((np.abs(d) > 50) & (np.abs(d) <= 600))
        oct_ = np.nansum((np.abs(d) > 600) & (np.abs(d) <= 1800))
        other = np.nansum(np.abs(d) > 1800)
        recall = float(est_v[ref_v].sum() / nv)
        # 「上限」：把真值浊音区间的估计全部计入（漏检也算，看估计质量本身）
        rpa = ok / nv
        rows.append((recall, ok / nv, semi / nv, oct_ / nv, other / nv, rpa))
        print(f"{s:<14}{nv:>8}{recall*100:>7.1f}%{ok/nv*100:>7.1f}%{semi/nv*100:>7.1f}%"
              f"{oct_/nv*100:>7.1f}%{other/nv*100:>7.1f}%{rpa*100:>7.1f}%")

    a = np.mean(np.array(rows), axis=0)
    print(f"\n{'平均':<14}{'':>8}{a[0]*100:>7.1f}%{a[1]*100:>7.1f}%{a[2]*100:>7.1f}%"
          f"{a[3]*100:>7.1f}%{a[4]*100:>7.1f}%{a[5]*100:>7.1f}%")
    print("\n注：「检出率」=真值浊音帧中被我们判为浊音的比例；"
          "半音错=|误差| 50~600¢；八度错 600~1800¢。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
