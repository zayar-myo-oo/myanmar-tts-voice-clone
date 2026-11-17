"""Command line front end for the voice engine.

    mvs-speak voices
    mvs-speak caps male_calm
    mvs-speak say male_calm "မင်္ဂလာပါ" --out outputs/engine
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import VoiceEngine
from .schemas import SynthesisRequest, UnsupportedControlError


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="mvs-speak")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("voices", help="list voice profiles")
    caps = sub.add_parser("caps", help="show capabilities for a voice")
    caps.add_argument("voice")
    say = sub.add_parser("say", help="synthesize text")
    say.add_argument("voice")
    say.add_argument("text", nargs="?", help="text; or use --text-file")
    say.add_argument("--text-file", type=Path)
    say.add_argument("--out", type=Path, required=True, help="existing output directory")
    say.add_argument("--speed", type=float, default=1.0)
    say.add_argument("--pitch", type=float, default=0.0)
    say.add_argument("--emotion")
    say.add_argument("--delivery")
    say.add_argument("--pause-after-ms", type=int, default=0)
    say.add_argument("--strict", action="store_true")
    for name, help_text in (("preview", "validate a direction JSON and show the plan (no audio)"),
                            ("render", "render a direction JSON to one WAV + report")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("direction", type=Path, help="voice-direction JSON file (schema 1.0)")
        cmd.add_argument("--strict", action="store_true")
        if name == "render":
            cmd.add_argument("--out", type=Path, required=True, help="existing output directory")
            cmd.add_argument("--segments", action="store_true", help="also write one WAV per segment")
    sub.add_parser("schema", help="print the voice-direction JSON Schema")
    args = parser.parse_args(argv)

    if args.cmd == "schema":
        from .direction import json_schema
        print(json.dumps(json_schema(), ensure_ascii=False, indent=2))
        return 0

    engine = VoiceEngine.from_settings()
    if args.cmd == "voices":
        for v in engine.list_voices():
            print(f"{v.voice_id}\t{v.display_name}\t{v.adapter_id}:{v.speaker}")
        return 0
    if args.cmd == "caps":
        print(engine.capabilities(args.voice).model_dump_json(indent=2))
        return 0

    if args.cmd in ("preview", "render"):
        from pydantic import ValidationError

        from .direction import VoiceDirection
        from .renderer import preview, render
        try:
            doc = VoiceDirection.model_validate_json(args.direction.read_text(encoding="utf-8"))
        except ValidationError as exc:
            print(f"error: invalid direction file:\n{exc}", file=sys.stderr)
            return 2
        try:
            if args.cmd == "preview":
                out = preview(engine, doc, strict=args.strict)
            else:
                out = render(engine, doc, args.out, strict=args.strict, write_segments=args.segments)
        except (UnsupportedControlError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(json.loads(out.model_dump_json()), ensure_ascii=False, indent=2))
        return 0

    text = args.text_file.read_text(encoding="utf-8") if args.text_file else args.text
    if not text:
        parser.error("provide text or --text-file")
    request = SynthesisRequest(
        text=text, voice_id=args.voice, speed=args.speed, pitch_semitones=args.pitch,
        emotion=args.emotion, delivery=args.delivery, pause_after_ms=args.pause_after_ms, strict=args.strict,
    )
    try:
        result = engine.synthesize(request, args.out)
    except UnsupportedControlError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(json.loads(result.model_dump_json()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
