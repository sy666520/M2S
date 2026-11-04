"""CREPE 神经网络音高识别器（GPU 加速）。

相比 pYIN（基于自相关累积的统计方法），CREPE 用卷积网络直接从波形估计基频，
在真人演唱上的逐帧准确率明显更高。

本项目实测（MIR-1K 10 首、htdemucs_ft 分离人声）：
    原始 pYIN 帧准确率            66.8%（分离+旧解码）
    CREPE 默认解码 + 自写 Viterbi  88.1%（原始帧）→ 77.4%（成谱）
    CREPE + 细帧移集成（本文件）    94.0%（原始帧）→ 81.7%（成谱）

三个关键改进（都经扫描验证，见 tests/sweep_f0.py、sweep_final.py）：
  1. **decoder=weighted_argmax**
     CREPE 默认 decoder 是 bin 级 Viterbi，输出被量化到 20 音分网格再加抖动；
     weighted_argmax 在 argmax 邻域做加权平均，得到连续的音分估计。
  2. **细帧移 + 多窗口平均**
     内部帧移取 2.5ms、连续 8 帧按置信度加权平均成 20ms 一帧，
     等价于用 8 个错开窗口共同投票，压掉单窗噪声（原始帧准确率 +5 点）。
  3. **解码参数按新 f0 重调**
     f0 变干净后旧参数（sigma=30/switch=3）会过度平滑，改为 sigma=18/switch=4。

依赖：pip install torchcrepe（模型权重随包分发，无需联网下载）
"""
from typing import Callable, List, Optional

import numpy as np

from ..models import Note
from .base import Transcriber, register
from .segment import (harmonic_octave_fix, notes_from_viterbi, smooth_curve,
                      split_notes_at_onsets, viterbi_quantize)

try:
    import torch
    import torchcrepe
    _HAS_CREPE = True
except Exception:
    _HAS_CREPE = False

# torchcrepe 内部固定重采样到 16 kHz，hop 也以 16k 为单位
CREPE_SR = 16000
FRAME = 320             # 输出帧长 20 ms，与 MIR-1K 标注帧移一致，便于对齐
FMIN, FMAX = 65.0, 1050.0


def _device() -> str:
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _grid(device: str) -> tuple:
    """按设备选内部帧移与平均窗口数：有 GPU 用细网格，纯 CPU 退化一档。"""
    if device == "cuda":
        hop, avg = 40, 8      # 2.5ms × 8 = 20ms
    else:
        hop, avg = 160, 2     # 10ms × 2 = 20ms
    return hop, avg


