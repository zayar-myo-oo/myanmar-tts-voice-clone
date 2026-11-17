"""Desktop worker protocol tests (fake engine)."""
from __future__ import annotations

import io
import json
import time

import pytest

pytest.importorskip("mcp")

from myanmar_voice_studio.worker.worker import handle_line, make_handlers, serve

from test_mcp import make_service


def call(handlers, method, params=None, req_id=1):
    return handle_line(json.dumps({"id": req_id, "method": method, "params": params or {}}), handlers)


def test_ping_and_unknown_method(tmp_path):
    h = make_handlers(make_service(tmp_path))
    assert call(h, "ping")["result"]["ok"] is True
    assert call(h, "nope")["error"]["type"] == "ValueError"
    assert handle_line("not json", h)["error"]["type"] == "JSONDecodeError"


def test_generate_poll_play_and_export(tmp_path):
    h = make_handlers(make_service(tmp_path))
    job = call(h, "generate_speech", {"request": {"text": "မင်္ဂလာပါ", "voice_id": "male_calm"}})["result"]
    for _ in range(50):
        status = call(h, "status", {"job_id": job["job_id"]})["result"]
        if status["status"] == "completed":
            break
        time.sleep(0.05)
    assert status["status"] == "completed"
    path = call(h, "audio_path", {"output_id": status["output_id"]})["result"]
    assert path.endswith(".wav")
    dest = tmp_path / "chosen.wav"
    out = call(h, "export_to_path", {"output_id": status["output_id"], "path": str(dest)})["result"]
    assert dest.exists() and out["format"] == "wav"
    again = call(h, "export_to_path", {"output_id": status["output_id"], "path": str(dest)})
    assert again["error"]["type"] == "FileExistsError"
    bad = call(h, "export_to_path", {"output_id": status["output_id"], "path": str(tmp_path / "x.txt")})
    assert "wav or .mp3" in bad["error"]["message"]


def test_validation_and_strict_errors_are_structured(tmp_path):
    h = make_handlers(make_service(tmp_path))
    bad = call(h, "generate_speech", {"request": {"text": "", "voice_id": "male_calm"}})
    assert bad["error"]["type"] == "ValidationError"
    strict = call(h, "generate_speech", {"request": {"text": "က", "voice_id": "male_calm",
                                                     "delivery": "whisper", "strict": True}})
    assert strict["error"]["type"] == "UnsupportedControlError"
    assert strict["error"]["controls"] == ["delivery=whisper"]


def test_serve_reads_lines_and_writes_one_response_each(tmp_path):
    stdin = io.StringIO('{"id": 7, "method": "ping"}\n\n{"id": 8, "method": "list_voices"}\n')
    stdout = io.StringIO()
    serve(make_service(tmp_path), stdin, stdout)
    lines = [json.loads(x) for x in stdout.getvalue().splitlines()]
    assert [x["id"] for x in lines] == [7, 8]
    assert {v["voice_id"] for v in lines[1]["result"]} == {"male_calm", "female_warm"}
