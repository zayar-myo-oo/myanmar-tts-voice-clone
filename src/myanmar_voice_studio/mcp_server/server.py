"""Myanmar Voice Studio MCP server (stdio).

Run:  mvs-mcp            (or: python -m myanmar_voice_studio.mcp_server)
Env:  MVS_PROJECT_ROOT, MVS_MODELS_DIR, MVS_OUTPUT_DIR, MVS_EXPORT_DIR

stdout carries only the MCP protocol; logs go to stderr. No network listener is opened.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..engine import ModelCapabilities, Settings, SynthesisRequest, VoiceEngine
from ..engine.renderer import DirectionPlan
from .service import ExportResult, JobInfo, ValidationReport, VoiceStudioService, VoiceSummary, wait_seconds

log = logging.getLogger("mvs-mcp")

INSTRUCTIONS = """Offline Burmese (my-MM) text-to-speech.
Workflow: list_voices -> (validate_voice_config / preview_voice_direction) -> generate_speech or
generate_directed_speech -> get_generation_status -> export_audio.
Results list applied and unsupported controls. Emotions (calm, sad, happy, excited, surprised,
curious, suspenseful, angry) and deliveries (narrator, podcast, energetic, soft) are prosody
approximations (speed/pitch/pauses, support "dsp"), not acted emotion. Whisper and shout are
not produced; never tell the user something was applied when the result lists it as unsupported.
Write numbers as Burmese words or Burmese digits; the engine reads Burmese digits aloud."""


def build_service() -> VoiceStudioService:
    settings = Settings.from_env()
    output_root = Path(os.environ.get("MVS_OUTPUT_DIR", settings.project_root / "outputs" / "mcp"))
    export_root = Path(os.environ.get("MVS_EXPORT_DIR", settings.project_root / "exports"))
    return VoiceStudioService(lambda: VoiceEngine.from_settings(settings), output_root, export_root)


def create_server(service: VoiceStudioService, transport_security=None) -> FastMCP:
    mcp = FastMCP("myanmar-voice-studio", instructions=INSTRUCTIONS, transport_security=transport_security)

    @mcp.tool()
    def list_voices() -> list[VoiceSummary]:
        """List installed voice profiles and how each control is supported (native/dsp/engine/unsupported)."""
        return service.list_voices()

    @mcp.tool()
    def list_presets() -> dict[str, Any]:
        """Return available voice-direction presets."""
        return service.list_presets()

    @mcp.tool()
    def get_model_capabilities(voice_id: str) -> ModelCapabilities:
        """Languages, devices, sample rate, limits and per-control support for a voice."""
        return service.capabilities(voice_id)

    @mcp.tool()
    def validate_voice_config(config: dict[str, Any]) -> ValidationReport:
        """Validate a voice-direction JSON (schema 1.0). Returns field errors and unsupported controls."""
        return service.validate(config)

    @mcp.tool()
    def preview_voice_direction(config: dict[str, Any]) -> DirectionPlan:
        """Show how a script will be segmented and directed, without generating audio."""
        return service.preview(config)

    @mcp.tool()
    def generate_speech(
        text: str = Field(description="Burmese text, up to 2000 characters"),
        voice_id: str = Field(description="from list_voices"),
        speed: float = Field(1.0, ge=0.5, le=2.0),
        pitch_semitones: float = Field(0.0, ge=-6, le=6),
        emotion: str | None = None,
        delivery: str | None = None,
        pause_after_ms: int = Field(0, ge=0, le=10000),
        strict: bool = Field(False, description="refuse if any requested control is unsupported"),
        wait_s: float | None = Field(120.0, description="seconds to wait; 0 returns a job to poll"),
    ) -> JobInfo:
        """Generate speech for one text. Returns a job; when completed it has an output_id for export_audio."""
        request = SynthesisRequest(text=text, voice_id=voice_id, speed=speed, pitch_semitones=pitch_semitones,
                                   emotion=emotion, delivery=delivery, pause_after_ms=pause_after_ms, strict=strict)
        job = service.submit_speech(request)
        return service.wait(job.job_id, wait_seconds(wait_s))

    @mcp.tool()
    def generate_directed_speech(
        config: dict[str, Any] = Field(description="voice-direction JSON, schema 1.0"),
        strict: bool = False,
        wait_s: float | None = Field(120.0, description="seconds to wait; 0 returns a job to poll"),
    ) -> JobInfo:
        """Render a segmented script (voices, pauses, directions) into one audio output."""
        job = service.submit_directed(config, strict=strict)
        return service.wait(job.job_id, wait_seconds(wait_s))

    @mcp.tool()
    def get_generation_status(job_id: str) -> JobInfo:
        """Progress (0..1), status, output_id, unsupported controls and errors for a job."""
        return service.status(job_id)

    @mcp.tool()
    def cancel_generation(job_id: str) -> JobInfo:
        """Cancel a queued job, or stop a directed job before its next segment."""
        return service.cancel(job_id)

    @mcp.tool()
    def export_audio(
        output_id: str,
        filename: str = Field(description="plain file name without folders, e.g. 'psychology-facts'"),
        format: Literal["wav", "mp3"] = "wav",
    ) -> ExportResult:
        """Copy a finished output into the approved export folder (MVS_EXPORT_DIR). Never overwrites."""
        return service.export(output_id, filename, format)

    return mcp


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=os.environ.get("MVS_LOG_LEVEL", "WARNING"))
    service = build_service()
    try:
        create_server(service).run(transport="stdio")
    finally:
        service.shutdown()


if __name__ == "__main__":
    main()
