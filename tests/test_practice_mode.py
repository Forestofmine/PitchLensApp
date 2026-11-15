import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.pitch import PitchFrame
from pitchlens.core.project import Project
from pitchlens.core.settings import AppSettings
from pitchlens.ui.main_window import MainWindow
from pitchlens.ui.pitch_timeline import PitchTimeline, _snap_band_note


def _make_project() -> Project:
    score = parse_jianpu_text("1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - |").score
    score.refresh()
    return Project(score=score)


class SnapBandNoteTests(unittest.TestCase):
    def test_initial_snap_rounds_to_nearest(self):
        self.assertEqual(_snap_band_note(60.3, None), 60)
        self.assertEqual(_snap_band_note(60.49, None), 60)
        self.assertEqual(_snap_band_note(60.51, None), 61)

    def test_hysteresis_holds_band_at_boundary(self):
        # 60.5 is exactly between 60 and 61; with the band on 60 it must stay.
        self.assertEqual(_snap_band_note(60.5, 60), 60)
        self.assertEqual(_snap_band_note(60.55, 60), 60)
        self.assertEqual(_snap_band_note(59.5, 60), 60)

    def test_switch_beyond_hysteresis(self):
        self.assertEqual(_snap_band_note(60.61, 60), 61)
        self.assertEqual(_snap_band_note(59.39, 60), 59)

    def test_no_flicker_when_oscillating_near_boundary(self):
        note = None
        for value in (60.48, 60.52, 60.47, 60.53, 60.49):
            note = _snap_band_note(value, note)
            self.assertEqual(note, 60)


class PracticeModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.win._apply_project(_make_project(), reset=True)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_enter_practice_hides_panel_and_empties_follower(self):
        self.assertFalse(self.win._practice_mode)
        self.win._enter_practice()
        self.assertTrue(self.win._practice_mode)
        self.assertTrue(self.win.right_panel.isHidden())
        self.assertEqual(len(self.win.follower.score.notes), 0)
        self.assertEqual(self.win.practice_btn.text(), "返回乐谱")
        # Score editing actions are disabled while practicing.
        self.assertFalse(self.win.edit_btn.isEnabled())
        self.assertFalse(self.win.correct_btn.isEnabled())
        # The project itself is kept for restore.
        self.assertIsNotNone(self.win.project)
        self.assertGreater(len(self.win.project.score.notes), 0)

    def test_exit_practice_restores_project_and_panel(self):
        original_notes = len(self.win.project.score.notes)
        self.win._enter_practice()
        self.win._exit_practice()
        self.assertFalse(self.win._practice_mode)
        self.assertFalse(self.win.right_panel.isHidden())
        self.assertEqual(self.win.practice_btn.text(), "练唱模式")
        self.assertEqual(len(self.win.follower.score.notes), original_notes)
        self.assertTrue(self.win.edit_btn.isEnabled())

    def test_toggle_roundtrip(self):
        self.win._toggle_practice()
        self.assertTrue(self.win._practice_mode)
        self.win._toggle_practice()
        self.assertFalse(self.win._practice_mode)

    def test_apply_project_exits_practice(self):
        self.win._enter_practice()
        self.win._apply_project(_make_project(), reset=True)
        self.assertFalse(self.win._practice_mode)
        self.assertFalse(self.win.right_panel.isHidden())
        self.assertGreater(len(self.win.follower.score.notes), 0)

    def test_enter_practice_without_project(self):
        win = MainWindow()
        try:
            self.assertIsNone(win.project)
            win._enter_practice()
            self.assertTrue(win._practice_mode)
            self.assertTrue(win.right_panel.isHidden())
            win._exit_practice()
            self.assertFalse(win._practice_mode)
            self.assertFalse(win.right_panel.isHidden())
            self.assertIsNone(win.project)
        finally:
            win.close()
            win.deleteLater()


class PitchBandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _voiced(self, t: float, midi: float) -> PitchFrame:
        return PitchFrame(
            audio_time=t,
            frequency_hz=440.0,
            midi_float=midi,
            confidence=0.9,
            voiced=True,
        )

    def test_band_shows_and_snaps_when_voiced(self):
        timeline = PitchTimeline(AppSettings())
        timeline.append_frames([self._voiced(0.0, 60.2)])
        timeline.update_view(0.1, timeline._last_state, follower=None)
        self.assertTrue(timeline.pitch_band_inner.isVisible())
        self.assertEqual(timeline._band_note, 60)

    def test_band_hidden_when_unvoiced(self):
        timeline = PitchTimeline(AppSettings())
        timeline.append_frames([PitchFrame(audio_time=0.0, voiced=False)])
        timeline.update_view(0.1, timeline._last_state, follower=None)
        self.assertFalse(timeline.pitch_band_inner.isVisible())
        self.assertIsNone(timeline._band_note)

    def test_band_hidden_after_voice_timeout(self):
        timeline = PitchTimeline(AppSettings())
        timeline.append_frames([self._voiced(0.0, 60.2)])
        timeline.update_view(0.1, timeline._last_state, follower=None)
        self.assertTrue(timeline.pitch_band_inner.isVisible())
        # 0.5 s later the frame is stale (> 0.35 s): band hides again.
        timeline.update_view(0.6, timeline._last_state, follower=None)
        self.assertFalse(timeline.pitch_band_inner.isVisible())

    def test_band_label_shows_ideal_frequency(self):
        timeline = PitchTimeline(AppSettings())
        timeline.append_frames([self._voiced(0.0, 69.1)])
        timeline.update_view(0.1, timeline._last_state, follower=None)
        self.assertEqual(timeline._band_note, 69)
        text = timeline.pitch_band_label.textItem.toPlainText()
        self.assertIn("A4", text)
        self.assertIn("440", text)

    def test_clear_hides_band(self):
        timeline = PitchTimeline(AppSettings())
        timeline.append_frames([self._voiced(0.0, 60.2)])
        timeline.update_view(0.1, timeline._last_state, follower=None)
        timeline.clear()
        self.assertFalse(timeline.pitch_band_inner.isVisible())
        self.assertIsNone(timeline._band_note)


if __name__ == "__main__":
    unittest.main()
