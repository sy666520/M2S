"""检查真值相对十二平均律是否存在整体调音偏移（半音网格错位）。

若整首歌的基频系统性偏高/偏低 δ 半音，则真值落在半音边界附近，
任何取整都会大规模判错；估计并补偿 δ 后应能大幅回升。

用法：
    py -3.10 tests/diag_tuning.py --model htdemucs_ft --stem vocals
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_stage import get_f0, load_pv_midi, rpa_midi  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--thr", type=float, default=0.21)
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    print(f"调音偏移诊断 | {args.model}/{args.stem}\n")
    print(f"{'歌曲':<14}{'偏移(音分)':>11}{'真值离半音':>11}{'原始RPA':>9}"
          f"{'取整RPA':>9}{'补偿后':>9}{'Oracle':>9}")
    rows = []
    for s in songs:
        ref = load_pv_midi(os.path.join(DATA, f"{s}.pv"))
        midi_f, conf = get_f0(s, args.model, args.stem, args.thr)
        n = min(len(ref), len(midi_f))
        ref, est = ref[:n], midi_f[:n]
        vv = ref > 0
        if not vv.any():
            continue

        # 1) 用真值本身估计全局调音偏移：真值小数部分相对 0 的偏离（循环均值）
        frac = ref[vv] - np.round(ref[vv])
        # 循环均值：把小数部分当作角度看，避免 ±0.5 处的不连续
        ang = 2 * np.pi * frac
        off_cents = float(np.degrees(np.arctan2(np.sin(ang).mean(),
                                                np.cos(ang).mean())) / 360.0 * 1200.0)
        dist = float(np.mean(np.abs(frac)) * 100.0)

        a = rpa_midi(est, ref)
        snap = np.round(np.where(np.isfinite(est), est, np.nan))
        a0 = rpa_midi(snap, ref)

        # 2) 补偿偏移后重新取整：把估计值先减去 δ 再取整
        d = off_cents / 100.0
        snap2 = np.round(np.where(np.isfinite(est), est - d, np.nan)) + d
        a1 = rpa_midi(snap2, ref)

        # 3) Oracle：已知真值，取最接近的半音（在小数真值上直接取整）
        oracle = rpa_midi(np.round(ref), ref)

        rows.append((off_cents, dist, a, a0, a1, oracle))
        print(f"{s:<14}{off_cents:>10.1f}¢{dist:>10.1f}¢{a*100:>8.1f}%"
              f"{a0*100:>8.1f}%{a1*100:>8.1f}%{oracle*100:>8.1f}%")

    m = np.mean(np.array(rows), axis=0)
    print(f"\n{'平均':<14}{m[0]:>10.1f}¢{m[1]:>10.1f}¢{m[2]:>8.1f}%"
          f"{m[3]:>8.1f}%{m[4]:>8.1f}%{m[5]:>8.1f}%")
    print("\n注：「真值离半音」= 真值小数部分绝对值的平均（音分）；"
          "越接近 50¢ 说明真值越贴着半音边界，取整越容易判错。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
