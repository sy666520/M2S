"""生成测试用旋律音频。

默认合成《小星星》前两句（C 大调，四分音符 0.5s），带轻微泛音与 ADSR，
让基频检测面对的不是纯正弦，更接近真实乐器。
"""
import os
import sys

import numpy as np
import soundfile as sf

SR = 22050

# (MIDI, 起始拍, 时值拍)
TWINKLE = [
    (60, 0, 1), (60, 1, 1), (67, 2, 1), (67, 3, 1),
    (69, 4, 1), (69, 5, 1), (67, 6, 2),
    (65, 8, 1), (65, 9, 1), (64, 10, 1), (64, 11, 1),
    (62, 12, 1), (62, 13, 1), (60, 14, 2),
]

# 音阶（含八分音符，用来验证更细的量化网格）
SCALE = [
    (60, 0, 0.5), (62, 0.5, 0.5), (64, 1, 0.5), (65, 1.5, 0.5),
    (67, 2, 1), (69, 3, 1),
    (67, 4, 0.5), (65, 4.5, 0.5), (64, 5, 1), (62, 6, 2),
]


def synth_note(midi: int, dur: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(dur * sr)) / sr
    f = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    wave = np.sin(2 * np.pi * f * t)
    wave += 0.34 * np.sin(2 * np.pi * 2 * f * t)
    wave += 0.16 * np.sin(2 * np.pi * 3 * f * t)
    wave += 0.06 * np.sin(2 * np.pi * 4 * f * t)

    # ADSR：快速起音 + 指数衰减，制造清晰的 onset
    n = len(t)
    a = int(0.012 * sr)
    r = int(0.12 * sr)
    env = np.ones(n)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if r:
        env[-r:] *= np.linspace(1, 0.15, r)
    env *= np.exp(-t * 0.9)
    return (wave * env).astype(np.float32)


def build(notes, bpm: float = 120.0, sr: int = SR, gap: float = 0.02) -> np.ndarray:
    spb = 60.0 / bpm
    total = max(int(((max(n[1] + n[2] for n in notes)) * spb + 0.6) * sr), sr)
    out = np.zeros(total, dtype=np.float32)
    for midi, beat, dur in notes:
        seg = synth_note(midi, dur * spb - gap, sr)
        start = int(beat * spb * sr)
        end = min(start + len(seg), total)
        out[start:end] += seg[: end - start]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.85).astype(np.float32)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "data")
    os.makedirs(out_dir, exist_ok=True)

    for name, seq, bpm in (("twinkle", TWINKLE, 120.0), ("scale", SCALE, 96.0)):
        y = build(seq, bpm=bpm)
        path = os.path.join(out_dir, f"{name}.wav")
        sf.write(path, y, SR)
        print(f"已生成 {path}  ({len(y) / SR:.2f}s, {bpm} BPM)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
