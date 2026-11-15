"""Visual themes for PitchLens (dark / paper)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "bg": "#080d19",
    "panel": "#0f1729",
    "panel_alt": "#141f36",
    "panel_hi": "#1a2744",
    "border": "#223252",
    "border_soft": "#1a2844",
    "text": "#e8eefc",
    "text_dim": "#9aaecd",
    "muted": "#6f83a6",
    "accent": "#38d9ff",
    "accent_dim": "#1b91b4",
    "green": "#45e6a1",
    "amber": "#ffc857",
    "red": "#ff5c7a",
    "purple": "#b28dff",
    "pink": "#ff8ab5",
    "target_past": "#38d9ff",
    "target_future": "#d2e1ff",
    "target_future_lost": "#6f83a6",
    "target_current": "#45e6a1",
    "curve": "#50e2ff",
    "curve_raw": "#b28dff",
    "wash_history": "#38d9ff",
    "wash_future": "#b28dff",
    "dot_outline": "#080d19",
    "grid_alpha": "0.13",
    "highlight_text": "#06202a",
}

PAPER = {
    "bg": "#f4f2ec",
    "panel": "#ffffff",
    "panel_alt": "#faf9f5",
    "panel_hi": "#f1efe8",
    "border": "#e2ded3",
    "border_soft": "#eae7dd",
    "text": "#1f2937",
    "text_dim": "#55606e",
    "muted": "#8b929d",
    "accent": "#e8632c",
    "accent_dim": "#c2511f",
    "green": "#2e9e5b",
    "amber": "#b57708",
    "red": "#d64545",
    "purple": "#8a7aa8",
    "pink": "#c2638a",
    "target_past": "#8a97a8",
    "target_future": "#4f6b8a",
    "target_future_lost": "#a3aab4",
    "target_current": "#2e9e5b",
    "curve": "#1f2937",
    "curve_raw": "#a8b2bd",
    "wash_history": "#1f2937",
    "wash_future": "#e8632c",
    "dot_outline": "#ffffff",
    "grid_alpha": "0.35",
    "highlight_text": "#ffffff",
}

THEMES = {"dark": DARK, "paper": PAPER}

# Live palette: mutated in place by apply_theme so every COLORS[...] lookup
# made at call time follows the current theme.
COLORS = dict(DARK)

QSS_DARK = """
* {
    outline: none;
}
QMainWindow, QDialog {
    background: #080d19;
}
QWidget {
    color: #e8eefc;
    font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}
QToolTip {
    background: #1a2744;
    color: #e8eefc;
    border: 1px solid #2e4269;
    padding: 6px 8px;
    border-radius: 6px;
}
QFrame#TopBar {
    background: #0d1526;
    border-bottom: 1px solid #1c2a46;
}
QFrame#Card {
    background: #0f1729;
    border: 1px solid #1e2d4b;
    border-radius: 14px;
}
QFrame#CardHi {
    background: #111c31;
    border: 1px solid #284064;
    border-radius: 14px;
}
QFrame#Hud {
    background: rgba(13, 22, 40, 225);
    border: 1px solid #2a4166;
    border-radius: 16px;
}
QLabel#AppTitle {
    font-size: 19px;
    font-weight: 700;
    color: #f1f6ff;
    letter-spacing: 0.5px;
}
QLabel#AppSub {
    color: #6f83a6;
    font-size: 11px;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 700;
    color: #dfe9ff;
}
QLabel#Muted {
    color: #8fa3c8;
}
QLabel#TinyMuted {
    color: #6f83a6;
    font-size: 11px;
}
QLabel#BigNote {
    font-size: 52px;
    font-weight: 800;
    color: #f4f9ff;
}
QLabel#BigNoteGood { font-size: 52px; font-weight: 800; color: #45e6a1; }
QLabel#BigNoteOk { font-size: 52px; font-weight: 800; color: #ffc857; }
QLabel#BigNoteBad { font-size: 52px; font-weight: 800; color: #ff5c7a; }
QLabel#Hz {
    color: #9fb7dc;
    font-size: 15px;
}
QLabel#Cents {
    font-size: 17px;
    font-weight: 700;
    color: #38d9ff;
}
QLabel#Target {
    color: #d7e5ff;
    font-size: 13px;
}
QLabel#Pill {
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#PillGood { background: rgba(69,230,161,35); color: #45e6a1; border: 1px solid rgba(69,230,161,80); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillWarn { background: rgba(255,200,87,35); color: #ffc857; border: 1px solid rgba(255,200,87,80); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillBad { background: rgba(255,92,122,35); color: #ff5c7a; border: 1px solid rgba(255,92,122,80); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillInfo { background: rgba(56,217,255,25); color: #38d9ff; border: 1px solid rgba(56,217,255,70); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }

