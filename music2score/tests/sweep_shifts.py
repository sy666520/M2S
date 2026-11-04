"""在最差的几首歌上试 demucs shifts=2（测试时增强，分离质量更高）。

用法：
    py -3.10 tests/sweep_shifts.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.audio import load_audio  # noqa: E402
from backend.transcribe.crepe import predict_f0 as legacy  # noqa: F401,E402
from backend.transcribe.segment import notes_from_viterbi, viterbi_quantize  # noqa: E402
from backend.transcribe.song import separate_stems  # noqa: E402
from diag_stage import HOP_SEC, load_pv_midi, medfilt_voiced, rpa_midi  # noqa: E402
from sweep_f0 import curve_of, predict_f0  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
SONGS = ["Ani_5_08", "Ani_1_03", "Kenshin_3_01"]
CFG = {"decoder": "weighted_argmax", "hop": 40, "avg": 8, "thr": 0.21}


def chain(track, sr, ref):
    midi, conf = predict_f0(track, sr, **CFG)
    n = min(len(ref), len(midi))
    ref, midi, conf = ref[:n], midi[:n], conf[:n]
    m = medfilt_voiced(midi, 3)
    q, _ = viterbi_quantize(m, conf, sigma_cents=18.0, switch_penalty=4.0)
    q = q[:n]
    notes = notes_from_viterbi(q, np.arange(n) * HOP_SEC, conf, min_dur=0.04)
    return rpa_midi(m, ref), rpa_midi(curve_of(notes, n), ref)


def main():
    print("demucs shifts=2 试验 | 3 首最差歌\n")
    for s in SONGS:
        ref = load_pv_midi(os.path.join(DATA, f"{s}.pv"))
        y, sr = load_audio(os.path.join(DATA, f"{s}_m.wav"), sr=22050)

        z = np.load(os.path.join(ROOT, "data", "real", "mir1k", "_stems", f"{s}_htdemucs_ft.npz"))
        raw1, note1 = chain(z["vocals"], int(z["sr"]), ref)

        stems = separate_stems(y, sr, model="htdemucs_ft", shifts=2)
        track = stems["vocals"]
        peak = float(np.max(np.abs(track))) if track.size else 0.0
        if peak > 1e-6:
            track = (track / peak * 0.9).astype(np.float32)
        raw2, note2 = chain(track, sr, ref)
        print(f"  {s:<14} shifts=1: {note1*100:5.1f}%   shifts=2: {note2*100:5.1f}%"
              f"   (原始 {raw1*100:.0f}% → {raw2*100:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
