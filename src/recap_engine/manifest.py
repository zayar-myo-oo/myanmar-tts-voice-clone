"""Versioned project manifest + on-disk layout + input hashing."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .settings import ProjectSettings

SCHEMA_VERSION = 1
SUBDIRS = ("source", "analysis", "analysis/frames", "script", "tts", "render", "export", "logs")


def default_projects_root() -> Path:
    env = os.environ.get("RECAP_PROJECTS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "projects"


def hash_obj(obj: Any) -> str:
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def hash_file(path: Path, chunk: int = 1 << 20) -> str:
    """Fast content hash: size + first/last MiB (sources can be multi-GB)."""
    st = path.stat()
    h = hashlib.sha256(str(st.st_size).encode())
    with path.open("rb") as f:
        h.update(f.read(chunk))
        if st.st_size > 2 * chunk:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))
    return h.hexdigest()[:16]


class StageState(BaseModel):
    status: str = "pending"  # pending | running | done | failed | cancelled | skipped
    input_hash: str | None = None
    started: float | None = None
    finished: float | None = None
    seconds: float | None = None
    error: str | None = None
    artifacts: dict[str, str] = {}
    cache_hit: bool = False


class Manifest(BaseModel):
    schema_version: int = SCHEMA_VERSION
    project_id: str
    created: float = Field(default_factory=time.time)
    title: str = ""
    source: dict[str, Any] = {}  # url / original filename / probe info
    settings: ProjectSettings = ProjectSettings()
    stages: dict[str, StageState] = {}
    characters: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    exports: dict[str, str] = {}


class Project:
    """A project folder on disk."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.manifest_path = self.root / "manifest.json"
        self.manifest = Manifest.model_validate_json(self.manifest_path.read_text("utf-8"))

    # ---- creation / io -------------------------------------------------
    @classmethod
    def create(cls, settings: ProjectSettings | None = None, projects_root: Path | None = None,
               title: str = "", project_id: str | None = None) -> "Project":
        root_dir = Path(projects_root or default_projects_root())
        pid = project_id or time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        root = root_dir / pid
        for d in SUBDIRS:
            (root / d).mkdir(parents=True, exist_ok=True)
        m = Manifest(project_id=pid, title=title, settings=settings or ProjectSettings())
        (root / "manifest.json").write_text(m.model_dump_json(indent=2), "utf-8")
        return cls(root)

    def save(self) -> None:
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(self.manifest.model_dump_json(indent=2), "utf-8")
        os.replace(tmp, self.manifest_path)

    def reload(self) -> None:
        self.manifest = Manifest.model_validate_json(self.manifest_path.read_text("utf-8"))

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def read_json(self, rel: str, default: Any = None) -> Any:
        p = self.path(rel)
        if not p.exists():
            return default
        return json.loads(p.read_text("utf-8"))

    def write_json(self, rel: str, obj: Any) -> Path:
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, p)
        return p

    def stage(self, name: str) -> StageState:
        return self.manifest.stages.setdefault(name, StageState())

    @property
    def source_video(self) -> Path:
        return self.path(self.manifest.source.get("video", "source/video.mp4"))

    def log(self, msg: str) -> None:
        with self.path("logs", "engine.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
