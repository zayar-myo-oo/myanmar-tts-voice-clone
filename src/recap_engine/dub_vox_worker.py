"""Runs inside the Voice Workbench venv ("voice model collection/Voice Workbench/.venv").

Serves JSON lines on stdin: {"text", "voice_id", "model", "out"} -> {"ok", "seconds", "backend"}.
It only wraps Voice Workbench's own engine.clone_burma_cat (VoxCPM2 voice cloning, fully local), so the
recap venv never needs the VoxCPM2 runtime and the two apps always produce the same voice.
"""
from __future__ import annotations

import json
import shutil
import sys
import wave


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    sys.path.insert(0, sys.argv[1])  # the Voice Workbench source folder
    import engine  # noqa: PLC0415  (Voice Workbench engine.py)

    voices = [{"id": v["id"], "name": v["name"], "language": v.get("language", "")} for v in engine.burma_cat_voices()]
    print(json.dumps({"ready": True, "voices": voices, "missing": engine.vox_clone_status()["missing"]}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            r = engine.clone_burma_cat(req["text"], model=req.get("model", "pro"), voice_id=req["voice_id"])
            shutil.move(r["path"], req["out"])
            with wave.open(req["out"], "rb") as w:
                seconds = w.getnframes() / w.getframerate()
            print(json.dumps({"ok": True, "seconds": seconds, "backend": r.get("backend"),
                              "elapsed": r.get("elapsed_seconds")}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
