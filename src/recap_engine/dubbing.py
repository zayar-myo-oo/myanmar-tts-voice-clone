"""Dubbing: an English short (narration + burned-in word-pop captions) -> a Burmese-dubbed short.

  1 audio      demucs splits narration from music / SFX (the bed is kept)
  2 transcribe faster-whisper (English, word timestamps) -> sentences
  3 captions   local OCR (RapidOCR) finds where the burned-in English captions sit and tracks them frame by frame
  4 translate  LLM -> natural spoken Burmese with a hook first line (text only; nothing visual leaves the PC)
  5 voice      Burma Cat (VoxCPM2 clone from "voice model collection") or any voice the app already has
  6 render     English text removed (inpaint, or a blur box that follows it), Burmese phrase-pop captions burned in
               with libass (HarfBuzz shaping), video slowed per sentence where the Burmese line is longer, bed + voice mixed

Text detection, text removal and Burmese text rendering are all local. Every step caches its result in the job folder,
so editing a line only re-runs voice + render.
"""
from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .burmese import display_len
from .errors import RecapError
from .manifest import default_projects_root, hash_obj
from .media import CREATE_NO_WINDOW, ffmpeg_bin, ffmpeg_filter_path, probe, run as ff_run, video_encoder_args

REPO = Path(__file__).resolve().parents[2]
FONTS_DIR = REPO / "fonts"
WORKBENCH = Path(os.environ.get("RECAP_VOICE_WORKBENCH",
                                str(Path.home() / "Desktop" / "voice model collection" / "Voice Workbench")))
SR = 48000
MAX_TEMPO = 1.2      # the Burmese voice is sped up at most this much
MAX_STRETCH = 1.35   # the picture is slowed down at most this much
DEFAULTS: dict[str, Any] = {
    "voice": "bc:builtin-aung", "vox_model": "lite", "remove": "auto", "highlight": True, "intro": False,
    "llm": "", "review": True, "tone": "normal", "bed": "keep", "bed_gain": 0.85, "caption_scale": 1.0, "max_chars": 14,
}
VERSION = 1


def root() -> Path:
    d = default_projects_root() / "_dub"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ====================================================================================== job
class Cancelled(Exception):
    pass


class Job:
    def __init__(self, jid: str):
        self.id = jid
        self.dir = root() / jid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cancel = False
        self.lock = threading.Lock()
        self.meta: dict[str, Any] = self.read("job.json", {}) or {
            "id": jid, "created": int(time.time()), "state": "new", "progress": 0.0, "message": "", "opts": dict(DEFAULTS),
            "title": "", "error": "", "warnings": []}

    def path(self, *parts: str) -> Path:
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def read(self, name: str, default: Any = None) -> Any:
        f = self.dir / name
        try:
            return json.loads(f.read_text("utf-8")) if f.exists() else default
        except (OSError, ValueError):
            return default

    def write(self, name: str, data: Any) -> None:
        f = self.path(name)
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        for attempt in range(40):  # Windows refuses the swap while another process (the UI polling) has the file open
            try:
                tmp.replace(f)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05)

    def save(self) -> None:
        with self.lock:
            self.write("job.json", self.meta)

    def log(self, msg: str) -> None:
        with open(self.path("log.txt"), "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

    def progress(self, frac: float, message: str = "") -> None:
        if self.cancel:
            raise Cancelled()
        self.meta["progress"] = round(max(0.0, min(1.0, frac)), 4)
        if message:
            self.meta["message"] = message
        now = time.time()
        if now - getattr(self, "_saved", 0) > 0.7:
            self._saved = now
            try:
                self.save()
            except OSError:  # a progress tick is never worth failing the job for
                pass

    def warn(self, msg: str) -> None:
        self.log("WARN " + msg)
        if msg not in self.meta["warnings"]:
            self.meta["warnings"].append(msg)

    @property
    def opts(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.meta.get("opts", {})}

    @property
    def source(self) -> Path:
        return self.dir / self.meta["source"]


def _span(job: Job, a: float, b: float) -> Callable[[float, str], None]:
    return lambda f, m="": job.progress(a + (b - a) * max(0.0, min(1.0, f)), m)


def _cached(job: Job, name: str, key: Any) -> Any:
    d = job.read(name)
    return d if isinstance(d, dict) and d.get("_key") == hash_obj(key) else None


def _cuda() -> bool:
    from .analyze import _cuda as c
    return c()


# ====================================================================================== 1 audio
def stage_audio(job: Job, prog) -> None:
    audio, vocals, bed = job.path("audio.wav"), job.path("vocals.wav"), job.path("bed.wav")
    if vocals.exists() and bed.exists():
        return
    prog(0.02, "အသံ ထုတ်ယူနေပါတယ်")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(job.source), "-vn", "-ac", "2", "-ar", str(SR),
            "-c:a", "pcm_s16le", str(audio)])
    from .pipeline import gpu_lock
    tmp = job.path("_demucs", "x").parent
    shutil.rmtree(tmp, ignore_errors=True)
    cmd = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-d", "cuda" if _cuda() else "cpu",
           "--segment", "7", "--overlap", "0.1", "-j", "0", "-o", str(tmp), str(audio)]
    prog(0.1, "စကားသံနဲ့ တေးသံ/SFX ကို ခွဲနေပါတယ် (Demucs)")
    with gpu_lock(None, "dub-demucs"):
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=CREATE_NO_WINDOW, timeout=3600)
    stem = tmp / "htdemucs" / "audio"
    if r.returncode != 0 or not (stem / "vocals.wav").exists():
        job.warn("Demucs မအောင်မြင်လို့ တေးသံ/SFX ကို မခွဲနိုင်ပါ — မူရင်းအသံကို ပိတ်ပြီး မြန်မာအသံပဲ ထည့်ပါမယ်။")
        job.log(r.stderr[-800:])
        shutil.copy(audio, vocals)
        import soundfile as sf
        info = sf.info(str(audio))
        sf.write(str(bed), np.zeros((info.frames, 2), dtype=np.float32), SR, subtype="PCM_16")
    else:
        shutil.move(str(stem / "vocals.wav"), vocals)
        shutil.move(str(stem / "no_vocals.wav"), bed)
    shutil.rmtree(tmp, ignore_errors=True)


# ====================================================================================== 2 transcribe
_SENT_END = re.compile(r"[.!?…][\"')\]]?$")


