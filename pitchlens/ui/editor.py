"""Visual jianpu correction dialog."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.music import KEY_CHOICES, midi_to_note_name, parse_key_name
from ..core.score import NoteEvent, Score
from .score_view import ScoreImageView
from .theme import COLORS

_COLUMNS = ["#", "小节", "音级", "八度", "变音", "时值", "MIDI", "音名", "置信度"]

# Durations in beats (quarter note = 1 beat).  The four quick buttons cover
# the common cases; the editable combo carries everything else plus free
# numeric input.
_QUICK_DURATIONS = [("16分", 0.25), ("8分", 0.5), ("4分", 1.0), ("2分", 2.0)]
_DURATION_CHOICES = [
    ("32分音符", 0.125),
    ("16分音符", 0.25),
    ("附点16分音符", 0.375),
    ("8分音符", 0.5),
    ("附点8分音符", 0.75),
    ("4分音符", 1.0),
    ("附点4分音符", 1.5),
    ("2分音符", 2.0),
    ("附点2分音符", 3.0),
    ("全音符", 4.0),
]


class ScoreEditorDialog(QDialog):
    def __init__(self, score: Score, image_bytes: bytes | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("识谱校正 · PitchLens")
        self.resize(1260, 820)
        self.setMinimumSize(980, 640)
        self.score = score.copy()
        self.image_bytes = image_bytes
        self.result_score: Score | None = None
        self._updating = False
        # Snapshot-based undo/redo: Score.copy() is cheap at this scale and
        # immune to partial-mutation bugs.
        self._undo_stack: list[Score] = []
        self._redo_stack: list[Score] = []
        self._build_ui()
        self._load_metadata()
        self._rebuild_table()
        self._refresh_preview()

    # ------------------------------------------------------------------ ui
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("识谱校正")
        title.setStyleSheet(f"font-size:20px;font-weight:800;color:{COLORS['text']};")
        title_row.addWidget(title)
        subtitle = QLabel("所有识别结果都可修改；低频置信度会用黄/红框标出")
        subtitle.setObjectName("Muted")
        title_row.addWidget(subtitle)
        title_row.addStretch(1)
        self.warning_pill = QLabel("")
        self.warning_pill.setObjectName("PillWarn")
        title_row.addWidget(self.warning_pill)
        root.addLayout(title_row)

        meta_frame = QFrame()
        meta_frame.setObjectName("Card")
        meta_layout = QHBoxLayout(meta_frame)
        meta_layout.setContentsMargins(14, 10, 14, 10)
        meta_layout.setSpacing(12)

        self.title_edit = QLineEdit()
        self.title_edit.setMinimumWidth(180)
        self.key_combo = QComboBox()
        self.key_combo.addItems(KEY_CHOICES)
        self.key_combo.setEditable(True)
        self.key_combo.setMinimumWidth(86)
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(1, 8)
        self.octave_spin.setSuffix(" 八度")
        self.meter_num = QSpinBox()
        self.meter_num.setRange(1, 16)
        self.meter_den = QComboBox()
        self.meter_den.addItems(["2", "4", "8", "16"])
        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(20, 300)
        self.bpm_spin.setDecimals(1)
        self.bpm_spin.setSuffix(" BPM")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["大调 (major)", "小调 (minor)"])
        self.mode_combo.setMinimumWidth(120)

        for label, widget in [
            ("标题", self.title_edit),
            ("调号 1=", self.key_combo),
            ("基准", self.octave_spin),
            ("拍号", self._meter_widget()),
            ("速度", self.bpm_spin),
            ("调式", self.mode_combo),
        ]:
            cell = QVBoxLayout()
            cell.setSpacing(3)
            text = QLabel(label)
            text.setObjectName("TinyMuted")
            cell.addWidget(text)
            cell.addWidget(widget)
            meta_layout.addLayout(cell)
        meta_layout.addStretch(1)
        root.addWidget(meta_frame)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)
        hint = QLabel("原图与识别框 · 点击音符跳转表格")
        hint.setObjectName("TinyMuted")
        left_layout.addWidget(hint)
        self.image_view = ScoreImageView()
        self.image_view.noteClicked.connect(self._select_note_by_id)
        left_layout.addWidget(self.image_view, 1)
        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(6)
        table_header = QHBoxLayout()
        table_title = QLabel("音符列表")
        table_title.setObjectName("SectionTitle")
        table_header.addWidget(table_title)
        table_header.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("TinyMuted")
        table_header.addWidget(self.count_label)
        right_layout.addLayout(table_header)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        header = self.table.horizontalHeader()
        # Interactive (fixed) widths: ResizeToContents mode re-measures every
        # cell on each change — fine for 20 rows, fatal for 359.  Explicit
        # resizeColumnsToContents() runs at controlled moments instead.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        right_layout.addWidget(self.table, 1)
        # Duration toolbar: quick buttons for the common note values plus an
        # editable combo for dotted/other values — typing raw beat numbers in
        # the table is error-prone when fixing OCR duration mistakes.
        duration_row = QHBoxLayout()
        duration_row.setSpacing(6)
        duration_label = QLabel("时值")
        duration_label.setObjectName("TinyMuted")
        duration_row.addWidget(duration_label)
        self.duration_buttons = []
        for text, beats in _QUICK_DURATIONS:
            btn = QPushButton(text)
            btn.setObjectName("Ghost")
            btn.setToolTip(f"把选中音符的时值设为 {beats:g} 拍（{text}音符）")
            btn.clicked.connect(
                lambda _checked=False, value=beats: self._set_duration_for_selected(value)
            )
            self.duration_buttons.append(btn)
            duration_row.addWidget(btn)
        self.duration_combo = QComboBox()
        self.duration_combo.setEditable(True)
        for text, beats in _DURATION_CHOICES:
            self.duration_combo.addItem(text, beats)
        self.duration_combo.setMinimumWidth(140)
        self.duration_combo.setToolTip("更多时值；也可以直接输入拍数，如 0.75、1.5、3")
        self.duration_combo.activated.connect(self._on_duration_combo_activated)
        self.duration_combo.lineEdit().returnPressed.connect(self._on_duration_text_entered)
        duration_row.addWidget(self.duration_combo)
        duration_row.addStretch(1)
        right_layout.addLayout(duration_row)
        actions = QHBoxLayout()
        self.add_button = QPushButton("插入音符")
        self.add_button.setObjectName("Ghost")
        self.add_button.setToolTip("在选中音符后面插入一个新音符；未选中时加到末尾")
        self.add_button.clicked.connect(self._add_note)
        self.delete_button = QPushButton("删除选中")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._delete_selected)
        self.recalc_button = QPushButton("重新计算")
        self.recalc_button.setObjectName("Ghost")
        self.recalc_button.clicked.connect(self._recalculate)
        self.undo_button = QPushButton("撤销")
        self.undo_button.setObjectName("Ghost")
        self.undo_button.setToolTip("撤销上一步修改（Ctrl+Z）")
        self.undo_button.clicked.connect(self._undo)
        self.redo_button = QPushButton("恢复")
        self.redo_button.setObjectName("Ghost")
        self.redo_button.setToolTip("恢复被撤销的修改（Ctrl+Y）")
        self.redo_button.clicked.connect(self._redo)
        actions.addWidget(self.add_button)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.recalc_button)
        actions.addSpacing(12)
        actions.addWidget(self.undo_button)
        actions.addWidget(self.redo_button)
        actions.addStretch(1)
        right_layout.addLayout(actions)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)
        self._update_undo_buttons()
        self._set_duration_controls_enabled(False)
        splitter.addWidget(right)
        splitter.setSizes([700, 520])
        root.addWidget(splitter, 1)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("Muted")
        root.addWidget(self.warning_label)
        self.confirm_recognition = QCheckBox("已核对识谱提示，应用时清除这些提示")
        root.addWidget(self.confirm_recognition)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply
        )
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("Ghost")
        apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply.setText("应用校正")
        apply.setObjectName("Accent")
        # QDialogButtonBox emits accepted() only for AcceptRole buttons (OK/Save).
        # Apply has ApplyRole and only emits clicked() — wiring accepted() here
        # would leave the button dead.
        apply.clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _meter_widget(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.meter_num)
        slash = QLabel("/")
        slash.setObjectName("Muted")
        layout.addWidget(slash)
        layout.addWidget(self.meter_den)
        return widget

    # -------------------------------------------------------------- loading
    def _load_metadata(self) -> None:
        self._updating = True
        self.title_edit.setText(self.score.title)
        key = self.score.key_name
        if self.key_combo.findText(key) < 0:
            self.key_combo.addItem(key)
        self.key_combo.setCurrentText(key)
        self.octave_spin.setValue(self.score.base_octave)
        self.meter_num.setValue(self.score.meter_num)
        self.meter_den.setCurrentText(str(self.score.meter_den))
        self.bpm_spin.setValue(self.score.tempo_hint)
        self.mode_combo.setCurrentIndex(1 if self.score.mode.startswith("min") else 0)
        self._updating = False

    def _refresh_preview(self) -> None:
        self.confirm_recognition.setVisible(self.score.source == "image" and bool(self.score.source_warnings))
        self.image_view.set_image_bytes(self.image_bytes)
        self.image_view.set_notes(self.score.notes)
        self.warning_label.setText(" · ".join(self.score.warnings[:4]))
        self.warning_label.setToolTip("\n".join(self.score.warnings))
        if self.score.warnings:
            self.warning_pill.setText(f"{len(self.score.warnings)} 项待确认")
            self.warning_pill.setObjectName("PillWarn")
        else:
            self.warning_pill.setText("时值校验通过")
            self.warning_pill.setObjectName("PillGood")
        self.warning_pill.style().unpolish(self.warning_pill)
        self.warning_pill.style().polish(self.warning_pill)

    def _rebuild_table(self) -> None:
        t0 = time.perf_counter()
        logging.info("editor.table start rows=%d", len(self.score.notes))
        self._updating = True
        self.table.setUpdatesEnabled(False)
        try:
            header = self.table.horizontalHeader()
            # Bulk-fill must not run with ResizeToContents sections: on a
            # visible view every setItem re-measures ALL rows in that column
            # (O(n²) font-metric calls), which froze the dialog for minutes.
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            self.table.setRowCount(len(self.score.notes))
            logging.info(
                "editor.table setRowCount done %.0fms", (time.perf_counter() - t0) * 1000
            )
            for row, note in enumerate(self.score.notes):
                values = [
                    str(row + 1),
                    str(note.measure_index + 1),
                    str(note.degree),
                    f"{note.octave_offset:+d}" if note.octave_offset else "0",
                    "#" if note.accidental > 0 else "b" if note.accidental < 0 else "—",
                    f"{note.duration_beat:g}",
                    str(note.midi_pitch) if note.midi_pitch is not None else "—",
                    self.score.note_name(note),
                    f"{note.confidence:.0%}",
                ]
                for col, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter if col != 7 else Qt.AlignmentFlag.AlignLeft
                    )
                    if col in (1, 2, 3, 4, 5):
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                        item.setBackground(QColor(COLORS["panel_alt"]))
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setForeground(QColor(COLORS["text_dim"]))
                    if col == 8:
                        confidence = note.confidence
                        if confidence >= 0.8:
                            item.setForeground(QColor(COLORS["green"]))
                        elif confidence >= 0.55:
                            item.setForeground(QColor(COLORS["amber"]))
                        else:
                            item.setForeground(QColor(COLORS["red"]))
                    self.table.setItem(row, col, item)
                self.table.setRowHeight(row, 27)
            logging.info(
                "editor.table items done %.0fms", (time.perf_counter() - t0) * 1000
            )
            self.table.resizeColumnsToContents()
            logging.info(
                "editor.table resizeColumns done %.0fms", (time.perf_counter() - t0) * 1000
            )
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
            self.count_label.setText(
                f"{len(self.score.notes)} 个音符 / {self.score.measure_count} 小节"
            )
            logging.info("editor.table done %.0fms", (time.perf_counter() - t0) * 1000)
        finally:
            self.table.setUpdatesEnabled(True)
            self._updating = False

    # --------------------------------------------------------------- events
    def _select_note_by_id(self, note_id: int) -> None:
        for row, note in enumerate(self.score.notes):
            if note.id == note_id:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0))
                break

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.image_view.set_current_note(None)
            self._set_duration_controls_enabled(False)
            return
        row = rows[0].row()
        if 0 <= row < len(self.score.notes):
            self.image_view.set_current_note(self.score.notes[row].id)
        self._set_duration_controls_enabled(True)
        self._sync_duration_combo()

    # ------------------------------------------------------ duration toolbar
    def _set_duration_controls_enabled(self, enabled: bool) -> None:
        for btn in self.duration_buttons:
            btn.setEnabled(enabled)
        self.duration_combo.setEnabled(enabled)

    def _sync_duration_combo(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if not (0 <= row < len(self.score.notes)):
            return
        beats = float(self.score.notes[row].duration_beat)
        for index in range(self.duration_combo.count()):
            data = self.duration_combo.itemData(index)
            if data is not None and abs(float(data) - beats) < 1e-9:
                self.duration_combo.setCurrentIndex(index)
                return
        self.duration_combo.setCurrentText(f"{beats:g} 拍")

    def _on_duration_combo_activated(self, index: int) -> None:
        beats = self.duration_combo.itemData(index)
        if beats is not None:
            self._set_duration_for_selected(float(beats))

    def _on_duration_text_entered(self) -> None:
        typed = self.duration_combo.currentText().strip()
        # A named choice typed out in full resolves to its value first.
        for index in range(self.duration_combo.count()):
            if self.duration_combo.itemText(index) == typed:
                self._set_duration_for_selected(float(self.duration_combo.itemData(index)))
                return
        try:
            beats = float(typed.replace("拍", "").strip())
        except ValueError:
            self._sync_duration_combo()  # revert the display
            return
        if not 0.0625 <= beats <= 16:
            self._sync_duration_combo()
            return
        self._set_duration_for_selected(beats)

    def _set_duration_for_selected(self, beats: float) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        if not (0 <= row < len(self.score.notes)):
            return
        note = self.score.notes[row]
        if abs(float(note.duration_beat) - beats) < 1e-9:
            return
        self._push_undo(self.score.copy())
        note.duration_beat = float(beats)
        # Duration is not part of the (measure, id) sort key, so the row
        # order is stable; refresh derived cells in place.
        self.score.refresh()
        self._refresh_after_model_change(rebuild_table=False)
        self._sync_duration_combo()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row = item.row()
        col = item.column()
        if not (0 <= row < len(self.score.notes)):
            return
        note = self.score.notes[row]
        # Object identity, not note.id: refresh() renumbers ids sequentially,
        # so id lists always look ordered even after a re-sort.
        order_before = [id(n) for n in self.score.notes]
        snapshot = self.score.copy()
        try:
            if col == 1:
                value = max(0, int(item.text()) - 1)
                note.measure_index = value
            elif col == 2:
                value = int(item.text())
                if not 0 <= value <= 7:
                    raise ValueError
                note.degree = value
            elif col == 3:
                value = int(item.text())
                if not -3 <= value <= 3:
                    raise ValueError
                note.octave_offset = value
            elif col == 4:
                text = item.text().strip().lower()
                note.accidental = 1 if text in {"#", "升"} else -1 if text in {"b", "降"} else 0
            elif col == 5:
                value = float(item.text())
                if not 0.0625 <= value <= 16:
                    raise ValueError
                note.duration_beat = value
        except (ValueError, TypeError):
            self._rebuild_table()
            return
        self._push_undo(snapshot)
        self.score.refresh()
        if [id(n) for n in self.score.notes] != order_before:
            # refresh() re-sorts notes by (measure, id); a measure edit can
            # therefore reorder the list.  Rebuild the whole table so rows and
            # notes stay aligned, and keep the edited note selected.
            self._refresh_after_model_change(rebuild_table=True)
            try:
                new_row = self.score.notes.index(note)
            except ValueError:
                new_row = -1
            if new_row >= 0:
                self.table.selectRow(new_row)
                self.table.scrollToItem(self.table.item(new_row, 0))
            return
        self._refresh_after_model_change(rebuild_table=False)

    def _refresh_after_model_change(self, rebuild_table: bool) -> None:
        if rebuild_table:
            self._rebuild_table()
        else:
            # Update derived cells without destroying the cell being edited.
            self._updating = True
            for row, note in enumerate(self.score.notes):
                if row >= self.table.rowCount():
                    break
                self.table.item(row, 1).setText(str(note.measure_index + 1))
                self.table.item(row, 2).setText(str(note.degree))
                self.table.item(row, 3).setText(
                    f"{note.octave_offset:+d}" if note.octave_offset else "0"
                )
                self.table.item(row, 4).setText(
                    "#" if note.accidental > 0 else "b" if note.accidental < 0 else "—"
                )
                self.table.item(row, 5).setText(f"{note.duration_beat:g}")
                self.table.item(row, 6).setText(
                    str(note.midi_pitch) if note.midi_pitch is not None else "—"
                )
                self.table.item(row, 7).setText(self.score.note_name(note))
            self._updating = False
        self.image_view.set_notes(self.score.notes)
        self.warning_label.setText(" · ".join(self.score.warnings[:4]))
        self.warning_label.setToolTip("\n".join(self.score.warnings))
        if self.score.warnings:
            self.warning_pill.setText(f"{len(self.score.warnings)} 项待确认")
            self.warning_pill.setObjectName("PillWarn")
        else:
            self.warning_pill.setText("时值校验通过")
            self.warning_pill.setObjectName("PillGood")
        self.warning_pill.style().unpolish(self.warning_pill)
        self.warning_pill.style().polish(self.warning_pill)
        self.count_label.setText(f"{len(self.score.notes)} 个音符 / {self.score.measure_count} 小节")
        self._sync_duration_combo()

    def _add_note(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        insert_after = rows[0].row() if rows else -1
        self._push_undo(self.score.copy())
        if 0 <= insert_after < len(self.score.notes):
            # Insert right after the selected note, copying its pitch and
            # duration as the starting point for the fix.
            anchor = self.score.notes[insert_after]
            note = NoteEvent(
                id=-1,  # renumbered below
                degree=anchor.degree,
                accidental=anchor.accidental,
                octave_offset=anchor.octave_offset,
                duration_beat=anchor.duration_beat,
                measure_index=anchor.measure_index,
                confidence=1.0,
                image_bbox=tuple(anchor.image_bbox),
            )
            self.score.notes.insert(insert_after + 1, note)
        else:
            measure = self.score.notes[-1].measure_index if self.score.notes else 0
            note = NoteEvent(
                id=-1,  # renumbered below
                degree=1,
                duration_beat=1.0,
                measure_index=measure,
                confidence=1.0,
            )
            self.score.notes.append(note)
        # refresh() sorts by (measure, id); renumber ids along the current
        # list order so the new note actually lands next to its anchor.
        for idx, existing in enumerate(self.score.notes):
            existing.id = idx
        self.score.refresh()
        new_index = next(
            (i for i, existing in enumerate(self.score.notes) if existing is note),
            len(self.score.notes) - 1,
        )
        self._rebuild_table()
        self.table.selectRow(new_index)
        self.table.scrollToItem(self.table.item(new_index, 0))
        self.image_view.set_notes(self.score.notes)

    def _delete_selected(self) -> None:
        rows = sorted((r.row() for r in self.table.selectionModel().selectedRows()), reverse=True)
        if not rows:
            return
        self._push_undo(self.score.copy())
        for row in rows:
            if 0 <= row < len(self.score.notes):
                del self.score.notes[row]
        self.score.refresh()
        self._rebuild_table()
        self.image_view.set_notes(self.score.notes)

    def _recalculate(self) -> None:
        t0 = time.perf_counter()
        logging.info("editor.recalculate start notes=%d", len(self.score.notes))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._apply_metadata()
            self.score.refresh()
            logging.info("editor.recalculate refresh done %.0fms", (time.perf_counter() - t0) * 1000)
            self._rebuild_table()
            logging.info("editor.recalculate table done %.0fms", (time.perf_counter() - t0) * 1000)
            self.image_view.set_notes(self.score.notes)
            self._refresh_preview()
            logging.info("editor.recalculate done %.0fms", (time.perf_counter() - t0) * 1000)
        finally:
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------ undo
    def _update_undo_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._undo_stack))
        self.redo_button.setEnabled(bool(self._redo_stack))

    def _push_undo(self, snapshot: Score) -> None:
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _restore(self, score: Score) -> None:
        self.score = score
        self._load_metadata()
        self._rebuild_table()
        self._refresh_preview()
        self._update_undo_buttons()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self.score.copy())
        self._restore(self._undo_stack.pop())

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self.score.copy())
        self._restore(self._redo_stack.pop())

    def _apply_metadata(self) -> None:
        self.score.title = self.title_edit.text().strip() or "未命名乐谱"
        try:
            _, key_name = parse_key_name(self.key_combo.currentText())
            self.score.key_name = key_name
        except Exception:
            self.score.key_name = "C"
        self.score.base_octave = int(self.octave_spin.value())
        self.score.meter_num = int(self.meter_num.value())
        self.score.meter_den = int(self.meter_den.currentText())
        self.score.tempo_hint = float(self.bpm_spin.value())
        self.score.mode = "minor" if self.mode_combo.currentIndex() == 1 else "major"

    def _apply(self) -> None:
        t0 = time.perf_counter()
        logging.info("editor.apply start notes=%d", len(self.score.notes))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._apply_metadata()
            if self.confirm_recognition.isChecked():
                self.score.source_warnings.clear()
            self.score.refresh()
            self.result_score = self.score.copy()
            logging.info("editor.apply done %.0fms", (time.perf_counter() - t0) * 1000)
            self.accept()
        finally:
            QApplication.restoreOverrideCursor()
