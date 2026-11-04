"""音符级评测：在指定音频轨上比较不同识别引擎的音符准确率。

用法：
    py -3.10 tests/eval_note.py --engines pyin,crepe --stem v     # 人声真值轨（看切分+估计器）
    py -3.10 tests/eval_note.py --engines pyin,crepe,song --stem m # 完整混音（看端到端）
"""
import argparse
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.base import get_transcriber  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "real", "mir1k")
HOP_SEC = 0.02
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]


def load_pv(path):
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
    midi = np.asarray(vals, dtype=np.float64)
    return np.where(midi > 0, 440.0 * (2.0 ** ((midi - 69.0) / 12.0)), 0.0)


def curve_of(notes, duration):
    n_frames = int(round(duration / HOP_SEC))
    curve = np.zeros(n_frames, dtype=np.float64)
    for n in notes:
        t0 = n.start
        t1 = t0 + n.duration
        f = 440.0 * (2.0 ** ((n.midi - 69) / 12.0))
        i0 = max(0, int(round(t0 / HOP_SEC)))
        i1 = min(n_frames, int(round(t1 / HOP_SEC)))
        if i1 > i0:
            curve[i0:i1] = f
    return curve


def rpa(est, ref, cents=50.0):
    m = min(len(est), len(ref))
    est, ref = est[:m], ref[:m]
    voiced = ref > 0
    nv = int(voiced.sum())
    if nv == 0:
        return 0.0, 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        diff = 1200.0 * np.log2(np.where(est > 0, est, np.nan) / ref)
    valid = voiced & np.isfinite(diff)
    ok = valid & (np.abs(diff) <= cents)
    octd = np.where(valid, ((diff + 600) % 1200) - 600, np.inf)
    return float(ok.sum() / nv), float((ok | (valid & (np.abs(octd) <= cents))).sum() / nv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", default="pyin,crepe")
    ap.add_argument("--stem", default="v", choices=["v", "m"])
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]
    engines = [e for e in args.engines.split(",") if e]

    print(f"音符级评测 | 素材: MIR-1K {'人声真值轨' if args.stem == 'v' else '完整混音'}"
          f" | {len(songs)} 首\n")
    summary = {e: [] for e in engines}
    for song in songs:
        y, sr = sf.read(os.path.join(DATA, f"{song}_{args.stem}.wav"),
                        dtype="float32", always_2d=False)
        if getattr(y, "ndim", 1) > 1:
            y = y.mean(axis=1)
        y = np.ascontiguousarray(y, dtype=np.float32)
        ref = load_pv(os.path.join(DATA, f"{song}.pv"))
        duration = len(ref) * HOP_SEC
        line = f"{song:<14}"
        for e in engines:
            t = time.time()
            notes = get_transcriber(e).transcribe(y, sr)
            acc, acc_oct = rpa(curve_of(notes, duration), ref)
            summary[e].append(acc)
            line += f" | {e} {acc*100:5.1f}% ({time.time()-t:4.1f}s, {len(notes):>3}音)"
        print(line)

    print()
    for e in engines:
        print(f"  {e:<8} 平均 RPA {np.mean(summary[e])*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
