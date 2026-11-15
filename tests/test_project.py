import tempfile
import unittest
from pathlib import Path

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.project import Project, ProjectIO


class ProjectTests(unittest.TestCase):
    def test_round_trip(self):
        score = parse_jianpu_text(
            "1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - |", title="测试"
        ).score
        project = Project(score=score, image_bytes=b"\x89PNG\r\n\x1a\nfake")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.pitchproj"
            ProjectIO.save(project, path)
            loaded = ProjectIO.load(path)
        self.assertEqual(loaded.score.title, "测试")
        self.assertEqual(len(loaded.score.notes), 7)
        self.assertEqual(loaded.image_bytes, b"\x89PNG\r\n\x1a\nfake")
        self.assertEqual(loaded.score.key_name, "C")


if __name__ == "__main__":
    unittest.main()
