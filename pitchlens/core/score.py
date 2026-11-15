"""Structured score model used by the viewer, editor and score follower."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .music import (
    jianpu_to_midi,
    key_prefers_flats,
    midi_to_note_name,
    parse_key_name,
    scale_offsets,
)


@dataclass
class NoteEvent:
    """One jianpu note (or rest) with its known position in the picture."""

    id: int
    degree: int = 1
    accidental: int = 0
    octave_offset: int = 0
    duration_beat: float = 1.0
    start_beat: float = 0.0
    measure_index: int = 0
    midi_pitch: int | None = None
    image_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    confidence: float = 1.0
    lyric: str = ""
    underlines: int = 0
    dotted: bool = False
    is_rest: bool = False

    def __post_init__(self) -> None:
        self.degree = int(self.degree)
        self.accidental = int(self.accidental)
        self.octave_offset = int(self.octave_offset)
        self.duration_beat = max(0.0625, float(self.duration_beat))
        self.start_beat = max(0.0, float(self.start_beat))
        self.measure_index = max(0, int(self.measure_index))
        self.is_rest = self.degree == 0
        if self.midi_pitch is not None:
            self.midi_pitch = int(self.midi_pitch)

    @property
    def end_beat(self) -> float:
        return self.start_beat + self.duration_beat

    @property
    def midi(self) -> float | None:
        return None if self.midi_pitch is None else float(self.midi_pitch)

    def display_degree(self) -> str:
        if self.degree == 0:
            return "0"
        accidental = "#" if self.accidental > 0 else "b" if self.accidental < 0 else ""
        octave = "'" * max(0, self.octave_offset) + "," * max(0, -self.octave_offset)
        return f"{accidental}{self.degree}{octave}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "degree": self.degree,
            "accidental": self.accidental,
            "octave_offset": self.octave_offset,
            "duration_beat": self.duration_beat,
            "start_beat": self.start_beat,
            "measure_index": self.measure_index,
            "midi_pitch": self.midi_pitch,
            "image_bbox": list(self.image_bbox),
            "confidence": self.confidence,
            "lyric": self.lyric,
            "underlines": self.underlines,
            "dotted": self.dotted,
            "is_rest": self.is_rest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NoteEvent":
        bbox = tuple(int(v) for v in data.get("image_bbox", (0, 0, 0, 0)))
        return cls(
            id=int(data.get("id", 0)),
            degree=int(data.get("degree", 1)),
            accidental=int(data.get("accidental", 0)),
            octave_offset=int(data.get("octave_offset", 0)),
            duration_beat=float(data.get("duration_beat", 1.0)),
            start_beat=float(data.get("start_beat", 0.0)),
            measure_index=int(data.get("measure_index", 0)),
            midi_pitch=(
                None if data.get("midi_pitch") is None else int(data["midi_pitch"])
            ),
            image_bbox=bbox if len(bbox) == 4 else (0, 0, 0, 0),
            confidence=float(data.get("confidence", 1.0)),
            lyric=str(data.get("lyric", "")),
            underlines=int(data.get("underlines", 0)),
            dotted=bool(data.get("dotted", False)),
            is_rest=bool(data.get("is_rest", data.get("degree", 1) == 0)),
        )


@dataclass
class Score:
    title: str = "未命名乐谱"
    key_name: str = "C"
    base_octave: int = 4
    meter_num: int = 4
    meter_den: int = 4
    tempo_hint: float = 90.0
    mode: str = "major"
    transpose: int = 0
    notes: list[NoteEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta_confidence: float = 1.0
    source: str = "manual"
    image_name: str = ""

    # ------------------------------------------------------------------ key
    @property
    def key_tonic(self) -> int:
        return parse_key_name(self.key_name)[0]

    @property
    def prefer_flats(self) -> bool:
        return key_prefers_flats(self.key_name, self.mode)

    @property
    def beat_seconds(self) -> float:
        bpm = max(20.0, min(300.0, float(self.tempo_hint or 90.0)))
        return 60.0 / bpm

    @property
    def total_beats(self) -> float:
        if not self.notes:
            return 0.0
        return max(note.end_beat for note in self.notes)

    @property
    def total_seconds(self) -> float:
        return self.total_beats * self.beat_seconds

    @property
    def measure_count(self) -> int:
        if not self.notes:
            return 0
        return max(note.measure_index for note in self.notes) + 1

    def copy(self) -> "Score":
        return Score.from_dict(self.to_dict())

    # -------------------------------------------------------------- mapping
    def midi_for(self, degree: int, accidental: int = 0, octave_offset: int = 0) -> int | None:
        return jianpu_to_midi(
            degree,
            key_tonic=self.key_tonic,
            base_octave=self.base_octave,
            accidental=accidental,
            octave_offset=octave_offset,
            mode=self.mode,
        )

    def recompute_pitches(self) -> None:
        for note in self.notes:
            midi = self.midi_for(
                note.degree, note.accidental, note.octave_offset
            )
            note.midi_pitch = None if midi is None else int(midi) + int(self.transpose)
            note.is_rest = note.degree == 0

    def note_name(self, note: NoteEvent) -> str:
        if note.midi_pitch is None:
            return "休止"
        return midi_to_note_name(note.midi_pitch, self.prefer_flats)

    # --------------------------------------------------------------- timing
    def rebuild_timing(self) -> None:
        """Recompute start beats from note order + measure numbers.

        The editor can freely change durations and measure numbers; this method
        makes the absolute timeline consistent again.
        """
        if not self.notes:
            return
        self.notes.sort(key=lambda n: (n.measure_index, n.id))
        current_measure = self.notes[0].measure_index
        measure_beat = 0.0
        base_beat = 0.0
        for note in self.notes:
            if note.measure_index != current_measure:
                base_beat += measure_beat
                measure_beat = 0.0
                current_measure = note.measure_index
            note.start_beat = base_beat + measure_beat
            measure_beat += note.duration_beat
        # Re-number ids by visual order so the table stays predictable.
        for idx, note in enumerate(self.notes):
            note.id = idx

    def measure_totals(self) -> dict[int, float]:
        totals: dict[int, float] = {}
        for note in self.notes:
            totals[note.measure_index] = totals.get(note.measure_index, 0.0) + note.duration_beat
        return totals

    def validate(self) -> list[str]:
        warnings: list[str] = []
        expected = float(self.meter_num) * (4.0 / float(self.meter_den))
        for measure, total in sorted(self.measure_totals().items()):
            if abs(total - expected) > 1e-6:
                warnings.append(
                    f"第 {measure + 1} 小节总时值 {total:g} 拍，拍号要求 {expected:g} 拍"
                )
        if not any(note.degree > 0 for note in self.notes):
            warnings.append("乐谱中没有可演唱的音符")
        if not self.notes:
            warnings.append("乐谱为空")
        return warnings

    def refresh(self) -> list[str]:
        self.recompute_pitches()
        self.rebuild_timing()
        self.warnings = self.validate()
        return self.warnings

    # --------------------------------------------------------------- lookup
    def note_at_beat(self, beat: float) -> NoteEvent | None:
        for note in self.notes:
            if note.start_beat <= beat < note.end_beat:
                return note
        if self.notes and beat >= self.notes[-1].end_beat:
            return self.notes[-1]
        return None

    def note_index_at_beat(self, beat: float) -> int:
        for index, note in enumerate(self.notes):
            if note.start_beat <= beat < note.end_beat:
                return index
        return len(self.notes) - 1 if self.notes else -1

    def note_by_id(self, note_id: int) -> NoteEvent | None:
        for note in self.notes:
            if note.id == note_id:
                return note
        return None

    def index_of(self, note: NoteEvent | int | None) -> int:
        if note is None:
            return -1
        if isinstance(note, int):
            for index, item in enumerate(self.notes):
                if item.id == note:
                    return index
            return -1
        for index, item in enumerate(self.notes):
            if item is note or item.id == note.id:
                return index
        return -1

    # ------------------------------------------------------------- serialize
    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "key_name": self.key_name,
            "base_octave": self.base_octave,
            "meter_num": self.meter_num,
            "meter_den": self.meter_den,
            "tempo_hint": self.tempo_hint,
            "mode": self.mode,
            "transpose": self.transpose,
            "warnings": list(self.warnings),
            "meta_confidence": self.meta_confidence,
            "source": self.source,
            "image_name": self.image_name,
            "notes": [note.to_dict() for note in self.notes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Score":
        score = cls(
            title=str(data.get("title", "未命名乐谱")),
            key_name=str(data.get("key_name", "C")),
            base_octave=int(data.get("base_octave", 4)),
            meter_num=int(data.get("meter_num", 4)),
            meter_den=int(data.get("meter_den", 4)),
            tempo_hint=float(data.get("tempo_hint", 90.0)),
            mode=str(data.get("mode", "major")),
            transpose=int(data.get("transpose", 0)),
            warnings=list(data.get("warnings", [])),
            meta_confidence=float(data.get("meta_confidence", 1.0)),
            source=str(data.get("source", "manual")),
            image_name=str(data.get("image_name", "")),
            notes=[NoteEvent.from_dict(item) for item in data.get("notes", [])],
        )
        score.refresh()
        # Preserve imported warnings that were not generated by validation.
        extra = [str(w) for w in data.get("warnings", []) if str(w) not in score.warnings]
        score.warnings = extra + score.warnings
        return score

    def summary(self) -> str:
        valid = [n for n in self.notes if n.midi_pitch is not None]
        if not valid:
            return "空乐谱"
        low = min(n.midi_pitch for n in valid)  # type: ignore[type-var]
        high = max(n.midi_pitch for n in valid)  # type: ignore[type-var]
        return (
            f"{self.title} · 1={self.key_name} · {self.meter_num}/{self.meter_den} · "
            f"{len(valid)} 音 · {midi_to_note_name(low, self.prefer_flats)}–"
            f"{midi_to_note_name(high, self.prefer_flats)}"
        )


def beat_to_seconds(beat: float, tempo_bpm: float) -> float:
    return float(beat) * 60.0 / max(20.0, float(tempo_bpm))


def seconds_to_beat(seconds: float, tempo_bpm: float) -> float:
    return float(seconds) * max(20.0, float(tempo_bpm)) / 60.0
