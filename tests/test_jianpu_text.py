import unittest

from pitchlens.core.jianpu_text import export_jianpu_text, parse_jianpu_text


class JianpuTextTests(unittest.TestCase):
    TEXT = """1=C 4/4 90
| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |"""

    def test_demo_parse(self):
        parsed = parse_jianpu_text(self.TEXT, title="小星星")
        score = parsed.score
        self.assertEqual(score.key_name, "C")
        self.assertEqual((score.meter_num, score.meter_den), (4, 4))
        self.assertEqual(score.tempo_hint, 90)
        self.assertEqual(len(score.notes), 12)
        self.assertEqual(score.total_beats, 16)
        self.assertEqual(score.notes[0].midi_pitch, 60)
        self.assertEqual(score.notes[6].duration_beat, 2)
        self.assertEqual(score.notes[11].duration_beat, 4)
        self.assertEqual(score.warnings, [])

    def test_octave_accidental_rhythm(self):
        text = "1=G 4/4 80\n| 1' #4_ b7__ 0. |"
        score = parse_jianpu_text(text).score
        self.assertEqual(score.key_name, "G")
        self.assertEqual(score.notes[0].octave_offset, 1)
        self.assertEqual(score.notes[1].accidental, 1)
        self.assertAlmostEqual(score.notes[1].duration_beat, 0.5)
        self.assertEqual(score.notes[2].accidental, -1)
        self.assertAlmostEqual(score.notes[2].duration_beat, 0.25)
        self.assertTrue(score.notes[3].is_rest)
        self.assertAlmostEqual(score.notes[3].duration_beat, 1.5)

    def test_export_roundtrip(self):
        score = parse_jianpu_text(self.TEXT).score
        text = export_jianpu_text(score)
        again = parse_jianpu_text(text).score
        self.assertEqual(len(again.notes), len(score.notes))
        self.assertEqual(again.total_beats, score.total_beats)
        self.assertEqual(
            [n.midi_pitch for n in again.notes],
            [n.midi_pitch for n in score.notes],
        )

    def test_export_roundtrip_dotted(self):
        text = "1=C 4/4 90\n| 1. 2_ 3 4 | 1_. 2_. 3_ 4 5 |"
        score = parse_jianpu_text(text).score
        self.assertEqual(score.warnings, [])
        again = parse_jianpu_text(export_jianpu_text(score)).score
        self.assertEqual(
            [n.duration_beat for n in again.notes],
            [n.duration_beat for n in score.notes],
        )
        self.assertEqual(again.total_beats, score.total_beats)
        self.assertEqual(again.warnings, [])

    def test_export_editor_set_dotted_duration(self):
        # The editor can set duration=1.5 directly with the dotted flag unset;
        # the export must still survive the round-trip.
        score = parse_jianpu_text("1=C 4/4 90\n| 1 2 3 4 |").score
        score.notes[0].duration_beat = 1.5
        score.notes[0].dotted = False
        score.notes[1].duration_beat = 0.5
        score.refresh()
        again = parse_jianpu_text(export_jianpu_text(score)).score
        self.assertAlmostEqual(again.notes[0].duration_beat, 1.5)
        self.assertEqual(again.total_beats, 4.0)

    def test_export_dotted_whole_note_falls_back_to_dashes(self):
        # 3 beats cannot be written as dot+dashes ("1. -" is 2.5 beats), so
        # the dot must be dropped rather than corrupting the duration.
        score = parse_jianpu_text("1=C 4/4 90\n| 1 - - - | 2 3 4 5 |").score
        score.notes[0].dotted = True  # misrecognised dot on a 4-beat note
        score.notes[0].duration_beat = 3.0
        score.notes[1].duration_beat = 1.0
        score.refresh()
        again = parse_jianpu_text(export_jianpu_text(score)).score
        self.assertAlmostEqual(again.notes[0].duration_beat, 3.0)

    def test_dash_at_measure_boundary_does_not_modify_previous_note(self):
        for bar in ("|", "||", "|."):
            with self.subTest(bar=bar):
                parsed = parse_jianpu_text(f"1=C 4/4 90\n| 1 2 3 4 {bar} - 5 6 7 |")
                score = parsed.score
                self.assertEqual(score.measure_totals(), {0: 4.0, 1: 4.0})
                self.assertEqual(score.notes[3].duration_beat, 1.0)
                self.assertTrue(score.notes[4].is_rest)
                self.assertEqual(score.notes[4].measure_index, 1)
                self.assertEqual(len(score.warnings), 1)
                self.assertIn("不支持跨小节", score.warnings[0])
                self.assertEqual(score.refresh(), parsed.warnings)
                again = parse_jianpu_text(export_jianpu_text(score)).score
                self.assertEqual(again.measure_totals(), score.measure_totals())
                self.assertTrue(again.notes[4].is_rest)


if __name__ == "__main__":
    unittest.main()
