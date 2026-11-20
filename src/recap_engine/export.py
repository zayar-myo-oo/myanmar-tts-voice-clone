"""Stage 9: export script.txt, metadata.json and the Post Kit (caption, hashtags,
title, hook, 3:4 thumbnail with Burmese title rendered by libass/HarfBuzz)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .burmese import normalize, wrap_two_lines
from .llm import chat_json, unload
from .media import ffmpeg_bin, ffmpeg_filter_path, run as ff_run
from .pipeline import Context, gpu_lock
from .render import FONTS_DIR

POST_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "caption": {"type": "string"},
                                                 "hashtags": {"type": "array", "items": {"type": "string"}},
                                                 "thumb_text": {"type": "string"}},
               "required": ["title", "caption", "hashtags", "thumb_text"]}


def pick_thumbnail_frame(ctx: Context) -> float:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    # most important beat's best clip
    best = max(beats, key=lambda b: (b.get("importance", 0), b.get("clip_score", 0)), default=None)
    if best and best.get("clips"):
        c = best["clips"][0]
        return (c["src_start"] + c["src_end"]) / 2
    return float(p.manifest.source.get("probe", {}).get("duration", 2)) * 0.3


def make_thumbnail(ctx: Context, title: str, out: Path) -> None:
    p = ctx.project
    t = pick_thumbnail_frame(ctx)
    W, H = 1080, 1440
    ass = p.path("render", "thumb.ass")
    text = wrap_two_lines(normalize(title), 12)
    font = ctx.settings.caption.font
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1440\nWrapStyle: 2\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: T,{font},104,&H0000D4FF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,7,3,2,80,80,110,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,0:00:10.00,T,,0,0,0,,{text}\n", "utf-8")
    fonts = f":fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'" if FONTS_DIR.exists() else ""
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},eq=contrast=1.08:saturation=1.15,"
          f"drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.35:t=fill,"
          f"subtitles=filename='{ffmpeg_filter_path(ass)}'{fonts}:shaping=complex")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(p.source_video), "-frames:v", "1",
            "-vf", vf, str(out)])


def export_inputs(ctx: Context) -> Any:
    return {"qc": ctx.project.stage("qc").input_hash, "lang": ctx.settings.language, "v": 3,
            "tags": [ctx.settings.hashtags, ctx.settings.add_fyp]}


def post_kit_model(model: str) -> str:
    """Short captions/hashtags don't need the big model: local gemma4 -> gemma4:e4b when installed."""
    from .llm import list_models
    if model.startswith("gemma4:") and model != "gemma4:e4b" and "gemma4:e4b" in list_models():
        return "gemma4:e4b"
    return model


def stage_export(ctx: Context) -> dict[str, str]:
    p = ctx.project
    s = ctx.settings
    beats = p.read_json("script/beats.json", [])
    script_txt = "\n\n".join(b.get("spoken_text") or b.get("narration", "") for b in beats)
    p.path("export", "script.txt").write_text(script_txt + "\n", "utf-8")
    ctx.progress(0.2, "Post Kit (caption, hashtag) ရေးနေပါတယ်")
    hook = beats[0].get("spoken_text", beats[0]["narration"]) if beats else ""
    try:
        with gpu_lock(p, "llm-postkit"):
            L = {"my": "Burmese", "en": "English", "th": "Thai"}[s.language]
            kit = chat_json(post_kit_model(s.llm_model), f"You write social media posts for {L} drama-recap pages. Natural spoken {L}.",
                            f"Recap script:\n{script_txt[:4000]}\n\nWrite: title (short, clickable, {L}), caption "
                            f"(2-3 {L} sentences that tease without spoiling the ending, end with a question), "
                            f"hashtags (8-12; {L} plus English like #ChineseDrama #MovieRecap), "
                            f"thumb_text (max 8 {L} words, bold hook for a thumbnail). JSON.",
                            POST_SCHEMA, temperature=0.8)
            unload(s.llm_model)
    except Exception as e:  # noqa: BLE001  post kit must never block the export
        p.log(f"post kit LLM failed: {e}")
        kit = {"title": p.manifest.title, "caption": hook, "hashtags": ["#MovieRecap", "#ChineseDrama", "#ဇာတ်လမ်းအကျဉ်း"],
               "thumb_text": p.manifest.title}
    from .burmese import norm_for
    normalize = lambda t: norm_for(t, s.language)  # noqa: E731
    kit = {"title": normalize(kit.get("title", "")), "caption": normalize(kit.get("caption", "")),
           "hashtags": [h if h.startswith("#") else "#" + h for h in kit.get("hashtags", []) if h],
           "thumb_text": normalize(kit.get("thumb_text", "")), "hook": hook}
    ctx.progress(0.7, "Thumbnail ပုံ လုပ်နေပါတယ်")
    make_thumbnail(ctx, kit["thumb_text"] or kit["title"], p.path("export", "thumbnail_3x4.png"))
    kit["thumbnail"] = "thumbnail_3x4.png"
    extra = [h if h.startswith("#") else "#" + h for h in (s.hashtags or "").split() if h.strip("#")]
    if s.add_fyp:
        extra.append("#fyp")
    kit["hashtags"] = list(dict.fromkeys(extra + kit["hashtags"]))  # user tags first, no duplicates
    p.write_json("export/post_kit.json", kit)
    p.path("export", "post_kit.txt").write_text(
        f"{kit['title']}\n\n{kit['caption']}\n\n{' '.join(kit['hashtags'])}\n", "utf-8")
    meta = {"project_id": p.manifest.project_id, "title": p.manifest.title, "source": {k: v for k, v in
            p.manifest.source.items() if k in ("url", "original_file", "probe", "uploader")},
            "settings": s.model_dump(), "characters": p.manifest.characters,
            "beats": [{k: b.get(k) for k in ("id", "narration", "source_ranges", "out_start", "out_end", "tts_seconds",
                                             "clip_score", "clips", "source_start", "source_end", "chinese")} for b in beats],
            "qc": p.read_json("export/qc_report.json")}
    p.write_json("export/metadata.json", meta)
    p.reload()
    p.manifest.exports = {"mp4": "export/final.mp4", "srt": "export/final.srt", "ass": "export/final.ass",
                          "vtt": "export/final.vtt", "script": "export/script.txt", "metadata": "export/metadata.json",
                          "post_kit": "export/post_kit.json", "thumbnail": "export/thumbnail_3x4.png",
                          "qc": "export/qc_report.json", "caption_frame": "export/caption_frame.png"}
    p.save()
    return {"script": "export/script.txt", "post_kit": "export/post_kit.json", "thumb": "export/thumbnail_3x4.png",
            "metadata": "export/metadata.json"}
