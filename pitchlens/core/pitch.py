"""Pitch detection and post-processing.

The application talks to a small ``PitchDetector`` interface.  YIN is shipped as
the always-available detector; a CREPE adapter is provided for machines where
ONNX Runtime (or torchcrepe) and the model file are available.  Keeping the
interface narrow means the detector can be replaced without touching the audio
thread or the UI.
"""

from __future__ import annotations

import importlib.util
import math
import os
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from .music import frequency_to_midi


class DetectorUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DetectorOutput:
    frequency_hz: float | None
    confidence: float
    voiced: bool
    algorithm: str = "yin"


@dataclass
class PitchFrame:
    audio_time: float
    frequency_hz: float | None = None
    midi_float: float | None = None
    confidence: float = 0.0
    voiced: bool = False
    onset_strength: float = 0.0
    rms: float = 0.0
    latency_ms: float = 0.0
    # The follower uses this unsmoothed value; the UI draws ``midi_float``.
    raw_midi_float: float | None = None

    @property
    def midi(self) -> float | None:
        return self.midi_float

    def copy(self) -> "PitchFrame":
        return replace(self)


class PitchDetector(Protocol):
    name: str

    def detect(self, samples: np.ndarray, sample_rate: int) -> DetectorOutput:
        ...


class YinDetector:
    """Fast YIN detector suitable for monophonic singing.

    The implementation uses an FFT-free autocorrelation formulation:
    d(tau) = sum(x[:N-tau]^2) + sum(x[tau:]^2) - 2 * sum(x[:N-tau] * x[tau:])
    ``np.correlate`` computes the last term in C, which keeps 20 ms updates
    comfortable on a normal laptop CPU.
    """

    name = "YIN"

    def __init__(
        self,
        fmin: float = 65.0,
        fmax: float = 1200.0,
        threshold: float = 0.14,
        silence_rms: float = 0.004,
    ) -> None:
        self.fmin = float(fmin)
        self.fmax = float(fmax)
        self.threshold = float(threshold)
        # silence_rms is only the *initial* noise-floor estimate; the floor
        # adapts at runtime (see detect()).  A fixed threshold kills quiet
        # singing outright: with the old gate, RMS below ~0.008 could never
        # reach the voiced confidence threshold.
        self._noise_floor = float(silence_rms)

    @property
    def current_silence_rms(self) -> float:
        return max(0.0012, min(0.02, self._noise_floor * 2.2))

    def _update_noise_floor(self, rms: float, periodic: bool) -> None:
        floor = self._noise_floor
        if periodic:
            # Periodic content is signal: never let the floor rise into it,
            # but allow the floor to *fall* quickly for quiet singing.  The
            # fall must be fast (~150 ms): a singer locked out by a too-high
            # initial estimate should not sing a full second before the gate
            # opens.
            target = rms / 4.0
            if target < floor:
                floor += 0.25 * (target - floor)
        else:
            # Non-periodic frames (noise, breath, consonants) track the floor:
            # fast downwards, very slow upwards so consonants cannot push the
            # floor up into the sung level.
            floor += (0.03 if rms < floor else 0.002) * (rms - floor)
        self._noise_floor = float(np.clip(floor, 0.0008, 0.03))

    def detect(self, samples: np.ndarray, sample_rate: int) -> DetectorOutput:
        x = np.asarray(samples, dtype=np.float64).reshape(-1)
        if x.size < 128:
            return DetectorOutput(None, 0.0, False, "yin")
        rms = float(np.sqrt(np.mean(x * x) + 1e-12))
        if rms < 0.0008:
            # Absolute floor: digital silence.  No floor update here — one
            # muted moment must not drag the estimate to zero.
            return DetectorOutput(None, 0.0, False, "yin")

        x = x - float(np.mean(x))
        n = x.size
        tau_min = max(2, int(math.floor(sample_rate / self.fmax)))
        tau_max = min(int(math.ceil(sample_rate / self.fmin)), n // 2 - 1)
        if tau_max <= tau_min + 2:
            return DetectorOutput(None, 0.0, False, "yin")

        corr = np.correlate(x, x, mode="full")[n - 1 :]
        energy = np.cumsum(x * x)
        total = energy[-1]
        taus = np.arange(tau_min, tau_max + 1)
        # e0 = sum_{j=0}^{n-tau-1} x[j]^2  (energy before the shifted part)
        e0 = energy[n - taus - 1]
        # e1 = sum_{j=tau}^{n-1} x[j]^2
        e1 = total - np.where(taus > 1, energy[taus - 1], 0.0)
        diff = np.maximum(0.0, e0 + e1 - 2.0 * corr[taus])
        if diff.size == 0 or not np.isfinite(diff).any():
            return DetectorOutput(None, 0.0, False, "yin")

        cmnd = np.ones_like(diff)
        cumulative = np.cumsum(diff[1:])
        indexes = np.arange(1, diff.size)
        cmnd[1:] = diff[1:] * indexes / np.maximum(cumulative, 1e-12)

        # Choose the first *local* minimum below the threshold.  This is the
        # classic YIN rule and avoids the octave-down error of taking a global
        # minimum at 2x the period.  If no convincing dip exists, fall back to
        # the global minimum and let the confidence gate decide.
        local_minima = [
            index
            for index in range(1, cmnd.size - 1)
            if cmnd[index] <= cmnd[index - 1]
            and cmnd[index] <= cmnd[index + 1]
            and cmnd[index] < self.threshold
        ]
        idx = int(local_minima[0]) if local_minima else int(np.argmin(cmnd))
        if idx <= 0 or idx >= cmnd.size - 1:
            self._update_noise_floor(rms, periodic=False)
            return DetectorOutput(None, 0.0, False, "yin")
        cmnd_min = float(cmnd[idx])

        # Frames with a plausible dip (even a weak one, e.g. breathy voice)
        # are signal and only push the noise floor *down*; clearly aperiodic
        # frames track the ambient noise floor.
        self._update_noise_floor(rms, periodic=cmnd_min < 0.35)
        silence = self.current_silence_rms
        if rms < silence * 0.75:
            return DetectorOutput(None, 0.0, False, "yin")

        # Parabolic interpolation around the selected lag.
        a, b, c = cmnd[idx - 1], cmnd[idx], cmnd[idx + 1]
        denominator = a - 2.0 * b + c
        delta = 0.5 * (a - c) / denominator if abs(denominator) > 1e-12 else 0.0
        tau = float(taus[idx]) + float(np.clip(delta, -0.5, 0.5))
        if tau <= 0:
            return DetectorOutput(None, 0.0, False, "yin")
        frequency = float(sample_rate) / tau
        if not (self.fmin * 0.97 <= frequency <= self.fmax * 1.03):
            return DetectorOutput(None, 0.0, False, "yin")
        base_conf = float(np.clip(1.0 - cmnd_min, 0.0, 1.0))
        # The level factor only scales the *reported* confidence (follower /
        # HUD).  Folding it into the voiced flag created a cliff: quiet but
        # clean singing sat right at conf 0.5 and flickered frame to frame,
        # which showed up as the curve breaking mid-note.  Voicing is decided
        # on periodicity (level-independent) plus a slightly relaxed level
        # floor instead.
        floor_conf = 0.55 if cmnd_min < 0.08 else 0.35
        confidence = base_conf * float(np.clip((rms / silence - 1.0) / 1.2, floor_conf, 1.0))
        voiced = base_conf >= 0.5 and rms >= silence * 0.9
        return DetectorOutput(frequency, confidence, voiced, "yin")


class CrepeDetector:
    """CREPE adapter (ONNX first, torchcrepe second).

    The adapter is deliberately optional: the default build stays small and
    fully offline.  When a model/runtime is present the UI can select CREPE;
    otherwise the application transparently falls back to YIN.
    """

    name = "CREPE"

    def __init__(
        self,
        model_path: str | os.PathLike[str] | None = None,
        fmin: float = 65.0,
        fmax: float = 1200.0,
        confidence_threshold: float = 0.45,
    ) -> None:
        self.model_path = Path(model_path).expanduser() if model_path else None
        self.fmin = float(fmin)
        self.fmax = float(fmax)
        self.confidence_threshold = float(confidence_threshold)
        self._session = None
        self._torch_model = None
        self._torch = None
        self._backend = ""
        self._load()

    def _load(self) -> None:
        if self.model_path and self.model_path.exists():
            try:
                import onnxruntime as ort  # type: ignore

                providers = ["CPUExecutionProvider"]
                self._session = ort.InferenceSession(
                    str(self.model_path), providers=providers
                )
                self._backend = "onnx"
                return
            except Exception:
                self._session = None
        if importlib.util.find_spec("torchcrepe") is not None and importlib.util.find_spec("torch") is not None:
            try:
                import torch  # type: ignore
                import torchcrepe  # type: ignore

                self._torch = torch
                self._torch_model = torchcrepe.load.model("full", "cpu")
                self._backend = "torchcrepe"
                return
            except Exception:
                self._torch_model = None
        raise DetectorUnavailable(
            "CREPE 不可用：未找到 ONNX Runtime/模型，也未安装 torchcrepe。"
            "当前将使用 YIN 检测器。"
        )

    def detect(self, samples: np.ndarray, sample_rate: int) -> DetectorOutput:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(x * x) + 1e-12))
        if rms < 0.004:
            return DetectorOutput(None, 0.0, False, "crepe")
        if self._backend == "onnx" and self._session is not None:
            # CREPE expects 1024 samples at 16 kHz.  The audio layer already
            # downsamples; this guard keeps the adapter usable from tests.
            if sample_rate != 16000:
                x = _resample_linear(x, sample_rate, 16000)
            if x.size < 1024:
                x = np.pad(x, (0, 1024 - x.size))
            else:
                x = x[-1024:]
            x = x - float(np.mean(x))
            x = x / (float(np.std(x)) + 1e-6)
            inputs = {self._session.get_inputs()[0].name: x[None, :].astype(np.float32)}
            output = self._session.run(None, inputs)[0]
            probs = np.asarray(output).reshape(-1)
            if probs.size != 360:
                return DetectorOutput(None, 0.0, False, "crepe")
            bin_index = int(np.argmax(probs))
            confidence = float(probs[bin_index])
            cents = 1997.3794084376191 + 20.0 * bin_index
            frequency = 10.0 * (2.0 ** (cents / 1200.0))
            voiced = confidence >= self.confidence_threshold and self.fmin <= frequency <= self.fmax
            return DetectorOutput(frequency if voiced else None, confidence, voiced, "crepe")
        if self._backend == "torchcrepe" and self._torch is not None:
            if sample_rate != 16000:
                x = _resample_linear(x, sample_rate, 16000)
            tensor = self._torch.tensor(x, dtype=self._torch.float32).unsqueeze(0)
            with self._torch.no_grad():
                frequency, confidence = __import__("torchcrepe").predict(
                    tensor,
                    fmin=self.fmin,
                    fmax=self.fmax,
                    model="full",
                    batch_size=1,
                    device="cpu",
                    return_periodicity=True,
                )
            freq_value = float(np.asarray(frequency).reshape(-1)[0])
            conf_value = float(np.asarray(confidence).reshape(-1)[0])
            voiced = conf_value >= self.confidence_threshold and self.fmin <= freq_value <= self.fmax
            return DetectorOutput(freq_value if voiced else None, conf_value, voiced, "crepe")
        return DetectorOutput(None, 0.0, False, "crepe")


