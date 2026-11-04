"""切分参数网格搜索：音高曲线只算一次，之后只调切分逻辑。

用于在 MIR-1K 人声真值轨上找最优 (tol, min_dur, periodicity, 补洞) 组合。
"""
import argparse
import itertools
import os
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.transcribe.crepe import predict_f0  # noqa: E402
from backend.transcribe.segment import (harmonic_octave_fix, notes_from_frames,  # noqa: E402
                                        smooth_curve)
from eval_note import DATA, HOP_SEC, curve_of, load_pv, rpa  # noqa: E402

CACHE = os.path.join(DATA, "_f0cache")


def get_curve(song, stem="v", per=0.21):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{song}_{stem}_{per:.2f}.npz")
    if os.path.exists(path):
        d = np.load(path)
        return d["midi"], d["conf"], d["times"]
    y, sr = sf.read(os.path.join(DATA, f"{song}_{stem}.wav"), dtype="float32")
    if y.ndim > 1:
        y = y.mean(1)
    midi, conf, times = predict_f0(np.ascontiguousarray(y, dtype=np.float32), sr,
                                   periodicity_threshold=per)
    np.savez(path, midi=midi, conf=conf, times=times)
    return midi, conf, times


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", default="Ani_1_02,Ani_2_05,Kenshin_4_03,Kenshin_5_01")
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    refs, curves = {}, {}
    for s in songs:
        y, sr = sf.read(os.path.join(DATA, f"{s}_v.wav"), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        refs[s] = load_pv(os.path.join(DATA, f"{s}.pv"))
        curves[s] = get_curve(s, "v")
        print(f"曲线缓存 {s}: {len(curves[s][0])} 帧")

    import librosa
    onsets = {}
    for s in songs:
        y, sr = sf.read(os.path.join(DATA, f"{s}_v.wav"), dtype="float32")
        if y.ndim > 1:
            y = y.mean(1)
        onsets[s] = librosa.onset.onset_detect(y=np.ascontiguousarray(y, dtype=np.float32),
                                              sr=sr, hop_length=512, units="time",
                                              backtrack=True)

    grid = list(itertools.product([0.45, 0.55, 0.62, 0.75], [0.05, 0.08, 0.11],
                                  [3, 5], [0, 1]))
    rows = []
    for tol, min_dur, smooth, fill in grid:
        accs = []
        for s in songs:
            midi, conf, times = curves[s]
            m = smooth_curve(midi, smooth) if smooth else midi
            m = harmonic_octave_fix(m, conf)
            if fill:
                m = _fill_gaps(m, conf, gap=0.09)
            notes = notes_from_frames(m, times, conf, onsets[s], tol=tol,
                                      min_dur=min_dur, gap_merge=0.09)
            dur = len(refs[s]) * HOP_SEC
            acc, _ = rpa(curve_of(notes, dur), refs[s])
            accs.append(acc)
        rows.append((float(np.mean(accs)), tol, min_dur, smooth, fill))
    rows.sort(reverse=True)
    print("\n top 10:")
    for r in rows[:10]:
        print(f"   RPA {r[0]*100:5.2f}%  tol={r[1]} min_dur={r[2]} smooth={r[3]} fill={r[4]}")
    print(" 最差:", f"{rows[-1][0]*100:.2f}%")
    return 0


def _fill_gaps(m, conf, gap=0.09):
    """把短于 gap 秒的静音空洞补上（唱句内换气不应算作断句）。"""
    out = m.copy()
    n = len(out)
    i = 0
    while i < n:
        if np.isfinite(out[i]):
            i += 1
            continue
        j = i
        while j < n and not np.isfinite(out[j]):
            j += 1
        # i..j 是空洞
        if 0 < i and j < n and (j - i) * 0.02 <= gap:
            left = out[i - 1]
            right = out[j]
            if abs(left - right) <= 1.2:
                out[i:j] = 0.5 * (left + right)
        i = j
    return out


if __name__ == "__main__":
    sys.exit(main())
