"""Fit video to narration: choose clips per beat so footage length == speech length.
Speech is never time-stretched (except Pro mode's capped last-resort speed-up)."""
from __future__ import annotations

from typing import Any

from .pipeline import Context

GAP = 0.25  # pause after each beat
MIN_CLIP = 1.2


MONTAGE_CLIP = 2.2  # intro teaser: short cuts from across the whole video


def pick_montage(beat: dict, need: float, shots: dict[int, dict], duration: float) -> list[dict]:
    """Intro teaser: ~2 s from each montage range, in story order, cycling until the voice is covered.
    Montage shots are not marked used, so the recap can still show them in full later."""
    ranges = [r for r in (beat.get("source_ranges") or []) if r[1] - r[0] > 0.3] or [[0.0, min(duration, 10.0)]]
    clips: list[dict] = []
    have, k, offs = 0.0, 0, [0.0] * len(ranges)
    while have < need - 1e-3 and k < 60:
        i = k % len(ranges)
        a, b = ranges[i]
        st = a + offs[i]
        if st >= b - 0.3:  # range used up: continue just after it
            st, b = b, min(duration, b + MONTAGE_CLIP * 2)
            ranges[i] = [a, b]
        take = min(MONTAGE_CLIP, b - st, need - have)
        if take > 0.25:
            clips.append({"shot": None, "src_start": round(st, 3), "src_end": round(st + take, 3), "score": 0.0})
            have += take
            offs[i] += take
        k += 1
    if clips and have < need - 1e-3:  # a sliver too short for its own cut: stretch the last clip
        last = clips[-1]
        last["src_end"] = round(min(duration, last["src_end"] + need - have), 3)
    return clips


def pick_clips(beat: dict, need: float, used: set[int], shots: dict[int, dict], duration: float) -> list[dict]:
    if beat.get("kind") == "intro":
        return pick_montage(beat, need, shots, duration)
    clips: list[dict] = []
    have = 0.0
    for c in beat.get("candidates", []):
        if have >= need - 1e-3:
            break
        if c["shot"] in used:
            continue
        s = shots.get(c["shot"])
        if not s or s["end"] - s["start"] < 0.4:
            continue
        take = min(s["end"] - s["start"], need - have)
        if take < min(MIN_CLIP, need - have) - 1e-3 and need - have > MIN_CLIP:
            continue
        clips.append({"shot": s["id"], "src_start": s["start"], "src_end": round(s["start"] + take, 3),
                      "score": c["score"]})
        used.add(s["id"])
        have += take
    if have < need - 1e-3:
        # extend continuously from the end of the beat's first range (keeps the story order)
        rng = beat.get("source_ranges") or [[0.0, duration]]
        t = rng[0][0]
        while have < need - 1e-3 and t < duration:
            take = min(need - have, duration - t, 6.0)
            if take <= 0.05:
                break
            clips.append({"shot": None, "src_start": round(t, 3), "src_end": round(t + take, 3), "score": 0.0})
            have += take
            t += take
    clips.sort(key=lambda c: c["src_start"])
    return clips


def build_recap_timeline(beats: list[dict], shots_list: list[dict], duration: float) -> list[dict]:
    shots = {s["id"]: s for s in shots_list}
    used: set[int] = set()
    out_t = 0.0
    tl = []
    for b in beats:
        need = b["tts_seconds"] + GAP
        clips = pick_clips(b, need, used, shots, duration)
        t = out_t
        for c in clips:
            c["out_start"] = round(t, 3)
            t += c["src_end"] - c["src_start"]
            c["out_end"] = round(t, 3)
        b["out_start"], b["out_end"] = round(out_t, 3), round(out_t + b["tts_seconds"], 3)
        b["clips"] = clips
        tl.append({"beat": b["id"], "out_start": out_t, "out_end": round(t, 3), "clips": clips})
        out_t = t
    return tl


def build_pro_timeline(beats: list[dict], duration: float) -> list[dict]:
    for b in beats:
        b["out_start"] = b["source_start"]
        b["out_end"] = round(b["source_start"] + b["tts_seconds"], 3)
        b["clips"] = []
    return [{"beat": None, "out_start": 0.0, "out_end": duration,
             "clips": [{"shot": None, "src_start": 0.0, "src_end": duration, "out_start": 0.0, "out_end": duration}]}]


def build_compact_timeline(beats: list[dict], duration: float, max_gap: float = 2.0, pad: float = 0.3) -> list[dict]:
    """Keep only the spoken parts (+ short pauses); silent stretches longer than max_gap are cut.
    Each line keeps its own footage, so speech and picture stay in sync."""
    segs: list[list[float]] = []
    for b in sorted(beats, key=lambda x: x["source_start"]):
        a = max(0.0, b["source_start"] - pad)
        e = min(duration, max(b["source_end"], b["source_start"] + b["tts_seconds"]) + pad)
        if segs and a - segs[-1][1] <= max_gap:
            segs[-1][1] = max(segs[-1][1], e)
        else:
            segs.append([a, e])
    clips, t = [], 0.0
    for a, e in segs:
        clips.append({"shot": None, "src_start": round(a, 3), "src_end": round(e, 3),
                      "out_start": round(t, 3), "out_end": round(t + e - a, 3)})
        t += e - a

    def to_out(x: float) -> float:
        for c in clips:
            if c["src_start"] - 1e-6 <= x <= c["src_end"] + 1e-6:
                return c["out_start"] + x - c["src_start"]
        return clips[-1]["out_end"] if clips else 0.0
    for b in beats:
        b["out_start"] = round(to_out(b["source_start"]), 3)
        b["out_end"] = round(b["out_start"] + b["tts_seconds"], 3)
        b["clips"] = []
    return [{"beat": None, "out_start": 0.0, "out_end": round(t, 3), "clips": clips}]


def timeline_inputs(ctx: Context) -> Any:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    return {"b": [(b.get("tts_path"), b.get("tts_seconds"), b.get("source_ranges"), b.get("pinned_clips"))
                  for b in beats], "mode": ctx.settings.mode,
            "tight": [ctx.settings.tighten_gaps, ctx.settings.max_gap]}


def stage_timeline(ctx: Context) -> dict[str, str]:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    shots = p.read_json("analysis/shots.json", [])
    dur = float(p.manifest.source.get("probe", {}).get("duration") or 0)
    if ctx.settings.mode == "subtitle":  # no TTS: subtitle shows for the original line's time
        for b in beats:
            b["tts_seconds"] = round(b["source_end"] - b["source_start"], 3)
            b["spoken_text"] = b.get("burmese") or b.get("narration", "")
    if ctx.settings.mode in ("pro", "subtitle"):
        tl = (build_compact_timeline(beats, dur, ctx.settings.max_gap) if ctx.settings.tighten_gaps
              else build_pro_timeline(beats, dur))
    else:
        # honour user-pinned clips from the editor
        for b in beats:
            if b.get("pinned_clips"):
                b["candidates"] = [{"shot": s, "score": 9.0} for s in b["pinned_clips"]] + b.get("candidates", [])
        tl = build_recap_timeline(beats, shots, dur)
    p.write_json("script/beats.json", beats)
    p.write_json("render/timeline.json", tl)
    p.reload()
    p.manifest.beats = [{k: v for k, v in b.items() if k != "candidates"} for b in beats]
    p.save()
    return {"timeline": "render/timeline.json"}
