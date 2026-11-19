"""Claude / OpenAI / ElevenLabs routing with mocked HTTP (no real API calls)."""
from __future__ import annotations

from types import SimpleNamespace as NS

import numpy as np
import pytest
import soundfile as sf

from recap_engine import cloud, llm, providers, tts
from recap_engine.errors import RecapError


@pytest.fixture
def keys(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, "KEYS_FILE", tmp_path / "api_keys.json")
    for k in cloud.KEY_NAMES:
        monkeypatch.delenv({"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                            "elevenlabs": "ELEVENLABS_API_KEY"}.get(k, "X_NONE"), raising=False)
    providers._CACHE.clear()
    return tmp_path


def test_missing_keys_give_clear_burmese_errors(keys):
    with pytest.raises(RecapError) as e:
        llm.chat("oai:gpt-test", "s", "u")
    assert "OpenAI" in e.value.message_my and "Settings" in e.value.message_my
    with pytest.raises(RecapError):
        tts.synth_any("က", "el:abc", keys / "x.wav")


def test_openai_route_sends_schema_and_parses(keys, monkeypatch):
    cloud.save_keys({"openai": "sk-test"})
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=headers["Authorization"])
        return NS(status_code=200, json=lambda: {"choices": [{"message": {"content": '{"a": 1}'}}]}, text="")
    monkeypatch.setattr(providers.httpx, "post", fake_post)
    out = llm.chat_json("oai:gpt-test", "sys", "user", {"type": "object", "properties": {"a": {"type": "number"}}})
    assert out == {"a": 1} and seen["url"].endswith("/chat/completions") and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "gpt-test" and seen["body"]["response_format"]["type"] == "json_schema"


def test_elevenlabs_tts_writes_wav_and_caches(keys, monkeypatch, tmp_path):
    cloud.save_keys({"elevenlabs": "el-test"})
    monkeypatch.setattr(providers, "elevenlabs_model", lambda: "model_x")
    posts = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append((url, json, headers))
        return NS(status_code=200, content=b"mp3", text="")
    monkeypatch.setattr(providers.httpx, "post", fake_post)

    def fake_ff(cmd, **kw):  # stand-in for the mp3 -> wav conversion
        sf.write(cmd[-1], np.zeros(24000, dtype=np.float32) + 0.1, 24000)
    monkeypatch.setattr("recap_engine.media.run", fake_ff)
    r = tts.synth_cached("မင်္ဂလာပါ", "el:VOICE1", tmp_path, "t", 1.1)
    assert posts[0][0].startswith("https://api.elevenlabs.io/v1/text-to-speech/VOICE1")
    assert posts[0][1]["model_id"] == "model_x" and posts[0][2]["xi-api-key"] == "el-test"
    assert r["path"].exists() and not r["cache_hit"]
    assert tts.synth_cached("မင်္ဂလာပါ", "el:VOICE1", tmp_path, "t", 1.1)["cache_hit"]  # no 2nd paid call
    assert len(posts) == 1
