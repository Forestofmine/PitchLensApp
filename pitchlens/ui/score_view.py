"""Interactive score-image preview with recognition-box overlays."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.score import NoteEvent, Score
from .theme import COLORS


class ScoreImageView(QGraphicsView):
    noteClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(COLORS["bg"])))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._note_items: dict[int, QGraphicsRectItem] = {}
        self._current_id: int | None = None
        self._empty_text: QGraphicsSimpleTextItem | None = None
        self._fit_width = True
        self._zoom = 1.0
        self._show_boxes = True
        self.auto_follow = True
        # Decoded-pixmap cache: set_image_bytes is called on every editor
        # refresh (recalculate / undo / redo); decoding a multi-MB photo each
        # time stalls the GUI thread for seconds.
        self._pixmap_cache_key: int | None = None
        self._pixmap_cache: QPixmap | None = None

    # ------------------------------------------------------------- content
    def set_image_bytes(self, data: bytes | None) -> bool:
        self.scene().clear()
        self._note_items.clear()
        self._current_id = None
        self._pixmap_item = None
        if not data:
            self._add_empty_text("尚未导入简谱图片")
            self.resetTransform()
            self._pixmap_cache_key = None
            self._pixmap_cache = None
            return False
        key = hash(data)
        if key == self._pixmap_cache_key and self._pixmap_cache is not None:
            pixmap = self._pixmap_cache
        else:
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                self._add_empty_text("图片无法读取")
                return False
            self._pixmap_cache_key = key
            self._pixmap_cache = pixmap
        self._pixmap_item = self.scene().addPixmap(pixmap)
        self._pixmap_item.setZValue(0)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.resetTransform()
        self.fit_to_width()
        return True

    def set_notes(self, notes: list[NoteEvent], show_boxes: bool = True) -> None:
        self._show_boxes = show_boxes
        for item in self._note_items.values():
            self.scene().removeItem(item)
        self._note_items.clear()
        for note in notes:
            x, y, w, h = note.image_bbox
            # Skip degenerate or non-finite boxes: NaN/inf coordinates can
            # send Qt's raster paint engine into pathological behaviour.
            if not all(math.isfinite(v) for v in (x, y, w, h)):
                continue
            if w <= 0 or h <= 0 or max(abs(x), abs(y)) > 1e6:
                continue
            rect = QGraphicsRectItem(QRectF(x, y, w, h))
            rect.setData(0, int(note.id))
            rect.setData(1, float(note.confidence))
            color = _confidence_color(note.confidence)
            pen = QPen(color, 1.2)
            pen.setCosmetic(True)
            rect.setPen(pen)
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 20)))
            rect.setZValue(10)
            rect.setVisible(show_boxes)
            rect.setToolTip(
                f"#{note.id + 1} · 简谱 {note.display_degree()} · "
                f"MIDI {note.midi_pitch} · 置信度 {note.confidence:.0%}"
            )
            self.scene().addItem(rect)
            self._note_items[int(note.id)] = rect
        self._current_id = None

    def set_boxes_visible(self, visible: bool) -> None:
        self._show_boxes = visible
        for item in self._note_items.values():
            item.setVisible(visible)

    def retheme(self) -> None:
        """Repaint after the global theme (COLORS) changed."""
        self.setBackgroundBrush(QBrush(QColor(COLORS["bg"])))
        if self._empty_text is not None:
            self._empty_text.setBrush(QBrush(QColor(COLORS["muted"])))
        for note_id, item in self._note_items.items():
            if note_id == self._current_id:
                color = QColor(COLORS["accent"])
                width, alpha = 2.8, 42
            else:
                color = _confidence_color(self._confidence_from_item(item))
                width, alpha = 1.2, 20
            pen = QPen(color, width)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setBrush(
                QBrush(QColor(color.red(), color.green(), color.blue(), alpha))
            )

    def set_current_note(self, note_id: int | None) -> None:
        previous = self._current_id
        self._current_id = note_id
        if previous is not None and previous in self._note_items:
            item = self._note_items[previous]
            confidence = float(item.data(1) if item.data(1) is not None else 0.7)
            color = _confidence_color(confidence)
            pen = QPen(color, 1.2)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 20)))
            item.setZValue(10)
        if note_id is not None and note_id in self._note_items:
            item = self._note_items[note_id]
            pen = QPen(QColor(COLORS["accent"]), 2.8)
            pen.setCosmetic(True)
            item.setPen(pen)
            accent = QColor(COLORS["accent"])
            item.setBrush(
                QBrush(QColor(accent.red(), accent.green(), accent.blue(), 42))
            )
            item.setZValue(20)
            if self.auto_follow and self._fit_width:
                self.ensureVisible(item, 30, 30)

    def select_note(self, note_id: int | None) -> None:
        self.set_current_note(note_id)

    def _confidence_from_item(self, item: QGraphicsRectItem) -> float:
        value = item.data(1)
        return float(value) if value is not None else 0.7

    def _add_empty_text(self, text: str) -> None:
        item = self.scene().addSimpleText(text, QFont("Microsoft YaHei UI", 11))
        item.setBrush(QBrush(QColor(COLORS["muted"])))
        self.scene().setSceneRect(item.boundingRect().adjusted(-40, -20, 40, 20))
        self._empty_text = item

    # --------------------------------------------------------------- view
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit_width and self._pixmap_item is not None:
            self.fit_to_width()

    def fit_to_width(self) -> None:
        if self._pixmap_item is None:
            return
        rect = self._pixmap_item.boundingRect()
        if rect.width() <= 0:
            return
        available = max(40, self.viewport().width() - 18)
        factor = available / rect.width()
        factor = max(0.12, min(3.5, factor))
        self.resetTransform()
        self.scale(factor, factor)
        self._zoom = factor
        self._fit_width = True
        self.centerOn(rect.center())

    def zoom_by(self, factor: float) -> None:
        new_zoom = max(0.1, min(6.0, self._zoom * factor))
        factor = new_zoom / max(1e-6, self._zoom)
        self.scale(factor, factor)
        self._zoom = new_zoom
        self._fit_width = False

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.18 if event.angleDelta().y() > 0 else 1 / 1.18)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            # Prefer the topmost note box under the cursor.
            items = self.scene().items(point)
            for item in items:
                if isinstance(item, QGraphicsRectItem):
                    note_id = item.data(0)
                    if note_id is not None:
                        self.noteClicked.emit(int(note_id))
                        event.accept()
                        return
        super().mousePressEvent(event)


def _confidence_color(confidence: float) -> QColor:
    if confidence >= 0.80:
        return QColor(COLORS["green"])
    if confidence >= 0.55:
        return QColor(COLORS["amber"])
    return QColor(COLORS["red"])


class ScorePanel(QWidget):
    noteClicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QLabel("简谱与标准音高")
        header.setObjectName("SectionTitle")
        layout.addWidget(header)
        self.meta_label = QLabel("尚未导入乐谱")
        self.meta_label.setObjectName("Muted")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)
        self.view = ScoreImageView()
        self.view.noteClicked.connect(self.noteClicked)
        layout.addWidget(self.view, 1)
        target_card = QFrame()
        target_card.setObjectName("CardHi")
        target_layout = QVBoxLayout(target_card)
        target_layout.setContentsMargins(12, 9, 12, 9)
        target_layout.setSpacing(2)
        target_title = QLabel("当前目标")
        target_title.setObjectName("TinyMuted")
        target_layout.addWidget(target_title)
        self.target_value = QLabel("尚未导入乐谱")
        self.target_value.setStyleSheet(
            f"font-size:18px;font-weight:800;color:{COLORS['text']};"
        )
        target_layout.addWidget(self.target_value)
        self.follow_value = QLabel("跟谱：未开始")
        self.follow_value.setObjectName("Muted")
        target_layout.addWidget(self.follow_value)
        layout.addWidget(target_card)
        self.hint_label = QLabel("滚轮滚动 · Ctrl+滚轮缩放 · 点击音符定位")
        self.hint_label.setObjectName("TinyMuted")
        layout.addWidget(self.hint_label)

    def set_project(self, score: Score | None, image_bytes: bytes | None) -> None:
        if score is None:
            self.meta_label.setText("尚未导入乐谱")
            self.target_value.setText("尚未导入乐谱")
            self.follow_value.setText("跟谱：未开始")
            self.view.set_image_bytes(None)
            return
        self.meta_label.setText(score.summary())
        if score.notes:
            first = score.notes[0]
            self.target_value.setText(
                f"{score.note_name(first)}  ·  简谱 {first.display_degree()}"
            )
        else:
            self.target_value.setText("乐谱为空")
        self.follow_value.setText(f"跟谱：等待起音 · 速度 {score.tempo_hint:g} BPM")
        has_image = self.view.set_image_bytes(image_bytes)
        if has_image:
            self.view.set_notes(score.notes)
        else:
            self.view.set_notes([])

    def set_target_info(
        self,
        *,
        note_name: str | None,
        degree: str | None,
        status: str,
        tempo: float,
        confidence: float,
    ) -> None:
        if note_name and degree:
            self.target_value.setText(f"{note_name}  ·  简谱 {degree}")
        else:
            self.target_value.setText("等待起音")
        status_text = {
            "waiting": "等待起音",
            "tracking": "跟踪中",
            "paused": "保持位置",
            "lost": "跟谱丢失",
        }.get(status, status)
        self.follow_value.setText(
            f"跟谱：{status_text} · 速度 {tempo:.0f} BPM · 置信度 {confidence * 100:.0f}%"
        )

    def set_current_note(self, note_id: int | None) -> None:
        self.view.set_current_note(note_id)

    def retheme(self) -> None:
        self.view.retheme()
        self.target_value.setStyleSheet(
            f"font-size:18px;font-weight:800;color:{COLORS['text']};"
        )
