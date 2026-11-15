"""Recognition fixture evaluation utilities.

Run the real-image pass with::

    $env:PITCHLENS_REAL_OCR = "1"
    .\\.venv\\Scripts\\python.exe -m unittest tests.test_recognition_real -v

The report is written to ``tests/fixtures/jianpu/baseline_report.json``.
Images without a matching ``*.expected.txt`` are reported as *unlabeled*; the
harness never fabricates ground truth from the recognizer itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.recognition import JianpuRecognizer
from pitchlens.core.score import Score

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


@dataclass
class Fixture:
    image: Path
    expected: Path | None


def discover_fixtures(root: str | Path) -> list[Fixture]:
    root = Path(root)
    result: list[Fixture] = []
    for path in sorted(root.iterdir()):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        expected = path.with_suffix(".expected.txt")
        result.append(Fixture(path, expected if expected.exists() else None))
    return result


def _pitch_tokens(score: Score) -> list[tuple[int, int, int]]:
    return [
        (note.degree, note.accidental, note.octave_offset)
        for note in score.notes
        if note.degree > 0
    ]


def _duration_tokens(score: Score) -> list[int]:
    # Quantise to a sixteenth-note grid; the expected text format uses the same
    # fractional beats as the score model.
    return [
        int(round(note.duration_beat * 4))
        for note in score.notes
        if note.degree > 0
    ]


def compare_scores(expected: Score, actual: Score) -> dict[str, Any]:
    exp_pitch = _pitch_tokens(expected)
    act_pitch = _pitch_tokens(actual)
    exp_dur = _duration_tokens(expected)
    act_dur = _duration_tokens(actual)

    pitch_matcher = SequenceMatcher(None, exp_pitch, act_pitch, autojunk=False)
    pitch_matches = sum(block.size for block in pitch_matcher.get_matching_blocks())
    duration_matcher = SequenceMatcher(None, exp_dur, act_dur, autojunk=False)
    duration_matches = sum(block.size for block in duration_matcher.get_matching_blocks())

    exp_totals = expected.measure_totals()
    act_totals = actual.measure_totals()
    checked = 0
    passed = 0
    for measure, total in exp_totals.items():
        if measure not in act_totals:
            continue
        checked += 1
        if abs(act_totals[measure] - total) <= 1e-6:
            passed += 1

    return {
        "labeled": True,
        "expected_notes": len(exp_pitch),
        "detected_notes": len(act_pitch),
        "note_count_ratio": round(
            len(act_pitch) / max(1, len(exp_pitch)), 3
        ),
        "pitch_recall": round(pitch_matches / max(1, len(exp_pitch)), 3),
        "pitch_precision": round(pitch_matches / max(1, len(act_pitch)), 3),
        "duration_recall": round(duration_matches / max(1, len(exp_dur)), 3),
        "measure_pass_rate": round(passed / max(1, checked), 3),
        "key_match": expected.key_name == actual.key_name,
        "meter_match": (expected.meter_num, expected.meter_den)
        == (actual.meter_num, actual.meter_den),
        "tempo_delta": round(actual.tempo_hint - expected.tempo_hint, 1),
    }


def evaluate_fixture(
    fixture: Fixture,
    recognizer: JianpuRecognizer | None = None,
) -> dict[str, Any]:
    recognizer = recognizer or JianpuRecognizer()
    started = time.perf_counter()
    result = recognizer.recognize_path(fixture.image, title=fixture.image.stem)
    elapsed = time.perf_counter() - started
    score = result.score
    confidence = [
        n.confidence for n in score.notes if n.degree > 0
    ]
    low_ratio = (
        sum(1 for value in confidence if value < 0.55) / max(1, len(confidence))
    )
    entry: dict[str, Any] = {
        "image": fixture.image.name,
        "labeled": fixture.expected is not None,
        "elapsed_sec": round(elapsed, 3),
        "notes": len(score.notes),
        "measures": score.measure_count,
        "warnings": len(score.warnings),
        "arcs": len(result.arcs),
        "low_confidence_ratio": round(low_ratio, 3),
        "key": score.key_name,
        "meter": f"{score.meter_num}/{score.meter_den}",
        "bpm": score.tempo_hint,
        "note_localization_boxes": sum(
            1 for n in score.notes if n.image_bbox[2] > 0 and n.image_bbox[3] > 0
        ),
    }
    if fixture.expected is not None:
        expected = parse_jianpu_text(
            fixture.expected.read_text(encoding="utf-8"),
            title=fixture.image.stem,
        ).score
        entry.update(compare_scores(expected, score))
    else:
        entry["labeled"] = False
        entry["note"] = "no .expected.txt; structural metrics only"
    return entry


def run_all(
    fixtures_dir: str | Path,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    fixtures_dir = Path(fixtures_dir)
    fixtures = discover_fixtures(fixtures_dir)
    recognizer = JianpuRecognizer()
    entries = [evaluate_fixture(fixture, recognizer) for fixture in fixtures]
    labeled = [e for e in entries if e.get("labeled") and "pitch_recall" in e]
    aggregate: dict[str, Any] = {
        "image_count": len(entries),
        "labeled_count": len(labeled),
        "unlabeled_count": len(entries) - len(labeled),
    }
    if labeled:
        for key in (
            "note_count_ratio",
            "pitch_recall",
            "pitch_precision",
            "duration_recall",
            "measure_pass_rate",
        ):
            aggregate[f"mean_{key}"] = round(
                sum(float(e[key]) for e in labeled) / len(labeled), 3
            )
    report = {"aggregate": aggregate, "images": entries}
    if output_json is not None:
        output = Path(output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


def print_report(report: dict[str, Any]) -> None:
    print("PitchLens recognition baseline")
    print(json.dumps(report["aggregate"], ensure_ascii=False, indent=2))
    print(
        f"{'image':44s} {'notes':>5s} {'meas':>5s} {'warn':>5s} "
        f"{'arcs':>4s} {'low%':>6s} {'pitch':>6s} {'dur':>6s}"
    )
    for entry in report["images"]:
        if entry.get("labeled") and "pitch_recall" in entry:
            pitch_text = f"{entry['pitch_recall']:6.3f}"
            duration_text = f"{entry['duration_recall']:6.3f}"
        else:
            pitch_text = "    --"
            duration_text = "    --"
        print(
            f"{entry['image'][:44]:44s} {entry['notes']:5d} {entry['measures']:5d} "
            f"{entry['warnings']:5d} {entry.get('arcs', 0):4d} "
            f"{entry['low_confidence_ratio'] * 100:5.1f}% "
            f"{pitch_text} {duration_text}"
        )
