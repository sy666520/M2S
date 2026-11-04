"""调性与拍号推断。"""
from typing import List, Tuple

import numpy as np
import librosa

from ..models import Key, Note, QuantNote

# Krumhansl-Schmuckler 调性剖面
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-9:
        return 0.0
    return float((a * b).sum() / denom)


def detect_key(notes: List[QuantNote], fallback: List[Note] = None) -> Key:
    """按时值加权的音级直方图与 24 个调性剖面做相关，取最优。"""
    hist = np.zeros(12, dtype=np.float64)
    src = [(n.midi, n.dur) for n in notes] if notes else \
          [(n.midi, max(n.duration, 0.05)) for n in (fallback or [])]
    if not src:
        return Key(tonic_pc=0, mode="major")
    for midi, dur in src:
        hist[midi % 12] += float(dur)

    # 首末音的调性暗示很强（大量曲目首尾都落在主音上），作为辅助加分项
    first_pc = src[0][0] % 12
    last_pc = src[-1][0] % 12

    best = (0, "major", -2.0)
    for tonic in range(12):
        for mode, prof in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
            c = _corr(hist, np.roll(prof, tonic))
            # 轻微偏好大调：两者相关系数接近时（常见于缺音片段），大调是更好的猜测
            if mode == "minor":
                c *= 0.95
            if tonic == first_pc:
                c += 0.03
            if tonic == last_pc:
                c += 0.02
            if c > best[2]:
                best = (tonic, mode, c)
    return Key(tonic_pc=best[0], mode=best[1])


def detect_meter(y: np.ndarray, sr: int, tempo: float, t0: float, dt: float,
                 hop_length: int = 512) -> Tuple[int, int]:
    """在 4/4、3/4、2/4 中选重音周期性最明显的一个。"""
    if tempo <= 0 or dt <= 0:
        return (4, 4)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    times = librosa.frames_to_time(np.arange(len(env)), sr=sr, hop_length=hop_length)

    n_beats = int(min((times[-1] - t0) / dt, 200)) if len(times) else 0
    if n_beats < 8:
        return (4, 4)
    strengths = []
    for i in range(n_beats):
        a, b = t0 + i * dt, t0 + (i + 1) * dt
        seg = env[(times >= a) & (times < b)]
        strengths.append(float(seg.max()) if seg.size else 0.0)
    strengths = np.array(strengths)
    if strengths.sum() <= 0:
        return (4, 4)

    overall = strengths.mean()
    spread = float(strengths.std()) or 1e-6

    def downbeat_gain(m: int) -> float:
        """小节首拍平均强度相对整体高出多少个标准差。"""
        return (strengths[::m].mean() - overall) / spread

    # 4/4 是强先验：绝大多数流行 / 古典旋律都是 4/4。
    # 2/4 是 4/4 的因数，其"首拍"必然也强，会无脑胜出，所以不参与自动判断
    # （需要时由用户手动指定）。只有 3/4 拿到明显更强的重音周期才改判。
    if n_beats >= 9 and downbeat_gain(3) - downbeat_gain(4) > 0.5:
        return (3, 4)
    return (4, 4)
