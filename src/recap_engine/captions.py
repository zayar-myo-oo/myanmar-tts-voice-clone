"""Stage 6: caption cues from final narration timing -> SRT / ASS / VTT."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from .burmese import display_len, split_phrases, wrap_two_lines
from .pipeline import Context
from .settings import ASPECT_SIZES, CaptionStyle  # noqa: I001


def src_to_out_y(s, src_w: int, src_h: int, y: float) -> float:
    """Where a source height fraction lands in the output frame (crop box, zoom and reframe applied)."""
    w, h = float(src_w), float(src_h)
    c = s.crop_box
    if c:
        y = (y - c["y0"]) / max(1e-6, c["y1"] - c["y0"])
        w, h = w * (c["x1"] - c["x0"]), h * (c["y1"] - c["y0"])
    if s.zoom > 1.001:
        y = (y - (1 - 1 / s.zoom) / 2) * s.zoom
    from .transform import effective
    # "keep the original aspect" only exists in the transform render path (transform.enabled)
    if (s.transform.enabled and effective(s.transform).aspect_original) or w <= 0 or h <= 0:
        return min(1.0, max(0.0, y))
    W, H = ASPECT_SIZES[s.aspect]
    k = max(W / w, H / h) if s.reframe == "center_crop" else min(W / w, H / h)
    return min(1.0, max(0.0, (y * h * k + (H - h * k) / 2) / H))


_AUTO_CACHE: dict[str, tuple[float, Any, Any]] = {}


def resolve_auto(project, s):
    """caption.position == "auto": put the captions on the burned-in subtitle band found by OCR and widen the blur over
    that band, so nobody has to draw a blur box or drag the caption. Falls back to "bottom" when no band was found."""
    f = project.path("analysis", "ocr.json")
    mt = f.stat().st_mtime if f.exists() else 0.0
    key = str(project.root)
    hit = _AUTO_CACHE.get(key)
    if hit and hit[0] == mt and hit[1] is s:
        return hit[2]
    region = (project.read_json("analysis/ocr.json", {}) or {}).get("region") if mt else None
    if not region:
        out = s.model_copy(update={"caption": s.caption.model_copy(update={"position": "bottom"})})
    else:
        pr = project.manifest.source.get("probe", {})
        sw, sh = int(pr.get("width") or 1920), int(pr.get("height") or 1080)
        y0, y1 = float(region["y0"]), float(region["y1"])
        # captions are bottom-anchored a little under pos_pct: aim at the lower part of the band
        pos = src_to_out_y(s, sw, sh, y0 + 0.65 * (y1 - y0))
        cap = s.caption.model_copy(update={"position": "custom", "pos_pct": round(min(0.97, max(0.08, pos)), 4)})
        # cover the whole subtitle (descenders, a second line, slightly off-centre lines), not only the median box
        box = {"x0": round(max(0.0, region["x0"] - 0.05), 4), "y0": round(max(0.0, y0 - 0.035), 4),
               "x1": round(min(1.0, region["x1"] + 0.05), 4), "y1": round(min(1.0, y1 + 0.05), 4), "strength": 20, "auto": True}
        boxes = [b for b in (s.blur_boxes or []) if not b.get("auto")] + ([box] if s.hardsub == "blur" else [])
        out = s.model_copy(update={"caption": cap, "blur_boxes": boxes})
    _AUTO_CACHE[key] = (mt, s, out)
    return out


def build_cues(beats: list[dict], max_chars: int = 22) -> list[dict]:
    """Distribute each beat's speech time over its phrases proportionally to length."""
    cues = []
    for b in beats:
        text = b.get("spoken_text") or b.get("narration", "")
        a, dur = float(b["out_start"]), float(b["tts_seconds"])
        parts = split_phrases(text, max_chars) or [text]
        weights = [max(1, display_len(x)) for x in parts]
        tot = sum(weights)
        t = a
        for x, w in zip(parts, weights):
            d = dur * w / tot
            cues.append({"start": round(t, 3), "end": round(t + d, 3), "text": x, "beat": b["id"]})
            t += d
    cues.sort(key=lambda c: c["start"])
    for i in range(len(cues) - 1):  # never overlap
        if cues[i]["end"] > cues[i + 1]["start"]:
            cues[i]["end"] = cues[i + 1]["start"]
    return [c for c in cues if c["end"] - c["start"] > 0.05]


