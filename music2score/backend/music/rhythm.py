"""节奏分析：拍点追踪、量化网格推断、音符量化。"""
from typing import List, Tuple

import numpy as np
import librosa

from ..models import Note, QuantNote


def estimate_tempo_and_beats(y: np.ndarray, sr: int,
                             hop_length: int = 512) -> Tuple[float, float, float]:
    """返回 (tempo, t0, dt)。

    t0 = 第 0 拍所在时间；dt = 每拍秒数。
    用最小二乘拟合求相位，避免 librosa 首个 beat 偏移导致整体网格错位。
    """
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    if tempo is None or not np.isfinite(tempo) or tempo <= 0:
        tempo = 100.0
    tempo = float(np.atleast_1d(tempo)[0])

    beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop_length)
    if len(beat_times) >= 2:
        dt = 60.0 / tempo
        k = np.arange(len(beat_times))
        # 相位拟合：t0 = mean(beat_time_k - k*dt)
        t0 = float(np.mean(beat_times - k * dt))
    else:
        dt = 60.0 / tempo
        t0 = float(beat_times[0]) if len(beat_times) else 0.0

    # tempo 落到常用区间，避免倍频错误（librosa 偶尔给出 60 或 180）
    while tempo < 60:
        tempo *= 2
        dt /= 2
    while tempo > 180:
        tempo /= 2
        dt *= 2
    return tempo, t0, dt


def to_beat_units(notes: List[Note], t0: float, dt: float) -> List[Tuple[int, float, float, float]]:
    """(midi, beat, dur_beats, velocity)"""
    out = []
    for n in notes:
        out.append((n.midi, (n.start - t0) / dt, n.duration / dt, n.velocity))
    out.sort(key=lambda x: x[1])
    return out


def choose_grid(items: List[Tuple[int, float, float, float]]) -> float:
    """选择量化网格（单位拍）。依次尝试 1/1、1/2、1/4 拍。"""
    if not items:
        return 0.5
    vals = [b for _, b, _, _ in items] + [d for _, _, d, _ in items]
    best_g, best_bad = 0.25, 1.0
    for g in (1.0, 0.5, 0.25):
        errs = [abs(v / g - round(v / g)) for v in vals]
        bad = sum(1 for e in errs if e > 0.28) / len(errs)
        if bad < best_bad:
            best_bad, best_g = bad, g
        if bad <= 0.10:
            return g
    return best_g


def quantize_notes(items: List[Tuple[int, float, float, float]], grid: float) -> List[QuantNote]:
    """量化到网格，并修整重叠。"""
    raw = []
    for midi, beat, dur, vel in items:
        b = round(beat / grid) * grid
        d = round(dur / grid) * grid
        if d <= 0:
            d = grid
        raw.append(QuantNote(midi=midi, beat=round(b, 6), dur=round(d, 6), velocity=vel))

    raw.sort(key=lambda n: (n.beat, n.midi))
    fixed: List[QuantNote] = []
    for n in raw:
        if fixed:
            prev = fixed[-1]
            end = prev.beat + prev.dur
            if n.beat < end - 1e-6:
                new_dur = n.beat - prev.beat
                if new_dur <= 1e-6:
                    # 完全被覆盖，丢弃前一个（保留后来的起音）
                    fixed.pop()
                else:
                    prev.dur = round(new_dur, 6)
        fixed.append(n)

    # 允许起始为负（弱起 / 拾音）时整体平移到非负
    if fixed and fixed[0].beat < 0:
        shift = -fixed[0].beat
        for n in fixed:
            n.beat = round(n.beat + shift, 6)
    return fixed


def snap_to_bar(notes: List[QuantNote], beats_per_bar: int, grid: float) -> List[QuantNote]:
    """把落在小节线之前的弱起音符对齐，并保证总时值补齐整小节。"""
    if not notes:
        return notes
    total = notes[-1].beat + notes[-1].dur
    bars = int(np.ceil(total / beats_per_bar))
    return notes, bars * beats_per_bar
