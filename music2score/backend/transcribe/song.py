"""完整歌曲识别：先用 demucs 做音源分离抽出人声，再交给单旋律识别器。

需要额外安装（含 torch，体积较大）：
    pip install demucs
分离模型首次运行时会自动下载（约 300MB）。

htdemucs 产出四轨：drums / bass / other / vocals。
主旋律优先取 vocals；若人声轨能量过低（纯伴奏、或分离结果为空），
自动退到 other 轨（通常承载主奏乐器），而不是返回空谱。
"""
import os
import shutil
import sys
import threading
from typing import List, Optional, Callable

import numpy as np

from ..models import Note
from .base import Transcriber, register

try:
    import torch  # noqa: F401
    import demucs.api  # noqa: F401
    _HAS_DEMUCS = True
except Exception:
    _HAS_DEMUCS = False

# demucs 各模型的原生采样率（htdemucs 系列均为 44.1k）
NATIVE_SR = 44100


def _pick_device() -> str:
    import torch
    try:
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _to_stereo(y: np.ndarray) -> "torch.Tensor":
    import torch
    wav = torch.from_numpy(np.ascontiguousarray(y, dtype=np.float32))
    # demucs 期望 (channels, samples)；单声道复制成双声道更稳
    return wav.unsqueeze(0).repeat(2, 1)


def _resample_to(y: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or not y.size:
        return y.astype(np.float32)
    try:
        import librosa
        return librosa.resample(y, orig_sr=src_sr, target_sr=dst_sr).astype(np.float32)
    except Exception:
        import scipy.signal as signal
        import math
        g = math.gcd(src_sr, dst_sr)
        return signal.resample_poly(y, dst_sr // g, src_sr // g).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0


_SEPARATORS: dict = {}
_SEP_LOCK = threading.Lock()


def _ensure_bundled_weights() -> None:
    """把随安装包分发的 demucs 权重拷进用户 torch hub 缓存。

    demucs 的权重默认从 HuggingFace 下载，国内网络经常连不上；
    PyInstaller 包里带着 model_cache/（见 desktop/m2s.spec），首次
    运行时同步拷到 ~/.cache/torch/hub/checkpoints 即可离线使用。
    """
    if not getattr(sys, "frozen", False):
        return
    src = os.path.join(getattr(sys, "_MEIPASS", ""), "model_cache")
    if not os.path.isdir(src):
        return
    try:
        import torch
        dst = os.path.join(torch.hub.get_dir(), "checkpoints")
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(src):
            d = os.path.join(dst, f)
            if not os.path.exists(d):
                shutil.copyfile(os.path.join(src, f), d)
    except Exception:
        # 拷贝失败不致命：联网的机器仍可自行下载
        pass


def _get_separator(model: str, device: str, shifts: int):
    """按 (模型, 设备, shifts) 复用 Separator。

    每次新建 Separator 都会重新从磁盘加载数百 MB 权重（实测占单次识别
    时间的 80% 以上），缓存后同一进程内连续识别几乎不再有这项开销。
    """
    from demucs.api import Separator

    _ensure_bundled_weights()
    key = (model, device, shifts)
    with _SEP_LOCK:
        sep = _SEPARATORS.get(key)
        if sep is None:
            sep = Separator(model=model, device=device, shifts=shifts,
                            progress=False, jobs=0)
            _SEPARATORS[key] = sep
        return sep


def separate_stems(y: np.ndarray, sr: int, model: str = "htdemucs",
                   shifts: int = 1, device: Optional[str] = None):
    """返回 (音轨名 -> 单声道波形) 的字典，波形已重采样回输入采样率。"""
    if device is None:
        device = _pick_device()
    separator = _get_separator(model, device, shifts)
    _, stems = separator.separate_tensor(_to_stereo(y), sr=sr)
    # 注意：separate_tensor 返回 (重采样后的原始波形, 音轨字典)，取 [1] 才是分离结果
    out = {}
    for name, tensor in stems.items():
        mono = tensor.detach().float().mean(dim=0).cpu().numpy()
        mono = _resample_to(mono, separator.samplerate, sr)
        out[name] = np.ascontiguousarray(mono, dtype=np.float32)
    return out


def _default_model() -> str:
    """有 GPU 时用微调版（更准，约 2 倍耗时）；纯 CPU 用标准版，避免等到崩溃。"""
    import torch
    try:
        if torch.cuda.is_available():
            return "htdemucs_ft"
    except Exception:
        pass
    return "htdemucs"


def _default_inner() -> str:
    """分离之后用什么识别器：优先神经网络（CREPE），没有就退回 pYIN。"""
    from .base import get_transcriber
    for name in ("crepe", "pyin"):
        try:
            get_transcriber(name)
            return name
        except Exception:
            continue
    return "pyin"


def pick_melody_stem(stems: dict, mix: np.ndarray) -> tuple:
    """在人声与伴奏之间挑出更像主旋律的一轨。

    返回 (音轨名, 波形)；挑不出来时返回 ("mix", 原始混音)。
    """
    mix_rms = _rms(mix) or 1e-9
    best_name, best_track, best_score = "mix", mix, -1.0
    for name in ("vocals", "other", "bass", "drums"):
        track = stems.get(name)
        if track is None or not track.size:
            continue
        level = _rms(track) / mix_rms
        # 能量太低说明这轨基本是空的，直接跳过
        if level < 0.02:
            continue
        # 人声是主旋律的第一猜测，给固定偏好；其余按能量排序
        score = level + (1.0 if name == "vocals" else 0.0)
        if score > best_score:
            best_name, best_track, best_score = name, track, score
    return best_name, best_track


if _HAS_DEMUCS:

    @register
    class SongTranscriber(Transcriber):
        name = "song"
        label = "完整歌曲（先分离人声再转谱）"
        polyphonic = False
        # pYIN 的帧参数是按 22.05k 调过的，保持一致；demucs 内部会自行重采样到 44.1k
        input_sr = 22050
        slow = True
        hint = "适合带伴奏的歌曲：先分离人声，再用神经网络识别；最准也最慢"

        def __init__(self, inner: str = "", model: str = ""):
            self.inner_name = inner or _default_inner()
            self.model = model or _default_model()

        def transcribe(self, y: np.ndarray, sr: int,
                       progress: Optional[Callable[[float, str], None]] = None) -> List[Note]:
            from .base import get_transcriber

            def _p(v, msg=""):
                if progress:
                    progress(max(0.0, min(1.0, v)), msg)

            _p(0.06, f"音源分离（{_pick_device()}）…")
            stems = separate_stems(y, sr, model=self.model)
            _p(0.5, "选出主旋律轨…")
            stem_name, track = pick_melody_stem(stems, y)

            # 峰值归一，避免分离后音量过小影响音高检测
            peak = float(np.max(np.abs(track))) if track.size else 0.0
            if peak > 1e-6:
                track = (track / peak * 0.9).astype(np.float32)

            _p(0.55, f"识别旋律（{stem_name} 轨）…")
            inner = get_transcriber(self.inner_name)

            def sub(v, msg=""):
                _p(0.55 + v * 0.42, msg)

            return inner.transcribe(track, sr, sub)
