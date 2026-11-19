"""Local LLM / VLM via Ollama's HTTP API (127.0.0.1:11434). No cloud calls."""
from __future__ import annotations

import base64
import functools
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .errors import RecapError

OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA
TIMEOUT = httpx.Timeout(1800.0, connect=10.0)


# when a big model cannot load (VRAM/RAM pressure), retry once, then step down to a smaller one
FALLBACK = {"gemma4:26b": "gemma4:12b", "gemma4:12b": "gemma4:e4b", "qwen3:14b": "qwen3:8b"}


def _post(path: str, payload: dict) -> dict:
    model = payload.get("model")
    tried = 0
    while True:
        try:
            return _post_once(path, payload)
        except RecapError as e:
            if e.code != "out_of_vram" or not model:
                raise
            tried += 1
            if tried == 1:  # transient (another model still unloading): wait and retry same model
                time.sleep(5)
                continue
            nxt = FALLBACK.get(model)
            if not nxt or nxt not in list_models():
                raise
            import logging
            logging.getLogger("recap").warning("LLM %s failed to load; falling back to %s", model, nxt)
            payload = {**payload, "model": nxt}
            model, tried = nxt, 0


def _post_once(path: str, payload: dict) -> dict:
    try:
        r = httpx.post(OLLAMA + path, json=payload, timeout=TIMEOUT)
    except httpx.ConnectError as e:
        raise RecapError("missing_model", "Ollama မဖွင့်ထားပါ။ Ollama app ကို ဖွင့်ပြီး Retry လုပ်ပါ။") from e
    if r.status_code == 404:
        raise RecapError("missing_model", f"Ollama model '{payload.get('model')}' မရှိပါ။ "
                         f"Model Manager မှာ (သို့) `ollama pull {payload.get('model')}` နဲ့ ဒေါင်းပါ။", r.text)
    if r.status_code >= 400:
        txt = r.text
        low = txt.lower()
        if "memory" in low or "cuda error" in low or "process has terminated" in low:
            raise RecapError("out_of_vram", "LLM အတွက် memory မလောက်ပါ။ Settings မှာ qwen3:4b ကို ရွေးပါ။", txt)
        raise RecapError("llm_failed", "LLM ခေါ်တာ မအောင်မြင်ပါ။ Retry လုပ်ပါ။", txt)
    return r.json()


@functools.lru_cache(maxsize=1)
def list_models() -> tuple[str, ...]:
    try:
        r = httpx.get(OLLAMA + "/api/tags", timeout=5)
        return tuple(m["name"] for m in r.json().get("models", []))
    except Exception:
        return ()


@functools.lru_cache(maxsize=32)
def model_caps(name: str) -> tuple[str, ...]:
    try:
        r = httpx.post(OLLAMA + "/api/show", json={"model": name}, timeout=10)
        return tuple(r.json().get("capabilities", []))
    except Exception:
        return ()


def pick_vision_model(preferred: str | None) -> str | None:
    if preferred and preferred.startswith(("or:", "claude:", "oai:")):
        return preferred
    models = list_models()
    if preferred:
        return preferred if preferred in models or any(m.startswith(preferred) for m in models) else None
    # vision captions run on ~60 frames: prefer the fast small model (e4b ~6x faster than 26b)
    order = ["gemma4:e4b", "qwen2.5vl:7b", "qwen2.5vl:3b", "qwen3-vl", "gemma4", "gemma3", "llava", "minicpm-v"]
    for pref in order:
        for m in models:
            if m.startswith(pref) and "vision" in model_caps(m):
                return m
    for m in models:
        if "vision" in model_caps(m):
            return m
    return None


def unload(model: str) -> None:
    if model.startswith(("or:", "claude:", "oai:")):
        return
    try:
        httpx.post(OLLAMA + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def chat(model: str, system: str, user: str, *, json_schema: dict | None = None, temperature: float = 0.6,
         num_ctx: int = 8192, keep_alive: str | int = "5m", images: list[Path] | None = None) -> str:
    if model.startswith("claude:"):  # Claude API (user's Anthropic key)
        from .providers import claude_chat
        txt = claude_chat(model[7:], system, user, json_schema=json_schema, images=images)
        return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    if model.startswith("oai:"):  # OpenAI API (ChatGPT / Codex models, user's key)
        from .providers import openai_chat
        return openai_chat(model[4:], system, user, json_schema=json_schema, images=images)
    if model.startswith("or:"):  # Own-key mode: OpenRouter cloud model
        from .cloud import openrouter_chat
        txt = openrouter_chat(model[3:], system, user, json_schema=json_schema, temperature=temperature, images=images)
        return re.sub(r"<think>.*?</think>", "", txt, flags=re.S).strip()
    msg: dict[str, Any] = {"role": "user", "content": user}
    if images:
        msg["images"] = [base64.b64encode(Path(i).read_bytes()).decode() for i in images]
    payload: dict[str, Any] = {
        "model": model, "stream": False, "keep_alive": keep_alive,
        "messages": [{"role": "system", "content": system}, msg],
        "options": {"temperature": temperature, "num_ctx": num_ctx},
        "think": False,
    }
    if json_schema is not None:
        payload["format"] = json_schema
    try:
        out = _post("/api/chat", payload)
    except RecapError as e:
        if "think" in (e.detail or "") and "not support" in (e.detail or ""):
            payload.pop("think")
            out = _post("/api/chat", payload)
        else:
            raise
    content = out.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


def repair_json(txt: str) -> Any:
    """Truncated output (hit the token limit): cut back to the last complete element and close
    the open brackets. Keeps everything the model finished instead of failing the stage."""
    s = txt[txt.find("{") if "{" in txt else 0:]
    for cut in range(len(s), 0, -1):
        if s[cut - 1] not in "}]\"0123456789el":  # only try at plausible value ends
            continue
        head = s[:cut]
        stack, in_str, esc = [], False, False
        for ch in head:
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            obj = json.loads(head.rstrip().rstrip(",") + "".join(reversed(stack)))
        except json.JSONDecodeError:
            continue
        for v in (obj.values() if isinstance(obj, dict) else [obj]):  # drop a half-written last item
            if isinstance(v, list) and len(v) > 1 and isinstance(v[0], dict) and isinstance(v[-1], dict) \
                    and set(v[-1]) < set(v[0]):
                v.pop()
        return obj
    raise json.JSONDecodeError("unrepairable", txt, 0)


def chat_json(model: str, system: str, user: str, schema: dict, retries: int = 2, **kw) -> Any:
    last = ""
    kw.setdefault("num_ctx", 12288)  # long JSON (story memory / many beats) needs room to finish
    for _ in range(retries + 1):
        txt = chat(model, system, user, json_schema=schema, **kw)
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}|\[.*\]", txt, flags=re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            try:
                return repair_json(txt)
            except json.JSONDecodeError:
                pass
            last = txt
    raise RecapError("llm_failed", "LLM က JSON မှန်မှန် မပြန်ပေးပါ။ Retry လုပ်ပါ (သို့) model ပြောင်းပါ။", last[-2000:])


def caption_image(model: str, image: Path) -> str:
    return chat(model, "You describe film frames for a story editor. One short English sentence.",
                "Describe this drama frame: who is on screen (gender/age/clothing), the action, and the emotion. "
                "Max 25 words. No speculation about names.", images=[image], temperature=0.2,
                num_ctx=4096, keep_alive="2m")
