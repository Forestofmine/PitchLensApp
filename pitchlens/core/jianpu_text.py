"""A compact, human-friendly jianpu text format.

This is intentionally separate from image recognition: it gives users an exact
way to create or repair a score, and it is also used by the demo generator and
the automatic tests.

Example::

    1=C 4/4 90
    | 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |

Modifiers:
    1'       one octave up       1,   one octave down
    1_       eighth note         1__  sixteenth note
    1.       dotted note         -    extends the previous note in this measure
    0        rest                #4 / b7  chromatic alteration
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .music import parse_key_name
from .score import NoteEvent, Score

_HEADER_KEY = re.compile(r"1\s*=\s*([#b]?[A-Ga-g][#b]?)")
_HEADER_METER = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_HEADER_BPM = re.compile(r"(?:bpm|tempo|♩|q)\s*[=:]?\s*(\d{2,3})", re.IGNORECASE)
_NUMBER_ONLY = re.compile(r"^\s*(\d{2,3})\s*$")

TOKEN_RE = re.compile(
    r"(?P<accidental>[#b]?)(?P<degree>[0-7])(?P<octave>[',]*)(?P<underlines>_*)(?P<dot>\.?)"
)


@dataclass
class ParsedJianpu:
    score: Score
    header: str
    warnings: list[str]


def parse_jianpu_text(text: str, *, title: str = "手动录入乐谱") -> ParsedJianpu:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    header_lines: list[str] = []
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if not line:
            continue
        if not in_body and _looks_like_header(line):
            header_lines.append(line)
        else:
            in_body = True
            body_lines.append(line)
    header = " ".join(header_lines)
    key_name = "C"
    meter_num, meter_den = 4, 4
    bpm = 90.0
    key_match = _HEADER_KEY.search(header)
    if key_match:
        try:
            _, key_name = parse_key_name(key_match.group(1))
        except ValueError:
            key_name = "C"
    meter_match = _HEADER_METER.search(header)
    if meter_match:
        meter_num = max(1, int(meter_match.group(1)))
        meter_den = max(1, int(meter_match.group(2)))
    bpm_match = _HEADER_BPM.search(header)
    if bpm_match:
        bpm = float(bpm_match.group(1))
    else:
        # A bare number on the header line is treated as BPM, but not the "1"
        # in "1=C" or the numbers of a time signature.
        cleaned = re.sub(r"1\s*=\s*[#b]?[A-Ga-g][#b]?", " ", header)
        cleaned = re.sub(r"\d+\s*/\s*\d+", " ", cleaned)
        for candidate in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", cleaned):
            value = int(candidate)
            if 30 <= value <= 300:
                bpm = float(value)
                break

    body = " ".join(body_lines)
    # Normalise typographic apostrophes and full-width bars.
    body = body.replace("’", "'").replace("‘", "'").replace("｜", "|")
    tokens = body.split()
    notes: list[NoteEvent] = []
    warnings: list[str] = []
    measure = 0
    prev_note: NoteEvent | None = None

    for raw in tokens:
        if raw in {"|", "||", "|."}:
            if prev_note is not None and prev_note.measure_index == measure:
                measure += 1
            continue
        if raw == ":":
            continue
        if raw == "-":
            crosses_bar = prev_note is not None and prev_note.measure_index != measure
            if crosses_bar:
                warnings.append(
                    f"第 {measure + 1} 小节开头的延长线不支持跨小节，已按一拍休止处理"
                )
            if prev_note is None or crosses_bar or prev_note.is_rest:
                # A dash without a preceding sung note in this measure is a rest.
                note = NoteEvent(
                    id=len(notes),
                    degree=0,
                    duration_beat=1.0,
                    measure_index=measure,
                    confidence=1.0,
                )
                notes.append(note)
                prev_note = note
            else:
                prev_note.duration_beat += 1.0
            continue
        match = TOKEN_RE.fullmatch(raw)
        if not match:
            warnings.append(f"无法解析记号：{raw}")
            continue
        degree = int(match.group("degree"))
        accidental_text = match.group("accidental")
        accidental = 1 if accidental_text == "#" else -1 if accidental_text == "b" else 0
        octave_text = match.group("octave") or ""
        octave_offset = octave_text.count("'") - octave_text.count(",")
        underlines = len(match.group("underlines") or "")
        dotted = bool(match.group("dot"))
        duration = 1.0 * (0.5 ** underlines)
        if dotted:
            duration *= 1.5
        note = NoteEvent(
            id=len(notes),
            degree=degree,
            accidental=accidental,
            octave_offset=octave_offset,
            duration_beat=duration,
            measure_index=measure,
            confidence=1.0,
            underlines=underlines,
            dotted=dotted,
        )
        notes.append(note)
        prev_note = note

    score = Score(
        title=title,
        key_name=key_name,
        base_octave=4,
        meter_num=meter_num,
        meter_den=meter_den,
        tempo_hint=bpm,
        mode="major",
        notes=notes,
        source="text",
        source_warnings=list(dict.fromkeys(warnings)),
    )
    score.refresh()
    return ParsedJianpu(score=score, header=header, warnings=list(score.warnings))


def _looks_like_header(line: str) -> bool:
    if "=" in line and "1" in line:
        return True
    if _HEADER_METER.search(line):
        return True
    if _HEADER_BPM.search(line):
        return True
    if _NUMBER_ONLY.match(line):
        return True
    if re.search(r"[A-Ga-g]", line) and "=" in line:
        return True
    return False


def export_jianpu_text(score: Score) -> str:
    """Round-trip helper for saving a human-readable copy of a score."""
    header = f"1={score.key_name} {score.meter_num}/{score.meter_den} {score.tempo_hint:g}"
    lines: list[str] = [header]
    current_measure = 0
    chunks: list[str] = []
    for note in score.notes:
        while note.measure_index > current_measure:
            chunks.append("|")
            current_measure += 1
        if note.is_rest:
            token = "0"
        else:
            acc = "#" if note.accidental > 0 else "b" if note.accidental < 0 else ""
            octave = "'" * max(0, note.octave_offset) + "," * max(0, -note.octave_offset)
            token = f"{acc}{note.degree}{octave}"
        duration = float(note.duration_beat)
        dotted = bool(note.dotted)
        if not dotted and abs(duration - round(duration)) > 1e-6:
            # A dotted value typed straight into the editor (e.g. 1.5 beats
            # with the dotted flag unset) must round-trip as well.
            alt = duration / 1.5
            if alt >= 0.125 and abs(math_log2(alt) - round(math_log2(alt))) < 1e-6:
                dotted = True
        base = duration / 1.5 if dotted else duration
        if dotted and base >= 1.0:
            # A dot only scales the base glyph; extension dashes still add
            # whole beats.  Values like 3.0 cannot be written as dot+dashes,
            # so fall back to plain dashes rather than lose the dot silently.
            if abs((duration - 1.5) - round(duration - 1.5)) > 1e-6:
                dotted = False
                base = duration
        if base >= 1.0:
            underlines = 0
            dashes = int(round(duration - 1.5)) if dotted else int(round(base - 1.0))
        else:
            # Infer underline count from the note model.
            underlines = max(0, int(round(-math_log2(base))))
            dashes = 0
        token += "_" * underlines
        if dotted:
            token += "."
        chunks.append(token)
        chunks.extend(["-"] * dashes)
    lines.append("| " + " ".join(chunks) + " |")
    return "\n".join(lines)


def math_log2(value: float) -> float:
    import math

    return math.log2(max(value, 1e-6))
