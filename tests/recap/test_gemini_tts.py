import base64
import io
import wave

import numpy as np

from recap_engine import providers, tts


def _wav(seconds=1.0, sr=24000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.sin(np.arange(int(sr * seconds)) / 8) * 8000).astype("<i2").tobytes())
    return b.getvalue()


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_gemini_tts_request_and_audio(tmp_path, monkeypatch):
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        return _Resp({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/wav", "data": base64.b64encode(_wav(2.0)).decode()}}]}}]})

    monkeypatch.setattr(providers.httpx, "post", fake_post)
    monkeypatch.setattr(providers, "load_keys", lambda: {"gemini": "test-key"})
    out = tmp_path / "a.wav"
    secs = tts.synth_any("မင်္ဂလာပါ", "gem:Kore", out, speed=1.25)
    assert sent["url"].endswith("/models/gemini-3.8-flash-tts:generateContent")
    assert sent["headers"]["x-goog-api-key"] == "test-key"
    assert sent["body"]["generationConfig"]["speechConfig"]["voiceConfig"]["voice"] == "Kore"
    assert sent["body"]["contents"][0]["parts"][0]["text"] == "မင်္ဂလာပါ"
    assert out.exists() and abs(secs - 2.0 / 1.25) < 0.05   # speed applied with atempo


def test_gemini_voices_are_multilingual():
    from recap_engine.server import voice_speaks
    assert all(voice_speaks("gem:Kore", l) for l in ("my", "en", "th"))
    assert len(providers.gemini_voices()) == 30 and tts.is_remote_voice("gem:Puck")
