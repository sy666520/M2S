"""识别层抽象接口。

新增一种识别算法（basic-pitch 多声部、demucs + pyin 等）只需实现 Transcriber，
在 registry 中注册即可，上层流水线与渲染器无需改动。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable

import numpy as np

from ..models import Note


class Transcriber(ABC):
    name: str = "base"
    label: str = "基础识别器"
    # 是否支持多声部（渲染层据此决定是否按声部拆分）
    polyphonic: bool = False
    # 期望的输入采样率：流水线按此值解码，避免二次重采样
    input_sr: int = 22050
    # 给前端的简短说明
    hint: str = ""
    # 是否耗时较长（前端据此提示用户）
    slow: bool = False
    # 是否作为默认引擎（前端优先选中）
    preferred: bool = False

    @abstractmethod
    def transcribe(self, y: np.ndarray, sr: int,
                   progress: Optional[Callable[[float, str], None]] = None) -> List[Note]:
        """输入单声道波形，输出音符列表（时间单位：秒）。"""
        raise NotImplementedError


REGISTRY: dict = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get_transcriber(name: str) -> Transcriber:
    if name not in REGISTRY:
        raise KeyError(f"未注册的识别器: {name}，可用: {list(REGISTRY)}")
    return REGISTRY[name]()


def available_transcribers() -> List[dict]:
    items = [
        {"name": c.name, "label": c.label, "polyphonic": c.polyphonic,
         "hint": c.hint, "slow": c.slow, "preferred": c.preferred}
        for c in REGISTRY.values()
    ]
    # 让前端有明确默认项：优先 preferred，其次第一个
    if not any(i["preferred"] for i in items) and items:
        items[0]["preferred"] = True
    return items
