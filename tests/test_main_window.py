import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.pitch import PitchFrame
from pitchlens.core.project import Project, ProjectIO
from pitchlens.core.recognition import RecognitionResult
from pitchlens.ui.editor import ScoreEditorDialog
from pitchlens.ui.main_window import MainWindow


def _score(title):
    return parse_jianpu_text("1=C 4/4 90\n| 1 2 3 4 |", title=title).score


class MainWindowRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.enterContext(mock.patch("pitchlens.ui.main_window.AudioEngine.list_devices", return_value=[]))
        self.enterContext(mock.patch("pitchlens.ui.main_window.load_settings_dict", return_value={}))
        self.enterContext(mock.patch("pitchlens.ui.main_window.save_settings_dict"))
        self.message_box = self.enterContext(mock.patch("pitchlens.ui.main_window.QMessageBox"))
        self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.window.close)

    @contextmanager
    def _pending_recognition(self):
        entered = threading.Event()
        release = threading.Event()
        score = _score("识谱 A")
        score.source = "image"
        score.source_warnings = ["调号需要确认"]
        score.refresh()
        result = RecognitionResult(score=score, image_bgr=np.zeros((8, 8, 3), dtype=np.uint8))

        def recognize(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=10):
                raise TimeoutError("test did not release recognition worker")
            return result

        with mock.patch("pitchlens.ui.main_window.JianpuRecognizer.recognize_bytes", side_effect=recognize):
            self.window._start_recognition(b"image", score.title)
            thread = self.window._recognition_thread
            try:
                self.assertTrue(entered.wait(timeout=3))
                yield
            finally:
                release.set()
                self.assertTrue(thread.wait(5000))
                self.app.processEvents()
                self.assertIsNone(self.window._recognition_thread)

    def test_late_recognition_does_not_replace_project_opened_by_button_or_drop(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.pitchproj"
            ProjectIO.save(Project(score=_score("项目 B")), path)
            for via_drop in (False, True):
                with self.subTest(via_drop=via_drop), self._pending_recognition():
                    if via_drop:
                        mime = QMimeData()
                        mime.setUrls([QUrl.fromLocalFile(str(path))])
                        drop = QDropEvent(
                            QPointF(), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                        )
                        self.window.dropEvent(drop)
                    else:
                        with mock.patch("pitchlens.ui.main_window.QFileDialog.getOpenFileName", return_value=(str(path), "")):
                            self.window._open_project()
                    self.assertFalse(self.window.edit_btn.isEnabled())
                self.assertEqual(self.window.project.score.title, "项目 B")
                self.assertTrue(self.window.edit_btn.isEnabled())
        self.message_box.information.assert_not_called()

    def test_late_recognition_does_not_replace_manually_entered_score(self):
        def enter_score(dialog):
            dialog.result_score = _score("手动录入 B")
            return QDialog.DialogCode.Accepted

        with self._pending_recognition():
            with mock.patch("pitchlens.ui.main_window.JianpuTextDialog.exec", new=enter_score):
                self.window._manual_input()
        self.assertEqual(self.window.project.score.title, "手动录入 B")
        self.message_box.information.assert_not_called()

    def test_normal_recognition_keeps_diagnostics_until_explicit_confirmation(self):
        self.window.settings.transpose = 2
        with self._pending_recognition():
            pass
        score = self.window.project.score
        self.assertEqual(score.notes[0].midi_pitch, 62)
        self.assertEqual(score.warnings, ["调号需要确认"])
        self.message_box.information.assert_called_once()
        self.assertIn("调号需要确认", self.message_box.information.call_args.args[2])

        score.notes[0].duration_beat = 2
        score.refresh()
        dialog = ScoreEditorDialog(score, None)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.confirm_recognition.isHidden())
        dialog.confirm_recognition.setChecked(True)
        dialog._apply()
        self.assertEqual(dialog.result_score.source_warnings, [])
        self.assertEqual(dialog.result_score.warnings, dialog.result_score.validate())
        self.assertTrue(dialog.result_score.warnings)

    def test_close_waits_for_slow_recognition_and_discards_result(self):
        self.window.show()
        with self._pending_recognition():
            self.assertFalse(self.window.close())
            QTest.qWait(900)
            self.assertTrue(self.window.isVisible())
            self.assertFalse(self.window.centralWidget().isEnabled())
        self.assertFalse(self.window.isVisible())
        self.assertIsNone(self.window.project)
        self.message_box.information.assert_not_called()
        self.message_box.warning.assert_not_called()
        self.message_box.critical.assert_not_called()

    def test_pause_and_resume_preserve_entire_recorded_pitch_history(self):
        frames = [
            PitchFrame(audio_time=index / 50, midi_float=60.0, voiced=True)
            for index in range(6001)
        ]
        first = mock.Mock(sample_rate=48000, analysis_ms=1.0, detector_label="YIN")
        first.start.return_value = (True, "OK")
        first.poll_frames.return_value = frames
        first.audio_time.return_value = 120.01
        first.display_time.return_value = 120.0
        second = mock.Mock(sample_rate=48000, analysis_ms=1.0, detector_label="YIN")
        second.start.return_value = (True, "OK")
        second.poll_frames.return_value = [PitchFrame(audio_time=0.1, midi_float=62.0, voiced=True)]
        second.audio_time.return_value = 0.11
        second.display_time.return_value = 0.1
        with mock.patch("pitchlens.ui.main_window.AudioEngine", side_effect=[first, second]):
            self.window._start_audio()
            self.window._tick()
            self.window._stop_audio()
            timeline = self.window.timeline
            timeline.plot.setXRange(-120.0, -115.0, padding=0)
            x, y = timeline.curve.getData()
            self.assertAlmostEqual(x[0], -120.0)
            self.assertEqual(y[0], 60.0)
            self.assertLess(len(x), 350)
            self.window._start_audio()
            self.window._tick()
            self.assertFalse(timeline._paused)
            self.assertAlmostEqual(timeline._frames[-1].audio_time, 120.11)
            self.assertFalse(timeline._frames[-2].voiced)
            self.window._stop_audio()
            timeline.plot.setXRange(-120.11, -115.11, padding=0)
            x, y = timeline.curve.getData()
            self.assertAlmostEqual(x[0], -120.11)
            self.assertEqual(y[0], 60.0)
            self.window._reset_position()
            self.assertEqual(timeline._frames, [])
