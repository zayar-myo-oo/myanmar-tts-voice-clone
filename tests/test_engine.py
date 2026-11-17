"""Engine tests. Unit tests use a fake adapter; the Nara test runs only when models are installed."""
from __future__ import annotations

import shutil

import numpy as np
import pytest
import soundfile as sf

from myanmar_voice_studio.engine import (
    ControlCapability,
    ModelCapabilities,
    Settings,
    Support,
    SynthesisRequest,
    UnsupportedControlError,
    VoiceEngine,
    VoiceProfile,
)

SR = 24000


class FakeAdapter:
    adapter_id = "fake"

    def capabilities(self) -> ModelCapabilities:
        c = ControlCapability
        return ModelCapabilities(
            adapter_id="fake", model_id="fake/model", model_license="test", languages=["my-MM"],
            devices=["cpu"], sample_rate=SR, max_chars=50,
            controls={
                "pause_after": c(name="pause_after", support=Support.ENGINE),
                "pitch": c(name="pitch", support=Support.DSP),
                "emotion": c(name="emotion", support=Support.UNSUPPORTED),
            },
        )

    def speakers(self):
        return ["a"]

    def synthesize(self, text, voice, gap_s):
        t = np.arange(int(SR * 0.5)) / SR
        return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def make_engine() -> VoiceEngine:
    voice = VoiceProfile(voice_id="v1", display_name="Test", adapter_id="fake", speaker="a")
    return VoiceEngine({"v1": voice}, {"fake": FakeAdapter()})


def test_unsupported_controls_are_reported_not_silently_applied(tmp_path):
    result = make_engine().synthesize(
        SynthesisRequest(text="မင်္ဂလာပါ", voice_id="v1", emotion="excited", pause_after_ms=300), tmp_path
    )
    assert result.unsupported == ["emotion=excited"]
    assert any("emotion" in w for w in result.warnings)
    assert [(a.name, a.support) for a in result.applied] == [("pause_after", Support.ENGINE)]


def test_strict_mode_rejects_unsupported_controls(tmp_path):
    with pytest.raises(UnsupportedControlError):
        make_engine().synthesize(
            SynthesisRequest(text="မင်္ဂလာပါ", voice_id="v1", delivery="whisper", strict=True), tmp_path
        )
    assert list(tmp_path.iterdir()) == []  # nothing written


def test_pause_after_extends_audio_and_output_is_new_file(tmp_path):
    engine = make_engine()
    a = engine.synthesize(SynthesisRequest(text="က", voice_id="v1"), tmp_path)
    b = engine.synthesize(SynthesisRequest(text="က", voice_id="v1", pause_after_ms=500), tmp_path)
    assert a.output_path != b.output_path
    assert b.duration_s == pytest.approx(a.duration_s + 0.5, abs=0.01)
    audio, sr = sf.read(b.output_path)
    assert sr == SR and np.abs(audio).max() > 0.5  # peak normalized


@pytest.mark.parametrize(
    "kwargs, message",
    [({"voice_id": "nope"}, "Unknown voice"), ({"text": "မ" * 51}, "exceeds")],
)
def test_validation_errors(tmp_path, kwargs, message):
    req = {"text": "မင်္ဂလာပါ", "voice_id": "v1", **kwargs}
    with pytest.raises(ValueError, match=message):
        make_engine().synthesize(SynthesisRequest(**req), tmp_path)


def test_missing_output_dir_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not exist"):
        make_engine().synthesize(SynthesisRequest(text="က", voice_id="v1"), tmp_path / "missing")


def test_request_rejects_unknown_fields():
    with pytest.raises(ValueError):
        SynthesisRequest(text="က", voice_id="v1", volume=3)


def _nara_ready() -> bool:
    try:
        s = Settings.from_env()
    except RuntimeError:
        return False
    return (s.models_dir / "nara-mini-v1" / "onnx" / "htet-myat" / "encoder.onnx").exists() and bool(
        shutil.which("ffmpeg")
    )


