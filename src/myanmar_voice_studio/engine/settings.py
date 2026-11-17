"""Where the engine finds models, presets and the refined frontend. No hard-coded user paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PRESETS_RELATIVE = Path("config") / "voice_presets.json"


def _find_project_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / PRESETS_RELATIVE).exists():
            return candidate
    return None


@dataclass(frozen=True)
class Settings:
    project_root: Path
    models_dir: Path
    presets_file: Path
    third_party_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        """Resolve paths from MVS_PROJECT_ROOT / MVS_MODELS_DIR, else search upward from cwd and this file."""
        env_root = os.environ.get("MVS_PROJECT_ROOT")
        root = Path(env_root) if env_root else (
            _find_project_root(Path.cwd()) or _find_project_root(Path(__file__).resolve().parent)
        )
        if root is None:
            raise RuntimeError(
                "Cannot locate the project root (config/voice_presets.json). Set MVS_PROJECT_ROOT."
            )
        models = Path(os.environ.get("MVS_MODELS_DIR", root / "models"))
        return cls(
            project_root=root,
            models_dir=models,
            presets_file=root / PRESETS_RELATIVE,
            third_party_dir=root / "third_party",
        )
