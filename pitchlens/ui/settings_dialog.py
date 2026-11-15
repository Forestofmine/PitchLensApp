"""Settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.audio import MicTester, list_input_devices
from ..core.pitch import detector_available
from ..core.settings import AppSettings
from .theme import COLORS


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置 · PitchLens")
        self.resize(760, 620)
        self.settings = AppSettings.from_dict(settings.to_dict())
        self.result_settings: AppSettings | None = None
        self._devices = []
        self._mic_tester = MicTester()
        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(60)
        self._mic_timer.timeout.connect(self._update_mic_level)
        self._mic_busy = False  # recording or playing back
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        title = QLabel("设置")
        title.setStyleSheet(f"font-size:20px;font-weight:800;color:{COLORS['text']};")
        root.addWidget(title)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        # ---------------------------------------------------------- audio
        audio_tab = QWidget()
        audio_layout = QVBoxLayout(audio_tab)
        audio_layout.setContentsMargins(14, 14, 14, 14)
        audio_layout.setSpacing(10)
        audio_group = QGroupBox("音频输入")
        form = QFormLayout(audio_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.device_combo = QComboBox()
        refresh = QPushButton("刷新")
        refresh.setObjectName("Ghost")
        refresh.clicked.connect(self._refresh_devices)
        device_row = QHBoxLayout()
        device_row.addWidget(self.device_combo, 1)
        device_row.addWidget(refresh)
        form.addRow("麦克风", self._wrap(device_row))
        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItems(["48000", "44100"])
        form.addRow("采样率", self.sample_rate_combo)
        self.detector_combo = QComboBox()
        self.detector_combo.addItems(["YIN（低延迟，内置）", "CREPE（需模型/运行时）"])
        form.addRow("音高检测器", self.detector_combo)
        self.crepe_path_edit = QLineEdit()
        self.crepe_path_edit.setPlaceholderText("可选：CREPE ONNX 模型路径；留空自动查找")
        form.addRow("CREPE 模型", self.crepe_path_edit)
        self.latency_spin = QDoubleSpinBox()
        self.latency_spin.setRange(-200, 400)
        self.latency_spin.setSuffix(" ms")
        self.latency_spin.setDecimals(0)
        self.latency_spin.setToolTip("音频到画面的延迟补偿；正值表示把画面推迟")
        form.addRow("延迟补偿", self.latency_spin)
        audio_layout.addWidget(audio_group)

        # -------------------------------------------------- mic self-test
        test_group = QGroupBox("麦克风测试")
        test_layout = QVBoxLayout(test_group)
        test_hint = QLabel(
            "先「开始监听」看实时电平是否随声音起伏；再「录 5 秒并回放」"
            "听当前设备和采样率的真实收音效果。建议戴耳机测试，避免外放啸叫。"
        )
        test_hint.setObjectName("Muted")
        test_hint.setWordWrap(True)
        test_layout.addWidget(test_hint)
        test_row = QHBoxLayout()
        self.mic_monitor_btn = QPushButton("开始监听")
        self.mic_monitor_btn.setObjectName("Ghost")
        self.mic_monitor_btn.clicked.connect(self._toggle_mic_monitor)
        test_row.addWidget(self.mic_monitor_btn)
        self.mic_record_btn = QPushButton("录 5 秒并回放")
        self.mic_record_btn.setObjectName("Ghost")
        self.mic_record_btn.setEnabled(False)
        self.mic_record_btn.clicked.connect(self._mic_record)
        test_row.addWidget(self.mic_record_btn)
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 60)
        self.mic_level.setValue(0)
        self.mic_level.setTextVisible(False)
        self.mic_level.setFixedHeight(10)
        test_row.addWidget(self.mic_level, 1)
        self.mic_level_label = QLabel("-- dB")
        self.mic_level_label.setObjectName("TinyMuted")
        self.mic_level_label.setMinimumWidth(52)
        test_row.addWidget(self.mic_level_label)
        test_layout.addLayout(test_row)
        self.mic_status = QLabel("")
        self.mic_status.setObjectName("TinyMuted")
        test_layout.addWidget(self.mic_status)
        audio_layout.addWidget(test_group)

        # Switching device / sample rate while monitoring restarts the test
        # stream so the user always hears the current selection.
        self.device_combo.currentIndexChanged.connect(self._mic_maybe_restart)
        self.sample_rate_combo.currentTextChanged.connect(self._mic_maybe_restart)

        note = QLabel(
            "提示：使用耳机可避免伴奏被麦克风拾取。建议在 Windows 声音设置中关闭"
            "麦克风增强/回声消除；本程序不会修改系统音效。CREPE 不可用时自动回退 YIN。"
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        audio_layout.addWidget(note)
        audio_layout.addStretch(1)
        tabs.addTab(audio_tab, "音频")

        # -------------------------------------------------------- display
        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)
        display_layout.setContentsMargins(14, 14, 14, 14)
        display_layout.setSpacing(10)
        display_group = QGroupBox("曲线显示")
        form2 = QFormLayout(display_group)
        self.a4_spin = QDoubleSpinBox()
        self.a4_spin.setRange(400, 480)
        self.a4_spin.setDecimals(1)
        self.a4_spin.setSuffix(" Hz")
        form2.addRow("标准音 A4", self.a4_spin)
        self.history_spin = QDoubleSpinBox()
        self.history_spin.setRange(4, 30)
        self.history_spin.setSuffix(" 秒")
        form2.addRow("左侧历史", self.history_spin)
        self.future_spin = QDoubleSpinBox()
        self.future_spin.setRange(2, 30)
        self.future_spin.setSuffix(" 秒")
        form2.addRow("右侧未来", self.future_spin)
        self.span_spin = QSpinBox()
        self.span_spin.setRange(12, 36)
        self.span_spin.setSuffix(" 半音")
        form2.addRow("纵轴范围", self.span_spin)
        self.good_spin = QDoubleSpinBox()
        self.good_spin.setRange(5, 45)
        self.good_spin.setSuffix(" ¢")
        form2.addRow("绿色容差", self.good_spin)
        self.ok_spin = QDoubleSpinBox()
        self.ok_spin.setRange(10, 80)
        self.ok_spin.setSuffix(" ¢")
        form2.addRow("黄色容差", self.ok_spin)
        self.target_check = QCheckBox("显示目标音高线与容差带")
        self.raw_check = QCheckBox("叠加原始（未平滑）曲线")
        self.follow_scroll_check = QCheckBox("识谱预览自动滚动到当前音符")
        form2.addRow("", self.target_check)
        form2.addRow("", self.raw_check)
        form2.addRow("", self.follow_scroll_check)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("明亮 · 纸感", "paper")
        self.theme_combo.addItem("暗色 · 夜景", "dark")
        form2.addRow("界面主题", self.theme_combo)
        display_layout.addWidget(display_group)
        display_layout.addStretch(1)
        tabs.addTab(display_tab, "显示")

        # ---------------------------------------------------------- score
        score_tab = QWidget()
        score_layout = QVBoxLayout(score_tab)
        score_layout.setContentsMargins(14, 14, 14, 14)
        score_layout.setSpacing(10)
        score_group = QGroupBox("乐谱默认值")
        form3 = QFormLayout(score_group)
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(1, 8)
        self.octave_spin.setSuffix(" 八度")
        form3.addRow("中音 1 基准八度", self.octave_spin)
        self.bpm_spin = QDoubleSpinBox()
        self.bpm_spin.setRange(20, 300)
        self.bpm_spin.setSuffix(" BPM")
        form3.addRow("默认速度", self.bpm_spin)
        self.transpose_spin = QSpinBox()
        self.transpose_spin.setRange(-24, 24)
        self.transpose_spin.setSuffix(" 半音")
        form3.addRow("整体移调", self.transpose_spin)
        score_layout.addWidget(score_group)
        note2 = QLabel(
            "简谱识别默认按大调音级映射。若谱面是小调或需要移调，请在校正窗口中调整调式/调号。"
        )
        note2.setObjectName("Muted")
        note2.setWordWrap(True)
        score_layout.addWidget(note2)
        score_layout.addStretch(1)
        tabs.addTab(score_tab, "乐谱")

        # ---------------------------------------------------------- about
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setContentsMargins(18, 18, 18, 18)
        about_layout.setSpacing(8)
        about_title = QLabel("PitchLens 音准镜")
        about_title.setStyleSheet(f"font-size:22px;font-weight:800;color:{COLORS['accent']};")
        about_layout.addWidget(about_title)
        about_text = QLabel(
            "实时唱歌音高监测 + 简谱图片对比。\n"
            "音频与图片只在本地处理，不上传网络。\n\n"
            "核心链路：麦克风 → 环形缓冲 → YIN/CREPE → 音高曲线；"
            "简谱图片 → 预处理/符号识别 → 标准 NoteEvent；"
            "在线 HMM/速度估计 → 当前小节与未来旋律。\n\n"
            "识别边界：印刷体、单旋律、清晰图片。手写、多声部、复杂反复请使用校正/手动录入。"
        )
        about_text.setObjectName("Muted")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        about_layout.addStretch(1)
        tabs.addTab(about_tab, "关于")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setObjectName("Ghost")
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("保存设置")
        ok.setObjectName("Accent")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_devices()

    def _wrap(self, layout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    # --------------------------------------------------------- mic self-test
    def _toggle_mic_monitor(self) -> None:
        if self._mic_tester.is_running:
            self._stop_mic_test()
            return
        device = self.device_combo.currentData()
        try:
            rate = int(self.sample_rate_combo.currentText())
        except ValueError:
            rate = 48000
        ok, message = self._mic_tester.start(device, rate)
        if not ok:
            self.mic_status.setText(f"启动失败：{message}")
            return
        self.mic_monitor_btn.setText("停止监听")
        self.mic_record_btn.setEnabled(True)
        self.mic_status.setText("监听中 · 对着麦克风说话/唱，看电平起伏")
        self._mic_timer.start()

    def _stop_mic_test(self) -> None:
        self._mic_timer.stop()
        self._mic_tester.stop()
        self._mic_busy = False
        self.mic_monitor_btn.setText("开始监听")
        self.mic_record_btn.setEnabled(False)
        self.mic_record_btn.setText("录 5 秒并回放")
        self.mic_level.setValue(0)
        self.mic_level_label.setText("-- dB")

    def _update_mic_level(self) -> None:
        db = self._mic_tester.level_db()
        self.mic_level.setValue(max(0, min(60, int(db + 60))))
        self.mic_level_label.setText(f"{db:.0f} dB" if db > -60 else "-- dB")

    def _mic_record(self) -> None:
        if not self._mic_tester.is_running or self._mic_busy:
            return
        self._mic_busy = True
        self.mic_record_btn.setEnabled(False)
        self.mic_monitor_btn.setEnabled(False)
        self._mic_tester.start_recording()
        self.mic_status.setText("录音中… 5 秒，唱一段试试")
        QTimer.singleShot(5000, self._mic_finish_record)

    def _mic_finish_record(self) -> None:
        data = self._mic_tester.stop_recording()
        if data.size == 0:
            self.mic_status.setText("没有录到声音")
            self._mic_restore_after_test()
            return
        duration_ms = int(data.size / self._mic_tester.sample_rate * 1000)
        try:
            import sounddevice as sd

            sd.play(data, self._mic_tester.sample_rate)
        except Exception as exc:
            self.mic_status.setText(f"回放失败：{type(exc).__name__}: {exc}")
            self._mic_restore_after_test()
            return
        self.mic_status.setText("回放中… 这就是当前设置下的真实收音")
        QTimer.singleShot(duration_ms + 400, self._mic_restore_after_test)

    def _mic_restore_after_test(self) -> None:
        self._mic_busy = False
        if self._mic_tester.is_running:
            self.mic_monitor_btn.setEnabled(True)
            self.mic_record_btn.setEnabled(True)
            if "回放" in self.mic_status.text() or "没有录到" in self.mic_status.text():
                self.mic_status.setText("监听中 · 可再次录音回放对比")

    def done(self, result: int) -> None:  # noqa: N802
        self._stop_mic_test()
        super().done(result)

    def _mic_maybe_restart(self, *_args) -> None:
        if self._mic_tester.is_running and not self._mic_busy:
            self._stop_mic_test()
            self._toggle_mic_monitor()

    def _refresh_devices(self) -> None:
        self._devices = list_input_devices()
        self.device_combo.clear()
        self.device_combo.addItem("系统默认输入", None)
        for device in self._devices:
            self.device_combo.addItem(device.label, device.index)

    def _load(self) -> None:
        self.sample_rate_combo.setCurrentText(str(self.settings.sample_rate))
        self.detector_combo.setCurrentIndex(1 if self.settings.detector == "crepe" else 0)
        self.crepe_path_edit.setText(self.settings.crepe_model)
        available, reason = detector_available("crepe")
        if not available:
            self.detector_combo.setItemText(1, "CREPE（不可用，使用 YIN）")
            self.detector_combo.setToolTip(reason)
        self.latency_spin.setValue(self.settings.latency_offset_ms)
        self.a4_spin.setValue(self.settings.a4)
        self.history_spin.setValue(self.settings.history_seconds)
        self.future_spin.setValue(self.settings.future_seconds)
        self.span_spin.setValue(self.settings.y_span)
        self.good_spin.setValue(self.settings.good_cents)
        self.ok_spin.setValue(self.settings.ok_cents)
        self.target_check.setChecked(self.settings.show_target_band)
        self.raw_check.setChecked(self.settings.show_raw_curve)
        self.follow_scroll_check.setChecked(self.settings.auto_follow_scroll)
        self.theme_combo.setCurrentIndex(1 if self.settings.dark else 0)
        self.octave_spin.setValue(self.settings.base_octave)
        self.bpm_spin.setValue(self.settings.default_bpm)
        self.transpose_spin.setValue(self.settings.transpose)
        # Select the saved device.
        if self.settings.device_index is not None:
            index = self.device_combo.findData(self.settings.device_index)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)

    def _accept(self) -> None:
        self.settings.device_index = self.device_combo.currentData()
        self.settings.sample_rate = int(self.sample_rate_combo.currentText())
        self.settings.detector = "crepe" if self.detector_combo.currentIndex() == 1 else "yin"
        self.settings.crepe_model = self.crepe_path_edit.text().strip()
        self.settings.latency_offset_ms = float(self.latency_spin.value())
        self.settings.a4 = float(self.a4_spin.value())
        self.settings.history_seconds = float(self.history_spin.value())
        self.settings.future_seconds = float(self.future_spin.value())
        self.settings.y_span = int(self.span_spin.value())
        self.settings.good_cents = float(self.good_spin.value())
        self.settings.ok_cents = float(self.ok_spin.value())
        self.settings.show_target_band = self.target_check.isChecked()
        self.settings.show_raw_curve = self.raw_check.isChecked()
        self.settings.auto_follow_scroll = self.follow_scroll_check.isChecked()
        self.settings.dark = self.theme_combo.currentData() == "dark"
        self.settings.base_octave = int(self.octave_spin.value())
        self.settings.default_bpm = float(self.bpm_spin.value())
        self.settings.transpose = int(self.transpose_spin.value())
        self.result_settings = self.settings.clamped()
        self.accept()