def _ts(t: float, sep: str = ",") -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[dict], max_chars: int = 22) -> str:
    return "\n".join(f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n{wrap_two_lines(c['text'], max_chars).replace(chr(92) + 'N', chr(10))}\n"
                     for i, c in enumerate(cues, 1))


def to_vtt(cues: list[dict], max_chars: int = 22) -> str:
    body = "\n".join(f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n"
                     f"{wrap_two_lines(c['text'], max_chars).replace(chr(92) + 'N', chr(10))}\n" for c in cues)
    return "WEBVTT\n\n" + body


def _ass_color(hex_rgba: str) -> str:
    h = hex_rgba.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = h[6:8] if len(h) >= 8 else "00"
    # ASS alpha: 00 opaque .. FF transparent; input alpha is CSS-like (FF opaque)
    if len(h) >= 8:
        a = f"{255 - int(a, 16):02X}"
    return f"&H{a}{b}{g}{r}".upper()


FONTS_DIR = Path(__file__).resolve().parents[2] / "fonts"
_FONT_FILES = {"noto sans myanmar": "NotoSansMyanmar", "padauk": "PadaukBook", "noto sans thai": "NotoSansThai",
               "noto sans": "NotoSans"}


@lru_cache(maxsize=16)
def _font(name: str, bold: bool, size: int):
    """PIL font matching the caption font (falls back to Noto Sans Myanmar) - used only to measure widths."""
    from PIL import ImageFont
    base = next((v for k, v in _FONT_FILES.items() if name.lower().startswith(k)), "NotoSansMyanmar")
    for variant in (("Bold", "Regular") if bold else ("Regular", "Bold")):
        f = FONTS_DIR / f"{base}-{variant}.ttf"
        if f.exists():
            return ImageFont.truetype(str(f), size)
    return None


def text_width(text: str, font_name: str, bold: bool, size: int) -> float:
    f = _font(font_name, bold, max(8, size))
    if f is None:
        return len(text) * size * 0.55
    asc, desc = f.getmetrics()  # libass sizes a font so ascent+descent == Fontsize, not the em size
    return size / max(1, asc + desc) * max(f.getlength(line) for line in text.split(r"\N"))


