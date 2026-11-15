"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __app_name__, __version__
from .ui.main_window import MainWindow
from .ui.theme import apply_theme

_LOG_PATH: Path | None = None


def _saved_theme() -> str:
    """Theme from the persisted settings JSON; paper by default."""
    try:
        from .core.settings import load_settings_dict

        return "dark" if load_settings_dict().get("dark", False) else "paper"
    except Exception:
        return "paper"


def _resource_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "resources" / name


def _configure_logging() -> Path:
    # Candidate order matters: on this machine the profile root is not
    # writable (WinError 5) and the unsigned exe was even blocked from
    # creating %LOCALAPPDATA%\PitchLens.  Next to the exe always works for a
    # portable build and is the easiest place for the user to find.
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "PitchLens")
    candidates.append(Path.home() / "PitchLens")
    candidates.append(Path.cwd())
    log_path = candidates[-1] / "pitchlens.log"
    for folder in candidates:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(
                folder / "pitchlens.log", encoding="utf-8"
            )
            log_path = folder / "pitchlens.log"
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                handlers=[handler, logging.StreamHandler(sys.stdout)],
            )
            return log_path
        except Exception:
            continue
    logging.basicConfig(level=logging.INFO)
    return log_path


def install_exception_hook() -> None:
    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.error("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                "PitchLens 发生错误",
                f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入日志：\n"
                f"{_LOG_PATH or 'pitchlens.log'}",
            )
        except Exception:
            pass

    sys.excepthook = hook


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PitchLens 音准镜")
    parser.add_argument("--demo", action="store_true", help="启动后自动加载示例简谱")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--project", type=str, default="", help="启动时打开 .pitchproj 项目")
    return parser


def main(argv: list[str] | None = None) -> int:
    global _LOG_PATH
    args = build_parser().parse_args(argv)
    _LOG_PATH = _configure_logging()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("PitchLens")
    app.setApplicationDisplayName(__app_name__)
    app.setOrganizationName("PitchLens")
    app.setApplicationVersion(__version__)
    apply_theme(app, _saved_theme())
    install_exception_hook()
    icon_path = _resource_path("app.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow(demo=args.demo)
    window.show()
    if args.project:
        QTimer.singleShot(300, lambda: _open_project_path(window, args.project))
    logging.info("PitchLens %s started", __version__)
    return int(app.exec())


def _open_project_path(window: MainWindow, path: str) -> None:
    try:
        from .core.project import ProjectIO

        project = ProjectIO.load(path)
        window._apply_project(project, reset=True)
        window._set_status(f"已打开 {Path(path).name}")
    except Exception as exc:
        QMessageBox.critical(window, "打开失败", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
