"""端到端配置对比：分离模型 × 音高识别器的组合在真实歌曲上的表现。

用法：
    py -3.10 tests/eval_pipeline.py --configs "htdemucs+pyin,htdemucs+crepe,htdemucs_ft+crepe"
"""
import argparse
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.audio import load_audio  # noqa: E402
from backend.transcribe.base import get_transcriber  # noqa: E402
from backend.transcribe.song import pick_melody_stem, separate_stems  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_note import HOP_SEC, DATA, curve_of, load_pv, rpa  # noqa: E402

ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="htdemucs+pyin,htdemucs+crepe,htdemucs_ft+crepe")
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]
    configs = [c.split("+") for c in args.configs.split(",") if c]

    refs = {s: load_pv(os.path.join(DATA, f"{s}.pv")) for s in songs}
    mixes = {}
    for s in songs:
        y, sr = load_audio(os.path.join(DATA, f"{s}_m.wav"), sr=22050)
        mixes[s] = y

    print(f"端到端评测 | 完整混音 {len(songs)} 首 | 指标 RPA(±50音分)\n")
    results = {}
    for model, engine in configs:
        accs, times = [], []
        for s in songs:
            y = mixes[s]
            t0 = time.time()
            stems = separate_stems(y, 22050, model=model)
            _, track = pick_melody_stem(stems, y)
            peak = float(np.max(np.abs(track))) if track.size else 0.0
            if peak > 1e-6:
                track = (track / peak * 0.9).astype(np.float32)
            notes = get_transcriber(engine).transcribe(track, 22050)
            dt = time.time() - t0
            acc, _ = rpa(curve_of(notes, len(refs[s]) * HOP_SEC), refs[s])
            accs.append(acc)
            times.append(dt)
            print(f"  {model}+{engine:<6} {s:<14} RPA {acc*100:5.1f}%  {len(notes):>3}音  {dt:5.1f}s")
        results[(model, engine)] = (float(np.mean(accs)), float(np.mean(times)))
        print(f"  ── {model}+{engine} 平均 RPA {np.mean(accs)*100:.1f}%  "
              f"平均耗时 {np.mean(times):.1f}s\n")

    print("汇总：")
    for (m, e), (acc, t) in sorted(results.items(), key=lambda kv: -kv[1][0]):
        print(f"  {m:<12}+{e:<6} {acc*100:5.1f}%   {t:5.1f}s/首")
    return 0


if __name__ == "__main__":
    sys.exit(main())
