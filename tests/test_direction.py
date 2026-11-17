"""Voice-direction schema and segment renderer tests (fake adapter, no model needed)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import soundfile as sf
from pydantic import ValidationError

from myanmar_voice_studio.engine import UnsupportedControlError, VoiceEngine, VoiceProfile
from myanmar_voice_studio.engine.direction import VoiceDirection, json_schema
from myanmar_voice_studio.engine.renderer import preview, render, segment_request

from test_engine import SR, FakeAdapter

ROOT = Path(__file__).resolve().parents[1]


def engine() -> VoiceEngine:
    voices = {
        "v1": VoiceProfile(voice_id="v1", display_name="One", adapter_id="fake", speaker="a"),
        "v2": VoiceProfile(voice_id="v2", display_name="Two", adapter_id="fake", speaker="a"),
    }
    return VoiceEngine(voices, {"fake": FakeAdapter()})


def doc(**overrides) -> VoiceDirection:
    base = {
        "voice_id": "v1",
        "global_settings": {"pause_scale": 2.0, "pitch": 1.0},
        "segments": [
            {"id": "s1", "text": "မင်းသိလား", "emotion": "curious", "pause_after_ms": 250},
            {"id": "s2", "text": "ဟုတ်တယ်", "voice_id": "v2", "pitch": 0.5},
        ],
    }
    base.update(overrides)
    return VoiceDirection.model_validate(base)


def test_example_file_validates():
    data = json.loads((ROOT / "schemas" / "examples" / "stickman-story.json").read_text(encoding="utf-8"))
    assert VoiceDirection.model_validate(data).segments[0].id == "segment_001"


def test_exported_schema_file_is_current():
    exported = json.loads((ROOT / "schemas" / "voice-direction-1.0.json").read_text(encoding="utf-8"))
    assert exported == json_schema(), "run: mvs-speak schema > schemas/voice-direction-1.0.json"


@pytest.mark.parametrize(
    "bad",
    [
        {"segments": []},
        {"schema_version": "2.0"},
        {"segments": [{"id": "a", "text": "က"}, {"id": "a", "text": "ခ"}]},
        {"segments": [{"id": "a", "text": "   "}]},
        {"segments": [{"id": "a b", "text": "က"}]},
        {"segments": [{"id": "a", "text": "က", "emotion": "furious"}]},
        {"surprise": 1},
    ],
)
def test_invalid_documents_are_rejected(bad):
    with pytest.raises(ValidationError):
        doc(**bad)


def test_segment_request_merges_global_settings():
    d = doc()
    r1, r2 = (segment_request(d, s) for s in d.segments)
    assert r1.pause_after_ms == 500  # 250 * pause_scale 2.0
    assert r1.pitch_semitones == 1.0 and r1.emotion == "curious"
    assert r2.voice_id == "v2" and r2.pitch_semitones == 1.5


def test_preview_reports_unsupported_per_segment_and_strict_refuses():
    plan = preview(engine(), doc())
    assert plan.segments[0].unsupported == ["emotion=curious"]
    assert plan.unsupported_total == 1
    with pytest.raises(UnsupportedControlError):
        preview(engine(), doc(), strict=True)


def test_preview_rejects_unknown_voice():
    with pytest.raises(ValueError, match="Unknown voice"):
        preview(engine(), doc(voice_id="missing"))


def test_render_joins_segments_with_timings_and_report(tmp_path):
    result = render(engine(), doc(), tmp_path, write_segments=True)
    audio, sr = sf.read(result.output_path)
    assert sr == SR
    s1, s2 = result.segments
    assert s1.start_s == 0 and s2.start_s == s1.end_s
    assert s1.end_s == pytest.approx(0.5 + 0.5, abs=0.01)  # 0.5 s audio + 0.5 s pause
    assert result.duration_s == pytest.approx(len(audio) / sr, abs=0.001)
    assert s1.segment_path and s1.segment_path.exists()
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["segments"][0]["unsupported"] == ["emotion=curious"]
    assert report["direction"]["voice_id"] == "v1"


def test_render_strict_writes_nothing(tmp_path):
    with pytest.raises(UnsupportedControlError):
        render(engine(), doc(), tmp_path, strict=True)
    assert list(tmp_path.iterdir()) == []
