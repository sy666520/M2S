"""完整歌曲链路验收：混音 -> demucs 分离 -> 旋律识别 -> 与真值比对。

用法：
    py -3.10 tests/test_song.py            # 跑完整 30s
    py -3.10 tests/test_song.py --seconds 8  # 只跑前 8 秒（快速验证）
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.audio import load_audio                # noqa: E402
from backend.pipeline import transcribe_audio       # noqa: E402
from backend.transcribe.base import available_transcribers, get_transcriber  # noqa: E402
from backend.transcribe.song import pick_melody_stem, separate_stems  # noqa: E402

from make_song import MELODY, SPB  # noqa: E402  (tests 目录已在 sys.path)


def ground_truth():
    """把 (midi, 起始拍, 时值拍) 展开成 (起始秒, 结束秒, midi)。"""
    return [(m, b * SPB, (b + d) * SPB) for m, b, d in MELODY]


def evaluate(score, gt):
    """在每个真值音符的中点取样，看识别结果是否命中同一音高。

    score.notes 用的是「拍」，真值是「秒」，按识别出的速度换算后再比对。
    """
    spb = 60.0 / score.tempo
    notes = [(n.beat, n.dur, n.midi) for n in score.notes]
    hit = miss = octave = 0
    wrong = []
    for midi, t0, t1 in gt:
        mid = (t0 + t1) / 2.0 / spb          # 秒 -> 拍
        found = None
        for b, d, m in notes:
            if b - 1e-6 <= mid <= b + d + 1e-6:
                found = m
                break
        if found is None:
            miss += 1
            wrong.append((mid, None, midi))
        elif found == midi:
            hit += 1
        elif abs(found - midi) % 12 == 0:
            octave += 1
        else:
            miss += 1
            wrong.append((mid, found, midi))
    total = len(gt)
    return hit, octave, miss, total, wrong, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=0.0, help="只取前 N 秒")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "data", "song.wav")
    if not os.path.exists(src):
        print("缺少素材，先运行 tests/make_song.py")
        return 2

    print("可用识别器：")
    for t in available_transcribers():
        print(f"  - {t['name']:>6}  {t['label']}" + ("  [慢]" if t.get("slow") else ""))
    print()

    y, sr = load_audio(src, sr=22050)
    if args.seconds > 0:
        y = y[: int(args.seconds * sr)]
    print(f"素材：{len(y)/sr:.1f}s @ {sr}Hz")

    # ---- 1. 单独看分离效果 ----
    t0 = time.time()
    stems = separate_stems(y, sr)
    dt = time.time() - t0
    print(f"\n[分离] 用时 {dt:.1f}s，产出音轨：{list(stems)}")
    mix_rms = float(np.sqrt(np.mean(y ** 2))) or 1e-9
    for name in ("vocals", "other", "bass", "drums"):
        if name in stems:
            r = float(np.sqrt(np.mean(stems[name] ** 2)))
            print(f"   {name:<7} 相对能量 {r/mix_rms:5.2f}")
    stem_name, _ = pick_melody_stem(stems, y)
    print(f"   选中主旋律轨：{stem_name}")

    # ---- 2. 跑完整流水线 ----
    print("\n[转谱] 完整歌曲模式…")
    t0 = time.time()

    def prog(v, msg=""):
        print(f"   {v*100:5.1f}%  {msg}", flush=True)

    score = transcribe_audio(src, "song", title="song", progress=prog)
    print(f"   总耗时 {time.time()-t0:.1f}s")

    gt = ground_truth()
    hit, octave, miss, total, wrong, notes = evaluate(score, gt)
    acc = hit / total * 100 if total else 0.0
    print(f"\n[结果] 音符 {len(notes)} 个 / 真值 {total} 个")
    print(f"   音高准确率 {acc:.1f}%  （完全命中 {hit}，八度偏差 {octave}，错误 {miss}）")
    print(f"   调性 {score.key}   拍号 {score.meter[0]}/{score.meter[1]}   "
          f"速度 {score.tempo:.0f} BPM")
    if wrong[:8]:
        print("   错例（时间 / 识别 / 真值）：")
        for t, f, g in wrong[:8]:
            print(f"     {t:6.2f}s   {f}   ->   {g}")

    # ---- 3. 对照：不分离直接识别 ----
    print("\n[对照] 不分离、直接在混音上跑 pYIN：")
    score2 = transcribe_audio(src, "pyin", title="song")
    hit2, oct2, miss2, total2, _, notes2 = evaluate(score2, gt)
    print(f"   音符 {len(notes2)} 个，音高准确率 {hit2/total2*100:.1f}%")

    print(f"\n提升：{acc - hit2/total2*100:+.1f} 个百分点")
    return 0 if acc >= 60 else 1


if __name__ == "__main__":
    sys.exit(main())
