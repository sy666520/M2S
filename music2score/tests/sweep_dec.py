"""在新的 f0 配置（weighted_argmax + 80x4 平均）上重调解码参数。

用法：
    py -3.10 tests/sweep_dec.py --model htdemucs_ft --stem vocals
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.segment import notes_from_frames, notes_from_viterbi, viterbi_quantize  # noqa: E402
from diag_stage import HOP_SEC, load_pv_midi, medfilt_voiced, rpa_midi  # noqa: E402
from sweep_f0 import get_f0, curve_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]

CFG = {"decoder": "weighted_argmax", "hop": 80, "avg": 4, "thr": 0.21}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    refs = {s: load_pv_midi(os.path.join(DATA, f"{s}.pv")) for s in songs}
    data = {}
    for s in songs:
        midi, conf = get_f0(s, args.model, args.stem, CFG)
        n = min(len(refs[s]), len(midi))
        data[s] = (refs[s][:n], midi[:n], conf[:n])

    print(f"解码参数扫描 | {args.model}/{args.stem} | f0=weighted_argmax/80x4\n")

    def run(label, fn):
        accs = []
        for s in songs:
            ref, midi, conf = data[s]
            n = len(ref)
            notes = fn(midi, conf, n)
            accs.append(rpa_midi(curve_of(notes, n), ref))
        print(f"  {label:<44} {np.mean(accs)*100:5.1f}%")
        return np.mean(accs)

    def v_run(midi, conf, n):
        q, _ = viterbi_quantize(midi, conf, sigma_cents=S, switch_penalty=P)
        return notes_from_viterbi(q[:n], np.arange(n) * HOP_SEC, conf)

    print("Viterbi (sigma, switch):")
    best = (None, 0)
    for S in (20.0, 25.0, 30.0, 40.0, 50.0, 60.0):
        for P in (1.0, 1.5, 2.0, 3.0, 4.5, 6.0):
            acc = run(f"sigma={S:<5} switch={P:<4}", v_run)
            if acc > best[1]:
                best = ((S, P), acc)
    print(f"  → 最优 Viterbi: sigma={best[0][0]} switch={best[0][1]}  {best[1]*100:.1f}%")

    print("\n基线对比：")
    def b_round(midi, conf, n):
        return notes_from_viterbi(np.round(midi), np.arange(n) * HOP_SEC, conf)
    run("直接取整 + notes_from_viterbi", b_round)

    def b_med(midi, conf, n):
        return notes_from_viterbi(np.round(medfilt_voiced(midi, 5)),
                                  np.arange(n) * HOP_SEC, conf)
    run("中值滤波5 + 取整", b_med)

    def b_frames(midi, conf, n):
        q = np.round(medfilt_voiced(midi, 5))
        return notes_from_frames(q, np.arange(n) * HOP_SEC, conf)
    run("中值滤波5 + 取整 + notes_from_frames", b_frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
