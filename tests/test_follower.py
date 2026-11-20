import unittest

from pitchlens.core.follower import ScoreFollower
from pitchlens.core.jianpu_text import parse_jianpu_text
from pitchlens.core.pitch import PitchFrame


def _sing(score, factors=None, dt=0.02):
    follower = ScoreFollower(score, bpm_hint=score.tempo_hint)
    time = 0.0
    factors = factors or [1.0] * len(score.notes)
    for index, note in enumerate(score.notes):
        duration = note.duration_beat * 60 / 90 * factors[index % len(factors)]
        steps = max(1, int(duration / dt))
        for step in range(steps):
            midi = float(note.midi_pitch) if note.midi_pitch is not None else None
            frame = PitchFrame(
                audio_time=time,
                frequency_hz=440.0,
                midi_float=midi,
                raw_midi_float=midi,
                confidence=0.95,
                voiced=midi is not None,
                onset_strength=0.9 if midi is not None and step == 0 else 0.03,
            )
            follower.update(frame, time)
            time += dt
    return follower, time


class FollowerTests(unittest.TestCase):
    TEXT = """1=C 4/4 90
| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |"""

    def test_constant_tempo_tracks_all_notes(self):
        score = parse_jianpu_text(self.TEXT).score
        follower, _ = _sing(score)
        self.assertEqual(follower.state.note_index, len(score.notes) - 1)
        self.assertIn(follower.state.status, {"tracking", "paused"})
        self.assertAlmostEqual(follower.state.tempo_bpm, 90.0, delta=4)

    def test_repeated_notes_and_free_tempo(self):
        text = """1=C 4/4 90
| 3 3 3 3 | 5 5 3 - | 2 2 1 - | 3 3 3 3 | 5 - - - |"""
        score = parse_jianpu_text(text).score
        factors = [1.0, 0.78, 1.18, 0.9, 1.1, 0.8, 1.2, 1.0, 0.75, 1.25, 1.0, 1.0, 1.0, 1.0, 1.0]
        follower, _ = _sing(score, factors)
        self.assertEqual(follower.state.note_index, len(score.notes) - 1)
        self.assertGreater(follower.state.confidence, 0.25)

    def test_manual_seek(self):
        score = parse_jianpu_text(self.TEXT).score
        follower = ScoreFollower(score, bpm_hint=90)
        state = follower.seek(6, 1.0)
        self.assertEqual(state.note_index, 6)
        self.assertEqual(state.target.id, 6)

    def test_waiting_requires_candidate_consistency(self):
        score = parse_jianpu_text("1=C 4/4 90\n| 1 2 1 2 |").score
        follower = ScoreFollower(score, bpm_hint=90)
        time = 0.0
        # Alternating candidates must not accumulate into a false start.
        for midi in (60.0, 62.0, 60.0, 62.0):
            frame = PitchFrame(
                audio_time=time,
                midi_float=midi,
                raw_midi_float=midi,
                confidence=0.95,
                voiced=True,
            )
            state = follower.update(frame, time)
            self.assertEqual(state.status, "waiting")
            time += 0.02
        for _ in range(2):
            frame = PitchFrame(
                audio_time=time,
                midi_float=60.0,
                raw_midi_float=60.0,
                confidence=0.95,
                voiced=True,
            )
            state = follower.update(frame, time)
            time += 0.02
        self.assertEqual(state.status, "tracking")
        self.assertEqual(state.note_index, 0)

    def test_timed_notes_are_relative(self):
        score = parse_jianpu_text(self.TEXT).score
        follower = ScoreFollower(score, bpm_hint=90)
        follower.reset(0)
        notes = follower.timed_notes(5, 5)
        self.assertTrue(notes)
        self.assertAlmostEqual(notes[0][1], 0.0, places=4)
        self.assertAlmostEqual(notes[1][1], 60 / 90, places=4)

    def test_first_rest_advances_without_voice_for_auto_start_and_seek(self):
        score = parse_jianpu_text("1=C 4/4 60\n| 0 1 2 3 |").score
        for entry in ("auto", "seek", "reset"):
            with self.subTest(entry=entry):
                follower = ScoreFollower(score, bpm_hint=60)
                if entry == "seek":
                    follower.seek(0, 10.0)
                elif entry == "reset":
                    follower.reset(0, now=10.0)
                follower.update(PitchFrame(audio_time=10.0))
                state = follower.update(PitchFrame(audio_time=10.5))
                self.assertEqual(state.note_index, 0)
                self.assertAlmostEqual(state.beat_position, 0.5)
                state = follower.update(PitchFrame(audio_time=11.0))
                self.assertEqual(state.note_index, 1)
                self.assertEqual(state.status, "tracking")

    def test_consecutive_rests_advance_without_losing_track(self):
        score = parse_jianpu_text("1=C 6/4 60\n| 1 0 0 0 0 2 |").score
        follower = ScoreFollower(score, bpm_hint=60, start_index=0)
        for step in range(50):
            follower.update(PitchFrame(audio_time=step * 0.02, midi_float=60.0, confidence=0.95, voiced=True))
        for step in range(50, 250):
            time = step * 0.02
            state = follower.update(PitchFrame(audio_time=time))
            self.assertEqual(state.note_index, int(time))
            self.assertEqual(state.status, "tracking")
            self.assertAlmostEqual(state.beat_position, time)
        state = follower.update(PitchFrame(audio_time=5.0, midi_float=62.0, confidence=0.95, voiced=True))
        self.assertEqual(state.note_index, 5)
        self.assertEqual(state.error_cents, 0.0)
        self.assertEqual(state.tempo_bpm, 60.0)

    def test_trailing_rest_reaches_end_without_losing_track(self):
        score = parse_jianpu_text("1=C 2/4 60\n| 1 0 |").score
        follower = ScoreFollower(score, bpm_hint=60, start_index=0)
        follower.update(PitchFrame(audio_time=0.2, midi_float=60.0, confidence=0.95, voiced=True))
        follower.update(PitchFrame(audio_time=1.0))
        state = follower.update(PitchFrame(audio_time=8.0))
        self.assertEqual(state.status, "paused")
        self.assertEqual(state.beat_position, 2.0)
        self.assertEqual(state.reason, "已到乐谱末尾")


if __name__ == "__main__":
    unittest.main()
