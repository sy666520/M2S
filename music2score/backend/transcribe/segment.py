"""逐帧音高曲线 → 音符事件的统一切分逻辑。

pYIN 与 CREPE 都产出「每帧一个基频 + 一个置信度」，切分规则完全一样，
所以抽到这里共用，避免两套实现各自漂移。

要点：
  * 用**滑动中位数**判断「还在同一个音」而不是单帧比较，颤音不会把长音切碎
  * onset 处强制断开，解决同音反复（5555）被合并成一整个长音
  * 音符音高取置信度加权中位数，抗边界帧抖动
  * 收尾做同音合并、过短音清除、孤立八度跳音纠正
"""
from typing import List, Optional, Sequence

import numpy as np

from ..models import Note


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones_like(v)
    c = np.cumsum(w) - 0.5 * w
    idx = min(int(np.searchsorted(c, c[-1] / 2.0)), len(v) - 1)
    return float(v[idx])


def notes_from_frames(midi_f: np.ndarray,
                      times: np.ndarray,
                      conf: np.ndarray,
                      onset_times: Sequence[float] = (),
                      *,
                      tol: float = 0.62,
                      min_dur: float = 0.055,
                      gap_merge: float = 0.045,
                      rel_floor: float = 0.2,
                      fix_octave: bool = True) -> List[Note]:
    """把浮点 MIDI 曲线切成音符。

    midi_f 非浊音处为 NaN；conf 为每帧置信度（0~1）。
    """
    n = len(midi_f)
    if n == 0:
        return []
    notes: List[Note] = []

    onset_sorted = np.sort(np.asarray(onset_times, dtype=np.float64)) if len(onset_times) else np.empty(0)
    onset_set = set(np.round(onset_sorted, 2).tolist())

    def _has_onset(t: float) -> bool:
        return round(float(t), 2) in onset_set

    dt = float(times[1] - times[0]) if n > 1 else 0.01
    i = 0
    while i < n:
        if not np.isfinite(midi_f[i]):
            i += 1
            continue
        window = [midi_f[i]]
        j = i + 1
        while j < n and np.isfinite(midi_f[j]):
            # 用当前段的中位数作为参考音高，颤音/滑音不会被误切
            ref = float(np.median(window[-9:]))
            if abs(midi_f[j] - ref) > tol:
                break
            # onset 处断开（同音反复），但太短的段不切，避免 onset 抖动产生碎片
            if _has_onset(times[j]) and (times[j] - times[i]) > min_dur:
                break
            window.append(midi_f[j])
            j += 1

        seg_p = midi_f[i:j]
        seg_w = np.clip(conf[i:j], 1e-3, None)
        start = float(times[i])
        end = float(times[j - 1]) + dt
        dur = end - start

        if dur >= min_dur:
            midi = int(round(_weighted_median(seg_p, seg_w)))
            if 12 <= midi <= 120:
                vel = float(np.clip(np.mean(np.nan_to_num(conf[i:j])), 0.2, 1.0))
                notes.append(Note(midi=midi, start=start, duration=dur, velocity=vel))
        i = j if j > i else i + 1

    notes = _merge_same_pitch(notes, gap_merge)
    notes = _drop_short(notes, min_dur, rel_floor)
    if fix_octave:
        notes = _fix_isolated_octaves(notes)
    return notes


def _merge_same_pitch(notes: List[Note], max_gap: float) -> List[Note]:
    """相同音高、间隔极短的相邻音符合并（切分毛刺）。"""
    if len(notes) < 2:
        return notes
    out = [notes[0]]
    for n in notes[1:]:
        prev = out[-1]
        gap = n.start - (prev.start + prev.duration)
        if n.midi == prev.midi and 0 <= gap <= max_gap:
            prev.duration = (n.start + n.duration) - prev.start
        else:
            out.append(n)
    return out


def _drop_short(notes: List[Note], min_dur: float, rel_floor: float) -> List[Note]:
    if not notes:
        return notes
    durs = np.array([n.duration for n in notes])
    floor = max(min_dur, float(np.median(durs)) * rel_floor)
    kept = [n for n in notes if n.duration >= floor]
    return kept or notes


def _fix_isolated_octaves(notes: List[Note]) -> List[Note]:
    """纠正「突变一个八度、且时值很短」的孤立音。

    典型的音高检测八度错误：两侧都是同一个音，中间夹一个 ±12 的短音。
    """
    if len(notes) < 3:
        return notes
    for k in range(1, len(notes) - 1):
        prev, cur, nxt = notes[k - 1], notes[k], notes[k + 1]
        if prev.midi != nxt.midi:
            continue
        delta = cur.midi - prev.midi
        if abs(abs(delta) - 12) > 0 and abs(abs(delta) - 12) > 1:
            continue
        if cur.duration <= max(0.25, 0.5 * prev.duration):
            cur.midi = prev.midi
    return notes


