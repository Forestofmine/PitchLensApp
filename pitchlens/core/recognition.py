"""Best-effort recognition of printed jianpu (numbered notation) images.

The recogniser is deliberately modular:

1. preprocess (illumination, binarisation, deskew, line removal)
2. connected-symbol extraction
3. template-based digit / accidental classification
4. spatial assembly of octave dots, rhythm lines, barlines and measures
5. music-rule validation and a correction-friendly result

It is tuned for clean printed / digitally exported single-voice scores.  Phone
photos, handwriting, multi-voice scores and complex repeats are intentionally
out of the initial acceptance envelope.  Every note keeps its source bounding
box so the UI can show recognition boxes and let the user repair mistakes.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageFont, ImageOps

from .music import parse_key_name
from .score import NoteEvent, Score

# ---------------------------------------------------------------------------
# Template classifier
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = (
    ("C:/Windows/Fonts/simsun.ttc", 0),
    ("C:/Windows/Fonts/simhei.ttf", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/arial.ttf", 0),
    ("C:/Windows/Fonts/times.ttf", 0),
    ("C:/Windows/Fonts/calibri.ttf", 0),
)


@dataclass
class _Template:
    char: str
    image: np.ndarray


class TemplateClassifier:
    """Normalised bitmap templates rendered from common Windows fonts."""

    def __init__(self, chars: str = "0123456789ABCDEFG#b=/", size: int = 32) -> None:
        self.size = int(size)
        self.templates: list[_Template] = []
        self._build(chars)

    def _build(self, chars: str) -> None:
        for path, index in _FONT_CANDIDATES:
            if not Path(path).exists():
                continue
            for font_size in (48, 64, 80):
                try:
                    font = ImageFont.truetype(path, font_size, index=index)
                except Exception:
                    continue
                for char in chars:
                    try:
                        image = self._render(char, font)
                    except Exception:
                        continue
                    if image is not None:
                        self.templates.append(_Template(char, image))

    def _render(self, char: str, font: ImageFont.FreeTypeFont) -> np.ndarray | None:
        canvas = Image.new("L", (160, 160), 0)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(canvas)
        draw.text((20, 10), char, fill=255, font=font)
        arr = np.asarray(canvas)
        ys, xs = np.where(arr > 30)
        if xs.size == 0:
            return None
        crop = arr[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        return self._normalise(crop)

    def _normalise(self, crop: np.ndarray) -> np.ndarray:
        h, w = crop.shape[:2]
        if h <= 1 or w <= 1:
            return np.zeros((self.size, self.size), dtype=np.float32)
        target = self.size
        scale = min((target - 4) / w, (target - 4) / h)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
        out = np.zeros((target, target), dtype=np.float32)
        x0 = (target - new_w) // 2
        y0 = (target - new_h) // 2
        out[y0 : y0 + new_h, x0 : x0 + new_w] = resized.astype(np.float32) / 255.0
        return out

    def classify(self, crop: np.ndarray, allowed: str | None = None) -> tuple[str, float]:
        if crop is None or crop.size == 0:
            return "", 0.0
        if crop.ndim == 3:
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        normalised = self._normalise(crop)
        best_char = ""
        best_score = -1.0
        for template in self.templates:
            if allowed is not None and template.char not in allowed:
                continue
            # Zero-normalised correlation is robust to stroke weight changes.
            a = normalised - float(normalised.mean())
            b = template.image - float(template.image.mean())
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            score = float(np.sum(a * b) / denom) if denom > 1e-9 else 0.0
            if score > best_score:
                best_score = score
                best_char = template.char
        return best_char, max(0.0, min(1.0, best_score))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    kind: str
    x: int
    y: int
    w: int
    h: int
    char: str = ""
    confidence: float = 0.0

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (int(self.x), int(self.y), int(self.w), int(self.h))


@dataclass
class RecognitionResult:
    score: Score
    image_bgr: np.ndarray
    symbols: list[Symbol] = field(default_factory=list)
    arcs: list[Symbol] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Recogniser
# ---------------------------------------------------------------------------


class JianpuRecognizer:
    def __init__(self, debug: bool = False) -> None:
        self.debug = debug
        self.classifier = TemplateClassifier()
        self._digit_height = 32.0

    # ------------------------------------------------------------- public
    def recognize_path(
        self,
        path: str | Path,
        *,
        title: str = "",
        override_key: str | None = None,
        override_meter: tuple[int, int] | None = None,
        override_bpm: float | None = None,
        base_octave: int = 4,
    ) -> RecognitionResult:
        path = Path(path)
        data = path.read_bytes()
        return self.recognize_bytes(
            data,
            title=title or path.stem,
            override_key=override_key,
            override_meter=override_meter,
            override_bpm=override_bpm,
            base_octave=base_octave,
        )

    def recognize_bytes(
        self,
        data: bytes,
        *,
        title: str = "简谱",
        override_key: str | None = None,
        override_meter: tuple[int, int] | None = None,
        override_bpm: float | None = None,
        base_octave: int = 4,
    ) -> RecognitionResult:
        image = decode_image(data)
        return self.recognize_array(
            image,
            title=title,
            override_key=override_key,
            override_meter=override_meter,
            override_bpm=override_bpm,
            base_octave=base_octave,
        )

    def recognize_array(
        self,
        image_bgr: np.ndarray,
        *,
        title: str = "简谱",
        override_key: str | None = None,
        override_meter: tuple[int, int] | None = None,
        override_bpm: float | None = None,
        base_octave: int = 4,
    ) -> RecognitionResult:
        warnings: list[str] = []
        processed, gray, binary, scale, angle = preprocess_image(image_bgr)
        hint_height = estimate_text_height(binary)
        h_lines, v_lines, digit_mask = split_line_masks(binary, hint_height)
        self._digit_height = estimate_digit_height(v_lines, digit_mask, hint_height)
        dh = self._digit_height
        symbols: list[Symbol] = []
        symbols.extend(self._extract_digits(digit_mask, dh))
        symbols.extend(self._extract_dots(binary, dh))
        symbols.extend(self._extract_small_chars(digit_mask, dh))
        v_line_symbols = extract_vertical_lines(v_lines, dh)

        # Detect slur/tie arcs before accepting horizontal lines as dashes.
        # The top of an arc is nearly horizontal and is otherwise easy to
        # mistake for a one-beat extension line.
        rough_rows = [
            row
            for row in group_digit_rows(
                [s for s in symbols if s.kind == "digit"], dh
            )
            if len(row) >= 3
        ]
        arcs, arc_mask = detect_arcs(binary, dh, rough_rows)
        clean_binary = binary
        if arcs:
            h_lines = cv2.subtract(h_lines, arc_mask)
            digit_mask = cv2.subtract(digit_mask, arc_mask)
            clean_binary = cv2.subtract(binary, arc_mask)
            symbols = []
            symbols.extend(self._extract_digits(digit_mask, dh))
            symbols.extend(self._extract_dots(clean_binary, dh))
            symbols.extend(self._extract_small_chars(digit_mask, dh))
            warnings.append(
                f"检测到 {len(arcs)} 条连音线/延音线（弧线），已从增时线候选中排除；"
                "请在校正中确认时值"
            )
        h_line_symbols = extract_horizontal_lines(h_lines, dh)

        # Find the first melody row so the meta parser does not accidentally
        # include the title or the first line of lyrics.
        digit_symbols = [s for s in symbols if s.kind == "digit"]
        candidate_rows = group_digit_rows(digit_symbols, dh) if digit_symbols else []
        melody_rows_for_meta = []
        for row in candidate_rows:
            if len(row) < 2:
                continue
            top = min(s.y for s in row)
            bottom = max(s.bottom for s in row)
            row_bars = [
                line
                for line in v_line_symbols
                if line.y <= bottom + 0.35 * dh and line.bottom >= top - 0.35 * dh
            ]
            if row_bars or len(row) >= 4:
                melody_rows_for_meta.append(row)
        melody_top = (
            min(s.y for row in melody_rows_for_meta for s in row)
            if melody_rows_for_meta
            else int(binary.shape[0] * 0.4)
        )
        meta = self._parse_meta(binary, dh, cutoff_y=melody_top - 0.35 * dh)
        if override_key:
            key_name = override_key
            meta["key_confidence"] = 1.0
        else:
            key_name = meta.get("key") or "C"
            if not meta.get("key"):
                warnings.append("未能自动识别调号，已使用 1=C；请在“识谱校正”中确认")
            elif float(meta.get("key_confidence", 0.0)) < 0.65:
                warnings.append(
                    f"调号自动识别为 1={key_name}，但置信度较低；请在“识谱校正”中确认"
                )
        if override_meter:
            meter_num, meter_den = override_meter
        else:
            meter_num = int(meta.get("meter_num") or 4)
            meter_den = int(meta.get("meter_den") or 4)
            if not meta.get("meter_num"):
                warnings.append("未能自动识别拍号，已使用 4/4；请在“识谱校正”中确认")
        if override_bpm is not None:
            bpm = float(override_bpm)
        else:
            bpm = float(meta.get("bpm") or 90.0)
            if not meta.get("bpm"):
                warnings.append("未能自动识别速度，已使用 90 BPM；可在界面中调整")

        notes, build_warnings = self._assemble_notes(
            symbols,
            h_line_symbols,
            v_line_symbols,
            dh,
            digit_mask=digit_mask,
            key_name=key_name,
            base_octave=base_octave,
            meter=(meter_num, meter_den),
        )
        warnings.extend(build_warnings)
        score = Score(
            title=title,
            key_name=key_name,
            base_octave=int(base_octave),
            meter_num=meter_num,
            meter_den=meter_den,
            tempo_hint=max(30.0, min(300.0, bpm)),
            mode="major",
            notes=notes,
            source="image",
            image_name=title,
            meta_confidence=float(meta.get("confidence", 0.0)),
        )
        if not notes:
            warnings.insert(0, "没有识别到音符，请使用“手动录入”或在校正中添加")
        score.source_warnings = list(dict.fromkeys(warnings))
        score.refresh()
        debug = {
            "scale": scale,
            "deskew_deg": angle,
            "digit_height": dh,
            "meta": meta,
            "arcs": len(arcs),
            "horizontal_lines": len(h_line_symbols),
            "vertical_lines": len(v_line_symbols),
            "symbols": len(symbols),
        }
        return RecognitionResult(
            score=score,
            image_bgr=processed,
            symbols=symbols + h_line_symbols + v_line_symbols,
            arcs=arcs,
            debug=debug,
            warnings=score.warnings,
        )

    # ---------------------------------------------------------- extraction
    def _extract_digits(self, digit_mask: np.ndarray, dh: float) -> list[Symbol]:
        result: list[Symbol] = []
        count, labels, stats, _ = cv2.connectedComponentsWithStats(digit_mask, 8)
        pieces: list[Symbol] = []
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if h < 4 or w < 2 or area < 8:
                continue
            if h > 1.55 * dh or w > 1.25 * dh:
                continue
            pieces.append(Symbol("piece", x, y, w, h))
        # Reconnect glyph pieces that were separated by line removal or a thin
        # font join (the top bar of 5, the stem of 4, etc.).
        pieces = merge_piece_fragments(pieces, dh)
        for piece in pieces:
            x, y, w, h = piece.x, piece.y, piece.w, piece.h
            if h < 7 or w < 3 or piece.w * piece.h < 10:
                continue
            if not (0.70 * dh <= h <= 1.55 * dh):
                continue
            if not (0.10 * dh <= w <= 1.15 * dh):
                continue
            aspect = w / max(1.0, h)
            if aspect < 0.08 or aspect > 1.35:
                continue
            crop = digit_mask[y : y + h, x : x + w]
            char, confidence = self.classifier.classify(crop, allowed="01234567")
            if not char or confidence < 0.35:
                continue
            result.append(
                Symbol("digit", x, y, w, h, char=char, confidence=confidence)
            )
        return result

    def _extract_dots(self, binary: np.ndarray, dh: float) -> list[Symbol]:
        result: list[Symbol] = []
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
        min_size = max(4.0, 0.13 * dh)
        min_area = max(14.0, 0.016 * dh * dh)
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if h < min_size or w < min_size or area < min_area:
                continue
            if h > 0.33 * dh or w > 0.36 * dh:
                continue
            aspect = w / max(1.0, h)
            if not 0.45 <= aspect <= 2.2:
                continue
            crop = binary[y : y + h, x : x + w]
            # Circularity via fill ratio.  A dot is close to a filled blob.
            fill = area / max(1.0, float(w * h))
            if fill < 0.35:
                continue
            result.append(Symbol("dot", x, y, w, h, char=".", confidence=0.7))
        return result

    def _extract_small_chars(self, digit_mask: np.ndarray, dh: float) -> list[Symbol]:
        """Find accidentals (# / b) and dot-like glyphs near digits."""
        result: list[Symbol] = []
        count, labels, stats, _ = cv2.connectedComponentsWithStats(digit_mask, 8)
        for index in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[index])
            if h < 4 or w < 2 or area < 5:
                continue
            if not (0.30 * dh <= h <= 0.86 * dh):
                continue
            if not (0.08 * dh <= w <= 0.9 * dh):
                continue
            crop = digit_mask[y : y + h, x : x + w]
            char, confidence = self.classifier.classify(crop, allowed="#b")
            if not char or confidence < 0.42:
                continue
            result.append(
                Symbol("accidental", x, y, w, h, char=char, confidence=confidence)
            )
        return result

    # --------------------------------------------------------------- meta
    def _parse_meta(self, binary: np.ndarray, dh: float, cutoff_y: float | None = None) -> dict[str, Any]:
        h, w = binary.shape[:2]
        # The meta line is above the first melody row.  Restrict to that region
        # and to glyphs no taller than a note, which excludes a large title.
        y_limit = int(min(h * 0.32, cutoff_y if cutoff_y is not None else h * 0.32))
        y_limit = max(10, y_limit)
        meta_mask = np.zeros_like(binary)
        meta_mask[:y_limit, :] = binary[:y_limit, :]
        count, labels, stats, _ = cv2.connectedComponentsWithStats(meta_mask, 8)
        glyphs: list[Symbol] = []
        for index in range(1, count):
            x, y, gw, gh, area = (int(v) for v in stats[index])
            if gh < 4 or gw < 2 or area < 5:
                continue
            if gh > 1.02 * dh or gh < 0.25 * dh:
                continue
            crop = meta_mask[y : y + gh, x : x + gw]
            # Wide flat components are likely '=', lines or decorations.
            aspect = gw / max(1.0, gh)
            if aspect > 3.0:
                glyphs.append(Symbol("meta", x, y, gw, gh, char=" ", confidence=0.2))
                continue
            char, confidence = self.classifier.classify(
                crop, allowed="0123456789ABCDEFG#b=/"
            )
            if char and confidence >= 0.35:
                glyphs.append(
                    Symbol("meta", x, y, gw, gh, char=char, confidence=confidence)
                )
        # Group glyphs into lines and sort by x.
        lines: list[list[Symbol]] = []
        for glyph in sorted(glyphs, key=lambda item: item.cy):
            placed = False
            for line in lines:
                if abs(np.mean([g.cy for g in line]) - glyph.cy) < max(4.0, 0.4 * dh):
                    line.append(glyph)
                    placed = True
                    break
            if not placed:
                lines.append([glyph])
        text_lines: list[str] = []
        confidences: list[float] = []
        for line in lines:
            line.sort(key=lambda item: item.x)
            # Insert a space where the x-gap clearly separates two tokens.
            # Without this, "4/4   120" glues into "44120" and the BPM (and
            # sometimes the meter) silently falls back to defaults.
            parts: list[str] = []
            prev: Symbol | None = None
            for glyph in line:
                if prev is not None and glyph.char.strip() and glyph.x - prev.right > 0.45 * dh:
                    parts.append(" ")
                parts.append(glyph.char)
                prev = glyph
            text_lines.append("".join(parts))
            confidences.extend(item.confidence for item in line if item.char.strip())
        text = " ".join(text_lines)
        key_name = None
        key_confidence = 0.0
        # Look for a digit 1 closely followed by a letter A-G.
        for line in lines:
            line.sort(key=lambda item: item.x)
            for index, glyph in enumerate(line):
                if glyph.char != "1":
                    continue
                window = [g for g in line[index + 1 :] if g.x - glyph.right < 2.6 * dh]
                letters = [g for g in window if g.char in "ABCDEFG"]
                if letters:
                    letter = letters[0]
                    accidental = ""
                    for candidate in window:
                        if candidate is letter:
                            break
                        if candidate.char in "#b" and abs(candidate.cy - letter.cy) < 0.8 * dh:
                            accidental = candidate.char
                    try:
                        _, key_name = parse_key_name(accidental + letter.char)
                        key_confidence = float(min(glyph.confidence, letter.confidence))
                    except Exception:
                        key_name = None
                    break
            if key_name:
                break
        # Time signature: either "4/4" from the glyph stream or two nearby
        # digits with a slash-like gap.
        meter_num = meter_den = None
        meter_match = re.search(r"(\d)\s*/\s*(\d)", text)
        if meter_match:
            meter_num, meter_den = int(meter_match.group(1)), int(meter_match.group(2))
        else:
            # Find a line with two digits separated by a slash-sized gap.
            # Try every consecutive pair (the first pair may belong to the
            # key signature or a tempo number) and reject impossible meters.
            for line in lines:
                digits = [g for g in line if g.char.isdigit() and g.char != "1"]
                for a, b in zip(digits, digits[1:]):
                    gap = b.x - a.right
                    if not (0.3 * dh <= gap <= 2.5 * dh):
                        continue
                    num, den = int(a.char), int(b.char)
                    if 1 <= num <= 16 and den in (2, 4, 8, 16):
                        meter_num, meter_den = num, den
                        break
                if meter_num is not None:
                    break
        # Tempo: a 2-3 digit value in the meta region, preferring a value not
        # immediately adjacent to "1=" (which is a key signature).
        bpm = None
        bpm_candidates = [
            int(token)
            for token in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", text)
            if 30 <= int(token) <= 300
        ]
        if bpm_candidates:
            bpm = float(bpm_candidates[-1])
        confidence_values = confidences or [0.0]
        return {
            "text": text,
            "key": key_name,
            "key_confidence": key_confidence,
            "meter_num": meter_num,
            "meter_den": meter_den,
            "bpm": bpm,
            "confidence": float(np.mean(confidence_values)),
        }

    # ------------------------------------------------------------ assembly
    def _assemble_notes(
        self,
        symbols: list[Symbol],
        h_lines: list[Symbol],
        v_lines: list[Symbol],
        dh: float,
        *,
        digit_mask: np.ndarray,
        key_name: str,
        base_octave: int,
        meter: tuple[int, int],
    ) -> tuple[list[NoteEvent], list[str]]:
        warnings: list[str] = []
        digits = [s for s in symbols if s.kind == "digit"]
        dots = [s for s in symbols if s.kind == "dot"]
        accidentals = [s for s in symbols if s.kind == "accidental"]
        if not digits:
            return [], ["没有识别到数字音符"]

        rows = group_digit_rows(digits, dh)
        # Keep only rows that have at least two digits.  Meta rows and stray
        # digits are rejected.
        rows = [row for row in rows if len(row) >= 2]
        if not rows:
            return [], ["识别到的音符不足以构成旋律行"]

        # Barlines that overlap a row make it much more likely to be a melody
        # row rather than a lyric/meta row.
        melody_rows: list[tuple[list[Symbol], list[Symbol]]] = []
        for row in rows:
            top = min(s.y for s in row)
            bottom = max(s.bottom for s in row)
            row_barlines = [
                line
                for line in v_lines
                if line.y <= bottom + 0.35 * dh and line.bottom >= top - 0.35 * dh
            ]
            if row_barlines or len(row) >= 4:
                melody_rows.append((row, row_barlines))
        if not melody_rows:
            return [], ["未能分离出旋律行"]

        # Lyrics sit directly beneath their melody row and carry no barlines.
        # CJK characters fragment into disconnected strokes; only stroke-like
        # fragments survive digit filtering, so per-symbol confidence/aspect
        # cannot tell them apart from real digits.  Ink coverage can: a melody
        # row's ink is almost entirely inside digit boxes, while a lyric row
        # leaves most of its stroke ink outside them.
        if any(bars for _, bars in melody_rows):
            melody_rows.sort(key=lambda item: min(s.y for s in item[0]))
            kept_rows: list[tuple[list[Symbol], list[Symbol]]] = []
            dropped_glyphs = 0
            prev_bottom: float | None = None
            for row, bars in melody_rows:
                top = min(s.y for s in row)
                bottom = max(s.bottom for s in row)
                directly_below = (
                    prev_bottom is not None and 0 < top - prev_bottom <= 3.2 * dh
                )
                if not bars and directly_below and _row_ink_coverage(digit_mask, row, dh) < 0.55:
                    dropped_glyphs += len(row)
                else:
                    kept_rows.append((row, bars))
                prev_bottom = bottom
            if dropped_glyphs:
                warnings.append(
                    f"已忽略疑似歌词的 {dropped_glyphs} 个符号；如有误删请在“识谱校正”中检查"
                )
            melody_rows = kept_rows
        if not melody_rows:
            return [], ["未能分离出旋律行"]

        notes: list[NoteEvent] = []
        measure = 0
        note_id = 0
        for row, row_barlines in melody_rows:
            row.sort(key=lambda item: item.cx)
            row_top = min(s.y for s in row)
            row_bottom = max(s.bottom for s in row)
            # Barlines strictly between notes; edge barlines belong to the
            # previous/next system and must not double-increment the measure.
            inner_barlines = [
                line
                for line in row_barlines
                if line.cx > row[0].cx + 0.2 * dh
            ]
            inner_barlines.sort(key=lambda item: item.cx)
            bar_xs = [line.cx for line in inner_barlines]

            # Build a combined event list: notes, dashes, barlines.
            events: list[tuple[float, str, Any]] = []
            for digit in row:
                events.append((digit.cx, "note", digit))
            for line in h_lines:
                if line.cy < row_top - 0.2 * dh or line.cy > row_bottom + 1.1 * dh:
                    continue
                overlap = _line_overlaps_row(line, row, dh)
                if not overlap:
                    continue
                if line.cy >= row_bottom - 0.2 * dh:
                    # Underline: assigned to every digit it spans.
                    for digit in row:
                        if digit.x - 0.2 * dh <= line.cx <= digit.right + 0.2 * dh or (
                            line.x <= digit.cx <= line.right
                        ):
                            events.append((line.cx, "underline", digit))
                else:
                    # A dash at mid-height extends the previous note.
                    events.append((line.cx, "dash", line))
            for line in inner_barlines:
                events.append((line.cx, "bar", line))
            events.sort(key=lambda item: (item[0], {"bar": 0, "note": 1, "dash": 2, "underline": 3}[item[1]]))

            current_measure_has_note = False
            prev_note: NoteEvent | None = None
            for _, kind, payload in events:
                if kind == "bar":
                    if current_measure_has_note:
                        measure += 1
                        current_measure_has_note = False
                        prev_note = None
                    continue
                if kind == "underline":
                    continue
                if kind == "dash":
                    if prev_note is not None and not prev_note.is_rest:
                        prev_note.duration_beat += 1.0
                    continue
                digit: Symbol = payload
                local_dots = [
                    dot
                    for dot in dots
                    if not (
                        digit.x - 2 <= dot.cx <= digit.right + 2
                        and digit.y - 2 <= dot.cy <= digit.bottom + 2
                    )
                ]
                above = [
                    dot
                    for dot in local_dots
                    if abs(dot.cx - digit.cx) <= 0.45 * dh
                    and digit.y - 0.95 * dh <= dot.cy <= digit.y - 0.16 * dh
                ]
                below = [
                    dot
                    for dot in local_dots
                    if abs(dot.cx - digit.cx) <= 0.45 * dh
                    and digit.bottom + 0.16 * dh <= dot.cy <= digit.bottom + 0.95 * dh
                ]
                octave_offset = len(above) - len(below)
                accidental_symbol = None
                for candidate in accidentals:
                    if not (digit.x - 0.95 * dh <= candidate.cx <= digit.x + 0.15 * dh):
                        continue
                    if not (digit.y - 0.2 * dh <= candidate.cy <= digit.bottom + 0.2 * dh):
                        continue
                    if candidate.char not in "#b":
                        continue
                    if accidental_symbol is None or candidate.right > accidental_symbol.right:
                        accidental_symbol = candidate
                accidental = 0
                if accidental_symbol is not None:
                    accidental = 1 if accidental_symbol.char == "#" else -1
                # Dotted note: a small dot to the right at mid height.
                dotted_dot = next(
                    (
                        dot
                        for dot in dots
                        if digit.right + 0.1 * dh <= dot.cx <= digit.right + 0.85 * dh
                        and abs(dot.cy - digit.cy) <= 0.55 * dh
                    ),
                    None,
                )
                dotted = dotted_dot is not None
                underline_lines = [
                    line
                    for line in h_lines
                    if line.cy >= digit.bottom - 0.15 * dh
                    and line.cy <= digit.bottom + 1.1 * dh
                    and (
                        line.x <= digit.cx <= line.right
                        or digit.x <= line.cx <= digit.right
                    )
                ]
                underline_levels = sorted(
                    {
                        round(line.cy / max(2.0, 0.16 * dh))
                        for line in underline_lines
                    }
                )
                underlines = max(0, len(underline_levels) - 0) if underline_levels else 0
                # A beamed underline may be one line spanning several notes;
                # count levels rather than individual segments.
                underlines = min(3, underlines)
                duration = 1.0 * (0.5**underlines)
                if dotted:
                    duration *= 1.5
                degree = int(digit.char) if digit.char.isdigit() else 1
                confidence = float(digit.confidence)
                if above or below:
                    confidence *= 0.92
                if accidental_symbol:
                    confidence *= float(max(0.5, accidental_symbol.confidence))
                bbox_parts = [digit.bbox]
                bbox_parts.extend(dot.bbox for dot in above)
                bbox_parts.extend(dot.bbox for dot in below)
                if accidental_symbol is not None:
                    bbox_parts.append(accidental_symbol.bbox)
                if dotted_dot is not None:
                    bbox_parts.append(dotted_dot.bbox)
                for line in underline_lines:
                    left = max(line.x, digit.x - 0.2 * dh)
                    right = min(line.right, digit.right + 0.2 * dh)
                    if right > left:
                        bbox_parts.append(
                            (int(left), int(line.y), int(right - left), max(1, int(line.h)))
                        )
                note = NoteEvent(
                    id=note_id,
                    degree=degree,
                    accidental=accidental,
                    octave_offset=octave_offset,
                    duration_beat=duration,
                    measure_index=measure,
                    image_bbox=union_bboxes(bbox_parts),
                    confidence=confidence,
                    underlines=underlines,
                    dotted=dotted,
                )
                notes.append(note)
                note_id += 1
                prev_note = note
                current_measure_has_note = True
            # End of row: do not force a measure increment.  The next row
            # normally starts with a barline, and the measure counter carries
            # over so a system break does not create an empty measure.

        # Sort and rebuild the absolute beat timeline.
        notes.sort(key=lambda n: (n.measure_index, n.image_bbox[0] if n.image_bbox else n.id))
        # Within a measure preserve visual left-to-right order.
        score_stub = Score(
            key_name=key_name,
            base_octave=base_octave,
            meter_num=meter[0],
            meter_den=meter[1],
            notes=notes,
        )
        score_stub.recompute_pitches()
        score_stub.rebuild_timing()
        return notes, warnings


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def decode_image(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        rgb = np.asarray(image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def preprocess_image(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("空图片")
    image = image_bgr.copy()
    # Work at a predictable resolution.  Upscaling small screenshots makes the
    # template classifier much more reliable.
    h, w = image.shape[:2]
    scale = 1.0
    target_width = 1500.0
    if w < 900:
        scale = min(2.0, target_width / max(1.0, w))
    elif w > 2600:
        scale = 2600.0 / w
    if abs(scale - 1.0) > 0.01:
        image = cv2.resize(
            image,
            (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
            interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Normalise uneven phone-photo illumination.
    background = cv2.GaussianBlur(gray, (0, 0), max(9, image.shape[1] // 40))
    normalized = cv2.divide(gray, background, scale=255)
    _, otsu = cv2.threshold(
        normalized, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    ink_ratio = float(np.mean(otsu > 0))
    if ink_ratio < 0.004 or ink_ratio > 0.35:
        block = max(21, (image.shape[1] // 45) | 1)
        adaptive = cv2.adaptiveThreshold(
            normalized,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block,
            13,
        )
        binary = adaptive
    else:
        binary = otsu
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    angle = estimate_skew(binary)
    if abs(angle) > 0.35:
        matrix = cv2.getRotationMatrix2D(
            (image.shape[1] / 2.0, image.shape[0] / 2.0), angle, 1.0
        )
        image = cv2.warpAffine(
            image,
            matrix,
            (image.shape[1], image.shape[0]),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(255, 255, 255),
        )
        binary = cv2.warpAffine(
            binary,
            matrix,
            (binary.shape[1], binary.shape[0]),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image, gray, binary, scale, angle


def estimate_skew(binary: np.ndarray) -> float:
    """Projection-profile deskew; returns degrees to rotate clockwise."""
    h, w = binary.shape[:2]
    if h < 80 or w < 80:
        return 0.0
    small = binary
    if w > 900:
        factor = 900.0 / w
        small = cv2.resize(binary, (900, max(1, int(h * factor))), interpolation=cv2.INTER_NEAREST)
    best_angle = 0.0
    best_score = -1.0
    for angle in np.arange(-3.0, 3.01, 0.75):
        matrix = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), angle, 1.0)
        rotated = cv2.warpAffine(
            small, matrix, (small.shape[1], small.shape[0]), flags=cv2.INTER_NEAREST
        )
        projection = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.var(projection))
        if score > best_score:
            best_score = score
            best_angle = float(angle)
    return best_angle if abs(best_angle) >= 0.75 else 0.0


def detect_arcs(
    binary: np.ndarray,
    dh: float,
    rows: list[list[Symbol]],
) -> tuple[list[Symbol], np.ndarray]:
    """Find isolated slur/tie arcs above melody rows.

    This is a conservative stop-gap detector: it only needs to identify the
    arc so its nearly-horizontal top can be removed from the dash candidates.
    It deliberately does not interpret tie vs. slur semantics.
    """
    if not rows or dh <= 0:
        return [], np.zeros_like(binary)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    arcs: list[Symbol] = []
    union = np.zeros_like(binary)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if w < 1.10 * dh or h < 0.12 * dh or h > 0.78 * dh:
            continue
        if w / max(1.0, h) < 1.7:
            continue
        fill = area / max(1.0, float(w * h))
        if fill > 0.52:
            continue
        # The arc must sit just above a melody row, not in the lyrics/title.
        near_row = False
        for row in rows:
            row_top = min(item.y for item in row)
            row_left = min(item.x for item in row)
            row_right = max(item.right for item in row)
            if x + w < row_left - 0.6 * dh or x > row_right + 0.6 * dh:
                continue
            if row_top - 1.15 * dh <= y + h <= row_top + 0.20 * dh:
                near_row = True
                break
        if not near_row:
            continue
        roi = binary[y : y + h, x : x + w] > 0
        profile: list[float] = []
        for col in range(w):
            ys = np.nonzero(roi[:, col])[0]
            if ys.size:
                profile.append(float(ys.mean()))
        if len(profile) < 0.60 * w:
            continue
        values = np.asarray(profile, dtype=np.float64)
        # A straight underline/dash has a flat column profile; a slur has a
        # curved one with its middle higher than its ends.
        if float(values.max() - values.min()) < 0.18 * h:
            continue
        middle = float(np.median(values[len(values) // 3 : 2 * len(values) // 3]))
        edges = float((values[0] + values[-1]) / 2.0)
        if edges - middle < 0.10 * h:
            continue
        arcs.append(Symbol("arc", x, y, w, h, char="~", confidence=0.65))
        arc_roi = (labels[y : y + h, x : x + w] == index).astype(np.uint8) * 255
        union[y : y + h, x : x + w] = np.maximum(
            union[y : y + h, x : x + w], arc_roi
        )
    if arcs:
        union = cv2.dilate(union, np.ones((3, 3), np.uint8), iterations=1)
    return arcs, union


def split_line_masks(binary: np.ndarray, digit_height: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, w = binary.shape[:2]
    h_len = max(14, int(w * 0.018))
    # The vertical kernel must be longer than a digit but shorter than a
    # barline.  Otherwise the digit "1" is erased as if it were a barline.
    v_len = max(30, int(round((digit_height or max(24.0, h * 0.035)) * 1.55)))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
    digit_mask = cv2.subtract(binary, cv2.bitwise_or(h_lines, v_lines))
    # Reconnect thin strokes that were cut by the line masks (notably the top
    # bar of "5" and the stem of "4") without bridging separate glyphs.
    digit_mask = cv2.morphologyEx(
        digit_mask, cv2.MORPH_CLOSE, np.ones((5, 2), np.uint8)
    )
    digit_mask = cv2.morphologyEx(digit_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return h_lines, v_lines, digit_mask


def estimate_text_height(binary: np.ndarray) -> float:
    """Estimate the dominant printed-glyph height before line removal."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    heights: list[int] = []
    barline_heights: list[int] = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if h < 10 or w < 2 or area < 12:
            continue
        if h > 260:
            continue
        aspect = w / max(1.0, h)
        if h >= 50 and aspect <= 0.16:
            barline_heights.append(h)
            continue
        if 0.03 <= aspect <= 1.6:
            heights.append(h)
    if len(barline_heights) >= 2:
        # Barlines are roughly three times the height of the digit body.
        return float(np.clip(np.median(barline_heights) * 0.33, 20.0, 90.0))
    if not heights:
        return 32.0
    values, counts = np.unique(heights, return_counts=True)
    weights = counts.astype(np.float64) * (values.astype(np.float64) ** 0.25)
    return float(np.clip(values[int(np.argmax(weights))], 12.0, 160.0))


def estimate_digit_height(
    v_lines: np.ndarray, digit_mask: np.ndarray, hint: float | None = None
) -> float:
    heights: list[int] = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(digit_mask, 8)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if 10 <= h <= 160 and 3 <= w <= 160 and area >= 18:
            heights.append(h)
    if heights and hint:
        # Refine the barline-derived hint with the actual glyph components.
        candidates = [h for h in heights if 0.72 * hint <= h <= 1.30 * hint]
        if candidates:
            values, counts = np.unique(candidates, return_counts=True)
            order = np.lexsort((values, counts))
            return float(np.clip(values[order[-1]], 12.0, 140.0))
    if heights:
        # Digits are the dominant repeated glyph height.  A plain median is
        # skewed by dots, accents and lyric fragments; the mode of the larger
        # components is much more stable.
        filtered = [h for h in heights if h >= max(10, int(np.percentile(heights, 35)))]
        if filtered:
            values, counts = np.unique(filtered, return_counts=True)
            # Prefer a tall repeated height when counts are close.
            order = np.lexsort((values, counts))
            return float(np.clip(values[order[-1]], 12.0, 140.0))
        return float(np.clip(np.median(heights), 12.0, 140.0))
    # Fall back to barlines if the note mask is fragmented.
    heights = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(v_lines, 8)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if h >= 18 and w <= max(8, h * 0.25):
            heights.append(h)
    if heights:
        return float(np.clip(np.median(heights), 12.0, 140.0))
    return 32.0


def extract_horizontal_lines(mask: np.ndarray, dh: float) -> list[Symbol]:
    result: list[Symbol] = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if w < max(8, 0.35 * dh) or h > max(4, 0.22 * dh):
            continue
        if w / max(1.0, h) < 2.8:
            continue
        result.append(Symbol("hline", x, y, w, h, char="-", confidence=0.8))
    return result


def extract_vertical_lines(mask: np.ndarray, dh: float) -> list[Symbol]:
    result: list[Symbol] = []
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if h < max(10, 0.45 * dh) or w > max(8, 0.28 * dh):
            continue
        if h / max(1.0, w) < 2.5:
            continue
        result.append(Symbol("vline", x, y, w, h, char="|", confidence=0.8))
    return result


def group_digit_rows(digits: list[Symbol], dh: float) -> list[list[Symbol]]:
    rows: list[list[Symbol]] = []
    tolerance = max(5.0, 0.62 * dh)
    for digit in sorted(digits, key=lambda item: item.cy):
        placed = False
        for row in rows:
            row_center = float(np.median([item.cy for item in row]))
            if abs(row_center - digit.cy) <= tolerance:
                row.append(digit)
                placed = True
                break
        if not placed:
            rows.append([digit])
    rows.sort(key=lambda row: float(np.median([item.cy for item in row])))
    return rows


def _line_overlaps_row(line: Symbol, row: list[Symbol], dh: float) -> bool:
    row_left = min(item.x for item in row)
    row_right = max(item.right for item in row)
    # Rhythm lines may extend past the last glyph (dashes for held notes), so
    # allow a generous margin on the right.
    return line.right >= row_left - 4 and line.x <= row_right + max(180.0, 5.0 * dh)


def _row_ink_coverage(digit_mask: np.ndarray, row: list[Symbol], dh: float) -> float:
    """Share of the row band's ink that falls inside accepted digit boxes.

    Melody rows score close to 1.0 (digits are the only ink left in
    ``digit_mask``).  Lyric rows score low because CJK characters fragment
    into strokes and most fragments never become digit symbols.
    """
    top = max(0, int(min(s.y for s in row) - 0.3 * dh))
    bottom = min(digit_mask.shape[0], int(max(s.bottom for s in row) + 0.3 * dh))
    left = max(0, int(min(s.x for s in row) - 0.5 * dh))
    right = min(digit_mask.shape[1], int(max(s.right for s in row) + 0.5 * dh))
    band = digit_mask[top:bottom, left:right]
    total = int(np.count_nonzero(band))
    if total == 0:
        return 1.0
    covered = 0
    for s in row:
        x0, x1 = max(left, s.x) - left, min(right, s.right) - left
        y0, y1 = max(top, s.y) - top, min(bottom, s.bottom) - top
        covered += int(np.count_nonzero(band[y0:y1, x0:x1]))
    return covered / total


def union_bboxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    if not boxes:
        return (0, 0, 0, 0)
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return (int(left), int(top), int(max(1, right - left)), int(max(1, bottom - top)))


def merge_piece_fragments(pieces: list[Symbol], dh: float) -> list[Symbol]:
    """Greedy spatial merge for fragmented glyphs.

    The old all-pairs loop was O(n²) and became the dominant cost on full-page
    scans.  Pieces are bucketed by vertical band; candidates only come from the
    same/adjacent band, which is where a genuine glyph fragment can live.
    """
    if not pieces:
        return []
    band_height = max(4.0, 0.55 * dh)
    buckets: dict[int, list[int]] = {}
    merged: list[Symbol] = []
    for piece in sorted(pieces, key=lambda item: (item.cy, item.cx)):
        key = int(piece.cy // band_height)
        candidates: list[int] = []
        for neighbor in (key - 1, key, key + 1):
            candidates.extend(buckets.get(neighbor, ()))
        target = -1
        for index in candidates:
            if _should_merge(merged[index], piece, dh):
                target = index
                break
        if target >= 0:
            union = _union_symbols(merged[target], piece)
            merged[target] = union
            new_key = int(union.cy // band_height)
            if new_key != key:
                buckets.setdefault(new_key, []).append(target)
        else:
            index = len(merged)
            merged.append(piece)
            buckets.setdefault(key, []).append(index)
    return merged


def _should_merge(a: Symbol, b: Symbol, dh: float) -> bool:
    overlap = min(a.right, b.right) - max(a.x, b.x)
    min_width = max(1.0, min(a.w, b.w))
    if overlap < 0.45 * min_width:
        return False
    gap = max(a.y, b.y) - min(a.bottom, b.bottom)
    if gap > 0.20 * dh:
        return False
    union = _union_symbols(a, b)
    if union.h > 1.55 * dh or union.w > 1.25 * dh:
        return False
    # Do not merge two full-size digits; only true fragments.
    if a.h >= 0.70 * dh and b.h >= 0.70 * dh and gap > 0.02 * dh:
        return False
    return True


def _union_symbols(a: Symbol, b: Symbol) -> Symbol:
    x = min(a.x, b.x)
    y = min(a.y, b.y)
    right = max(a.right, b.right)
    bottom = max(a.bottom, b.bottom)
    return Symbol("piece", x, y, right - x, bottom - y)
