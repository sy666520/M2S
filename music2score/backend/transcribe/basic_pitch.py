"""多声部识别：Google Magenta basic-pitch。

需要额外安装（约 500MB，含 tensorflow）：
    pip install basic-pitch
依赖就绪后会自动出现在可用识别器列表中，无需改动上层代码。
"""
import numpy as np

from ..models import Note
from .base import Transcriber, register, REGISTRY

try:
    from basic_pitch.inference import predict as _bp_predict  # noqa: F401
    _HAS_BASIC_PITCH = True
except Exception:
    _HAS_BASIC_PITCH = False


if _HAS_BASIC_PITCH:

    @register
    class BasicPitchTranscriber(Transcriber):
        name = "basic-pitch"
        label = "basic-pitch 多声部识别（钢琴/合奏）"
        polyphonic = True

        def transcribe(self, y: np.ndarray, sr: int, progress=None) -> list:
            import tempfile, os
            import soundfile as sf
            from basic_pitch.inference import predict

            def _p(v, msg=""):
                if progress:
                    progress(v, msg)

            _p(0.15, "多声部音符检测中…")
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            try:
                sf.write(tmp.name, y, sr)
                model_output, midi_data, note_events = predict(tmp.name)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

            _p(0.8, "整理音符…")
            notes = []
            for start, end, pitch, vel, _ in note_events:
                # basic-pitch 的 pitch 是 MIDI 号
                notes.append(Note(midi=int(round(pitch)), start=float(start),
                                  duration=max(float(end - start), 0.03),
                                  velocity=0.8))
            notes.sort(key=lambda n: n.start)
            return notes

else:
    # 依赖未安装：不注册，避免在界面上列出无法使用的选项
    pass
