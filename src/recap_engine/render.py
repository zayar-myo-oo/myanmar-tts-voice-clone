"""Stage 7: render. Per-clip intermediates (cached by hash -> editing one beat only
re-cuts that beat's clips), concat, audio bed + Burmese narration with sidechain
ducking, loudness to -14 LUFS, captions burned with libass, NVENC/libx264."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .manifest import hash_obj
from .media import ffmpeg_bin, ffmpeg_filter_path, run as ff_run, video_encoder_args
from .pipeline import Context
from .settings import ASPECT_SIZES

SR = 48000
FPS = 30
REPO = Path(__file__).resolve().parents[2]
FONTS_DIR = REPO / "fonts"


def render_workers() -> int:
    """Parallel clip encoders: RECAP_RENDER_WORKERS, else auto from CPU cores (NVENC allows several sessions)."""
    import os
    env = os.environ.get("RECAP_RENDER_WORKERS")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, min(4, (os.cpu_count() or 4) // 3))


def run_parallel(ctx: Context, tasks: list, lo: float, hi: float, label: str) -> None:
    """Run clip jobs on a thread pool (ffmpeg does the work, so threads are enough)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not tasks:
        return
    n = 1 if len(tasks) == 1 else render_workers()
    done = 0
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = [ex.submit(t) for t in tasks]
        try:
            for f in as_completed(futs):
                f.result()
                done += 1
                ctx.progress(lo + (hi - lo) * done / len(tasks), f"{label} {done}/{len(tasks)} (worker {n})")
        except BaseException:
            for f in futs:
                f.cancel()
            raise


CHUNK = 60.0


def split_long(clips: list[dict]) -> list[dict]:
    """Long clips (Pro / subtitle mode = the whole video) -> 60 s chunks so workers encode in parallel."""
    out = []
    for c in clips:
        a, b = c["src_start"], c["src_end"]
        if b - a <= CHUNK * 1.5:
            out.append(c)
            continue
        t = a
        while t < b - 1e-3:
            e = min(b, t + CHUNK) if b - (t + CHUNK) > 5 else b
            out.append({**c, "src_start": round(t, 3), "src_end": round(e, 3),
                        "out_start": round(c["out_start"] + t - a, 3), "out_end": round(c["out_start"] + e - a, 3)})
            t = e
    return out


def out_size(ctx: Context) -> tuple[int, int]:
    w, h = ASPECT_SIZES[ctx.settings.aspect]
    if ctx.settings.proxy:
        w, h = w // 2, h // 2
    return w - w % 2, h - h % 2


def user_box_filters(s, src_w: int, src_h: int) -> list[str]:
    """Studio editor: gaussian blur inside each drawn box, then optional keep-area crop."""
    f = []
    for i, b in enumerate(s.blur_boxes or []):
        x0, y0 = int(max(0, b["x0"]) * src_w), int(max(0, b["y0"]) * src_h)
        w = max(8, int((min(1, b["x1"]) - max(0, b["x0"])) * src_w)) // 2 * 2
        h = max(8, int((min(1, b["y1"]) - max(0, b["y0"])) * src_h)) // 2 * 2
        w, h = min(w, src_w - x0), min(h, src_h - y0)
        sig = max(1.0, float(b.get("strength", 20)))
        f.append(f"split[u{i}a][u{i}b];[u{i}b]crop={w}:{h}:{x0}:{y0},gblur=sigma={sig:.1f}:steps=3[u{i}c];"
                 f"[u{i}a][u{i}c]overlay={x0}:{y0}")
    c = s.crop_box
    if c:
        x0, y0 = int(c["x0"] * src_w) // 2 * 2, int(c["y0"] * src_h) // 2 * 2
        w = max(32, int((c["x1"] - c["x0"]) * src_w)) // 2 * 2
        h = max(32, int((c["y1"] - c["y0"]) * src_h)) // 2 * 2
        f.append(f"crop={min(w, src_w - x0)}:{min(h, src_h - y0)}:{x0}:{y0}")
    return f