def build_sentences(words: list[dict], max_seconds: float = 7.0, min_seconds: float = 1.2) -> list[dict]:
    """Group whisper words into dubbing lines: break at sentence punctuation or a pause, never mid-phrase."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else 9.0
        dur = w["end"] - cur[0]["start"]
        txt = w["word"].strip()
        if nxt is None or _SENT_END.search(txt) or gap > 0.7 or (dur > max_seconds * 0.6 and txt.endswith((",", ";", ":"))) \
                or dur > max_seconds:
            out.append(cur)
            cur = []
    merged: list[list[dict]] = []
    for s in out:  # a very short line ("Wrong.") joins its neighbour so the voice has something to say
        if merged and (s[-1]["end"] - s[0]["start"] < min_seconds or merged[-1][-1]["end"] - merged[-1][0]["start"] < min_seconds) \
                and s[-1]["end"] - merged[-1][0]["start"] <= max_seconds and s[0]["start"] - merged[-1][-1]["end"] < 0.7:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return [{"id": i, "start": round(s[0]["start"], 3), "end": round(s[-1]["end"], 3),
             "en": " ".join(w["word"].strip() for w in s).strip()} for i, s in enumerate(merged)]


def stage_transcribe(job: Job, prog) -> None:
    if job.read("transcript.json"):
        return
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RecapError("missing_model", "faster-whisper မရှိသေးပါ။ Model Manager မှာ install လုပ်ပါ။") from e
    from .pipeline import gpu_lock
    from .transcribe import resolve_whisper
    prog(0.05, "English စကားကို စာသားပြောင်းနေပါတယ် (Whisper)")
    dev = "cuda" if _cuda() else "cpu"
    words: list[dict] = []
    with gpu_lock(None, "dub-whisper"):
        model = WhisperModel(resolve_whisper("large-v3-turbo"), device=dev, compute_type="float16" if dev == "cuda" else "int8")
        segs, info = model.transcribe(str(job.path("vocals.wav")), language="en", word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
        for s in segs:
            for w in s.words or []:
                if w.word.strip():
                    words.append({"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
            prog(min(0.95, s.end / max(1.0, info.duration)))
        del model
    if not words:
        raise RecapError("no_speech", "ဒီဗီဒီယိုမှာ English စကားပြောသံ မတွေ့ပါ။")
    job.write("transcript.json", {"words": words, "sentences": build_sentences(words)})


# ====================================================================================== 3 captions (OCR tracking)
_ocr_engine = None
_ocr_lock = threading.Lock()


def _ocr():
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            import torch  # noqa: F401  (loads the CUDA DLLs onnxruntime-gpu needs)
            from rapidocr import RapidOCR
            _ocr_engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": _cuda(), "Global.use_cls": False,
                                           "Global.log_level": "error"})
        return _ocr_engine


def _boxes(res) -> list[list[float]]:
    b = getattr(res, "boxes", None)
    if b is None:
        return []
    out = []
    for q in b:
        a = np.asarray(q, dtype=float).reshape(-1, 2)
        out.append([float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())])
    return out


def _norm_word(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _is_caption(text: str, spoken: set[str]) -> bool:
    toks = [t for t in (_norm_word(x) for x in text.split()) if t]
    if not toks:
        return False
    hit = 0
    for t in toks:
        if t in spoken or (len(t) >= 3 and any(s.startswith(t) or t.startswith(s) for s in spoken if len(s) >= 3)):
            hit += 1
    return hit * 2 >= len(toks)


def stage_captions(job: Job, prog) -> None:
    """Where are the burned-in English captions? Pass 1 (2 fps, full frame, with recognition) keeps only text that the
    narrator is saying at that moment, which separates captions from signs in the scene. Pass 2 (about 15 fps, caption
    band only, detection only) tracks the boxes densely so the cover follows every word pop."""
    if job.read("captions.json"):
        return
    import cv2
    from .pipeline import gpu_lock
    words = job.read("transcript.json")["words"]
    starts = [w["start"] for w in words]
    cap = cv2.VideoCapture(str(job.source))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ocr = _ocr()
    hits: list[dict] = []  # matched caption lines of pass 1
    step1 = max(1, int(round(fps / 2)))
    sampled = 0
    with gpu_lock(None, "dub-ocr"):
        i = 0
        while True:
            if not cap.grab():
                break
            if i % step1 == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                sampled += 1
                t = i / fps
                lo, hi = bisect.bisect_left(starts, t - 1.3), bisect.bisect_right(starts, t + 1.3)
                spoken = {_norm_word(w["word"]) for w in words[lo:hi]} - {""}
                res = ocr(frame)
                txts = getattr(res, "txts", None) or []
                group = [b for b, tx in zip(_boxes(res), txts) if _is_caption(tx, spoken)]
                if group:
                    hits.append({"f": i, "boxes": group})
                prog(0.45 * i / max(1, n), "English စာတန်း နေရာကို ရှာနေပါတယ် (OCR)")
            i += 1
        n = max(n, i)
        info: dict[str, Any] = {"fps": fps, "frames": n, "w": W, "h": H, "found": False, "boxes": {}, "step": 1}
        # captions sit at a steady height: keep the dominant cluster of matched lines
        if len(hits) >= max(4, sampled * 0.12):
            hs = np.array([b[3] - b[1] for h in hits for b in h["boxes"]])
            cys = np.array([(min(b[1] for b in h["boxes"]) + max(b[3] for b in h["boxes"])) / 2 for h in hits])
            th = float(np.median(hs))
            cy = float(np.median(cys))
            keep = [h for h, c in zip(hits, cys) if abs(c - cy) < max(2.2 * th, 0.06 * H)]
            tops = [b[1] for h in keep for b in h["boxes"]]
            bots = [b[3] for h in keep for b in h["boxes"]]
            cxs = [(min(b[0] for b in h["boxes"]) + max(b[2] for b in h["boxes"])) / 2 for h in keep]
            y0 = int(max(0, np.percentile(tops, 2) - 0.9 * th))
            y1 = int(min(H, np.percentile(bots, 98) + 0.9 * th))
            info.update(found=True, band=[y0, y1], text_h=round(th, 1), cx=round(float(np.median(cxs)), 1),
                        cy=round(float(np.median([(min(b[1] for b in h["boxes"]) + max(b[3] for b in h["boxes"])) / 2
                                                  for h in keep])), 1),
                        lines=int(round(float(np.median([len(h["boxes"]) for h in keep])))),
                        share=round(len(keep) / max(1, sampled), 3))
            step = max(1, int(round(fps / 15)))
            info["step"] = step
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            i = 0
            boxes: dict[str, list[list[int]]] = {}
            while True:
                if not cap.grab():
                    break
                if i % step == 0:
                    ok, frame = cap.retrieve()
                    if not ok:
                        break
                    res = ocr(frame[y0:y1], use_det=True, use_cls=False, use_rec=False)
                    got = []
                    for b in _boxes(res):
                        bh, bw = b[3] - b[1], b[2] - b[0]
                        if 0.45 * th <= bh <= 2.6 * th and bw >= 0.5 * th:
                            got.append([int(b[0]), int(b[1] + y0), int(b[2] + 1), int(b[3] + y0 + 1)])
                    if got:
                        boxes[str(i)] = got
                    prog(0.45 + 0.55 * i / max(1, n), "English စာတန်းကို frame တိုင်း လိုက်မှတ်နေပါတယ်")
                i += 1
            info["boxes"] = boxes
    cap.release()
    if not info["found"]:
        job.warn("ဗီဒီယိုထဲမှာ ပြောစကားနဲ့ ကိုက်တဲ့ English စာတန်း မတွေ့ပါ — စာဖျောက်တာကို ကျော်ပြီး မြန်မာစာတန်းကို ပုံသေနေရာမှာ ထည့်ပါမယ်။")
    job.write("captions.json", info)


# ====================================================================================== 4 translate
_SCHEMA = {"type": "object", "required": ["lines", "hook"], "properties": {
    "hook": {"type": "string"}, "hook_line": {"type": "integer"},
    "lines": {"type": "array", "items": {"type": "object", "required": ["id", "my"], "properties": {
        "id": {"type": "integer"}, "my": {"type": "string"}, "kw": {"type": "string"}}}}}}

_SYSTEM = """You adapt English short-video narration (TikTok / Reels / Shorts) into Burmese for a Burmese creator.
Write natural SPOKEN Burmese (ပြောစကား: တယ်/ဘူး/တဲ့/ပဲ/လေ), never formal written Burmese (သည်/၏/၍) and never word-by-word translation.
Rules:
- One Burmese line per English line, same id, same meaning, same order. It is spoken over the same picture.
- Line 0 is the HOOK: rewrite it so a viewer stops scrolling in the first second (a surprising claim, a question or a tension), while staying true to the video.
- Each line has a syllable budget ("max"). Stay at or under it: drop filler, keep the point. A short punchy line beats a complete one.
- Put a SPACE between natural phrases (every 2-5 syllables), like subtitle chunks: "ရှေးခေတ်က ကျောက်တုံးပစ်စက်တွေ တကယ်ပဲ အသုံးမဝင်ခဲ့တာလား". Never one long unbroken string.
- Numbers as Burmese words (၃၀၀ -> သုံးရာ). Keep well-known names; write foreign names in Burmese script the way Burmese people say them.
- "kw": the ONE most striking short phrase of that line (1-2 words, at most 10 letters), copied EXACTLY from "my". It is highlighted in the caption.
- "hook": one extra teaser sentence (max 12 syllables) for an optional intro, and "hook_line": the id of the line whose picture is the most dramatic.
- Every "my" is the COMPLETE spoken line (a full sentence), never just a keyword.
- If a glossary is given, use exactly its Burmese wording for those terms every time.
Return JSON only."""


GLOSSARY_FILE = REPO / "config" / "dub_glossary.json"


def load_glossary() -> dict[str, str]:
    """The user's fixed translations (English term -> Burmese), used in every dub."""
    try:
        d = json.loads(GLOSSARY_FILE.read_text("utf-8")) if GLOSSARY_FILE.exists() else {}
    except (OSError, ValueError):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in d.items() if str(k).strip() and str(v).strip()}


