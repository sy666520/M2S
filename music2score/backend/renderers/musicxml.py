"""MusicXML 生成。

把 Score（拍单位）铺进小节，处理跨小节延音（tie）与休止符填充，
输出可被 Verovio / MuseScore / Sibelius 直接读取的 MusicXML。
"""
from functools import lru_cache
from typing import List, Tuple
from xml.sax.saxutils import escape

from ..models import Score, QuantNote, Key
from ..music.pitch import midi_to_step_octave

DIV = 4  # divisions per quarter note（十六分音符分辨率）

# (divisions, type 名, 附点数)，从大到小
NOTE_TYPES = [
    (16, "whole", 0),
    (12, "half", 1),
    (8, "half", 0),
    (6, "quarter", 1),
    (4, "quarter", 0),
    (3, "eighth", 1),
    (2, "eighth", 0),
    (1, "16th", 0),
]


@lru_cache(maxsize=4096)
def _best_split(rem: int) -> tuple:
    """最少音符数的时值拆分（用于需要连音线的组合音）。"""
    if rem <= 0:
        return ()
    best = None
    for div, typ, dots in NOTE_TYPES:
        if div <= rem:
            sub = _best_split(rem - div)
            cand = ((div, typ, dots),) + sub
            if best is None or len(cand) < len(best):
                best = cand
    return best or ()


def split_duration(divisions: int) -> List[Tuple[int, str, int]]:
    return list(_best_split(max(int(divisions), 1)))


class Event:
    __slots__ = ("kind", "midi", "div", "typ", "dots", "tie_start", "tie_stop", "velocity")

    def __init__(self, kind, midi=None, div=0, typ="quarter", dots=0,
                 tie_start=False, tie_stop=False, velocity=0.8):
        self.kind = kind          # 'note' | 'rest'
        self.midi = midi
        self.div = div
        self.typ = typ
        self.dots = dots
        self.tie_start = tie_start
        self.tie_stop = tie_stop
        self.velocity = velocity


def build_measures(score: Score) -> List[List[Event]]:
    beats_per_bar = score.meter[0]
    bar_div = beats_per_bar * DIV

    # 1) 把音符切到小节内，跨小节的用 tie 连接
    pieces = []
    for n in score.notes:
        start_div = int(round(n.beat * DIV))
        remain = max(int(round(n.dur * DIV)), 1)
        first = True
        while remain > 0:
            bar = start_div // bar_div
            pos = start_div % bar_div
            take = min(remain, bar_div - pos)
            pieces.append({
                "bar": bar, "pos": pos, "div": take, "midi": n.midi,
                "vel": n.velocity, "first": first, "last": take >= remain,
            })
            start_div += take
            remain -= take
            first = False

    if not pieces:
        return [[]]
    n_bars = max(p["bar"] for p in pieces) + 1
    bars: List[List[dict]] = [[] for _ in range(n_bars)]
    for p in pieces:
        bars[p["bar"]].append(p)

    # 2) 每小节内排序、填休止、拆时值
    measures: List[List[Event]] = []
    for bar_pieces in bars:
        bar_pieces.sort(key=lambda p: (p["pos"], p["midi"]))
        events: List[Event] = []
        cursor = 0
        for p in bar_pieces:
            if p["pos"] > cursor:
                events.extend(_rest_events(p["pos"] - cursor))
                cursor = p["pos"]
            segs = split_duration(p["div"])
            n_segs = len(segs)
            for i, (d, typ, dots) in enumerate(segs):
                is_first_seg = (i == 0)
                is_last_seg = (i == n_segs - 1)
                # 整条延音链：除首个 segment 外都有 stop，除末个 segment 外都有 start
                tie_stop = not (p["first"] and is_first_seg)
                tie_start = not (p["last"] and is_last_seg)
                events.append(Event("note", midi=p["midi"], div=d, typ=typ, dots=dots,
                                    tie_start=tie_start, tie_stop=tie_stop,
                                    velocity=p["vel"]))
            cursor += p["div"]
        if cursor < bar_div:
            events.extend(_rest_events(bar_div - cursor))
        measures.append(events)
    return measures


def _rest_events(divisions: int) -> List[Event]:
    out = []
    for d, typ, dots in split_duration(divisions):
        out.append(Event("rest", div=d, typ=typ, dots=dots))
    return out


def _pitch_xml(midi: int) -> str:
    step, alter, octave = midi_to_step_octave(midi)
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    return f"<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"


def _note_xml(ev: Event) -> str:
    lines = ["<note>"]
    is_rest = ev.kind == "rest"
    lines.append("<rest/>" if is_rest else _pitch_xml(ev.midi))
    lines.append(f"<duration>{ev.div}</duration>")
    for t in ("start", "stop"):
        flag = ev.tie_start if t == "start" else ev.tie_stop
        if flag:
            lines.append(f'<tie type="{t}"/>')
    lines.append("<voice>1</voice>")
    lines.append(f"<type>{ev.typ}</type>")
    lines.append("<dot/>" * ev.dots)
    if not is_rest and (ev.tie_start or ev.tie_stop):
        notations = []
        if ev.tie_start:
            notations.append('<tied type="start"/>')
        if ev.tie_stop:
            notations.append('<tied type="stop"/>')
        lines.append("<notations>" + "".join(notations) + "</notations>")
    lines.append("</note>")
    return "".join(lines)


def build_musicxml(score: Score, title: str = None) -> str:
    title = escape(title or score.title or "Untitled")
    beats, beat_type = score.meter
    fifths = score.key.fifths
    measures = build_measures(score)
    tempo = int(round(score.tempo))

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
           '"http://www.musicxml.org/dtds/partwise.dtd">',
           '<score-partwise version="3.1">',
           f"<work><work-title>{title}</work-title></work>",
           "<identification>",
           '<creator type="composer">music2score</creator>',
           "<encoding><software>music2score</software></encoding>",
           "</identification>",
           '<part-list>',
           '<score-part id="P1"><part-name></part-name>',
           '<score-instrument id="P1-I1"><instrument-name>Acoustic Grand Piano</instrument-name></score-instrument>',
           '<midi-instrument id="P1-I1"><midi-channel>1</midi-channel><midi-program>1</midi-program>'
           "<volume>78</volume><pan>-0</pan></midi-instrument>",
           "</score-part>",
           "</part-list>",
           '<part id="P1">']

    for i, events in enumerate(measures):
        out.append(f'<measure number="{i + 1}">')
        if i == 0:
            out.append(
                f"<attributes><divisions>{DIV}</divisions>"
                f"<key><fifths>{fifths}</fifths><mode>{score.key.mode}</mode></key>"
                f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
                f"<clef><sign>G</sign><line>2</line></clef></attributes>"
            )
            out.append(
                '<direction placement="above"><direction-type><metronome>'
                f"<beat-unit>quarter</beat-unit><per-minute>{tempo}</per-minute>"
                "</metronome></direction-type>"
                f'<sound tempo="{tempo}"/></direction>'
            )
        for ev in events:
            out.append(_note_xml(ev))
        out.append("</measure>")

    out.append("</part>")
    out.append("</score-partwise>")
    return "\n".join(out)
