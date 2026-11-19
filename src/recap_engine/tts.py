"""Stage 5: Burmese voice. Adapter to the existing Myanmar Voice Studio engine
(Nara Mini v1) running in its own venv as a persistent subprocess."""
from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from .burmese import apply_pronunciations, load_pronunciations, normalize
from .errors import RecapError
from .manifest import hash_obj
from .media import CREATE_NO_WINDOW, audio_duration, ffmpeg_bin, run as ff_run
from .pipeline import Context

REPO = Path(__file__).resolve().parents[2]
RATE_FILE = REPO / "config" / "recap_voice_rates.json"
CALIBRATION_TEXT = ("ဒီနေ့ ကျွန်တော်တို့ ပြောပြမယ့် ဇာတ်လမ်းကတော့ အရမ်းကို စိတ်ဝင်စားဖို့ ကောင်းပါတယ်။ "
                    "သူမဟာ သူ့ခင်ပွန်းရဲ့ လျှို့ဝှက်ချက်ကို သိသွားတဲ့အခါ ဘာလုပ်မလဲ။")
VOICE_PY = os.environ.get("RECAP_TTS_PYTHON", str(REPO / ".venv-nara" / "Scripts" / "python.exe"))
MAX_SPEEDUP = 1.15


class TTSClient:
    _inst: "TTSClient | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        if not Path(VOICE_PY).exists():
            raise RecapError("missing_model", "Voice Studio (Nara Mini) venv မတွေ့ပါ။ README မှာ .venv-nara setup ကို ကြည့်ပါ။")
        self.proc = subprocess.Popen([VOICE_PY, str(Path(__file__).with_name("tts_worker.py"))], cwd=str(REPO),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", creationflags=CREATE_NO_WINDOW)
        hello = self._read()
        if not hello.get("ready"):
            raise RecapError("missing_model", "Burmese TTS engine မစနိုင်ပါ။ Model Manager မှာ Nara Mini ကို စစ်ပါ။", str(hello))
        self.voices = hello.get("voices", [])
        self._io_lock = threading.Lock()

    def _read(self) -> dict:
        assert self.proc.stdout
        line = self.proc.stdout.readline()
        if not line:
            raise RecapError("tts_failed", "Burmese TTS engine ရပ်သွားပါတယ်။ Retry လုပ်ပါ။")
        return json.loads(line)

    # ---- pool of TTS processes: lines are split across workers (CPU cores) and run in parallel
    _pool: list["TTSClient"] = []
    _free: "queue.Queue[TTSClient] | None" = None

    @staticmethod
    def workers() -> int:
        env = os.environ.get("RECAP_TTS_WORKERS")
        if env and env.isdigit() and int(env) > 0:
            return int(env)
        return max(1, min(6, (os.cpu_count() or 4) // 4))

    @classmethod
    def _ensure_pool(cls) -> None:
        with cls._lock:
            want = cls.workers()
            alive = [c for c in cls._pool if c.proc.poll() is None]
            if cls._free is None or len(alive) != len(cls._pool) or len(cls._pool) != want:
                for c in cls._pool:
                    if c.proc.poll() is None:
                        c.proc.kill()
                cls._pool = [TTSClient() for _ in range(want)]
                cls._free = queue.Queue()
                for c in cls._pool:
                    cls._free.put(c)

    @classmethod
    @contextlib.contextmanager
    def lease(cls):
        cls._ensure_pool()
        q = cls._free
        c = q.get()
        try:
            yield c
        finally:
            q.put(c)

    @classmethod
    def get(cls) -> "TTSClient":  # single client (calibration etc.)
        cls._ensure_pool()
        return cls._pool[0]

    @classmethod
    def close(cls) -> None:
        with cls._lock:
            for c in cls._pool:
                if c.proc.poll() is None:
                    c.proc.kill()
            cls._pool, cls._free = [], None
    def synth(self, text: str, voice_id: str, out: Path, speed: float = 1.0) -> float:
        with self._io_lock:
            assert self.proc.stdin
            self.proc.stdin.write(json.dumps({"text": text, "voice_id": voice_id, "speed": speed,
                                              "out": str(out)}, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            r = self._read()
        if not r.get("ok"):
            raise RecapError("tts_failed", "အသံထုတ်လို့ မရပါ။ စာသားကို စစ်ပြီး ဒီ beat ကို ပြန်ထုတ်ကြည့်ပါ။", r.get("error", ""))
        return float(r["seconds"])


# Microsoft neural Burmese voices (online, free, no key) via edge-tts
EDGE_VOICES = {"edge_thiha": "my-MM-ThihaNeural", "edge_nilar": "my-MM-NilarNeural"}


def edge_synth(text: str, voice_id: str, out: Path, speed: float = 1.0) -> float:
    import asyncio
    import tempfile

    import edge_tts
    rate = f"{round((speed - 1) * 100):+d}%"
    with tempfile.TemporaryDirectory() as td:
        mp3 = Path(td) / "a.mp3"
        for attempt in range(3):
            try:
                asyncio.run(edge_tts.Communicate(text, EDGE_VOICES[voice_id], rate=rate).save(str(mp3)))
                break
            except Exception as e:  # noqa: BLE001  network hiccup
                if attempt == 2:
                    raise RecapError("tts_failed", "Microsoft အသံ (Thiha/Nilar) ထုတ်လို့ မရပါ။ Internet စစ်ပါ (သို့) "
                                                   "local voice ကို ရွေးပါ။", str(e)) from e
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(mp3), "-ar", "24000", "-ac", "1", str(out)])
    return audio_duration(out)


def is_remote_voice(voice_id: str) -> bool:
    return voice_id in EDGE_VOICES or voice_id.startswith("el:")


def synth_any(text: str, voice_id: str, out: Path, speed: float = 1.0) -> float:
    if voice_id.startswith("el:"):  # ElevenLabs (user's key)
        from .providers import elevenlabs_tts
        return elevenlabs_tts(text, voice_id, out, speed)
    if voice_id in EDGE_VOICES:
        return edge_synth(text, voice_id, out, speed)
    with TTSClient.lease() as tts:
        return tts.synth(text, voice_id, out, speed)


def prepare_text(text: str) -> str:
    return apply_pronunciations(normalize(text), load_pronunciations())


def synth_cached(text: str, voice_id: str, out_dir: Path, stem: str, speed: float = 1.0) -> dict:
    """Synthesize with caching by hash(text after pronunciation dict, voice, speed)."""
    spoken = prepare_text(text)
    h = hash_obj({"t": spoken, "v": voice_id, "s": round(speed, 3),
                  "engine": "elevenlabs" if voice_id.startswith("el:") else
                  "edge-neural" if voice_id in EDGE_VOICES else "nara-mini-v1"})
    out = out_dir / f"{stem}_{h}.wav"
    if out.exists():
        return {"path": out, "seconds": audio_duration(out), "hash": h, "cache_hit": True}
    for old in out_dir.glob(f"{stem}_*.wav"):
        old.unlink(missing_ok=True)
    synth_any(spoken, voice_id, out, speed)
    secs = tighten_silence(out)
    return {"path": out, "seconds": secs, "hash": h, "cache_hit": False}


def tighten_silence(path: Path, max_pause: float = 0.45, edge: float = 0.05, thresh: float = 0.01) -> float:
    """Trim leading/trailing silence and shorten internal pauses > max_pause (keeps natural
    phrasing but removes the long gaps that read as dead air in a recap)."""
    import numpy as np
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    hop = max(1, sr // 100)
    n = len(x) // hop
    if n == 0:
        return len(x) / sr
    loud = np.abs(x[: n * hop]).reshape(n, hop, -1).max(axis=(1, 2)) > thresh
    if not loud.any():
        return len(x) / sr
    first, last = int(np.argmax(loud)), int(n - np.argmax(loud[::-1]))
    keep: list[np.ndarray] = []
    i = first
    max_frames = int(max_pause * 100)
    while i < last:
        j = i
        while j < last and loud[j] == loud[i]:
            j += 1
        seg = x[i * hop: j * hop]
        if not loud[i] and (j - i) > max_frames:
            half = max_frames * hop // 2
            seg = np.concatenate([seg[:half], seg[-half:]])
        keep.append(seg)
        i = j
    pad = np.zeros((int(edge * sr), x.shape[1]), dtype=np.float32)
    y = np.concatenate([pad, *keep, pad])
    sf.write(str(path), y, sr, subtype="PCM_16")
    return len(y) / sr


def speech_rate(voice_id: str) -> float:
    """Measured Burmese syllables/second for a voice (cached in config)."""
    from .script import estimate_syllables
    rates = json.loads(RATE_FILE.read_text("utf-8")) if RATE_FILE.exists() else {}
    if voice_id in rates:
        return float(rates[voice_id])
    tmp = REPO / "outputs" / "_rate"
    tmp.mkdir(parents=True, exist_ok=True)
    secs = synth_any(prepare_text(CALIBRATION_TEXT), voice_id, tmp / f"{voice_id}.wav")
    rate = estimate_syllables(CALIBRATION_TEXT) / max(0.5, secs)
    rates[voice_id] = round(rate, 3)
    RATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_FILE.write_text(json.dumps(rates, indent=2), "utf-8")
    return rate


def speed_up(src: Path, dst: Path, factor: float) -> None:
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={factor:.4f}", str(dst)])


# ------------------------------------------------------------------ stage
def voice_inputs(ctx: Context) -> Any:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    hooks = p.read_json("script/hooks.json", {}).get("hooks", [])
    return {"beats": [(b.get("narration"), b.get("voice_id")) for b in beats], "voice": ctx.settings.voice_id,
            "hook": ctx.settings.hook_index, "hooks": hooks, "dict": load_pronunciations(), "mode": ctx.settings.mode,
            "speed": ctx.settings.voice_speed}


def beat_text(ctx: Context, beat: dict, hooks: list[str]) -> str:
    if beat["id"] == 0 and ctx.settings.mode != "pro" and ctx.settings.hook_index > 0 and \
            ctx.settings.hook_index <= len(hooks):
        return hooks[ctx.settings.hook_index - 1]
    return beat["narration"]


def stage_voice(ctx: Context) -> dict[str, str]:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    hooks = p.read_json("script/hooks.json", {}).get("hooks", [])
    tdir = p.path("tts")
    from concurrent.futures import ThreadPoolExecutor

    done = [0]
    plock = threading.Lock()

    def one(b: dict) -> dict:
        entry = _voice_one(ctx, p, b, hooks, tdir)
        with plock:
            done[0] += 1
            ctx.progress(done[0] / max(1, len(beats)),
                         f"မြန်မာ အသံ ထုတ်နေပါတယ် {done[0]}/{len(beats)} (worker {TTSClient.workers()})")
        return entry

    if any(not is_remote_voice(b.get("voice_id") or ctx.settings.voice_id) for b in beats):
        TTSClient._ensure_pool()
    with ThreadPoolExecutor(max_workers=TTSClient.workers()) as ex:
        log = list(ex.map(one, beats))  # each worker takes its own lines; order kept
    hits = sum(1 for e in log if e["cache_hit"])
    p.write_json("script/beats.json", beats)
    p.write_json("tts/voice_log.json", {"cache_hits": hits, "total": len(beats), "items": log})
    p.log(f"voice: {hits}/{len(beats)} beats reused from cache, {TTSClient.workers()} TTS workers")
    return {"voice_log": "tts/voice_log.json"}


def _voice_one(ctx: Context, p, b: dict, hooks: list[str], tdir: Path) -> dict:
    voice = b.get("voice_id") or ctx.settings.voice_id
    text = beat_text(ctx, b, hooks)
    r = synth_cached(text, voice, tdir, f"beat_{b['id']:04d}", ctx.settings.voice_speed)
    entry = {"id": b["id"], "voice": voice, "hash": r["hash"], "cache_hit": r["cache_hit"]}
    if ctx.settings.mode == "pro":
        slot = float(b["max_duration"])
        tries = 0
        while r["seconds"] > slot and tries < 2:
            tries += 1
            text = shorten(ctx, b, text, slot, r["seconds"])
            r = synth_cached(text, voice, tdir, f"beat_{b['id']:04d}", ctx.settings.voice_speed)
            entry.setdefault("shortened", []).append(text)
        if r["seconds"] > slot:
            factor = min(MAX_SPEEDUP, r["seconds"] / slot)
            fast = tdir / f"beat_{b['id']:04d}_fast.wav"
            speed_up(r["path"], fast, factor)
            entry["speedup"] = round(factor, 3)
            p.log(f"line {b['id']}: speed-up {factor:.3f}x (slot {slot:.2f}s, tts {r['seconds']:.2f}s)")
            r = {**r, "path": fast, "seconds": audio_duration(fast)}
        if r["seconds"] > slot + 0.05:
            entry["overflow"] = round(r["seconds"] - slot, 3)
        b["burmese"] = b["narration"] = text
    b["tts_path"] = str(r["path"].relative_to(p.root)).replace("\\", "/")
    b["tts_seconds"] = round(r["seconds"], 3)
    b["spoken_text"] = text
    return entry


def shorten(ctx: Context, b: dict, text: str, slot: float, actual: float) -> str:
    from .llm import unload
    from .pipeline import gpu_lock
    from .script import shorten_line
    # TTS runs on CPU (onnxruntime) so the LLM may use the GPU here
    with gpu_lock(ctx.project, "llm-shorten"):
        out = shorten_line(ctx.settings.llm_model, ctx.settings.language, b.get("chinese", ""), text, slot, actual)
    return out


def cleanup() -> None:
    TTSClient.close()
    shutil.rmtree(REPO / "outputs" / "_rate", ignore_errors=True)
