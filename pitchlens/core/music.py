"""Small music-theory helpers shared by the detector, score and UI.

The project uses the scientific pitch convention: MIDI 60 == C4, A4 == 69.
All jianpu (numbered notation) pitches are converted to MIDI note numbers here so
that the rest of the program never has to know about key signatures.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

_PC_BY_NAME = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "F": 5,
    "E#": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}

MAJOR_OFFSETS = (0, 2, 4, 5, 7, 9, 11)
NATURAL_MINOR_OFFSETS = (0, 2, 3, 5, 7, 8, 10)

# Keys that are conventionally written with flats.
FLAT_MAJOR_KEYS = {"F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"}
FLAT_MINOR_KEYS = {"D", "G", "C", "F", "Bb", "Eb", "Ab"}

KEY_CHOICES = (
    "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B",
)


def frequency_to_midi(frequency: float, a4: float = 440.0) -> float:
    """Return a continuous MIDI value for a frequency in Hz."""
    if not frequency or frequency <= 0:
        return float("nan")
    return 69.0 + 12.0 * math.log2(float(frequency) / float(a4))


def midi_to_frequency(midi: float, a4: float = 440.0) -> float:
    return float(a4) * (2.0 ** ((float(midi) - 69.0) / 12.0))


def midi_to_note_name(midi: float, prefer_flats: bool = False) -> str:
    """Return a note name such as C4, F#5 or Bb3."""
    if midi is None or not math.isfinite(float(midi)):
        return "--"
    rounded = int(round(float(midi)))
    pc = rounded % 12
    octave = rounded // 12 - 1
    names = FLAT_NAMES if prefer_flats else SHARP_NAMES
    return f"{names[pc]}{octave}"


def note_name_to_midi(name: str, octave: int | None = None) -> int:
    """Parse C4, F#5, Bb3 or C#/4 into a MIDI number."""
    text = str(name).strip()
    match = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)?", text)
    if not match:
        raise ValueError(f"无法识别的音名: {name!r}")
    letter, accidental, oct_text = match.groups()
    token = (letter.upper() + accidental.upper()).upper()
    if token not in _PC_BY_NAME:
        # Handle Chinese-style bB / #F ordering if it slips through.
        if accidental and letter:
            token = (letter.upper() + accidental.upper()).upper()
    if token not in _PC_BY_NAME:
        raise ValueError(f"无法识别的音名: {name!r}")
    if oct_text is not None:
        octave_value = int(oct_text)
    elif octave is not None:
        octave_value = int(octave)
    else:
        octave_value = 4
    return int((octave_value + 1) * 12 + _PC_BY_NAME[token])


def parse_key_name(text: str) -> tuple[int, str]:
    """Parse a jianpu key name such as C, D, bB, #F, Bb.

    Returns (pitch_class, canonical_name).  The canonical name uses sharps for
    sharp keys and flats for flat keys.
    """
    raw = str(text).strip().replace("♭", "b").replace("♯", "#")
    if not raw:
        return 0, "C"
    # 1=bB, 1=#F, 1=Bb, 1=C etc.
    raw = re.sub(r"^1\s*=\s*", "", raw)
    match = re.fullmatch(r"([#b]?)([A-Ga-g])([#b]?)", raw)
    if not match:
        raise ValueError(f"无法识别的调号: {text!r}")
    prefix, letter, suffix = match.groups()
    accidental = prefix or suffix
    token = (letter.upper() + accidental.upper()).upper()
    if token not in _PC_BY_NAME:
        raise ValueError(f"无法识别的调号: {text!r}")
    pc = _PC_BY_NAME[token]
    prefer_flats = bool(accidental == "b") or (pc in (1, 3, 6, 8, 10) and accidental == "b")
    if accidental == "#":
        prefer_flats = False
    name = (FLAT_NAMES if prefer_flats else SHARP_NAMES)[pc]
    # Spell common black keys more naturally.
    if accidental == "b":
        name = FLAT_NAMES[pc]
    elif accidental == "#":
        name = SHARP_NAMES[pc]
    return pc, name


def key_pc(name: str) -> int:
    return parse_key_name(name)[0]


