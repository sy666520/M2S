"""MIDI 导出。"""
import io

import mido

from ..models import Score

TPQ = 480


def build_midi(score: Score) -> bytes:
    mid = mido.MidiFile(ticks_per_beat=TPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    tempo = int(mido.bpm2tempo(max(20.0, min(300.0, score.tempo))))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(mido.MetaMessage("time_signature",
                                  numerator=score.meter[0],
                                  denominator=score.meter[1], time=0))
    track.append(mido.Message("program_change", program=0, channel=0, time=0))

    events = []
    for n in score.notes:
        start = int(round(n.beat * TPQ))
        dur = max(int(round(n.dur * TPQ)), 1)
        vel = max(1, min(127, int(round(n.velocity * 110))))
        events.append((start, 1, n.midi, vel))
        events.append((start + dur, 0, n.midi, vel))
    # note_off 排在同 tick 的 note_on 之后，避免零时长
    events.sort(key=lambda e: (e[0], e[1]))

    last = 0
    for tick, kind, midi_note, vel in events:
        delta = tick - last
        last = tick
        msg = ("note_on" if kind else "note_off")
        track.append(mido.Message(msg, note=midi_note, velocity=vel,
                                  time=max(0, delta), channel=0))
    track.append(mido.MetaMessage("end_of_track", time=0))

    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()
