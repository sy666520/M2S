"""吉他六线谱（TAB）SVG 渲染。

- 标准调弦 EADGBE，自上而下为 1-6 弦
- 指法用「贴近前一音手型 + 偏低把位」的启发式打分自动选把
- 谱面上方叠一条节奏条，直观表达时值（简化 TAB 不画符干）
"""
import math
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

from ..models import Score

PAGE_W = 1760
PAD_L = 78
PAD_R = 58
BEAT_W = 46
GAP = 19            # 弦间距
TOP_PAD = 40        # 节奏条区域
LINE_H = 5 * GAP + 92
MAX_BARS_PER_LINE = 6
LINES_PER_PAGE = 5

INK = "#1e1c19"
MUTED = "#8a8378"
RULE = "#b0a791"

# 1-6 弦空弦音（从上到下）
OPEN_STRINGS = [64, 59, 55, 50, 45, 40]
STRING_LABELS = ["E", "B", "G", "D", "A", "E"]
MAX_FRET = 22
LOW, HIGH = 40, 88


def _fit_range(midi: int) -> int:
    m = midi
    while m < LOW:
        m += 12
    while m > HIGH:
        m -= 12
    return m


def _choose_position(midi: int, prev: Optional[List[int]]) -> Optional[Tuple[int, int]]:
    """返回 (弦序号 0-5, 品格)。"""
    best = None
    for s, open_m in enumerate(OPEN_STRINGS):
        fret = midi - open_m
        if 0 <= fret <= MAX_FRET:
            cost = fret * 0.10
            if prev is not None:
                cost += abs(fret - prev[s]) * 0.55
                # 轻微偏好同弦延续，减少跳弦
                if fret == prev[s]:
                    cost -= 0.15
            else:
                cost += fret * 0.02
            if best is None or cost < best[0]:
                best = (cost, s, fret)
    if best is None:
        return None
    return best[1], best[2]


def build_tab(score: Score) -> List[dict]:
    """为量化后的每个音符分配指法。"""
    prev = None
    out = []
    for n in sorted(score.notes, key=lambda x: x.beat):
        m = _fit_range(n.midi)
        pos = _choose_position(m, prev)
        if pos is None:
            continue
        s, fret = pos
        if prev is None:
            prev = [0] * 6
        prev[s] = fret
        out.append({"beat": n.beat, "dur": n.dur, "string": s, "fret": fret, "midi": m})
    return out


