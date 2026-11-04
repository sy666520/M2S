"""更细的帧移集成 + 新 f0 的误差结构分析。

用法：
    py -3.10 tests/sweep_fine.py --model htdemucs_ft --stem vocals
"""
import argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    refs = {s: load_pv_midi(os.path.join(DATA, f"{s}.pv")) for s in songs}

    cfgs = [
        ("warg 80x4", {"decoder": "weighted_argmax", "hop": 80, "avg": 4, "thr": 0.21}),
        ("warg 80x2", {"decoder": "weighted_argmax", "hop": 80, "avg": 2, "thr": 0.21}),
        ("warg 40x8", {"decoder": "weighted_argmax", "hop": 40, "avg": 8, "thr": 0.21}),
        ("warg 160x1", {"decoder": "weighted_argmax", "hop": 160, "avg": 1, "thr": 0.21}),
    ]
    print(f"帧移细化 | {args.model}/{args.stem}\n")
    print(f"{'配置':<14}{'原始':>8}{'取整':>8}{'音符':>8}")
    best = {}
    for name, cfg in cfgs:
        raw, snap, nt = [], [], []
        for s in songs:
            ref = refs[s]
            midi, conf = get_f0(s, args.model, args.stem, cfg)
            n = min(len(ref), len(midi))
            ref, midi, conf = ref[:n], midi[:n], conf[:n]
            raw.append(rpa_midi(midi, ref))
            snap.append(rpa_midi(np.round(medfilt_voiced(midi, 5)), ref))
            m = medfilt_voiced(midi, 5)
            q, _ = viterbi_quantize(m, conf, sigma_cents=20.0, switch_penalty=6.0)
            q = q[:n]
            notes = notes_from_viterbi(q, np.arange(n) * HOP_SEC, conf, min_dur=0.04)
            nt.append(rpa_midi(curve_of(notes, n), ref))
        f = lambda x: np.mean(x) * 100  # noqa: E731
        print(f"{name:<14}{f(raw):>7.1f}%{f(snap):>7.1f}%{f(nt):>7.1f}%")
        best[name] = (midi, conf)

    # 误差结构（用 80x4）
    print("\n误差结构 | warg 80x4：")
    cfg = cfgs[0][1]
    cnt = np.zeros(6)
    tot_v = 0
    for s in songs:
        ref = refs[s]
        midi, conf = get_f0(s, args.model, args.stem, cfg)
        n = min(len(ref), len(midi))
        ref, midi = ref[:n], midi[:n]
        vv = ref > 0
        tot_v += int(vv.sum())
        d = 100.0 * (midi - ref)
        ok = int(np.sum(vv & (np.abs(d) <= 50)))
        miss = int(np.sum(vv & ~np.isfinite(d)))
        semi = int(np.sum(vv & np.isfinite(d) & (np.abs(d) > 50) & (np.abs(d) <= 600)))
        oct_ = int(np.sum(vv & np.isfinite(d) & (np.abs(d) > 600) & (np.abs(d) <= 1800)))
        other = int(np.sum(vv & np.isfinite(d) & (np.abs(d) > 1800)))
        cnt += [ok, miss, semi, oct_, other, 0]
    names = ["≤50¢ 正确", "漏检(判非浊音)", "50~600¢", "600~1800¢(八度)", ">1800¢"]
    for k, nm in enumerate(names):
        print(f"  {nm:<16} {cnt[k]/tot_v*100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
