"""Segment planner and renderer for voice-direction documents (schema 1.0)."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Callable

import numpy as np
from pydantic import BaseModel

from .direction import Segment, VoiceDirection
from .engine import VoiceEngine, write_wav_exclusive
from .schemas import AppliedControl, SynthesisRequest, UnsupportedControlError


class GenerationCancelled(RuntimeError):
    """Raised between segments when the caller asked to stop."""


class SegmentPlan(BaseModel):
    id: str
    voice_id: str
    text: str
    request: SynthesisRequest
    applied: list[AppliedControl]
    unsupported: list[str]


class DirectionPlan(BaseModel):
    project_name: str
    segments: list[SegmentPlan]
    unsupported_total: int
    warnings: list[str]


class SegmentTiming(BaseModel):
    id: str
    voice_id: str
    start_s: float
    end_s: float
    applied: list[AppliedControl]
    unsupported: list[str]
    segment_path: Path | None = None


class RenderResult(BaseModel):
    output_path: Path
    report_path: Path
    sample_rate: int
    duration_s: float
    segments: list[SegmentTiming]
    warnings: list[str]


def segment_request(doc: VoiceDirection, seg: Segment, strict: bool = False) -> SynthesisRequest:
    """Merge document-level settings with one segment into an engine request."""
    g = doc.global_settings
    speed = float(np.clip(g.speed * (seg.speed or 1.0), 0.5, 2.0))
    pitch = float(np.clip(g.pitch + (seg.pitch or 0.0), -6.0, 6.0))
    energy = seg.energy if seg.energy is not None else g.energy
    return SynthesisRequest(
        text=seg.text,
        voice_id=seg.voice_id or doc.voice_id,
        speed=speed,
        pitch_semitones=pitch,
        emotion=None if seg.emotion in (None, "neutral") else seg.emotion,
        delivery=None if seg.delivery in (None, "normal") else seg.delivery,
        energy=energy,
        emphasis=seg.emphasis,
        pause_before_ms=int(round(seg.pause_before_ms * g.pause_scale)),
        pause_after_ms=int(round(seg.pause_after_ms * g.pause_scale)),
        strict=strict,
    )


def preview(engine: VoiceEngine, doc: VoiceDirection, strict: bool = False) -> DirectionPlan:
    """Validate voices and report, per segment, what will and will not be applied. No audio."""
    plans: list[SegmentPlan] = []
    warnings: list[str] = []
    if doc.preset:
        warnings.append(f"Preset '{doc.preset}' is recorded but presets are applied in Phase 9; settings come from the document")
    problems: list[str] = []
    for seg in doc.segments:
        req = segment_request(doc, seg)
        applied, unsupported = engine.plan(req)  # raises ValueError for unknown voices
        if unsupported:
            problems.extend(f"{seg.id}: {u}" for u in unsupported)
        plans.append(SegmentPlan(id=seg.id, voice_id=req.voice_id, text=seg.text, request=req,
                                 applied=applied, unsupported=unsupported))
    if strict and problems:
        raise UnsupportedControlError(problems)
    if problems:
        warnings.append(f"{len(problems)} requested control(s) cannot be applied; see segment 'unsupported'")
    return DirectionPlan(project_name=doc.project_name, segments=plans,
                         unsupported_total=len(problems), warnings=warnings)


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower()
    return slug[:40] or "project"


def render(
    engine: VoiceEngine,
    doc: VoiceDirection,
    output_dir: Path,
    *,
    strict: bool = False,
    write_segments: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> RenderResult:
    """Render every segment, join them with their pauses, and write one WAV plus a JSON report."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ValueError(f"Output directory does not exist: {output_dir}")
    plan = preview(engine, doc, strict=strict)  # fail fast before any synthesis

    run_id = uuid.uuid4().hex[:10]
    base = f"{_slug(doc.project_name)}-{run_id}"
    seg_dir = None
    if write_segments:
        seg_dir = output_dir / f"{base}-segments"
        seg_dir.mkdir()  # new directory; fails if it exists

    audio: list[np.ndarray] = []
    timings: list[SegmentTiming] = []
    warnings = list(plan.warnings)
    sr_all: int | None = None
    cursor = 0
    total = len(plan.segments)
    for index, sp in enumerate(plan.segments):
        if should_cancel and should_cancel():
            raise GenerationCancelled(f"cancelled before segment {sp.id} ({index}/{total} done)")
        wav, sr, applied, unsupported, seg_warnings = engine.render(sp.request)
        if sr_all is None:
            sr_all = sr
        elif sr != sr_all:
            raise ValueError(f"Segment {sp.id} uses sample rate {sr}, expected {sr_all}; mix voices of one rate")
        seg_path = write_wav_exclusive(seg_dir / f"{sp.id}.wav", wav, sr) if seg_dir else None
        timings.append(SegmentTiming(id=sp.id, voice_id=sp.voice_id, start_s=round(cursor / sr, 3),
                                     end_s=round((cursor + wav.size) / sr, 3), applied=applied,
                                     unsupported=unsupported, segment_path=seg_path))
        warnings.extend(f"{sp.id}: {w}" for w in seg_warnings)
        audio.append(wav)
        cursor += wav.size
        if on_progress:
            on_progress(index + 1, total)

    assert sr_all is not None
    final = np.concatenate(audio)
    out_path = write_wav_exclusive(output_dir / f"{base}.wav", final, sr_all)
    result_wo_report = {
        "output_path": str(out_path), "sample_rate": sr_all, "duration_s": round(final.size / sr_all, 3),
        "segments": [json.loads(t.model_dump_json()) for t in timings], "warnings": warnings,
        "direction": json.loads(doc.model_dump_json()),
    }
    report_path = output_dir / f"{base}.report.json"
    with open(report_path, "x", encoding="utf-8") as fh:
        json.dump(result_wo_report, fh, ensure_ascii=False, indent=2)
    return RenderResult(output_path=out_path, report_path=report_path, sample_rate=sr_all,
                        duration_s=round(final.size / sr_all, 3), segments=timings, warnings=warnings)
