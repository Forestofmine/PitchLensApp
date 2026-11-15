import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from pitchlens.core import settings as settings_module
from pitchlens.core.settings import AppSettings
from pitchlens.ui.pitch_timeline import PitchTimeline
from pitchlens.ui import theme
from pitchlens.ui.theme import COLORS, DARK, PAPER, THEMES, apply_theme


def _mean_luminance(pixmap) -> float:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    width, height = image.width(), image.height()
    total = 0
    count = 0
    for y in range(0, height, 7):
        for x in range(0, width, 7):
            color = image.pixelColor(x, y)
            total += 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            count += 1
    return total / max(1, count)


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        apply_theme(self.app, "dark")

    def test_themes_have_identical_keys(self):
        self.assertEqual(set(DARK), set(PAPER))
        self.assertEqual(set(THEMES), {"dark", "paper"})

    def test_apply_theme_mutates_live_palette(self):
        apply_theme(self.app, "paper")
        self.assertEqual(COLORS["bg"], PAPER["bg"])
        self.assertEqual(COLORS["accent"], PAPER["accent"])
        apply_theme(self.app, "dark")
        self.assertEqual(COLORS["bg"], DARK["bg"])

    def test_apply_theme_rejects_unknown_name(self):
        apply_theme(self.app, "nope")
        self.assertEqual(COLORS["bg"], DARK["bg"])

    def test_stylesheet_follows_theme(self):
        apply_theme(self.app, "paper")
        self.assertIn("#f4f2ec", self.app.styleSheet())
        self.assertIn("chevron-down-dark.png", self.app.styleSheet())
        apply_theme(self.app, "dark")
        self.assertIn("#080d19", self.app.styleSheet())
        self.assertIn("chevron-down.png", self.app.styleSheet())
        self.assertNotIn("chevron-down-dark.png", self.app.styleSheet())

    def test_timeline_retheme_actually_repaints(self):
        timeline = PitchTimeline(AppSettings())
        timeline.resize(640, 400)
        timeline.show()
        apply_theme(self.app, "paper")
        timeline.retheme()
        self.app.processEvents()
        light = _mean_luminance(timeline.plot.grab())
        apply_theme(self.app, "dark")
        timeline.retheme()
        self.app.processEvents()
        dark = _mean_luminance(timeline.plot.grab())
        timeline.close()
        self.assertGreater(light, 180.0, f"paper plot should be bright, got {light:.0f}")
        self.assertLess(dark, 100.0, f"dark plot should be dark, got {dark:.0f}")


class SettingsPersistenceTests(unittest.TestCase):
    def test_default_theme_is_paper(self):
        self.assertFalse(AppSettings().dark)

    def test_settings_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = [Path(tmp)]
            with mock.patch.object(
                settings_module, "_settings_candidates", return_value=candidates
            ):
                data = AppSettings(dark=False, good_cents=31.0).to_dict()
                self.assertTrue(settings_module.save_settings_dict(data))
                loaded = settings_module.load_settings_dict()
        self.assertEqual(loaded["good_cents"], 31.0)
        self.assertFalse(loaded["dark"])

    def test_load_tolerates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                settings_module, "_settings_candidates", return_value=[Path(tmp)]
            ):
                self.assertEqual(settings_module.load_settings_dict(), {})


if __name__ == "__main__":
    unittest.main()
