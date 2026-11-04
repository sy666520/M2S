"""转谱主流水线：音频 -> 音符 -> 量化 -> 调性/拍号 -> Score。"""
import os
from typing import Callable, Optional

import numpy as np

from .audio import load_audio
from .models import Score, Key
from .transcribe.base import get_transcriber
from .music.rhythm import (
    estimate_tempo_and_beats,
    to_beat_units,
    choose_grid,
    quantize_notes,
)
from .music.key import detect_key, detect_meter

SR = 22050


def _progress(progress: Optional[Callable[[float, str], None]], v: float, msg: str):
    if progress:
        progress(max(0.0, min(1.0, v)), msg)


def transcribe_audio(path: str,
                     transcriber_name: str = "pyin",
                     title: Optional[str] = None,
                     meter: Optional[tuple] = None,
                     key: Optional["Key"] = None,
                     progress: Optional[Callable[[float, str], None]] = None) -> Score:
    _progress(progress, 0.02, "读取音频…")
    # 识别器可以声明自己想要的采样率（如音源分离模型偏好 44.1k）
    transcriber = get_transcriber(transcriber_name)
    sr = int(getattr(transcriber, "input_sr", SR) or SR)
    y, sr = load_audio(path, sr=sr)
    if y.size < sr * 0.3:
        raise ValueError("音频太短（不足 0.3 秒）")

    _progress(progress, 0.1, "识别音高…")

    def sub(v, msg=""):
        # 识别阶段占总进度的 10% -> 60%
        _progress(progress, 0.1 + v * 0.5, msg)

    notes = transcriber.transcribe(y, sr, sub)
    if not notes:
        raise ValueError("未识别到任何音符，试试更清晰的单旋律音频")

    _progress(progress, 0.62, "分析节奏…")
    tempo, t0, dt = estimate_tempo_and_beats(y, sr)

    items = to_beat_units(notes, t0, dt)
    grid = choose_grid(items)
    qnotes = quantize_notes(items, grid)

    _progress(progress, 0.8, "推断调性与拍号…")
    # 调性 / 拍号自动推断都有极限，允许用户手动指定覆盖
    key = key if key is not None else detect_key(qnotes, notes)
    meter = tuple(meter) if meter else detect_meter(y, sr, tempo, t0, dt)

    total_beats = 0.0
    if qnotes:
        total_beats = qnotes[-1].beat + qnotes[-1].dur

    _progress(progress, 0.95, "生成乐谱…")
    return Score(
        notes=qnotes,
        tempo=round(float(tempo), 1),
        meter=meter,
        key=key,
        grid=grid,
        total_beats=round(total_beats, 4),
        source_duration=round(float(y.size / sr), 2),
        title=title or os.path.splitext(os.path.basename(path))[0],
        transcriber=transcriber_name,
    )