def _resample_linear(x: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or x.size == 0:
        return x.astype(np.float32, copy=False)
    duration = x.size / float(source_rate)
    target_size = max(1, int(round(duration * target_rate)))
    old_positions = np.linspace(0.0, 1.0, x.size, endpoint=False)
    new_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
    return np.interp(new_positions, old_positions, x).astype(np.float32)


def detector_available(name: str) -> tuple[bool, str]:
    if str(name).lower() != "crepe":
        return True, ""
    try:
        CrepeDetector()
        return True, ""
    except Exception as exc:  # pragma: no cover - depends on local install
        return False, str(exc)


def create_detector(
    name: str = "yin",
    *,
    fmin: float = 65.0,
    fmax: float = 1200.0,
    crepe_model: str | None = None,
) -> PitchDetector:
    if str(name).lower() == "crepe":
        try:
            return CrepeDetector(crepe_model, fmin=fmin, fmax=fmax)
        except DetectorUnavailable:
            return YinDetector(fmin=fmin, fmax=fmax)
    return YinDetector(fmin=fmin, fmax=fmax)


class VoicingGate:
    """Hysteresis + short hangover between the detector and the display.

    A legato vowel with a weak frame, or a brief consonant, must not chop the
    curve; real silence still breaks it (after a two-frame grace so a single
    breath-pulse/consonant dip below the noise floor does not cut a phrase).
    Hangover frames carry a decaying confidence so the score follower (which
    requires confidence >= 0.42) ignores them — bridging is a display property
    only.
    """

    def __init__(
        self,
        max_holdover: int = 5,
        exit_conf: float = 0.28,
        tolerance_semitones: float = 1.2,
    ) -> None:
        self.max_holdover = int(max_holdover)
        self.exit_conf = float(exit_conf)
        self.tolerance = float(tolerance_semitones)
        self._hold = 0
        self._silent = 0
        self._last_freq: float | None = None

    def reset(self) -> None:
        self._hold = 0
        self._silent = 0
        self._last_freq = None

    def update(
        self, out: DetectorOutput, *, rms: float, silence_rms: float
    ) -> DetectorOutput:
        if out.voiced and out.frequency_hz:
            self._hold = 0
            self._silent = 0
            self._last_freq = out.frequency_hz
            return out
        if rms < silence_rms:
            self._silent += 1
            if self._silent >= 2 or self._last_freq is None:
                # True silence: break and forget the pitch context.
                self._hold = 0
                self._silent = 0
                self._last_freq = None
                return DetectorOutput(None, float(out.confidence), False, out.algorithm)
            # Single-frame dip below the floor: fall through to bridging.
        else:
            self._silent = 0
        if self._last_freq is None or self._hold >= self.max_holdover:
            self._last_freq = None
            return DetectorOutput(None, float(out.confidence), False, out.algorithm)
        freq = out.frequency_hz
        chosen = self._last_freq
        if freq is not None and out.confidence >= self.exit_conf:
            jump = abs(12.0 * math.log2(freq / self._last_freq))
            if jump <= self.tolerance:
                chosen = freq  # same note, weak frame: keep the fresh reading
        self._hold += 1
        confidence = max(float(out.confidence), 0.4) * (0.85 ** self._hold)
        return DetectorOutput(chosen, confidence, True, out.algorithm)


class PitchSmoother:
    """Very light median smoothing for display only.

    The follower always receives the raw frame, as required by the design: the
    target note must never pull the measured curve towards itself.
    """

    def __init__(self, window: int = 5) -> None:
        self.window = max(1, int(window))
        self._values: deque[float] = deque(maxlen=self.window)
        self._last_voiced: PitchFrame | None = None

    def reset(self) -> None:
        self._values.clear()
        self._last_voiced = None

    def update(self, frame: PitchFrame) -> PitchFrame:
        if not frame.voiced or frame.midi_float is None:
            self._values.clear()
            return replace(frame, midi_float=None)
        self._values.append(float(frame.midi_float))
        # A five-frame median removes isolated octave/outlier errors while
        # preserving real vibrato (the window is only ~100 ms at 50 fps).
        value = float(np.median(np.asarray(self._values, dtype=np.float64)))
        smoothed = replace(frame, midi_float=value)
        self._last_voiced = smoothed
        return smoothed
