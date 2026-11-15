"""Application settings independent of the Qt UI layer."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppSettings:
    # audio
    device_index: int | None = None
    detector: str = "yin"
    crepe_model: str = ""
    sample_rate: int = 48000
    fmin: float = 65.0
    fmax: float = 1200.0
    latency_offset_ms: float = 0.0
    # display
    a4: float = 440.0
    history_seconds: float = 9.0
    future_seconds: float = 7.0
    y_span: int = 24
    time_scale: float = 1.0
    good_cents: float = 25.0
    ok_cents: float = 50.0
    show_target_band: bool = True
    show_raw_curve: bool = False
    auto_follow_scroll: bool = True
    # score defaults
    base_octave: int = 4
    default_bpm: float = 90.0
    transpose: int = 0
    # ui
    dark: bool = False
    last_project: str = ""
    last_image_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        settings = cls()
        for key, value in (data or {}).items():
            if hasattr(settings, key) and value is not None:
                current = getattr(settings, key)
                try:
                    if isinstance(current, bool):
                        value = bool(value)
                    elif isinstance(current, int) and not isinstance(current, bool):
                        value = int(value)
                    elif isinstance(current, float):
                        value = float(value)
                    elif isinstance(current, str):
                        value = str(value)
                except Exception:
                    continue
                setattr(settings, key, value)
        return settings

    def clamped(self) -> "AppSettings":
        self.history_seconds = max(3.0, min(30.0, float(self.history_seconds)))
        self.future_seconds = max(2.0, min(30.0, float(self.future_seconds)))
        self.fmin = max(30.0, min(300.0, float(self.fmin)))
        self.fmax = max(self.fmin + 50.0, min(2000.0, float(self.fmax)))
        self.latency_offset_ms = max(-200.0, min(400.0, float(self.latency_offset_ms)))
        self.a4 = max(400.0, min(480.0, float(self.a4)))
        self.y_span = max(12, min(48, int(self.y_span)))
        self.good_cents = max(5.0, min(45.0, float(self.good_cents)))
        self.ok_cents = max(self.good_cents + 5.0, min(80.0, float(self.ok_cents)))
        return self


# ---------------------------------------------------------------- persistence
# QSettings (registry) writes are silently blocked on some machines, same as
# the profile root / LOCALAPPDATA restrictions that forced the log file next
# to the exe.  Persist settings as a plain JSON file with the same candidate
# order instead.
def _settings_candidates() -> list[Path]:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "PitchLens")
    candidates.append(Path.home() / "PitchLens")
    candidates.append(Path.cwd())
    return candidates


def _writable_settings_path() -> Path | None:
    for folder in _settings_candidates():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".pitchlens_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return folder / "settings.json"
        except Exception:
            continue
    return None


def load_settings_dict() -> dict[str, Any]:
    """Read the persisted settings JSON; first readable candidate wins."""
    for folder in _settings_candidates():
        path = folder / "settings.json"
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def save_settings_dict(data: dict[str, Any]) -> bool:
    path = _writable_settings_path()
    if path is None:
        logging.warning("settings: no writable location, changes not persisted")
        return False
    try:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        return True
    except Exception:
        logging.exception("settings: failed to write %s", path)
        return False
