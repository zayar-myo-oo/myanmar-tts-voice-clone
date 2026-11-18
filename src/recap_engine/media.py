"""FFmpeg / ffprobe helpers."""
from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .errors import RecapError

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ffmpeg_bin() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RecapError("missing_ffmpeg", "FFmpeg မတွေ့ပါ။ FFmpeg ကို install လုပ်ပြီး PATH ထဲ ထည့်ပါ။")
    return p


def ffprobe_bin() -> str:
    p = shutil.which("ffprobe")
    if not p:
        raise RecapError("missing_ffmpeg", "ffprobe မတွေ့ပါ။ FFmpeg ကို install လုပ်ပါ။")
    return p


def run(cmd: list[str], *, cancel: Callable[[], bool] | None = None,
        progress: Callable[[float], None] | None = None, total_seconds: float | None = None) -> str:
    """Run ffmpeg-like command; parse `-progress pipe:1` out_time for progress; support cancel."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    err_lines: list[str] = []
    import threading

    def _drain() -> None:
        assert proc.stderr
        for line in proc.stderr:
            err_lines.append(line)
            if len(err_lines) > 400:
                del err_lines[:200]

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    out_lines: list[str] = []
    assert proc.stdout
    for line in proc.stdout:
        out_lines.append(line)
        if cancel and cancel():
            proc.kill()
            proc.wait()
            from .errors import Cancelled
            raise Cancelled()
        if progress and total_seconds and line.startswith("out_time_us="):
            try:
                us = int(line.split("=", 1)[1])
                progress(min(1.0, us / 1e6 / total_seconds))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        tail = "".join(err_lines[-25:])
        raise RecapError("ffmpeg_failed", "FFmpeg အလုပ် မအောင်မြင်ပါ။ log ကို ကြည့်ပါ။", detail=tail)
    return "".join(out_lines)


def probe(path: Path) -> dict[str, Any]:
    out = subprocess.run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True,
                         encoding="utf-8", creationflags=CREATE_NO_WINDOW)
    if out.returncode != 0:
        raise RecapError("invalid_media", "ဗီဒီယိုဖိုင် ဖတ်လို့ မရပါ။ ဖိုင်ပျက်နေသလား စစ်ပြီး တခြားဖိုင် တင်ကြည့်ပါ။",
                         detail=out.stderr[-2000:])
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = [s for s in streams if s.get("codec_type") == "audio"]
    subs = [s for s in streams if s.get("codec_type") == "subtitle"]
    if v is None:
        raise RecapError("invalid_media", "ဒီဖိုင်ထဲမှာ ဗီဒီယို မပါပါ။ ဗီဒီယိုဖိုင် တင်ပါ။")
    fmt = data.get("format", {})
    dur = float(fmt.get("duration") or v.get("duration") or 0)
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    fps = v.get("avg_frame_rate", "0/1")
    try:
        n, d = fps.split("/")
        fps_f = float(n) / float(d) if float(d) else 0.0
    except ValueError:
        fps_f = 0.0
    return {
        "container": fmt.get("format_name"),
        "duration": dur,
        "width": w,
        "height": h,
        "aspect": round(w / h, 4) if h else None,
        "fps": round(fps_f, 3),
        "video_codec": v.get("codec_name"),
        "audio_tracks": [{"index": s["index"], "codec": s.get("codec_name"),
                          "lang": s.get("tags", {}).get("language")} for s in a],
        "subtitle_tracks": [{"index": s["index"], "codec": s.get("codec_name"),
                             "lang": s.get("tags", {}).get("language")} for s in subs],
        "streams": {"video": 1, "audio": len(a), "subtitle": len(subs)},
    }


def has_nvenc() -> bool:
    from .pipeline import cpu_only
    return not cpu_only() and _has_nvenc()


@functools.lru_cache(maxsize=1)
def _has_nvenc() -> bool:
    try:
        r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "color=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True, timeout=30, creationflags=CREATE_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def video_encoder_args(proxy: bool = False, intermediate: bool = False) -> list[str]:
    """Final: high quality for re-upload (platforms re-compress). Intermediate clips: near-lossless
    so the final pass (captions burned in) does not stack a second generation of blur."""
    if proxy:
        return (["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "30", "-b:v", "0", "-pix_fmt", "yuv420p"] if has_nvenc()
                else ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p"])
    if has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", "14" if intermediate else "18",
                "-b:v", "0", "-maxrate", "60M" if intermediate else "25M", "-bufsize", "50M",
                "-spatial-aq", "1", "-temporal-aq", "1", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "fast" if intermediate else "slow", "-crf", "12" if intermediate else "17",
            "-profile:v", "high", "-pix_fmt", "yuv420p"]


def extract_audio(src: Path, out: Path, sr: int = 48000, cancel=None) -> Path:
    run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "2", "-ar", str(sr),
         "-c:a", "pcm_s16le", str(out)], cancel=cancel)
    return out


def extract_frame(src: Path, t: float, out: Path, width: int = 640) -> Path:
    run([ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "3", str(out)])
    return out


def audio_duration(path: Path) -> float:
    import soundfile as sf
    info = sf.info(str(path))
    return info.frames / info.samplerate


def ffmpeg_filter_path(p: Path) -> str:
    """Escape a Windows path for use inside an ffmpeg filter argument."""
    s = str(p).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", r"\1\\:", s)
    return s.replace("'", r"\'")
