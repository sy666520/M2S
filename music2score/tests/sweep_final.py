"""40x8 f0 上的最终解码网格搜索。

用法：
    py -3.10 tests/sweep_final.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.segment import notes_from_viterbi, viterbi_quantize  # noqa: E402
from diag_stage import HOP_SEC, load_pv_midi, medfilt_voiced, rpa_midi  # noqa: E402
from sweep_f0 import get_f0, curve_of  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]

CFG = {"decoder": "weighted_argmax", "hop": 40, "avg": 8, "thr": 0.21}


def main():
    refs, data = {}, {}
    for s in ALL:
        refs[s] = load_pv_midi(os.path.join(DATA, f"{s}.pv"))
        midi, conf = get_f0(s, "htdemucs_ft", "vocals", CFG)
        n = min(len(refs[s]), len(midi))
        data[s] = (refs[s][:n], midi[:n], conf[:n])

    print("最终解码网格 | f0=warg 40x8 @ htdemucs_ft\n")

    def run(label, med, S, P, md, rf):
        accs = []
        for s in ALL:
            ref, midi, conf = data[s]
            n = len(ref)
            m = medfilt_voiced(midi, med) if med >= 3 else midi
            q, _ = viterbi_quantize(m, conf, sigma_cents=S, switch_penalty=P)
            q = q[:n]
            notes = notes_from_viterbi(q, np.arange(n) * HOP_SEC, conf,
                                       min_dur=md, rel_floor=rf)
            accs.append(rpa_midi(curve_of(notes, n), ref))
        acc = np.mean(accs)
        print(f"  med={med:<2} S={S:<4} P={P:<4} md={md:<5} rf={rf:<5} → {acc*100:5.1f}%")
        return acc

    best = (None, 0)
    for med in (3, 5, 7):
        for S in (18.0, 22.0, 26.0):
            for P in (4.0, 6.0, 8.0):
                acc = run("", med, S, P, 0.04, 0.1)
                if acc > best[1]:
                    best = ((med, S, P, 0.04, 0.1), acc)
    print(f"\n最优: med={best[0][0]} sigma={best[0][1]} switch={best[0][2]} "
          f"min_dur={best[0][3]}  {best[1]*100:.1f}%")

    # 对最优再做 min_dur/rel_floor 细扫
    med, S, P, _, _ = best[0]
    print("\nmin_dur / rel_floor 细扫：")
    for md in (0.03, 0.04, 0.05):
        for rf in (0.05, 0.1, 0.15):
            acc = run("", med, S, P, md, rf)
            if acc > best[1]:
                best = ((med, S, P, md, rf), acc)
    print(f"\n最终最优: {best[0]}  {best[1]*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
