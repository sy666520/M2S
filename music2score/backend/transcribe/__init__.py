"""识别层。

导入子模块即完成注册；可选依赖（basic-pitch / demucs）未安装时静默跳过，
界面上就不会列出用不了的引擎。
"""
from .base import Transcriber, register, get_transcriber, available_transcribers, REGISTRY

from . import pyin  # noqa: F401  单旋律识别，经典基线

try:
    from . import crepe  # noqa: F401  神经网络音高检测（需 pip install torchcrepe）
except Exception:
    pass

try:
    from . import basic_pitch  # noqa: F401  多声部（需 pip install basic-pitch）
except Exception:
    pass

try:
    from . import song  # noqa: F401  完整歌曲（需 pip install demucs）
except Exception:
    pass

__all__ = ["Transcriber", "register", "get_transcriber", "available_transcribers", "REGISTRY"]
