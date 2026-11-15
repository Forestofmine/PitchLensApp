"""PitchLens main window."""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import cv2
from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core.audio import AudioDeviceInfo, AudioEngine
from ..core.follower import FollowState, ScoreFollower
from ..core.pitch import PitchFrame
from ..core.project import Project, ProjectIO
from ..core.recognition import JianpuRecognizer, RecognitionResult
from ..core.score import Score
from ..core.settings import AppSettings, load_settings_dict, save_settings_dict
from ..demo import render_demo_score
from .editor import ScoreEditorDialog
from .pitch_timeline import PitchTimeline
from .score_view import ScorePanel
from .settings_dialog import SettingsDialog
from .text_input import JianpuTextDialog
from .theme import COLORS, apply_theme, theme_name


class RecognitionThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, data: bytes, title: str, base_octave: int, parent=None) -> None:
        super().__init__(parent)
        self.data = data
        self.title = title
        self.base_octave = int(base_octave)

    def run(self) -> None:
        t0 = time.perf_counter()
        logging.info("recognition start bytes=%d", len(self.data))
        try:
            result = JianpuRecognizer().recognize_bytes(
                self.data, title=self.title, base_octave=self.base_octave
            )
            logging.info(
                "recognition done %.0fms notes=%d",
                (time.perf_counter() - t0) * 1000,
                len(result.score.notes),
            )
            self.completed.emit(result)
        except Exception as exc:  # pragma: no cover - UI path
            import traceback

            traceback.print_exc()
            logging.exception("recognition failed after %.0fms", (time.perf_counter() - t0) * 1000)
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self, *, demo: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("PitchLens 音准镜")
        self.resize(1480, 900)
        self.setMinimumSize(1360, 720)
        self.setAcceptDrops(True)
        self.settings = self._load_settings()
        self.project: Project | None = None
        self.audio: AudioEngine | None = None
        self.follower = ScoreFollower()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._running = False
        self._now = 0.0
        self._last_state = FollowState()
        self._last_frame: PitchFrame | None = None
        self._recognition_thread: RecognitionThread | None = None
        self._frame_count = 0
        self._fps = 0.0
        self._fps_t0 = time.perf_counter()
        self._fps_frames = 0
        self._resume_index: int | None = None
        self._quiet_start = bool(demo)
        self._practice_mode = False
        self._build_ui()
        self._refresh_devices()
        self._update_actions()
        self._set_idle_state()
        if demo:
            QTimer.singleShot(250, self._load_demo)

    # ------------------------------------------------------------------ ui
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(18, 12, 18, 12)
        top_layout.setSpacing(10)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(10)
        logo = QLabel("◉")
        self.logo = logo
        self._apply_brand_style()
        brand_layout.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("PitchLens")
        name.setObjectName("AppTitle")
        brand_text.addWidget(name)
        sub = QLabel("音准镜 · 实时演唱音高与简谱对比")
        sub.setObjectName("AppSub")
        brand_text.addWidget(sub)
        brand_layout.addLayout(brand_text)
        top_layout.addWidget(brand)
        top_layout.addSpacing(12)

        self.import_btn = QPushButton("导入简谱")
        self.import_btn.setObjectName("Accent")
        self.import_btn.setToolTip("导入 JPG/PNG 简谱图片并自动识别")
        self.import_btn.clicked.connect(self._import_image)
        top_layout.addWidget(self.import_btn)

        self.text_btn = QPushButton("手动录入")
        self.text_btn.setObjectName("Ghost")
        self.text_btn.clicked.connect(self._manual_input)
        top_layout.addWidget(self.text_btn)

        self.edit_btn = QPushButton("识谱校正")
        self.edit_btn.setObjectName("Ghost")
        self.edit_btn.clicked.connect(self._open_editor)
        top_layout.addWidget(self.edit_btn)

        self.open_btn = QPushButton("打开")
        self.open_btn.setObjectName("Ghost")
        self.open_btn.clicked.connect(self._open_project)
        top_layout.addWidget(self.open_btn)

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("Ghost")
        self.save_btn.clicked.connect(self._save_project)
        top_layout.addWidget(self.save_btn)

        self.demo_btn = QPushButton("示例")
        self.demo_btn.setObjectName("Ghost")
        self.demo_btn.clicked.connect(self._load_demo)
        top_layout.addWidget(self.demo_btn)

        top_layout.addStretch(1)

        device_label = QLabel("麦克风")
        device_label.setObjectName("TinyMuted")
        top_layout.addWidget(device_label)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(210)
        self.device_combo.setMaximumWidth(300)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        top_layout.addWidget(self.device_combo)
        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("Icon")
        refresh_btn.setToolTip("刷新麦克风列表")
        refresh_btn.clicked.connect(self._refresh_devices)
        top_layout.addWidget(refresh_btn)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("Ghost")
        self.settings_btn.clicked.connect(self._open_settings)
        top_layout.addWidget(self.settings_btn)

        self.start_btn = QPushButton("开始演唱")
        self.start_btn.setObjectName("Transport")
        self.start_btn.setMinimumWidth(120)
        self.start_btn.clicked.connect(self._toggle_transport)
        top_layout.addWidget(self.start_btn)

        self.reset_btn = QPushButton("回到开头")
        self.reset_btn.setObjectName("Ghost")
        self.reset_btn.clicked.connect(self._reset_position)
        top_layout.addWidget(self.reset_btn)

        self.practice_btn = QPushButton("练唱模式")
        self.practice_btn.setObjectName("Ghost")
        self.practice_btn.setToolTip("收起乐谱面板，只识别和显示实时音高；再点一次返回乐谱")
        self.practice_btn.clicked.connect(self._toggle_practice)
        top_layout.addWidget(self.practice_btn)

        layout.addWidget(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.timeline = PitchTimeline(self.settings)
        splitter.addWidget(self.timeline)

        right = QFrame()
        self.right_panel = right
        right.setObjectName("Card")
        right.setMinimumWidth(380)
        right.setMaximumWidth(580)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(14, 14, 14, 14)
        right_layout.setSpacing(8)
        self.score_panel = ScorePanel()
        self.score_panel.noteClicked.connect(self._on_note_clicked)
        right_layout.addWidget(self.score_panel, 1)
        actions = QHBoxLayout()
        self.correct_btn = QPushButton("校正 / 编辑")
        self.correct_btn.setObjectName("Ghost")
        self.correct_btn.clicked.connect(self._open_editor)
        actions.addWidget(self.correct_btn)
        self.boxes_btn = QPushButton("显示识别框")
        self.boxes_btn.setObjectName("Ghost")
        self.boxes_btn.setCheckable(True)
        self.boxes_btn.setChecked(True)
        self.boxes_btn.toggled.connect(self._toggle_boxes)
        actions.addWidget(self.boxes_btn)
        right_layout.addLayout(actions)
        splitter.addWidget(right)
        splitter.setSizes([1000, 450])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        layout.addWidget(splitter, 1)

        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = QLabel("就绪 · 导入简谱，或直接开始演唱")
        self.status_label.setObjectName("Muted")
        status.addWidget(self.status_label, 1)
        self.level_label = QLabel("电平 -- dB")
        self.level_label.setObjectName("TinyMuted")
        self.level_label.setToolTip("麦克风输入电平；演唱时持续低于 -45 dB 说明增益太低，音高容易断")
        status.addPermanentWidget(self.level_label)
        self.engine_label = QLabel("YIN · 48 kHz")
        self.engine_label.setObjectName("TinyMuted")
        status.addPermanentWidget(self.engine_label)
        self.fps_label = QLabel("-- fps")
        self.fps_label.setObjectName("TinyMuted")
        status.addPermanentWidget(self.fps_label)

        # Keyboard shortcuts.
        self._shortcuts = []
        for sequence, callback in [
            (QKeySequence(Qt.Key.Key_Space), self._toggle_transport),
            (QKeySequence("Ctrl+O"), self._open_project),
            (QKeySequence("Ctrl+S"), self._save_project),
            (QKeySequence("Ctrl+I"), self._import_image),
            (QKeySequence("Ctrl+E"), self._open_editor),
        ]:
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    # -------------------------------------------------------------- settings
    def _apply_brand_style(self) -> None:
        accent = QColor(COLORS["accent"])
        r, g, b = accent.red(), accent.green(), accent.blue()
        self.logo.setStyleSheet(
            f"font-size:26px;color:{COLORS['accent']};font-weight:800;"
            f"background:rgba({r},{g},{b},15);"
            f"border:1px solid rgba({r},{g},{b},60);"
            "border-radius:12px;padding:1px 7px;"
        )

    def _apply_live_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme_name(self.settings.dark))
        self._apply_brand_style()
        self.timeline.retheme()
        self.score_panel.retheme()

    def _load_settings(self) -> AppSettings:
        try:
            return AppSettings.from_dict(load_settings_dict()).clamped()
        except Exception:
            return AppSettings().clamped()

    def _save_settings(self) -> None:
        save_settings_dict(self.settings.to_dict())

    def _refresh_devices(self) -> None:
        current = self.device_combo.currentData() if hasattr(self, "device_combo") else None
        devices = AudioEngine.list_devices()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("系统默认输入", None)
        for device in devices:
            self.device_combo.addItem(device.label, device.index)
        target = current if current is not None else self.settings.device_index
        if target is not None:
            index = self.device_combo.findData(target)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)
        if not devices:
            self._set_status("未发现输入设备；请检查麦克风连接后点击 ↻")

    def _on_device_changed(self) -> None:
        self.settings.device_index = self.device_combo.currentData()
        self._save_settings()

    # ------------------------------------------------------------- project
    def _apply_project(self, project: Project, *, reset: bool = True) -> None:
        t0 = time.perf_counter()
        if self._practice_mode:
            # Loading a score always leaves practice mode first.
            self._exit_practice()
        logging.info(
            "apply_project start notes=%d image=%s",
            len(project.score.notes),
            f"{len(project.image_bytes) / 1e6:.1f}MB" if project.image_bytes else "none",
        )
        self.project = project
        score = project.score
        self.follower.set_score(score, bpm_hint=score.tempo_hint)
        if reset:
            self.follower.reset(0)
            self._resume_index = 0
        self.score_panel.set_project(score, project.image_bytes)
        self.score_panel.view.auto_follow = self.settings.auto_follow_scroll
        if score.notes:
            self.score_panel.set_current_note(score.notes[0].id)
        self.timeline.clear()
        self._last_state = self.follower.state
        self.timeline.update_view(0.0, self._last_state, follower=self.follower)
        self._update_actions()
        self.setWindowTitle(f"{score.title} · PitchLens 音准镜")
        if score.notes:
            self._set_status(
                f"已载入《{score.title}》 · {len(score.notes)} 个音符 · "
                f"1={score.key_name} · {score.meter_num}/{score.meter_den} · {score.tempo_hint:g} BPM"
            )
        else:
            self._set_status("乐谱为空；请打开校正或手动录入")
        logging.info("apply_project done %.0fms", (time.perf_counter() - t0) * 1000)

    def _update_actions(self) -> None:
        has_project = self.project is not None
        has_score = bool(self.project and self.project.score.notes)
        practice = self._practice_mode
        self.edit_btn.setEnabled(has_project and not practice)
        self.correct_btn.setEnabled(has_project and not practice)
        self.save_btn.setEnabled(has_project)
        self.boxes_btn.setEnabled(
            has_project and self.project.has_image and not practice
        )
        self.reset_btn.setEnabled(has_project or practice)
        self.engine_label.setText(
            f"{'YIN' if self.settings.detector == 'yin' else 'CREPE'} · {self.settings.sample_rate // 1000} kHz"
        )

    def _set_idle_state(self) -> None:
        self._last_state = FollowState(status="waiting", reason="等待起音")
        self.timeline.update_view(0.0, self._last_state, follower=self.follower)
        self.fps_label.setText("-- fps")

    # ------------------------------------------------------------ practice
    def _toggle_practice(self) -> None:
        if self._practice_mode:
            self._exit_practice()
        else:
            self._enter_practice()

    def _enter_practice(self) -> None:
        """Practice mode: hide the score panel, follow an empty score so only
        the live pitch is detected and drawn.  The loaded project is kept in
        memory untouched and restored on exit."""
        if self._practice_mode:
            return
        self._practice_mode = True
        self.follower.set_score(Score(), bpm_hint=self.settings.default_bpm)
        self.follower.reset(0)
        self.right_panel.setVisible(False)
        self.practice_btn.setText("返回乐谱")
        self.practice_btn.setObjectName("Accent")
        self.practice_btn.style().unpolish(self.practice_btn)
        self.practice_btn.style().polish(self.practice_btn)
        self.setWindowTitle("练唱模式 · PitchLens 音准镜")
        self._last_state = self.follower.state
        if not self._running:
            self.timeline.update_view(self._now, self._last_state, follower=self.follower)
        self._update_actions()
        self._set_status("练唱模式 · 只显示实时音高与理想音高参考带，不跟谱")
        logging.info("practice mode entered")

    def _exit_practice(self) -> None:
        if not self._practice_mode:
            return
        self._practice_mode = False
        self.right_panel.setVisible(True)
        self.practice_btn.setText("练唱模式")
        self.practice_btn.setObjectName("Ghost")
        self.practice_btn.style().unpolish(self.practice_btn)
        self.practice_btn.style().polish(self.practice_btn)
        if self.project is not None:
            score = self.project.score
            self.follower.set_score(score, bpm_hint=score.tempo_hint)
            self.follower.reset(0)
            self._resume_index = 0
            self.score_panel.set_project(score, self.project.image_bytes)
            self.score_panel.view.auto_follow = self.settings.auto_follow_scroll
            if score.notes:
                self.score_panel.set_current_note(score.notes[0].id)
            self.setWindowTitle(f"{score.title} · PitchLens 音准镜")
            self._set_status(f"已返回乐谱《{score.title}》 · 跟谱位置已回到开头")
        else:
            self.setWindowTitle("PitchLens 音准镜")
            self._set_status("就绪 · 导入简谱，或直接开始演唱")
        self._last_state = self.follower.state
        if not self._running:
            self.timeline.update_view(self._now, self._last_state, follower=self.follower)
        self._update_actions()
        logging.info("practice mode exited")

    # --------------------------------------------------------------- import
    def _import_image(self) -> None:
        start_dir = self.settings.last_image_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入简谱图片",
            start_dir,
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if not path:
            return
        self.settings.last_image_dir = str(Path(path).parent)
        self._save_settings()
        self._start_recognition_file(path)

    def _start_recognition_file(self, path: str, title: str | None = None) -> None:
        try:
            data = Path(path).read_bytes()
        except Exception as exc:
            QMessageBox.warning(self, "无法读取图片", str(exc))
            return
        self._start_recognition(data, title=title or Path(path).stem)

    def _start_recognition(self, data: bytes, title: str) -> None:
        if self._recognition_thread is not None and self._recognition_thread.isRunning():
            return
        self.import_btn.setEnabled(False)
        # Recognition finishing pops a modal message box; if the user had the
        # editor open at that moment the two modal grabs fight and the UI
        # looks frozen.  Keep the editor out of reach while recognition runs.
        self.edit_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.settings_btn.setEnabled(False)
        self._set_status(f"正在识别《{title}》… 音频与界面保持可用")
        thread = RecognitionThread(data, title, self.settings.base_octave, self)
        thread.completed.connect(self._on_recognition_done)
        thread.failed.connect(self._on_recognition_failed)
        thread.finished.connect(self._on_recognition_finished)
        self._recognition_thread = thread
        thread.start()

    def _on_recognition_done(self, result: RecognitionResult) -> None:
        score = result.score
        score.image_name = score.title
        score.transpose = self.settings.transpose
        score.refresh()
        ok, encoded = cv2.imencode(".png", result.image_bgr)
        image_bytes = encoded.tobytes() if ok else None
        project = Project(
            score=score,
            image_bytes=image_bytes,
            image_ext=".png",
            source_name=score.title,
            settings={"recognition": result.debug},
        )
        self._apply_project(project, reset=True)
        summary = (
            f"识别完成：{len(score.notes)} 个音符 / {score.measure_count} 小节\n"
            f"调号 1={score.key_name} · {score.meter_num}/{score.meter_den} · "
            f"{score.tempo_hint:g} BPM"
        )
        if score.warnings:
            summary += "\n\n" + "\n".join(score.warnings[:5])
            if len(score.warnings) > 5:
                summary += f"\n… 另有 {len(score.warnings) - 5} 项"
            summary += "\n\n建议打开“识谱校正”确认低置信度音符。"
        if self._quiet_start:
            self._quiet_start = False
            self._set_status(
                f"示例已载入 · {len(score.notes)} 个音符 · "
                f"{'有提示，可打开校正' if score.warnings else '时值校验通过'}"
            )
            return
        if score.warnings:
            QMessageBox.information(self, "识别完成（需校正）", summary)
        elif not score.notes:
            QMessageBox.warning(
                self,
                "未识别到音符",
                "图片可能不是清晰的单声部印刷简谱。\n"
                "请使用“识谱校正”手动添加，或用“手动录入”粘贴简谱文本。",
            )
        else:
            self._set_status(f"识别完成 · {len(score.notes)} 个音符 · 时值校验通过")
            QMessageBox.information(self, "识别完成", summary + "\n\n可直接点击“开始演唱”。")

    def _on_recognition_failed(self, message: str) -> None:
        self._quiet_start = False
        self._set_status("识谱失败")
        QMessageBox.critical(
            self,
            "识谱失败",
            message + "\n\n请尝试更清晰的图片，或使用“手动录入”。",
        )

    def _on_recognition_finished(self) -> None:
        self.import_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self._update_actions()
        self._recognition_thread = None

    # ---------------------------------------------------------------- demo
    def _load_demo(self) -> None:
        demo_path = Path(__file__).resolve().parents[2] / "examples" / "demo_jianpu.png"
        if not demo_path.exists():
            try:
                render_demo_score(demo_path)
            except Exception as exc:
                QMessageBox.warning(self, "示例不可用", f"无法生成示例图片：{exc}")
                return
        self._start_recognition_file(str(demo_path), title="小星星")

    # --------------------------------------------------------------- files
    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 PitchLens 项目",
            self.settings.last_image_dir or str(Path.home()),
            "PitchLens 项目 (*.pitchproj);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            project = ProjectIO.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
            return
        self.settings.last_project = path
        self.settings.last_image_dir = str(Path(path).parent)
        self._save_settings()
        self._apply_project(project, reset=True)
        self._set_status(f"已打开 {Path(path).name}")

    def _save_project(self) -> None:
        if self.project is None:
            QMessageBox.information(self, "没有可保存的乐谱", "请先导入或手动录入简谱。")
            return
        default_name = f"{self.project.score.title or '未命名'}.pitchproj"
        start_dir = self.settings.last_project or str(Path.home() / default_name)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 PitchLens 项目",
            start_dir,
            "PitchLens 项目 (*.pitchproj)",
        )
        if not path:
            return
        if not path.lower().endswith(".pitchproj"):
            path += ".pitchproj"
        try:
            ProjectIO.save(self.project, path)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.settings.last_project = path
        self._save_settings()
        self._set_status(f"已保存 {Path(path).name}")

    def _manual_input(self) -> None:
        dialog = JianpuTextDialog(self)
        if dialog.exec() != JianpuTextDialog.DialogCode.Accepted or dialog.result_score is None:
            return
        score = dialog.result_score
        score.base_octave = self.settings.base_octave
        score.transpose = self.settings.transpose
        score.refresh()
        image_bytes = self.project.image_bytes if self.project else None
        project = Project(score=score, image_bytes=image_bytes, source_name=score.title)
        self._apply_project(project, reset=True)
        self._set_status(f"已生成《{score.title}》 · {len(score.notes)} 个音符")

    # --------------------------------------------------------------- editor
    def _open_editor(self) -> None:
        if self.project is None:
            return
        logging.info("editor open notes=%d", len(self.project.score.notes))
        t0 = time.perf_counter()
        dialog = ScoreEditorDialog(self.project.score, self.project.image_bytes, self)
        logging.info("editor dialog built %.0fms", (time.perf_counter() - t0) * 1000)
        if dialog.exec() != ScoreEditorDialog.DialogCode.Accepted:
            logging.info("editor cancelled")
            return
        if dialog.result_score is None:
            return
        logging.info("editor accepted, applying result")
        self.project.score = dialog.result_score
        self._apply_project(self.project, reset=True)
        self._set_status("校正已应用，跟谱位置已重置")

    def _toggle_boxes(self, checked: bool) -> None:
        if self.project is not None:
            self.score_panel.view.set_boxes_visible(checked)

    def _on_note_clicked(self, note_id: int) -> None:
        if self.project is None:
            return
        index = self.project.score.index_of(note_id)
        if index < 0:
            return
        now = self.audio.display_time() if self.audio else self._now
        state = self.follower.seek(index, now)
        self._last_state = state
        self._resume_index = index
        self.score_panel.set_current_note(self.project.score.notes[index].id)
        self.timeline.update_view(now, state, follower=self.follower)
        self._set_status(f"已定位到第 {index + 1} 个音符")

    # --------------------------------------------------------------- audio
    def _toggle_transport(self) -> None:
        if self._running:
            self._stop_audio()
        else:
            self._start_audio()

    def _start_audio(self) -> None:
        if self._running:
            return
        self._save_settings()
        try:
            audio = AudioEngine(
                detector_name=self.settings.detector,
                sample_rate=self.settings.sample_rate,
                fmin=self.settings.fmin,
                fmax=self.settings.fmax,
                crepe_model=self.settings.crepe_model or None,
                latency_offset_ms=self.settings.latency_offset_ms,
                a4=self.settings.a4,
            )
        except Exception as exc:
            self.audio = None
            QMessageBox.critical(self, "音频初始化失败", f"{type(exc).__name__}: {exc}")
            return
        ok, message = audio.start(self.settings.device_index)
        if not ok:
            self.audio = None
            self.timeline.set_paused(False)
            QMessageBox.critical(
                self,
                "麦克风启动失败",
                message
                + "\n\n请检查：\n• 麦克风是否被其他程序占用\n"
                "• Windows 隐私设置是否允许桌面应用使用麦克风\n"
                "• 是否选择了正确的输入设备",
            )
            return
        self.audio = audio
        self._running = True
        if self.project is not None and not self._practice_mode:
            score = self.project.score
            self.follower.set_score(score, bpm_hint=score.tempo_hint)
            start_index = self._resume_index if self._resume_index is not None else 0
            self.follower.reset(start_index)
        else:
            self.follower.set_score(Score(), bpm_hint=self.settings.default_bpm)
            self._resume_index = None
        self.timeline.clear()
        self.timeline.set_paused(False)
        self._now = 0.0
        self._last_state = self.follower.state
        self.start_btn.setText("暂停")
        self.start_btn.setObjectName("TransportStop")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self._set_status(f"正在监听 · {message}")
        self._timer.start()

    def _stop_audio(self) -> None:
        if self.audio is not None:
            self.audio.stop()
            self.audio = None
        self._running = False
        self._timer.stop()
        self.start_btn.setText("开始演唱")
        self.start_btn.setObjectName("Transport")
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)
        self.timeline.set_paused(True)
        self.level_label.setText("电平 -- dB")
        self._set_status("已暂停 · 可左右拖动回看历史，点击“回到当前”复位")

    def _reset_position(self) -> None:
        was_running = self._running
        if was_running:
            self._stop_audio()
        self.follower.reset(0)
        self._resume_index = 0
        self.timeline.clear()
        self.timeline.set_paused(False)
        self._now = 0.0
        self._last_state = self.follower.state
        self.timeline.update_view(0.0, self._last_state, follower=self.follower)
        if self.project is not None and not self._practice_mode:
            self.score_panel.set_current_note(
                self.project.score.notes[0].id if self.project.score.notes else None
            )
        self._set_status("已回到开头")

    # ----------------------------------------------------------------- tick
    def _tick(self) -> None:
        if not self._running or self.audio is None:
            return
        frames = self.audio.poll_frames(64)
        # Count UI ticks, not pitch frames: the status bar label reads "fps"
        # and should reflect the actual screen refresh rate.
        self._fps_frames += 1
        if frames:
            self._frame_count += len(frames)
            self.timeline.append_frames(frames)
            for frame in frames:
                state = self.follower.update(frame, frame.audio_time)
                self._last_state = state
                self._last_frame = frame
            self._now = self.audio.display_time()
        else:
            self._now = self.audio.display_time()

        state = self._last_state
        self.timeline.update_view(
            self._now,
            state,
            follower=self.follower,
            detector_label=self.audio.detector_label if self.audio else "",
            latency_ms=self.audio.analysis_ms if self.audio else 0.0,
        )
        if self.project is not None and not self._practice_mode:
            current_id = None
            if state.target is not None and state.note_index >= 0:
                current_id = state.target.id
                self._resume_index = state.note_index
            self.score_panel.set_current_note(current_id)
            if state.target is not None:
                self.score_panel.set_target_info(
                    note_name=self.project.score.note_name(state.target),
                    degree=state.target.display_degree(),
                    status=state.status,
                    tempo=state.tempo_bpm,
                    confidence=state.confidence,
                )
        now_perf = time.perf_counter()
        elapsed = now_perf - self._fps_t0
        if elapsed >= 0.8:
            self._fps = self._fps_frames / elapsed
            self._fps_frames = 0
            self._fps_t0 = now_perf
            self.fps_label.setText(f"{self._fps:.0f} fps")
        if self.audio is not None:
            self.engine_label.setText(
                f"{self.audio.detector_label} · {self.audio.sample_rate // 1000} kHz · "
                f"{self.audio.analysis_ms:.1f} ms"
            )
        if self._last_frame is not None:
            db = 20.0 * math.log10(max(self._last_frame.rms, 1e-6))
            self.level_label.setText(f"电平 {db:.0f} dB")

    # -------------------------------------------------------------- settings
    def _open_settings(self) -> None:
        was_running = self._running
        if was_running:
            self._stop_audio()
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            if was_running:
                self._start_audio()
            return
        if dialog.result_settings is not None:
            previous_theme = self.settings.dark
            self.settings = dialog.result_settings
            self.timeline.settings = self.settings
            self.score_panel.view.auto_follow = self.settings.auto_follow_scroll
            self.timeline.plot.setXRange(
                -self.settings.history_seconds, self.settings.future_seconds, padding=0
            )
            if self.settings.dark != previous_theme:
                self._apply_live_theme()
            self._save_settings()
            self._update_actions()
            self._set_status("设置已保存")
        if was_running:
            self._start_audio()

    # ------------------------------------------------------------ shortcuts
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                suffix = Path(url.toLocalFile()).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".pitchproj"}:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() == ".pitchproj":
                try:
                    self._apply_project(ProjectIO.load(path), reset=True)
                    self._set_status(f"已打开 {path.name}")
                except Exception as exc:
                    QMessageBox.critical(self, "打开失败", str(exc))
                return
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                self._start_recognition_file(str(path))
                return

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_audio()
        if self._recognition_thread is not None and self._recognition_thread.isRunning():
            self._recognition_thread.quit()
            self._recognition_thread.wait(800)
        self._save_settings()
        event.accept()

    # --------------------------------------------------------------- helpers
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
