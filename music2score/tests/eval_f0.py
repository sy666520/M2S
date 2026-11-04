"""逐帧音高估计器对比：在数据集的人声真值轨上直接测 f0 精度。

这一步排除「分离质量」与「音符切分」的干扰，只看估计器本身。
输出 RPA（±50 音分）、八度错误率、以及非八度的偏差分布。
"""
import argparse
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "real", "mir1k")
HOP_SEC = 0.02


def load_pv(path: str) -> np.ndarray:
    vals = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                vals.append(float(line.split()[0]))
            except ValueError:
                vals.append(0.0)
    midi = np.asarray(vals, dtype=np.float64)
    return np.where(midi > 0, 440.0 * (2.0 ** ((midi - 69.0) / 12.0)), 0.0)


def f0_pyin(y, sr):
    import librosa
    hop = int(round(HOP_SEC * sr))
    f0, flag, prob = librosa.pyin(y, sr=sr, fmin=librosa.note_to_hz("C2"),
                                  fmax=librosa.note_to_hz("C7"),
                                  frame_length=2048, hop_length=hop, fill_na=0.0)
    p = np.nan_to_num(prob, nan=0.0)
    out = np.where(np.asarray(flag, dtype=bool) & (p >= 0.42), np.nan_to_num(f0), 0.0)
    return out


def f0_crepe(y, sr, model="full", device="cuda"):
    import torch
    import torchcrepe
    # torchcrepe 内部重采样到 16k，hop 以 16k 为单位
    hop = 320  # 20ms
    t = torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))[None]
    with torch.no_grad():
        pitch, period = torchcrepe.predict(
            t, sr, hop_length=hop, fmin=65.0, fmax=1000.0, model=model,
            batch_size=1024, device=device, return_periodicity=True,
        )
    p = pitch[0].cpu().numpy().astype(np.float64)
    per = period[0].cpu().numpy()
    # 周期置零 = 静音；低周期度视为清音
    return np.where((p > 0) & (per > 0.21), p, 0.0)


def score(est, ref):
    m = min(len(est), len(ref))
    est, ref = est[:m].copy(), ref[:m].copy()
    voiced = ref > 0
    nv = int(voiced.sum())
    if nv == 0:
        return dict(rpa=0.0, voice_acc=0.0, oct_wrong=0.0, other=0.0, fine=0.0)
    both = voiced & (est > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cents = 1200.0 * np.log2(np.where(est > 0, est, 1.0) / ref)
    err = np.where(both, cents, np.inf)
    ok = both & (np.abs(err) <= 50)
    # 八度错误：把偏差折叠到 ±600 后落在 ±50 内
    folded = np.where(both, ((err + 600) % 1200) - 600, np.inf)
    oct_wrong = both & ~ok & (np.abs(folded) <= 50)
    # 偏差在 50~200 音分之间（音准偏差但方向对）
    fine = both & ~ok & (np.abs(err) <= 200)
    other = both & ~ok & ~oct_wrong & ~fine
    return dict(
        rpa=float(ok.sum() / nv),
        voice_acc=float(both.sum() / nv),
        oct_wrong=float(oct_wrong.sum() / nv),
        fine=float(fine.sum() / nv),
        other=float(other.sum() / nv),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", default="Ani_1_02,Ani_2_05,Kenshin_4_03,Ani_5_08")
    ap.add_argument("--crepe-model", default="full")
    args = ap.parse_args()
    songs = [s.strip() for s in args.songs.split(",") if s.strip()]

    print(f"逐帧音高对比（人声真值轨，{len(songs)} 首）")
    print("列含义：RPA=±50音分内  voice=有声判对率  oct=八度错误  100-200c=音准偏移  其余\n")

    agg = {"pyin": [], "crepe": []}
    for song in songs:
        y, sr = sf.read(os.path.join(DATA, f"{song}_v.wav"), dtype="float32",
                        always_2d=False)
        if getattr(y, "ndim", 1) > 1:
            y = y.mean(axis=1)
        ref = load_pv(os.path.join(DATA, f"{song}.pv"))
        y = np.ascontiguousarray(y, dtype=np.float32)[: int(len(ref) * HOP_SEC * sr) + sr]

        row = {}
        for name, fn in (("pyin", lambda: f0_pyin(y, sr)),
                         ("crepe", lambda: f0_crepe(y, sr, args.crepe_model))):
            t = time.time()
            est = fn()
            row[name] = score(est, ref)
            row[name]["sec"] = time.time() - t
            agg[name].append(row[name]["rpa"])
        print(f"{song:<14} pYIN {row['pyin']['rpa']*100:5.1f}%  "
              f"CREPE {row['crepe']['rpa']*100:5.1f}%   "
              f"| pYIN 八度 {row['pyin']['oct_wrong']*100:4.1f}% 音准 {row['pyin']['fine']*100:4.1f}%"
              f" | CREPE 八度 {row['crepe']['oct_wrong']*100:4.1f}% 音准 {row['crepe']['fine']*100:4.1f}%")

    print()
    for name in ("pyin", "crepe"):
        print(f"  {name:<6} 平均 RPA {np.mean(agg[name])*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
