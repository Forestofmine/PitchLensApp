"""Offscreen visual smoke for the paper theme."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.pitch import PitchFrame
from pitchlens.core.project import Project
from pitchlens.ui.main_window import MainWindow
from pitchlens.ui.theme import apply_theme


def main() -> None:
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "paper")
    win = MainWindow()
    score = parse_jianpu_text("1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - |").score
    score.refresh()
    win._apply_project(Project(score=score), reset=True)

    frames = []
    t = 0.0
    for i in range(360):
        midi = 69.1 if i < 220 else 72.05
        frames.append(
            PitchFrame(
                audio_time=t,
                frequency_hz=440.0,
                midi_float=midi + 0.05 * ((i % 7) - 3),
                confidence=0.9,
                voiced=True,
                rms=0.1,
            )
        )
        t += 1.0 / 60.0
    win.timeline.append_frames(frames)
    win.resize(1360, 820)
    win.show()
    win.timeline.update_view(t, win._last_state, follower=win.follower)
    app.processEvents()
    out = os.path.join(os.path.dirname(__file__), "smoke_paper_theme.png")
    win.grab().save(out)
    print("saved", out)
    win.close()


if __name__ == "__main__":
    main()
