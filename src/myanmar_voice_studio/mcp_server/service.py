"""Transport-independent service behind the MCP tools: jobs, outputs and safe export.

Kept separate from the MCP layer so it can be unit-tested without a client.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..engine import ModelCapabilities, SynthesisRequest, VoiceEngine
from ..engine.direction import VoiceDirection
from ..engine.renderer import DirectionPlan, GenerationCancelled, preview, render


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobInfo(BaseModel):
    job_id: str
    kind: Literal["speech", "directed"]
    status: JobStatus
    progress: float  # 0..1
    output_id: str | None = None
    duration_s: float | None = None
    unsupported: list[str] = []
    warnings: list[str] = []
    error: str | None = None


class ValidationReport(BaseModel):
    valid: bool
    errors: list[str]
    unsupported: list[str]
    warnings: list[str]


class ExportResult(BaseModel):
    output_id: str
    path: str
    format: str
    bytes: int


class VoiceSummary(BaseModel):
    voice_id: str
    display_name: str
    adapter_id: str
    speaker: str
    supported_controls: dict[str, str]
    control_values: dict[str, list[str]] = {}
    note: str


@dataclass
class _Job:
    info: JobInfo
    cancel: threading.Event = field(default_factory=threading.Event)
    audio_path: Path | None = None
    done: threading.Event = field(default_factory=threading.Event)


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,99}$")


class VoiceStudioService:
    def __init__(self, engine_factory, output_root: Path, export_root: Path, max_workers: int = 1):
        self._engine_factory = engine_factory
        self._engine: VoiceEngine | None = None
        self._engine_lock = threading.Lock()
        self.output_root = Path(output_root)
        self.export_root = Path(export_root)
        self._jobs: dict[str, _Job] = {}
        self._jobs_lock = threading.Lock()
        # One worker by default: a single CPU model instance, jobs run in order.
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mvs-job")

    # -- engine (loaded once, lazily) ------------------------------------------------
    @property
    def engine(self) -> VoiceEngine:
        with self._engine_lock:
            if self._engine is None:
                self._engine = self._engine_factory()
            return self._engine

    # -- discovery -----------------------------------------------------------------------
    def list_voices(self) -> list[VoiceSummary]:
        out = []
        for v in self.engine.list_voices():
            caps = self.engine.capabilities(v.voice_id)
            out.append(VoiceSummary(
                voice_id=v.voice_id, display_name=v.display_name, adapter_id=v.adapter_id, speaker=v.speaker,
                supported_controls={k: c.support.value for k, c in caps.controls.items()},
                control_values={k: c.values for k, c in caps.controls.items() if c.values is not None},
                note="Expressions are prosody approximations (DSP), not acted emotion. Whisper/shout are not produced.",
            ))
        return out

    def capabilities(self, voice_id: str) -> ModelCapabilities:
        return self.engine.capabilities(voice_id)

    def list_presets(self) -> dict:
        return {
            "presets": [],
            "note": "Voice-direction presets (TikTok Hook, Documentary Narrator, ...) arrive in Phase 9. "
                    "Use voice_id from list_voices and per-segment settings for now.",
        }

    # -- validation / preview ---------------------------------------------------------
    def validate(self, config: dict) -> ValidationReport:
        from pydantic import ValidationError

        try:
            doc = VoiceDirection.model_validate(config)
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
            return ValidationReport(valid=False, errors=errors, unsupported=[], warnings=[])
        try:
            plan = preview(self.engine, doc)
        except ValueError as exc:
            return ValidationReport(valid=False, errors=[str(exc)], unsupported=[], warnings=[])
        unsupported = [f"{s.id}: {u}" for s in plan.segments for u in s.unsupported]
        return ValidationReport(valid=True, errors=[], unsupported=unsupported, warnings=plan.warnings)

    def preview(self, config: dict) -> DirectionPlan:
        return preview(self.engine, VoiceDirection.model_validate(config))

    # -- jobs ------------------------------------------------------------------------------
    def _new_job(self, kind: Literal["speech", "directed"]) -> _Job:
        job_id = uuid.uuid4().hex[:12]
        job = _Job(JobInfo(job_id=job_id, kind=kind, status=JobStatus.QUEUED, progress=0.0))
        with self._jobs_lock:
            self._jobs[job_id] = job
        return job

    def _job_dir(self, job_id: str) -> Path:
        path = self.output_root / job_id
        path.mkdir(parents=True, exist_ok=False)
        return path

    def _run(self, job: _Job, work) -> None:
        if job.cancel.is_set():
            job.info.status = JobStatus.CANCELLED
            job.done.set()
            return
        job.info.status = JobStatus.RUNNING
        try:
            work(job)
            job.info.status = JobStatus.COMPLETED
            job.info.progress = 1.0
            job.info.output_id = job.info.job_id
        except GenerationCancelled as exc:
            job.info.status = JobStatus.CANCELLED
            job.info.error = str(exc)
        except Exception as exc:  # reported to the client, never swallowed
            job.info.status = JobStatus.FAILED
            job.info.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.done.set()

    def submit_speech(self, request: SynthesisRequest) -> JobInfo:
        self.engine.plan(request)  # validate voice / strict mode before queueing
        job = self._new_job("speech")

        def work(j: _Job) -> None:
            result = self.engine.synthesize(request, self._job_dir(j.info.job_id))
            j.audio_path = result.output_path
            j.info.duration_s = result.duration_s
            j.info.unsupported = result.unsupported
            j.info.warnings = result.warnings

        self._pool.submit(self._run, job, work)
        return job.info

    def submit_directed(self, config: dict, strict: bool = False) -> JobInfo:
        doc = VoiceDirection.model_validate(config)
        preview(self.engine, doc, strict=strict)  # fail fast before queueing
        job = self._new_job("directed")

        def work(j: _Job) -> None:
            def progress(done: int, total: int) -> None:
                j.info.progress = done / total

            result = render(self.engine, doc, self._job_dir(j.info.job_id), strict=strict,
                            write_segments=True, should_cancel=j.cancel.is_set, on_progress=progress)
            j.audio_path = result.output_path
            j.info.duration_s = result.duration_s
            j.info.unsupported = [f"{s.id}: {u}" for s in result.segments for u in s.unsupported]
            j.info.warnings = result.warnings

        self._pool.submit(self._run, job, work)
        return job.info

    def _job(self, job_id: str) -> _Job:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id '{job_id}'")
        return job

    def status(self, job_id: str) -> JobInfo:
        return self._job(job_id).info

    def wait(self, job_id: str, timeout_s: float) -> JobInfo:
        job = self._job(job_id)
        job.done.wait(timeout=max(0.0, timeout_s))
        return job.info

    def cancel(self, job_id: str) -> JobInfo:
        """Queued jobs never start; directed jobs stop before their next segment.
        A single-sentence job that is already running cannot be interrupted mid-synthesis."""
        job = self._job(job_id)
        if job.info.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            job.cancel.set()
            if job.info.status is JobStatus.RUNNING and job.info.kind == "speech":
                job.info.warnings = [*job.info.warnings,
                                     "Cancel requested; single-sentence synthesis finishes before it can stop"]
        return job.info

    # -- export ----------------------------------------------------------------------------
    def export(self, output_id: str, filename: str, fmt: Literal["wav", "mp3"] = "wav") -> ExportResult:
        job = self._job(output_id)
        if job.info.status is not JobStatus.COMPLETED or job.audio_path is None:
            raise ValueError(f"Output '{output_id}' is not ready (status: {job.info.status.value})")
        stem = filename.strip()
        if stem.lower().endswith((".wav", ".mp3")):
            stem = stem[:-4]
        if not _SAFE_NAME.match(stem) or ".." in stem:
            raise ValueError("filename must be a plain name: letters, digits, space, _ . - (no folders)")
        self.export_root.mkdir(parents=True, exist_ok=True)
        root = self.export_root.resolve()
        dest = (root / f"{stem}.{fmt}").resolve()
        if dest.parent != root:
            raise ValueError("export path escapes the export directory")
        if dest.exists():
            raise FileExistsError(f"{dest.name} already exists in the export directory; choose another name")
        return self._write_export(output_id, job, dest, fmt)

    def export_to_path(self, output_id: str, dest: Path) -> ExportResult:
        """Export to a path the user chose in a native save dialog (desktop app). Never overwrites."""
        job = self._job(output_id)
        if job.info.status is not JobStatus.COMPLETED or job.audio_path is None:
            raise ValueError(f"Output '{output_id}' is not ready (status: {job.info.status.value})")
        dest = Path(dest).resolve()
        fmt = dest.suffix.lower().lstrip(".")
        if fmt not in ("wav", "mp3"):
            raise ValueError("file must end in .wav or .mp3")
        if not dest.parent.is_dir():
            raise ValueError(f"folder does not exist: {dest.parent}")
        if dest.exists():
            raise FileExistsError(f"{dest.name} already exists; choose another name")
        return self._write_export(output_id, job, dest, fmt)

    def audio_path(self, output_id: str) -> Path:
        job = self._job(output_id)
        if job.info.status is not JobStatus.COMPLETED or job.audio_path is None:
            raise ValueError(f"Output '{output_id}' is not ready")
        return job.audio_path

    def _write_export(self, output_id: str, job: _Job, dest: Path, fmt: str) -> ExportResult:
        assert job.audio_path is not None
        if fmt == "wav":
            with open(job.audio_path, "rb") as src, open(dest, "xb") as out:
                shutil.copyfileobj(src, out)
        else:
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise RuntimeError("ffmpeg is required for MP3 export")
            subprocess.run([ffmpeg, "-n", "-loglevel", "error", "-i", str(job.audio_path),
                            "-codec:a", "libmp3lame", "-q:a", "2", str(dest)], check=True)
        return ExportResult(output_id=output_id, path=str(dest), format=fmt, bytes=dest.stat().st_size)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def wait_seconds(seconds: float | None, default: float = 120.0) -> float:
    return default if seconds is None else min(max(seconds, 0.0), 600.0)


__all__ = ["VoiceStudioService", "JobInfo", "JobStatus", "ValidationReport", "ExportResult",
           "VoiceSummary", "wait_seconds"]
