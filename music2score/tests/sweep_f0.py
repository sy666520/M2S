"""扫描 f0 提取配置：解码器 × 帧移集成 × 周期阈值。

核心发现：CREPE 默认 decoder=viterbi 会把输出量化到 20 音分网格，
换成 weighted_argmax 可得连续估计；再用更细的帧移做多窗口平均可降噪。

用法：
    py -3.10 tests/sweep_f0.py --model htdemucs_ft --stem vocals
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.segment import notes_from_viterbi, viterbi_quantize  # noqa: E402
from diag_stage import HOP_SEC, load_pv_midi, medfilt_voiced, rpa_midi  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "real", "mir1k")
CACHE = os.path.join(DATA, "_stems")
F0DIR = os.path.join(CACHE, "f0sweep")
ALL = ["Ani_1_02", "Ani_1_03", "Ani_2_01", "Ani_2_05", "Ani_5_02",
       "Ani_5_08", "Kenshin_3_01", "Kenshin_4_02", "Kenshin_4_03", "Kenshin_5_01"]

CREPE_SR = 16000


def _to_16k(y, sr):
    import librosa
    y = np.ascontiguousarray(y, dtype=np.float32)
    return y if sr == CREPE_SR else librosa.resample(y, orig_sr=sr, target_sr=CREPE_SR).astype(np.float32)


def predict_f0(y, sr, decoder="viterbi", hop=320, avg=1, thr=0.21, fmin=65.0, fmax=1050.0):
    """返回 (逐帧 MIDI（NaN 表示非浊音）, 置信度)。

    hop 为 CREPE 内部帧移；avg 表示把连续 avg 帧平均成 20ms 一帧。
    """
    import torch
    import torchcrepe

    dec = {"viterbi": torchcrepe.decode.viterbi,
           "weighted_argmax": torchcrepe.decode.weighted_argmax,
           "argmax": torchcrepe.decode.argmax}[decoder]
    audio = _to_16k(y, sr)
    t = torch.from_numpy(audio)[None]
    with torch.no_grad():
        pitch, per = torchcrepe.predict(
            t, CREPE_SR, hop_length=hop, fmin=fmin, fmax=fmax, model="full",
            batch_size=2048, device="cuda" if torch.cuda.is_available() else "cpu",
            return_periodicity=True, decoder=dec, pad=True,
        )
    f0 = pitch[0].detach().cpu().numpy().astype(np.float64)
    conf = per[0].detach().cpu().numpy().astype(np.float64)

    if avg > 1:
        f0, conf = _average_frames(f0, conf, avg)
    voiced = (f0 > 0) & (conf >= thr)
    midi = np.where(voiced, 69.0 + 12.0 * np.log2(np.maximum(f0, 1e-6) / 440.0), np.nan)
    return midi, conf


def _average_frames(f0, conf, k):
    """把连续 k 帧合成一帧：在音分域按置信度加权平均，避免 Hz 域均值偏高。"""
    n = (len(f0) // k) * k
    if n == 0:
        return f0, conf
    f0, conf = f0[:n], conf[:n]
    f0m = f0.reshape(-1, k)
    cm = conf.reshape(-1, k)
    valid = (f0m > 0) & (cm > 0)
    cents = np.where(valid, 1200.0 * np.log2(np.maximum(f0m, 1e-6) / 440.0), 0.0)
    cw = np.where(valid, cm, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        avg_c = np.sum(cents * cw, axis=1) / np.maximum(np.sum(cw, axis=1), 1e-9)
    bad = np.sum(cw, axis=1) <= 1e-9
    out_f = np.where(bad, 0.0, 440.0 * 2.0 ** (avg_c / 1200.0))
    out_c = np.where(bad, 0.0, np.max(cm, axis=1))
    return out_f, out_c


def cfg_key(cfg):
    return hashlib.md5(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def get_f0(song, model, stem, cfg):
    os.makedirs(F0DIR, exist_ok=True)
    p = os.path.join(F0DIR, f"{song}_{model}_{stem}_{cfg_key(cfg)}.npz")
    if os.path.exists(p):
        z = np.load(p)
        return z["midi"], z["conf"]
    z = np.load(os.path.join(CACHE, f"{song}_{model}.npz"))
    midi, conf = predict_f0(z[stem], int(z["sr"]), **cfg)
    np.savez_compressed(p, midi=midi, conf=conf)
    return midi, conf


def curve_of(notes, n):
    curve = np.full(n, np.nan)
    for x in notes:
        i0 = max(0, int(round(x.start / HOP_SEC)))
        i1 = min(n, int(round((x.start + x.duration) / HOP_SEC)))
        if i1 > i0:
            curve[i0:i1] = float(x.midi)
    return curve


CONFIGS = [
    {"name": "base  viterbi/320", "decoder": "viterbi", "hop": 320, "avg": 1, "thr": 0.21},
    {"name": "warg  w-argmax/320", "decoder": "weighted_argmax", "hop": 320, "avg": 1, "thr": 0.21},
    {"name": "warg+2 w-argmax/160x2", "decoder": "weighted_argmax", "hop": 160, "avg": 2, "thr": 0.21},
    {"name": "warg+4 w-argmax/80x4", "decoder": "weighted_argmax", "hop": 80, "avg": 4, "thr": 0.21},
    {"name": "vit+2  viterbi/160x2", "decoder": "viterbi", "hop": 160, "avg": 2, "thr": 0.21},
    {"name": "warg+2 thr.15", "decoder": "weighted_argmax", "hop": 160, "avg": 2, "thr": 0.15},
    {"name": "warg+2 thr.30", "decoder": "weighted_argmax", "hop": 160, "avg": 2, "thr": 0.30},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="htdemucs_ft")
    ap.add_argument("--stem", default="vocals")
    ap.add_argument("--songs", default=",".join(ALL))
    ap.add_argument("--sigma", type=float, default=30.0)
    ap.add_argument("--switch", type=float, default=3.0)
    args = ap.parse_args()
    songs = [s for s in args.songs.split(",") if s]

    refs = {s: load_pv_midi(os.path.join(DATA, f"{s}.pv")) for s in songs}
    print(f"f0 配置扫描 | {args.model}/{args.stem} | {len(songs)} 首\n")
    print(f"{'配置':<22}{'原始RPA':>9}{'取整RPA':>9}{'中值取整':>9}{'Viterbi':>9}{'成音符':>9}")
    for cfg in CONFIGS:
        c = {k: v for k, v in cfg.items() if k != "name"}
        raw, snap, med, vt, nt = [], [], [], [], []
        for s in songs:
            ref = refs[s]
            midi, conf = get_f0(s, args.model, args.stem, c)
            n = min(len(ref), len(midi))
            ref_n, midi, conf = ref[:n], midi[:n], conf[:n]
            raw.append(rpa_midi(midi, ref_n))
            snap.append(rpa_midi(np.round(midi), ref_n))
            med.append(rpa_midi(np.round(medfilt_voiced(midi, 5)), ref_n))
            q, _ = viterbi_quantize(midi, conf, sigma_cents=args.sigma,
                                    switch_penalty=args.switch)
            vt.append(rpa_midi(q[:n], ref_n))
            notes = notes_from_viterbi(q[:n], np.arange(n) * HOP_SEC, conf)
            nt.append(rpa_midi(curve_of(notes, n), ref_n))
        f = lambda x: np.mean(x) * 100  # noqa: E731
        print(f"{cfg['name']:<22}{f(raw):>8.1f}%{f(snap):>8.1f}%{f(med):>8.1f}%"
              f"{f(vt):>8.1f}%{f(nt):>8.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
