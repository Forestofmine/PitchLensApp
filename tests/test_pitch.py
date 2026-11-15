import unittest

import numpy as np

from pitchlens.core.pitch import (
    DetectorOutput,
    PitchSmoother,
    PitchFrame,
    VoicingGate,
    YinDetector,
)


class PitchTests(unittest.TestCase):
    SR = 48000
    N = 2048

    def _tone(self, frequency, amplitude=0.2, harmonics=False):
        t = np.arange(self.N) / self.SR
        if harmonics:
            x = np.zeros_like(t)
            for h in range(1, 8):
                x += (0.5 / h) * np.sin(2 * np.pi * frequency * h * t)
            x = x / max(1e-9, np.max(np.abs(x))) * amplitude
            return x
        return amplitude * np.sin(2 * np.pi * frequency * t)

    def test_known_tones(self):
        detector = YinDetector()
        for frequency in (65.4, 110.0, 220.0, 440.0, 880.0, 1046.5):
            output = detector.detect(self._tone(frequency), self.SR)
            self.assertTrue(output.voiced, frequency)
            self.assertIsNotNone(output.frequency_hz)
            cents = 1200 * np.log2(output.frequency_hz / frequency)
            self.assertLess(abs(cents), 8, f"{frequency}: {output.frequency_hz}")

    def test_silence_is_unvoiced(self):
        detector = YinDetector()
        output = detector.detect(np.zeros(self.N), self.SR)
        self.assertFalse(output.voiced)
        self.assertIsNone(output.frequency_hz)

    def test_harmonic_signal(self):
        detector = YinDetector()
        output = detector.detect(self._tone(220.0, harmonics=True), self.SR)
        self.assertTrue(output.voiced)
        self.assertLess(abs(1200 * np.log2(output.frequency_hz / 220.0)), 10)

    def test_smoother_keeps_signal(self):
        smoother = PitchSmoother(window=5)
        last = None
        for i in range(20):
            midi = 60.0 + 0.15 * np.sin(2 * np.pi * i / 10)
            frame = PitchFrame(
                audio_time=i * 0.02,
                frequency_hz=440.0,
                midi_float=midi,
                raw_midi_float=midi,
                confidence=0.9,
                voiced=True,
            )
            last = smoother.update(frame)
        self.assertIsNotNone(last)
        self.assertAlmostEqual(last.midi_float, 60.0, delta=0.15)

    def test_quiet_singing_stays_voiced(self):
        # Quiet sung vowel (RMS ~0.007, like a low-gain mic): the old fixed
        # silence gate clipped confidence below the voiced threshold forever.
        # The adaptive noise floor must let it through.
        detector = YinDetector()
        rng = np.random.default_rng(7)
        voiced = 0
        total = 0
        for i in range(40):
            t = np.arange(self.N) / self.SR
            vibrato = 1.0 + 0.006 * np.sin(2 * np.pi * 5.0 * t)
            phase = 2 * np.pi * np.cumsum(220.0 * vibrato) / self.SR
            x = 0.007 * np.sin(phase) + 0.0005 * rng.standard_normal(self.N)
            output = detector.detect(x, self.SR)
            total += 1
            voiced += int(output.voiced)
        self.assertGreater(voiced / total, 0.9, f"voiced {voiced}/{total}")

    def test_voicing_gate_bridges_weak_frames(self):
        gate = VoicingGate(max_holdover=3)
        silence = 0.004
        # Strong voiced frame establishes context.
        out = gate.update(
            DetectorOutput(220.0, 0.9, True, "yin"), rms=0.05, silence_rms=silence
        )
        self.assertTrue(out.voiced)
        self.assertAlmostEqual(out.frequency_hz, 220.0)
        # Two loud-but-unvoiced frames (consonant / weak periodicity) bridge.
        for _ in range(2):
            out = gate.update(
                DetectorOutput(None, 0.2, False, "yin"), rms=0.05, silence_rms=silence
            )
            self.assertTrue(out.voiced)
            self.assertIsNotNone(out.frequency_hz)
        # Holdover exhausted after max_holdover frames → unvoiced.
        out = gate.update(
            DetectorOutput(None, 0.2, False, "yin"), rms=0.05, silence_rms=silence
        )
        self.assertTrue(out.voiced)
        out = gate.update(
            DetectorOutput(None, 0.2, False, "yin"), rms=0.05, silence_rms=silence
        )
        self.assertFalse(out.voiced)
        # True silence: first silent frame is still bridged (two-frame grace
        # so a breath pulse does not cut a phrase), the second breaks.
        gate.reset()
        gate.update(DetectorOutput(220.0, 0.9, True, "yin"), rms=0.05, silence_rms=silence)
        out = gate.update(
            DetectorOutput(None, 0.0, False, "yin"), rms=0.001, silence_rms=silence
        )
        self.assertTrue(out.voiced)  # grace frame keeps the curve alive
        self.assertIsNotNone(out.frequency_hz)
        out = gate.update(
            DetectorOutput(None, 0.0, False, "yin"), rms=0.001, silence_rms=silence
        )
        self.assertFalse(out.voiced)
        self.assertIsNone(out.frequency_hz)
    def test_quiet_breathy_tone_stays_voiced(self):
        # Regression: the level multiplier used to be folded into the voiced
        # flag, so a quiet tone with a moderate dip (cmnd ~0.2) sat at
        # conf ~0.44 < 0.5 and the curve broke mid-note.  Voicing is now
        # decided on periodicity (base confidence) alone.
        detector = YinDetector()
        detector._noise_floor = 0.004  # silence gate ≈ 0.0088
        rng = np.random.default_rng(11)
        voiced = 0
        total = 0
        for _ in range(30):
            t = np.arange(self.N) / self.SR
            x = 0.016 * np.sin(2 * np.pi * 220.0 * t)  # rms ≈ 0.011
            x += 0.004 * rng.standard_normal(self.N)  # breathy: dips moderate
            output = detector.detect(x, self.SR)
            total += 1
            voiced += int(output.voiced)
        self.assertGreater(voiced / total, 0.8, f"voiced {voiced}/{total}")

    def test_default_gate_hangover_is_five_frames(self):
        gate = VoicingGate()
        silence = 0.004
        gate.update(DetectorOutput(220.0, 0.9, True, "yin"), rms=0.05, silence_rms=silence)
        for _ in range(5):
            out = gate.update(
                DetectorOutput(None, 0.2, False, "yin"), rms=0.05, silence_rms=silence
            )
            self.assertTrue(out.voiced)
        out = gate.update(
            DetectorOutput(None, 0.2, False, "yin"), rms=0.05, silence_rms=silence
        )
        self.assertFalse(out.voiced)

    def test_silence_grace_requires_two_frames(self):
        gate = VoicingGate()
        silence = 0.004
        gate.update(DetectorOutput(220.0, 0.9, True, "yin"), rms=0.05, silence_rms=silence)
        # One silent frame between loud content: bridged both times.
        out = gate.update(
            DetectorOutput(None, 0.0, False, "yin"), rms=0.001, silence_rms=silence
        )
        self.assertTrue(out.voiced)
        out = gate.update(
            DetectorOutput(220.0, 0.9, True, "yin"), rms=0.05, silence_rms=silence
        )
        self.assertTrue(out.voiced)
        out = gate.update(
            DetectorOutput(None, 0.0, False, "yin"), rms=0.001, silence_rms=silence
        )
        self.assertTrue(out.voiced)
        # Two consecutive silent frames break.
        out = gate.update(
            DetectorOutput(None, 0.0, False, "yin"), rms=0.001, silence_rms=silence
        )
        self.assertFalse(out.voiced)


if __name__ == "__main__":
    unittest.main()
