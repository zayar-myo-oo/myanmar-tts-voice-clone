"""Desktop worker: JSON lines over stdin/stdout.

Request:  {"id": 1, "method": "list_voices", "params": {}}
Response: {"id": 1, "result": ...}  or  {"id": 1, "error": {"type": "ValueError", "message": "..."}}

stdout carries only protocol lines; logs go to stderr. The desktop app (Tauri) starts one
worker, so the model is loaded once and shared by every screen.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ..engine import SynthesisRequest, UnsupportedControlError
from ..mcp_server.server import build_service
from ..mcp_server.service import VoiceStudioService

PROTOCOL_VERSION = 1
log = logging.getLogger("mvs-worker")


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return json.loads(value.model_dump_json())
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def make_handlers(svc: VoiceStudioService, project_root: Path | None = None) -> dict[str, Callable[[dict], Any]]:
    from ..engine.settings import Settings
    from ..mcp_server import registration

    from ..mcp_server.http import HttpMcpController
    from ..training import review

    def root() -> Path:
        return project_root or Settings.from_env().project_root

    http = HttpMcpController(svc)
    return {
        "review_summary": lambda p: review.summary(root(), p.get("folder")),
        "review_audio_path": lambda p: str(review.audio_path(root(), p["folder"], p["file"])),
        "review_approve": lambda p: review.approve(root(), p["folder"], p["file"], p["text"]),
        "review_reject": lambda p: review.reject(root(), p["folder"], p["file"], bool(p.get("rejected", True))),
        "mcp_http_status": lambda p: http.status(),
        "mcp_http_start": lambda p: http.start(p.get("port")),
        "mcp_http_stop": lambda p: http.stop(),
        "mcp_status": lambda p: registration.status(root()),
        "mcp_set_enabled": lambda p: registration.set_enabled(p["client"], bool(p["enabled"]), root()),
        "ping": lambda p: {"protocol": PROTOCOL_VERSION, "ok": True},
        "list_voices": lambda p: svc.list_voices(),
        "capabilities": lambda p: svc.capabilities(p["voice_id"]),
        "validate": lambda p: svc.validate(p["config"]),
        "preview": lambda p: svc.preview(p["config"]),
        "generate_speech": lambda p: svc.submit_speech(SynthesisRequest.model_validate(p["request"])),
        "generate_directed": lambda p: svc.submit_directed(p["config"], strict=bool(p.get("strict", False))),
        "status": lambda p: svc.status(p["job_id"]),
        "cancel": lambda p: svc.cancel(p["job_id"]),
        "audio_path": lambda p: str(svc.audio_path(p["output_id"])),
        "export_to_path": lambda p: svc.export_to_path(p["output_id"], Path(p["path"])),
    }


def handle_line(line: str, handlers: dict[str, Callable[[dict], Any]]) -> dict:
    req_id = None
    try:
        msg = json.loads(line)
        req_id = msg.get("id")
        method = msg["method"]
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unknown method '{method}'")
        return {"id": req_id, "result": _dump(handler(msg.get("params") or {}))}
    except ValidationError as exc:
        errors = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return {"id": req_id, "error": {"type": "ValidationError", "message": "; ".join(errors)}}
    except UnsupportedControlError as exc:
        return {"id": req_id, "error": {"type": "UnsupportedControlError", "message": str(exc),
                                        "controls": exc.controls}}
    except (KeyError, ValueError, FileExistsError, RuntimeError, json.JSONDecodeError) as exc:
        return {"id": req_id, "error": {"type": type(exc).__name__, "message": str(exc)}}


def serve(svc: VoiceStudioService, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    handlers = make_handlers(svc)
    for line in stdin:
        if not line.strip():
            continue
        stdout.write(json.dumps(handle_line(line, handlers), ensure_ascii=False) + "\n")
        stdout.flush()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level="WARNING")
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    svc = build_service()
    try:
        serve(svc)
    finally:
        svc.shutdown()


if __name__ == "__main__":
    main()
