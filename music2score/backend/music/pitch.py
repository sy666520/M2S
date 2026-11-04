"""音高 / 音名 / 简谱度数换算工具。"""
import math
from typing import Tuple, Optional

from ..models import PITCH_CLASS_NAMES

NOTE_STEPS = ["C", "D", "E", "F", "G", "A", "B"]
STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# 大调音阶：半音偏移 -> 唱名 1-7
MAJOR_DEGREE = {0: 1, 2: 2, 4: 3, 5: 4, 7: 5, 9: 6, 11: 7}
# 变化音的简谱记法（升号一侧）
ALTER_TO_SHARP = {1: (1, "#"), 3: (2, "#"), 6: (4, "#"), 8: (5, "#"), 10: (6, "#")}


def hz_to_midi(hz: float) -> float:
    if hz <= 0:
        return float("-inf")
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def midi_to_name(midi: int) -> str:
    """60 -> 'C4'（科学音高记号，中央 C = C4）。"""
    return f"{PITCH_CLASS_NAMES[midi % 12]}{midi // 12 - 1}"


def midi_to_step_octave(midi: int) -> Tuple[str, int, int]:
    """返回 (step, alter, octave)，alter 为 -1/0/1，用于 MusicXML <pitch>。"""
    pc = midi % 12
    octave = midi // 12 - 1
    # 优先用不带变音记号的音名，其次升号
    natural = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    for step, semi in natural.items():
        if semi == pc:
            return step, 0, octave
    for step, semi in natural.items():
        if semi == pc - 1:
            return step, 1, octave
    return "C", 0, octave


def jianpu_symbol(midi: int, tonic_pc: int) -> Tuple[str, int]:
    """把 MIDI 音高转成简谱符号。

    返回 (文本, 八度点数)：点数 > 0 表示高音（数字上方加点），< 0 表示低音。
    变化音在数字前加 '#'，如 '#4'。
    """
    # 参考点：使 tonic 落在中央八度（MIDI 60..71）
    ref = 60 + ((tonic_pc - 60) % 12)
    interval = midi - ref
    dots = interval // 12
    semi = interval % 12
    rel = (semi - 0) % 12  # 相对主音的半音数

    if rel in MAJOR_DEGREE:
        return str(MAJOR_DEGREE[rel]), dots
    if rel in ALTER_TO_SHARP:
        deg, sign = ALTER_TO_SHARP[rel]
        return f"{sign}{deg}", dots
    # 兜底：按半音映射到最近的级数
    nearest = min(MAJOR_DEGREE.keys(), key=lambda k: abs(k - rel))
    return str(MAJOR_DEGREE[nearest]), dots


def freq_to_note_name_approx(midi_float: float) -> str:
    return midi_to_name(int(round(midi_float)))
