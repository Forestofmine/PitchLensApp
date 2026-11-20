import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.project import Project, ProjectIO
from pitchlens.core.score import Score


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

    def test_failed_write_or_replace_keeps_existing_project(self):
        original = Project(score=Score(title="旧乐谱"), image_bytes=b"original")
        edited = Project(score=Score(title="新乐谱"), image_bytes=b"edited")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.pitchproj"
            ProjectIO.save(original, path)
            original_bytes = path.read_bytes()
            write = zipfile.ZipFile.writestr

            def fail_image_write(archive, name, data):
                if name.startswith("score."):
                    raise OSError("simulated image write failure")
                return write(archive, name, data)

            for target, options in (
                ("pitchlens.core.project.zipfile.ZipFile.writestr", {"new": fail_image_write}),
                ("pitchlens.core.project.os.replace", {"side_effect": PermissionError("file locked")}),
            ):
                with self.subTest(target=target), mock.patch(target, **options):
                    with self.assertRaises(OSError):
                        ProjectIO.save(edited, path)
                    self.assertEqual(path.read_bytes(), original_bytes)
                    self.assertEqual(ProjectIO.load(path).score.title, original.score.title)
                    self.assertEqual(list(path.parent.iterdir()), [path])
            ProjectIO.save(edited, path)
            self.assertEqual(ProjectIO.load(path).image_bytes, edited.image_bytes)

    def test_recognition_diagnostics_survive_refresh_and_old_project_load(self):
        score = parse_jianpu_text("1=C 4/4 90\n| 1 2 |", title="识谱").score
        score.source = "image"
        diagnostic = "未能识别调号，请确认"
        score.source_warnings = [diagnostic]
        score.refresh()
        legacy = score.to_dict()
        legacy.pop("source_warnings")
        score = Score.from_dict(legacy)
        self.assertEqual(score.source_warnings, [diagnostic])
        self.assertEqual(len(score.warnings), 2)
        score.transpose = 1
        score.notes[-1].duration_beat = 3.0
        self.assertEqual(score.refresh(), [diagnostic])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.pitchproj"
            ProjectIO.save(Project(score=score), path)
            loaded = ProjectIO.load(path).score
            self.assertEqual(loaded.source_warnings, [diagnostic])
            self.assertEqual(loaded.refresh(), [diagnostic])


if __name__ == "__main__":
    unittest.main()