def render_tab_pages(score: Score, title: str = None) -> List[str]:
    items = build_tab(score)
    if not items:
        return [_empty_svg("没有可映射到吉他的音符")]

    bpb = max(1, score.meter[0])
    total = items[-1]["beat"] + items[-1]["dur"]
    n_bars = max(1, int(math.ceil((total + 1e-6) / bpb)))
    avail = PAGE_W - PAD_L - PAD_R
    bar_w = bpb * BEAT_W
    bars_per_line = max(1, min(MAX_BARS_PER_LINE, int(avail // bar_w) or 1))

    line_specs = []
    bar_idx = 0
    while bar_idx < n_bars:
        n = min(bars_per_line, n_bars - bar_idx)
        line_specs.append((bar_idx, n))
        bar_idx += n
    page_w = max(n for _, n in line_specs) * bar_w + PAD_L + PAD_R

    lines = []
    first = True
    for bar_idx, n in line_specs:
        start_beat = bar_idx * bpb
        end_beat = start_beat + n * bpb
        seg = [it for it in items if start_beat - 1e-6 <= it["beat"] < end_beat]
        row_x = PAD_L + (page_w - PAD_L - PAD_R - n * bar_w) / 2
        lines.append(_render_line(seg, start_beat, n, bpb, score, row_x=row_x, page_w=page_w,
                                  header=(title or score.title) if first else None))
        first = False

    pages = []
    for i in range(0, len(lines), LINES_PER_PAGE):
        chunk = lines[i:i + LINES_PER_PAGE]
        top = 62 if i == 0 else 30
        h = top + len(chunk) * LINE_H + 34
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}" height="{h}" '
                 f'viewBox="0 0 {page_w} {h}" class="score-svg">']
        y = top
        for s in chunk:
            parts.append(f'<g transform="translate(0,{y})">{s}</g>')
            y += LINE_H
        parts.append("</svg>")
        pages.append("".join(parts))
    return pages


def _render_line(items, start_beat, n_bars, bpb, score, row_x=PAD_L, page_w=PAGE_W, header=None):
    parts = []
    bar_w = bpb * BEAT_W
    top = TOP_PAD
    bottom = top + 5 * GAP

    if header:
        parts.append(f'<text x="{page_w / 2:.0f}" y="-6" font-size="17" fill="{INK}" '
                     f'text-anchor="middle" font-family="Georgia, serif" font-weight="600">'
                     f"{escape(str(header))}</text>")

    def x_of(beat: float) -> float:
        return row_x + (beat - start_beat) * BEAT_W

    # 弦名
    for s in range(6):
        y = top + s * GAP
        parts.append(f'<text x="{row_x - 16:.1f}" y="{y + 4:.1f}" font-size="12" '
                     f'text-anchor="end" fill="{MUTED}" font-family="Georgia, serif">'
                     f"{STRING_LABELS[s]}</text>")

    # 六条弦
    for s in range(6):
        y = top + s * GAP
        width = n_bars * bar_w
        sw = 1.1 if s not in (0, 5) else 1.4
        parts.append(f'<line x1="{row_x:.1f}" y1="{y:.1f}" x2="{row_x + width:.1f}" '
                     f'y2="{y:.1f}" stroke="{INK}" stroke-width="{sw}"/>')

    # 节奏条
    for it in items:
        x = x_of(it["beat"])
        w = max(6, it["dur"] * BEAT_W * 0.86)
        parts.append(f'<rect x="{x - w / 2:.1f}" y="{top - 22:.1f}" width="{w:.1f}" '
                     f'height="7" rx="3.5" fill="{INK}" opacity="0.62"/>')

    # 小节线
    for i in range(n_bars + 1):
        x = row_x + i * bar_w
        if i in (0, n_bars):
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
                         f'stroke="{INK}" stroke-width="1.8"/>')
            if i == n_bars:
                parts.append(f'<line x1="{x + 5:.1f}" y1="{top}" x2="{x + 5:.1f}" '
                             f'y2="{bottom}" stroke="{INK}" stroke-width="4"/>')
        else:
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
                         f'stroke="{RULE}" stroke-width="1.2"/>')

    # 指法数字
    for it in items:
        x = x_of(it["beat"])
        y = top + it["string"] * GAP
        parts.append(f'<rect x="{x - 9:.1f}" y="{y - 9:.1f}" width="18" height="18" '
                     f'rx="4" fill="#fdfcf9" stroke="{INK}" stroke-width="1.1"/>')
        parts.append(f'<text x="{x:.1f}" y="{y + 5:.1f}" font-size="14" text-anchor="middle" '
                     f'fill="{INK}" font-family="Georgia, \'Times New Roman\', serif">'
                     f"{it['fret']}</text>")

    # 调弦与拍号提示
    parts.append(f'<text x="{row_x:.1f}" y="{bottom + 30:.1f}" font-size="12" '
                 f'fill="{MUTED}" font-family="Georgia, serif">'
                 f"Tuning E A D G B E　·　{score.meter[0]}/{score.meter[1]}　"
                 f"♩={int(round(score.tempo))}</text>")
    return "".join(parts)


def _empty_svg(msg: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}" height="160" '
            f'viewBox="0 0 {PAGE_W} 160">'
            f'<text x="{PAGE_W // 2}" y="80" text-anchor="middle" font-size="18" '
            f'fill="{MUTED}" font-family="Georgia, serif">{escape(msg)}</text></svg>')


def render_tab_svg(score: Score, title: str = None) -> str:
    return "\n".join(render_tab_pages(score, title))
