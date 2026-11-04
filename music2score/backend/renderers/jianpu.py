"""简谱（数字谱）SVG 渲染。

规则按国内通行写法：
  - 1-7 表示音级，0 表示休止
  - 数字上/下加点表示高低八度
  - 数字下方横线为减时线（八分一条、十六分两条），同一拍内可连写
  - 数字右侧横线为增时线，每延长一拍加一条
  - 附点点在数字右侧（增时线之后）
"""
import math
from typing import List
from xml.sax.saxutils import escape

from ..models import Score
from ..music.pitch import jianpu_symbol, PITCH_CLASS_NAMES

PAGE_W = 1760
PAD_L = 58
PAD_R = 58
BEAT_W = 60
LINE_H = 118
FONT_SIZE = 25
MAX_BARS_PER_LINE = 6
LINES_PER_PAGE = 7

INK = "#1e1c19"
MUTED = "#8a8378"
RULE = "#b0a791"


def _dot_count(dur: float) -> bool:
    """是否带附点（非整数拍，且不是恰好 0.25 的倍数导致的浮点误差）。"""
    return abs(dur - round(dur)) > 0.02


def _extender_lines(dur: float) -> int:
    """增时线条数。"""
    return max(0, int(math.floor(dur + 1e-6)) - 1)


def _beam_count(dur: float) -> int:
    """减时线条数：二分音符及以下不加，八分 1 条，十六分 2 条。"""
    if dur <= 0.26:
        return 2
    if dur <= 0.52:
        return 1
    return 0