def save_glossary(entries: dict[str, str]) -> dict[str, str]:
    clean = {" ".join(str(k).split()): " ".join(str(v).split()) for k, v in entries.items()}
    clean = {k: v for k, v in clean.items() if k and v and len(k) <= 80 and len(v) <= 120}
    GLOSSARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    GLOSSARY_FILE.write_text(json.dumps(dict(sorted(clean.items(), key=lambda kv: kv[0].lower())), ensure_ascii=False, indent=1), "utf-8")
    return load_glossary()


def glossary_for(text: str, glossary: dict[str, str] | None = None) -> dict[str, str]:
    """Only the glossary terms that occur in this narration (whole words, any case; a plural s is allowed)."""
    g = load_glossary() if glossary is None else glossary
    return {k: v for k, v in g.items() if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?:e?s)?(?![A-Za-z0-9])", text, re.I)}


_HOOKS_SCHEMA = {"type": "object", "required": ["hooks"], "properties": {"hooks": {"type": "array", "items": {"type": "string"}}}}


def looks_collapsed(sents: list[dict], lines: Any) -> bool:
    """True when most translated lines are far too short for their English (a model that returned only keywords)."""
    from .script import estimate_syllables
    by = {int(x.get("id", -1)): str(x.get("my", "")) for x in lines if isinstance(x, dict)} if isinstance(lines, list) else {}
    long = [s for s in sents if len(s["en"].split()) >= 5]
    if not long:
        return False
    short = sum(1 for s in long if estimate_syllables(by.get(s["id"], "")) < 0.6 * len(s["en"].split()) or not by.get(s["id"]))
    return short * 2 > len(long)


def pick_hooks(raw: Any, line0: str) -> list[str]:
    """Hook choices for line 0: the translated line first, then the model's alternatives (no blanks, no repeats)."""
    out = [line0] if line0 else []
    for h in raw if isinstance(raw, list) else []:
        h = " ".join(str(h).split())
        if h and h not in out:
            out.append(h)
    return out[:4]


def stage_translate(job: Job, prog) -> None:
    if job.read("lines.json"):
        return
    from .llm import chat_json
    from .settings import ProjectSettings
    sents = job.read("transcript.json")["sentences"]
    o = job.opts
    model = o["llm"] or ProjectSettings().llm_model
    rate = voice_rate(o["voice"])
    dur = float(job.meta.get("duration") or sents[-1]["end"])
    from .script import tone_rule
    tone = o["tone"] if o["tone"] in ("rude", "funny") else "normal"
    system = _SYSTEM + tone_rule(tone).replace(" TONE", "\nTONE", 1)
    room = 1.3 if tone != "normal" else 1.1  # the added remarks need a little more room; the picture slows to fit
    items = []
    for i, s in enumerate(sents):
        slot = (sents[i + 1]["start"] if i + 1 < len(sents) else max(dur, s["end"])) - s["start"]
        items.append({"id": s["id"], "en": s["en"], "max": max(4, int(slot * rate * MAX_TEMPO * room))})
    prog(0.1, f"မြန်မာလို ဘာသာပြန်နေပါတယ် ({model})")
    full = " ".join(s["en"] for s in sents)
    gloss = glossary_for(full)
    user = ("Full narration, for context:\n" + full
            + ("\n\nGlossary (always use exactly this Burmese):\n" + "\n".join(f"{k} = {v}" for k, v in gloss.items()) if gloss else "")
            + "\n\nLines to adapt (id, English, max syllables):\n" + json.dumps(items, ensure_ascii=False, indent=0))
    data = chat_json(model, system, user, _SCHEMA, temperature=0.5 if tone == "normal" else 0.75, num_ctx=8192)
    if looks_collapsed(sents, data.get("lines", [])):  # a small model sometimes answers with keywords only: ask once more
        job.log("translation came back as keywords only; retrying")
        prog(0.4, "ဘာသာပြန် မပြည့်စုံလို့ ပြန်စမ်းနေပါတယ်")
        data = chat_json(model, system, user + "\n\nIMPORTANT: every \"my\" must be the whole spoken sentence for that line, "
                         "about as long as its English, not a keyword.", _SCHEMA, temperature=0.3, num_ctx=8192)
        if looks_collapsed(sents, data.get("lines", [])):
            job.warn("ဘာသာပြန်က စာကြောင်းအပြည့် မထွက်ပါ — စာကြောင်းတွေကို ကိုယ်တိုင် ပြင်ပါ (သို့) တခြား AI model ရွေးပါ။")
    by = {int(x.get("id", -1)): x for x in data.get("lines", []) if isinstance(x, dict)}
    # local models overshoot the budget: one pass that rewrites only the lines that are clearly too long
    from .script import estimate_syllables
    budget = {it["id"]: it["max"] for it in items}
    long = [{"id": i, "en": next(it["en"] for it in items if it["id"] == i), "my": " ".join(str(x.get("my", "")).split()),
             "now": estimate_syllables(str(x.get("my", ""))), "max": budget[i]}
            for i, x in by.items() if i in budget and estimate_syllables(str(x.get("my", ""))) > budget[i] * 1.2]
    if long:
        prog(0.7, f"ရှည်လွန်းတဲ့ စာကြောင်း {len(long)} ကြောင်းကို တိုအောင် ပြန်ရေးနေပါတယ်")
        try:
            fix = chat_json(model, system, "These Burmese lines are too long to speak in their time slot. Rewrite each one shorter: "
                            "\"now\" is its current syllable count, \"max\" is the limit. Cut detail, keep the point and the punch, "
                            "keep the spaces between phrases. Return the same JSON shape (hook may be empty).\n"
                            + json.dumps(long, ensure_ascii=False, indent=0), _SCHEMA, temperature=0.3, num_ctx=8192)
            for x in fix.get("lines", []):
                i = int(x.get("id", -1)) if isinstance(x, dict) else -1
                if i in by and x.get("my") and budget[i] * 0.6 <= estimate_syllables(str(x["my"])) < estimate_syllables(str(by[i].get("my", ""))):
                    by[i] = {**by[i], **x}
        except RecapError as e:
            job.log(f"shorten pass failed: {e.code}")
    lines = []
    for s in sents:
        x = by.get(s["id"], {})
        my = " ".join(str(x.get("my", "")).split())
        if not my:
            job.warn(f"Line {s['id'] + 1} ကို ဘာသာမပြန်နိုင်ပါ — ကိုယ်တိုင် ဖြည့်ပေးပါ။")
        lines.append({**s, "my": my, "kw": str(x.get("kw", "")).strip()})
    hooks: list = []
    if lines and lines[0]["my"]:  # its own small call: asking for it in the big one made local models drop the lines
        prog(0.85, "Hook ရွေးစရာ ၃ မျိုး ရေးနေပါတယ်")
        try:
            hooks = chat_json(model, "You write scroll-stopping first lines for Burmese short videos, in natural spoken Burmese."
                              + tone_rule(tone),
                              "The video's narration:\n" + full + "\n\nIts first line in English: " + sents[0]["en"]
                              + "\nCurrent Burmese first line: " + lines[0]["my"]
                              + ("\nGlossary: " + "; ".join(f"{k} = {v}" for k, v in gloss.items()) if gloss else "")
                              + f"\n\nWrite THREE different alternatives for that first line, each a complete sentence of at most "
                              f"{budget.get(sents[0]['id'], 14)} syllables, with a space between phrases, true to the video and to the "
                              "opening picture: (1) a question, (2) a surprising claim, (3) what is at stake. Return JSON {\"hooks\": [...]}.",
                              _HOOKS_SCHEMA, temperature=0.7, num_ctx=4096).get("hooks", [])
        except RecapError as e:
            job.log(f"hook choices failed: {e.code}")
    if not model.startswith(("claude:", "oai:", "or:")):  # free the VRAM for the voice engine and the encoder
        from .llm import unload
        unload(model)
    hl = data.get("hook_line")
    job.write("lines.json", {"lines": lines, "hook": " ".join(str(data.get("hook", "")).split()),
                             "hook_line": hl if isinstance(hl, int) and 0 <= hl < len(lines) else len(lines) // 2, "model": model,
                             "hooks": pick_hooks(hooks, lines[0]["my"] if lines else ""), "glossary": gloss, "tone": tone})


