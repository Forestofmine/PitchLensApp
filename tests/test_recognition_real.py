"""Opt-in evaluation against the user-provided jianpu fixtures.

The labels are intentionally not auto-generated.  Put a matching
``<image>.expected.txt`` next to an image to activate the accuracy metrics.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.recognition_metrics import discover_fixtures, print_report, run_all

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jianpu"


@unittest.skipUnless(
    os.environ.get("PITCHLENS_REAL_OCR") == "1",
    "set PITCHLENS_REAL_OCR=1 to run the slow real-image baseline",
)
class RealImageRecognitionTests(unittest.TestCase):
    def test_fixture_report(self):
        fixtures = discover_fixtures(FIXTURES)
        self.assertGreaterEqual(len(fixtures), 1)
        report = run_all(FIXTURES, FIXTURES / "baseline_report.json")
        self.assertEqual(report["aggregate"]["image_count"], len(fixtures))
        self.assertGreaterEqual(report["aggregate"]["labeled_count"], 1)
        print_report(report)


if __name__ == "__main__":
    report = run_all(FIXTURES, FIXTURES / "baseline_report.json")
    print_report(report)