def render_jianpu_pages(score: Score, title: str = None) -> List[str]:
    notes = sorted(score.notes, key=lambda n: (n.beat, -n.midi))
    if not notes:
        return [_empty_svg("没有识别到音符")]

    bpb = max(1, score.meter[0])
    total_beats = notes[-1].beat + notes[-1].dur
    n_bars = max(1, int(math.ceil((total_beats + 1e-6) / bpb)))

    avail = PAGE_W - PAD_L - PAD_R
    bar_w = bpb * BEAT_W
    bars_per_line = max(1, min(MAX_BARS_PER_LINE, int(avail // bar_w) or 1))

    tonic_pc = score.key.tonic_pc

    # 行规格：每行放多少小节；页宽按实际最宽行收紧，避免右侧大片空白
    line_specs = []
    bar_idx = 0
    while bar_idx < n_bars:
        n = min(bars_per_line, n_bars - bar_idx)
        line_specs.append((bar_idx, n))
        bar_idx += n
    max_line_w = max(n for _, n in line_specs) * bar_w
    page_w = max_line_w + PAD_L + PAD_R

    lines: List[str] = []
    header = _header_svg(score, title, page_w)
    first_page = True
    for bar_idx, n in line_specs:
        start_beat = bar_idx * bpb
        end_beat = start_beat + n * bpb
        line_notes = [nt for nt in notes if start_beat - 1e-6 <= nt.beat < end_beat]
        row_x = PAD_L + (page_w - PAD_L - PAD_R - n * bar_w) / 2
        svg = _render_line_group(
            line_notes, start_beat, n, bpb, tonic_pc, score,
            header_text=(header if first_page else None), row_x=row_x,
        )
        lines.append(svg)
        first_page = False

    # 按行分页，每页最多 LINES_PER_PAGE 行
    pages = []
    for i in range(0, len(lines), LINES_PER_PAGE):
        chunk = lines[i:i + LINES_PER_PAGE]
        body_h = len(chunk) * LINE_H
        top = 74 if i == 0 else 34
        h = top + body_h + 40
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}" height="{h}" '
                 f'viewBox="0 0 {page_w} {h}" class="score-svg">']
        y = top
        for s in chunk:
            parts.append(f'<g transform="translate(0,{y})">{s}</g>')
            y += LINE_H
        parts.append("</svg>")
        pages.append("".join(parts))
    return pages


def _header_svg(score: Score, title: str, page_w: int) -> str:
    tonic_name = PITCH_CLASS_NAMES[score.key.tonic_pc]
    mode_cn = "大调" if score.key.mode == "major" else "小调"
    t = escape(title or score.title or "未命名")
    return (f'<text x="{page_w / 2:.0f}" y="-26" font-size="19" fill="{INK}" text-anchor="middle" '
            f'font-family="Georgia, serif" font-weight="600">{t}</text>'
            f'<text x="{page_w / 2:.0f}" y="-4" font-size="15" fill="{MUTED}" text-anchor="middle" '
            f'font-family="Georgia, \'Songti SC\', serif">'
            f"1={tonic_name}　{score.meter[0]}/{score.meter[1]}　"
            f"♩={int(round(score.tempo))}　{escape(mode_cn)}</text>")


def _render_line_group(notes, start_beat, n_bars, bpb, tonic_pc, score,
                       header_text=None, row_x=PAD_L):
    parts = []
    if header_text:
        parts.append(header_text)

    baseline = 62
    bar_w = bpb * BEAT_W

    def x_of(beat: float) -> float:
        return row_x + (beat - start_beat) * BEAT_W

    # 1) 增时线先画（会被小节线穿过，观感与手写谱一致）
    for n in notes:
        if n.dur >= 1.999:
            ext = _extender_lines(n.dur)
            if ext <= 0:
                continue
            x0 = x_of(n.beat) + 16
            for k in range(ext):
                xx = x0 + k * 22
                parts.append(f'<line x1="{xx:.1f}" y1="{baseline - 8}" x2="{xx + 17:.1f}" '
                             f'y2="{baseline - 8}" stroke="{INK}" stroke-width="1.6"/>')

    # 2) 拍内减时线（成组连写）
    for b in range(int(start_beat), int(start_beat + n_bars * bpb)):
        group = [n for n in notes if b - 1e-6 <= n.beat < b + 1 - 1e-6]
        if not group:
            continue
        beams = [_beam_count(n.dur) for n in group]
        max_beam = max(beams)
        if max_beam == 0:
            continue
        xs = [x_of(n.beat) for n in group]
        if len(group) >= 2:
            x1, x2 = min(xs) - 9, max(xs) + 9
        else:
            x1, x2 = xs[0] - 11, xs[0] + 11
        for k in range(max_beam):
            yy = baseline + 6 + k * 5.5
            parts.append(f'<line x1="{x1:.1f}" y1="{yy:.1f}" x2="{x2:.1f}" y2="{yy:.1f}" '
                         f'stroke="{INK}" stroke-width="1.7" stroke-linecap="round"/>')

    # 3) 音符主体
    for n in notes:
        x = x_of(n.beat)
        symbol, dots = jianpu_symbol(n.midi, tonic_pc)
        # 数字
        parts.append(f'<text x="{x:.1f}" y="{baseline}" font-size="{FONT_SIZE}" '
                     f'text-anchor="middle" fill="{INK}" '
                     f'font-family="Georgia, \'Times New Roman\', serif">{escape(symbol)}</text>')
        # 高低音点
        if dots != 0:
            sign = -1 if dots > 0 else 1
            base_off = 21 if dots > 0 else (17 if _beam_count(n.dur) else 10)
            for k in range(abs(dots)):
                cy = baseline + sign * (base_off + k * 6)
                parts.append(f'<circle cx="{x:.1f}" cy="{cy:.1f}" r="2.1" fill="{INK}"/>')
        # 附点
        if _dot_count(n.dur):
            ext = _extender_lines(n.dur)
            dx = x + 16 + ext * 22
            parts.append(f'<circle cx="{dx:.1f}" cy="{baseline - 8}" r="2.4" fill="{INK}"/>')

    # 4) 小节线
    for i in range(n_bars + 1):
        x = row_x + i * bar_w
        last = (i == n_bars)
        if i == 0:
            parts.append(f'<line x1="{x:.1f}" y1="{baseline - 30}" x2="{x:.1f}" '
                         f'y2="{baseline + 12}" stroke="{INK}" stroke-width="2.4"/>')
        elif last:
            parts.append(f'<line x1="{x:.1f}" y1="{baseline - 30}" x2="{x:.1f}" '
                         f'y2="{baseline + 12}" stroke="{INK}" stroke-width="1.4"/>')
            parts.append(f'<line x1="{x + 5:.1f}" y1="{baseline - 30}" x2="{x + 5:.1f}" '
                         f'y2="{baseline + 12}" stroke="{INK}" stroke-width="4"/>')
        else:
            parts.append(f'<line x1="{x:.1f}" y1="{baseline - 30}" x2="{x:.1f}" '
                         f'y2="{baseline + 12}" stroke="{RULE}" stroke-width="1.3"/>')

    # 5) 行首小节序号
    parts.append(f'<text x="{row_x - 12:.1f}" y="{baseline - 14}" font-size="12" '
                 f'text-anchor="end" fill="{MUTED}" font-family="Georgia, serif">'
                 f"{int(start_beat // bpb) + 1}</text>")

    return "".join(parts)


def _empty_svg(msg: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W}" height="160" '
            f'viewBox="0 0 {PAGE_W} 160">'
            f'<text x="{PAGE_W // 2}" y="80" text-anchor="middle" font-size="18" '
            f'fill="{MUTED}" font-family="Georgia, serif">{escape(msg)}</text></svg>')


def render_jianpu_svg(score: Score, title: str = None) -> str:
    return "\n".join(render_jianpu_pages(score, title))
