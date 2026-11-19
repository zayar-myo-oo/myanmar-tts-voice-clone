"""Script -> animation: the scene code of a new cartoon short is written by Claude through the Claude API
(the user's own Anthropic key), checked locally, and fixed in a loop:

  1. scaffold   copy a template short (rock / jump / pagoda), rename its identifiers, register it in Root.tsx
  2. generate   Claude rewrites story.ts / cast.ts / world.ts / Overlay.tsx / Thumb.tsx for the new script,
                with the skill rules (SKILL.md) and the template code as cached context
  3. typecheck  `tsc --noEmit`; errors go back to Claude (up to 3 rounds)
  4. review     3 stills are rendered and shown to Claude; it answers LOOKS_GOOD or sends fixed files (1 round)

Only files inside src/videos/<key>/ are ever written from Claude's output. Every call's token use and cost are
logged to src/videos/<key>/ai_log.json.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import animation
from .errors import RecapError

TEMPLATES = {"rock": "Rock", "jump": "Jump", "pagoda": "Pagoda"}
PRICES = {  # $ per 1M tokens: input, output, cache write (5 min), cache read
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.10),
}
SKILL_CANDIDATES = [Path.home() / ".claude" / "skills" / "cartoon-3d-short" / "SKILL.md"]
FILE_RE = re.compile(r'<file path="([^"]+)">\r?\n(.*?)\r?\n</file>', re.S)


def _pascal(key: str) -> str:
    return key[:1].upper() + key[1:]


def skill_text(R: Path) -> str:
    for p in [R.parent / "claude-animated-shorts" / "SKILL.md", *SKILL_CANDIDATES]:
        if p.exists():
            return p.read_text("utf-8", errors="ignore")
    return ""


# ------------------------------------------------------------------ 1. scaffold
def scaffold(key: str, template: str = "rock") -> dict[str, Any]:
    R = animation.root()
    if not re.fullmatch(r"[a-z][a-z0-9]{1,23}", key):
        raise RecapError("anim_key", "နာမည်ကို English အက္ခရာ အသေး/ဂဏန်း (၂–၂၄ လုံး) နဲ့ ပေးပါ (ဥပမာ: shwedagon)။")
    if template not in TEMPLATES:
        raise RecapError("anim_tpl", "Template မရှိပါ။")
    src, dst = R / "src" / "videos" / template, R / "src" / "videos" / key
    if dst.exists():
        raise RecapError("anim_exists", f"'{key}' ရှိပြီးသား ဖြစ်နေပါတယ်။ နာမည်အသစ် ပေးပါ။")
    T, P = TEMPLATES[template], _pascal(key)
    swaps = [(f"{T}Short", f"{P}Short"), (f"{T}Overlay", f"{P}Overlay"), (f"{T}Thumb", f"{P}Thumb"),
             (f"{T}Avatar", f"{P}Avatar"), (f"{template.upper()}_FRAMES", f"{key.upper()}_FRAMES"),
             (f"voice_{template}/", f"voice_{key}/"), (f"{template}_mix", f"{key}_mix")]
    if template == "pagoda":
        swaps.append(("../../../voice/lines_timing.json", f"../../../voice_{key}/lines_timing.json"))
    dst.mkdir(parents=True)
    for f in src.iterdir():
        if not f.is_file() or f.suffix not in (".ts", ".tsx"):
            continue
        txt = f.read_text("utf-8")
        for a, b in swaps:
            txt = txt.replace(a, b)
        name = f"{P}.tsx" if f.name == f"{T}.tsx" else f.name
        (dst / name).write_text(txt, "utf-8")
    vd = R / f"voice_{key}"
    vd.mkdir(exist_ok=True)
    (R / "out" / key).mkdir(parents=True, exist_ok=True)
    register(key)
    return {"key": key, "dir": f"src/videos/{key}", "voice_dir": f"voice_{key}"}


def register(key: str) -> None:
    """Add the composition (+ thumbnail still) to src/Root.tsx (once)."""
    R = animation.root()
    rt = R / "src" / "Root.tsx"
    P, U = _pascal(key), key.upper()
    txt = rt.read_text("utf-8")
    if f'id="{P}Short"' in txt:
        return
    has_thumb = (R / "src" / "videos" / key / "Thumb.tsx").exists()
    imp = f'import {{ {P}Short, {U}_FRAMES }} from "./videos/{key}/{P}";\n'
    if has_thumb:
        imp += f'import {{ {P}Thumb }} from "./videos/{key}/Thumb";\n'
    last = list(re.finditer(r"^import .*;\s*$", txt, re.M))[-1]
    txt = txt[:last.end()] + "\n" + imp + txt[last.end():]
    comp = (f'    <Composition id="{P}Short" component={{{P}Short}} durationInFrames={{{U}_FRAMES}} fps={{30}} '
            f'width={{1080}} height={{1920}} />\n')
    if has_thumb:
        comp += f'    <Still id="{P}Thumb" component={{{P}Thumb}} width={{1080}} height={{1920}} />\n'
    i = txt.rindex("</>")
    line_start = txt.rfind("\n", 0, i) + 1  # insert before the line that closes the fragment
    txt = txt[:line_start] + comp + txt[line_start:]
    rt.write_text(txt, "utf-8")


# ------------------------------------------------------------------ 2-4. Claude loop
class Cost:
    def __init__(self, model: str):
        self.model, self.calls, self.usd = model, [], 0.0

    def add(self, usage: Any, label: str) -> float:
        pi, po, pw, pr = PRICES.get(self.model, PRICES["claude-opus-5-5"])
        i = getattr(usage, "input_tokens", 0) or 0
        o = getattr(usage, "output_tokens", 0) or 0
        w = getattr(usage, "cache_creation_input_tokens", 0) or 0
        r = getattr(usage, "cache_read_input_tokens", 0) or 0
        usd = (i * pi + o * po + w * pw + r * pr) / 1e6
        self.usd += usd
        self.calls.append({"step": label, "input": i, "output": o, "cache_write": w, "cache_read": r,
                           "usd": round(usd, 4)})
        return usd


def _client():
    import anthropic
    from .cloud import load_keys
    k = load_keys().get("anthropic")
    if not k:
        raise RecapError("missing_key", "Claude API key မထည့်ရသေးပါ။ Settings → ☁ Cloud / API Key မှာ ထည့်ပါ။")
    return anthropic.Anthropic(api_key=k, timeout=900)


def _ask(client, model: str, system: list, messages: list, cost: Cost, label: str, log: Callable[[str], None]):
    import anthropic
    t0 = time.time()
    try:
        with client.beta.messages.stream(
            model=model, max_tokens=64000, system=system, messages=messages,
            thinking={"type": "adaptive"}, output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        ) as stream:
            resp = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise RecapError("missing_key", "Claude API key မမှန်ပါ။ Settings မှာ ပြန်စစ်ပါ။") from e
    except anthropic.PermissionDeniedError as e:
        raise RecapError("llm_failed", "ဒီ key နဲ့ ဒီ model သုံးခွင့် မရှိပါ။", str(e)) from e
    except anthropic.RateLimitError as e:
        raise RecapError("llm_failed", "Claude API rate limit — ခဏနေမှ ပြန်စမ်းပါ။", str(e)) from e
    except anthropic.APIStatusError as e:
        if e.status_code == 400 and "credit" in str(e).lower():
            raise RecapError("llm_failed", "Anthropic account မှာ credit မလောက်ပါ (console.anthropic.com → Billing)။",
                             str(e)) from e
        raise RecapError("llm_failed", f"Claude API error {e.status_code}", str(e)) from e
    except anthropic.APIConnectionError as e:
        raise RecapError("llm_failed", "Claude API ကို ချိတ်လို့ မရပါ — internet စစ်ပါ။", str(e)) from e
    usd = cost.add(resp.usage, label)
    log(f"[{label}] {time.time() - t0:.0f}s · in {resp.usage.input_tokens} (cache read "
        f"{resp.usage.cache_read_input_tokens or 0}) · out {resp.usage.output_tokens} · ${usd:.3f} · {resp.stop_reason}")
    if resp.stop_reason == "refusal":
        raise RecapError("llm_failed", "Claude က ဒီ request ကို မလုပ်ပေးနိုင်ဘူးလို့ ငြင်းပါတယ် (refusal)။")
    if resp.stop_reason == "max_tokens":
        raise RecapError("llm_failed", "Claude ရဲ့ အဖြေ ရှည်လွန်းလို့ ပြတ်သွားပါတယ်။ Script ကို တိုပြီး ပြန်စမ်းပါ။")
    messages.append({"role": "assistant", "content": resp.content})  # keep full content (thinking blocks) for follow-ups
    return "".join(b.text for b in resp.content if b.type == "text")


def _apply(text: str, key: str, log) -> list[str]:
    """Write the <file path=...> blocks, but only inside src/videos/<key>/."""
    R = animation.root()
    base = (R / "src" / "videos" / key).resolve()
    written = []
    for path, body in FILE_RE.findall(text):
        f = (R / path.strip()).resolve()
        if base not in f.parents or f.suffix not in (".ts", ".tsx"):
            log(f"  skip (outside src/videos/{key}): {path}")
            continue
        f.write_text(body.rstrip() + "\n", "utf-8")
        written.append(f.name)
    return written


def typecheck(key: str) -> str:
    """tsc errors for this short only ('' when clean)."""
    R = animation.root()
    r = subprocess.run([animation._npx(), "tsc", "--noEmit", "-p", "."], cwd=str(R), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=animation.NO_WINDOW, timeout=900)
    errs = [ln for ln in (r.stdout + r.stderr).splitlines() if f"videos/{key}/" in ln.replace("\\", "/")
            or "Root.tsx" in ln]
    return "\n".join(errs[:60])


def _stills(key: str, comp: str, frames: list[int], task: dict) -> list[Path]:
    R = animation.root()
    out = []
    for fr in frames:
        f = f"out/{key}/ai_still_{fr}.jpg"
        animation._run(task, [animation._npx(), "remotion", "still", "src/index.ts", comp, f, f"--frame={fr}",
                              "--gl=angle", "--scale=0.5"], R, label=f"Still {fr}")
        out.append(R / f)
    return out


def generate(key: str, task: dict, model: str = "claude-opus-5-5", review: bool = True) -> dict:
    R = animation.root()
    d = R / "src" / "videos" / key
    P = _pascal(key)
    log = lambda m: (task["log"].append(m), task.__setitem__("message", m[:120]))
    timing = json.loads((R / f"voice_{key}" / "lines_timing.json").read_text("utf-8"))
    files = sorted(p for p in d.iterdir() if p.suffix in (".ts", ".tsx"))
    tpl = "\n\n".join(f'<file path="src/videos/{key}/{p.name}">\n{p.read_text("utf-8")}\n</file>' for p in files)
    skill = skill_text(R)
    system = [{"type": "text", "cache_control": {"type": "ephemeral"}, "text":
               "You write the scene code for one short animated story video in an existing Remotion + three.js project "
               "('2D flat characters in a colourful 3D toon world'). Follow the project skill below. Keep everything the "
               "main component file imports and uses working; reuse the shared look modules under ../bridge/ exactly as "
               "the template does; use only packages already imported in the template. Never invent asset files: use "
               "only props/kit pieces the template already loads, or simple three.js geometry.\n\n"
               "Output format: every file you change, complete, as\n<file path=\"src/videos/" + key + "/NAME\">\n...full "
               "file...\n</file>\nFiles you don't change: omit. After the files, at most 3 short lines of summary.\n\n"
               "=== PROJECT SKILL (SKILL.md) ===\n" + (skill or "(skill file not found - follow the template)")}]
    lines_txt = "\n".join(f"{t['id']}. [{t['who']}] {t['start']:.2f}-{t['end']:.2f}s: {t['text']}" for t in timing)
    messages = [{"role": "user", "content": [
        {"type": "text", "cache_control": {"type": "ephemeral"},
         "text": f"Template files, already copied to src/videos/{key}/ and renamed ({P}Short, {key.upper()}_FRAMES, "
                 f"voice_{key}/lines_timing.json):\n\n{tpl}"},
        {"type": "text", "text":
         f"New short: '{task['args'].get('title', key)}'.\nThe voice is already built; story.ts imports its timing from "
         f"voice_{key}/lines_timing.json ({len(timing)} lines, keep the import). Lines (speaker, start-end, Burmese "
         f"text):\n{lines_txt}\n\nSpeakers: {', '.join(sorted({t['who'] for t in timing}))}.\n"
         f"Notes from the user: {task['args'].get('notes') or '-'}\n\n"
         "Rewrite story.ts (one shot per line, each starting 6 frames before its line like the template; cameras and "
         "staging that show what the line says), cast.ts (one character per speaker; narrator may be off-screen), "
         "world.ts (a setting that fits the topic), Overlay.tsx (2D inserts that explain the facts, or none) and "
         f"Thumb.tsx (title card). Edit {P}.tsx only if needed. Make it compile under the project's tsconfig."}]}]
    client = _client()
    cost = Cost(model)
    written = _apply(_ask(client, model, system, messages, cost, "write", log), key, log)
    log(f"  wrote: {', '.join(written) or '(none)'}")
    if not written:
        raise RecapError("anim_ai", "Claude က code ဖိုင် မပြန်ပေးပါ။ Log ကို ကြည့်ပါ။")
    for rnd in range(1, 4):
        task["message"] = f"TypeScript စစ်နေပါတယ် (round {rnd})"
        errs = typecheck(key)
        if not errs:
            log("  typecheck: OK")
            break
        log(f"  typecheck: {errs.count(chr(10)) + 1} error lines -> sending to Claude")
        messages.append({"role": "user", "content": "tsc --noEmit errors:\n" + errs +
                         "\n\nFix them. Output only the changed files, complete, in the same format."})
        _apply(_ask(client, model, system, messages, cost, f"fix{rnd}", log), key, log)
    else:
        if typecheck(key):
            raise RecapError("anim_ai", "Code ကို ၃ ကြိမ် ပြင်ပြီးတာတောင် compile မဖြစ်သေးပါ။ Log ကို ကြည့်ပါ။")
    if review:
        fps = 30
        picks = [timing[0], timing[len(timing) // 2], timing[-1]]
        frames = [int((t["start"] + t["end"]) / 2 * fps) for t in picks]
        task["message"] = "Still ပုံ ၃ ပုံ ထုတ်ပြီး Claude ကို စစ်ခိုင်းနေပါတယ်"
        imgs = _stills(key, f"{P}Short", frames, task)
        content: list[dict] = []
        for f, t in zip(imgs, picks):
            content.append({"type": "text", "text": f"Frame {int((t['start'] + t['end']) / 2 * fps)} - line {t['id']} "
                                                     f"[{t['who']}]: {t['text']}"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.standard_b64encode(f.read_bytes()).decode()}})
        content.append({"type": "text", "text": "These are rendered stills (half size). Check: blank/black frames, "
                        "characters missing or cut off, text overflowing, staging that does not match the line. If "
                        "they are fine reply exactly LOOKS_GOOD. Otherwise output the fixed files."})
        messages.append({"role": "user", "content": content})
        txt = _ask(client, model, system, messages, cost, "review", log)
        if "LOOKS_GOOD" not in txt:
            fixed = _apply(txt, key, log)
            log(f"  review fixes: {', '.join(fixed) or '(none)'}")
            if fixed and typecheck(key):
                messages.append({"role": "user", "content": "tsc errors after your fix:\n" + typecheck(key) +
                                 "\nFix them; output only changed files."})
                _apply(_ask(client, model, system, messages, cost, "fix-review", log), key, log)
    (d / "ai_log.json").write_text(json.dumps({"model": model, "usd": round(cost.usd, 3), "calls": cost.calls,
                                              "at": time.strftime("%Y-%m-%d %H:%M")}, indent=1), "utf-8")
    log(f"Claude API total: ${cost.usd:.2f} ({len(cost.calls)} calls)")
    return {"usd": round(cost.usd, 3), "calls": len(cost.calls)}
