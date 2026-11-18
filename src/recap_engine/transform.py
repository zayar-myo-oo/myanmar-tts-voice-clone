"""Advanced Video Transformation (optional, settings.transform.enabled).

Presentation/localisation tools only: smart reframing, subtitle-band blur and backgrounds,
colour, stabilisation, user-owned branding, audio clean-up, chapters, export options.
It does NOT remove copyright and is not a Content-ID workaround (see rights.py).
When disabled, render.py uses its original code path unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .captions import safe_margins, to_ass
from .errors import RecapError
from .manifest import hash_obj
from .media import ffmpeg_bin, ffmpeg_filter_path, has_nvenc, run as ff_run
from .pipeline import Context
from .settings import ASPECT_SIZES, ColorSettings, TransformSettings

PRESETS: dict[str, dict[str, Any]] = {
    "clean_drama": {"subtitle_blur": True, "color": True, "audio_enhance": True, "loudnorm": True,
                    "col": ColorSettings(preset="natural", denoise=1.5, sharpness=0.3)},
    "cinematic_drama": {"subtitle_blur": True, "color": True, "subtitle_background": "frosted",
                        "col": ColorSettings(preset="cinematic", sharpness=0.4)},
    "vertical_recap": {"smart_reframe": True, "subtitle_blur": True, "subtitle_background": "frosted",
                       "color": True, "col": ColorSettings(preset="clean_social")},
    "subtitle_focus": {"subtitle_blur": True, "subtitle_background": "box", "background_opacity": 0.55,
                       "avoid_faces": True},
}

# subtle grading offsets on top of the user's own sliders (never aggressive)
COLOR_PRESETS: dict[str, dict[str, float]] = {
    "natural": {},
    "cinematic": {"contrast": 1.06, "saturation": 0.92, "temperature": 6100, "shadows": -0.03, "highlights": -0.03},
    "warm_romance": {"temperature": 5400, "saturation": 1.05, "brightness": 0.02, "gamma": 1.03},
    "dark_thriller": {"contrast": 1.10, "saturation": 0.85, "brightness": -0.03, "temperature": 7200, "shadows": -0.05},
    "clean_social": {"contrast": 1.04, "saturation": 1.08, "sharpness": 0.3},
}


def effective(t: TransformSettings) -> TransformSettings:
    return t.model_copy(update=PRESETS[t.preset]) if t.preset in PRESETS else t


# ---------------------------------------------------------------- colour
def color_chain(col: ColorSettings) -> list[str]:
    p = COLOR_PRESETS.get(col.preset, {})
    bright = col.brightness + p.get("brightness", 0)
    contrast = col.contrast * p.get("contrast", 1)
    sat = col.saturation * p.get("saturation", 1)
    gamma = col.gamma * p.get("gamma", 1)
    temp = col.temperature if col.temperature != 6500 else int(p.get("temperature", 6500))
    sharp = col.sharpness + p.get("sharpness", 0)
    sh, hl = col.shadows + p.get("shadows", 0), col.highlights + p.get("highlights", 0)
    f = []
    if col.denoise > 0:
        d = col.denoise
        f.append(f"hqdn3d={d:.2f}:{d * 0.75:.2f}:{d * 1.5:.2f}:{d * 1.1:.2f}")
    if temp != 6500:  # white balance / colour temperature
        f.append(f"colortemperature=temperature={temp}:pl=0.5")
    f.append(f"eq=brightness={bright:.3f}:contrast={contrast:.3f}:gamma={gamma:.3f}:saturation={min(sat, 1.0):.3f}")
    if sat > 1.0:  # vibrance boosts muted colours more than skin tones (skin-tone preservation)
        f.append(f"vibrance=intensity={min(0.5, sat - 1.0):.3f}")
    if abs(sh) > 1e-3 or abs(hl) > 1e-3:
        f.append(f"curves=all='0/0 0.25/{0.25 + sh:.3f} 0.75/{0.75 + hl:.3f} 1/1'")
    if sharp > 0:
        f.append(f"unsharp=5:5:{min(1.5, sharp):.2f}:5:5:0")
    return f


# ---------------------------------------------------------------- output size / encoder
def nearest_aspect(w: int, h: int) -> str:
    r = w / max(1, h)
    return min(ASPECT_SIZES, key=lambda k: abs(ASPECT_SIZES[k][0] / ASPECT_SIZES[k][1] - r))


def eff_aspect(ctx: Context, src_w: int, src_h: int) -> str:
    return nearest_aspect(src_w, src_h) if ctx.settings.transform.aspect_original else ctx.settings.aspect


def out_size(ctx: Context, src_w: int, src_h: int) -> tuple[int, int]:
    t = ctx.settings.transform
    if t.aspect_original:
        w, h = src_w, src_h
        if t.resolution != "original":
            short = 1080 if t.resolution == "1080" else 720
            k = short / min(w, h)
            w, h = int(w * k), int(h * k)
    else:
        w, h = ASPECT_SIZES[ctx.settings.aspect]
        if t.resolution == "720":
            w, h = w * 2 // 3, h * 2 // 3
        elif t.resolution == "original":
            k = min(2.0, min(src_w, src_h) / min(w, h))
            w, h = int(w * k), int(h * k)
    if ctx.settings.proxy:
        w, h = w // 2, h // 2
    return w - w % 2, h - h % 2


def encoder_args(ctx: Context, intermediate: bool = False) -> list[str]:
    t = ctx.settings.transform
    q = str(max(10, t.quality - (5 if intermediate else 3)) if not ctx.settings.proxy else 30)
    rate = ["-b:v", f"{t.bitrate_k}k", "-maxrate", f"{int(t.bitrate_k * 1.5)}k", "-bufsize", f"{t.bitrate_k * 2}k"] \
        if t.bitrate_k else None
    if t.codec == "h265":
        tag = ["-tag:v", "hvc1"]
        if has_nvenc():
            return ["-c:v", "hevc_nvenc", "-preset", "p6", "-tune", "hq", "-spatial-aq", "1", "-temporal-aq", "1",
                    *(rate or ["-rc", "vbr", "-cq", q, "-b:v", "0"]), "-pix_fmt", "yuv420p", *tag]
        return ["-c:v", "libx265", "-preset", "medium", *(rate or ["-crf", q]), "-pix_fmt", "yuv420p", *tag]
    if has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-spatial-aq", "1", "-temporal-aq", "1",
                "-profile:v", "high", *(rate or ["-rc", "vbr", "-cq", q, "-b:v", "0", "-maxrate", "40M", "-bufsize", "50M"]),
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", *(rate or ["-crf", q]), "-pix_fmt", "yuv420p"]


# ---------------------------------------------------------------- faces (smart reframe)
YUNET = Path(__file__).resolve().parents[2] / "models" / "face_detection_yunet_2023mar.onnx"


def _face_detector(cv2):
    """YuNet (OpenCV >= 4.8, ONNX model file) or legacy Haar cascade; None if neither exists."""
    if YUNET.exists() and hasattr(cv2, "FaceDetectorYN"):
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 50)

        def run(img):
            det.setInputSize((img.shape[1], img.shape[0]))
            _, faces = det.detect(img)
            return [] if faces is None else [tuple(int(v) for v in f[:4]) for f in faces]
        return run
    if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
        cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        return lambda img: cas.detectMultiScale(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), scaleFactor=1.15,
                                                minNeighbors=6, minSize=(24, 24))
    return None


def detect_faces(ctx: Context, src: Path, step: float = 0.5) -> list[dict]:
    """Sample frames, OpenCV Haar face boxes (normalised). Cached by source hash."""
    p = ctx.project
    key = hash_obj({"src": p.manifest.source.get("file_hash"), "step": step, "v": 1})
    cached = p.read_json("analysis/faces.json")
    if cached and cached.get("key") == key:
        return cached["samples"]
    import cv2
    detect = _face_detector(cv2)
    if detect is None:  # no detector available -> smart reframe falls back to a centred crop
        p.log("faces: no detector (put face_detection_yunet_2023mar.onnx in models/); using centre")
        return []
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    every = max(1, int(round(fps * step)))
    out, i = [], 0
    while True:
        if ctx.cancelled():
            cap.release()
            from .errors import Cancelled
            raise Cancelled()
        if i % every:
            if not cap.grab():
                break
            i += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        k = 480 / w
        g = cv2.resize(frame, (480, int(h * k)))
        boxes = detect(g)
        gh, gw = g.shape[:2]
        out.append({"t": round(i / fps, 3), "faces": [[round(x / gw, 4), round(y / gh, 4), round((x + bw) / gw, 4),
                                                       round((y + bh) / gh, 4)] for x, y, bw, bh in boxes]})
        if total and len(out) % 40 == 0:
            ctx.progress(0.1 * i / total, "á€™á€»á€€á€ºá€”á€¾á€¬á€á€½á€± á€›á€¾á€¬á€”á€±á€•á€«á€á€šá€º (reframe)")
        i += 1
    cap.release()
    p.write_json("analysis/faces.json", {"key": key, "samples": out})
    return out


def crop_track(samples: list[dict], cuts: list[float], crop_w: float) -> list[tuple[float, float]]:
    """Centre-x (0..1) of the crop window over time. Keeps all faces in frame when they fit,
    else the biggest face; smoothed (dead-zone + speed limit), may jump only at scene cuts."""
    cw = crop_w
    cs: list[float | None] = []
    for s in samples:
        f = s["faces"]
        c = None
        if f:
            x0, x1 = min(b[0] for b in f), max(b[2] for b in f)
            if x1 - x0 <= cw * 0.9:
                c = (x0 + x1) / 2
            else:
                big = max(f, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                c = (big[0] + big[2]) / 2
        cs.append(c)
    # frames without a face: hold the previous face in the same scene, else look ahead to the
    # scene's first face (so a scene opens already framed on its subject), else centre
    scene = [sum(1 for x in cuts if x <= s["t"]) for s in samples]
    fill: list[float | None] = list(cs)
    for i in range(1, len(fill)):
        if fill[i] is None and scene[i] == scene[i - 1]:
            fill[i] = fill[i - 1]
    for i in range(len(fill) - 2, -1, -1):
        if fill[i] is None and scene[i] == scene[i + 1]:
            fill[i] = fill[i + 1]
    raw = [(s["t"], 0.5 if c is None else c) for s, c in zip(samples, fill)]
    out = []
    cur = None
    cut_i = 0
    cuts = sorted(cuts)
    prev_t = 0.0
    for t, c in raw:
        jumped = False
        while cut_i < len(cuts) and cuts[cut_i] <= t:
            cut_i += 1
            jumped = True
        target = min(1 - cw / 2, max(cw / 2, c))
        if cur is None or jumped:
            cur = target  # hard cut in the source: re-centre instantly (no visible pan)
        elif abs(target - cur) > cw * 0.08:  # dead-zone: ignore tiny head movements
            max_step = 0.12 * cw * max(0.1, t - prev_t)  # <= 12% of crop width per second
            cur += float(np.clip(target - cur, -max_step, max_step))
        out.append((t, round(cur, 4)))
        prev_t = t
    return out


def write_sendcmd(track: list[tuple[float, float]], a: float, b: float, src_w: int, cw_px: int, path: Path) -> str:
    """crop x commands (times relative to the clip start), interpolated every 0.1 s."""
    if not track:
        return ""
    ts = np.array([t for t, _ in track])
    cs = np.array([c for _, c in track])
    lines = []
    for t in np.arange(a, b + 1e-6, 0.1):
        c = float(np.interp(t, ts, cs))
        x = int(min(src_w - cw_px, max(0, c * src_w - cw_px / 2)))
        lines.append(f"{t - a:.2f} crop@rf x {x - x % 2};")
    txt = "\n".join(lines) + "\n"
    path.write_text(txt, "utf-8")
    return txt


def faces_in_band(samples: list[dict], y0: float = 0.72) -> float:
    """Share of sampled frames with a face reaching into the bottom caption band."""
    if not samples:
        return 0.0
    return sum(1 for s in samples if any(b[3] > y0 for b in s["faces"])) / len(samples)


# ---------------------------------------------------------------- per-clip video filter
def clip_filter(ctx: Context, src_w: int, src_h: int, region: dict | None, a: float, b: float,
                track: list | None, cmd_path: Path) -> tuple[str, str]:
    """Returns (filter, cache_key_extra)."""
    s = ctx.settings
    t = effective(s.transform)
    W, H = out_size(ctx, src_w, src_h)
    f: list[str] = []
    extra = ""
    if t.stabilize:
        f.append("deshake=rx=32:ry=32")
    if region and t.subtitle_blur and s.hardsub != "keep":
        x0, y0 = int(region["x0"] * src_w), int(region["y0"] * src_h)
        rw = max(16, int((region["x1"] - region["x0"]) * src_w))
        rh = max(8, int((region["y1"] - region["y0"]) * src_h))
        rw, rh = min(rw, src_w - x0), min(rh, src_h - y0)
        if rw * rh <= 0.35 * src_w * src_h:  # never blur (most of) the whole picture
            if s.hardsub == "box":
                f.append(f"drawbox=x={x0}:y={y0}:w={rw}:h={rh}:color=black@1:t=fill")
            elif s.hardsub == "crop":
                f.append(f"crop=iw:{y0 - y0 % 2}:0:0")
                src_h = y0 - y0 % 2
            else:  # localised gaussian blur of the subtitle band only
                sig = 6 + 10 * t.blur_strength
                f.append(f"split[a][b];[b]crop={rw}:{rh}:{x0}:{y0},gblur=sigma={sig:.1f}:steps=3"
                         f"[bb];[a][bb]overlay={x0}:{y0}")
    from .render import user_box_filters
    f += user_box_filters(s, src_w, src_h)
    if t.color:
        f += color_chain(t.col)
    if s.mirror:
        f.append("hflip")
    if s.zoom > 1.001:
        f.append(f"crop=trunc(iw/{s.zoom:.3f}/2)*2:trunc(ih/{s.zoom:.3f}/2)*2")
    flags = ":flags=lanczos"  # always: sharper than the default bicubic
    if max(W / max(1, src_w), H / max(1, src_h)) > 1.15 and not t.upscale:
        t = t.model_copy(update={"upscale": True})  # upscaling anyway -> add the gentle sharpen too
    target_r = W / H
    can_track = t.smart_reframe and track and src_w / src_h > target_r + 0.02 and s.zoom <= 1.001 and not s.mirror and not s.crop_box
    if t.aspect_original:
        f.append(f"scale={W}:{H}{flags}")
    elif can_track:
        cw_px = int(src_h * target_r) // 2 * 2
        txt = write_sendcmd(track, a, b, src_w, cw_px, cmd_path)
        extra = hash_obj(txt)
        f.append(f"sendcmd=f='{ffmpeg_filter_path(cmd_path)}',crop@rf=w={cw_px}:h={src_h - src_h % 2}:"
                 f"x={(src_w - cw_px) // 2}:y=0,scale={W}:{H}{flags}")
    elif s.reframe == "center_crop":
        f.append(f"scale={W}:{H}:force_original_aspect_ratio=increase{flags},crop={W}:{H}")
    else:
        f.append(f"split[m][bg];[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
                 f"boxblur=10:2,scale={W}:{H},eq=brightness=-0.08[bgb];"
                 f"[m]scale={W}:{H}:force_original_aspect_ratio=decrease{flags}[fg];[bgb][fg]overlay=(W-w)/2:(H-h)/2")
    if t.upscale:
        f.append("unsharp=3:3:0.3:3:3:0")
    f.append(f"fps={t.fps},setsar=1,format=yuv420p")
    return ",".join(f), extra


# ---------------------------------------------------------------- final pass (captions, bg, branding)
def _ass_text(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(ctx: Context, cues: list[dict], aspect: str, top: bool, total: float, size: tuple[int, int]) -> str:
    t = effective(ctx.settings.transform)
    st = ctx.settings.caption.model_copy(update={"position": "top"} if top else {})
    if t.subtitle_background == "box":  # libass box behind each line, opacity from slider
        a = int(round(t.background_opacity * 255))
        st = st.model_copy(update={"box": True, "box_color": f"#000000{a:02X}"})
    txt = to_ass(cues if t.subtitle_replace else [], aspect, st)
    if t.watermark and t.wm.text.strip():
        m = safe_margins(aspect, st)
        an = {"top_left": 7, "top_right": 9, "bottom_left": 1, "bottom_right": 3, "center": 5}[t.wm.position]
        alpha = f"{255 - int(t.wm.opacity * 255):02X}"
        fs = int(m["w"] * 0.032)
        mg = int(m["w"] * t.wm.margin_pct)
        style = (f"Style: Brand,{st.font},{fs},&H{alpha}FFFFFF,&H{alpha}FFFFFF,&H{alpha}000000,&H{alpha}000000,"
                 f"-1,0,0,0,100,100,0,0,1,2,0,{an},{mg},{mg},{mg},1\n")
        txt = txt.replace("\n\n[Events]", "\n" + style + "\n[Events]", 1)
        from .captions import _ass_ts
        motion = "fade" if t.wm.animated and t.wm.motion == "fixed" else t.wm.motion
        name = _ass_text(t.wm.text)
        if motion == "move":  # jumps to a new spot every 4 s (like TikTok re-uploads), never over the caption band
            rng = np.random.default_rng(len(name) + int(total))
            W0, H0 = m["w"], m["h"]
            for a0 in np.arange(0, total, 4.0):
                x, y = int(rng.uniform(0.15, 0.85) * W0), int(rng.uniform(0.10, 0.62) * H0)
                txt += (f"Dialogue: 1,{_ass_ts(a0)},{_ass_ts(min(total, a0 + 4.0))},Brand,,0,0,0,,"
                        f"{{\\an5\\pos({x},{y})\\fad(300,300)}}{name}\n")
        else:
            fade = r"{\fad(600,600)}" if motion == "fade" else ""
            ev = [(s0, min(total, s0 + 16)) for s0 in np.arange(0, total, 20)] if motion == "fade" else [(0.0, total)]
            txt += "".join(f"Dialogue: 1,{_ass_ts(a0)},{_ass_ts(b0)},Brand,,0,0,0,,{fade}{name}\n" for a0, b0 in ev)
    return txt


def border_png(ctx: Context, W: int, H: int) -> Path | None:
    """Frame decoration drawn once as a transparent PNG: inset rounded outline and/or soft colour
    glow on the left/right edges (does not cover the picture centre)."""
    t = effective(ctx.settings.transform)
    if t.border == "none":
        return None
    from PIL import Image, ImageDraw, ImageFilter
    key = hash_obj({"b": t.border, "c": t.border_color, "g": t.glow_colors, "s": [W, H], "v": 1})
    out = ctx.project.path("render", f"border_{key}.png")
    if out.exists():
        return out
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hexrgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    if "glow" in t.border:
        for side, col in zip((0, 1), t.glow_colors[:2] or ["#FF3B5C", "#3B7BFF"]):
            g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(g)
            bw = int(W * 0.05)
            x0 = 0 if side == 0 else W - bw
            d.rectangle([x0, 0, x0 + bw, H], fill=(*hexrgb(col), 150))
            img = Image.alpha_composite(img, g.filter(ImageFilter.GaussianBlur(W * 0.04)))
    if "line" in t.border:
        d = ImageDraw.Draw(img)
        m, r = int(W * 0.035), int(W * 0.05)
        d.rounded_rectangle([m, m, W - m, H - m], radius=r, outline=(*hexrgb(t.border_color), 170),
                            width=max(2, W // 300))
    img.save(out)
    return out


def band_box(ctx: Context, aspect: str, top: bool, W: int, H: int) -> tuple[int, int, int, int]:
    st = ctx.settings.caption.model_copy(update={"position": "top"} if top else {})
    m = safe_margins(aspect, st)
    k = H / m["h"]
    size = st.size * (m["w"] / 1080) * k
    mv = m["margin_v"] * k
    bh = int(size * 3.1)
    y = int(mv - size * 0.35) if top else int(H - mv - bh + size * 0.35)
    x = int(W * 0.03)
    return x, max(0, y), W - 2 * x, min(bh, H - max(0, y))


def logo_file(ctx: Context) -> Path | None:
    t = effective(ctx.settings.transform)
    if not (t.watermark and t.wm.logo_path):
        return None
    src = Path(t.wm.logo_path)
    if not src.exists():
        raise RecapError("logo_missing", f"Logo á€–á€­á€¯á€„á€º á€™á€á€½á€±á€·á€•á€«: {src}")
    if src.suffix.lower() != ".svg":
        return src
    out = ctx.project.path("render", "logo_svg.png")
    try:
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(src), "-frames:v", "1", str(out)])
    except Exception as e:  # ffmpeg build without librsvg
        raise RecapError("svg_unsupported", "SVG logo á€€á€­á€¯ á€–á€á€ºá€™á€›á€•á€«á‹ PNG á€”á€²á€· á€‘á€Šá€·á€ºá€•á€±á€¸á€•á€«á‹") from e
    return out


def final_video_filter(ctx: Context, cues: list[dict], ass: Path, fonts: str, W: int, H: int,
                       aspect: str, top: bool, logo: Path | None) -> str:
    """[0:v] -> optional subtitle background -> captions/brand text (libass) -> optional logo -> [v]."""
    t = effective(ctx.settings.transform)
    f = "[0:v]"
    if t.subtitle_background == "frosted" and cues and t.subtitle_replace:
        x, y, w, h = band_box(ctx, aspect, top, W, H)
        en = "+".join(f"between(t\\,{c['start']:.2f}\\,{c['end']:.2f})" for c in cues)
        op = t.background_opacity
        f += (f"split[fa][fb];[fb]crop={w}:{h}:{x}:{y},gblur=sigma=18,drawbox=c=black@{op:.2f}:t=fill[fz];"
              f"[fa][fz]overlay={x}:{y}:enable='{en}',")
    f += f"subtitles=filename='{ffmpeg_filter_path(ass)}'{fonts}:shaping=complex"
    bp = border_png(ctx, W, H)
    if bp:
        f += f"[vb];movie='{ffmpeg_filter_path(bp)}',format=rgba[bd];[vb][bd]overlay=0:0"
    if logo:
        lw = int(W * t.wm.size_pct) // 2 * 2
        m = int(W * t.wm.margin_pct)
        pos = {"top_left": (f"{m}", f"{m}"), "top_right": (f"W-w-{m}", f"{m}"),
               "bottom_left": (f"{m}", f"H-h-{m}"), "bottom_right": (f"W-w-{m}", f"H-h-{m}"),
               "center": ("(W-w)/2", "(H-h)/2")}[t.wm.position]
        en = ":enable='lt(mod(t\\,20)\\,16)'" if t.wm.animated else ""
        f += (f"[vs];movie='{ffmpeg_filter_path(logo)}',scale={lw}:-1,format=rgba,"
              f"colorchannelmixer=aa={t.wm.opacity:.2f}[lg];[vs][lg]overlay={pos[0]}:{pos[1]}{en}")
    return f + "[v]"


def audio_filter(ctx: Context, enhance: bool) -> str:
    """[1:a]=bed (original/accompaniment), [2:a]=Burmese narration."""
    t = effective(ctx.settings.transform)
    mode = ctx.settings.mode
    bed = "[1:a]"
    pre = ""
    if enhance and t.audio_enhance and mode == "subtitle":  # light noise reduction on the original audio
        pre += "[1:a]afftdn=nr=8:nf=-45[bd];"
        bed = "[bd]"
    narr = "[2:a]"
    if enhance and t.audio_enhance and mode != "subtitle":  # voice clarity + gentle compression
        pre += ("[2:a]highpass=f=70,equalizer=f=3000:t=q:w=1.2:g=2,"
                "acompressor=threshold=0.12:ratio=3:attack=10:release=200:makeup=1.2[nv];")
        narr = "[nv]"
    norm = "loudnorm=I=-14:TP=-1.5:LRA=11," if t.loudnorm else ""
    return (pre + f"{narr}asplit=2[nsc][nmix];"
            f"{bed}[nsc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400:makeup=1[ducked];"
            "[ducked][nmix]amix=inputs=2:duration=longest:normalize=0,"
            f"{norm}alimiter=limit=0.89:level=false,aresample=48000[a]")  # limiter: no clipping


# ---------------------------------------------------------------- chapters + compare
def chapters(ctx: Context, beats: list[dict], shots: list[dict], total: float) -> list[dict]:
    if ctx.settings.mode == "recap":
        ch = [{"start": b["out_start"], "title": (b.get("narration") or "")[:40]} for b in beats]
    else:  # group scenes into >= 60 s chapters at shot boundaries (never mid-shot)
        ch, last = [{"start": 0.0, "title": "á€¡á€…"}], 0.0
        for s in shots:
            if s["start"] - last >= 60 and total - s["start"] >= 30:
                ch.append({"start": s["start"], "title": f"á€¡á€•á€­á€¯á€„á€ºá€¸ {len(ch) + 1}"})
                last = s["start"]
    for i, c in enumerate(ch):
        c["end"] = ch[i + 1]["start"] if i + 1 < len(ch) else total
    return [c for c in ch if c["end"] - c["start"] >= 1.0]


def write_chapters(ctx: Context, ch: list[dict]) -> Path:
    p = ctx.project
    lines = [f"{int(c['start'] // 60):02d}:{int(c['start'] % 60):02d} {c['title']}" for c in ch]
    p.path("export", "chapters.txt").write_text("\n".join(lines) + "\n", "utf-8")
    meta = [";FFMETADATA1"]
    for c in ch:
        title = c["title"].replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(c['start'] * 1000)}", f"END={int(c['end'] * 1000)}",
                 f"title={title}"]
    out = p.path("render", "chapters.ffmeta")
    out.write_text("\n".join(meta) + "\n", "utf-8")
    return out


def compare_image(ctx: Context, src: Path, out_video: Path, clip: dict) -> None:
    """Before / after frame side by side -> export/compare.png."""
    d = clip["src_end"] - clip["src_start"]
    ts, to = clip["src_start"] + d / 2, clip["out_start"] + d / 2
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(src), "-ss", f"{to:.2f}",
            "-i", str(out_video), "-filter_complex",
            "[0:v]scale=-2:720,setsar=1[a];[1:v]scale=-2:720,setsar=1[b];[a][b]hstack=inputs=2",
            "-frames:v", "1", str(ctx.project.path("export", "compare.png"))])
