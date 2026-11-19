"""Optional cloud providers ("Own key" mode). Local mode (Whisper + Ollama) stays the default.

- OpenRouter: LLM for script / translation / post kit. Use llm_model = "or:<model id>",
  e.g. "or:google/gemini-2.5-flash".
- AssemblyAI: Chinese speech-to-text. Use whisper_model = "assemblyai".

Keys are read from env (OPENROUTER_API_KEY / ASSEMBLYAI_API_KEY) or config/api_keys.json,
which is git-ignored and never leaves this PC except to the provider itself.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from .errors import Cancelled, RecapError

KEY_NAMES = ("openrouter", "assemblyai", "anthropic", "openai", "elevenlabs")
KEYS_FILE = Path(__file__).resolve().parents[2] / "config" / "api_keys.json"
OR_URL = "https://openrouter.ai/api/v1"
AAI_URL = "https://api.assemblyai.com/v2"


def load_keys() -> dict[str, str]:
    k = {}
    try:
        k = json.loads(KEYS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        pass
    k.setdefault("openrouter", os.environ.get("OPENROUTER_API_KEY", ""))
    k.setdefault("assemblyai", os.environ.get("ASSEMBLYAI_API_KEY", ""))
    k.setdefault("anthropic", os.environ.get("ANTHROPIC_API_KEY", ""))
    k.setdefault("openai", os.environ.get("OPENAI_API_KEY", ""))
    k.setdefault("elevenlabs", os.environ.get("ELEVENLABS_API_KEY", ""))
    return k


def save_keys(changes: dict[str, str]) -> None:
    k = load_keys()
    for name in KEY_NAMES:
        if name in changes:
            k[name] = (changes[name] or "").strip()
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYS_FILE.write_text(json.dumps(k, indent=2), "utf-8")


def masked() -> dict[str, Any]:
    k = load_keys()
    return {n: {"set": bool(v), "hint": (v[:6] + "…" + v[-4:]) if len(v) > 12 else ("set" if v else "")}
            for n, v in k.items() if n in KEY_NAMES}


def _key(name: str) -> str:
    v = load_keys().get(name, "")
    if not v:
        label = {"openrouter": "OpenRouter", "assemblyai": "AssemblyAI", "anthropic": "Claude (Anthropic)", "openai": "OpenAI",
                 "elevenlabs": "ElevenLabs"}[name]
        raise RecapError("missing_key", f"{label} API key မထည့်ရသေးပါ။ Settings → API Key မှာ ထည့်ပါ။")
    return v


def test_key(name: str) -> dict:
    if name in ("openai", "elevenlabs"):
        from .providers import test
        return test(name)
    try:
        if name == "anthropic":
            import anthropic
            try:
                anthropic.Anthropic(api_key=_key(name), max_retries=0, timeout=20).models.list(limit=1)
                return {"ok": True, "message": "Key အလုပ်လုပ်ပါတယ်"}
            except anthropic.AuthenticationError:
                return {"ok": False, "message": "Key မမှန်ပါ (401)"}
            except anthropic.APIStatusError as e:
                return {"ok": False, "message": f"Key စစ်လို့ မရပါ ({e.status_code})"}
            except anthropic.APIConnectionError:
                return {"ok": False, "message": "Anthropic ကို ချိတ်လို့ မရပါ — internet စစ်ပါ"}
        if name == "openrouter":
            r = httpx.get(f"{OR_URL}/key", headers={"Authorization": f"Bearer {_key(name)}"}, timeout=20)
        else:
            r = httpx.get(f"{AAI_URL}/transcript?limit=1", headers={"authorization": _key(name)}, timeout=20)
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"ချိတ်ဆက်လို့ မရပါ: {e}"}
    except RecapError as e:
        return {"ok": False, "message": e.message_my}
    if r.status_code == 200:
        return {"ok": True, "message": "Key အလုပ်လုပ်ပါတယ်"}
    return {"ok": False, "message": f"Key မမှန်ပါ ({r.status_code})"}


# ------------------------------------------------------------------ OpenRouter LLM
def openrouter_chat(model: str, system: str, user: str, *, json_schema: dict | None = None,
                    temperature: float = 0.6, images: list[Path] | None = None) -> str:
    import base64
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                                                base64.b64encode(Path(i).read_bytes()).decode()}} for i in images]
    body: dict[str, Any] = {"model": model, "temperature": temperature,
                            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
    if json_schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "result", "strict": True, "schema": json_schema}}
    for attempt in range(3):
        try:
            r = httpx.post(f"{OR_URL}/chat/completions", json=body, timeout=600,
                           headers={"Authorization": f"Bearer {_key('openrouter')}", "X-Title": "Drama Recap Studio"})
        except httpx.HTTPError as e:
            if attempt == 2:
                raise RecapError("llm_failed", "OpenRouter ကို ချိတ်လို့ မရပါ။ Internet စစ်ပါ။", str(e)) from e
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code in (429, 502, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 402:
            raise RecapError("llm_failed", "OpenRouter credit မလောက်ပါ။ openrouter.ai မှာ credit ဖြည့်ပါ။", r.text)
        if r.status_code != 200:
            raise RecapError("llm_failed", f"OpenRouter error {r.status_code}", r.text)
        return (r.json()["choices"][0]["message"].get("content") or "").strip()
    raise RecapError("llm_failed", "OpenRouter မအောင်မြင်ပါ။")


# ------------------------------------------------------------------ AssemblyAI ASR
def assemblyai_transcribe(audio: Path, cancel=None, progress=None) -> list[dict]:
    """Chinese transcript as whisper-style segments (sentence level, word timestamps)."""
    key = _key("assemblyai")
    h = {"authorization": key}
    with tempfile.TemporaryDirectory() as td:
        small = Path(td) / "a.flac"  # mono 16 kHz FLAC: ~10x smaller upload than the wav
        from .media import ffmpeg_bin
        subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000", str(small)],
                       check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if progress:
            progress(0.1, "AssemblyAI သို့ အသံ upload လုပ်နေပါတယ်")
        with small.open("rb") as f:
            up = httpx.post(f"{AAI_URL}/upload", headers=h, content=f.read(), timeout=600)
    if up.status_code != 200:
        raise RecapError("asr_failed", f"AssemblyAI upload မအောင်မြင်ပါ ({up.status_code})", up.text)
    job = httpx.post(f"{AAI_URL}/transcript", headers=h, timeout=60,
                     json={"audio_url": up.json()["upload_url"], "language_code": "zh", "punctuate": True,
                           "format_text": True}).json()
    if "id" not in job:
        raise RecapError("asr_failed", "AssemblyAI job မစနိုင်ပါ။", json.dumps(job)[:500])
    t0 = time.time()
    while True:
        if cancel and cancel():
            raise Cancelled()
        st = httpx.get(f"{AAI_URL}/transcript/{job['id']}", headers=h, timeout=60).json()
        if st["status"] == "completed":
            break
        if st["status"] == "error":
            raise RecapError("asr_failed", "AssemblyAI က အသံကို စာမပြောင်းနိုင်ပါ။", st.get("error", ""))
        if progress:
            progress(min(0.9, 0.2 + (time.time() - t0) / 300), "AssemblyAI က စာပြောင်းနေပါတယ်")
        time.sleep(3)
    sents = httpx.get(f"{AAI_URL}/transcript/{job['id']}/sentences", headers=h, timeout=60).json()
    out = []
    for s in sents.get("sentences", []):
        out.append({"start": round(s["start"] / 1000, 3), "end": round(s["end"] / 1000, 3), "text": s["text"].strip(),
                    "source": "assemblyai", "conf": round(float(s.get("confidence", 0.9)), 3),
                    "words": [{"start": round(w["start"] / 1000, 3), "end": round(w["end"] / 1000, 3), "w": w["text"]}
                              for w in s.get("words", [])]})
    return out
