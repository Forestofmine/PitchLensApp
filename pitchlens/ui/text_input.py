"""Manual jianpu text entry dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.jianpu_text import parse_jianpu_text
from ..core.score import Score
from .theme import COLORS


class JianpuTextDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("手动录入简谱 · PitchLens")
        self.resize(720, 620)
        self.result_score: Score | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        title = QLabel("手动录入简谱")
        title.setStyleSheet(f"font-size:20px;font-weight:800;color:{COLORS['text']};")
        layout.addWidget(title)
        help_text = QLabel(
            "第一行写调号/拍号/速度，例如 <b>1=C 4/4 90</b>，下一行用 <b>|</b> 分小节。<br>"
            "<b>1'</b> 高八度 · <b>1,</b> 低八度 · <b>1_</b> 八分音符 · <b>1__</b> 十六分 · "
            "<b>1.</b> 附点 · <b>-</b> 在本小节延长一拍 · <b>0</b> 休止 · <b>#4/b7</b> 升降音"
        )
        help_text.setObjectName("Muted")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |")
        self.editor.setPlainText(initial or "1=C 4/4 90\n| 1 2 3 5 | 6 5 3 - | 2 3 5 3 | 1 - - - |")
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ background:{COLORS['panel']}; border:1px solid {COLORS['border']}; border-radius:10px;"
            f" padding:10px; font-family:Consolas,'Microsoft YaHei UI'; font-size:15px; color:{COLORS['text']}; }}"
        )
        layout.addWidget(self.editor, 1)
        self.preview = QLabel("")
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("Ghost")
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("生成乐谱")
        ok.setObjectName("Accent")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.editor.textChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self) -> None:
        try:
            parsed = parse_jianpu_text(self.editor.toPlainText(), title="手动录入乐谱")
            score = parsed.score
            self.preview.setText(
                f"预览：1={score.key_name} · {score.meter_num}/{score.meter_den} · "
                f"{score.tempo_hint:g} BPM · {len(score.notes)} 个音符 · {score.total_beats:g} 拍"
                + (f"  ⚠ {score.warnings[0]}" if score.warnings else "")
            )
        except Exception as exc:
            self.preview.setText(f"预览失败：{exc}")

    def _accept(self) -> None:
        try:
            parsed = parse_jianpu_text(self.editor.toPlainText(), title="手动录入乐谱")
        except Exception as exc:
            QMessageBox.warning(self, "解析失败", str(exc))
            return
        self.result_score = parsed.score
        self.accept()