def video_filter(ctx: Context, src_w: int, src_h: int, region: dict | None) -> str:
    s = ctx.settings
    W, H = out_size(ctx)
    f: list[str] = []
    # 1) hide burned-in Chinese subtitles (source coordinates)
    if region and s.hardsub != "keep":
        x0, y0 = int(region["x0"] * src_w), int(region["y0"] * src_h)
        rw, rh = max(16, int((region["x1"] - region["x0"]) * src_w)), max(8, int((region["y1"] - region["y0"]) * src_h))
        rw, rh = min(rw, src_w - x0), min(rh, src_h - y0)
        if s.hardsub == "blur":
            f.append(f"split[a][b];[b]crop={rw}:{rh}:{x0}:{y0},boxblur=luma_radius=min(h\\,w)/5:luma_power=3:"
                     f"chroma_radius=min(ch\\,cw)/5:chroma_power=3"
                     f"[bb];[a][bb]overlay={x0}:{y0}")
        elif s.hardsub == "box":
            f.append(f"drawbox=x={x0}:y={y0}:w={rw}:h={rh}:color=black@1:t=fill")
        elif s.hardsub == "crop":
            f.append(f"crop=iw:{y0 - y0 % 2}:0:0")
    f += user_box_filters(s, src_w, src_h)
    # 2) mirror + zoom (before captions, so captions are never mirrored)
    if s.mirror:
        f.append("hflip")
    if s.zoom > 1.001:
        f.append(f"crop=trunc(iw/{s.zoom:.3f}/2)*2:trunc(ih/{s.zoom:.3f}/2)*2")
    # 3) reframe to target aspect
    up = ",unsharp=5:5:0.45:5:5:0" if max(W / max(1, src_w), H / max(1, src_h)) > 1.15 else ""
    if s.reframe == "center_crop":
        f.append(f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}{up}")
    else:
        f.append(f"split[m][bg];[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
                 f"boxblur=10:2,scale={W}:{H},eq=brightness=-0.08[bgb];"
                 f"[m]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos{up}[fg];[bgb][fg]overlay=(W-w)/2:(H-h)/2")
    f.append(f"fps={FPS},setsar=1,format=yuv420p")
    return ",".join(f)


def frames_for(c: dict, fps: float) -> int:
    """Exact frame count for a clip so the concat never drifts from the audio timeline."""
    return max(1, int(round(c["out_end"] * fps)) - int(round(c["out_start"] * fps)))


def cut_clip(ctx: Context, src: Path, a: float, b: float, vf: str, out: Path, nf: int | None = None) -> None:
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", str(src), "-t", f"{b - a + 0.5:.3f}",
            *(["-frames:v", str(nf)] if nf else []),
            "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-an", *video_encoder_args(ctx.settings.proxy, True),
            str(out)], cancel=ctx.cancelled)


def load_48k(path: Path, cache_dir: Path) -> np.ndarray:
    """Read audio as float32 stereo 48 kHz (resampling via ffmpeg, cached)."""
    info = sf.info(str(path))
    if info.samplerate == SR and info.channels == 2:
        x, _ = sf.read(str(path), dtype="float32", always_2d=True)
        return x
    out = cache_dir / (path.stem + "_48k.wav")
    if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(path), "-ar", str(SR), "-ac", "2",
                "-af", "aresample=resampler=soxr", str(out)])
    x, _ = sf.read(str(out), dtype="float32", always_2d=True)
    return x


