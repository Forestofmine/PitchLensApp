import math
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pitchlens.core.recognition import JianpuRecognizer, Symbol, detect_arcs, union_bboxes


class ArcDetectionTests(unittest.TestCase):
    def test_curved_arc_is_detected_and_flat_line_is_not(self):
        image = np.zeros((260, 460), dtype=np.uint8)
        points = []
        for x in range(80, 340):
            y = int(125 - 20 * math.sin(math.pi * (x - 80) / 260))
            points.append((x, y))
        cv2.polylines(image, [np.asarray(points, dtype=np.int32)], False, 255, 3)
        # A straight line in the same upper area must not be called an arc.
        cv2.line(image, (360, 105), (430, 105), 255, 3)
        rows = [
            [
                Symbol("digit", 90, 155, 20, 42, char="1"),
                Symbol("digit", 150, 155, 24, 42, char="2"),
                Symbol("digit", 220, 155, 24, 42, char="3"),
            ]
        ]
        arcs, mask = detect_arcs(image, 34.0, rows)
        self.assertEqual(len(arcs), 1)
        self.assertGreater(int(np.count_nonzero(mask)), 0)
        self.assertEqual(arcs[0].kind, "arc")

    def test_no_arc_without_rows(self):
        image = np.zeros((200, 300), dtype=np.uint8)
        cv2.ellipse(image, (150, 100), (90, 20), 0, 200, 340, 255, 3)
        arcs, _ = detect_arcs(image, 30.0, [])
        self.assertEqual(arcs, [])

    def test_bbox_union_includes_symbols(self):
        self.assertEqual(
            union_bboxes([(10, 10, 4, 4), (20, 5, 2, 3)]),
            (10, 5, 12, 9),
        )

    def test_arc_does_not_become_an_extra_dash(self):
        font_path = "C:/Windows/Fonts/simsun.ttc"
        if not Path(font_path).exists():
            self.skipTest("Windows SimSun font not available")

        def render(path: Path, with_arc: bool) -> None:
            image = Image.new("RGB", (900, 450), "white")
            draw = ImageDraw.Draw(image)
            header = ImageFont.truetype(font_path, 42)
            note_font = ImageFont.truetype(font_path, 64)
            draw.text((60, 50), "1=C 4/4 90", fill="black", font=header)
            y = 260
            for x in (90, 430, 770):
                draw.line((x, y - 55, x, y + 85), fill="black", width=3)
            for i, glyph in enumerate(("1", "2", "3")):
                draw.text((140 + i * 280, y - 50), glyph, fill="black", font=note_font)
            if with_arc:
                points = []
                for k in range(61):
                    t = k / 60.0
                    points.append((140 + 280 * t, 205 - 22 * (4 * t * (1 - t))))
                draw.line(points, fill="black", width=4, joint="curve")
            image.save(path)

        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder) / "plain.png"
            arced = Path(folder) / "arced.png"
            render(plain, False)
            render(arced, True)
            plain_result = JianpuRecognizer().recognize_path(plain, title="plain")
            arc_result = JianpuRecognizer().recognize_path(arced, title="arc")
        self.assertGreaterEqual(len(arc_result.arcs), 1)
        self.assertEqual(
            [n.duration_beat for n in arc_result.score.notes],
            [n.duration_beat for n in plain_result.score.notes],
        )


if __name__ == "__main__":
    unittest.main()
