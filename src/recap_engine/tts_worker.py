"""Runs inside the voice-studio venv (.venv-nara). Keeps the Nara engine loaded and
serves JSON-lines requests on stdin:  {"text","voice_id","speed","out"} -> {"ok","seconds"}.

This is the adapter to the existing aivoiceclone renderer; it imports only
myanmar_voice_studio so the recap venv never needs the TTS dependencies.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    import soundfile as sf
    from myanmar_voice_studio.engine.engine import VoiceEngine
    from myanmar_voice_studio.engine.schemas import SynthesisRequest

    engine = VoiceEngine.from_settings()
    print(json.dumps({"ready": True, "voices": [v.voice_id for v in engine.list_voices()]}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            r = SynthesisRequest(text=req["text"], voice_id=req["voice_id"], speed=float(req.get("speed", 1.0)))
            wav, sr, *_ = engine.render(r)
            sf.write(req["out"], wav, sr, subtype="PCM_16")
            print(json.dumps({"ok": True, "seconds": len(wav) / sr, "sr": sr}), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
