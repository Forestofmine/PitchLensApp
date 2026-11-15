"""Online score following with free-tempo estimation.

This is a constrained online-HMM/Viterbi-style tracker: the hidden state is the
current score note, transitions are limited to stay / next / skip-nearby, and
the transition prior is modulated by the expected note duration and the
observed onset.  A local pitch search plus a re-localisation state handles
wrong notes, breaths and mid-song starts.  Manual seeking is always available,
which is important because repeated identical notes are inherently ambiguous
from pitch alone.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from .pitch import PitchFrame
from .score import NoteEvent, Score


@dataclass
class FollowState:
    status: str = "waiting"  # waiting / tracking / paused / lost
    note_index: int = -1
    confidence: float = 0.0
    beat_position: float = 0.0
    tempo_bpm: float = 90.0
    error_cents: float | None = None
    pitch_distance: float | None = None
    target: NoteEvent | None = None
    target_start_offset: float = 0.0
    target_end_offset: float = 0.0
    reason: str = "等待起唱"
    in_tune: bool = False

    @property
    def is_tracking(self) -> bool:
        return self.status in {"tracking", "paused"}

    @property
    def target_midi(self) -> int | None:
        return self.target.midi_pitch if self.target is not None else None


@dataclass
class _Candidate:
    index: int
    distance: float
    when: float


class ScoreFollower:
    def __init__(
        self,
        score: Score | None = None,
        *,
        bpm_hint: float = 90.0,
        start_index: int | None = None,
        good_cents: float = 50.0,
    ) -> None:
        self.score = score or Score()
        self.bpm_hint = max(30.0, min(260.0, float(bpm_hint)))
        self.good_cents = float(good_cents)
        self._preferred_start = start_index
        self._auto_start = start_index is None
        self.reset(start_index)

    # ------------------------------------------------------------- lifecycle
    def set_score(self, score: Score, bpm_hint: float | None = None) -> None:
        self.score = score
        if bpm_hint is not None:
            self.bpm_hint = max(30.0, min(260.0, float(bpm_hint)))
        self.reset(self._preferred_start)

    def reset(self, start_index: int | None = None) -> None:
        self._preferred_start = start_index
        self._auto_start = start_index is None
        self.index = int(start_index) if start_index is not None else -1
        if self.index >= len(self.score.notes):
            self.index = len(self.score.notes) - 1
        self.status = "waiting" if self.index < 0 else "tracking"
        self.tempo_bpm = float(self.bpm_hint or self.score.tempo_hint or 90.0)
        self.beat_position = (
            float(self.score.notes[self.index].start_beat) if self.index >= 0 else 0.0
        )
        self._note_enter_time = 0.0
        self._last_frame_time = 0.0
        self._last_voiced_time = 0.0
        self._last_target_time = 0.0
        self._error_ema: float | None = None
        self._confidence = 0.0
        self._candidate_history: deque[_Candidate] = deque(maxlen=8)
        self._match_streak = 0
        self._waiting_candidate = -1
        self._wrong_streak = 0
        self._advance_pending = 0
        self._last_reason = "等待起唱" if self.index < 0 else "已定位，等待发声"
        self._last_state = self._state(
            self.status, self.index, self._last_reason, None
        )

    # --------------------------------------------------------------- public
    def seek(self, note_index: int, now: float | None = None) -> FollowState:
        if not self.score.notes:
            return self._last_state
        index = max(0, min(len(self.score.notes) - 1, int(note_index)))
        self.index = index
        self.status = "tracking"
        self._note_enter_time = float(now if now is not None else self._last_frame_time)
        self.beat_position = float(self.score.notes[index].start_beat)
        self._match_streak = 0
        self._wrong_streak = 0
        self._confidence = 0.35
        self._last_reason = f"手动定位到第 {index + 1} 个音符"
        return self._make_state(self.score.notes[index], None)

    def update(self, frame: PitchFrame, now: float | None = None) -> FollowState:
        """Consume one raw (or lightly smoothed) pitch frame."""
        if not self.score.notes:
            self._last_state = FollowState(status="waiting", reason="尚未导入乐谱")
            return self._last_state
        current_time = float(now if now is not None else frame.audio_time)
        dt = current_time - self._last_frame_time if self._last_frame_time else 0.02
        dt = max(0.001, min(0.25, dt))
        self._last_frame_time = current_time
        midi = (
            frame.raw_midi_float
            if frame.raw_midi_float is not None
            else frame.midi_float
        )
        voiced = bool(frame.voiced and midi is not None and frame.confidence >= 0.42)
        if voiced:
            self._last_voiced_time = current_time

        if self.status == "waiting":
            return self._update_waiting(frame, current_time, midi, voiced)
        if self.status == "lost":
            return self._update_lost(frame, current_time, midi, voiced)
        if self.status in {"tracking", "paused"}:
            return self._update_tracking(frame, current_time, midi, voiced, dt)
        return self._last_state

    # -------------------------------------------------------------- waiting
    def _update_waiting(
        self, frame: PitchFrame, now: float, midi: float | None, voiced: bool
    ) -> FollowState:
        if not voiced:
            self._match_streak = 0
            self._waiting_candidate = -1
            return self._state("waiting", self.index, "等待起唱", None)
        assert midi is not None
        if self._preferred_start is not None:
            candidates = [self._preferred_start]
        else:
            candidates = range(len(self.score.notes))
        best_index = -1
        best_distance = 999.0
        for index in candidates:
            note = self.score.notes[index]
            if note.midi_pitch is None:
                continue
            distance = abs(midi - note.midi_pitch)
            if distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance <= 0.9:
            if best_index == self._waiting_candidate:
                self._match_streak += 1
            else:
                # Two frames matching different notes must not accumulate into
                # a false start (important for repeated notes / wide vibrato).
                self._waiting_candidate = best_index
                self._match_streak = 1
        else:
            self._waiting_candidate = -1
            self._match_streak = 0
        if self._match_streak >= 2:
            self.index = best_index
            self.status = "tracking"
            self._note_enter_time = now
            self.beat_position = float(self.score.notes[best_index].start_beat)
            self._confidence = 0.55
            self._last_reason = f"起唱定位：第 {best_index + 1} 个音符"
            return self._make_state(self.score.notes[best_index], midi)
        return self._state(
            "waiting",
            -1,
            f"等待起唱（最近候选偏差 {best_distance * 100:.0f}¢）",
            midi,
        )

    # ---------------------------------------------------------------- lost
    def _update_lost(
        self, frame: PitchFrame, now: float, midi: float | None, voiced: bool
    ) -> FollowState:
        if not voiced:
            return self._state("lost", self.index, "跟谱丢失，等待重新定位", None)
        assert midi is not None
        best_index = -1
        best_distance = 999.0
        # Prefer the neighbourhood of the last known position: repeated notes
        # make a global search prone to jumping back to the first occurrence.
        nearby = list(
            range(max(0, self.index - 2), min(len(self.score.notes), self.index + 10))
        )
        rest = [i for i in range(len(self.score.notes)) if i not in nearby]
        for index in nearby + rest:
            note = self.score.notes[index]
            if note.midi_pitch is None:
                continue
            distance = abs(midi - note.midi_pitch)
            if distance < best_distance - 1e-9:
                best_distance = distance
                best_index = index
        if best_index >= 0 and best_distance <= 0.6:
            self._match_streak += 1
        else:
            self._match_streak = 0
        if self._match_streak >= 3:
            self.index = best_index
            self.status = "tracking"
            self._note_enter_time = now
            self.beat_position = float(self.score.notes[best_index].start_beat)
            self._confidence = 0.5
            self._match_streak = 0
            self._last_reason = f"重新定位：第 {best_index + 1} 个音符"
            return self._make_state(self.score.notes[best_index], midi)
        return self._state("lost", self.index, "跟谱丢失，正在搜索位置", midi)

    # ------------------------------------------------------------- tracking
    def _update_tracking(
        self,
        frame: PitchFrame,
        now: float,
        midi: float | None,
        voiced: bool,
        dt: float,
    ) -> FollowState:
        note = self.score.notes[self.index]
        expected = max(0.08, note.duration_beat * 60.0 / max(30.0, self.tempo_bpm))

        if not voiced:
            silence = now - self._last_voiced_time
            if silence < 0.9:
                self.status = "paused"
                self._last_reason = "换气/无声，保持位置"
                return self._state("paused", self.index, self._last_reason, None)
            if silence < 2.4:
                self.status = "paused"
                self._last_reason = "无声音，等待继续"
                return self._state("paused", self.index, self._last_reason, None)
            self.status = "lost"
            self._match_streak = 0
            self._last_reason = "长时间无声，跟谱丢失"
            return self._state("lost", self.index, self._last_reason, None)

        assert midi is not None
        self.status = "tracking"
        target_midi = note.midi_pitch
        if target_midi is None:
            # Rest: advance silently after its nominal duration.
            elapsed = now - self._note_enter_time
            if elapsed >= expected * 0.95:
                return self._advance(now, midi, elapsed, note)
            return self._state("tracking", self.index, "休止", midi)

        distance = midi - target_midi
        cents = distance * 100.0
        self._error_ema = (
            cents if self._error_ema is None else 0.78 * self._error_ema + 0.22 * cents
        )
        self._confidence = 0.84 * self._confidence + 0.16 * max(
            0.0, 1.0 - min(1.0, abs(distance) / 1.5)
        )
        self.beat_position = min(
            note.start_beat + note.duration_beat + 0.5,
            note.start_beat + max(0.0, now - self._note_enter_time) * self.tempo_bpm / 60.0,
        )
        self._last_target_time = now

        if abs(distance) <= 0.52:
            self._match_streak = min(10, self._match_streak + 1)
            self._wrong_streak = 0
        else:
            self._wrong_streak += 1
            self._match_streak = 0

        elapsed = now - self._note_enter_time
        in_tune = abs(cents) <= self.good_cents
        next_note = self._next_sung_note(self.index + 1)
        if next_note is not None:
            next_index, next_note_obj = next_note
            next_distance = abs(midi - (next_note_obj.midi_pitch or midi))
            same_pitch = (
                target_midi is not None
                and next_note_obj.midi_pitch is not None
                and abs(next_note_obj.midi_pitch - target_midi) < 0.01
            )
            onset = frame.onset_strength >= 0.50
            if same_pitch:
                # Repeated identical notes are inherently ambiguous from pitch
                # alone.  Require a re-articulation onset, or the written
                # duration, before moving on.
                if (onset and elapsed >= expected * 0.55) or elapsed >= expected * 0.95:
                    return self._advance(now, midi, elapsed, note)
            else:
                # Normal note change: the singer must actually be near the next
                # pitch, and enough of the current note must have elapsed.
                if elapsed >= expected * 0.65 and (
                    next_distance <= 0.55 or (onset and next_distance <= 0.85)
                ):
                    return self._advance(now, midi, elapsed, note)
                if elapsed >= expected * 1.25 and next_distance <= 0.65:
                    return self._advance(now, midi, elapsed, note)
                if elapsed >= expected * 1.90 and abs(distance) <= 0.85:
                    return self._advance(now, midi, elapsed, note)

        # A narrow skip-ahead rule: only when the pitch is clearly *not* the
        # current note and matches a note two positions ahead.  This avoids the
        # classic "same pitch appears later" false jump.
        if abs(distance) >= 0.9 and elapsed >= expected * 0.55:
            jump = self._best_nearby_match(midi, self.index + 2, 2)
            if jump is not None and jump[1] <= 0.45:
                self._advance_pending += 1
                if self._advance_pending >= 3:
                    self.index = jump[0]
                    self._note_enter_time = now
                    self.beat_position = float(self.score.notes[self.index].start_beat)
                    self._advance_pending = 0
                    self._match_streak = 0
                    self._last_reason = f"跳音定位：第 {self.index + 1} 个音符"
                    return self._make_state(self.score.notes[self.index], midi)
            else:
                self._advance_pending = 0

        # 3) Wrong-note persistence: do not instantly abandon the position;
        #    wait long enough to distinguish a scoop/vibrato from a real error.
        if self._wrong_streak >= 18 and elapsed > expected * 1.5:
            self.status = "lost"
            self._last_reason = "持续偏离标准音，跟谱丢失"
            return self._state("lost", self.index, self._last_reason, midi)

        reason = "跟踪中" if in_tune else ("偏高" if cents > 0 else "偏低")
        return self._state("tracking", self.index, reason, midi)

    # --------------------------------------------------------------- advance
    def _advance(self, now: float, midi: float, elapsed: float, note: NoteEvent) -> FollowState:
        observed = 60.0 * note.duration_beat / max(0.12, elapsed)
        if 35.0 <= observed <= 240.0:
            # Slow adaptation, so a single held note does not wreck the tempo.
            self.tempo_bpm = max(
                35.0, min(240.0, 0.82 * self.tempo_bpm + 0.18 * observed)
            )
        next_index = self._next_sung_index(self.index + 1)
        if next_index is None:
            self.status = "paused"
            self._last_reason = "已到乐谱末尾"
            return self._state("paused", self.index, self._last_reason, midi)
        self.index = next_index
        self._note_enter_time = now
        self.beat_position = float(self.score.notes[next_index].start_beat)
        self._match_streak = 0
        self._wrong_streak = 0
        self._advance_pending = 0
        self._last_reason = f"进入第 {next_index + 1} 个音符"
        return self._make_state(self.score.notes[next_index], midi)

    def _next_sung_index(self, start: int) -> int | None:
        for index in range(max(0, start), len(self.score.notes)):
            if self.score.notes[index].midi_pitch is not None:
                return index
        return None

    def _next_sung_note(self, start: int) -> tuple[int, NoteEvent] | None:
        index = self._next_sung_index(start)
        if index is None:
            return None
        return index, self.score.notes[index]

    def _best_nearby_match(
        self, midi: float, start: int, count: int
    ) -> tuple[int, float] | None:
        best: tuple[int, float] | None = None
        for index in range(max(0, start), min(len(self.score.notes), start + count)):
            note = self.score.notes[index]
            if note.midi_pitch is None:
                continue
            distance = abs(midi - note.midi_pitch)
            if best is None or distance < best[1]:
                best = (index, distance)
        return best

    # ---------------------------------------------------------------- state
    def _make_state(self, note: NoteEvent | None, midi: float | None) -> FollowState:
        state = self._state(self.status, self.index, self._last_reason, midi, note)
        self._last_state = state
        return state

    def _state(
        self,
        status: str,
        index: int,
        reason: str,
        midi: float | None,
        note: NoteEvent | None = None,
    ) -> FollowState:
        note = note if note is not None else (
            self.score.notes[index] if 0 <= index < len(self.score.notes) else None
        )
        error = None
        if midi is not None and note is not None and note.midi_pitch is not None:
            error = (float(midi) - float(note.midi_pitch)) * 100.0
        sec_per_beat = 60.0 / max(30.0, self.tempo_bpm)
        start_offset = end_offset = 0.0
        if note is not None:
            start_offset = (note.start_beat - self.beat_position) * sec_per_beat
            end_offset = (note.end_beat - self.beat_position) * sec_per_beat
        return FollowState(
            status=status,
            note_index=index,
            confidence=float(max(0.0, min(1.0, self._confidence))),
            beat_position=float(self.beat_position),
            tempo_bpm=float(self.tempo_bpm),
            error_cents=error,
            pitch_distance=None if error is None else error / 100.0,
            target=note,
            target_start_offset=start_offset,
            target_end_offset=end_offset,
            reason=reason,
            in_tune=error is not None and abs(error) <= self.good_cents,
        )

    # ------------------------------------------------------------- timeline
    def timed_notes(self, horizon_past: float = 10.0, horizon_future: float = 10.0) -> list[tuple[NoteEvent, float, float]]:
        """Return (note, start_seconds_relative_to_now, end_seconds) for drawing.

        The mapping is based on the *estimated* beat position and tempo, so the
        future score stretches and compresses with the singer.
        """
        sec_per_beat = 60.0 / max(30.0, self.tempo_bpm)
        result: list[tuple[NoteEvent, float, float]] = []
        for note in self.score.notes:
            start = (note.start_beat - self.beat_position) * sec_per_beat
            end = (note.end_beat - self.beat_position) * sec_per_beat
            if end < -horizon_past or start > horizon_future:
                continue
            result.append((note, start, end))
        return result

    @property
    def state(self) -> FollowState:
        return self._last_state
