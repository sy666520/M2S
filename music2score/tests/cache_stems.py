"""缓存分离结果，便于后续快速调参与评测（分离是耗时大头，识别很快）。"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.audio import load_audio  # noqa: E402
from backend.transcribe.song import separate_stems  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "real", "mir1k")
CACHE = os.path.join(DATA, "_stems")
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--songs", default=",".join(ALL))
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]
    os.makedirs(CACHE, exist_ok=True)

    for s in songs:
        out = os.path.join(CACHE, f"{s}_{args.model}.npz")
        if os.path.exists(out):
            print(f"  已有 {s}")
            continue
        y, sr = load_audio(os.path.join(DATA, f"{s}_m.wav"), sr=22050)
        stems = separate_stems(y, sr, model=args.model)
        np.savez_compressed(out, sr=sr, mix=y,
                            vocals=stems.get("vocals", np.zeros(1, dtype=np.float32)),
                            other=stems.get("other", np.zeros(1, dtype=np.float32)))
        print(f"  写入 {s}")
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