QPushButton {
    background: #152138;
    border: 1px solid #273a5e;
    border-radius: 9px;
    padding: 7px 14px;
    color: #cfdcf2;
    font-weight: 600;
}
QPushButton:hover { background: #1b2a47; border-color: #36517c; }
QPushButton:pressed { background: #101a2c; }
QPushButton:disabled { color: #586b8c; background: #111a2b; border-color: #1b2943; }
QPushButton#Accent {
    background: #38d9ff;
    color: #06202a;
    border: 1px solid #6ee7ff;
    font-weight: 800;
}
QPushButton#Accent:hover { background: #65e3ff; }
QPushButton#Danger {
    background: rgba(255,92,122,30);
    color: #ff8aa2;
    border: 1px solid rgba(255,92,122,80);
}
QPushButton#Danger:hover { background: rgba(255,92,122,50); }
QPushButton#Ghost {
    background: transparent;
    border: 1px solid #233451;
    color: #9fb2d1;
    font-weight: 500;
}
QPushButton#Ghost:hover { background: #131f35; color: #e8eefc; }
QPushButton#Icon {
    padding: 5px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
}
QPushButton#Transport {
    background: #45e6a1;
    color: #042014;
    border: 1px solid #7af0bd;
    border-radius: 11px;
    padding: 9px 22px;
    font-size: 14px;
    font-weight: 800;
}
QPushButton#Transport:hover { background: #6aecb7; }
QPushButton#TransportStop {
    background: rgba(255,92,122,28);
    color: #ff9ab0;
    border: 1px solid rgba(255,92,122,90);
    border-radius: 11px;
    padding: 9px 22px;
    font-size: 14px;
    font-weight: 800;
}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #0c1424;
    border: 1px solid #223252;
    border-radius: 8px;
    padding: 6px 9px;
    color: #e8eefc;
    selection-background-color: #1d6f89;
    min-height: 20px;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #34527f; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #38d9ff; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #111c31;
    border: 1px solid #2a4166;
    selection-background-color: #1d3a5c;
    color: #e8eefc;
    padding: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #16233a;
    border: none;
    width: 16px;
}
QCheckBox { color: #b9c8e2; spacing: 7px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    background: #0c1424; border: 1px solid #2b4064;
}
QCheckBox::indicator:checked { background: #38d9ff; border-color: #6ee7ff; }
QRadioButton { color: #b9c8e2; spacing: 7px; }
QSlider::groove:horizontal { height: 4px; background: #1b2943; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #38d9ff; }
QSlider::sub-page:horizontal { background: #1d7f9e; border-radius: 2px; }

QGroupBox {
    border: 1px solid #1e2d4b;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 12px 10px 12px;
    font-weight: 700;
    color: #c9d8ef;
    background: #0d1627;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #9fb7dc;
}

QTableView, QTableWidget {
    background: #0b1322;
    alternate-background-color: #0e1728;
    border: 1px solid #1e2d4b;
    border-radius: 10px;
    gridline-color: #1a2844;
    selection-background-color: #143a52;
    selection-color: #eaf7ff;
}
QHeaderView::section {
    background: #111c31;
    color: #8fa3c8;
    border: none;
    border-bottom: 1px solid #223252;
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
}
QTableCornerButton::section { background: #111c31; border: none; }

QSplitter::handle { background: #101a2c; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #1d3352; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a3c5e; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #3a5580; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2a3c5e; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QStatusBar { background: #0a111e; color: #7186a9; border-top: 1px solid #16233a; }
QStatusBar::item { border: none; }
QMenu { background: #111c31; border: 1px solid #2a4166; padding: 6px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #1b3454; }
QProgressBar { background: #101a2c; border: 1px solid #223252; border-radius: 5px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #38d9ff; border-radius: 4px; }
QTabWidget::pane { border: 1px solid #1e2d4b; border-radius: 10px; background: #0b1322; }
QTabBar::tab { background: transparent; color: #8fa3c8; padding: 8px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #e8eefc; border-bottom: 2px solid #38d9ff; }
QTabBar::tab:hover { color: #cfe0f7; }
"""

QSS_PAPER = """
* {
    outline: none;
}
QMainWindow, QDialog {
    background: #f4f2ec;
}
QWidget {
    color: #1f2937;
    font-family: "Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei";
    font-size: 13px;
}
QToolTip {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #d8d2c4;
    padding: 6px 8px;
    border-radius: 6px;
}
QFrame#TopBar {
    background: #ffffff;
    border-bottom: 1px solid #e2ded3;
}
QFrame#Card {
    background: #ffffff;
    border: 1px solid #e2ded3;
    border-radius: 14px;
}
QFrame#CardHi {
    background: #faf9f5;
    border: 1px solid #e2ded3;
    border-radius: 14px;
}
QFrame#Hud {
    background: rgba(255, 255, 255, 235);
    border: 1px solid #ddd8ca;
    border-radius: 16px;
}
QLabel#AppTitle {
    font-size: 19px;
    font-weight: 700;
    color: #1f2937;
    letter-spacing: 0.5px;
}
QLabel#AppSub {
    color: #8b929d;
    font-size: 11px;
}
QLabel#SectionTitle {
    font-size: 15px;
    font-weight: 700;
    color: #1f2937;
}
QLabel#Muted {
    color: #6b7380;
}
QLabel#TinyMuted {
    color: #8b929d;
    font-size: 11px;
}
QLabel#BigNote {
    font-size: 52px;
    font-weight: 800;
    color: #11161d;
}
QLabel#BigNoteGood { font-size: 52px; font-weight: 800; color: #2e9e5b; }
QLabel#BigNoteOk { font-size: 52px; font-weight: 800; color: #b57708; }
QLabel#BigNoteBad { font-size: 52px; font-weight: 800; color: #d64545; }
QLabel#Hz {
    color: #55606e;
    font-size: 15px;
}
QLabel#Cents {
    font-size: 17px;
    font-weight: 700;
    color: #e8632c;
}
QLabel#Target {
    color: #3d4653;
    font-size: 13px;
}
QLabel#Pill {
    border-radius: 10px;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 700;
}
QLabel#PillGood { background: rgba(46,158,91,30); color: #2e9e5b; border: 1px solid rgba(46,158,91,95); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillWarn { background: rgba(181,119,8,32); color: #a66a00; border: 1px solid rgba(181,119,8,95); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillBad { background: rgba(214,69,69,28); color: #c93a3a; border: 1px solid rgba(214,69,69,95); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }
QLabel#PillInfo { background: rgba(232,99,44,26); color: #c2511f; border: 1px solid rgba(232,99,44,85); border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 700; }

