"""On-screen (real rendering) repro of the editor recalculate hang.

Runs with real widgets (no offscreen) because _rebuild_table layout/paint
behaves differently when the dialog is actually visible.  Drives the exact
sequence from the user's log: project -> editor -> recalculate, with a
watchdog that reports which step completed.
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pitchlens.app import _configure_logging
from pitchlens.core.project import Project
from pitchlens.core.score import NoteEvent, Score
from pitchlens.ui.editor import ScoreEditorDialog
from pitchlens.ui.main_window import MainWindow


def make_score() -> Score:
    score = Score(title="泪海", key_name="C", meter_num=4, meter_den=4, tempo_hint=90.0)
    rng = np.random.default_rng(11)
    notes = []
    nid = 0
    for measure in range(9, 120):
        beats = 0.0
        while beats < 3.0:
            dur = float(rng.choice([0.25, 0.5, 0.5, 1.0]))
            notes.append(
                NoteEvent(
                    id=nid,
                    degree=int(rng.choice([0, 1, 2, 3, 4, 5, 6, 7])),
                    duration_beat=dur,
                    measure_index=measure,
                    confidence=float(rng.uniform(0.4, 0.99)),
                    image_bbox=(100 + nid % 10 * 60, 200 + (measure % 12) * 90, 40, 50),
                )
            )
            nid += 1
            beats += dur
    score.notes = notes[:359]
    score.refresh()
    return score


def main() -> None:
    log_path = _configure_logging()
    print("log:", log_path)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    import cv2
    img = np.full((1400, 1000, 3), 245, np.uint8)
    cv2.line(img, (50, 200), (950, 200), (30, 30, 30), 3)
    ok, enc = cv2.imencode(".png", img)
    image = enc.tobytes()
    state = {}

    def step_open():
        window._apply_project(Project(score=make_score(), image_bytes=image), reset=True)
        state["dialog"] = ScoreEditorDialog(window.project.score, image, window)
        state["dialog"].show()
        logging.info("repro: dialog shown")
        QTimer.singleShot(1500, step_recalc)

    def step_recalc():
        logging.info("repro: cell edit start")
        t0 = time.perf_counter()
        item = state["dialog"].table.item(3, 1)
        item.setText("12")  # fires itemChanged on a VISIBLE table
        app.processEvents()
        logging.info("repro: cell edit done %.0fms", (time.perf_counter() - t0) * 1000)
        logging.info("repro: recalc start")
        t0 = time.perf_counter()
        state["dialog"]._recalculate()
        logging.info("repro: recalc returned %.0fms", (time.perf_counter() - t0) * 1000)
        logging.info("repro: apply start")
        t0 = time.perf_counter()
        state["dialog"]._apply()
        logging.info("repro: apply returned %.0fms", (time.perf_counter() - t0) * 1000)
        QTimer.singleShot(1000, app.quit)

    QTimer.singleShot(1000, step_open)
    QTimer.singleShot(30000, app.quit)  # hard watchdog
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
