"""统一数据模型。

设计原则：识别层产出以「秒」为单位的原始音符，量化层转成以「拍」为单位，
之后所有渲染器只认「拍」，彼此完全解耦。
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Note:
    """原始音符：时间单位为秒。"""
    midi: int
    start: float
    duration: float
    velocity: float = 0.8


@dataclass
class QuantNote:
    """量化后的音符：时间单位为拍。"""
    midi: int
    beat: float          # 起始拍（0 = 第 0 拍）
    dur: float           # 时值，单位拍
    velocity: float = 0.8
    tied_from: bool = False   # 渲染用：本音符是否由前一音符延音而来


@dataclass
class Key:
    tonic_pc: int        # 主音 pitch class, 0=C
    mode: str            # 'major' | 'minor'

    @property
    def name(self) -> str:
        return f"{PITCH_CLASS_NAMES[self.tonic_pc]} {self.mode}"

    @property
    def fifths(self) -> int:
        """MusicXML 调号：升号数为正，降号数为负。"""
        table = MAJOR_FIFTHS_POS if self.mode == "major" else MINOR_FIFTHS_POS
        return table.get(self.tonic_pc, 0)


PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 调号圈上各大 / 小调对应的 fifths 值（升号为正，降号为负）
MAJOR_FIFTHS_POS = {
    0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: 7,
    5: -1, 10: -2, 3: -3, 8: -4,
}
MINOR_FIFTHS_POS = {
    9: 0, 4: 1, 11: 2, 6: 3, 1: 4, 8: 5, 3: 6, 10: 7,
    2: -1, 7: -2, 0: -3, 5: -4,
}


@dataclass
class Score:
    """一份完整乐谱的中间表示。"""
    notes: List[QuantNote]
    tempo: float
    meter: Tuple[int, int]
    key: Key
    grid: float                 # 量化网格，单位拍（0.25 = 十六分音符）
    total_beats: float
    source_duration: float      # 原始音频时长（秒）
    title: str = "Untitled"
    transcriber: str = "pyin"

    def beats_to_seconds(self, beat: float) -> float:
        return beat * 60.0 / self.tempo
