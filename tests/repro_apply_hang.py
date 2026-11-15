"""Simulate the user's exact flow: import-sized score + editor + apply.

Mirrors the 泪海 case from the screenshot: 335 notes / 111 measures,
measure numbers starting at 9, lots of duration warnings, a large
photo-like image.  Any step that blocks the GUI thread will show up
in the timings.
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pitchlens.core.project import Project
from pitchlens.core.score import NoteEvent, Score
from pitchlens.ui.editor import ScoreEditorDialog
from pitchlens.ui.main_window import MainWindow


def make_score() -> Score:
    score = Score(title="泪海", key_name="C", meter_num=4, meter_den=4, tempo_hint=90.0)
    notes = []
    nid = 0
    for measure in range(9, 120):  # 111 measures, starts at 9 like the screenshot
        beats = 0.0
        while beats < 3.0:  # under-filled on purpose -> many warnings
            dur = float(np.random.choice([0.25, 0.5, 0.5, 1.0]))
            degree = int(np.random.choice([0, 1, 2, 3, 4, 5, 6, 7]))
            notes.append(
                NoteEvent(
                    id=nid,
                    degree=degree,
                    duration_beat=dur,
                    measure_index=measure,
                    confidence=float(np.random.uniform(0.4, 0.99)),
                    image_bbox=(100 + nid % 10 * 60, 200 + (measure % 12) * 90, 40, 50),
                )
            )
            nid += 1
            beats += dur
    score.notes = notes[:335]
    score.refresh()
    return score


def make_image() -> bytes:
    img = np.full((2800, 2000, 3), 245, np.uint8)
    for y in range(300, 2700, 90):
        cv2.line(img, (100, y), (1900, y), (30, 30, 30), 3)
    ok, enc = cv2.imencode(".png", img)
    assert ok
    return enc.tobytes()


def main() -> None:
    app = QApplication([])
    score = make_score()
    image = make_image()
    print(f"notes={len(score.notes)} measures={score.measure_count} warnings={len(score.warnings)} image={len(image)/1e6:.1f}MB")

    t0 = time.perf_counter()
    window = MainWindow()
    window._apply_project(Project(score=score, image_bytes=image, image_ext=".png"), reset=True)
    print(f"open/apply_project: {time.perf_counter()-t0:.2f}s")

    t0 = time.perf_counter()
    dialog = ScoreEditorDialog(window.project.score, window.project.image_bytes, window)
    print(f"editor __init__: {time.perf_counter()-t0:.2f}s")

    # Edit a cell (measure number) through the real signal path.
    t0 = time.perf_counter()
    item = dialog.table.item(3, 1)
    item.setText("12")  # fires itemChanged -> _on_item_changed
    app.processEvents()
    print(f"cell edit: {time.perf_counter()-t0:.2f}s  undo_stack={len(dialog._undo_stack)}")

    t0 = time.perf_counter()
    dialog._undo()
    dialog._redo()
    print(f"undo/redo: {time.perf_counter()-t0:.2f}s")

    t0 = time.perf_counter()
    dialog._apply()
    print(f"_apply: {time.perf_counter()-t0:.2f}s  accepted={dialog.result()}")

    assert dialog.result_score is not None
    t0 = time.perf_counter()
    window.project.score = dialog.result_score
    window._apply_project(window.project, reset=True)
    app.processEvents()
    print(f"post-apply _apply_project: {time.perf_counter()-t0:.2f}s")

    print("OK - no blocking step")


if __name__ == "__main__":
    main()
