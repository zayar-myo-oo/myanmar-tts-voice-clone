"""Paid API providers the user can plug in (own keys, stored in config/api_keys.json):

  * Claude (Anthropic SDK)       llm_model "claude:<model id>"  - script / translation / post kit
                                  (animation scene code: anim_ai.py)
  * OpenAI (ChatGPT / Codex)     llm_model "oai:<model id>"     - script / translation / post kit
  * ElevenLabs                   voice_id  "el:<voice id>"      - narration / dub / voiceover voices

Model and voice lists come live from each service (cached 10 min), so nothing here hardcodes a
model name that may not exist on the user's account.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from .cloud import load_keys
from .errors import RecapError

_CACHE: dict[str, tuple[float, Any]] = {}
OAI = "https://api.openai.com/v1"
EL = "https://api.elevenlabs.io/v1"


def _cached(name: str, fn, ttl: float = 600):
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[name] = (time.time(), val)
    return val


def _key(name: str, label: str) -> str:
    k = load_keys().get(name, "")
    if not k:
        raise RecapError("missing_key", f"{label} API key မထည့်ရသေးပါ။ Settings → ☁ Cloud / API Key မှာ ထည့်ပါ။")
    return k


# ------------------------------------------------------------------ Claude
def claude_models() -> list[str]:
    def f():
        import anthropic
        c = anthropic.Anthropic(api_key=_key("anthropic", "Claude"), max_retries=1, timeout=20)
        return [m.id for m in c.models.list(limit=50)]
    return _cached("claude_models", f)


def claude_chat(model: str, system: str, user: str, *, json_schema: dict | None = None,
                images: list[Path] | None = None) -> str:
    import base64

    import anthropic
    c = anthropic.Anthropic(api_key=_key("anthropic", "Claude"), timeout=900)
    content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(Path(i).read_bytes()).decode()}}
                           for i in (images or [])]
    sys_txt = system + ("\n\nReply with only a JSON object matching this schema, no other text:\n"
                        + __import__("json").dumps(json_schema, ensure_ascii=False) if json_schema else "")
    content.append({"type": "text", "text": user})
    try:
        with c.messages.stream(model=model, max_tokens=32000, system=sys_txt,
                               messages=[{"role": "user", "content": content}],
                               output_config={"effort": "medium"}) as s:
            resp = s.get_final_message()
    except anthropic.AuthenticationError as e:
        raise RecapError("missing_key", "Claude API key မမှန်ပါ။") from e
    except anthropic.RateLimitError as e:
        raise RecapError("llm_failed", "Claude API rate limit — ခဏနေမှ ပြန်စမ်းပါ။", str(e)) from e
    except anthropic.APIStatusError as e:
        raise RecapError("llm_failed", f"Claude API error {e.status_code}", str(e)) from e
    except anthropic.APIConnectionError as e:
        raise RecapError("llm_failed", "Claude API ကို ချိတ်လို့ မရပါ — internet စစ်ပါ။", str(e)) from e
    if resp.stop_reason == "refusal":
        raise RecapError("llm_failed", "Claude က ဒီ request ကို ငြင်းပါတယ် (refusal)။")
    return "".join(b.text for b in resp.content if b.type == "text").strip()


# ------------------------------------------------------------------ OpenAI (ChatGPT / Codex)
def openai_models() -> list[str]:
    def f():
        r = httpx.get(f"{OAI}/models", headers={"Authorization": f"Bearer {_key('openai', 'OpenAI')}"}, timeout=20)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        keep = [i for i in ids if i.startswith(("gpt-", "o", "codex", "chatgpt")) and not any(
            x in i for x in ("audio", "realtime", "transcribe", "tts", "image", "embedding", "moderation", "search"))]
        return sorted(keep, reverse=True)
    return _cached("openai_models", f)


def openai_chat(model: str, system: str, user: str, *, json_schema: dict | None = None,
                images: list[Path] | None = None) -> str:
    import base64
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                                                base64.b64encode(Path(i).read_bytes()).decode()}} for i in images]
    body: dict[str, Any] = {"model": model, "messages": [{"role": "system", "content": system},
                                                         {"role": "user", "content": content}]}
    if json_schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "result", "schema": json_schema, "strict": False}}
    for attempt in range(3):
        try:
            r = httpx.post(f"{OAI}/chat/completions", json=body, timeout=600,
                           headers={"Authorization": f"Bearer {_key('openai', 'OpenAI')}"})
        except httpx.HTTPError as e:
            if attempt == 2:
                raise RecapError("llm_failed", "OpenAI ကို ချိတ်လို့ မရပါ — internet စစ်ပါ။", str(e)) from e
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise RecapError("missing_key", "OpenAI API key မမှန်ပါ။")
        if r.status_code == 429:
            raise RecapError("llm_failed", "OpenAI quota / rate limit ပြည့်နေပါတယ် (billing စစ်ပါ)။", r.text)
        if r.status_code != 200:
            raise RecapError("llm_failed", f"OpenAI error {r.status_code}", r.text[:1000])
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    raise RecapError("llm_failed", "OpenAI မအောင်မြင်ပါ။")


# ------------------------------------------------------------------ ElevenLabs
def _el_headers() -> dict:
    return {"xi-api-key": _key("elevenlabs", "ElevenLabs")}


def elevenlabs_voices() -> list[dict]:
    def f():
        r = httpx.get(f"{EL}/voices", headers=_el_headers(), timeout=30)
        r.raise_for_status()
        return [{"id": "el:" + v["voice_id"], "name": v.get("name", v["voice_id"]),
                 "category": v.get("category", ""), "labels": v.get("labels") or {},
                 "preview": v.get("preview_url")} for v in r.json().get("voices", [])]
    return _cached("el_voices", f)


def elevenlabs_models() -> list[dict]:
    def f():
        r = httpx.get(f"{EL}/models", headers=_el_headers(), timeout=30)
        r.raise_for_status()
        out = []
        for m in r.json():
            if not m.get("can_do_text_to_speech"):
                continue
            langs = [l.get("language_id") for l in m.get("languages", [])]
            out.append({"id": m["model_id"], "name": m.get("name", m["model_id"]), "burmese": "my" in langs,
                        "languages": len(langs)})
        return out
    return _cached("el_models", f)


def elevenlabs_model() -> str:
    """Saved choice, else the first model that lists Burmese, else the first multilingual one."""
    from .cloud import KEYS_FILE
    import json
    try:
        m = json.loads(KEYS_FILE.with_name("app_settings.json").read_text("utf-8")).get("el_model")
        if m:
            return m
    except (OSError, ValueError):
        pass
    ms = elevenlabs_models()
    pick = next((m for m in ms if m["burmese"]), None) or max(ms, key=lambda m: m["languages"], default=None)
    if not pick:
        raise RecapError("tts_failed", "ElevenLabs မှာ text-to-speech model မတွေ့ပါ။")
    return pick["id"]


def elevenlabs_tts(text: str, voice_id: str, out: Path, speed: float = 1.0) -> float:
    from .media import audio_duration, ffmpeg_bin, run as ff_run
    vid = voice_id.split(":", 1)[1]
    body = {"text": text, "model_id": elevenlabs_model(),
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": max(0.7, min(1.2, speed))}}
    for attempt in range(3):
        try:
            r = httpx.post(f"{EL}/text-to-speech/{vid}?output_format=mp3_44100_128", json=body,
                           headers=_el_headers(), timeout=180)
        except httpx.HTTPError as e:
            if attempt == 2:
                raise RecapError("tts_failed", "ElevenLabs ကို ချိတ်လို့ မရပါ — internet စစ်ပါ။", str(e)) from e
            time.sleep(3)
            continue
        if r.status_code == 429 and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise RecapError("missing_key", "ElevenLabs API key မမှန်ပါ။")
        if r.status_code != 200:
            msg = "ElevenLabs credit ကုန်နေပါပြီ။" if "quota" in r.text.lower() else f"ElevenLabs error {r.status_code}"
            raise RecapError("tts_failed", msg, r.text[:800])
        mp3 = out.with_suffix(".el.mp3")
        mp3.write_bytes(r.content)
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(mp3), "-ar", "24000", "-ac", "1", str(out)])
        mp3.unlink(missing_ok=True)
        return audio_duration(out)
    raise RecapError("tts_failed", "ElevenLabs မအောင်မြင်ပါ။")


# ------------------------------------------------------------------ key tests + summary
def test(name: str) -> dict:
    try:
        if name == "openai":
            _CACHE.pop("openai_models", None)
            n = len(openai_models())
            return {"ok": True, "message": f"Key အလုပ်လုပ်ပါတယ် · model {n} ခု"}
        if name == "elevenlabs":
            _CACHE.pop("el_voices", None)
            r = httpx.get(f"{EL}/user/subscription", headers=_el_headers(), timeout=20)
            if r.status_code == 401:
                return {"ok": False, "message": "Key မမှန်ပါ (401)"}
            r.raise_for_status()
            s = r.json()
            left = (s.get("character_limit") or 0) - (s.get("character_count") or 0)
            return {"ok": True, "message": f"Key အလုပ်လုပ်ပါတယ် · {s.get('tier', '')} · စာလုံး {left:,} ကျန်"}
    except RecapError as e:
        return {"ok": False, "message": e.message_my}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "message": f"Key မမှန်ပါ ({e.response.status_code})"}
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"ချိတ်ဆက်လို့ မရပါ: {e}"}
    return {"ok": False, "message": "unknown provider"}


def summary() -> dict:
    keys = load_keys()
    out: dict[str, Any] = {}
    for name, fn in (("claude", claude_models), ("openai", openai_models)):
        k = "anthropic" if name == "claude" else name
        out[name] = {"set": bool(keys.get(k)), "models": []}
        if keys.get(k):
            try:
                out[name]["models"] = fn()
            except Exception as e:  # noqa: BLE001
                out[name]["error"] = str(e)[:200]
    out["elevenlabs"] = {"set": bool(keys.get("elevenlabs")), "voices": [], "models": []}
    if keys.get("elevenlabs"):
        try:
            out["elevenlabs"]["voices"] = elevenlabs_voices()
            out["elevenlabs"]["models"] = elevenlabs_models()
        except Exception as e:  # noqa: BLE001
            out["elevenlabs"]["error"] = str(e)[:200]
    return out
