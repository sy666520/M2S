"""真实歌曲评测（MIR-1K：中文流行歌演唱 + 伴奏 + 逐帧音高真值）。

对比三种配置的「原始音高准确率 RPA」：
  A 基线   pYIN 直接跑在混音上
  B 本方案 demucs 分离出人声后再跑 pYIN
  C 上界   pYIN 跑在数据集给出的人声真值轨上（分离完美的理论上限）

RPA = 在真值判定为有声的帧中，估计音高误差 <= 50 音分的比例。
"""
import argparse
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.transcribe.base import get_transcriber  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "real", "mir1k")
HOP_SEC = 0.02          # MIR-1K 音高标注的帧移


def load_pv(path: str) -> np.ndarray:
    """读 .pv 音高标注，返回每帧的基频（Hz，0 表示无声）。

    MIR-1K 的标注是 MIDI 音高号（实测范围 41~64，A4=69），这里换算成 Hz。
    """
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
    hz = np.where(midi > 0, 440.0 * (2.0 ** ((midi - 69.0) / 12.0)), 0.0)
    return hz


def notes_to_curve(notes, duration: float) -> np.ndarray:
    """把音符列表（秒）展开成与真值对齐的逐帧基频曲线。"""
    n_frames = int(round(duration / HOP_SEC))
    curve = np.zeros(n_frames, dtype=np.float64)
    for n in notes:
        t0 = getattr(n, "start", None)
        if t0 is None:
            continue
        t1 = t0 + getattr(n, "duration", getattr(n, "dur", 0.0))
        f = 440.0 * (2.0 ** ((n.midi - 69) / 12.0))
        i0 = max(0, int(round(t0 / HOP_SEC)))
        i1 = min(n_frames, int(round(t1 / HOP_SEC)))
        if i1 > i0:
            curve[i0:i1] = f
    return curve


def rpa(est: np.ndarray, ref: np.ndarray, cents: float = 50.0):
    """原始音高准确率 + 八度容错准确率。"""
    m = min(len(est), len(ref))
    est, ref = est[:m], ref[:m]
    voiced = ref > 0
    n_voiced = int(voiced.sum())
    if n_voiced == 0:
        return 0.0, 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        diff = 1200.0 * np.log2(np.where(est > 0, est, np.nan) / ref)
    valid = voiced & np.isfinite(diff)
    ok = valid & (np.abs(diff) <= cents)
    oct_diff = np.where(valid, ((diff + 600) % 1200) - 600, np.inf)
    ok_oct = ok | (valid & (np.abs(oct_diff) <= cents))
    return float(ok.sum() / n_voiced), float(ok_oct.sum() / n_voiced)


def run_case(name: str, songs: list, engine: str, use_vocal_ref: bool = False):
    rows = []
    t_all = time.time()
    for song in songs:
        src = os.path.join(DATA, f"{song}{'_v' if use_vocal_ref else '_m'}.wav")
        ref_path = os.path.join(DATA, f"{song}.pv")
        y, sr = sf.read(src, dtype="float32", always_2d=False)
        if getattr(y, "ndim", 1) > 1:
            y = y.mean(axis=1)
        ref = load_pv(ref_path)
        duration = len(ref) * HOP_SEC

        t0 = time.time()
        notes = get_transcriber(engine).transcribe(np.asarray(y, dtype=np.float32), sr)
        elapsed = time.time() - t0
        curve = notes_to_curve(notes, duration)
        acc, acc_oct = rpa(curve, ref)
        rows.append((song, acc, acc_oct, len(notes), elapsed))
        print(f"   {song:<14} RPA {acc*100:5.1f}%  (含八度容错 {acc_oct*100:5.1f}%)"
              f"   音符 {len(notes):>3}   {elapsed:5.1f}s")

    accs = [r[1] for r in rows]
    mean_acc = float(np.mean(accs)) if accs else 0.0
    total = time.time() - t_all
    print(f"   ── {name} 平均 RPA {mean_acc*100:.1f}%   总耗时 {total:.1f}s\n")
    return mean_acc, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", default="Ani_1_02,Ani_2_05,Kenshin_4_03,Ani_5_08")
    ap.add_argument("--skip-ref", action="store_true", help="跳过人声真值上界测试")
    args = ap.parse_args()
    songs = [s.strip() for s in args.songs.split(",") if s.strip()]

    print(f"评测素材：MIR-1K 测试集 {len(songs)} 首（真实中文流行歌演唱 + 伴奏）")
    print(f"指标：RPA（真值有声帧中音高误差 ≤50 音分的比例）\n")

    print("[A] 基线：pYIN 直接跑在混音上")
    base, _ = run_case("基线", songs, "pyin")

    print("[B] 本方案：demucs 分离人声 + pYIN")
    ours, _ = run_case("分离后", songs, "song")

    if not args.skip_ref:
        print("[C] 上界：pYIN 跑在数据集的人声真值轨上")
        upper, _ = run_case("上界", songs, "pyin", use_vocal_ref=True)
        print(f"结论：分离带来的提升 {ours*100 - base*100:+.1f} 个百分点"
              f"（相对上界还差 {upper*100 - ours*100:.1f} 个百分点）")
    else:
        print(f"结论：分离带来的提升 {ours*100 - base*100:+.1f} 个百分点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