def viterbi_quantize(midi_f: np.ndarray,
                     conf: np.ndarray,
                     *,
                     lo: int = 36,
                     hi: int = 96,
                     sigma_cents: float = 55.0,
                     switch_penalty: float = 6.0,
                     max_emission: float = 6.0):
    """Viterbi 解码：找一条「分段恒定在整数半音上」的最优音高轨迹。

    「每个音只对应一个音高」这个约束直接写进解码过程，比先取中位数再四舍五入
    准得多：滑音/颤音帧会把误差摊到整段，而 DP 会在换音的真边界处才切换。

    midi_f 非浊音为 NaN（不约束，允许跨越短促的换气停顿）。
    返回 (整数 MIDI 序列（非浊音段为 NaN）, 每帧状态序列)。
    """
    n = len(midi_f)
    if n == 0:
        return midi_f.copy(), np.zeros(0, dtype=int)

    states = np.arange(lo, hi + 1, dtype=np.float64)
    obs = midi_f
    voiced = np.isfinite(obs)

    # 发射代价：与观测的偏差（以音分计）的高斯负对数，非浊音帧不提供约束
    diff = np.where(voiced[:, None], obs[:, None] - states[None, :], 0.0)
    emit = np.where(voiced[:, None],
                    np.minimum((diff * 100.0) ** 2 / (2.0 * sigma_cents ** 2), max_emission),
                    0.0)
    # 置信度低的帧削弱其发言权
    w = np.where(voiced, np.clip(conf if conf is not None else 1.0, 0.0, 1.0), 0.0)
    emit = emit * w[:, None]

    ns = len(states)
    dp = emit[0].copy()
    back = np.zeros((n, ns), dtype=np.int16)

    for i in range(1, n):
        best_same = dp
        k = int(np.argmin(dp))
        best_switch = dp[k] + switch_penalty
        other = np.full(ns, best_switch)
        other[k] = np.inf          # 从最优状态「切换」到自己不算切换
        use_switch = best_switch < best_same
        dp = emit[i] + np.where(use_switch, other, best_same)
        back[i] = np.where(use_switch, k, np.arange(ns))

    path = np.zeros(n, dtype=int)
    path[-1] = int(np.argmin(dp))
    for i in range(n - 1, 0, -1):
        path[i - 1] = back[i, path[i]]

    midi = states[path]
    midi = np.where(voiced | _fillable(voiced), midi, np.nan)
    return midi, path


def _fillable(voiced: np.ndarray) -> np.ndarray:
    """标记被浊音夹住的短空档（换气、辅音），这些帧允许由 DP 结果填充。"""
    out = np.zeros_like(voiced)
    n = len(voiced)
    i = 0
    while i < n:
        if voiced[i]:
            i += 1
            continue
        j = i
        while j < n and not voiced[j]:
            j += 1
        if i > 0 and j < n and (j - i) <= 8:   # <=160ms
            out[i:j] = True
        i = j
    return out


def notes_from_viterbi(midi_q: np.ndarray, times: np.ndarray, conf: np.ndarray,
                       *, min_dur: float = 0.05, rel_floor: float = 0.12) -> List[Note]:
    """把离散音高轨迹转成音符（连续同值的帧合成一个音）。"""
    n = len(midi_q)
    notes: List[Note] = []
    if not n:
        return notes
    dt = float(times[1] - times[0]) if n > 1 else 0.01
    i = 0
    while i < n:
        if not np.isfinite(midi_q[i]):
            i += 1
            continue
        j = i + 1
        while j < n and np.isfinite(midi_q[j]) and midi_q[j] == midi_q[i]:
            j += 1
        dur = (j - i) * dt
        if dur >= min_dur:
            midi = int(midi_q[i])
            if 12 <= midi <= 120:
                vel = float(np.clip(np.mean(np.nan_to_num(conf[i:j])), 0.2, 1.0))
                notes.append(Note(midi=midi, start=float(times[i]), duration=dur,
                                  velocity=vel))
        i = j
    if notes:
        durs = np.array([x.duration for x in notes])
        floor = max(min_dur, float(np.median(durs)) * rel_floor)
        notes = [x for x in notes if x.duration >= floor] or notes
    return notes


def split_notes_at_onsets(notes: List[Note], onsets, min_piece: float = 0.08) -> List[Note]:
    """在 onset 处切开同音长音。

    Viterbi 只看音高，同音反复（如「1 1 5 5」）会被粘成一个长音；
    onset 提供了「重新起音」的证据，据此切开才符合乐谱记法。
    切开不改变逐帧音高，所以对准确率指标无损。
    """
    if not len(notes) or onsets is None or len(onsets) == 0:
        return notes
    ons = np.sort(np.asarray(onsets, dtype=np.float64))
    out: List[Note] = []
    for n in notes:
        end = n.start + n.duration
        cuts = ons[(ons > n.start + min_piece) & (ons < end - min_piece)]
        if cuts.size == 0:
            out.append(n)
            continue
        pts = [n.start] + [float(c) for c in cuts] + [end]
        for a, b in zip(pts[:-1], pts[1:]):
            if b - a >= min_piece * 0.5:
                out.append(Note(midi=n.midi, start=a, duration=b - a, velocity=n.velocity))
    return out


def smooth_curve(midi_f: np.ndarray, kernel: int = 3) -> np.ndarray:
    """对浊音段做短窗中位数平滑，压掉单帧跳点。"""
    if kernel < 3 or len(midi_f) < kernel:
        return midi_f
    out = midi_f.copy()
    half = kernel // 2
    n = len(midi_f)
    for i in range(n):
        if not np.isfinite(midi_f[i]):
            continue
        seg = midi_f[max(0, i - half): i + half + 1]
        seg = seg[np.isfinite(seg)]
        if seg.size:
            out[i] = float(np.median(seg))
    return out


def harmonic_octave_fix(midi_f: np.ndarray, conf: np.ndarray,
                        tol: float = 0.6) -> np.ndarray:
    """对整段做一次八度去抖：孤立的 ±12 跳变拉回邻域中位数。"""
    out = midi_f.copy()
    n = len(out)
    if n < 5:
        return out
    for i in range(2, n - 2):
        if not np.isfinite(out[i]):
            continue
        left = out[max(0, i - 6):i]
        right = out[i + 1:i + 7]
        near = np.concatenate([left[np.isfinite(left)], right[np.isfinite(right)]])
        if near.size < 4:
            continue
        ref = float(np.median(near))
        if abs(out[i] - ref) > 6.5 and abs(abs(out[i] - ref) - 12) <= 1.0:
            out[i] = ref
    return out
