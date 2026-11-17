"""MCP service unit tests (fake engine) and a real stdio protocol test (needs Nara + ffmpeg)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from myanmar_voice_studio.engine import SynthesisRequest, UnsupportedControlError, VoiceEngine, VoiceProfile
from myanmar_voice_studio.mcp_server.service import JobStatus, VoiceStudioService

from test_engine import FakeAdapter, _nara_ready

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((ROOT / "schemas" / "examples" / "stickman-story.json").read_text(encoding="utf-8"))


class SlowAdapter(FakeAdapter):
    """Blocks until released, so tests can observe queued/running jobs."""

    def __init__(self):
        self.release = threading.Event()

    def synthesize(self, text, voice, gap_s):
        self.release.wait(5)
        return super().synthesize(text, voice, gap_s)


def make_service(tmp_path, adapter=None) -> VoiceStudioService:
    adapter = adapter or FakeAdapter()
    voices = {
        "male_calm": VoiceProfile(voice_id="male_calm", display_name="M", adapter_id="fake", speaker="a"),
        "female_warm": VoiceProfile(voice_id="female_warm", display_name="F", adapter_id="fake", speaker="a"),
    }
    return VoiceStudioService(lambda: VoiceEngine(voices, {"fake": adapter}), tmp_path / "out", tmp_path / "exp")


def test_speech_job_completes_and_exports_without_overwrite(tmp_path):
    svc = make_service(tmp_path)
    job = svc.submit_speech(SynthesisRequest(text="မင်္ဂလာပါ", voice_id="male_calm", emotion="sad"))
    info = svc.wait(job.job_id, 5)
    assert info.status is JobStatus.COMPLETED and info.output_id == job.job_id
    assert info.unsupported == ["emotion=sad"]
    exported = svc.export(info.output_id, "hello", "wav")
    assert Path(exported.path).parent == (tmp_path / "exp").resolve() and exported.bytes > 44
    with pytest.raises(FileExistsError):
        svc.export(info.output_id, "hello.wav", "wav")


@pytest.mark.parametrize("name", ["../evil", "a/b", "C:\\x", "", ".hidden", "a" * 120])
def test_export_rejects_unsafe_names(tmp_path, name):
    svc = make_service(tmp_path)
    info = svc.wait(svc.submit_speech(SynthesisRequest(text="က", voice_id="male_calm")).job_id, 5)
    with pytest.raises(ValueError):
        svc.export(info.output_id, name, "wav")
    assert not any((tmp_path / "exp").glob("*")) if (tmp_path / "exp").exists() else True


def test_directed_job_reports_progress_and_unsupported(tmp_path):
    svc = make_service(tmp_path)
    info = svc.wait(svc.submit_directed(EXAMPLE).job_id, 5)
    assert info.status is JobStatus.COMPLETED and info.progress == 1.0
    assert "segment_003: delivery=shout" in info.unsupported


def test_strict_directed_is_refused_before_queueing(tmp_path):
    svc = make_service(tmp_path)
    with pytest.raises(UnsupportedControlError):
        svc.submit_directed(EXAMPLE, strict=True)


def test_cancel_queued_job_never_runs(tmp_path):
    slow = SlowAdapter()
    svc = make_service(tmp_path, slow)
    first = svc.submit_speech(SynthesisRequest(text="က", voice_id="male_calm"))
    second = svc.submit_directed(EXAMPLE)
    assert svc.cancel(second.job_id).job_id == second.job_id
    slow.release.set()
    assert svc.wait(first.job_id, 5).status is JobStatus.COMPLETED
    assert svc.wait(second.job_id, 5).status is JobStatus.CANCELLED


def test_validate_reports_field_errors_and_unknown_voice(tmp_path):
    svc = make_service(tmp_path)
    bad = svc.validate({"voice_id": "male_calm", "segments": []})
    assert not bad.valid and bad.errors
    unknown = svc.validate({**EXAMPLE, "voice_id": "nobody"})
    assert not unknown.valid and "Unknown voice" in unknown.errors[0]
    ok = svc.validate(EXAMPLE)
    assert ok.valid and ok.unsupported


def test_unknown_job_and_unready_export(tmp_path):
    svc = make_service(tmp_path)
    with pytest.raises(ValueError):
        svc.status("nope")
    slow = SlowAdapter()
    svc2 = make_service(tmp_path / "2", slow)
    job = svc2.submit_speech(SynthesisRequest(text="က", voice_id="male_calm"))
    with pytest.raises(ValueError, match="not ready"):
        svc2.export(job.job_id, "x", "wav")
    slow.release.set()


@pytest.mark.skipif(not _nara_ready(), reason="Nara models or ffmpeg not installed")
def test_stdio_protocol_end_to_end(tmp_path):
    """Start the real server as a subprocess and drive it with the official MCP client."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "MVS_PROJECT_ROOT": str(ROOT), "MVS_OUTPUT_DIR": str(tmp_path / "out"),
           "MVS_EXPORT_DIR": str(tmp_path / "exp"), "PYTHONIOENCODING": "utf-8"}
    params = StdioServerParameters(command=sys.executable, args=["-m", "myanmar_voice_studio.mcp_server"], env=env)

    async def run() -> dict:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                voices = (await session.call_tool("list_voices", {})).structuredContent
                check = (await session.call_tool("validate_voice_config", {"config": EXAMPLE})).structuredContent
                job = (await session.call_tool("generate_directed_speech",
                                               {"config": EXAMPLE, "wait_s": 300})).structuredContent
                exported = (await session.call_tool("export_audio", {"output_id": job["output_id"],
                                                                     "filename": "stickman", "format": "mp3"}))
                return {"names": names, "voices": voices, "check": check, "job": job,
                        "export": exported.structuredContent, "export_error": exported.isError}

    out = asyncio.run(run())
    assert len(out["names"]) == 10
    assert {v["voice_id"] for v in out["voices"]["result"]} >= {"male_calm", "female_warm"}
    assert out["check"]["valid"] is True
    assert out["job"]["status"] == "completed" and out["job"]["duration_s"] > 3
    assert not out["export_error"] and Path(out["export"]["path"]).suffix == ".mp3"
    assert Path(out["export"]["path"]).stat().st_size > 1000
