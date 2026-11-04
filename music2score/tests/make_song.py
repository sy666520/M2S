"""合成一段「完整歌曲」测试素材：人声旋律 + 和弦垫 + 贝斯 + 鼓。

用来验证音源分离（demucs）链路。同时输出人声轨的干净参考版本，
便于量化衡量「混合后 → 分离出 → 再识别」的损失。
"""
import os
import sys

import numpy as np
import soundfile as sf

SR = 44100
BPM = 100.0
SPB = 60.0 / BPM          # 每拍 0.6s
BARS = 12                  # 12 小节 ≈ 28.8s

# ---- 旋律（人声）：C 大调，一小节两音为主，音区 72~84 ----
# (MIDI, 起始拍, 时值拍)
MELODY = []
_MEL = [
    (72, 1), (72, 1), (79, 1), (79, 1),      # bar 1
    (81, 1), (81, 1), (79, 2),               # bar 2
    (77, 1), (77, 1), (76, 1), (76, 1),      # bar 3
    (74, 1), (74, 1), (72, 2),               # bar 4
    (79, 1), (79, 1), (81, 1), (81, 1),      # bar 5
    (83, 1), (83, 1), (81, 2),               # bar 6
    (79, 1), (77, 1), (76, 1), (74, 1),      # bar 7
    (72, 4),                                  # bar 8
    (76, 1), (77, 1), (79, 1), (81, 1),      # bar 9
    (79, 2), (76, 2),                        # bar 10
    (74, 1), (74, 1), (72, 1), (74, 1),      # bar 11
    (72, 4),                                  # bar 12
]
_b = 0.0
for _m, _d in _MEL:
    MELODY.append((_m, _b, _d))
    _b += _d

# ---- 和声：每小节一个和弦，C - Am - F - G 循环 ----
CHORDS = [(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]
BASS_ROOT = [36, 33, 29, 31]


def _env(n: int, sr: int, attack: float, release: float, sustain_level: float = 1.0):
    e = np.ones(n, dtype=np.float32)
    a = max(1, int(attack * sr))
    r = max(1, int(release * sr))
    if a < n:
        e[:a] = np.linspace(0.0, 1.0, a)
    if r < n:
        e[-r:] *= np.linspace(1.0, sustain_level, r)
    return e


def vocal(midi: int, dur: float, sr: int = SR) -> np.ndarray:
    """人声：基频 + 递减泛音 + 颤音 + 气声，模拟嗓音而非纯正弦。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    f = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    # 颤音：约 5.5Hz，深度约 0.8% 基频
    vib = 1.0 + 0.008 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * f * np.cumsum(vib) / sr
    wave = np.sin(phase)
    for h, amp in ((2, 0.5), (3, 0.28), (4, 0.14), (5, 0.07), (6, 0.03)):
        wave += amp * np.sin(h * phase + 0.3 * h)
    # 共振峰着色：让频谱不像乐器那样规整
    wave += 0.05 * np.sin(2 * np.pi * 2.6 * f * phase / (2 * np.pi))
    wave *= _env(n, sr, 0.03, 0.10, 0.7)
    # 气声噪声
    breath = np.random.default_rng(abs(midi) * 7 + n).standard_normal(n) * 0.012
    breath *= _env(n, sr, 0.02, 0.08)
    return ((wave + breath) * 0.5).astype(np.float32)


def pad(notes, dur: float, sr: int = SR) -> np.ndarray:
    """和弦垫：三角波叠加，柔和长音。"""
    n = int(dur * sr)
    t = np.arange(n) / sr
    out = np.zeros(n, dtype=np.float32)
    for i, m in enumerate(notes):
        f = 440.0 * (2.0 ** ((m - 69) / 12.0))
        # 轻微失谐让声音更宽
        for det in (-0.3, 0.0, 0.3):
            out += 0.33 * np.sin(2 * np.pi * (f + det) * t + i)
        out += 0.12 * np.sin(2 * np.pi * 2 * f * t)
    out *= _env(n, sr, 0.08, 0.20, 0.75)
    return (out * 0.16).astype(np.float32)


def bass(midi: int, dur: float, sr: int = SR) -> np.ndarray:
    n = int(dur * sr)
    t = np.arange(n) / sr
    f = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    w = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    w *= _env(n, sr, 0.006, 0.09, 0.5)
    return (w * 0.42).astype(np.float32)


def kick(sr: int = SR) -> np.ndarray:
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    f = 120.0 * np.exp(-t * 28) + 45.0
    w = np.sin(2 * np.pi * np.cumsum(f) / sr)
    w *= np.exp(-t * 9)
    return (w * 0.55).astype(np.float32)


def hat(sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(1234)
    n = int(0.06 * sr)
    w = rng.standard_normal(n).astype(np.float32)
    # 简易高通：一阶差分
    w = np.diff(w, prepend=0.0)
    w *= np.exp(-np.arange(n) / (0.012 * sr))
    return (w * 0.10).astype(np.float32)


def snare(sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(777)
    n = int(0.18 * sr)
    noise = rng.standard_normal(n).astype(np.float32) * np.exp(-np.arange(n) / (0.05 * sr))
    t = np.arange(n) / sr
    tone = 0.25 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 22)
    return ((noise * 0.5 + tone) * 0.30).astype(np.float32)


def _add(buf: np.ndarray, seg: np.ndarray, start_sample: int) -> None:
    s = int(start_sample)
    e = min(s + len(seg), len(buf))
    if s >= len(buf) or e <= 0:
        return
    buf[max(s, 0):e] += seg[: e - max(s, 0)]


def build():
    total_beats = BARS * 4
    n = int((total_beats * SPB + 1.2) * SR)
    mix = np.zeros(n, dtype=np.float32)
    vocal_only = np.zeros(n, dtype=np.float32)

    # 人声
    for midi, beat, dur in MELODY:
        seg = vocal(midi, dur * SPB)
        _add(mix, seg, beat * SPB * SR)
        _add(vocal_only, seg, beat * SPB * SR)

    # 和弦垫 + 贝斯 + 鼓（按小节铺）
    for bar in range(BARS):
        bar_start = int(bar * 4 * SPB * SR)
        triad = CHORDS[bar % 4]
        root = BASS_ROOT[bar % 4]
        _add(mix, pad(triad, 4 * SPB), bar_start)
        for b in (0.0, 2.0):
            _add(mix, bass(root, 0.9 * SPB), bar_start + int(b * SPB * SR))
        for b in (0.0, 2.0):
            _add(mix, kick(), bar_start + int(b * SPB * SR))
        for b in (1.0, 3.0):
            _add(mix, snare(), bar_start + int(b * SPB * SR))
        for i in range(8):
            _add(mix, hat(), bar_start + int(i * 0.5 * SPB * SR))

    def norm(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
        m = float(np.max(np.abs(x))) or 1.0
        return (x / m * peak).astype(np.float32)

    return norm(mix), norm(vocal_only, 0.8)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "data")
    os.makedirs(out_dir, exist_ok=True)

    mix, vox = build()
    p_mix = os.path.join(out_dir, "song.wav")
    p_vox = os.path.join(out_dir, "song_vocal_ref.wav")
    sf.write(p_mix, mix, SR)
    sf.write(p_vox, vox, SR)
    print(f"已生成 {p_mix}       （完整混音 {len(mix)/SR:.1f}s）")
    print(f"已生成 {p_vox} （人声参考轨 {len(vox)/SR:.1f}s）")
    print(f"旋律音符 {len(MELODY)} 个，{BARS} 小节 @ {BPM:.0f} BPM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
