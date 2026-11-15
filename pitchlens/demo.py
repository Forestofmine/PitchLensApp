"""Demo score rendering and sample project helpers."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .core.jianpu_text import parse_jianpu_text
from .core.score import NoteEvent, Score

DEMO_TEXT = """1=C 4/4 90
| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |
| 5 5 6 5 | 3 3 2 - | 5 5 6 5 | 3 - - - |
"""


def build_demo_score() -> Score:
    parsed = parse_jianpu_text(DEMO_TEXT, title="小星星")
    score = parsed.score
    score.warnings = []
    return score


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for name in names:
        try:
            if Path(name).exists():
                return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_demo_score(path: str | Path, width: int = 1500, height: int = 980) -> Score:
    """Render a clean, deliberately OCR-friendly jianpu sheet."""
    score = build_demo_score()
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(52, True)
    meta_font = _font(36)
    note_font = _font(64)
    lyric_font = _font(28)
    small_font = _font(24)
    draw.text((width // 2 - 100, 34), "小星星", fill="black", font=title_font)
    draw.text((90, 120), "1 = C      4/4      BPM = 90", fill="black", font=meta_font)
    draw.text((90, 168), "简谱旋律练习 · 单声部", fill=(90, 90, 90), font=small_font)

    margin_left = 100
    line_top = 245
    line_gap = 330
    measure_width = 315
    beats_per_measure = 4
    notes_by_measure: dict[int, list[NoteEvent]] = {}
    for note in score.notes:
        notes_by_measure.setdefault(note.measure_index, []).append(note)

    lyric_lines = [
        "一 闪 一 闪 亮 晶 晶",
        "满 天 都 是 小 星 星",
    ]

    y = line_top
    for line_index in range(2):
        measure_start = line_index * 4
        # Barlines + note glyphs.
        for local_measure in range(5):
            x = margin_left + local_measure * measure_width
            draw.line((x, y - 55, x, y + 80), fill="black", width=3)
        for local_measure in range(4):
            measure_index = measure_start + local_measure
            notes = notes_by_measure.get(measure_index, [])
            x0 = margin_left + local_measure * measure_width
            beat_cursor = 0.0
            for note in notes:
                # Use the accumulated duration to position the glyph; the
                # demo has no tuplets, so one beat == one slot.
                if note.start_beat >= local_measure * beats_per_measure:
                    relative_beat = note.start_beat - measure_index * beats_per_measure
                else:
                    relative_beat = beat_cursor
                x = x0 + int(20 + relative_beat * (measure_width - 36) / beats_per_measure)
                if note.is_rest:
                    draw.text((x, y - 45), "0", fill="black", font=note_font)
                else:
                    accidental = "#" if note.accidental > 0 else "b" if note.accidental < 0 else ""
                    glyph = f"{accidental}{note.degree}"
                    draw.text((x, y - 50), glyph, fill="black", font=note_font)
                    # Octave dots above/below.
                    for dot_index in range(max(0, note.octave_offset)):
                        draw.ellipse(
                            (x + 22, y - 68 - dot_index * 15, x + 32, y - 58 - dot_index * 15),
                            fill="black",
                        )
                    for dot_index in range(max(0, -note.octave_offset)):
                        draw.ellipse(
                            (x + 22, y + 52 + dot_index * 15, x + 32, y + 62 + dot_index * 15),
                            fill="black",
                        )
                    if note.underlines:
                        for level in range(note.underlines):
                            ly = y + 58 + level * 9
                            draw.line((x - 4, ly, x + 42, ly), fill="black", width=3)
                    if note.dotted:
                        draw.ellipse((x + 48, y + 2, x + 56, y + 10), fill="black")
                    # Draw extension dashes so the image itself carries the
                    # written duration (the parser stores it on the note).
                    extra_beats = int(round(note.duration_beat)) - 1
                    for dash_index in range(max(0, extra_beats)):
                        dash_x = x0 + int(
                            20
                            + (relative_beat + dash_index + 1)
                            * (measure_width - 36)
                            / beats_per_measure
                        )
                        draw.line(
                            (dash_x - 18, y - 22, dash_x + 22, y - 22),
                            fill="black",
                            width=5,
                        )
                beat_cursor += note.duration_beat
        # Lyrics are deliberately smaller; the recogniser should ignore them.
        draw.text((margin_left + 20, y + 105), lyric_lines[line_index], fill=(100, 100, 100), font=lyric_font)
        y += line_gap

    draw.text(
        (width - 330, height - 52),
        "PitchLens demo · clean printed jianpu",
        fill=(150, 150, 150),
        font=small_font,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return score


def demo_note_bboxes(image_path: str | Path) -> list[tuple[int, int, int, int]]:
    """Return approximate note boxes for the generated demo image."""
    return []


def make_demo_project_image(path: str | Path) -> Score:
    return render_demo_score(path)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "examples" / "demo_jianpu.png"
    render_demo_score(target)
    print(target)