# ====================================================================================== 5 voice
class VoxClient:
    """Persistent Burma Cat (VoxCPM2) worker inside the Voice Workbench venv."""
    _inst: "VoxClient | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        py = WORKBENCH / ".venv" / "Scripts" / "python.exe"
        if not py.exists() or not (WORKBENCH / "engine.py").exists():
            raise RecapError("missing_model", "Voice Workbench (voice model collection) မတွေ့ပါ။ Desktop\\voice model collection\\"
                                              "Voice Workbench ရှိမရှိ စစ်ပါ (သို့) တခြား voice ရွေးပါ။", str(WORKBENCH))
        self.proc = subprocess.Popen([str(py), str(Path(__file__).with_name("dub_vox_worker.py")), str(WORKBENCH)],
                                     cwd=str(WORKBENCH), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=CREATE_NO_WINDOW)
        hello = self._read()
        if not hello.get("ready") or hello.get("missing"):
            raise RecapError("missing_model", "Burma Cat (VoxCPM2) engine မစနိုင်ပါ။ Voice Workbench ကို ဖွင့်စစ်ပါ။", str(hello))
        self.voices = hello.get("voices", [])
        self.io = threading.Lock()

    def _read(self) -> dict:
        line = self.proc.stdout.readline() if self.proc.stdout else ""
        if not line:
            raise RecapError("tts_failed", "Burma Cat engine ရပ်သွားပါတယ်။ ပြန်စမ်းပါ။")
        return json.loads(line)

    @classmethod
    def get(cls) -> "VoxClient":
        with cls._lock:
            if cls._inst is None or cls._inst.proc.poll() is not None:
                cls._inst = VoxClient()
            return cls._inst

    @classmethod
    def close(cls) -> None:
        with cls._lock:
            if cls._inst and cls._inst.proc.poll() is None:
                cls._inst.proc.kill()
            cls._inst = None

    def synth(self, text: str, voice_id: str, out: Path, model: str = "lite") -> float:
        with self.io:
            self.proc.stdin.write(json.dumps({"text": text, "voice_id": voice_id, "model": model, "out": str(out)},
                                             ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
            r = self._read()
        if not r.get("ok"):
            raise RecapError("tts_failed", "Burma Cat အသံထုတ်လို့ မရပါ။ စာသားကို စစ်ပြီး ပြန်စမ်းပါ။", r.get("error", ""))
        return float(r["seconds"])


_BC_FALLBACK = [{"id": "zayar", "name": "Zayar"}, {"id": "builtin-aung", "name": "Aung"}, {"id": "builtin-may", "name": "May"},
                {"id": "builtin-phyoe", "name": "Phyoe"}, {"id": "builtin-thiri", "name": "Thiri"}]


def voices() -> list[dict]:
    """Burmese voices for the Dubbing page: Burma Cat clones first (local), then the app's other Burmese voices."""
    out = []
    if (WORKBENCH / "engine.py").exists():
        refs = Path(os.environ.get("LOCALAPPDATA", "")) / "Voice Workbench" / "References" / "Zayar.wav"
        for v in _BC_FALLBACK:
            if v["id"] == "zayar" and not refs.exists():
                continue
            out.append({"id": "bc:" + v["id"], "name": f"{v['name']} · Burma Cat", "engine": "VoxCPM2 (local)"})
    out += [{"id": "male_calm", "name": "Nara ကျား", "engine": "Nara Mini (local, မြန်)"},
            {"id": "female_warm", "name": "Nara မ", "engine": "Nara Mini (local, မြန်)"},
            {"id": "edge_thiha", "name": "Thiha", "engine": "Microsoft (online)"},
            {"id": "edge_nilar", "name": "Nilar", "engine": "Microsoft (online)"}]
    return out


def voice_rate(voice: str) -> float:
    """Burmese syllables per second of a voice (measured on earlier jobs; a safe guess before that)."""
    from .tts import RATE_FILE
    try:
        rates = json.loads(RATE_FILE.read_text("utf-8")) if RATE_FILE.exists() else {}
    except (OSError, ValueError):
        rates = {}
    return float(rates.get(voice, 4.2 if voice.startswith("bc:") else 4.8))


def _remember_rate(voice: str, rate: float) -> None:
    from .tts import RATE_FILE
    try:
        rates = json.loads(RATE_FILE.read_text("utf-8")) if RATE_FILE.exists() else {}
        rates[voice] = round(0.5 * rates.get(voice, rate) + 0.5 * rate, 3)
        RATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        RATE_FILE.write_text(json.dumps(rates, indent=2), "utf-8")
    except (OSError, ValueError):
        pass


def _to_48k(src: Path, dst: Path, tempo: float = 1.0) -> None:
    af = "loudnorm=I=-17:TP=-1.5:LRA=11" + (f",atempo={tempo:.4f}" if tempo > 1.001 else "")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", str(SR), "-ac", "1",
            "-c:a", "pcm_s16le", str(dst)])


