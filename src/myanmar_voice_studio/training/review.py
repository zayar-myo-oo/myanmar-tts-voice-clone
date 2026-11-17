"""Transcript review for own-voice recordings (used by the desktop app's Review screen).

Per clip `name.wav` in a recordings folder:
  name.txt        approved transcript (used for training)
  name.draft.txt  ASR draft (not used until approved)
  name.rejected   marker: clip excluded from training
  asr_matches.json (folder) ASR text + best script match per clip (from `mvs-asr --match-script`)

Only folders directly under <project>/recordings/ are allowed, and only plain *.wav names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import soundfile as sf
from pydantic import BaseModel

_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,80}\.wav$")


class ReviewItem(BaseModel):
    file: str
    status: Literal["approved", "draft", "rejected", "missing"]
    text: str  # approved text, else draft, else ""
    heard: str = ""  # ASR
    script_id: str | None = None
    script_text: str = ""
    ser: float | None = None
    duration_s: float = 0.0


class ReviewSummary(BaseModel):
    folder: str
    folders: list[str]
    items: list[ReviewItem]
    approved: int
    draft: int
    rejected: int
    approved_minutes: float


def recordings_root(project_root: Path) -> Path:
    return (Path(project_root) / "recordings").resolve()


def list_folders(project_root: Path) -> list[str]:
    root = recordings_root(project_root)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and any(p.glob("*.wav")))


def _folder(project_root: Path, name: str) -> Path:
    root = recordings_root(project_root)
    path = (root / name).resolve()
    if path.parent != root or not path.is_dir():
        raise ValueError(f"unknown recordings folder '{name}'")
    return path


def _clip(folder: Path, file: str) -> Path:
    if not _NAME.match(file):
        raise ValueError(f"invalid clip name '{file}'")
    path = folder / file
    if not path.is_file():
        raise ValueError(f"clip not found: {file}")
    return path


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def summary(project_root: Path, folder_name: str | None = None) -> ReviewSummary:
    folders = list_folders(project_root)
    if not folders:
        raise ValueError("no recordings folders with WAV files under recordings/")
    root = recordings_root(project_root)
    newest = max(folders, key=lambda n: max(p.stat().st_mtime for p in (root / n).glob("*.wav")))
    name = folder_name or newest  # default: the most recently recorded folder
    folder = _folder(project_root, name)
    matches_file = folder / "asr_matches.json"
    matches = json.loads(matches_file.read_text(encoding="utf-8")) if matches_file.exists() else {}
    items: list[ReviewItem] = []
    for wav in sorted(folder.glob("*.wav")):
        if not _NAME.match(wav.name):
            continue
        m = matches.get(wav.name, {})
        txt, draft = wav.with_suffix(".txt"), wav.with_name(wav.stem + ".draft.txt")
        if wav.with_suffix(".rejected").exists():
            status, text = "rejected", _read(txt) or _read(draft)
        elif txt.exists():
            status, text = "approved", _read(txt)
        elif draft.exists():
            status, text = "draft", _read(draft)
        else:
            status, text = "missing", m.get("heard", "")
        try:
            dur = round(sf.info(wav).duration, 2)
        except Exception:
            dur = 0.0
        items.append(ReviewItem(file=wav.name, status=status, text=text, heard=m.get("heard", ""),
                                script_id=m.get("match"), script_text=m.get("expected", ""), ser=m.get("ser"),
                                duration_s=dur))
    count = lambda s: sum(i.status == s for i in items)  # noqa: E731
    minutes = round(sum(i.duration_s for i in items if i.status == "approved") / 60, 2)
    return ReviewSummary(folder=name, folders=folders, items=items, approved=count("approved"),
                         draft=count("draft") + count("missing"), rejected=count("rejected"), approved_minutes=minutes)


def audio_path(project_root: Path, folder_name: str, file: str) -> Path:
    return _clip(_folder(project_root, folder_name), file)


def approve(project_root: Path, folder_name: str, file: str, text: str) -> ReviewItem:
    """Save the transcript the user confirmed (overwrites only this clip's .txt) and clear any reject mark."""
    wav = _clip(_folder(project_root, folder_name), file)
    clean = " ".join(text.split())
    if not clean or not re.search(r"[က-႟]", clean):
        raise ValueError("transcript must contain Burmese text")
    if re.search(r"[0-9၀-၉]", clean):
        raise ValueError("write numbers as Burmese words, not digits")
    wav.with_suffix(".txt").write_text(clean + "\n", encoding="utf-8")
    wav.with_suffix(".rejected").unlink(missing_ok=True)
    return next(i for i in summary(project_root, folder_name).items if i.file == file)


def reject(project_root: Path, folder_name: str, file: str, rejected: bool = True) -> ReviewItem:
    """Exclude (or re-include) a clip. The audio and any text files are kept."""
    wav = _clip(_folder(project_root, folder_name), file)
    marker = wav.with_suffix(".rejected")
    if rejected:
        marker.write_text("excluded from training by the user\n", encoding="utf-8")
    else:
        marker.unlink(missing_ok=True)
    return next(i for i in summary(project_root, folder_name).items if i.file == file)
