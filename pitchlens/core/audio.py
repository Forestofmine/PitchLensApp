"""Audio capture and off-thread pitch analysis.

The PortAudio callback only copies samples and advances a frame counter.  All
resampling, detection and smoothing happen on a worker thread so that a slow
model can never stall the audio callback (a common cause of clicks/dropouts).
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

from .music import frequency_to_midi
from .pitch import (
    PitchDetector,
    PitchFrame,
    PitchSmoother,
    VoicingGate,
    YinDetector,
    create_detector,
)


@dataclass
class AudioDeviceInfo:
    index: int
    name: str
    hostapi: str
    channels: int
    default_samplerate: float
    is_default: bool = False

    @property
    def label(self) -> str:
        suffix = "  · 默认" if self.is_default else ""
        return f"[{self.index}] {self.name}  ({self.hostapi}){suffix}"


def list_input_devices() -> list[AudioDeviceInfo]:
    """Return usable input devices, with a readable host-API label."""
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        try:
            default_input = int(sd.default.device[0])
        except Exception:
            default_input = -1
        result: list[AudioDeviceInfo] = []
        for index, device in enumerate(devices):
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
            host_index = int(device.get("hostapi", -1))
            host_name = ""
            if 0 <= host_index < len(hostapis):
                host_name = str(hostapis[host_index].get("name", ""))
            device_name = str(device.get("name", f"输入设备 {index}"))
            # WDM-KS exposes raw driver pins as "devices" — dozens of bogus
            # entries whose names are driver paths; opening them fails with
            # PaErrorCode -9996.  MME / DirectSound / WASAPI are the usable
            # host APIs on a normal Windows machine.
            if "wdm-ks" in host_name.lower():
                continue
            lowered = device_name.lower()
            if "system32" in lowered or "\\driver" in lowered or lowered.endswith(".sys"):
                continue
            result.append(
                AudioDeviceInfo(
                    index=index,
                    name=device_name,
                    hostapi=host_name,
                    channels=int(device.get("max_input_channels", 1)),
                    default_samplerate=float(device.get("default_samplerate", 48000)),
                    is_default=index == default_input,
                )
            )
        return _dedupe_devices(result)
    except Exception:
        return []


# Lower number = preferred host API when the same physical microphone shows
# up under several APIs (MME / DirectSound / WASAPI all wrap the same hardware).
_HOST_PRIORITY = {
    "windows wasapi": 0,
    "windows directsound": 1,
    "mme": 2,
}


def _host_priority(hostapi: str) -> int:
    return _HOST_PRIORITY.get(hostapi.strip().lower(), 3)


def _device_key(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _same_device(a: str, b: str) -> bool:
    ka, kb = _device_key(a), _device_key(b)
    if ka == kb:
        return True
    # WASAPI truncates long device names; treat a clear prefix as the same mic.
    shorter, longer = (ka, kb) if len(ka) <= len(kb) else (kb, ka)
    return len(shorter) >= 12 and longer.startswith(shorter)


def _dedupe_devices(devices: list[AudioDeviceInfo]) -> list[AudioDeviceInfo]:
    kept: list[AudioDeviceInfo] = []
    for device in devices:
        match = next(
            (d for d in kept if _same_device(d.name, device.name)), None
        )
        if match is None:
            kept.append(device)
            continue
        # Same physical device via another host API: keep the better one.
        better, worse = device, match
        if _host_priority(match.hostapi) < _host_priority(device.hostapi):
            better, worse = match, device
        if worse.is_default and not better.is_default:
            better.is_default = True
        if better is device:
            kept[kept.index(match)] = device
    # Default input first, then stable by device index.
    kept.sort(key=lambda d: (not d.is_default, d.index))
    return kept


def preferred_input_device() -> int | None:
    devices = list_input_devices()
    if not devices:
        return None
    # WASAPI generally gives the lowest latency on Windows.
    for device in devices:
        if "WASAPI" in device.hostapi and device.is_default:
            return device.index
    for device in devices:
        if "WASAPI" in device.hostapi:
            return device.index
    for device in devices:
        if device.is_default:
            return device.index
    return devices[0].index


class AudioRingBuffer:
    def __init__(self, capacity: int = 48000 * 4) -> None:
        self.capacity = max(4, int(capacity))
        self._buffer = np.zeros(self.capacity, dtype=np.float32)
        self._write = 0
        self.total_written = 0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._buffer.fill(0.0)
            self._write = 0
            self.total_written = 0

    def write(self, samples: np.ndarray) -> None:
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return
        with self._lock:
            if x.size >= self.capacity:
                self._buffer[:] = x[-self.capacity :]
                self._write = 0
                self.total_written += x.size
                return
            end = self._write + x.size
            if end <= self.capacity:
                self._buffer[self._write : end] = x
            else:
                first = self.capacity - self._write
                self._buffer[self._write :] = x[:first]
                self._buffer[: end - self.capacity] = x[first:]
            self._write = end % self.capacity
            self.total_written += x.size

    def read_last(self, count: int) -> np.ndarray | None:
        count = int(count)
        if count <= 0 or count > self.capacity:
            return None
        with self._lock:
            if self.total_written < count:
                return None
            end = self._write
            start = end - count
            if start >= 0:
                return self._buffer[start:end].copy()
            return np.concatenate((self._buffer[start:], self._buffer[:end])).copy()

    @property
    def available(self) -> int:
        with self._lock:
            return min(self.total_written, self.capacity)


class AudioEngine:
    """Owns the microphone stream and the pitch-analysis worker."""

    def __init__(
        self,
        detector_name: str = "yin",
        *,
        sample_rate: int = 48000,
        window_size: int = 2048,
        hop_size: int = 960,
        fmin: float = 65.0,
        fmax: float = 1200.0,
        crepe_model: str | None = None,
        latency_offset_ms: float = 0.0,
        a4: float = 440.0,
    ) -> None:
        self.requested_detector_name = detector_name
        self.detector: PitchDetector = create_detector(
            detector_name, fmin=fmin, fmax=fmax, crepe_model=crepe_model
        )
        self.sample_rate = int(sample_rate)
        self.window_size = int(window_size)
        self.hop_size = int(hop_size)
        self.latency_offset_ms = float(latency_offset_ms)
        self.a4 = float(a4)
        self._ring = AudioRingBuffer(capacity=int(self.sample_rate * 4))
        self._queue: queue.Queue[PitchFrame] = queue.Queue(maxsize=400)
        self._stream: sd.InputStream | None = None
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._smoother = PitchSmoother(window=5)
        self._gate = VoicingGate()
        self._device_index: int | None = None
        self._last_processed_total = 0
        self._last_rms = 0.0
        self._last_voice_time = 0.0
        self._error: str | None = None
        self._lock = threading.Lock()
        self._callback_count = 0
        self._dropped_callbacks = 0
        self._analysis_ms = 0.0
        self._started_at = 0.0

    # ------------------------------------------------------------- devices
    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        return list_input_devices()

    @property
    def detector_label(self) -> str:
        return getattr(self.detector, "name", self.requested_detector_name)

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def analysis_ms(self) -> float:
        return self._analysis_ms

    @property
    def dropped_callbacks(self) -> int:
        return self._dropped_callbacks

    @property
    def device_index(self) -> int | None:
        return self._device_index

    # --------------------------------------------------------------- start
    def start(self, device: int | None = None) -> tuple[bool, str]:
        if self._running.is_set():
            return True, "已在运行"
        self._error = None
        self._ring.reset()
        self._queue = queue.Queue(maxsize=400)
        self._last_processed_total = 0
        self._last_rms = 0.0
        self._smoother.reset()
        self._gate.reset()
        self._callback_count = 0
        self._dropped_callbacks = 0
        chosen = device if device is not None else preferred_input_device()
        ok, message = self._try_open(chosen)
        if not ok and chosen is not None:
            # The remembered/selected device may be stale (unplugged, driver
            # change) or a bogus entry — fall back to the system default once
            # instead of leaving the user stuck on an error dialog.
            fallback = preferred_input_device()
            if fallback is not None and fallback != chosen:
                ok, fallback_message = self._try_open(fallback)
                if ok:
                    return True, f"{fallback_message}（首选设备已失效，已改用默认输入）"
                message += f"；默认设备也失败：{fallback_message}"
        if not ok:
            self._error = message
            return False, f"无法打开麦克风：{message}"
        return True, message

    def _try_open(self, device: int | None) -> tuple[bool, str]:
        candidates = [self.sample_rate]
        if self.sample_rate != 44100:
            candidates.append(44100)
        last_error = ""
        for rate in candidates:
            stream = None
            try:
                self._ring = AudioRingBuffer(capacity=int(rate * 4))
                stream = sd.InputStream(
                    device=device,
                    channels=1,
                    samplerate=rate,
                    blocksize=0,
                    dtype="float32",
                    latency="low",
                    callback=self._callback,
                )
                stream.start()
                self._stream = stream
                self.sample_rate = int(rate)
                self._device_index = device
                self._running.set()
                self._started_at = time.perf_counter()
                self._worker = threading.Thread(
                    target=self._analysis_loop, name="pitch-analysis", daemon=True
                )
                self._worker.start()
                name = ""
                try:
                    info = sd.query_devices(device)
                    name = str(info.get("name", ""))
                except Exception:
                    pass
                return True, f"已启动：{name or '默认输入'} @ {self.sample_rate} Hz"
            except Exception as exc:  # PortAudio errors vary by host API
                last_error = f"{type(exc).__name__}: {exc}"
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass
                self._stream = None
                continue
        return False, last_error or "无法打开麦克风"

    def stop(self) -> None:
        self._running.clear()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        worker = self._worker
        self._worker = None
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.5)
        self._smoother.reset()

    # ------------------------------------------------------------- callback
    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            # Do not block or print heavily inside the audio callback.
            self._dropped_callbacks += 1
        try:
            x = np.asarray(indata, dtype=np.float32)
            if x.ndim > 1:
                x = x[:, 0]
            self._ring.write(x)
            self._callback_count += 1
        except Exception:
            self._dropped_callbacks += 1

    # --------------------------------------------------------------- worker
    def _analysis_loop(self) -> None:
        while self._running.is_set():
            total = self._ring.total_written
            if total < self.window_size:
                time.sleep(0.004)
                continue
            if total - self._last_processed_total < self.hop_size:
                time.sleep(0.003)
                continue
            window = self._ring.read_last(self.window_size)
            if window is None:
                time.sleep(0.004)
                continue
            self._last_processed_total = total
            started = time.perf_counter()
            try:
                output = self.detector.detect(window, self.sample_rate)
            except Exception as exc:
                with self._lock:
                    self._error = f"音高检测失败：{exc}"
                time.sleep(0.02)
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._analysis_ms = 0.85 * self._analysis_ms + 0.15 * elapsed_ms
            audio_time = total / float(self.sample_rate)
            rms = float(np.sqrt(np.mean(window * window) + 1e-12))
            # Hysteresis/hangover: keep legato phrases and brief consonants
            # from chopping the curve; true silence still breaks it.
            output = self._gate.update(
                output,
                rms=rms,
                silence_rms=float(
                    getattr(self.detector, "current_silence_rms", 0.004)
                ),
            )
            # Onset strength is a cheap energy-rise measure.  The follower uses
            # it to disambiguate repeated notes; it is intentionally not part
            # of the measured pitch.
            onset = max(0.0, rms - self._last_rms) / max(self._last_rms, 0.006)
            self._last_rms = 0.9 * self._last_rms + 0.1 * rms
            midi_float = (
                frequency_to_midi(output.frequency_hz, self.a4)
                if output.frequency_hz
                else None
            )
            frame = PitchFrame(
                audio_time=audio_time,
                frequency_hz=output.frequency_hz,
                midi_float=midi_float,
                confidence=float(output.confidence),
                voiced=bool(output.voiced and output.frequency_hz),
                onset_strength=float(np.clip(onset, 0.0, 1.0)),
                rms=rms,
                latency_ms=elapsed_ms,
            )
            display_frame = self._smoother.update(frame)
            # Keep raw fields available, but replace midi_float for display.
            display_frame.raw_midi_float = frame.midi_float
            display_frame.frequency_hz = frame.frequency_hz
            display_frame.confidence = frame.confidence
            display_frame.voiced = frame.voiced
            display_frame.onset_strength = frame.onset_strength
            display_frame.rms = frame.rms
            display_frame.latency_ms = frame.latency_ms
            self._enqueue(display_frame)
            if frame.voiced:
                self._last_voice_time = audio_time

    def _enqueue(self, frame: PitchFrame) -> None:
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                self._dropped_callbacks += 1

    def poll_frames(self, max_items: int = 32) -> list[PitchFrame]:
        frames: list[PitchFrame] = []
        for _ in range(max_items):
            try:
                frames.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return frames

    def audio_time(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self._ring.total_written / float(self.sample_rate)

    def display_time(self) -> float:
        return self.audio_time() - self.latency_offset_ms / 1000.0

    def clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


class MicTester:
    """Live level monitor + record/playback for the settings dialog.

    Lets the user hear what the currently selected device/sample-rate actually
    captures before starting a session.  Independent from AudioEngine so the
    settings dialog can poke devices freely.
    """

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._level = 0.0
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self.sample_rate = 48000

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def start(self, device: int | None, sample_rate: int) -> tuple[bool, str]:
        self.stop()
        try:
            stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=int(sample_rate),
                blocksize=0,
                dtype="float32",
                latency="low",
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        self._stream = stream
        self.sample_rate = int(sample_rate)
        return True, ""

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        try:
            x = np.asarray(indata, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt(np.mean(x * x) + 1e-12))
            with self._lock:
                self._level = 0.65 * self._level + 0.35 * rms
                if self._recording:
                    self._chunks.append(x.copy())
        except Exception:
            pass

    def level_db(self) -> float:
        with self._lock:
            rms = self._level
        return 20.0 * math.log10(max(rms, 1e-6))

    def start_recording(self) -> None:
        with self._lock:
            self._chunks = []
            self._recording = True

    def stop_recording(self) -> np.ndarray:
        with self._lock:
            self._recording = False
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._level = 0.0
            self._recording = False
            self._chunks = []


class SimulatedAudioEngine:
    """Small deterministic source used by tests and the UI demo/screenshot mode.

    It implements the same ``start/stop/poll_frames/audio_time`` surface as
    ``AudioEngine`` so the UI can run without a microphone.
    """

    def __init__(self, notes: list[tuple[float, float]] | None = None, speed: float = 1.0) -> None:
        self.notes = notes or [(0.0, 60), (1.0, 62), (2.0, 64), (3.0, 65)]
        self.speed = speed
        self.sample_rate = 48000
        self._running = False
        self._start = 0.0
        self._last_index = 0
        self._queue: queue.Queue[PitchFrame] = queue.Queue()
        self._error = None
        self._device_index = None
        self.detector = YinDetector()
        self.latency_offset_ms = 0.0
        self.analysis_ms = 0.0
        self.dropped_callbacks = 0

    @property
    def detector_label(self) -> str:
        return "模拟音源"

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, device: int | None = None) -> tuple[bool, str]:
        self._running = True
        self._start = time.perf_counter()
        self._last_index = 0
        return True, "模拟音源已启动"

    def stop(self) -> None:
        self._running = False

    def poll_frames(self, max_items: int = 32) -> list[PitchFrame]:
        """Generate frames lazily from wall-clock time."""
        if not self._running:
            return []
        now = (time.perf_counter() - self._start) * self.speed
        frames: list[PitchFrame] = []
        # Generate at 50 Hz up to the current time.
        frame_period = 0.02
        next_time = (self._last_index + 1) * frame_period
        while next_time <= now and len(frames) < max_items:
            midi = 60.0
            for start, pitch in self.notes:
                if next_time >= start:
                    midi = float(pitch)
            vibrato = 0.08 * np.sin(2 * np.pi * 5.0 * next_time)
            frames.append(
                PitchFrame(
                    audio_time=next_time,
                    frequency_hz=440.0 * 2 ** ((midi + vibrato - 69.0) / 12.0),
                    midi_float=midi + vibrato,
                    confidence=0.96,
                    voiced=True,
                    onset_strength=0.2,
                    rms=0.08,
                )
            )
            self._last_index += 1
            next_time = (self._last_index + 1) * frame_period
        return frames

    def audio_time(self) -> float:
        return (time.perf_counter() - self._start) * self.speed

    def display_time(self) -> float:
        return self.audio_time()

    def clear_queue(self) -> None:
        pass
