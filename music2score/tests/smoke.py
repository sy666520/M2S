"""端到端冒烟测试：合成音频 -> 转谱 -> 三种谱面 + MIDI/MusicXML 导出。

用法：
    python tests/smoke.py            只跑测试
    python tests/smoke.py --keep     保留产物到 data/out/
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from backend.pipeline import transcribe_audio                 # noqa: E402
from backend.renderers.staff import render_staff_pages        # noqa: E402
from backend.renderers.jianpu import render_jianpu_pages      # noqa: E402
from backend.renderers.tab import render_tab_pages            # noqa: E402
from backend.renderers.musicxml import build_musicxml         # noqa: E402
from backend.renderers.midi import build_midi                 # noqa: E402
from backend.music.pitch import midi_to_name                  # noqa: E402

DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "out")

EXPECT = {
    "twinkle": [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60],
    "scale": [60, 62, 64, 65, 67, 69, 67, 65, 64, 62],
}


def check(name, score):
    print(f"\n=== {name} ===")
    print(f"  tempo={score.tempo}  meter={score.meter}  key={score.key.name}  grid={score.grid}")
    print(f"  notes={len(score.notes)}  beats={score.total_beats}")
    got = [n.midi for n in score.notes]
    print("  pitches:", " ".join(midi_to_name(m) for m in got))

    exp = EXPECT[name]
    # 只比对音高序列（八度误差单独统计）
    matched = sum(1 for g, e in zip(got, exp) if g == e)
    oct_off = sum(1 for g, e in zip(got, exp) if g != e and (g - e) % 12 == 0)
    acc = matched / max(len(exp), 1)
    print(f"  音高准确率: {matched}/{len(exp)} = {acc:.0%}  (八度偏差 {oct_off})")
    if len(got) != len(exp):
        print(f"  ⚠ 音符数量 {len(got)}，期望 {len(exp)}")
    return acc, len(got)


def main():
    keep = "--keep" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    ok = True

    for name in ("twinkle", "scale"):
        path = os.path.join(DATA, f"{name}.wav")
        if not os.path.exists(path):
            print(f"缺少测试音频 {path}，请先运行 tests/make_sample.py")
            return 1

        t0 = time.time()
        score = transcribe_audio(path, "pyin", title=name,
                                 progress=lambda v, m: None)
        elapsed = time.time() - t0
        acc, cnt = check(name, score)
        print(f"  耗时 {elapsed:.2f}s")
        if acc < 0.6 or cnt == 0:
            ok = False
            print("  ✗ 识别质量不达标")

        # 三种谱面
        for label, fn in (("staff", render_staff_pages),
                          ("jianpu", render_jianpu_pages),
                          ("tab", render_tab_pages)):
            try:
                pages = fn(score, name)
                sizes = [len(p) for p in pages]
                print(f"  {label}: {len(pages)} 页, {sum(sizes)/1024:.1f} KB")
                if keep:
                    for i, p in enumerate(pages):
                        with open(os.path.join(OUT, f"{name}_{label}_{i+1}.svg"),
                                  "w", encoding="utf-8") as f:
                            f.write(p)
            except Exception as e:
                ok = False
                print(f"  ✗ {label} 渲染失败: {type(e).__name__}: {e}")

        # 导出
        try:
            midi_bytes = build_midi(score)
            print(f"  midi: {len(midi_bytes)} bytes")
            if keep:
                with open(os.path.join(OUT, f"{name}.mid"), "wb") as f:
                    f.write(midi_bytes)
        except Exception as e:
            ok = False
            print(f"  ✗ MIDI 导出失败: {e}")

        try:
            xml = build_musicxml(score, name)
            print(f"  musicxml: {len(xml)} chars")
            if keep:
                with open(os.path.join(OUT, f"{name}.musicxml"), "w", encoding="utf-8") as f:
                    f.write(xml)
        except Exception as e:
            ok = False
            print(f"  ✗ MusicXML 生成失败: {e}")

    print("\n" + ("✅ 全部通过" if ok else "❌ 存在失败项"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
