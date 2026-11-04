"""分离模型集成：把 htdemucs 与 htdemucs_ft 两版人声轨的 CREPE f0 平均。

用法：
    py -3.10 tests/sweep_ens.py --stem vocals
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


def fuse(midi_a, conf_a, midi_b, conf_b):
    """音分域按置信度加权融合两条 f0。"""
    n = min(len(midi_a), len(midi_b))
    ca = np.where(np.isfinite(midi_a), 1200.0 * np.log2(np.maximum(2.0 ** ((midi_a - 69) / 12.0), 1e-9)), 0.0)
    cb = np.where(np.isfinite(midi_b), 1200.0 * np.log2(np.maximum(2.0 ** ((midi_b - 69) / 12.0), 1e-9)), 0.0)
    va, vb = np.isfinite(midi_a[:n]), np.isfinite(midi_b[:n])
    ca, cb = ca[:n], cb[:n]
    wa = np.where(va, np.clip(conf_a[:n], 1e-3, 1.0), 0.0)
    wb = np.where(vb, np.clip(conf_b[:n], 1e-3, 1.0), 0.0)
    w = wa + wb
    cents = (ca * wa + cb * wb) / np.maximum(w, 1e-9)
    midi = np.where(w > 0, 69.0 + cents / 100.0, np.nan)
    conf = np.where(w > 0, w / 2.0, 0.0)
    return midi, conf


def eval_notes(midi, conf, ref):
    n = min(len(ref), len(midi))
    ref, midi, conf = ref[:n], midi[:n], conf[:n]
    m = medfilt_voiced(midi, 5)
    q, _ = viterbi_quantize(m, conf, sigma_cents=20.0, switch_penalty=6.0)
    q = q[:n]
    notes = notes_from_viterbi(q, np.arange(n) * HOP_SEC, conf, min_dur=0.04)
    return (rpa_midi(m, ref), rpa_midi(q, ref), rpa_midi(curve_of(notes, n), ref))


def main():
    refs = {s: load_pv_midi(os.path.join(DATA, f"{s}.pv")) for s in ALL}
    rows = {"ft": [], "std": [], "ens": []}
    rows_raw = {k: [] for k in rows}
    print(f"分离模型 f0 集成 | warg 40x8 | {len(ALL)} 首\n")
    print(f"{'歌曲':<14}{'仅ft':>8}{'仅std':>8}{'集成':>8}   (原始/量化/音符)")
    for s in ALL:
        ref = refs[s]
        ma, ca = get_f0(s, "htdemucs_ft", "vocals", CFG)
        mb, cb = get_f0(s, "htdemucs", "vocals", CFG)
        n = min(len(ma), len(mb))
        me, ce = fuse(ma[:n], ca[:n], mb[:n], cb[:n])
        res = {}
        for k, (m, c) in (("ft", (ma, ma)), ("std", (mb, mb)), ("ens", (me, ce))):
            c = ca if k == "ft" else (cb if k == "std" else ce)
            r = eval_notes(m, c, ref)
            res[k] = r
            rows[k].append(r[2])
            rows_raw[k].append(r[0])
        print(f"{s:<14}{res['ft'][2]*100:>7.1f}%{res['std'][2]*100:>7.1f}%"
              f"{res['ens'][2]*100:>7.1f}%   "
              f"({res['ens'][0]*100:.0f}/{res['ens'][1]*100:.0f}/{res['ens'][2]*100:.0f})")
    print(f"\n{'平均(音符级)':<14}{np.mean(rows['ft'])*100:>7.1f}%"
          f"{np.mean(rows['std'])*100:>7.1f}%{np.mean(rows['ens'])*100:>7.1f}%")
    print(f"{'平均(原始)':<14}{np.mean(rows_raw['ft'])*100:>7.1f}%"
          f"{np.mean(rows_raw['std'])*100:>7.1f}%{np.mean(rows_raw['ens'])*100:>7.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
