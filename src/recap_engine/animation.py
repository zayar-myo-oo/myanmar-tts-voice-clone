"""Animation tab: drives the Remotion + three.js cartoon-short project (claude-animated-shorts /
my-first-short) from the app. The project stays in its own folder; this module only

  * discovers the shorts (Root.tsx compositions) and their voice / mix / output files,
  * edits a short's script lines and builds voice.wav + lines_timing.json (same format as
    scripts/build_voice.py, so story.ts cut timings and audio/*_mix.py follow automatically),
  * runs stills / sound mix / Remotion render / final mux as queued background tasks.

New scenes / characters are code (story.ts, cast.ts, world.ts): those are still written with
Claude Code + the cartoon-3d-short skill. This tab covers everything around that code.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from .errors import RecapError

CONFIG = Path(__file__).resolve().parents[2] / "config" / "animation.json"
DEFAULT_ROOT = Path.home() / "Desktop" / "Code Claude" / "my-first-short"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SR = 48000


# ------------------------------------------------------------------ config / discovery
def root() -> Path:
    try:
        r = json.loads(CONFIG.read_text("utf-8")).get("root")
        if r:
            return Path(r)
    except (OSError, ValueError):
        pass
    return DEFAULT_ROOT


def set_root(path: str) -> Path:
    p = Path(path)
    if not (p / "src" / "Root.tsx").exists():
        raise RecapError("anim_root", "ဒီ folder ထဲမှာ Remotion project (src/Root.tsx) မတွေ့ပါ။")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"root": str(p)}, indent=2), "utf-8")
    return p


def _newest(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True) if folder.exists() else []
    return files[0] if files else None


def _rel(p: Path | None, base: Path) -> str | None:
    return str(p.relative_to(base)).replace("\\", "/") if p else None


def short_info(key: str, comp_id: str, thumb_id: str | None, R: Path) -> dict[str, Any]:
    src = R / "src" / "videos" / key
    voice_dir = None
    if src.exists():  # which voice folder does this short's code read?
        for f in src.glob("*.ts*"):
            m = re.search(r"(voice(?:_\w+)?)/lines_timing\.json", f.read_text("utf-8", errors="ignore"))
            if m:
                voice_dir = m.group(1)
                break
    voice_dir = voice_dir or (f"voice_{key}" if (R / f"voice_{key}").exists() else "voice")
    vd = R / voice_dir
    out = R / "out" / key
    final = _newest(out, "*final*.mp4") or _newest(out, "*.mp4")
    thumb = _newest(out, "*thumb*.jpg") or _newest(out, "*thumb*.png") or _newest(out, "*.jpg")
    mix_py = R / "audio" / f"{key}_mix.py"
    if not mix_py.exists() and key == "pagoda":
        mix_py = R / "audio" / "pagoda_mix.py"
    dur = None
    if final:
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                               capture_output=True, text=True, creationflags=NO_WINDOW, timeout=20)
            dur = round(float(r.stdout.strip()), 1)
        except (ValueError, subprocess.SubprocessError):
            pass
    lines = []
    try:
        lines = json.loads((vd / "lines.json").read_text("utf-8"))
    except (OSError, ValueError):
        pass
    return {"key": key, "id": comp_id, "thumb_id": thumb_id, "src": _rel(src, R) if src.exists() else None,
            "voice_dir": voice_dir, "has_lines": bool(lines), "lines": len(lines),
            "has_voice": (vd / "voice.wav").exists(), "mix_script": _rel(mix_py, R) if mix_py.exists() else None,
            "final": _rel(final, R), "thumb": _rel(thumb, R), "duration": dur,
            "public_voice": _rel(R / "public" / key / "voice.wav", R) if (R / "public" / key / "voice.wav").exists() else None}


def discover() -> dict[str, Any]:
    R = root()
    rt = R / "src" / "Root.tsx"
    if not rt.exists():
        return {"root": str(R), "ok": False, "shorts": []}
    txt = rt.read_text("utf-8", errors="ignore")
    comps = re.findall(r'<Composition\s+id="(\w+)"', txt)
    stills = set(re.findall(r'<Still\s+id="(\w+)"', txt))
    shorts = []
    for cid in comps:
        key = re.sub(r"Short$", "", cid).lower()
        thumb = next((s for s in stills if s.lower() == key + "thumb"), None)
        shorts.append(short_info(key, cid, thumb, R))
    return {"root": str(R), "ok": True, "studio": STUDIO.get("url"), "shorts": shorts}


def find_short(key: str) -> dict[str, Any]:
    for s in discover()["shorts"]:
        if s["key"] == key:
            return s
    raise RecapError("anim_missing", f"Animation '{key}' မတွေ့ပါ။")


def safe_file(rel: str) -> Path:
    R = root().resolve()
    f = (R / rel).resolve()
    if R not in f.parents or not f.is_file():
        raise RecapError("anim_file", "ဖိုင် မတွေ့ပါ။")
    return f


# ------------------------------------------------------------------ script lines + voice
def get_lines(key: str) -> dict[str, Any]:
    s = find_short(key)
    vd = root() / s["voice_dir"]
    def load(n, d):
        try:
            return json.loads((vd / n).read_text("utf-8"))
        except (OSError, ValueError):
            return d
    return {"voice_dir": s["voice_dir"], "lines": load("lines.json", []), "timing": load("lines_timing.json", []),
            "voices": load("voices.json", {})}


def save_lines(key: str, lines: list[dict], voices: dict[str, str] | None = None) -> None:
    s = find_short(key)
    vd = root() / s["voice_dir"]
    vd.mkdir(exist_ok=True)
    clean = [{"id": int(l.get("id") or i + 1), "who": (l.get("who") or "narrator").strip(),
              "gapAfter": round(float(l.get("gapAfter", 0.6)), 2), "text": (l.get("text") or "").strip()}
             for i, l in enumerate(lines) if (l.get("text") or "").strip()]
    (vd / "lines.json").write_text(json.dumps(clean, ensure_ascii=False, indent=1), "utf-8")
    if voices is not None:
        (vd / "voices.json").write_text(json.dumps(voices, ensure_ascii=False, indent=1), "utf-8")


def _nara_mcp(text: str, voice: str, out: Path) -> None:
    """Nara app voices (shoon, htet_myat, ...) through its local MCP server, like scripts/gen_voice.mjs."""
    import httpx
    url = os.environ.get("NARA_URL", "http://127.0.0.1:17862/mcp")
    try:
        r = httpx.post(url, timeout=300, headers={"Content-Type": "application/json",
                                                  "Accept": "application/json, text/event-stream"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                             "params": {"name": "nara_speak", "arguments": {"text": text, "voice": voice}}})
    except httpx.HTTPError as e:
        raise RecapError("tts_failed", "Nara app (MCP, port 17862) ကို ချိတ်လို့ မရပါ။ Nara app ဖွင့်ထားပါ (သို့) "
                                       "local / Microsoft voice ကို ရွေးပါ။", str(e)) from e
    t = r.text
    d = next((ln[6:] for ln in t.splitlines() if ln.startswith("data: ")), t)
    res = json.loads(d)
    txt = "\n".join(c.get("text", "") for c in res.get("result", {}).get("content", []))
    if res.get("result", {}).get("isError"):
        raise RecapError("tts_failed", "Nara voice ထုတ်လို့ မရပါ။", txt[:500])
    shutil.copyfile(json.loads(txt)["path"], out)


def _synth_line(text: str, voice: str, out: Path, speed: float) -> None:
    if voice.startswith("nara:"):
        _nara_mcp(text, voice[5:], out)
        return
    from .tts import prepare_text, synth_any
    synth_any(prepare_text(text), voice, out, speed)


def _read_mono48(path: Path) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g).astype(np.float32)
    return x


def build_voice(key: str, voices: dict[str, str], speed: float = 1.0, progress=None, cancel=None) -> dict:
    """Per-line TTS -> voice.wav (48 kHz mono 16-bit) + lines_timing.json, same rules as build_voice.py."""
    import soundfile as sf
    s = find_short(key)
    R = root()
    vd = R / s["voice_dir"]
    lines = json.loads((vd / "lines.json").read_text("utf-8"))
    if not lines:
        raise RecapError("anim_lines", "Script စာကြောင်း မရှိသေးပါ။")
    tmp = vd / "_lines"
    tmp.mkdir(exist_ok=True)
    pad = 0.15
    chunks, timing, t = [np.zeros(int(pad * SR), dtype=np.float32)], [], pad
    for i, ln in enumerate(lines):
        if cancel and cancel():
            raise RecapError("cancelled", "ရပ်လိုက်ပါပြီ")
        if progress:
            progress(i / len(lines), f"အသံ ထုတ်နေပါတယ် {i + 1}/{len(lines)} ({ln['who']})")
        v = voices.get(ln["who"]) or voices.get("*") or "male_calm"
        w = tmp / f"line_{ln['id']:03d}.wav"
        _synth_line(ln["text"], v, w, speed)
        x = _read_mono48(w)
        thr = 0.01 * max(1e-6, float(np.abs(x).max()))
        idx = np.where(np.abs(x) > thr)[0]
        if len(idx):
            x = x[max(0, idx[0] - int(0.04 * SR)): min(len(x), idx[-1] + int(0.04 * SR))]
        dur = len(x) / SR
        timing.append({"id": ln["id"], "who": ln["who"], "text": ln["text"], "start": round(t, 3),
                       "end": round(t + dur, 3), "voice": v})
        chunks += [x, np.zeros(int(float(ln.get("gapAfter", 0.6)) * SR), dtype=np.float32)]
        t += dur + float(ln.get("gapAfter", 0.6))
    y = np.concatenate(chunks)
    peak = float(np.abs(y).max())
    y = y * (0.89 / peak) if peak > 0 else y
    if (vd / "voice.wav").exists():  # keep the previous take
        shutil.copyfile(vd / "voice.wav", vd / "voice_prev.wav")
    sf.write(str(vd / "voice.wav"), y, SR, subtype="PCM_16")
    (vd / "lines_timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), "utf-8")
    (vd / "voices.json").write_text(json.dumps(voices, ensure_ascii=False, indent=1), "utf-8")
    if s.get("public_voice"):  # shorts that play public/<key>/voice.wav directly
        shutil.copyfile(vd / "voice.wav", R / s["public_voice"])
    shutil.rmtree(tmp, ignore_errors=True)
    return {"seconds": round(len(y) / SR, 2), "lines": len(timing)}


def write_script(topic: str, model: str, speakers: list[str], n: int = 12) -> list[dict]:
    """Local LLM drafts Burmese lines (narrator + characters) for a 55-70 s short."""
    from .llm import chat_json
    schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
        "who": {"type": "string"}, "text": {"type": "string"}, "gapAfter": {"type": "number"}},
        "required": ["who", "text", "gapAfter"]}}}, "required": ["lines"]}
    who = ", ".join(speakers or ["narrator"])
    r = chat_json(model, "You write scripts for 55-70 second animated story shorts in natural spoken Burmese (Unicode).",
                  f"Topic: {topic}\nSpeakers: {who} (narrator explains; characters react in short lines).\n"
                  f"Write {n} lines. Line 1 is a hook (a character's surprised question or a striking fact). "
                  "Use correct facts only. Each line 1-2 sentences. gapAfter = pause after the line in seconds (0.4-0.9).",
                  schema, temperature=0.6)
    return [{"id": i + 1, **ln} for i, ln in enumerate(r.get("lines", []))]


# ------------------------------------------------------------------ tasks (one at a time: Chrome/GL render is heavy)
TASKS: dict[str, dict] = {}
_queue: list[str] = []
_cv = threading.Condition()
STUDIO: dict[str, Any] = {}


def _npx() -> str:
    return "npx.cmd" if os.name == "nt" else "npx"


def _run(task: dict, cmd: list[str], cwd: Path, total_frames: int | None = None, label: str = "") -> None:
    env = {**os.environ, "REMOTION_TMP": str(cwd / ".remotion-tmp")}
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)
    task["pid"] = proc.pid
    for line in proc.stdout:
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).rstrip()  # drop terminal colour codes
        if not line:
            continue
        task["log"].append(line)
        del task["log"][:-200]
        m = re.search(r"(?:Rendered|Encoded|frame[s]?)\D{0,3}(\d+)\s*/\s*(\d+)", line)
        if m:
            done, tot = int(m.group(1)), int(m.group(2)) or (total_frames or 1)
            task["step_progress"] = min(1.0, done / max(1, tot))
            task["message"] = f"{label} {done}/{tot}"
        if task["cancel"]:
            proc.kill()
    proc.wait()
    if task["cancel"]:
        raise RecapError("cancelled", "ရပ်လိုက်ပါပြီ")
    if proc.returncode != 0:
        raise RecapError("anim_failed", f"{label} မအောင်မြင်ပါ။ Log ကို ကြည့်ပါ။", "\n".join(task["log"][-30:]))


def _python(R: Path) -> str:
    venv = R / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else "python"


def _do(task: dict) -> None:
    R = root()
    s = find_short(task["key"])
    steps = task["steps"]
    out = R / "out" / s["key"]
    out.mkdir(parents=True, exist_ok=True)
    for i, step in enumerate(steps):
        task["step"], task["step_index"], task["step_progress"] = step, i, 0.0
        if step == "voice":
            task["message"] = "အသံ ထုတ်နေပါတယ်"
            def prog(f, m):
                task["step_progress"], task["message"] = f, m
            build_voice(s["key"], task["args"].get("voices") or get_lines(s["key"])["voices"],
                        float(task["args"].get("speed", 1.0)), prog, lambda: task["cancel"])
        elif step == "ai_code":
            from .anim_ai import generate
            task["message"] = "Claude က scene code ရေးနေပါတယ် (၂–၁၀ မိနစ်)"
            generate(s["key"], task, task["args"].get("model") or "claude-opus-5-5", bool(task["args"].get("review", True)))
        elif step == "still":
            frames = str(task["args"].get("frames", "30,300,900"))
            task["message"] = "Still ပုံ ထုတ်နေပါတယ်"
            for fr in [f.strip() for f in frames.split(",") if f.strip().isdigit()][:6]:
                _run(task, [_npx(), "remotion", "still", "src/index.ts", s["id"], f"out/{s['key']}/still_{fr}.jpg",
                            f"--frame={fr}", "--gl=angle", "--scale=0.5"], R, label=f"Still {fr}")
        elif step == "mix":
            if not s["mix_script"]:
                task["log"].append("(sound mix script မရှိ — mix ကို ကျော်ပါတယ်)")
                continue
            task["message"] = "အသံ mix လုပ်နေပါတယ် (၅–၁၀ မိနစ် ကြာနိုင်)"
            _run(task, [_python(R), s["mix_script"]], R, label="Mix")
        elif step == "render":
            task["message"] = "Remotion render စနေပါတယ်"
            scale = ["--scale=1.3333"] if task["args"].get("hd2k") else []
            _run(task, [_npx(), "remotion", "render", "src/index.ts", s["id"], f"out/{s['key']}/video.mp4",
                        "--codec=h264", "--crf=17", "--gl=angle", "--concurrency=1", *scale], R, label="Render")
        elif step == "mux":
            video = out / "video.mp4"
            mix = R / "audio" / f"{s['key']}_mix.wav"
            voice = R / s["voice_dir"] / "voice.wav"
            audio = mix if mix.exists() else voice
            if not video.exists():
                raise RecapError("anim_failed", "video.mp4 မရှိသေးပါ — Render အရင်လုပ်ပါ။")
            task["message"] = "ဗီဒီယို + အသံ ပေါင်းနေပါတယ်"
            _run(task, ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-af", "volume=-1dB", "-c:a", "aac", "-b:a", "256k", "-shortest",
                        "-movflags", "+faststart", str(out / f"{s['key']}_final.mp4")], R, label="Mux")
        task["step_progress"] = 1.0


def _worker() -> None:
    while True:
        with _cv:
            while not _queue:
                _cv.wait()
            tid = _queue.pop(0)
        task = TASKS[tid]
        task["state"], task["started"] = "running", time.time()
        try:
            _do(task)
            task["state"], task["message"] = "done", "ပြီးပါပြီ"
        except Exception as e:  # noqa: BLE001
            task["state"] = "cancelled" if task["cancel"] else "failed"
            task["message"] = getattr(e, "message_my", str(e))
            task["log"].append(getattr(e, "detail", "") or str(e))
        task["finished"] = time.time()


threading.Thread(target=_worker, daemon=True, name="anim-worker").start()


def submit(key: str, steps: list[str], args: dict | None = None) -> dict:
    find_short(key)
    ok = [s for s in steps if s in ("voice", "ai_code", "still", "mix", "render", "mux")]
    if not ok:
        raise RecapError("anim_steps", "လုပ်ရမယ့် အဆင့် မရွေးရသေးပါ။")
    tid = uuid.uuid4().hex[:8]
    TASKS[tid] = {"id": tid, "key": key, "steps": ok, "args": args or {}, "state": "queued", "step": "", "step_index": 0,
                  "step_progress": 0.0, "message": "တန်းစီနေပါတယ်", "log": [], "cancel": False, "created": time.time()}
    with _cv:
        _queue.append(tid)
        _cv.notify()
    return public(TASKS[tid])


def cancel(tid: str) -> None:
    t = TASKS.get(tid)
    if t:
        t["cancel"] = True
        with _cv:
            if tid in _queue:
                _queue.remove(tid)
                t["state"] = "cancelled"


def public(t: dict) -> dict:
    n = max(1, len(t["steps"]))
    return {k: v for k, v in t.items() if k not in ("log", "args")} | {
        "progress": round((t["step_index"] + t["step_progress"]) / n, 3), "log_tail": t["log"][-12:]}


def start_studio() -> str:
    """Remotion Studio (live preview / timeline) on :3000, started once."""
    p = STUDIO.get("proc")
    if p is None or p.poll() is not None:
        R = root()
        STUDIO["proc"] = subprocess.Popen([_npx(), "remotion", "studio", "src/index.ts", "--port=3000", "--no-open"],
                                          cwd=str(R), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          env={**os.environ, "REMOTION_TMP": str(R / ".remotion-tmp")},
                                          creationflags=NO_WINDOW)
        STUDIO["url"] = "http://localhost:3000"
    return STUDIO["url"]