def synth_line(job: Job, text: str, stem: str) -> dict:
    """One spoken line -> tts/<stem>_<hash>.wav (cached by text + voice)."""
    from . import tts
    o = job.opts
    voice = o["voice"]
    spoken = tts.prepare_text(text.replace("၊", "၊ "))
    h = hash_obj({"t": spoken, "v": voice, "m": o["vox_model"] if voice.startswith("bc:") else ""})
    out = job.path("tts", f"{stem}_{h}.wav")
    if not out.exists():
        for old in out.parent.glob(f"{stem}_*.wav"):
            old.unlink(missing_ok=True)
        if voice.startswith("bc:"):
            VoxClient.get().synth(spoken, voice[3:], out, o["vox_model"])
        else:
            tts.synth_any(spoken, voice, out, 1.0)
        tts.tighten_silence(out, max_pause=0.35)
    from .media import audio_duration
    return {"path": out, "seconds": audio_duration(out)}


def stage_voice(job: Job, prog) -> None:
    from .script import estimate_syllables
    data = job.read("lines.json")
    lines = data["lines"]
    todo = [x for x in lines if x["my"].strip()]
    syl = secs = 0.0
    for k, x in enumerate(todo):
        prog(k / max(1, len(todo)), f"မြန်မာအသံ ထုတ်နေပါတယ် {k + 1}/{len(todo)}")
        r = synth_line(job, x["my"], f"line_{x['id']:03d}")
        x["tts"] = f"tts/{r['path'].name}"
        x["tts_seconds"] = round(r["seconds"], 3)
        syl += estimate_syllables(x["my"])
        secs += r["seconds"]
    if job.opts["intro"] and data.get("hook"):
        r = synth_line(job, data["hook"], "hook")
        data["hook_tts"], data["hook_seconds"] = f"tts/{r['path'].name}", round(r["seconds"], 3)
    if secs > 3:
        _remember_rate(job.opts["voice"], syl / secs)
    job.write("lines.json", data)


# ====================================================================================== 6 timing plan
def plan_timing(lines: list[dict], duration: float, intro: dict | None = None) -> dict:
    """Fit each Burmese line into its sentence slot: speed the voice up a little first (<= MAX_TEMPO), then slow the
    picture of that sentence (<= MAX_STRETCH). Returns picture segments (source a..b shown `factor` times longer) and
    where every voice clip starts on the new timeline."""
    segs: list[dict] = []
    voice: list[dict] = []
    t_out = 0.0
    if intro:
        f = max(0.6, min(1.6, intro["seconds"] / max(0.2, intro["b"] - intro["a"])))
        segs.append({"a": intro["a"], "b": intro["b"], "factor": round(f, 4), "out": 0.0, "intro": True})
        voice.append({"id": "hook", "path": intro["tts"], "at": 0.05, "tempo": 1.0, "seconds": intro["seconds"]})
        t_out = (intro["b"] - intro["a"]) * f
    spoken = [x for x in lines if x.get("tts")]
    cuts = [0.0] + [x["start"] for x in spoken[1:]] + [duration] if spoken else [0.0, duration]
    if spoken and spoken[0]["start"] > 0.35:  # lead-in before the first word keeps its own speed
        segs.append({"a": 0.0, "b": spoken[0]["start"], "factor": 1.0, "out": t_out})
        t_out += spoken[0]["start"]
        cuts[0] = spoken[0]["start"]
    busy_until = (voice[-1]["at"] + voice[-1]["seconds"]) if voice else -1.0
    for i, x in enumerate(spoken):
        a, b = cuts[i], max(cuts[i + 1], cuts[i] + 0.05)
        lead = max(0.0, x["start"] - a)            # the line starts where the original narrator started
        slot = (b - a) - lead
        d = float(x["tts_seconds"])
        tempo = min(MAX_TEMPO, max(1.0, d / max(0.2, slot - 0.08)))
        d2 = d / tempo
        factor = min(MAX_STRETCH, max(1.0, (d2 + 0.08 + lead) / (b - a)))
        at = max(t_out + lead * factor, busy_until + 0.06)
        segs.append({"a": a, "b": b, "factor": round(factor, 4), "out": round(t_out, 4)})
        voice.append({"id": x["id"], "path": x["tts"], "at": round(at, 3), "tempo": round(tempo, 4), "seconds": round(d2, 3)})
        busy_until = at + d2
        t_out += (b - a) * factor
    if not spoken:
        segs.append({"a": 0.0, "b": duration, "factor": 1.0, "out": t_out})
        t_out += duration
    return {"segments": segs, "voice": voice, "duration": round(max(t_out, busy_until + 0.2), 3)}


# ====================================================================================== captions (ASS)
_PUNCT = "။၊,.!?…\"'“”"


def chunk_caption(my: str, max_chars: int = 14) -> list[str]:
    """Burmese line -> short pop chunks (the translator already put spaces between phrases)."""
    out: list[str] = []
    for tok in my.split():
        if out and display_len(out[-1]) + display_len(tok) + 1 <= max_chars and not out[-1].rstrip().endswith(("။", "?", "!")):
            out[-1] = out[-1] + " " + tok
        else:
            out.append(tok)
    return [c.strip().strip(_PUNCT + " ") or c.strip() for c in out if c.strip()]


def _keywords(kw: str) -> list[str]:
    """Highlight phrases: short ones only (a model that returns half the sentence would turn everything yellow)."""
    out = []
    for k in re.split(r"[|,၊/]", kw):
        toks = k.strip(_PUNCT + " ").split()
        if toks:
            out.append(" ".join(toks[-2:]) if display_len(" ".join(toks[-2:])) <= 12 else toks[-1])
    return out[:2]


