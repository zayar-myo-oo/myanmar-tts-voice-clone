"""Stage 4: story analysis + Burmese recap script (AI Recap) and
Stage 4b: per-line translation (Pro AI Recap).

Everything is written so a 90-minute episode is processed in chunks with a
persistent story memory, and the character table is shared across episodes
(series memory lives in projects/_series/<series_id>.json).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .burmese import display_len, norm_for, normalize
from .errors import RecapError
from .llm import chat_json, unload
from .pipeline import Context, gpu_lock

CHUNK_SECONDS = 180.0

STYLE_HINTS = {
    "storyteller": "warm, gripping storyteller voice like a popular Burmese movie-recap channel",
    "calm": "calm, measured narration with gentle pauses",
    "suspense": "suspenseful narration with short sentences and dramatic pauses",
    "energetic": "fast, energetic narration with punchy short sentences",
    "documentary": "neutral documentary narration",
}

LANG_NAME = {"my": "Burmese (Myanmar Unicode)", "en": "English", "th": "Thai"}
NAME_RULE = {  # what the character table's display name ("my" field) holds for each output language
    "my": "Burmese transliteration in Myanmar script that stays fixed forever",
    "en": "English name that stays fixed forever: pinyin for real names (林渊 -> Lin Yuan), short English label for "
          "descriptive ones (年轻男子 -> the young man)",
    "th": "Thai transliteration in Thai script that stays fixed forever",
}
STYLE_EXAMPLE = {
    "my": "ဒီကောင်လေးက သူ့အဖေ ဘယ်သူလဲဆိုတာ မသိဘဲ ကြီးလာခဲ့တာ။ ဒါပေမဲ့ တစ်နေ့မှာတော့ ...",
    "en": "This kid grew up never knowing who his father was. But one day...",
    "th": "เด็กคนนี้โตมาโดยไม่รู้เลยว่าพ่อของเขาคือใคร แต่แล้ววันหนึ่ง...",
}


def _has_script(s: str, lang: str) -> bool:
    if lang == "my":
        return any("\u1000" <= ch <= "\u109f" for ch in s)
    if lang == "th":
        return any("\u0e00" <= ch <= "\u0e7f" for ch in s)
    return bool(s) and not any("\u4e00" <= ch <= "\u9fff" for ch in s) and any(ch.isalpha() for ch in s)


# ------------------------------------------------------------------ helpers
def fmt_t(t: float) -> str:
    return f"{t:.1f}"


def evidence_lines(cues: list[dict], shots: list[dict], captions: dict[str, str], a: float, b: float) -> list[str]:
    items: list[tuple[float, str]] = []
    for c in cues:
        if c["end"] >= a and c["start"] < b:
            items.append((c["start"], f"[{fmt_t(c['start'])}-{fmt_t(c['end'])}] SAY({c.get('source')}): {c['text']}"))
    for s in shots:
        cap = captions.get(str(s["id"]))
        if cap and s["end"] >= a and s["start"] < b:
            items.append((s["start"], f"[{fmt_t(s['start'])}-{fmt_t(s['end'])}] SEE(shot {s['id']}): {cap}"))
    items.sort(key=lambda x: x[0])
    return [x[1] for x in items]


def series_memory_path(ctx: Context) -> Path | None:
    sid = ctx.project.manifest.source.get("series_id")
    if not sid:
        return None
    return ctx.project.root.parent / "_series" / f"{sid}.json"


def load_series_memory(ctx: Context) -> dict:
    p = series_memory_path(ctx)
    if p and p.exists():
        return json.loads(p.read_text("utf-8"))
    return {"characters": [], "events": [], "episodes": []}


def save_series_memory(ctx: Context, mem: dict) -> None:
    p = series_memory_path(ctx)
    if not p:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mem, ensure_ascii=False, indent=2), "utf-8")


# ------------------------------------------------------------------ schemas
CHAR_SCHEMA = {"type": "object", "properties": {
    "zh": {"type": "string"}, "my": {"type": "string"}, "role": {"type": "string"},
    "gender": {"type": "string"}, "relations": {"type": "string"}}, "required": ["zh", "my", "role"]}

MEMORY_SCHEMA = {"type": "object", "properties": {
    "characters": {"type": "array", "items": CHAR_SCHEMA},
    "events": {"type": "array", "items": {"type": "object", "properties": {
        "start": {"type": "number"}, "end": {"type": "number"}, "summary": {"type": "string"},
        "characters": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": "integer"}, "visual": {"type": "boolean"}},
        "required": ["start", "end", "summary", "importance"]}},
    "so_far": {"type": "string"}}, "required": ["characters", "events", "so_far"]}

BEATS_SCHEMA = {"type": "object", "properties": {"beats": {"type": "array", "items": {"type": "object", "properties": {
    "narration": {"type": "string"}, "source_ranges": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
    "characters": {"type": "array", "items": {"type": "string"}}, "visual_query": {"type": "string"},
    "why_this_clip": {"type": "string"}, "importance": {"type": "integer"}},
    "required": ["narration", "source_ranges", "visual_query", "importance"]}}}, "required": ["beats"]}

REVIEW_SCHEMA = {"type": "object", "properties": {
    "checklist": {"type": "object", "properties": {
        "invented_events": {"type": "string"}, "name_consistency": {"type": "string"},
        "natural_spoken": {"type": "string"}, "hook_first_3s": {"type": "string"},
        "cause_and_effect": {"type": "string"}}},
    "notes": {"type": "string"}, "beats": BEATS_SCHEMA["properties"]["beats"]},
    "required": ["checklist", "notes", "beats"]}

HOOKS_SCHEMA = {"type": "object", "properties": {"hooks": {"type": "array", "items": {"type": "string"}}},
                "required": ["hooks"]}


# ------------------------------------------------------------------ story memory
def build_story_memory(ctx: Context, cues: list[dict], shots: list[dict], captions: dict[str, str]) -> dict:
    model = ctx.settings.llm_model
    dur = float(ctx.project.manifest.source.get("probe", {}).get("duration") or 0)
    series = load_series_memory(ctx)
    mem = {"characters": list(series.get("characters", [])), "events": [], "so_far": ""}
    n = max(1, int(np.ceil(dur / CHUNK_SECONDS)))
    for k in range(n):
        a, b = k * CHUNK_SECONDS, min(dur, (k + 1) * CHUNK_SECONDS)
        ctx.progress(0.05 + 0.4 * k / n, f"ဇာတ်လမ်းကို နားလည်အောင် ဖတ်နေပါတယ် ({k + 1}/{n})")
        lines = evidence_lines(cues, shots, captions, a, b)
        if not lines:
            continue
        system = ("You are a meticulous story analyst for Chinese dramas. You read timestamped evidence "
                  "(SAY = dialogue/subtitles in Chinese, SEE = visual description of a shot) and keep a story memory. "
                  "Only record events supported by the evidence. Never invent events.")
        user = (f"Known characters (keep these names EXACTLY; add new ones only when clearly a new person):\n"
                f"{json.dumps(mem['characters'], ensure_ascii=False)}\n\n"
                f"Story so far: {mem['so_far'] or '(start)'}\n\n"
                f"Evidence for {fmt_t(a)}s-{fmt_t(b)}s:\n" + "\n".join(lines[:700]) +
                "\n\nReturn JSON: characters = FULL updated table (zh = Chinese name or descriptive label like 男主, "
                f"my = {NAME_RULE[ctx.settings.language]}, role, gender, relations); "
                "events = the important events in THIS window with start/end seconds taken from evidence, "
                "an English summary, characters involved (zh names), importance 1-5, visual=true if the event is "
                "mainly visible rather than spoken (slap, look, reveal). Never add a descriptive label (男主, 年轻女性) "
                "for someone who already has a real name in the table; use the real name. relations must state "
                "family/romantic ties explicitly (e.g. 'claims to be 林渊's daughter'). so_far = updated 3-6 sentence English "
                "summary of the whole story so far including motivations and cause/effect.")
        out = chat_json(model, system, user, MEMORY_SCHEMA, temperature=0.3)
        mem["characters"] = _merge_chars(mem["characters"], out.get("characters", []))
        for e in out.get("events", []):
            e["start"] = float(max(a - 5, min(b, e.get("start", a))))
            e["end"] = float(max(e["start"] + 0.5, min(b + 5, e.get("end", e["start"] + 3))))
            mem["events"].append(e)
        mem["so_far"] = out.get("so_far", mem["so_far"])
        ctx.project.write_json("script/story_memory.json", mem)
    return mem


def _merge_chars(old: list[dict], new: list[dict]) -> list[dict]:
    """Existing Burmese names never change; new characters are appended."""
    by_zh = {c["zh"]: c for c in old}
    for c in new:
        if not c.get("zh"):
            continue
        if c["zh"] in by_zh:
            keep = by_zh[c["zh"]]
            for k in ("role", "gender", "relations"):
                if c.get(k) and not keep.get(k):
                    keep[k] = c[k]
        else:
            c["my"] = normalize(c.get("my", "")) or c["zh"]
            by_zh[c["zh"]] = c
    return list(by_zh.values())


NAMES_SCHEMA = {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "object", "properties": {
    "zh": {"type": "string"}, "my": {"type": "string"}}, "required": ["zh", "my"]}}}, "required": ["names"]}


def _has_my(s: str) -> bool:
    return any("က" <= ch <= "႟" for ch in s)


NAME_EXAMPLE = {"my": "林渊 -> လင်ယွမ်; 年轻男子 -> လူငယ်လေး, 中年男子 -> လူလတ်ပိုင်း. Myanmar script only.",
                "en": "林渊 -> Lin Yuan; 年轻男子 -> the young man, 中年男子 -> the middle-aged man. Latin letters only.",
                "th": "林渊 -> หลินหยวน; 年轻男子 -> ชายหนุ่ม, 中年男子 -> ชายวัยกลางคน. Thai script only."}


def burmese_names(model: str, chars: list[dict], lang: str = "my") -> list[dict]:
    """Make sure every character has a display name in the output language's script (the LLM often
    returns pinyin/English). Names already in that script are never changed (cross-episode consistency)."""
    todo = [c for c in chars if not _has_script(c.get("my", ""), lang)]
    if not todo:
        return chars
    out = chat_json(model, f"You name Chinese drama characters in {LANG_NAME[lang]}.",
                    "For each, give a short natural name: transliterate real names by sound, translate descriptive "
                    f"labels. Examples: {NAME_EXAMPLE[lang]}\n" + json.dumps([{"zh": c["zh"], "hint": c.get("my", "")}
                                                                             for c in todo], ensure_ascii=False)
                    + "\nReturn JSON {names:[{zh,my}]} (my = the name).", NAMES_SCHEMA, temperature=0.2)
    got = {x["zh"]: norm_for(x["my"], lang) for x in out.get("names", []) if _has_script(x.get("my", ""), lang)}
    for c in todo:
        if c["zh"] in got:
            c["alias"] = c.get("my", "")
            c["my"] = got[c["zh"]]
    return chars


def _to_simplified(text: str) -> str:
    try:
        from opencc import OpenCC  # opencc-python-reimplemented
        return OpenCC("t2s").convert(text)
    except ImportError:
        return text


def apply_names(text: str, chars: list[dict], lang: str = "my") -> str:
    """Force the fixed Burmese name wherever the LLM left a Chinese name (trad/simplified),
    its pinyin, or an English alias."""
    text = _to_simplified(text)
    import re as _re
    if lang != "th":
        text = _re.sub(r"[฀-๿]+", "", text)  # stray Thai glyphs the LLM sometimes mixes in
    for c in sorted(chars, key=lambda c: -len(c.get("zh", ""))):
        if c.get("alias") and c.get("my"):
            text = text.replace(c["alias"], c["my"])
        zh, my = c.get("zh", ""), c.get("my", "")
        if not zh or not my or zh == my:
            continue
        text = text.replace(zh, my)
        try:
            from pypinyin import lazy_pinyin  # optional
            py = " ".join(w.capitalize() for w in lazy_pinyin(zh))
            text = text.replace(py, my).replace(py.replace(" ", ""), my)
        except ImportError:
            pass
    return text


# ------------------------------------------------------------------ recap writing
def target_syllables(ctx: Context, rate_sps: float) -> int:
    # ~8% of time is pauses between beats
    return int(ctx.settings.target_seconds * 0.92 * rate_sps)


def write_recap(ctx: Context, mem: dict, rate_sps: float) -> dict:
    s = ctx.settings
    model = s.llm_model
    lang = LANG_NAME[s.language]
    total_syl = target_syllables(ctx, rate_sps)
    n_beats = max(4, int(round(s.target_seconds / 9)))
    per_beat = max(15, total_syl // n_beats)
    names = "\n".join(f"- {c['zh']} => {c['my']} ({c.get('role', '')}; {c.get('relations', '')})" for c in mem["characters"])
    events = "\n".join(f"[{fmt_t(e['start'])}-{fmt_t(e['end'])}] (imp {e.get('importance', 3)}{', visual' if e.get('visual') else ''}) "
                       f"{e['summary']}" for e in mem["events"])
    system = (f"You write viral {lang} movie-recap narration. Style: {STYLE_HINTS[s.narration_style]}. "
              f"Write natural SPOKEN {lang}, like a person talking to friends, not textbook or formal written language. "
              "Use ONLY events listed. Never invent events, names, or outcomes.")
    rules = (f"Rules:\n1. Exactly about {n_beats} beats in story order. Each beat narration is ~{per_beat} {lang} syllables "
             f"(~{per_beat / rate_sps:.0f} seconds spoken).\n"
             "2. Beat 1 is a HOOK: the most shocking/intriguing moment or question, so viewers keep watching within 3 seconds.\n"
             "3. Keep relationships, motivations, major turns and cause->effect clear.\n"
             "4. Use the character names from the table (the name after =>) EXACTLY, every time.\n"
             "5. source_ranges: 1-3 [start,end] second ranges from the event list that SHOW what this beat says "
             "(prefer visual events for silent moments).\n"
             "6. visual_query: a short ENGLISH description of what the footage should show (for image search).\n"
             "7. If the episode ends on a cliffhanger, the last beat ends with a short 'what happens next?' hook.\n"
             "8. importance 1-5.\n"
             "9. NEVER repeat a sentence or phrase. Every beat must add a NEW event and move the story forward.\n"
             "10. Say who did what to whom and why (e.g. 'X found out Y lied, so X ...'). Avoid vague verbs like 'said'.\n"
             f"Style example ({lang}, tone only, do not copy content): \"{STYLE_EXAMPLE[s.language]}\"")
    user = f"Characters:\n{names}\n\nStory summary: {mem['so_far']}\n\nEvents:\n{events}\n\n{rules}\n\nReturn JSON {{beats:[...]}}."
    ctx.progress(0.5, "Recap script အကြမ်း ရေးနေပါတယ်")
    draft = chat_json(model, system, user, BEATS_SCHEMA, temperature=0.7)["beats"]
    ctx.progress(0.65, "Script ကို ပြန်စစ်ပြီး ပြင်နေပါတယ်")
    review_user = (f"Characters:\n{names}\n\nEvents (ground truth):\n{events}\n\nDRAFT beats:\n"
                   f"{json.dumps(draft, ensure_ascii=False)}\n\nReview the draft against this checklist and then return a "
                   "REVISED full beats list that fixes every problem:\n"
                   "- invented_events: anything not in the events list? remove it.\n"
                   "- name_consistency: every character uses the exact name from the table?\n"
                   f"- natural_spoken: does it sound like natural spoken {lang}? rewrite stiff/literal lines.\n"
                   "- hook_first_3s: is beat 1 a strong hook?\n"
                   "- cause_and_effect: is it clear why things happen?\n"
                   "- relationships: check EVERY claim of who is whose father/mother/child/spouse/lover and who did "
                   "what to whom against the events and the characters' relations; fix any that are wrong or swapped.\n"
                   f"Keep the same length budget (~{per_beat} syllables per beat, ~{n_beats} beats). "
                   "Fill checklist with a short verdict for each item, notes = what you changed.")
    review = chat_json(model, system, review_user, REVIEW_SCHEMA, temperature=0.4)
    ctx.progress(0.8, "အဖွင့် hook ၃ မျိုး ရေးနေပါတယ်")
    hooks_user = (f"Story summary: {mem['so_far']}\nEvents:\n{events}\nCharacters:\n{names}\n\n"
                  f"Write 3 DIFFERENT alternative opening hooks in natural spoken {lang} (each ~{per_beat} syllables), "
                  "each must make a viewer stop scrolling within 3 seconds and use only real events. "
                  "Use the names from the table exactly. Return JSON {hooks:[h1,h2,h3]}.")
    hooks = chat_json(model, system, hooks_user, HOOKS_SCHEMA, temperature=0.9).get("hooks", [])[:3]
    unload(model)
    return {"draft": draft, "review": {"checklist": review.get("checklist"), "notes": review.get("notes")},
            "final": review.get("beats") or draft, "hooks": hooks}


# ------------------------------------------------------------------ validation + ranking
def validate_ranges(ranges: list, duration: float, shots: list[dict]) -> list[list[float]]:
    """Clamp to [0,duration], drop invalid/tiny, snap to shot boundaries (within 0.6 s), merge overlaps."""
    bounds = sorted({0.0, duration, *[s["start"] for s in shots], *[s["end"] for s in shots]})
    out: list[list[float]] = []
    for r in ranges or []:
        if not isinstance(r, (list, tuple)) or len(r) < 2:
            continue
        try:
            a, b = float(r[0]), float(r[1])
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(a) and np.isfinite(b)):
            continue
        a, b = sorted((a, b))
        a, b = max(0.0, min(duration, a)), max(0.0, min(duration, b))
        if bounds:
            na = min(bounds, key=lambda x: abs(x - a))
            nb = min(bounds, key=lambda x: abs(x - b))
            a = na if abs(na - a) <= 0.6 else a
            b = nb if abs(nb - b) <= 0.6 else b
        if b - a < 0.5:
            continue
        out.append([round(a, 3), round(b, 3)])
    out.sort()
    merged: list[list[float]] = []
    for r in out:
        if merged and r[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    return merged


def rank_shots(beats: list[dict], shots: list[dict], clip_embs: np.ndarray | None, text_embs: np.ndarray | None,
               cues: list[dict]) -> None:
    """Attach `candidates` [{shot, score, sim, overlap}] to every beat, best first."""
    for bi, beat in enumerate(beats):
        ranges = beat["source_ranges"]
        cands = []
        for s in shots:
            ov = 0.0
            for a, b in ranges:
                inter = max(0.0, min(b, s["end"]) - max(a, s["start"]))
                ov = max(ov, inter / max(0.1, s["end"] - s["start"]))
            near = any(s["end"] >= a - 15 and s["start"] <= b + 15 for a, b in ranges)
            if not near and ranges:
                continue
            sim = 0.0
            if clip_embs is not None and text_embs is not None and s["id"] < len(clip_embs):
                sim = float(clip_embs[s["id"]] @ text_embs[bi])
            # transcript overlap: does dialogue in this shot share names with the beat?
            tov = 0.0
            names = [c for c in beat.get("characters", []) if c]
            if names:
                said = " ".join(c["text"] for c in cues if c["end"] >= s["start"] and c["start"] <= s["end"])
                tov = sum(1 for n in names if n in said) / len(names)
            score = 0.5 * ov + 0.35 * max(0.0, (sim - 0.15) / 0.2) + 0.15 * tov
            cands.append({"shot": s["id"], "start": s["start"], "end": s["end"], "score": round(score, 4),
                          "sim": round(sim, 4), "overlap": round(ov, 3), "transcript": round(tov, 3)})
        cands.sort(key=lambda c: -c["score"])
        beat["candidates"] = cands[:24]
        beat["clip_score"] = cands[0]["score"] if cands else 0.0


# ------------------------------------------------------------------ stage entry points
def script_inputs(ctx: Context) -> Any:
    s = ctx.settings
    p = ctx.project
    return {"tr": p.stage("transcribe").input_hash, "vis": p.stage("vision").input_hash, "mode": s.mode,
            "lang": s.language, "target": s.target_seconds, "style": s.narration_style, "llm": s.llm_model,
            "voice": s.voice_id, "series": p.manifest.source.get("series_id"), "v": 3}


def stage_script(ctx: Context) -> dict[str, str]:
    from .tts import speech_rate
    p = ctx.project
    cues = p.read_json("analysis/transcript.json", {}).get("cues", [])
    shots = p.read_json("analysis/shots.json", [])
    vision = p.read_json("analysis/vision.json", {})
    captions = vision.get("captions", {})
    dur = float(p.manifest.source.get("probe", {}).get("duration") or 0)
    if not cues and not captions:
        raise RecapError("no_story", "ဗီဒီယိုထဲမှာ စကားပြော (သို့) စာတန်းထိုး မတွေ့ပါ။ အသံပါတဲ့ ဗီဒီယို သုံးပါ။")
    with gpu_lock(p, f"llm:{ctx.settings.llm_model}"):
        mem = build_story_memory(ctx, cues, shots, captions)
        mem["characters"] = burmese_names(ctx.settings.llm_model, mem["characters"], ctx.settings.language)
        p.write_json("script/story_memory.json", mem)
        p.write_json("script/characters.json", mem["characters"])
        if ctx.settings.mode in ("pro", "subtitle"):
            segments = translate_lines(ctx, cues, mem)
            p.write_json("script/segments.json", segments)
            unload(ctx.settings.llm_model)
            beats = segments
            out = {"draft": None, "review": None, "hooks": []}
        else:
            rate = speech_rate(ctx.settings.voice_id)
            out = write_recap(ctx, mem, rate)
            beats = []
            for i, b in enumerate(out["final"]):
                text = apply_names(norm_for(b.get("narration", ""), ctx.settings.language), mem["characters"],
                                   ctx.settings.language)
                if not text:
                    continue
                beats.append({"id": i, "narration": text, "source_ranges": validate_ranges(b.get("source_ranges"), dur, shots),
                              "characters": b.get("characters", []), "visual_query": b.get("visual_query", ""),
                              "why_this_clip": b.get("why_this_clip", ""), "importance": int(b.get("importance", 3) or 3),
                              "voice_id": None})
            if not beats:
                raise RecapError("llm_failed", "Script ထဲမှာ beat မပါပါ။ Retry လုပ်ပါ။")
            # beats with no valid range: inherit neighbouring range so footage stays in story order
            for i, b in enumerate(beats):
                if not b["source_ranges"]:
                    prev = next((x["source_ranges"] for x in reversed(beats[:i]) if x["source_ranges"]), None)
                    b["source_ranges"] = [[prev[-1][1], min(dur, prev[-1][1] + 8)]] if prev else [[0.0, min(dur, 8.0)]]
            for i, b in enumerate(beats):
                b["id"] = i
    if ctx.settings.mode not in ("pro", "subtitle"):
        ctx.progress(0.9, "Beat တစ်ခုချင်းအတွက် အကောင်းဆုံး clip ရွေးနေပါတယ်")
        clip_embs = None
        f = p.path("analysis", "clip_frames.npy")
        if f.exists():
            clip_embs = np.load(f)
        text_embs = None
        if clip_embs is not None and len(clip_embs):
            from .analyze import embed_texts
            with gpu_lock(p, "clip-text"):
                text_embs = embed_texts([b["visual_query"] or "a scene from a drama" for b in beats])
        rank_shots(beats, shots, clip_embs, text_embs, cues)
        for b in beats:
            p.log(f"beat {b['id']}: best clip score {b['clip_score']:.3f} "
                  f"(shot {b['candidates'][0]['shot'] if b['candidates'] else '-'})")
        p.write_json("script/draft.json", out["draft"])
        p.write_json("script/review.json", out["review"])
        p.write_json("script/hooks.json", {"hooks": [norm_for(h, ctx.settings.language) for h in out["hooks"]],
                                           "original_first_beat": beats[0]["narration"]})
    p.write_json("script/beats.json", beats)
    # series memory: share the character table with later episodes
    if series_memory_path(ctx):
        sm = load_series_memory(ctx)
        sm["characters"] = _merge_chars(sm.get("characters", []), mem["characters"])
        sm.setdefault("episodes", []).append({"project": p.manifest.project_id, "summary": mem["so_far"]})
        save_series_memory(ctx, sm)
    p.reload()
    p.manifest.characters = mem["characters"]
    p.manifest.beats = [{k: v for k, v in b.items() if k != "candidates"} for b in beats]
    p.save()
    arts = {"beats": "script/beats.json", "memory": "script/story_memory.json", "characters": "script/characters.json"}
    if ctx.settings.mode not in ("pro", "subtitle"):
        arts |= {"draft": "script/draft.json", "review": "script/review.json", "hooks": "script/hooks.json"}
    return arts


# ------------------------------------------------------------------ Pro AI Recap
TRANS_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "integer"}, "text": {"type": "string"}, "speaker": {"type": "string"}},
    "required": ["id", "text"]}}}, "required": ["lines"]}


def dialogue_segments(cues: list[dict], duration: float) -> list[dict]:
    """One segment per spoken line; merge fragments < 0.8 s into a neighbour; slot ends at next start."""
    segs: list[dict] = []
    for c in sorted(cues, key=lambda x: x["start"]):
        if c["end"] - c["start"] < 0.25:
            continue
        if segs and (c["start"] - segs[-1]["source_end"] < 0.15) and (segs[-1]["source_end"] - segs[-1]["source_start"] < 0.8):
            segs[-1]["source_end"] = c["end"]
            segs[-1]["chinese"] += " " + c["text"]
            continue
        segs.append({"source_start": round(c["start"], 3), "source_end": round(c["end"], 3), "chinese": c["text"]})
    for i, s in enumerate(segs):
        nxt = segs[i + 1]["source_start"] if i + 1 < len(segs) else duration
        s["id"] = i
        s["max_duration"] = round(max(0.5, min(nxt, s["source_end"] + 1.2) - s["source_start"]), 3)
    return segs


def translate_lines(ctx: Context, cues: list[dict], mem: dict, batch: int = 25) -> list[dict]:
    s = ctx.settings
    lang = LANG_NAME[s.language]
    dur = float(ctx.project.manifest.source.get("probe", {}).get("duration") or 0)
    segs = dialogue_segments(cues, dur)
    names = "\n".join(f"- {c['zh']} => {c['my']} ({c.get('role', '')})" for c in mem["characters"])
    system = (f"You are a professional Chinese-to-{lang} drama dubbing translator. Translate into natural SPOKEN {lang} "
              "that fits lip-sync length: short, colloquial, same meaning and emotion, never literal word-by-word. "
              "Use the character names table exactly.")
    for k in range(0, len(segs), batch):
        part = segs[k:k + batch]
        ctx.progress(0.5 + 0.45 * k / max(1, len(segs)), f"စကားပြောတွေ ဘာသာပြန်နေပါတယ် {k}/{len(segs)}")
        ctxlines = "\n".join(f"{x['id']}: {x['chinese']}" for x in segs[max(0, k - 4):k])
        lines = "\n".join(f"{x['id']} ({x['max_duration']:.1f}s): {x['chinese']}" for x in part)
        user = (f"Names:\n{names}\nStory: {mem['so_far']}\nPrevious lines (context only):\n{ctxlines}\n\n"
                f"Translate each line. The seconds in brackets is the max speaking time; keep each line short enough. "
                f"speaker = name (from the table) of who speaks if clear else ''.\n{lines}\n\nReturn JSON {{lines:[{{id,text,speaker}}]}}.")
        out = chat_json(s.llm_model, system, user, TRANS_SCHEMA, temperature=0.4)
        got = {int(x["id"]): x for x in out.get("lines", []) if "id" in x}
        for x in part:
            g = got.get(x["id"], {})
            x["burmese"] = norm_for(g.get("text", ""), s.language)
            x["speaker"] = g.get("speaker", "")
            x["narration"] = x["burmese"]
            x["voice_id"] = None
    return [x for x in segs if x.get("burmese")]


SHORTEN_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


def shorten_line(model: str, language: str, chinese: str, current: str, seconds: float, actual: float) -> str:
    lang = LANG_NAME[language]
    out = chat_json(model, f"You shorten {lang} dubbing lines while keeping meaning and natural spoken tone.",
                    f"Original Chinese: {chinese}\nCurrent {lang}: {current}\nIt takes {actual:.1f}s to speak but must fit in "
                    f"{seconds:.1f}s. Rewrite it about {int(100 * seconds / actual * 0.9)}% as long. Return JSON {{text}}.",
                    SHORTEN_SCHEMA, temperature=0.3)
    return norm_for(out.get("text", current), language) or current


def estimate_syllables(text: str) -> int:
    from .burmese import syllables
    return max(1, len(syllables(text))) if any("\u1000" <= ch <= "\u109f" for ch in text) else max(1, display_len(text) // 3)
