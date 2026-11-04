"""音频解码层：把任意常见音频统一成单声道 float32 波形。

优先用 ffmpeg 解码（mp3 / m4a / wma / flac / ogg 全覆盖），
ffmpeg 缺失时退回 soundfile 直读（wav / flac / ogg，新版 libsndfile 也支持 mp3）。
"""
import os
import shutil
import subprocess
import tempfile
from typing import Tuple

import numpy as np
import soundfile as sf

_FFMPEG_CACHE = {"path": None}


def ffmpeg_path() -> str:
    if _FFMPEG_CACHE["path"] is None:
        path = ""
        try:
            import imageio_ffmpeg
            # 0.8 起只有 get_ffmpeg_exe，老版本才有 get_exe_path
            getter = getattr(imageio_ffmpeg, "get_ffmpeg_exe", None) \
                or getattr(imageio_ffmpeg, "get_exe_path", None)
            if getter:
                path = getter() or ""
        except Exception:
            path = ""
        if not path:
            path = shutil.which("ffmpeg") or ""
        _FFMPEG_CACHE["path"] = path
    return _FFMPEG_CACHE["path"]


def has_ffmpeg() -> bool:
    return bool(ffmpeg_path())


def _resample(y: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return y
    try:
        import librosa
        return librosa.resample(y, orig_sr=src_sr, target_sr=dst_sr).astype(np.float32)
    except Exception:
        import scipy.signal as signal
        g = math_gcd(src_sr, dst_sr)
        return signal.resample_poly(y, dst_sr // g, src_sr // g).astype(np.float32)


def math_gcd(a: int, b: int) -> int:
    import math
    return math.gcd(a, b)


def _decode_with_ffmpeg(src: str, sr: int) -> np.ndarray:
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg not available")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        cmd = [
            ff, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src,
            "-vn",                 # 丢弃封面图
            "-ac", "1",            # 单声道
            "-ar", str(sr),
            "-sample_fmt", "s16",
            tmp.name,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        y, got_sr = sf.read(tmp.name, dtype="float32")
        if got_sr != sr:
            y = _resample(y, got_sr, sr)
        return np.asarray(y, dtype=np.float32)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def load_audio(path: str, sr: int = 22050) -> Tuple[np.ndarray, int]:
    """返回 (单声道 float32 波形, 采样率)。"""
    y = None
    if has_ffmpeg():
        try:
            y = _decode_with_ffmpeg(path, sr)
        except Exception:
            y = None
    if y is None:
        y, got_sr = sf.read(path, dtype="float32", always_2d=False)
        if getattr(y, "ndim", 1) > 1:
            y = np.mean(y, axis=1)
        if got_sr != sr:
            y = _resample(np.asarray(y, dtype=np.float32), got_sr, sr)
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    # 去掉直流偏移，避免影响能量检测
    if y.size:
        y = y - float(np.mean(y))
    return y, sr