def build_audio(ctx: Context, beats: list[dict], timeline: list[dict], total: float) -> tuple[Path, Path]:
    p = ctx.project
    n = int(round(total * SR)) + SR // 10
    narr = np.zeros((n, 2), dtype=np.float32)
    cache = p.path("render")
    for b in beats:
        if not b.get("tts_path"):  # subtitle mode: no narration
            continue
        x = load_48k(p.path(b["tts_path"]), cache)
        i = int(round(b["out_start"] * SR))
        j = min(n, i + len(x))
        narr[i:j] += x[: j - i]
    sf.write(str(p.path("render", "narration.wav")), narr, SR, subtype="PCM_16")

    mode = ctx.settings.original_audio
    bed = np.zeros_like(narr)
    if mode != "mute_all":
        src = p.path("analysis", "accompaniment.wav" if mode == "remove_vocals" else "audio.wav")
        if not src.exists():
            src = p.path("analysis", "audio.wav")
        full = load_48k(src, cache)
        for seg in timeline:
            for c in seg["clips"]:
                a, b = int(round(c["src_start"] * SR)), int(round(c["src_end"] * SR))
                o = int(round(c["out_start"] * SR))
                piece = full[a:b]
                k = min(len(piece), n - o)
                if k <= 0:
                    continue
                piece = piece[:k].copy()
                fade = min(k // 2, int(0.02 * SR))  # 20 ms crossfade at cut points: no clicks
                if fade > 0:
                    ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
                    piece[:fade] *= ramp
                    piece[-fade:] *= ramp[::-1]
                bed[o:o + k] += piece
    if ctx.settings.bgm_path:
        bgm_path = Path(ctx.settings.bgm_path)
        if bgm_path.is_dir():
            files = sorted([x for x in bgm_path.iterdir() if x.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac", ".ogg")])
            bgm_path = random.Random(p.manifest.project_id).choice(files) if files else None
        if bgm_path and bgm_path.exists():
            m = load_48k(bgm_path, cache)
            reps = int(np.ceil(n / max(1, len(m))))
            bed += np.tile(m, (reps, 1))[:n] * 0.25
    sf.write(str(p.path("render", "bed.wav")), np.clip(bed, -1, 1), SR, subtype="PCM_16")
    return p.path("render", "narration.wav"), p.path("render", "bed.wav")


def fix_loudness(path: Path, target: float = -14.0) -> float | None:
    """Second pass: single-pass loudnorm can land 1-3 LU low on sparse speech. Measure, then apply
    the exact gain (+ true-peak limiter) to the audio only; the video stream is copied untouched."""
    from .qc import measure_loudness
    m = measure_loudness(path)
    lufs = m.get("lufs")
    if lufs is None or abs(lufs - target) <= 0.7:
        return lufs
    tmp = path.with_name(path.stem + "_lufs" + path.suffix)
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
            "-af", f"volume={target - lufs:.2f}dB,alimiter=limit=0.89:level=false", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-movflags", "+faststart", str(tmp)])
    tmp.replace(path)
    return measure_loudness(path).get("lufs")


def render_inputs(ctx: Context) -> Any:
    p = ctx.project
    s = ctx.settings
    return {"tl": p.read_json("render/timeline.json"), "cap": p.stage("captions").input_hash,
            "voice": p.stage("voice").input_hash,
            "s": {k: getattr(s, k) for k in ("aspect", "mirror", "zoom", "reframe", "hardsub", "original_audio",
                                             "bgm_path", "proxy", "mode", "blur_boxes", "crop_box")},
            "ocr": p.stage("ocr").input_hash, "v": 3,
            **({"tf": s.transform.model_dump(), "shots": p.stage("shots").input_hash} if s.transform.enabled else {})}


def stage_render(ctx: Context) -> dict[str, str]:
    if ctx.settings.transform.enabled:
        return stage_render_tf(ctx)
    p = ctx.project
    s = ctx.settings
    src = p.source_video
    pr = p.manifest.source["probe"]
    region = (p.read_json("analysis/ocr.json", {}) or {}).get("region")
    beats = p.read_json("script/beats.json", [])
    timeline = p.read_json("render/timeline.json", [])
    vf = video_filter(ctx, pr["width"], pr["height"], region)
    clips = split_long([c for seg in timeline for c in seg["clips"]])
    total = max((c["out_end"] for c in clips), default=0.0)
    cdir = p.path("render", "clips")
    cdir.mkdir(exist_ok=True)
    sched: set[str] = set()
    listing = []
    reused = 0
    tasks = []
    for i, c in enumerate(clips):
        nf = frames_for(c, FPS)
        h = hash_obj({"src": p.manifest.source.get("file_hash"), "a": c["src_start"], "b": c["src_end"], "vf": vf,
                      "nf": nf})
        out = cdir / f"clip_{h}.mp4"
        if out.exists() or h in sched:
            reused += 1
        else:
            sched.add(h)
            tmp = cdir / f"tmp_{h}.mp4"

            def job(c=c, tmp=tmp, out=out, nf=nf):
                cut_clip(ctx, src, c["src_start"], c["src_end"], vf, tmp, nf)
                tmp.replace(out)
            tasks.append(job)
        listing.append(f"file '{out.as_posix()}'")
    run_parallel(ctx, tasks, 0.0, 0.75, "Clip တွေ ဖြတ်နေပါတယ်")
    p.log(f"render: {reused}/{len(clips)} clips reused from cache, {len(tasks)} cut")
    lst = p.path("render", "concat.txt")
    lst.write_text("\n".join(listing) + "\n", "utf-8")
    ctx.progress(0.78, "အသံ ရောစပ်နေပါတယ်")
    narr, bed = build_audio(ctx, beats, timeline, total)
    ctx.progress(0.8, "စာတန်းထိုး ထည့်ပြီး ဗီဒီယို ထုတ်နေပါတယ်")
    ass = p.path("render", "captions.ass")
    fonts = f":fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'" if FONTS_DIR.exists() else ""
    out = p.path("export", "preview.mp4" if s.proxy else "final.mp4")
    fc = (f"[0:v]subtitles=filename='{ffmpeg_filter_path(ass)}'{fonts}:shaping=complex[v];"
          "[2:a]asplit=2[nsc][nmix];"
          "[1:a][nsc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400:makeup=1[ducked];"
          "[ducked][nmix]amix=inputs=2:duration=longest:normalize=0,"
          "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
            "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(bed), "-i", str(narr),
            "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *video_encoder_args(s.proxy),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)],
           cancel=ctx.cancelled, progress=lambda f: ctx.progress(0.8 + 0.2 * f, "ဗီဒီယို ထုတ်နေပါတယ်"),
           total_seconds=total)
    fix_loudness(out)
    # drop clip intermediates no longer referenced (keeps disk use bounded)
    keep = {Path(x[6:-1]).name for x in listing}
    for f in cdir.glob("clip_*.mp4"):
        if f.name not in keep:
            f.unlink(missing_ok=True)
    p.write_json("render/render_info.json", {"duration": total, "clips": len(clips), "reused": reused,
                                              "encoder": video_encoder_args(s.proxy)[1], "size": out_size(ctx)})
    return {"video": str(out.relative_to(p.root)).replace("\\", "/"), "info": "render/render_info.json"}


def stage_render_tf(ctx: Context) -> dict[str, str]:
    """Advanced Video Transformation render path (transform.enabled=True)."""
    from . import transform as tf
    from .errors import RecapError
    p = ctx.project
    s = ctx.settings
    t = tf.effective(s.transform)
    src = p.source_video
    pr = p.manifest.source["probe"]
    sw, sh = pr["width"], pr["height"]
    region = (p.read_json("analysis/ocr.json", {}) or {}).get("region")
    beats = p.read_json("script/beats.json", [])
    timeline = p.read_json("render/timeline.json", [])
    shots = p.read_json("analysis/shots.json", [])
    cues = p.read_json("render/cues.json", [])
    W, H = tf.out_size(ctx, sw, sh)
    aspect = tf.eff_aspect(ctx, sw, sh)
    samples = tf.detect_faces(ctx, src) if (t.smart_reframe or t.avoid_faces) else []
    track = None
    if t.smart_reframe and samples:
        track = tf.crop_track(samples, [x["start"] for x in shots[1:]], (sh * W / H) / sw)
        p.write_json("analysis/reframe_track.json", track)
    # Burmese subs move to the top when faces often sit in the bottom caption band
    top = bool(t.avoid_faces and s.caption.position == "bottom" and tf.faces_in_band(samples) > 0.25)
    clips = split_long([c for seg in timeline for c in seg["clips"]])
    total = max((c["out_end"] for c in clips), default=0.0)
    cdir = p.path("render", "clips")
    cdir.mkdir(exist_ok=True)
    listing, reused, tracked = [], 0, False
    sched: set[str] = set()
    tasks = []
    for i, c in enumerate(clips):
        cmd = cdir / f"cmd_{i}.txt"
        vf, extra = tf.clip_filter(ctx, sw, sh, region, c["src_start"], c["src_end"], track, cmd)
        tracked = tracked or "sendcmd=" in vf
        nf = frames_for(c, t.fps)
        h = hash_obj({"src": p.manifest.source.get("file_hash"), "a": c["src_start"], "b": c["src_end"],
                      "vf": vf.replace(cmd.as_posix(), ""), "x": extra, "enc": tf.encoder_args(ctx, True), "nf": nf})
        out = cdir / f"clip_{h}.mp4"
        if out.exists() or h in sched:
            reused += 1
        else:
            sched.add(h)
            tmp = cdir / f"tmp_{h}.mp4"

            def job(c=c, vf=vf, tmp=tmp, out=out, nf=nf):
                ff_run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{c['src_start']:.3f}", "-i", str(src),
                        "-t", f"{c['src_end'] - c['src_start'] + 0.5:.3f}", "-frames:v", str(nf),
                        "-filter_complex", f"[0:v]{vf}[v]",
                        "-map", "[v]", "-an", *tf.encoder_args(ctx, True), str(tmp)], cancel=ctx.cancelled)
                tmp.replace(out)
            tasks.append(job)
        listing.append(f"file '{out.as_posix()}'")
    run_parallel(ctx, tasks, 0.1, 0.7, "Clip တွေ ပြင်ဆင်နေပါတယ်")
    p.log(f"render(tf): {reused}/{len(clips)} clips reused, top_captions={top}, track={bool(track)}")
    lst = p.path("render", "concat.txt")
    lst.write_text("\n".join(listing) + "\n", "utf-8")
    ctx.progress(0.72, "အသံ ရောစပ်နေပါတယ်")
    narr, bed = build_audio(ctx, beats, timeline, total)
    ass = p.path("render", "captions_tf.ass")
    ass.write_text(tf.build_ass(ctx, cues, aspect, top, total, (W, H)), "utf-8")
    fonts = f":fontsdir='{ffmpeg_filter_path(FONTS_DIR)}'" if FONTS_DIR.exists() else ""
    logo = tf.logo_file(ctx)
    vfc = tf.final_video_filter(ctx, cues, ass, fonts, W, H, aspect, top, logo)
    meta_in: list[str] = []
    ch = []
    if t.scene_chapters:
        ch = tf.chapters(ctx, beats, shots, total)
        meta_in = ["-i", str(tf.write_chapters(ctx, ch))]
    out = p.path("export", "preview.mp4" if s.proxy else "final.mp4")

    def final(enhance: bool) -> None:
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
                "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(bed), "-i", str(narr), *meta_in,
                "-filter_complex", vfc + ";" + tf.audio_filter(ctx, enhance), "-map", "[v]", "-map", "[a]",
                *(["-map_chapters", "3"] if meta_in else []), *tf.encoder_args(ctx),
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart",
                str(out)], cancel=ctx.cancelled, total_seconds=total,
               progress=lambda f: ctx.progress(0.75 + 0.22 * f, "ဗီဒီယို ထုတ်နေပါတယ်"))

    audio_fallback = False
    try:
        final(True)
    except RecapError as e:  # audio processing failed -> keep the original/plain mix
        if not t.audio_enhance or e.code != "ffmpeg_failed":
            raise
        p.log(f"render(tf): audio enhance failed ({e}); retry with plain audio")
        audio_fallback = True
        final(False)
    if t.loudnorm:
        fix_loudness(out)
    keep = {Path(x[6:-1]).name for x in listing}
    for f in cdir.glob("clip_*.mp4"):
        if f.name not in keep:
            f.unlink(missing_ok=True)
    for f in cdir.glob("cmd_*.txt"):
        f.unlink(missing_ok=True)
    if clips:
        try:
            tf.compare_image(ctx, src, out, clips[0])
        except Exception as e:  # preview image is optional
            p.log(f"compare image failed: {e}")
    p.write_json("render/render_info.json", {
        "duration": total, "clips": len(clips), "reused": reused, "encoder": tf.encoder_args(ctx)[1],
        "size": [W, H], "transform": {"preset": s.transform.preset, "smart_reframe": tracked,
                                      "captions_top": top, "chapters": len(ch), "audio_fallback": audio_fallback}})
    return {"video": str(out.relative_to(p.root)).replace("\\", "/"), "info": "render/render_info.json"}
