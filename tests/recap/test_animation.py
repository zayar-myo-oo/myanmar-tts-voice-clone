"""Animation tab: discovery of a Remotion shorts project and voice.wav + lines_timing.json building."""
from __future__ import annotations

import json

import numpy as np
import soundfile as sf

from recap_engine import animation, tts


def _fake_project(tmp_path):
    r = tmp_path / "shorts"
    (r / "src" / "videos" / "demo").mkdir(parents=True)
    (r / "src" / "Root.tsx").write_text('<Composition id="DemoShort" component={X} />\n<Still id="DemoThumb" />', "utf-8")
    (r / "src" / "videos" / "demo" / "story.ts").write_text('import T from "../../../voice_demo/lines_timing.json";', "utf-8")
    (r / "voice_demo").mkdir()
    (r / "public" / "demo").mkdir(parents=True)
    (r / "public" / "demo" / "voice.wav").write_bytes(b"")
    return r


def test_discover_and_build_voice(tmp_path, monkeypatch):
    r = _fake_project(tmp_path)
    monkeypatch.setattr(animation, "CONFIG", tmp_path / "anim.json")
    animation.set_root(str(r))
    d = animation.discover()
    s = d["shorts"][0]
    assert (s["key"], s["id"], s["thumb_id"], s["voice_dir"]) == ("demo", "DemoShort", "DemoThumb", "voice_demo")
    animation.save_lines("demo", [{"who": "narrator", "text": "မင်္ဂလာပါ", "gapAfter": 0.5},
                                  {"who": "kid", "text": "ဟုတ်လား", "gapAfter": 0.3}], {"narrator": "male_calm"})

    def fake_synth(text, voice, out, speed=1.0):  # 1 s tone with silence around it
        x = np.concatenate([np.zeros(4800), 0.3 * np.sin(np.arange(24000) * 2 * np.pi * 220 / 24000), np.zeros(4800)])
        sf.write(str(out), x.astype(np.float32), 24000)
        return len(x) / 24000
    monkeypatch.setattr(tts, "synth_any", fake_synth)
    res = animation.build_voice("demo", {"narrator": "male_calm", "kid": "female_warm"})
    timing = json.loads((r / "voice_demo" / "lines_timing.json").read_text("utf-8"))
    assert res["lines"] == 2 and timing[0]["start"] == 0.15
    assert abs((timing[0]["end"] - timing[0]["start"]) - 1.08) < 0.03  # silence trimmed to 40 ms each side
    assert abs(timing[1]["start"] - (timing[0]["end"] + 0.5)) < 1e-3  # gapAfter honoured
    x, sr = sf.read(str(r / "voice_demo" / "voice.wav"))
    assert sr == 48000 and x.ndim == 1 and abs(np.abs(x).max() - 0.89) < 0.01
    assert (r / "public" / "demo" / "voice.wav").stat().st_size > 1000  # public copy refreshed for shorts that play it
