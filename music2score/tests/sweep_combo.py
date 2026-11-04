"""组合扫描：平滑 × 解码 × 音符成形参数，并诊断覆盖率（空隙损失）。

用法：
    py -3.10 tests/sweep_combo.py --model htdemucs_ft --stem vocals
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.segment import (notes_from_viterbi,  # noqa: E402
                                        viterbi_quantize)
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

    print(f"组合扫描 | {args.model}/{args.stem} | f0=weighted_argmax/80x4\n")

    def run(label, fn, show_cov=False):
        accs, covs = [], []
        for s in songs:
            ref, midi, conf = data[s]
            n = len(ref)
            notes = fn(midi, conf, n)
            cur = curve_of(notes, n)
            accs.append(rpa_midi(cur, ref))
            voiced_ref = ref > 0
            cov = np.mean(np.isfinite(cur[voiced_ref]))
            covs.append(cov)
        acc, cov = np.mean(accs), np.mean(covs)
        tail = f"  覆盖 {cov*100:5.1f}%" if show_cov else ""
        print(f"  {label:<52} {acc*100:5.1f}%{tail}")
        return acc

    def mk(med, use_vit, S=20.0, P=6.0, min_dur=0.05, rel_floor=0.12):
        def f(midi, conf, n):
            m = medfilt_voiced(midi, med) if med >= 3 else midi
            if use_vit:
                q, _ = viterbi_quantize(m, conf, sigma_cents=S, switch_penalty=P)
                q = q[:n]
            else:
                q = np.round(m)
            return notes_from_viterbi(q, np.arange(n) * HOP_SEC, conf,
                                      min_dur=min_dur, rel_floor=rel_floor)
        return f

    print("中值核 × 是否 Viterbi：")
    for med in (0, 3, 5, 7, 9, 11):
        run(f"med={med or '无':<3} 取整", mk(med, False), show_cov=(med in (0, 5)))
        run(f"med={med or '无':<3} Viterbi(20,6)", mk(med, True, 20.0, 6.0))

    print("\n音符成形参数（med=5 + Viterbi(20,6)）：")
    for md in (0.03, 0.04, 0.05, 0.07):
        for rf in (0.06, 0.12, 0.25):
            run(f"min_dur={md} rel_floor={rf}", mk(5, True, 20.0, 6.0, md, rf))

    print("\nViterbi 微调（med=7）：")
    for S, P in ((15.0, 6.0), (20.0, 8.0), (20.0, 12.0), (25.0, 8.0), (25.0, 12.0)):
        run(f"med=7 Viterbi({S},{P})", mk(7, True, S, P))
    return 0


if __name__ == "__main__":
    sys.exit(main())