def key_prefers_flats(name: str, mode: str = "major") -> bool:
    pc, canonical = parse_key_name(name)
    if "b" in canonical:
        return True
    if mode == "minor":
        return canonical in FLAT_MINOR_KEYS
    return canonical in FLAT_MAJOR_KEYS


def scale_offsets(mode: str = "major") -> tuple[int, ...]:
    return NATURAL_MINOR_OFFSETS if str(mode).lower().startswith("min") else MAJOR_OFFSETS


def jianpu_to_midi(
    degree: int,
    *,
    key_tonic: int = 0,
    base_octave: int = 4,
    accidental: int = 0,
    octave_offset: int = 0,
    mode: str = "major",
) -> int | None:
    """Convert a jianpu scale degree to a MIDI pitch.

    degree 0 is a rest (returns None).  degree 1..7 is the major/minor scale
    degree.  ``base_octave`` is the octave of the un-dotted middle-register 1.
    """
    degree = int(degree)
    if degree <= 0:
        return None
    if not 1 <= degree <= 7:
        raise ValueError("简谱音级必须是 0..7")
    offsets = scale_offsets(mode)
    base_midi = (int(base_octave) + 1) * 12 + int(key_tonic)
    return int(
        base_midi
        + offsets[degree - 1]
        + int(accidental)
        + 12 * int(octave_offset)
    )


def jianpu_degree_for_midi(
    midi: int,
    *,
    key_tonic: int = 0,
    base_octave: int = 4,
    mode: str = "major",
) -> tuple[int, int, int]:
    """Best-effort inverse mapping used by the editor/demo tools.

    Returns (degree, accidental, octave_offset) relative to the selected key
    and base octave.
    """
    offsets = scale_offsets(mode)
    base = (int(base_octave) + 1) * 12 + int(key_tonic)
    rel = int(midi) - base
    octave_offset = rel // 12
    rel_in_octave = rel % 12
    best_degree = 1
    best_acc = 0
    best_distance = 99
    for idx, offset in enumerate(offsets, start=1):
        distance = abs(rel_in_octave - offset)
        if distance < best_distance:
            best_distance = distance
            best_degree = idx
            best_acc = 0
        # Also consider a flattened / sharpened neighbour.
        for acc in (-1, 1):
            distance = abs(rel_in_octave - (offset + acc))
            if distance < best_distance:
                best_distance = distance
                best_degree = idx
                best_acc = acc
    return best_degree, best_acc, octave_offset


def cents_from_midi(midi_float: float, target_midi: float) -> float:
    return (float(midi_float) - float(target_midi)) * 100.0


def cents_from_frequency(frequency: float, target_frequency: float) -> float:
    if frequency <= 0 or target_frequency <= 0:
        return float("nan")
    return 1200.0 * math.log2(float(frequency) / float(target_frequency))


def is_black_key(midi: int) -> bool:
    return int(round(midi)) % 12 in (1, 3, 6, 8, 10)


def note_range_label(midi_low: float, midi_high: float, prefer_flats: bool = False) -> str:
    return f"{midi_to_note_name(midi_low, prefer_flats)} – {midi_to_note_name(midi_high, prefer_flats)}"


def format_frequency(frequency: float | None) -> str:
    if frequency is None or not math.isfinite(float(frequency)) or frequency <= 0:
        return "--"
    if frequency >= 1000:
        return f"{frequency:,.1f} Hz"
    return f"{frequency:.1f} Hz"


def format_cents(cents: float | None, signed: bool = True) -> str:
    if cents is None or not math.isfinite(float(cents)):
        return "--"
    if signed:
        return f"{cents:+.0f}¢"
    return f"{abs(cents):.0f}¢"


def tolerance_state(cents: float | None, good: float = 25.0, ok: float = 50.0) -> str:
    """Return 'good', 'ok', 'bad' or 'none' for UI colouring."""
    if cents is None or not math.isfinite(float(cents)):
        return "none"
    value = abs(float(cents))
    if value <= good:
        return "good"
    if value <= ok:
        return "ok"
    return "bad"


def note_names_in_range(midi_low: int, midi_high: int) -> Iterable[tuple[int, str]]:
    for midi in range(int(midi_low), int(midi_high) + 1):
        yield midi, midi_to_note_name(midi)