def fit_line(text: str, style: CaptionStyle, size: int, max_px: float) -> str:
    """Wrap to at most two lines; if a line is still wider than the safe area (long Burmese words, big
    font), shrink just this cue horizontally+vertically so nothing runs past the frame edges."""
    text = wrap_two_lines(text, style.max_chars_per_line)
    if r"\N" not in text and text_width(text, style.font, style.bold, size) > max_px:
        text = wrap_two_lines(text, max(4, display_len(text) // 2))  # force a split near the middle
    wpx = text_width(text, style.font, style.bold, size) + 2 * style.outline
    if wpx > max_px > 0:
        k = max(40, int(100 * max_px / wpx))
        return f"{{\\fscx{k}\\fscy{k}}}" + text
    return text


def _ass_ts(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def safe_margins(aspect: str, style: CaptionStyle) -> dict[str, int]:
    w, h = ASPECT_SIZES[aspect]
    # TikTok/Reels UI covers ~ bottom 18% and right 12% on 9:16
    bottom_ui = 0.18 if aspect == "9:16" else 0.08
    mv = int(h * max(style.margin_v_pct, bottom_ui if style.position == "bottom" else 0.08))
    side = int(w * (0.12 if aspect == "9:16" else 0.06))
    return {"w": w, "h": h, "margin_v": mv, "margin_l": int(w * 0.06), "margin_r": side}


def to_ass(cues: list[dict], aspect: str, style: CaptionStyle, scale: float = 1.0) -> str:
    m = safe_margins(aspect, style)
    w, h = int(m["w"] * scale), int(m["h"] * scale)
    size = int(style.size * (m["w"] / 1080) * scale)
    align = {"bottom": 2, "middle": 5, "top": 8, "custom": 2}[style.position]
    if style.position == "custom":  # bottom-anchored at pos_pct (two lines fit above it)
        m = {**m, "margin_v": int(m["h"] * (1 - style.pos_pct) - size / scale * 0.3)}
    if style.width_pct < 0.999:
        side = int(m["w"] * (1 - style.width_pct) / 2)
        m = {**m, "margin_l": side, "margin_r": side}
    border = 3 if style.box else 1
    back = _ass_color(style.box_color) if style.box else _ass_color("#00000080")
    hdr = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\nPlayResY: {h}\nYCbCr Matrix: TV.709\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font},{size},{_ass_color(style.color)},{_ass_color(style.keyword_color)},"
        f"{_ass_color(style.outline_color)},{back},{-1 if style.bold else 0},0,0,0,100,100,0,0,{border},{style.outline * scale:.1f},"
        f"{style.shadow * scale:.1f},{align},{int(m['margin_l'] * scale)},{int(m['margin_r'] * scale)},"
        f"{int(m['margin_v'] * scale)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    kw_col = _ass_color(style.keyword_color)
    # usable width in ASS pixels, with a small safety factor (libass shaping differs slightly from PIL)
    max_px = (w - (m["margin_l"] + m["margin_r"]) * scale) * 0.95
    lines = []
    for c in (cues if style.burn else []):
        text = fit_line(c["text"], style, size, max_px)
        for kw in style.keywords:
            if kw and kw in text:
                text = text.replace(kw, f"{{\\c{kw_col}}}{kw}{{\\r}}")
        if style.karaoke:
            parts = text.replace(r"\N", " \\N ").split(" ")
            dur_cs = max(1, int((c["end"] - c["start"]) * 100))
            n = max(1, sum(1 for x in parts if x and x != r"\N"))
            text = "".join(x if x == r"\N" else f"{{\\kf{dur_cs // n}}}{x} " for x in parts if x).strip()
        lines.append(f"Dialogue: 0,{_ass_ts(c['start'])},{_ass_ts(c['end'])},Default,,0,0,0,,{text}")
    return hdr + "\n".join(lines) + "\n"


def caption_inputs(ctx: Context) -> Any:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    return {"b": [(b.get("spoken_text"), b.get("out_start"), b.get("tts_seconds")) for b in beats],
            "style": ctx.settings.caption.model_dump(), "aspect": ctx.settings.aspect,
            "fit": 2}  # v2: pixel-width fitting (captions no longer run past the frame edges)


def stage_captions(ctx: Context) -> dict[str, str]:
    p = ctx.project
    beats = p.read_json("script/beats.json", [])
    st = ctx.settings.caption
    cues = build_cues(beats, st.max_chars_per_line)
    p.write_json("render/cues.json", cues)
    Path(p.path("render", "captions.ass")).write_text(to_ass(cues, ctx.settings.aspect, st), "utf-8")
    Path(p.path("export", "final.srt")).write_text(to_srt(cues, st.max_chars_per_line), "utf-8")
    Path(p.path("export", "final.vtt")).write_text(to_vtt(cues, st.max_chars_per_line), "utf-8")
    Path(p.path("export", "final.ass")).write_text(to_ass(cues, ctx.settings.aspect, st), "utf-8")
    return {"cues": "render/cues.json", "ass": "render/captions.ass", "srt": "export/final.srt",
            "vtt": "export/final.vtt", "ass_export": "export/final.ass"}