def _to_16k(y: np.ndarray, sr: int) -> np.ndarray:
    """自行重采样到 16k。

    不能依赖 torchcrepe 内部的自动重采样：它在本环境下会跳过重采样却仍按
    16k 计算帧时间，导致时间轴被拉长、音符整体错位。
    """
    y = np.ascontiguousarray(y, dtype=np.float32)
    if sr == CREPE_SR:
        return y
    try:
        import librosa
        return librosa.resample(y, orig_sr=sr, target_sr=CREPE_SR).astype(np.float32)
    except Exception:
        import math
        import scipy.signal as signal
        g = math.gcd(sr, CREPE_SR)
        return signal.resample_poly(y, CREPE_SR // g, sr // g).astype(np.float32)


def _average_frames(f0: np.ndarray, conf: np.ndarray, k: int):
    """把连续 k 帧合成一帧。

    必须在音分域加权平均：直接对 Hz 取均值会系统性偏高（频率是等比标度）。
    """
    n = (len(f0) // k) * k
    if k <= 1 or n == 0:
        return f0, conf
    f0, conf = f0[:n], conf[:n]
    f0m, cm = f0.reshape(-1, k), conf.reshape(-1, k)
    valid = (f0m > 0) & (cm > 0)
    cents = np.where(valid, 1200.0 * np.log2(np.maximum(f0m, 1e-6) / 440.0), 0.0)
    w = np.where(valid, cm, 0.0)
    total = np.sum(w, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        avg_c = np.sum(cents * w, axis=1) / np.maximum(total, 1e-9)
    bad = total <= 1e-9
    out_f = np.where(bad, 0.0, 440.0 * 2.0 ** (avg_c / 1200.0))
    # 取窗内最大置信度：只要有子帧很确定，这一帧就算浊音
    out_c = np.where(bad, 0.0, np.max(cm, axis=1))
    return out_f, out_c


def predict_f0(y: np.ndarray, sr: int, model: str = "full",
               periodicity_threshold: float = 0.21,
               device: Optional[str] = None,
               decoder: str = "weighted_argmax",
               hop: Optional[int] = None,
               avg: Optional[int] = None):
    """返回 (逐帧浮点 MIDI（非浊音为 NaN）, 逐帧置信度, 帧时间)。"""
    dev = device or _device()
    if hop is None or avg is None:
        hop, avg = _grid(dev)

    dec = {
        "weighted_argmax": torchcrepe.decode.weighted_argmax,
        "viterbi": torchcrepe.decode.viterbi,
        "argmax": torchcrepe.decode.argmax,
    }[decoder]

    audio = _to_16k(y, sr)
    t = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))[None]
    with torch.no_grad():
        pitch, periodicity = torchcrepe.predict(
            t, CREPE_SR, hop_length=hop, fmin=FMIN, fmax=FMAX, model=model,
            batch_size=2048, device=dev, return_periodicity=True,
            decoder=dec, pad=True,
        )
    f0 = pitch[0].detach().cpu().numpy().astype(np.float64)
    per = periodicity[0].detach().cpu().numpy().astype(np.float64)

    f0, per = _average_frames(f0, per, avg)
    voiced = (f0 > 0) & (per >= periodicity_threshold)
    midi_f = np.where(voiced, 69.0 + 12.0 * np.log2(np.maximum(f0, 1e-6) / 440.0), np.nan)
    times = np.arange(len(midi_f), dtype=np.float64) * (hop * avg / CREPE_SR)
    return midi_f, per, times


if _HAS_CREPE:

    @register
    class CrepeTranscriber(Transcriber):
        name = "crepe"
        label = "CREPE 神经网络识别（推荐）"
        polyphonic = False
        input_sr = 22050
        slow = False
        preferred = True
        hint = "神经网络音高检测（细帧移多窗集成）+ Viterbi 解码，真人演唱上最准"

        def __init__(self, model: str = "full", periodicity_threshold: float = 0.21,
                     smooth: int = 3, decoder: str = "viterbi",
                     sigma_cents: float = 18.0, switch_penalty: float = 4.0,
                     min_dur: float = 0.04):
            self.model = model
            self.periodicity_threshold = periodicity_threshold
            self.smooth = smooth
            self.decoder = decoder
            self.sigma_cents = sigma_cents
            self.switch_penalty = switch_penalty
            self.min_dur = min_dur

        def transcribe(self, y, sr, progress: Optional[Callable] = None) -> List[Note]:
            def _p(v, msg=""):
                if progress:
                    progress(v, msg)

            _p(0.08, f"神经网络音高检测（{_device()}）…")
            midi_f, conf, times = predict_f0(
                y, sr, model=self.model,
                periodicity_threshold=self.periodicity_threshold,
            )

            _p(0.68, "平滑音高曲线…")
            if self.smooth >= 3:
                midi_f = smooth_curve(midi_f, self.smooth)
            midi_f = harmonic_octave_fix(midi_f, conf)

            _p(0.80, "Viterbi 解码音高…")
            quant, _ = viterbi_quantize(midi_f, conf,
                                        sigma_cents=self.sigma_cents,
                                        switch_penalty=self.switch_penalty)
            _p(0.9, "整理音符…")
            notes = notes_from_viterbi(quant, times, conf, min_dur=self.min_dur,
                                       rel_floor=0.1)
            # 同音反复需要 onset 才能切开（不改变逐帧音高，纯记谱改善）
            onsets = self._onsets(y, sr)
            return split_notes_at_onsets(notes, onsets)

        @staticmethod
        def _onsets(y, sr):
            import librosa
            try:
                return librosa.onset.onset_detect(
                    y=y, sr=sr, hop_length=512, units="time", backtrack=True,
                    delta=0.06, wait=2,
                )
            except Exception:
                return np.empty(0)
