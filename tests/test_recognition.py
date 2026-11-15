import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from pitchlens.core.recognition import JianpuRecognizer
from pitchlens.demo import _font, render_demo_score


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.image_path = Path(cls.temp.name) / "demo.png"
        render_demo_score(cls.image_path)
        cls.result = JianpuRecognizer().recognize_path(cls.image_path, title="小星星")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_metadata(self):
        score = self.result.score
        self.assertEqual(score.key_name, "C")
        self.assertEqual((score.meter_num, score.meter_den), (4, 4))
        self.assertEqual(score.tempo_hint, 90)

    def test_notes_and_rhythm(self):
        score = self.result.score
        self.assertEqual(len(score.notes), 24)
        self.assertEqual(score.measure_count, 8)
        self.assertEqual([n.degree for n in score.notes[:8]], [1, 2, 3, 5, 6, 5, 3, 2])
        self.assertEqual(score.notes[6].duration_beat, 2)
        self.assertEqual(score.notes[11].duration_beat, 4)
        self.assertEqual(score.notes[23].duration_beat, 4)
        self.assertEqual(score.warnings, [])

    def test_pitch_mapping(self):
        score = self.result.score
        self.assertEqual(score.notes[0].midi_pitch, 60)
        self.assertEqual(score.notes[3].midi_pitch, 67)
        self.assertEqual(score.notes[11].midi_pitch, 60)

    def test_boxes_exist(self):
        self.assertTrue(all(note.image_bbox[2] > 0 for note in self.result.score.notes))


class MetaRecognitionTests(unittest.TestCase):
    """Meta-line variants: the BPM number must survive next to the meter."""

    def _recognize(self, meta_line: str):
        image = Image.new("RGB", (1500, 900), "white")
        draw = ImageDraw.Draw(image)
        draw.text((90, 120), meta_line, fill="black", font=_font(36))
        y = 300
        for x in (100, 415, 730, 1045, 1360):
            draw.line((x, y - 55, x, y + 80), fill="black", width=3)
        glyphs = ["1", "2", "3", "5", "6", "5", "3", "2", "3", "5", "3", "1"]
        xs = [140, 235, 330, 425, 460, 555, 650, 745, 780, 875, 970, 1065]
        for glyph, x in zip(glyphs, xs):
            draw.text((x, y - 50), glyph, fill="black", font=_font(64))
        image_bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        return JianpuRecognizer().recognize_array(image_bgr, title="meta-test")

    def test_bpm_plain_number_after_meter(self):
        # "1 = C  4/4  120": glyphs used to glue into "1044120" and the BPM
        # silently fell back to the default.
        result = self._recognize("1 = C      4/4      120")
        self.assertEqual(result.score.tempo_hint, 120)

    def test_bpm_with_label_still_works(self):
        result = self._recognize("1 = C      4/4      BPM = 90")
        self.assertEqual(result.score.tempo_hint, 90)

    def test_key_meter_bpm_variant(self):
        result = self._recognize("1 = G      3/4      100")
        self.assertEqual(result.score.key_name, "G")
        self.assertEqual((result.score.meter_num, result.score.meter_den), (3, 4))
        self.assertEqual(result.score.tempo_hint, 100)


class LyricRejectionTests(unittest.TestCase):
    """A lyric line directly under the melody must not become notes."""

    def test_lyric_line_not_recognized_as_notes(self):
        image = Image.new("RGB", (1500, 900), "white")
        draw = ImageDraw.Draw(image)
        draw.text((90, 60), "1 = C      4/4      90", fill="black", font=_font(36))
        y = 250
        for x in (100, 415, 730, 1045, 1360):
            draw.line((x, y - 55, x, y + 80), fill="black", width=3)
        glyphs = ["1", "2", "3", "5", "6", "5", "3", "2", "3", "5", "3", "1"]
        xs = [140, 235, 330, 425, 460, 555, 650, 745, 780, 875, 970, 1065]
        for glyph, x in zip(glyphs, xs):
            draw.text((x, y - 50), glyph, fill="black", font=_font(64))
        # 与数字同尺寸、无小节线、紧邻旋律行下方的歌词行（最恶劣情形）
        lyrics = "一闪一闪亮晶晶满天都是小星星"
        for i, ch in enumerate(lyrics):
            draw.text((130 + i * 82, y + 120), ch, fill="black", font=_font(64))
        image_bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        result = JianpuRecognizer().recognize_array(image_bgr, title="lyric-test")
        self.assertEqual(
            [n.degree for n in result.score.notes],
            [1, 2, 3, 5, 6, 5, 3, 2, 3, 5, 3, 1],
        )


if __name__ == "__main__":
    unittest.main()