@pytest.mark.skipif(not _nara_ready(), reason="Nara models or ffmpeg not installed")
def test_nara_male_calm_end_to_end(tmp_path):
    pytest.importorskip("onnxruntime")
    engine = VoiceEngine.from_settings()
    caps = engine.capabilities("male_calm")
    assert caps.support_of("emotion", "excited") is Support.DSP
    assert caps.support_of("delivery", "whisper") is Support.UNSUPPORTED
    assert caps.support_of("delivery", "shout") is Support.UNSUPPORTED
    assert caps.support_of("pitch") is Support.DSP
    result = engine.synthesize(SynthesisRequest(text="ကမ္ဘာကြီး တည်ရှိနေတာ ကြာပြီ။", voice_id="male_calm"), tmp_path)
    audio, sr = sf.read(result.output_path)
    assert sr == 24000 and 0.5 < result.duration_s < 10
    assert np.isfinite(audio).all() and np.abs(audio).max() > 0.1


@pytest.mark.skipif(not _nara_ready(), reason="Nara models or ffmpeg not installed")
def test_nara_frontend_fork_has_kambar_fix():
    pytest.importorskip("onnxruntime")
    engine = VoiceEngine.from_settings()
    adapter = engine._adapter(engine.voice("male_calm"))
    assert adapter.phonemize("ကမ္ဘာကြီး").startswith("ɡə ba")


@pytest.mark.skipif(not _nara_ready(), reason="Nara models or ffmpeg not installed")
def test_nara_expression_changes_audio_and_reports_dsp(tmp_path):
    pytest.importorskip("onnxruntime")
    engine = VoiceEngine.from_settings()
    text = "ဒါက အရမ်းကို အံ့ဩစရာ ကောင်းပါတယ်။"
    base = engine.synthesize(SynthesisRequest(text=text, voice_id="female_warm"), tmp_path)
    sad = engine.synthesize(SynthesisRequest(text=text, voice_id="female_warm", emotion="sad"), tmp_path)
    excited = engine.synthesize(SynthesisRequest(text=text, voice_id="female_warm", emotion="excited",
                                                 delivery="whisper"), tmp_path)
    assert [(a.name, a.support) for a in sad.applied] == [("emotion", Support.DSP)]
    assert sad.duration_s > base.duration_s > excited.duration_s  # slower / faster prosody
    assert excited.unsupported == ["delivery=whisper"]


def test_expression_combine_rules():
    from myanmar_voice_studio.engine.expression import combine

    p = combine("excited", "energetic")
    assert p.speed == pytest.approx(1.12 * 1.12) and p.pitch == pytest.approx(3.0)
    assert combine(None, None).speed == 1.0
    assert combine("sad", "soft").lowpass_hz == 6500


@pytest.mark.skipif(not _nara_ready(), reason="Nara models or ffmpeg not installed")
@pytest.mark.parametrize("voice_id", ["male_calm", "female_warm"])
def test_presets_have_no_vocoder_whine(tmp_path, voice_id):
    """Regression: narrow lines at multiples of 1200 Hz (iSTFTNet whine) must not stick out."""
    pytest.importorskip("onnxruntime")
    pytest.importorskip("vocos")
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from tone_scan import scan

    engine = VoiceEngine.from_settings()
    text = "ကမ္ဘာကြီးက တည်ရှိနေတာ ကြာပြီ။ ဒီနေ့ ရာသီဥတု အရမ်း လှပပါတယ်။ မင်းသိလား၊ ဒါက အံ့ဩစရာ ကောင်းတယ်။"
    result = engine.synthesize(SynthesisRequest(text=text, voice_id=voice_id), tmp_path)
    worst = max(d for f, d in scan(str(result.output_path), 1200.0) if f >= 3600)
    assert worst < 3.0, f"whine line {worst:+.1f} dB above neighbourhood"


def test_voices_with_missing_adapter_are_hidden():
    voices = {
        "a": VoiceProfile(voice_id="a", display_name="A", adapter_id="fake", speaker="x"),
        "b": VoiceProfile(voice_id="b", display_name="B", adapter_id="not-installed", speaker="y"),
    }
    engine = VoiceEngine(voices, {"fake": FakeAdapter()})
    assert [v.voice_id for v in engine.list_voices()] == ["a"]
