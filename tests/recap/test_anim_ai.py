"""Script -> animation workflow with a fake Claude client (no API calls, no money spent)."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from recap_engine import anim_ai, animation
from recap_engine.errors import RecapError

ROOT_TSX = '''import React from "react";
import { Composition, Still } from "remotion";
import { RockShort, ROCK_FRAMES } from "./videos/rock/Rock";

export const Root: React.FC = () => (
  <>
    <Composition id="RockShort" component={RockShort} durationInFrames={ROCK_FRAMES} fps={30} width={1080} height={1920} />
  </>
);
'''


def _project(tmp_path, monkeypatch):
    r = tmp_path / "shorts"
    rock = r / "src" / "videos" / "rock"
    rock.mkdir(parents=True)
    (r / "src" / "Root.tsx").write_text(ROOT_TSX, "utf-8")
    (rock / "Rock.tsx").write_text('import { RockOverlay } from "./Overlay";\nexport const ROCK_FRAMES = 300;\n'
                                   'export const RockShort = () => null;\n', "utf-8")
    (rock / "story.ts").write_text('import T from "../../../voice_rock/lines_timing.json";\n', "utf-8")
    (rock / "Overlay.tsx").write_text("export const RockOverlay = () => null;\n", "utf-8")
    (rock / "Thumb.tsx").write_text("export const RockThumb = () => null;\n", "utf-8")
    monkeypatch.setattr(animation, "CONFIG", tmp_path / "anim.json")
    animation.set_root(str(r))
    return r


def test_scaffold_renames_and_registers(tmp_path, monkeypatch):
    r = _project(tmp_path, monkeypatch)
    anim_ai.scaffold("temple", "rock")
    d = r / "src" / "videos" / "temple"
    assert (d / "Temple.tsx").exists() and not (d / "Rock.tsx").exists()
    assert "TEMPLE_FRAMES" in (d / "Temple.tsx").read_text() and "TempleOverlay" in (d / "Temple.tsx").read_text()
    assert "voice_temple/lines_timing.json" in (d / "story.ts").read_text()
    root = (r / "src" / "Root.tsx").read_text()
    assert 'id="TempleShort"' in root and 'id="TempleThumb"' in root
    assert root.index("import { TempleShort") < root.index("export const Root")
    assert root.rstrip().endswith(");") and root.index('id="TempleShort"') < root.rindex("</>")
    anim_ai.register("temple")  # idempotent
    assert (r / "src" / "Root.tsx").read_text().count('id="TempleShort"') == 1
    with pytest.raises(RecapError):
        anim_ai.scaffold("temple", "rock")  # already exists
    with pytest.raises(RecapError):
        anim_ai.scaffold("Bad Name", "rock")


def test_generate_loop_with_fake_claude(tmp_path, monkeypatch):
    r = _project(tmp_path, monkeypatch)
    anim_ai.scaffold("temple", "rock")
    (r / "voice_temple" / "lines_timing.json").write_text(json.dumps(
        [{"id": 1, "who": "narrator", "text": "က", "start": 0.15, "end": 2.0}]), "utf-8")
    replies = [
        '<file path="src/videos/temple/story.ts">\nexport const SHOTS = [];\n</file>\n'
        '<file path="src/Root.tsx">\nhacked\n</file>\nsummary',  # outside the short's folder -> must be ignored
        '<file path="src/videos/temple/story.ts">\nexport const SHOTS = [1];\n</file>',
    ]
    calls = []

    class FakeStream:
        def __init__(self, **kw):
            calls.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            txt = replies[min(len(calls) - 1, len(replies) - 1)]
            return NS(content=[NS(type="text", text=txt)], stop_reason="end_turn",
                      usage=NS(input_tokens=1000, output_tokens=2000, cache_creation_input_tokens=20000,
                               cache_read_input_tokens=0))

    fake = NS(beta=NS(messages=NS(stream=lambda **kw: FakeStream(**kw))))
    monkeypatch.setattr(anim_ai, "_client", lambda: fake)
    errs = iter(["src/videos/temple/story.ts(1,1): error TS2304", ""])
    monkeypatch.setattr(anim_ai, "typecheck", lambda key: next(errs, ""))
    task = {"log": [], "message": "", "args": {"title": "Temple"}}
    res = anim_ai.generate("temple", task, "claude-opus-5-5", review=False)
    assert (r / "src" / "videos" / "temple" / "story.ts").read_text().strip() == "export const SHOTS = [1];"
    assert "hacked" not in (r / "src" / "Root.tsx").read_text()
    assert len(calls) == 2 and calls[0]["model"] == "claude-opus-5-5"
    assert calls[0]["thinking"] == {"type": "adaptive"} and calls[0]["fallbacks"] == "default"
    fed = [m for m in calls[1]["messages"] if m["role"] == "user" and isinstance(m["content"], str)]
    assert fed and fed[0]["content"].startswith("tsc --noEmit errors")  # errors fed back to Claude
    assert calls[1]["messages"][1]["role"] == "assistant"  # full first reply kept in the history
    assert res["calls"] == 2 and res["usd"] > 0
    log = json.loads((r / "src" / "videos" / "temple" / "ai_log.json").read_text())
    assert log["model"] == "claude-opus-5-5" and len(log["calls"]) == 2
