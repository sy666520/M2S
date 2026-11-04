"""pYIN 单旋律识别器。

流程：
  1. librosa.pyin 逐帧估计基频 + 浊音概率
  2. 用 onset 检测强制切分（解决「5555」这类同音重复被合并的问题）
  3. 相邻帧音高聚类成音符段
  4. 过滤过短 / 低置信度噪声段
"""
from typing import List, Optional, Callable

import numpy as np
import librosa

from ..models import Note
from .base import Transcriber, register


DEFAULT_FMIN = librosa.note_to_hz("C2")
DEFAULT_FMAX = librosa.note_to_hz("C7")


def _merge_segments(pitches: np.ndarray, times: np.ndarray, probs: np.ndarray,
                    onset_times: np.ndarray, tol: float = 0.55,
                    min_dur: float = 0.06) -> List[Note]:
    """把逐帧音高序列切成音符。"""
    n = len(pitches)
    notes: List[Note] = []
    i = 0
    onset_set = set(np.round(onset_times, 3))

    while i < n:
        if not np.isfinite(pitches[i]):
            i += 1
            continue
        j = i + 1
        while j < n and np.isfinite(pitches[j]) and abs(pitches[j] - pitches[i]) <= tol:
            # onset 处强制断开：同音重复也能切开
            t = round(float(times[j]), 3)
            if t in onset_set and (times[j] - times[i]) > min_dur:
                break
            j += 1

        seg_p = pitches[i:j]
        seg_w = probs[i:j]
        start = float(times[i])
        end = float(times[j - 1]) + (times[1] - times[0] if n > 1 else 0.01)
        dur = end - start

        if dur >= min_dur:
            # 用置信度加权的中位数作为最终音高，抗抖动
            try:
                midi_f = weighted_median(seg_p, seg_w)
            except Exception:
                midi_f = float(np.median(seg_p))
            midi = int(round(midi_f))
            if 12 <= midi <= 120:
                vel = float(np.clip(np.mean(seg_w), 0.2, 1.0))
                notes.append(Note(midi=midi, start=start, duration=dur, velocity=vel))
        i = j if j > i else i + 1

    return notes


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones_like(v)
    c = np.cumsum(w) - 0.5 * w
    idx = np.searchsorted(c, c[-1] / 2.0)
    idx = min(idx, len(v) - 1)
    return float(v[idx])


@register
class PyinTranscriber(Transcriber):
    name = "pyin"
    label = "pYIN 单旋律识别"
    polyphonic = False

    def __init__(self, hop_length: int = 512, frame_length: int = 2048,
                 voicing_threshold: float = 0.42):
        self.hop_length = hop_length
        self.frame_length = frame_length
        self.voicing_threshold = voicing_threshold

    def transcribe(self, y, sr, progress=None):
        def _p(v, msg=""):
            if progress:
                progress(v, msg)

        _p(0.05, "分析音频帧…")
        hop = self.hop_length
        f0, voiced_flag, voiced_prob = librosa.pyin(
            y, sr=sr,
            fmin=DEFAULT_FMIN, fmax=DEFAULT_FMAX,
            frame_length=self.frame_length,
            hop_length=hop,
            fill_na=None,
        )
        _p(0.45, "检测基频…")

        times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop)
        probs = np.nan_to_num(voiced_prob, nan=0.0)
        voiced = np.array(voiced_flag, dtype=bool) & (probs >= self.voicing_threshold)

        # 基频 -> 浮点 MIDI；非浊音置 NaN
        midi_f = np.full(len(f0), np.nan, dtype=np.float64)
        ok = voiced & np.isfinite(f0) & (f0 > 0)
        midi_f[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)

        _p(0.65, "切分音符…")
        onset_times = librosa.onset.onset_detect(
            y=y, sr=sr, hop_length=hop, units="time", backtrack=True
        )
        notes = _merge_segments(midi_f, times, probs, onset_times)

        # 二次清理：去掉明显孤立的极短音（多半是清唱气声 / 伴奏残留）
        if notes:
            durs = np.array([n.duration for n in notes])
            med = float(np.median(durs))
            floor = max(0.05, med * 0.22)
            notes = [n for n in notes if n.duration >= floor]

        _p(0.85, "整理音符…")
        return notes
