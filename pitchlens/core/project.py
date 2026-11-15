"""Project persistence: one portable ``.pitchproj`` zip per song."""

from __future__ import annotations

import base64
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .score import Score


@dataclass
class Project:
    score: Score
    image_bytes: bytes | None = None
    image_ext: str = ".png"
    source_name: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    app_version: str = "1.0.0"

    @property
    def has_image(self) -> bool:
        return bool(self.image_bytes)

    def to_dict(self, embed_image: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "format": "pitchlens-project",
            "version": 1,
            "app_version": self.app_version,
            "created_at": self.created_at,
            "image_ext": self.image_ext,
            "source_name": self.source_name,
            "settings": self.settings,
            "score": self.score.to_dict(),
        }
        if embed_image and self.image_bytes:
            data["image_base64"] = base64.b64encode(self.image_bytes).decode("ascii")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        image = None
        if data.get("image_base64"):
            try:
                image = base64.b64decode(data["image_base64"])
            except Exception:
                image = None
        return cls(
            score=Score.from_dict(data.get("score", {})),
            image_bytes=image,
            image_ext=str(data.get("image_ext", ".png")),
            source_name=str(data.get("source_name", "")),
            settings=dict(data.get("settings", {})),
            created_at=str(data.get("created_at", "")),
            app_version=str(data.get("app_version", "1.0.0")),
        )


class ProjectIO:
    @staticmethod
    def save(project: Project, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = project.to_dict(embed_image=False)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "project.json",
                json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            if project.image_bytes:
                ext = project.image_ext or ".png"
                if not ext.startswith("."):
                    ext = "." + ext
                archive.writestr(f"score{ext}", project.image_bytes)

    @staticmethod
    def load(path: str | Path) -> Project:
        path = Path(path)
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if "project.json" not in names:
                raise ValueError("不是有效的 PitchLens 项目文件（缺少 project.json）")
            data = json.loads(archive.read("project.json").decode("utf-8"))
            project = Project.from_dict(data)
            image_name = next(
                (name for name in names if name.startswith("score.") and name != "score."),
                None,
            )
            if image_name:
                project.image_bytes = archive.read(image_name)
                project.image_ext = Path(image_name).suffix or ".png"
            return project

    @staticmethod
    def save_json(project: Project, path: str | Path) -> None:
        path = Path(path)
        path.write_text(
            json.dumps(project.to_dict(embed_image=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def project_from_score(score: Score, image_bytes: bytes | None = None, image_ext: str = ".png") -> Project:
    return Project(
        score=score,
        image_bytes=image_bytes,
        image_ext=image_ext,
        source_name=score.image_name or score.title,
    )
