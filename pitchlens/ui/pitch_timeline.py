"""Scrolling pitch / standard-melody timeline."""

from __future__ import annotations

import math
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.follower import FollowState, ScoreFollower
from ..core.music import (
    format_cents,
    format_frequency,
    midi_to_frequency,
    midi_to_note_name,
    tolerance_state,
)
from ..core.pitch import PitchFrame
from ..core.score import NoteEvent
from ..core.settings import AppSettings
from .theme import COLORS

pg.setConfigOptions(antialias=True, useOpenGL=False, background=COLORS["bg"], foreground=COLORS["text_dim"])


def _themed_color(key: str, alpha: int | None = None) -> QColor:
    color = QColor(COLORS[key])
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def _cosmetic_pen(color: QColor, width: float = 1.0, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    return pen


def _snap_band_note(midi_float: float, current_note: int | None, hysteresis: float = 0.6) -> int:
    """Snap a live pitch to the reference semitone band, with hysteresis so a
    voice hovering near the ±50-cent boundary does not flip the band back and
    forth every frame."""
    nearest = int(round(midi_float))
    if current_note is None:
        return nearest
    if abs(midi_float - current_note) > hysteresis:
        return nearest
    return current_note


class MidiAxis(pg.AxisItem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setStyle(tickFont=QFont("Segoe UI", 8), tickTextOffset=8)
        self.setWidth(56)

    def tickStrings(self, values, scale, spacing):
        strings = []
        for value in values:
            midi = int(round(value))
            if abs(value - midi) < 0.12:
                strings.append(midi_to_note_name(midi))
            else:
                strings.append("")
        return strings


class PitchTimeline(QWidget):
    """The main visual: history on the left, current time at x=0, future right."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._frames: deque[PitchFrame] = deque(maxlen=2400)
        self._y_range = (55.0, 79.0)
        self._last_state = FollowState()
        self._last_now = 0.0
        self._last_follower: ScoreFollower | None = None
        self._paused = False
        self._band_note: int | None = None
        self._build_ui()

    # ------------------------------------------------------------------ ui
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 8)
        header_layout.setSpacing(10)
        title = QLabel("实时音高")
        title.setObjectName("SectionTitle")
        header_layout.addWidget(title)
        self.legend_label = QLabel("实测曲线  ·  左侧历史  ·  右侧标准旋律")
        self.legend_label.setObjectName("TinyMuted")
        header_layout.addWidget(self.legend_label)
        header_layout.addStretch(1)
        self.review_btn = QPushButton("回到当前")
        self.review_btn.setObjectName("Ghost")
        self.review_btn.setToolTip("从历史回看位置回到当前演唱时刻")
        self.review_btn.clicked.connect(self.return_to_current)
        self.review_btn.hide()
        header_layout.addWidget(self.review_btn)
        self.scale_label = QLabel("")
        self.scale_label.setObjectName("TinyMuted")
        header_layout.addWidget(self.scale_label)
        layout.addWidget(header)

        self.plot = pg.PlotWidget(axisItems={"left": MidiAxis(orientation="left")})
        self.plot.setBackground(COLORS["panel"])
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(False, False)
        self.plot.showGrid(x=True, y=True, alpha=0.13)
        self.plot.getViewBox().sigXRangeChanged.connect(self._on_view_range_changed)
        self.plot.getPlotItem().setContentsMargins(8, 4, 12, 8)
        self.plot.getAxis("bottom").setStyle(tickFont=QFont("Segoe UI", 8), tickTextOffset=6)
        self.plot.getAxis("bottom").setLabel("时间 / 秒", color=COLORS["muted"], size="8pt")
        self.plot.getAxis("left").setLabel("音高", color=COLORS["muted"], size="8pt")
        self.plot.setXRange(-self.settings.history_seconds, self.settings.future_seconds, padding=0)
        self.plot.setYRange(*self._y_range, padding=0)
        self.plot.getViewBox().setLimits(
            xMin=-60,
            xMax=60,
            yMin=24,
            yMax=108,
            minXRange=2,
            maxXRange=60,
            minYRange=8,
            maxYRange=60,
        )
        layout.addWidget(self.plot, 1)

        viewbox = self.plot.getViewBox()
        # Soft historical / future washes.  Colors are applied by
        # _apply_plot_colors() so retheme() can repaint everything.
        self.history_rect = QGraphicsRectItem()
        self.history_rect.setPen(QPen(Qt.PenStyle.NoPen))
        viewbox.addItem(self.history_rect, ignoreBounds=True)
        self.future_rect = QGraphicsRectItem()
        self.future_rect.setPen(QPen(Qt.PenStyle.NoPen))
        viewbox.addItem(self.future_rect, ignoreBounds=True)

        # Ideal-pitch reference band: highlights the nearest semitone's ideal
        # frequency (center line) and acceptable range while singing, so the
        # live curve can be compared against it at a glance.
        self.pitch_band_outer = QGraphicsRectItem()
        self.pitch_band_outer.setPen(QPen(Qt.PenStyle.NoPen))
        self.pitch_band_outer.setZValue(5)
        viewbox.addItem(self.pitch_band_outer, ignoreBounds=True)
        self.pitch_band_inner = QGraphicsRectItem()
        self.pitch_band_inner.setZValue(6)
        viewbox.addItem(self.pitch_band_inner, ignoreBounds=True)
        self.pitch_band_line = pg.InfiniteLine(
            angle=0,
            pos=0.0,
            movable=False,
        )
        self.pitch_band_line.setZValue(8)
        self.plot.addItem(self.pitch_band_line, ignoreBounds=True)
        self.pitch_band_label = pg.TextItem("", color=COLORS["text_dim"], anchor=(0.0, 1.0))
        self.pitch_band_label.setFont(QFont("Segoe UI", 8))
        self.pitch_band_label.setZValue(14)
        self.plot.addItem(self.pitch_band_label, ignoreBounds=True)
        for item in (
            self.pitch_band_outer,
            self.pitch_band_inner,
            self.pitch_band_line,
            self.pitch_band_label,
        ):
            item.setVisible(False)

        self.past_band = QPainterPath()
        self.past_band_item = QGraphicsPathItem()
        viewbox.addItem(self.past_band_item, ignoreBounds=True)

        self.future_band = QPainterPath()
        self.future_band_item = QGraphicsPathItem()
        viewbox.addItem(self.future_band_item, ignoreBounds=True)
        self.current_band = QPainterPath()
        self.current_band_item = QGraphicsPathItem()
        viewbox.addItem(self.current_band_item, ignoreBounds=True)

        self.center_line = pg.InfiniteLine(
            angle=90,
            pos=0.0,
            movable=False,
        )
        self.center_line.setZValue(20)
        self.plot.addItem(self.center_line, ignoreBounds=True)

        self.target_line = pg.InfiniteLine(
            angle=0,
            pos=60.0,
            movable=False,
        )
        self.target_line.setZValue(9)
        self.plot.addItem(self.target_line, ignoreBounds=True)

        self.curve_glow = pg.PlotDataItem()
        self.curve_glow.setZValue(15)
        self.plot.addItem(self.curve_glow)
        self.curve = pg.PlotDataItem()
        self.curve.setZValue(16)
        self.plot.addItem(self.curve)
        self.raw_curve = pg.PlotDataItem()
        self.raw_curve.setZValue(14)
        self.plot.addItem(self.raw_curve)

        self.deviation_line = pg.PlotDataItem()
        self.deviation_line.setZValue(18)
        self.plot.addItem(self.deviation_line)

        self.current_dot = pg.ScatterPlotItem(size=13)
        self.current_dot.setZValue(30)
        self.plot.addItem(self.current_dot)
        self.target_dot = pg.ScatterPlotItem(size=8)
        self.target_dot.setZValue(19)
        self.plot.addItem(self.target_dot)
        self._apply_plot_colors()

        self._target_labels: list[pg.TextItem] = []
        for _ in range(18):
            label = pg.TextItem("", color=COLORS["text_dim"], anchor=(0.0, 1.0))
            label.setFont(QFont("Segoe UI", 8))
            label.setZValue(14)
            label.setVisible(False)
            self.plot.addItem(label, ignoreBounds=True)
            self._target_labels.append(label)

        self.hud = QFrame(self)
        self.hud.setObjectName("Hud")
        self.hud.setFixedWidth(286)
        hud_layout = QVBoxLayout(self.hud)
        hud_layout.setContentsMargins(18, 12, 18, 12)
        hud_layout.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_pill = QLabel("等待")
        self.status_pill.setObjectName("PillInfo")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.status_pill)
        top.addStretch(1)
        self.confidence_label = QLabel("")
        self.confidence_label.setObjectName("TinyMuted")
        top.addWidget(self.confidence_label)
        hud_layout.addLayout(top)
        self.note_label = QLabel("--")
        self.note_label.setObjectName("BigNote")
        self.note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hud_layout.addWidget(self.note_label)
        self.freq_label = QLabel("--")
        self.freq_label.setObjectName("Hz")
        self.freq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hud_layout.addWidget(self.freq_label)
        self.cents_label = QLabel("等待发声")
        self.cents_label.setObjectName("Cents")
        self.cents_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hud_layout.addWidget(self.cents_label)
        self.target_label = QLabel("未导入简谱")
        self.target_label.setObjectName("Target")
        self.target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_label.setWordWrap(True)
        hud_layout.addWidget(self.target_label)
        self.hud.adjustSize()
        self.hud.raise_()

    # ----------------------------------------------------------------- theme
    def _apply_plot_colors(self) -> None:
        """(Re)apply every themed pen/brush; safe to call at any time."""
        self.history_rect.setBrush(_themed_color("wash_history", 9))
        self.future_rect.setBrush(_themed_color("wash_future", 11))
        self.pitch_band_outer.setBrush(_themed_color("accent", 13))
        self.pitch_band_inner.setBrush(_themed_color("accent", 34))
        self.pitch_band_inner.setPen(_cosmetic_pen(_themed_color("accent", 95), 1.0))
        self.pitch_band_line.setPen(_cosmetic_pen(_themed_color("accent", 150), 1.2))
        self.pitch_band_label.setColor(QColor(COLORS["text_dim"]))
        self.past_band_item.setBrush(_themed_color("target_past", 20))
        self.past_band_item.setPen(_cosmetic_pen(_themed_color("target_past", 62), 1.0))
        self._style_future_bands(self._last_state.status == "lost")
        self.current_band_item.setBrush(_themed_color("target_current", 55))
        self.current_band_item.setPen(
            _cosmetic_pen(_themed_color("target_current", 220), 1.6)
        )
        self.center_line.setPen(_cosmetic_pen(_themed_color("accent", 170), 1.2))
        self.target_line.setPen(
            _cosmetic_pen(_themed_color("green", 120), 1.1, Qt.PenStyle.DashLine)
        )
        self.curve_glow.setPen(pg.mkPen(_themed_color("curve", 30), width=11))
        self.curve.setPen(pg.mkPen(_themed_color("curve", 245), width=2.6))
        self.raw_curve.setPen(pg.mkPen(_themed_color("curve_raw", 85), width=1.0))
        self.deviation_line.setPen(pg.mkPen(_themed_color("green", 190), width=2))

    def retheme(self) -> None:
        """Repaint the plot after the global theme (COLORS) changed."""
        self.plot.setBackground(COLORS["panel"])
        fg = QColor(COLORS["text_dim"])
        grid_alpha = float(COLORS["grid_alpha"])
        for name in ("left", "bottom"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(fg))
            axis.setTextPen(pg.mkPen(fg))
            axis.setLabel(axis.labelText, color=COLORS["muted"], size="8pt")
        self.plot.showGrid(x=True, y=True, alpha=grid_alpha)
        self._apply_plot_colors()
        self.update_view(
            self._last_now, self._last_state, follower=self._last_follower
        )

    # ----------------------------------------------------------------- data
    def append_frames(self, frames: list[PitchFrame]) -> None:
        for frame in frames:
            self._frames.append(frame)
        if len(self._frames) > 2400:
            while len(self._frames) > 2400:
                self._frames.popleft()

    def clear(self) -> None:
        self._frames.clear()
        self.curve.setData([], [])
        self.curve_glow.setData([], [])
        self.raw_curve.setData([], [])
        self.current_dot.setData([], [])
        self.target_dot.setData([], [])
        self.deviation_line.setData([], [])
        self.past_band_item.setPath(QPainterPath())
        self.future_band_item.setPath(QPainterPath())
        self.current_band_item.setPath(QPainterPath())
        for label in self._target_labels:
            label.setVisible(False)
        self.target_line.setVisible(False)
        self._band_note = None
        self._set_pitch_band_visible(False)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.plot.setMouseEnabled(paused, False)
        self.review_btn.setVisible(paused)
        if paused:
            self.plot.setCursor(Qt.CursorShape.OpenHandCursor)
            self.legend_label.setText("回看模式 · 左右拖动查看历史 · 点击“回到当前”复位")
            if self._last_follower is not None:
                self.update_view(
                    self._last_now, self._last_state, follower=self._last_follower
                )
        else:
            self.plot.setCursor(Qt.CursorShape.ArrowCursor)
            self.review_btn.hide()
            self.plot.setXRange(
                -self.settings.history_seconds,
                self.settings.future_seconds,
                padding=0,
            )
            self.legend_label.setText("实测曲线  ·  左侧历史  ·  右侧标准旋律")

    def return_to_current(self) -> None:
        self.plot.setXRange(
            -self.settings.history_seconds,
            self.settings.future_seconds,
            padding=0,
        )
        if self._last_follower is not None:
            self.update_view(
                self._last_now, self._last_state, follower=self._last_follower
            )

    def _on_view_range_changed(self, *_args) -> None:
        # While paused there is no 60 fps timer: redraw labels for the newly
        # visible slice when the user drags the timeline.
        if self._paused and self._last_follower is not None:
            self.update_view(
                self._last_now, self._last_state, follower=self._last_follower
            )

    # --------------------------------------------------------------- render
    def update_view(
        self,
        now: float,
        state: FollowState,
        *,
        follower: ScoreFollower | None = None,
        detector_label: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        self._last_state = state
        self._last_now = now
        self._last_follower = follower
        history = self.settings.history_seconds
        future = self.settings.future_seconds
        left = -history
        right = future
        if self._paused:
            view_left, view_right = self.plot.getViewBox().viewRange()[0]
            data_left, data_right = -120.0, max(60.0, future)
            label_left, label_right = float(view_left), float(view_right)
            self.history_rect.setRect(
                QRectF(view_left, 24, max(0.0, -view_left), 84)
            )
            self.future_rect.setRect(QRectF(0, 24, max(0.0, view_right), 84))
        else:
            data_left, data_right = left, right
            label_left, label_right = left, right
            if self.plot.getViewBox().viewRange()[0][0] != left:
                self.plot.setXRange(left, right, padding=0)
            self.history_rect.setRect(QRectF(left, 24, -left, 84))
            self.future_rect.setRect(QRectF(0, 24, right, 84))

        xs: list[float] = []
        ys: list[float] = []
        raw_xs: list[float] = []
        raw_ys: list[float] = []
        last_voiced: PitchFrame | None = None
        for frame in self._frames:
            x = frame.audio_time - now
            if not self._paused and (x < left - 0.5 or x > right + 0.5):
                continue
            if frame.voiced and frame.midi_float is not None and math.isfinite(frame.midi_float):
                xs.append(x)
                ys.append(float(frame.midi_float))
                if frame.raw_midi_float is not None:
                    raw_xs.append(x)
                    raw_ys.append(float(frame.raw_midi_float))
                last_voiced = frame
            else:
                # A NaN breaks the line instead of connecting across silence.
                xs.append(x)
                ys.append(float("nan"))
                raw_xs.append(x)
                raw_ys.append(float("nan"))
        if xs:
            self.curve.setData(xs, ys, connect="finite")
            self.curve_glow.setData(xs, ys, connect="finite")
        else:
            self.curve.setData([], [])
            self.curve_glow.setData([], [])
        if self.settings.show_raw_curve and raw_xs:
            self.raw_curve.setData(raw_xs, raw_ys, connect="finite")
        else:
            self.raw_curve.setData([], [])

        current_midi = None
        current_hz = None
        if last_voiced is not None and (now - last_voiced.audio_time) <= 0.35:
            current_midi = last_voiced.midi_float
            current_hz = last_voiced.frequency_hz

        self._update_pitch_band(current_midi, label_left, label_right)

        self._draw_targets(
            state,
            data_left,
            data_right,
            follower,
            label_left=label_left,
            label_right=label_right,
        )
        target_midi = state.target_midi if state.target is not None else None
        target_state = "none"
        error = state.error_cents
        if current_midi is not None and target_midi is not None:
            error = (current_midi - target_midi) * 100.0
            target_state = tolerance_state(error, self.settings.good_cents, self.settings.ok_cents)
        elif current_midi is not None:
            nearest = round(current_midi)
            error = (current_midi - nearest) * 100.0
            target_state = tolerance_state(error, self.settings.good_cents, self.settings.ok_cents)

        if current_midi is not None:
            color = {
                "good": COLORS["green"],
                "ok": COLORS["amber"],
                "bad": COLORS["red"],
                "none": COLORS["accent"],
            }.get(target_state, COLORS["accent"])
            self.current_dot.setData(
                [0.0],
                [current_midi],
                brush=pg.mkBrush(QColor(color)),
                pen=pg.mkPen(_themed_color("dot_outline"), width=2),
            )
            if target_midi is not None:
                self.deviation_line.setData([0.0, 0.0], [target_midi, current_midi])
                self.target_dot.setData(
                    [0.0], [target_midi], brush=pg.mkBrush(_themed_color("green", 210)),
                    pen=pg.mkPen(_themed_color("dot_outline"), width=1),
                )
                self.target_line.setPos(float(target_midi))
                self.target_line.setVisible(self.settings.show_target_band)
            else:
                self.deviation_line.setData([], [])
                self.target_dot.setData([], [])
                self.target_line.setVisible(False)
        else:
            self.current_dot.setData([], [])
            self.target_dot.setData([], [])
            self.deviation_line.setData([], [])
            self.target_line.setVisible(False)

        self._update_y_range(current_midi, state, follower)
        self._update_hud(current_midi, current_hz, error, state, target_state)
        if not self._paused:
            if state.status == "lost":
                self.legend_label.setText("跟谱丢失 · 右侧标准旋律已变暗，等待重新定位")
            else:
                self.legend_label.setText("实测曲线  ·  左侧历史  ·  右侧标准旋律")
        self.scale_label.setText(
            f"{detector_label}  ·  {latency_ms:.0f} ms"
            if detector_label
            else ""
        )

    def _set_pitch_band_visible(self, visible: bool) -> None:
        for item in (
            self.pitch_band_outer,
            self.pitch_band_inner,
            self.pitch_band_line,
            self.pitch_band_label,
        ):
            item.setVisible(visible)

    def _update_pitch_band(
        self,
        current_midi: float | None,
        left: float,
        right: float,
    ) -> None:
        """Show the ideal-frequency reference band for the semitone nearest to
        the live pitch: outer wash = ±ok_cents, inner band = ±good_cents,
        center line = ideal pitch."""
        if current_midi is None:
            self._band_note = None
            self._set_pitch_band_visible(False)
            return
        note = _snap_band_note(current_midi, self._band_note)
        self._band_note = note
        good = self.settings.good_cents / 100.0
        ok = self.settings.ok_cents / 100.0
        width = max(0.0, right - left)
        self.pitch_band_outer.setRect(QRectF(left, note - ok, width, 2.0 * ok))
        self.pitch_band_inner.setRect(QRectF(left, note - good, width, 2.0 * good))
        self.pitch_band_line.setPos(float(note))
        freq = midi_to_frequency(note, self.settings.a4)
        self.pitch_band_label.setText(
            f"{midi_to_note_name(note)} · {freq:.1f} Hz · ±{self.settings.good_cents:.0f}¢"
        )
        self.pitch_band_label.setPos(left + 0.06, note + ok - 0.04)
        self._set_pitch_band_visible(True)

    def _draw_targets(
        self,
        state: FollowState,
        left: float,
        right: float,
        follower: ScoreFollower | None,
        *,
        label_left: float | None = None,
        label_right: float | None = None,
    ) -> None:
        past = QPainterPath()
        future = QPainterPath()
        current = QPainterPath()
        lost = state.status == "lost"
        self._style_future_bands(lost)
        if not self.settings.show_target_band:
            self.past_band_item.setPath(past)
            self.future_band_item.setPath(future)
            self.current_band_item.setPath(current)
            for label in self._target_labels:
                label.setVisible(False)
            return
        notes = (
            follower.timed_notes(
                horizon_past=120.0 if self._paused else self.settings.history_seconds,
                horizon_future=60.0 if self._paused else self.settings.future_seconds,
            )
            if follower is not None
            else []
        )
        current_index = state.note_index
        for index, (note, start, end) in enumerate(notes):
            if note.midi_pitch is None:
                continue
            if end < left or start > right:
                continue
            t0 = max(left, start)
            t1 = min(right, end)
            if t1 - t0 < 0.012:
                t1 = t0 + 0.012
            height = 0.5 if not self.settings.show_target_band else 0.5
            rect = QRectF(t0, note.midi_pitch - height / 2, t1 - t0, height)
            # The timed_notes list is a window of the whole score; find the
            # real index for current-note highlighting.
            real_index = self._real_note_index(note, state)
            if real_index == current_index:
                current.addRect(rect)
            elif end <= 0:
                past.addRect(rect)
            else:
                future.addRect(rect)
        self.past_band_item.setPath(past)
        self.future_band_item.setPath(future)
        self.current_band_item.setPath(current)
        self._place_target_labels(
            notes,
            state,
            label_left if label_left is not None else left,
            label_right if label_right is not None else right,
        )

    def _style_future_bands(self, lost: bool) -> None:
        color = QColor(COLORS["target_future_lost"] if lost else COLORS["target_future"])
        self.future_band_item.setBrush(
            QColor(color.red(), color.green(), color.blue(), 12 if lost else 20)
        )
        self.future_band_item.setPen(
            _cosmetic_pen(
                QColor(color.red(), color.green(), color.blue(), 45 if lost else 80),
                1.0,
            )
        )

    def _place_target_labels(
        self,
        notes: list[tuple[NoteEvent, float, float]],
        state: FollowState,
        left: float,
        right: float,
    ) -> None:
        for label in self._target_labels:
            label.setVisible(False)
        # Prefer the current and next few notes, then fill backwards with a
        # couple of history labels.
        ordered = []
        current_pos = 0
        for index, (note, start, end) in enumerate(notes):
            if state.target is note:
                current_pos = index
                break
        indexes = list(range(current_pos, min(len(notes), current_pos + 8)))
        indexes += list(range(max(0, current_pos - 3), current_pos))
        pool_index = 0
        for index in indexes:
            if pool_index >= len(self._target_labels):
                break
            note, start, end = notes[index]
            if note.midi_pitch is None:
                continue
            if end < left or start > right:
                continue
            if end - start < 0.24:
                continue
            label = self._target_labels[pool_index]
            pool_index += 1
            name = midi_to_note_name(note.midi_pitch)
            label.setText(f"{note.display_degree()}  {name}")
            if state.target is note:
                label.setColor(QColor(COLORS["amber"] if state.status == "lost" else COLORS["green"]))
            elif end <= 0:
                past_color = QColor(COLORS["target_past"])
                past_color.setAlpha(120)
                label.setColor(past_color)
            elif state.status == "lost":
                lost_color = QColor(COLORS["target_future_lost"])
                lost_color.setAlpha(150)
                label.setColor(lost_color)
            else:
                future_color = QColor(COLORS["target_future"])
                future_color.setAlpha(185)
                label.setColor(future_color)
            label.setPos(max(left, start) + 0.05, note.midi_pitch + 0.28)
            label.setVisible(True)

    def _real_note_index(self, note: NoteEvent, state: FollowState) -> int:
        # NoteEvent ids are stable; compare by identity first, then id.
        if state.target is note:
            return state.note_index
        return note.id

    def _update_y_range(
        self,
        current_midi: float | None,
        state: FollowState,
        follower: ScoreFollower | None,
    ) -> None:
        values: list[float] = []
        if current_midi is not None:
            values.append(float(current_midi))
        if state.target is not None and state.target.midi_pitch is not None:
            values.append(float(state.target.midi_pitch))
        if follower is not None:
            for note, _, _ in follower.timed_notes(horizon_past=2.0, horizon_future=4.0):
                if note.midi_pitch is not None:
                    values.append(float(note.midi_pitch))
        if self._paused:
            for frame in self._frames:
                if frame.voiced and frame.midi_float is not None:
                    values.append(float(frame.midi_float))
        if not values:
            return
        low = min(values) - 4.0
        high = max(values) + 4.0
        span = max(12.0, min(float(self.settings.y_span), 30.0))
        if high - low < span:
            center = (high + low) / 2.0
            low = center - span / 2.0
            high = center + span / 2.0
        low = max(28.0, low)
        high = min(104.0, high)
        old_low, old_high = self._y_range
        # Slow easing avoids the score jumping vertically on every note change.
        new_low = old_low * 0.86 + low * 0.14
        new_high = old_high * 0.86 + high * 0.14
        if abs(new_low - old_low) < 0.02 and abs(new_high - old_high) < 0.02:
            return
        self._y_range = (new_low, new_high)
        self.plot.setYRange(new_low, new_high, padding=0)

    def _update_hud(
        self,
        current_midi: float | None,
        current_hz: float | None,
        error: float | None,
        state: FollowState,
        target_state: str,
    ) -> None:
        if current_midi is None:
            self.note_label.setText("--")
            self.note_label.setStyleSheet(f"color:{COLORS['muted']};")
            self.freq_label.setText("--")
            self.cents_label.setText("等待发声")
            self.cents_label.setStyleSheet(f"color:{COLORS['muted']};")
        else:
            note_name = midi_to_note_name(current_midi, False)
            self.note_label.setText(note_name)
            color = {
                "good": COLORS["green"],
                "ok": COLORS["amber"],
                "bad": COLORS["red"],
                "none": COLORS["accent"],
            }.get(target_state, COLORS["accent"])
            self.note_label.setStyleSheet(f"color:{color};")
            self.freq_label.setText(format_frequency(current_hz))
            if error is not None:
                self.cents_label.setText(format_cents(error))
                self.cents_label.setStyleSheet(f"color:{color};")
            else:
                self.cents_label.setText("--")
        if state.target is not None and state.target.midi_pitch is not None:
            target_name = midi_to_note_name(state.target.midi_pitch, False)
            degree = state.target.display_degree()
            self.target_label.setText(
                f"目标 {target_name} / 简谱 {degree}\n{state.reason}"
            )
        else:
            self.target_label.setText(state.reason)

        if state.status == "lost":
            pill, pill_name = "跟谱丢失", "PillBad"
        elif current_midi is None:
            pill, pill_name = "无声音", "PillInfo"
        elif target_state == "good":
            pill, pill_name = "准", "PillGood"
        elif target_state == "ok":
            pill, pill_name = "略偏", "PillWarn"
        elif target_state == "bad":
            pill, pill_name = "偏差大", "PillBad"
        else:
            pill, pill_name = "跟踪中", "PillInfo"
        self.status_pill.setText(pill)
        if self.status_pill.objectName() != pill_name:
            self.status_pill.setObjectName(pill_name)
            self.status_pill.style().unpolish(self.status_pill)
            self.status_pill.style().polish(self.status_pill)
        if current_midi is None:
            self.confidence_label.setText("")
        else:
            self.confidence_label.setText(f"置信度 {int(round(state.confidence * 100))}%")

    # --------------------------------------------------------------- layout
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        hud_width = self.hud.width()
        x = max(8, (self.width() - hud_width) // 2)
        self.hud.move(x, 54)
        self.hud.raise_()