def _ass_ts(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(lines: list[dict], plan: dict, cap: dict, o: dict, hook: str = "") -> tuple[str, list[dict]]:
    from .captions import text_width
    from .script import estimate_syllables
    W, H = cap["w"], cap["h"]
    th = float(cap.get("text_h") or H * 0.03)
    cx, cy = float(cap.get("cx") or W / 2), float(cap.get("cy") or H * 0.72)
    cx = W / 2 if abs(cx - W / 2) < W * 0.08 else cx
    # libass Fontsize = ascent + descent of the font; Noto Sans Myanmar's letters fill about 45% of that
    size = int(max(36, min(H * 0.075, th * 2.05)) * float(o.get("caption_scale", 1.0)))
    bord = max(3, round(size * 0.085))
    font = "Noto Sans Myanmar"
    hdr = ("[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
           f"PlayResX: {W}\nPlayResY: {H}\nYCbCr Matrix: TV.709\n\n[V4+ Styles]\n"
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
           "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           f"Style: Pop,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,{bord},{max(1, bord // 3)},5,20,20,20,1\n"
           f"Style: Hook,{font},{int(size * 1.25)},&H0000E6FF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,{bord + 1},{max(1, bord // 3)},5,20,20,20,1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    max_px = W * 0.88
    by = {v["id"]: v for v in plan["voice"]}
    cues: list[dict] = []
    ev: list[str] = []

    def fit(text: str, sz: int) -> str:
        w = text_width(text, font, True, sz) + 2 * bord
        if w <= max_px:
            return ""
        k = max(55, int(100 * max_px / w))
        return f"\\fscx{k}\\fscy{k}"

    def pop(k: int = 100) -> str:
        return (f"\\fscx{int(k * 0.72)}\\fscy{int(k * 0.72)}\\t(0,70,\\fscx{int(k * 1.08)}\\fscy{int(k * 1.08)})"
                f"\\t(70,130,\\fscx{k}\\fscy{k})")

    if hook and "hook" in by:
        v = by["hook"]
        chunks = chunk_caption(hook, 16)
        wts = [estimate_syllables(c) for c in chunks]
        t = v["at"]
        for c, wt in zip(chunks, wts):
            d = v["seconds"] * wt / sum(wts)
            k = re.search(r"fscx(\d+)", fit(c, int(size * 1.25)) or "fscx100").group(1)
            ev.append(f"Dialogue: 1,{_ass_ts(t)},{_ass_ts(t + d)},Hook,,0,0,0,,{{\\an5\\pos({W / 2:.0f},{H * 0.42:.0f}){pop(int(k))}}}{c}")
            t += d
    for x in lines:
        v = by.get(x["id"])
        if not v:
            continue
        chunks = chunk_caption(x["my"], int(o.get("max_chars", 14)))
        if not chunks:
            continue
        wts = [estimate_syllables(c) for c in chunks]
        kws = _keywords(x.get("kw") or "") if o.get("highlight") else []
        t = v["at"]
        for j, (c, wt) in enumerate(zip(chunks, wts)):
            d = v["seconds"] * wt / sum(wts)
            end = t + d + (0.12 if j == len(chunks) - 1 else 0.0)
            k = int(re.search(r"fscx(\d+)", fit(c, size) or "fscx100").group(1))
            txt = c
            hot = any(kw in c or (c in kw and display_len(c) >= 3) for kw in kws)
            if hot:  # colour only the key phrase when the chunk holds more than that
                kw = next((q for q in kws if q in c), "")
                txt = (c.replace(kw, "{\\c&H0000E6FF&}" + kw + "{\\c&H00FFFFFF&}", 1) if kw else "{\\c&H0000E6FF&}" + c)
            ev.append(f"Dialogue: 0,{_ass_ts(t)},{_ass_ts(end)},Pop,,0,0,0,,{{\\an5\\pos({cx:.0f},{cy:.0f}){pop(k)}}}{txt}")
            cues.append({"start": round(t, 3), "end": round(end, 3), "text": c, "line": x["id"], "hot": hot})
            t += d
    return hdr + "\n".join(ev) + "\n", cues


# ====================================================================================== text removal
def _pad(b: list[int], th: float, W: int, H: int) -> tuple[int, int, int, int]:
    px, py = int(th * 0.45 + 8), int(th * 0.32 + 6)
    return max(0, b[0] - px), max(0, b[1] - py), min(W, b[2] + px), min(H, b[3] + py)


def remove_text(frame: np.ndarray, boxes: list[list[int]], th: float, mode: str = "auto") -> np.ndarray:
    """Cover caption text inside `boxes` (in place). inpaint: only the glyph pixels (bright fill + dark outline) are
    repainted from their surroundings; blur: the whole box is blurred with a soft edge; auto: inpaint, and blur instead
    when the background is too bright or busy for a clean glyph mask."""
    import cv2
    H, W = frame.shape[:2]
    for b in boxes:
        x0, y0, x1, y1 = _pad(b, th, W, H)
        roi = frame[y0:y1, x0:x1]
        if roi.size == 0:
            continue
        use_blur = mode == "blur"
        if not use_blur:
            v = roi.max(axis=2)
            lo = roi.min(axis=2)
            fill = ((v > 205) & (lo > 150)).astype(np.uint8)            # white / near-white letters
            sat = ((v > 200) & (v.astype(np.int16) - lo > 90)).astype(np.uint8)  # coloured (yellow, green...) letters
            fill = cv2.bitwise_or(fill, sat)
            frac = float(fill.mean())
            if mode == "auto" and (frac > 0.42 or frac < 0.004):
                use_blur = True
            else:
                k = max(3, int(th * 0.2) | 1)
                near = cv2.dilate(fill, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 2 + 1, k * 2 + 1)))
                dark = ((v < 75).astype(np.uint8)) & near                 # the outline / drop shadow around them
                mask = cv2.dilate(cv2.bitwise_or(fill, dark), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
                if mode == "auto" and float(mask.mean()) > 0.6:
                    use_blur = True
                else:
                    small = max(1, int(round(th / 40)))                   # inpaint at reduced size: faster and smoother
                    if small > 1:
                        r2 = cv2.resize(roi, (roi.shape[1] // small, roi.shape[0] // small), interpolation=cv2.INTER_AREA)
                        m2 = cv2.resize(mask, (r2.shape[1], r2.shape[0]), interpolation=cv2.INTER_NEAREST)
                        m2 = cv2.dilate(m2, np.ones((3, 3), np.uint8))
                        fixed = cv2.resize(cv2.inpaint(r2, m2 * 255, 4, cv2.INPAINT_TELEA), (roi.shape[1], roi.shape[0]),
                                           interpolation=cv2.INTER_LINEAR)
                    else:
                        fixed = cv2.inpaint(roi, mask * 255, 4, cv2.INPAINT_TELEA)
                    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 2.5)[..., None]
                    soft = np.clip(soft * 1.6, 0, 1)
                    roi[:] = (fixed * soft + roi * (1 - soft)).astype(np.uint8)
        if use_blur:
            k = max(15, int(th * 1.3) | 1)
            blur = cv2.GaussianBlur(roi, (k, k), 0)
            blur = cv2.GaussianBlur(blur, (k, k), 0)
            a = np.zeros(roi.shape[:2], np.float32)
            m = max(2, int(th * 0.25))
            a[m:-m or None, m:-m or None] = 1.0
            a = cv2.GaussianBlur(a, (0, 0), m * 0.6)[..., None]
            roi[:] = (blur * a + roi * (1 - a)).astype(np.uint8)
    return frame


def boxes_at(cap: dict, f: int, _cache: dict = {}) -> list[list[int]]:
    """Boxes to cover on source frame f: the union of the nearest tracked samples before and after it."""
    key = id(cap)
    if key not in _cache:
        _cache.clear()
        _cache[key] = sorted(int(k) for k in cap["boxes"])
    ks = _cache[key]
    step = int(cap.get("step", 1))
    out: list[list[int]] = []
    i = bisect.bisect_left(ks, f - step)
    while i < len(ks) and ks[i] <= f + step:
        out += cap["boxes"][str(ks[i])]
        i += 1
    return out


# ====================================================================================== 7 render
def _bed_track(job: Job, plan: dict) -> np.ndarray:
    """Music / SFX bed stretched exactly like the picture (pitch kept)."""
    import soundfile as sf
    bed = job.path("bed.wav")
    segs = plan["segments"]
    if all(abs(s["factor"] - 1) < 1e-3 for s in segs) and not any(s.get("intro") for s in segs):
        x, _ = sf.read(str(bed), dtype="float32", always_2d=True)
        return x
    parts, labels = [], []
    for i, s in enumerate(segs):
        tempo = 1.0 / s["factor"]
        chain = f"[0:a]atrim={s['a']:.4f}:{s['b']:.4f},asetpts=PTS-STARTPTS"
        if abs(tempo - 1) > 1e-3:
            chain += f",atempo={tempo:.5f}"
        parts.append(chain + f"[s{i}]")
        labels.append(f"[s{i}]")
    out = job.path("_bed_fit.wav")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(segs)}:v=0:a=1[o]"
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(bed), "-filter_complex", graph, "-map", "[o]",
            "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    x, _ = sf.read(str(out), dtype="float32", always_2d=True)
    return x


def _mix(job: Job, plan: dict) -> Path:
    import soundfile as sf
    o = job.opts
    n = int(plan["duration"] * SR) + SR // 2
    mix = np.zeros((n, 2), dtype=np.float32)
    if o["bed"] == "keep":
        bed = _bed_track(job, plan)[:n]
        mix[: len(bed)] += bed * float(o["bed_gain"])
    for v in plan["voice"]:
        tmp = job.path("tts", f"_fit_{v['id']}.wav")
        _to_48k(job.dir / v["path"], tmp, v["tempo"])
        x, _ = sf.read(str(tmp), dtype="float32", always_2d=True)
        a = int(v["at"] * SR)
        x = x[: max(0, n - a)]
        mix[a: a + len(x)] += x  # mono -> both channels
        tmp.unlink(missing_ok=True)
    peak = float(np.abs(mix).max()) or 1.0
    if peak > 0.97:
        mix *= 0.97 / peak
    out = job.path("mix.wav")
    sf.write(str(out), mix[: int(plan["duration"] * SR)], SR, subtype="PCM_16")
    return out


def _encoder() -> list[str]:
    """The app's final-quality encoder, capped lower: a short for phones does not need 25 Mbit/s."""
    args = video_encoder_args()
    for flag, val in (("-cq", "21"), ("-maxrate", "12M"), ("-bufsize", "24M"), ("-crf", "20")):
        if flag in args:
            args[args.index(flag) + 1] = val
    return args


def stage_render(job: Job, prog) -> None:
    import cv2
    o = job.opts
    data = job.read("lines.json")
    cap = job.read("captions.json")
    fps, W, H, nsrc = float(cap["fps"]), int(cap["w"]), int(cap["h"]), int(cap["frames"])
    intro = None
    if o["intro"] and data.get("hook_tts"):
        ln = data["lines"][data.get("hook_line", 0)]
        a = max(0.0, ln["start"])
        intro = {"a": a, "b": min(nsrc / fps, a + max(1.2, min(3.5, data["hook_seconds"] + 0.3))), "tts": data["hook_tts"],
                 "seconds": data["hook_seconds"]}
    plan = plan_timing(data["lines"], nsrc / fps, intro)
    job.write("plan.json", plan)
    for v in plan["voice"]:
        if v["id"] != "hook" and v["tempo"] >= MAX_TEMPO - 1e-3:
            ln = next(x for x in data["lines"] if x["id"] == v["id"])
            nxt = next((s for s in plan["segments"] if not s.get("intro") and abs(s["a"] - ln["start"]) < 0.36), None)
            if nxt and nxt["factor"] >= MAX_STRETCH - 1e-3:
                job.warn(f"Line {ln['id'] + 1} က ရှည်လွန်းလို့ နောက်စာကြောင်းဘက် နည်းနည်း ကျော်သွားနိုင်ပါတယ် — စာကို တိုပေးပါ။")
    prog(0.02, "အသံ ပေါင်းနေပါတယ်")
    mix = _mix(job, plan)
    ass_text, cues = build_ass(data["lines"], plan, cap, o, data.get("hook", "") if intro else "")
    ass = job.path("captions.ass")
    ass.write_text(ass_text, "utf-8")
    job.write("cues.json", cues)
    fonts = f":fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'" if FONTS_DIR.exists() else ""
    out = job.path("final.tmp.mp4")
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps:.6f}",
           "-i", "-", "-i", str(mix), "-vf", f"subtitles=filename='{ffmpeg_filter_path(ass)}'{fonts}:shaping=complex",
           *_encoder(), "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
    errf = open(job.path("ffmpeg.log"), "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errf, creationflags=CREATE_NO_WINDOW)
    vc = cv2.VideoCapture(str(job.source))
    mode = o["remove"] if cap.get("found") else "none"
    th = float(cap.get("text_h") or 40)
    segs = plan["segments"]
    total = int(round(plan["duration"] * fps))
    cur, frame, si = -1, None, 0
    seg_out_end = [s["out"] + (s["b"] - s["a"]) * s["factor"] for s in segs]
    try:
        for n in range(total):
            t = n / fps
            while si < len(segs) - 1 and t >= seg_out_end[si]:
                si += 1
            s = segs[si]
            src_t = min(s["b"] - 0.5 / fps, s["a"] + max(0.0, t - s["out"]) / s["factor"])
            idx = max(0, min(nsrc - 1, int(src_t * fps + 1e-6)))
            if idx != cur:
                if idx < cur or idx > cur + 90:
                    vc.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    cur = idx - 1
                ok = True
                while cur < idx and ok:
                    ok = vc.grab()
                    cur += 1
                ok, f2 = vc.retrieve() if ok else (False, None)
                if ok:
                    frame = f2
                    if mode != "none":
                        bx = boxes_at(cap, idx)
                        if bx:
                            remove_text(frame, bx, th, mode)
                cur = idx
            if frame is None:
                frame = np.zeros((H, W, 3), np.uint8)
            try:
                proc.stdin.write(frame.tobytes())
            except OSError as e:  # ffmpeg stopped reading: its log has the reason
                job.log(f"render pipe closed at frame {n}/{total}: {e!r}")
                break
            if n % 15 == 0:
                if proc.poll() is not None:
                    job.log(f"ffmpeg exited early at frame {n}/{total} (code {proc.returncode})")
                    break
                prog(0.05 + 0.95 * n / max(1, total), f"ဗီဒီယို ထုတ်နေပါတယ် {int(100 * n / max(1, total))}%")
    except Cancelled:
        proc.kill()
        raise
    finally:
        vc.release()
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.wait()
        errf.close()
    if proc.returncode != 0 or not out.exists() or n < total - 1:
        raise RecapError("stage_failed", "ဗီဒီယို render မအောင်မြင်ပါ။ Log ကို ကြည့်ပါ။", job.path("ffmpeg.log").read_text("utf-8")[-800:])
    final = job.path("final.mp4")
    out.replace(final)
    job.path("final.srt").write_text("\n".join(
        f"{i}\n{_srt(c['start'])} --> {_srt(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)), "utf-8")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{min(plan['duration'] * 0.3, 4):.2f}", "-i", str(final), "-frames:v", "1",
            "-vf", "scale=360:-2", "-q:v", "4", str(job.path("thumb.jpg"))])
    job.meta["out_duration"] = plan["duration"]


def _srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ====================================================================================== runner
STAGES: list[tuple[str, Callable, float]] = [
    ("audio", stage_audio, 0.10), ("transcribe", stage_transcribe, 0.08), ("captions", stage_captions, 0.14),
    ("translate", stage_translate, 0.08), ("voice", stage_voice, 0.30), ("render", stage_render, 0.30)]
JOBS: dict[str, Job] = {}
_run_lock = threading.Lock()  # one dubbing job at a time (GPU + the voice engine are shared)


def get(jid: str) -> Job:
    if not re.fullmatch(r"[a-z0-9]{6,32}", jid) or not (root() / jid / "job.json").exists():
        raise RecapError("not_found", "Dubbing job မတွေ့ပါ။")
    if jid not in JOBS:
        JOBS[jid] = Job(jid)
    return JOBS[jid]


def create(src: Path, title: str, opts: dict | None = None, move: bool = False) -> Job:
    jid = uuid.uuid4().hex[:12]
    job = Job(jid)
    ext = src.suffix.lower() if src.suffix.lower() in (".mp4", ".mkv", ".mov", ".webm", ".m4v") else ".mp4"
    dst = job.dir / f"source{ext}"
    (shutil.move if move else shutil.copy)(str(src), str(dst))
    info = probe(dst)
    job.meta.update(source=dst.name, title=title or src.stem, duration=float(info.get("duration") or 0),
                    opts={**DEFAULTS, **{k: v for k, v in (opts or {}).items() if k in DEFAULTS}})
    if job.meta["duration"] > 600:
        shutil.rmtree(job.dir, ignore_errors=True)
        raise RecapError("too_long", "Dubbing က ၁၀ မိနစ်အောက် short ဗီဒီယိုတွေအတွက်ပါ။")
    job.save()
    JOBS[jid] = job
    return job


def run(job: Job, from_stage: str = "audio") -> None:
    """Run the pipeline from `from_stage` (earlier stages use their cached files)."""
    names = [s[0] for s in STAGES]
    first = names.index(from_stage)
    job.cancel = False
    job.meta.update(state="queued", error="", message="တန်းစီနေပါတယ်", warnings=[] if first == 0 else job.meta.get("warnings", []))
    job.save()
    with _run_lock:
        job.meta.update(state="running", pid=os.getpid())
        t0 = time.time()
        try:
            done = sum(w for _, _, w in STAGES[:first])
            total = sum(w for _, _, w in STAGES)
            for name, fn, w in STAGES[first:]:
                job.meta["stage"] = name
                job.log(f"stage {name}")
                a, b = done / total, (done + w) / total
                fn(job, _span(job, a, b))
                job.progress(b)
                done += w
                if name == "translate" and job.opts["review"] and name != STAGES[-1][0]:
                    # review gate: the creator checks the Burmese (and picks a hook) before any voice time is spent
                    job.meta.update(state="review", message="ဘာသာပြန်ပြီးပါပြီ — စာကို စစ်/ပြင်ပြီး အသံထုတ်ပါ")
                    return
            job.meta.update(state="done", progress=1.0, message="ပြီးပါပြီ", seconds=round(time.time() - t0, 1))
        except Cancelled:
            job.meta.update(state="cancelled", message="ရပ်လိုက်ပါပြီ")
        except RecapError as e:
            job.meta.update(state="failed", error=e.message_my, message=e.message_my)
            job.log(f"ERROR {e.code}: {e.message_my}\n{e.detail or ''}")
        except Exception as e:  # noqa: BLE001
            import traceback
            job.meta.update(state="failed", error=f"{type(e).__name__}: {e}", message="မအောင်မြင်ပါ — Log ကို ကြည့်ပါ")
            job.log(traceback.format_exc())
        finally:
            job.save()


def start(job: Job, from_stage: str = "audio") -> None:
    threading.Thread(target=run, args=(job, from_stage), daemon=True, name=f"dub-{job.id}").start()


def update_lines(job: Job, lines: list[dict], hook: str | None = None, opts: dict | None = None) -> str:
    """Save edited Burmese lines / options; returns the stage to re-run from."""
    data = job.read("lines.json")
    if not data:
        raise RecapError("not_ready", "ဘာသာပြန် မပြီးသေးပါ။")
    by = {int(x["id"]): x for x in lines if "id" in x}
    for x in data["lines"]:
        e = by.get(x["id"])
        if e:
            x["my"] = " ".join(str(e.get("my", x["my"])).split())
            x["kw"] = str(e.get("kw", x.get("kw", ""))).strip()
    if hook is not None:
        data["hook"] = " ".join(hook.split())
    job.write("lines.json", data)
    old_tone = job.opts["tone"]
    if opts:
        job.meta["opts"] = {**job.opts, **{k: v for k, v in opts.items() if k in DEFAULTS}}
        job.save()
    if job.opts["tone"] != old_tone:  # another tone = another script: translate again (the edits above are replaced)
        (job.dir / "lines.json").replace(job.dir / f"lines.{old_tone}.json.bak")  # kept, so nothing typed is lost
        return "translate"
    return "voice"


def public(job: Job, full: bool = False) -> dict:
    m = job.meta
    d = {k: m.get(k) for k in ("id", "title", "created", "state", "stage", "progress", "message", "error", "warnings",
                               "duration", "out_duration", "seconds")}
    d["opts"] = job.opts
    d["final"] = (job.dir / "final.mp4").exists()
    d["thumb"] = (job.dir / "thumb.jpg").exists()
    if full:
        data = job.read("lines.json") or {}
        d["lines"] = [{k: x.get(k) for k in ("id", "start", "end", "en", "my", "kw", "tts_seconds")} for x in data.get("lines", [])]
        d["hook"] = data.get("hook", "")
        d["hooks"] = data.get("hooks", [])
        d["glossary"] = data.get("glossary", {})
        cap = job.read("captions.json") or {}
        d["captions"] = {k: cap.get(k) for k in ("found", "band", "text_h", "cx", "cy", "share")}
    return d


def list_jobs() -> list[dict]:
    out = []
    for f in root().glob("*/job.json"):
        try:
            out.append(public(get(f.parent.name)))
        except RecapError:
            pass
    return sorted(out, key=lambda x: -(x.get("created") or 0))


def _alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def recover() -> None:
    """Jobs left 'running' by a closed app are marked stopped (their cached stages are kept). A job that another
    running copy of the app is working on is left alone."""
    for f in root().glob("*/job.json"):
        try:
            j = get(f.parent.name)
        except RecapError:
            continue
        pid = j.meta.get("pid")
        if j.meta.get("state") in ("running", "queued") and not (pid and pid != os.getpid() and _alive(pid)):
            j.meta.update(state="cancelled", message="App ပိတ်သွားလို့ ရပ်သွားပါတယ် — ဆက်လုပ်ရန် နှိပ်ပါ")
            j.save()


def main() -> None:
    global STAGES
    import argparse
    ap = argparse.ArgumentParser(description="Dub an English short into Burmese")
    ap.add_argument("video", nargs="?")
    ap.add_argument("--job")
    ap.add_argument("--from", dest="frm", default="audio")
    ap.add_argument("--until", default="render")
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k}", default=None, type=(lambda s: s.lower() in ("1", "true", "yes")) if isinstance(v, bool) else type(v))
    a = ap.parse_args()
    opts = {k: getattr(a, k) for k in DEFAULTS if getattr(a, k) is not None}
    if a.job:
        job = get(a.job)
        if opts:
            job.meta["opts"] = {**job.opts, **opts}
    else:
        job = create(Path(a.video), "", opts)
    keep = STAGES
    names = [s[0] for s in STAGES]
    STAGES = STAGES[: names.index(a.until) + 1]
    try:
        run(job, a.frm)
    finally:
        STAGES = keep
        VoxClient.close()
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(public(job), ensure_ascii=False, indent=1))
    print(job.dir)


if __name__ == "__main__":
    main()