QPushButton {
    background: #ffffff;
    border: 1px solid #d8d2c4;
    border-radius: 9px;
    padding: 7px 14px;
    color: #3d4653;
    font-weight: 600;
}
QPushButton:hover { background: #f6f3ea; border-color: #c9c2b0; }
QPushButton:pressed { background: #efece2; }
QPushButton:disabled { color: #a9aeb6; background: #f3f1ea; border-color: #e6e2d6; }
QPushButton#Accent {
    background: #e8632c;
    color: #ffffff;
    border: 1px solid #d5561f;
    font-weight: 800;
}
QPushButton#Accent:hover { background: #f0763f; }
QPushButton#Danger {
    background: rgba(214,69,69,18);
    color: #c93a3a;
    border: 1px solid rgba(214,69,69,80);
}
QPushButton#Danger:hover { background: rgba(214,69,69,36); }
QPushButton#Ghost {
    background: transparent;
    border: 1px solid #d8d2c4;
    color: #6b7280;
    font-weight: 500;
}
QPushButton#Ghost:hover { background: #f3f0e7; color: #1f2937; }
QPushButton#Icon {
    padding: 5px;
    min-width: 28px;
    max-width: 28px;
    min-height: 28px;
    max-height: 28px;
    border-radius: 8px;
}
QPushButton#Transport {
    background: #2e9e5b;
    color: #ffffff;
    border: 1px solid #27824c;
    border-radius: 11px;
    padding: 9px 22px;
    font-size: 14px;
    font-weight: 800;
}
QPushButton#Transport:hover { background: #3ab06a; }
QPushButton#TransportStop {
    background: rgba(214,69,69,16);
    color: #c93a3a;
    border: 1px solid rgba(214,69,69,90);
    border-radius: 11px;
    padding: 9px 22px;
    font-size: 14px;
    font-weight: 800;
}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #d8d2c4;
    border-radius: 8px;
    padding: 6px 9px;
    color: #1f2937;
    selection-background-color: #f3ddc8;
    selection-color: #1f2937;
    min-height: 20px;
}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #c9c2b0; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #e8632c; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d8d2c4;
    selection-background-color: #f3e6d8;
    color: #1f2937;
    padding: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {
    background: #f3f0e7;
    border: none;
    width: 16px;
}
QCheckBox { color: #3d4653; spacing: 7px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    background: #ffffff; border: 1px solid #cfc9ba;
}
QCheckBox::indicator:checked { background: #e8632c; border-color: #d5561f; }
QRadioButton { color: #3d4653; spacing: 7px; }
QSlider::groove:horizontal { height: 4px; background: #e6e2d6; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #e8632c; }
QSlider::sub-page:horizontal { background: #ee9a6d; border-radius: 2px; }

QGroupBox {
    border: 1px solid #e2ded3;
    border-radius: 12px;
    margin-top: 16px;
    padding: 16px 12px 10px 12px;
    font-weight: 700;
    color: #3d4653;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #6b7280;
}

QTableView, QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8f6f0;
    border: 1px solid #e2ded3;
    border-radius: 10px;
    gridline-color: #eeeae0;
    selection-background-color: #f3e6d8;
    selection-color: #1f2937;
}
QHeaderView::section {
    background: #f3f0e7;
    color: #6b7280;
    border: none;
    border-bottom: 1px solid #e2ded3;
    padding: 7px 8px;
    font-size: 11px;
    font-weight: 700;
}
QTableCornerButton::section { background: #f3f0e7; border: none; }

QSplitter::handle { background: #eae7dd; width: 5px; height: 5px; }
QSplitter::handle:hover { background: #d8d2c4; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #d5d0c2; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #bfb9a8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #d5d0c2; min-width: 28px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QStatusBar { background: #f0eee6; color: #8b929d; border-top: 1px solid #e2ded3; }
QStatusBar::item { border: none; }
QMenu { background: #ffffff; border: 1px solid #d8d2c4; padding: 6px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #f3e6d8; }
QProgressBar { background: #f0eee6; border: 1px solid #d8d2c4; border-radius: 5px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #e8632c; border-radius: 4px; }
QTabWidget::pane { border: 1px solid #e2ded3; border-radius: 10px; background: #ffffff; }
QTabBar::tab { background: transparent; color: #6b7280; padding: 8px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #1f2937; border-bottom: 2px solid #e8632c; }
QTabBar::tab:hover { color: #3d4653; }
"""

# Backward-compatible alias: the dark stylesheet used to be the only one.
QSS = QSS_DARK


def theme_name(dark: bool) -> str:
    return "dark" if dark else "paper"


def apply_theme(app: QApplication, theme: str = "dark") -> None:
    if theme not in THEMES:
        theme = "dark"
    colors = THEMES[theme]
    COLORS.clear()
    COLORS.update(colors)
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(9)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["panel_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["panel_alt"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors["highlight_text"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
    app.setPalette(palette)
    app.setStyleSheet(_themed_qss(theme))


def _themed_qss(theme: str = "dark") -> str:
    # Fusion + a custom stylesheet drops the stock arrow glyphs; without an
    # explicit ::down-arrow image the combo boxes look like plain text fields.
    base = QSS_DARK if theme == "dark" else QSS_PAPER
    suffix = "" if theme == "dark" else "-dark"
    resources = (Path(__file__).resolve().parent.parent / "resources").as_posix()
    down = f'url("{resources}/chevron-down{suffix}.png")'
    up = f'url("{resources}/chevron-up{suffix}.png")'
    return (
        base
        + f"""
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: {down};
    width: 10px;
    height: 10px;
}}
QComboBox::down-arrow:on {{ top: 1px; }}
QComboBox::down-arrow:disabled {{
    image: {down};
    width: 10px;
    height: 10px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: {up};
    width: 8px;
    height: 8px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: {down};
    width: 8px;
    height: 8px;
}}
"""
    )


def status_color(state: str) -> str:
    return {
        "good": COLORS["green"],
        "ok": COLORS["amber"],
        "bad": COLORS["red"],
        "none": COLORS["muted"],
    }.get(state, COLORS["muted"])
