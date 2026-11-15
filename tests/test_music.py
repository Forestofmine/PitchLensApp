import math
import unittest

from pitchlens.core.music import (
    cents_from_midi,
    frequency_to_midi,
    jianpu_to_midi,
    midi_to_frequency,
    midi_to_note_name,
    note_name_to_midi,
    parse_key_name,
    tolerance_state,
)


class MusicTests(unittest.TestCase):
    def test_frequency_round_trip(self):
        self.assertAlmostEqual(frequency_to_midi(440.0), 69.0, places=6)
        self.assertAlmostEqual(midi_to_frequency(69.0), 440.0, places=6)
        for midi in (36, 48, 60, 69, 81, 96):
            self.assertAlmostEqual(
                frequency_to_midi(midi_to_frequency(midi)), midi, places=6
            )

    def test_note_names(self):
        self.assertEqual(midi_to_note_name(60), "C4")
        self.assertEqual(midi_to_note_name(69), "A4")
        self.assertEqual(midi_to_note_name(70, prefer_flats=True), "Bb4")
        self.assertEqual(note_name_to_midi("F#5"), 78)
        self.assertEqual(note_name_to_midi("Bb3"), 58)

    def test_key_parsing(self):
        self.assertEqual(parse_key_name("C"), (0, "C"))
        self.assertEqual(parse_key_name("1=bB"), (10, "Bb"))
        self.assertEqual(parse_key_name("#F"), (6, "F#"))
        self.assertEqual(parse_key_name("D"), (2, "D"))

    def test_jianpu_mapping(self):
        self.assertEqual(jianpu_to_midi(1, key_tonic=0, base_octave=4), 60)
        self.assertEqual(jianpu_to_midi(5, key_tonic=0, base_octave=4), 67)
        self.assertEqual(jianpu_to_midi(7, key_tonic=0, base_octave=4), 71)
        self.assertEqual(
            jianpu_to_midi(4, key_tonic=2, base_octave=4, accidental=1), 68
        )
        self.assertEqual(
            jianpu_to_midi(1, key_tonic=0, base_octave=4, octave_offset=-1), 48
        )
        self.assertIsNone(jianpu_to_midi(0))

    def test_cents_and_tolerance(self):
        self.assertAlmostEqual(cents_from_midi(60.25, 60), 25.0)
        self.assertEqual(tolerance_state(10), "good")
        self.assertEqual(tolerance_state(40), "ok")
        self.assertEqual(tolerance_state(70), "bad")
        self.assertEqual(tolerance_state(None), "none")

    def test_inverse_mapping_respects_base_octave(self):
        from pitchlens.core.music import jianpu_degree_for_midi

        self.assertEqual(
            jianpu_degree_for_midi(48, key_tonic=0, base_octave=4),
            (1, 0, -1),
        )
        self.assertEqual(
            jianpu_degree_for_midi(48, key_tonic=0, base_octave=3),
            (1, 0, 0),
        )


if __name__ == "__main__":
    unittest.main()
