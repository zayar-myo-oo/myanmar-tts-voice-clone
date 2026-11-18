"""Stage 1: import a local file or download a link with yt-dlp."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .errors import RecapError
from .manifest import Project, hash_file
from .media import CREATE_NO_WINDOW, ffmpeg_bin, probe
from .pipeline import Context

SUB_LANGS = ["zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "zh.*"]


def _ydl_error_my(msg: str) -> RecapError:
    low = msg.lower()
    if "drm" in low:
        why = "ဒီဗီဒီယိုမှာ DRM ကာကွယ်ထားလို့ ဒေါင်းလို့ မရပါ။"
    elif "private" in low or "login" in low or "sign in" in low or "cookies" in low:
        why = "ဒီဗီဒီယိုက private ဖြစ်နေတာ (သို့) login လိုအပ်တာပါ။ Settings မှာ 'browser cookies သုံးမယ်' ကို ဖွင့်ကြည့်ပါ။"
    elif "geo" in low or "not available in your country" in low:
        why = "ဒီဗီဒီယိုကို သင့်နိုင်ငံကနေ ကြည့်ခွင့် မရှိပါ (geo-block)။"
    elif "unsupported url" in low:
        why = "ဒီ website ကို မထောက်ပံ့ပါ။"
    elif "unable to download" in low or "http error" in low or "timed out" in low:
        why = "ဒေါင်းလုဒ် ဆွဲလို့ မရပါ (network ပြဿနာ ဖြစ်နိုင်ပါတယ်)။"
    else:
        why = "ဒီ link ကို ဒေါင်းလို့ မရပါ။"
    return RecapError("download_failed", why + " ဗီဒီယိုဖိုင်ကို ကိုယ်တိုင် ဒေါင်းပြီး Upload လုပ်ပါ။", detail=msg)


def _ydl_base_opts(ctx: Context | None, cookies_browser: str | None) -> dict[str, Any]:
    opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "noprogress": True,
                            "ffmpeg_location": str(Path(ffmpeg_bin()).parent), "retries": 10,
                            "fragment_retries": 10, "continuedl": True, "socket_timeout": 30}
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def list_playlist(url: str, cookies_browser: str | None = None) -> dict[str, Any]:
    """Return {'is_playlist', 'title', 'entries':[{url,title,duration}]} without downloading."""
    import yt_dlp
    opts = _ydl_base_opts(None, cookies_browser) | {"extract_flat": "in_playlist", "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        raise _ydl_error_my(str(e)) from e
    if info.get("_type") == "playlist" or info.get("entries"):
        entries = [{"url": e.get("url") or e.get("webpage_url"), "title": e.get("title"),
                    "duration": e.get("duration")} for e in (info.get("entries") or []) if e]
        return {"is_playlist": True, "title": info.get("title"), "entries": entries}
    return {"is_playlist": False, "title": info.get("title"),
            "entries": [{"url": url, "title": info.get("title"), "duration": info.get("duration")}]}


def download(ctx: Context, url: str, cookies_browser: str | None = None) -> Path:
    import yt_dlp
    p = ctx.project
    outdir = p.path("source")

    def hook(d: dict) -> None:
        if ctx.cancelled():
            raise yt_dlp.utils.DownloadCancelled("cancelled")
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if tot:
                spd = d.get("speed") or 0
                ctx.progress(0.95 * done / tot, f"ဒေါင်းနေပါတယ် {done / 1e6:.0f}/{tot / 1e6:.0f} MB"
                             + (f" · {spd / 1e6:.1f} MB/s" if spd else ""))

    opts = _ydl_base_opts(ctx, cookies_browser) | {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": {"default": str(outdir / "video.%(ext)s")},
        "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": SUB_LANGS,
        "subtitlesformat": "srt/vtt/best", "writeinfojson": True, "writethumbnail": True,
        "progress_hooks": [hook], "noplaylist": True,
        "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadCancelled:
        from .errors import Cancelled
        raise Cancelled()
    except Exception as e:  # noqa: BLE001
        if ctx.cancelled():
            from .errors import Cancelled
            raise Cancelled()
        raise _ydl_error_my(str(e)) from e
    vids = sorted(outdir.glob("video.mp4")) or sorted(x for x in outdir.glob("video.*")
                                                         if x.suffix in (".mp4", ".mkv", ".webm"))
    if not vids:
        raise RecapError("download_failed", "ဒေါင်းပြီးပေမယ့် ဗီဒီယိုဖိုင် မတွေ့ပါ။ ဖိုင်ကို Upload လုပ်ပါ။")
    info_json = next(outdir.glob("video.info.json"), None)
    if info_json and info_json.name != "info.json":
        shutil.copyfile(info_json, outdir / "info.json")
    p.manifest.title = p.manifest.title or (info.get("title") or "")
    p.manifest.source.update({"url": url, "uploader": info.get("uploader"), "thumbnail": info.get("thumbnail"),
                              "webpage_url": info.get("webpage_url")})
    p.save()
    return vids[0]


def extract_embedded_subs(video: Path, meta: dict, outdir: Path) -> list[str]:
    found = []
    for i, s in enumerate(meta.get("subtitle_tracks", [])):
        if s.get("codec") in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"):
            continue  # bitmap subs: handled by OCR path
        out = outdir / f"embedded_{i}_{s.get('lang') or 'und'}.srt"
        r = subprocess.run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-map", f"0:{s['index']}",
                            str(out)], capture_output=True, creationflags=CREATE_NO_WINDOW)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            found.append(out.name)
    return found


def stage_import_inputs(ctx: Context) -> Any:
    src = ctx.project.manifest.source
    # file_hash is written BY this stage, so it must not feed its own cache key (that made every
    # resume re-import, and failed once an uploaded original was cleaned up). Kept as None so
    # existing projects' stored keys still match.
    return {"url": src.get("url"), "file": src.get("original_file"), "fhash": None}


def stage_import(ctx: Context) -> dict[str, str]:
    p = ctx.project
    src = p.manifest.source
    if src.get("url") and not src.get("original_file"):
        video = download(ctx, src["url"], src.get("cookies_browser"))
    else:
        orig = Path(src["original_file"])
        if not orig.exists():
            raise RecapError("invalid_media", "ဖိုင် မတွေ့တော့ပါ။ ပြန် Upload လုပ်ပါ။")
        video = p.path("source", "video" + orig.suffix.lower())
        if orig.resolve() != video.resolve():
            ctx.progress(0.2, "ဖိုင်ကို project ထဲ ကူးနေပါတယ်")
            shutil.copyfile(orig, video)
    ctx.progress(0.96, "ဗီဒီယိုကို စစ်ဆေးနေပါတယ်")
    meta = probe(video)
    if meta["duration"] <= 0.5:
        raise RecapError("invalid_media", "ဗီဒီယို အရှည် မမှန်ပါ။ တခြားဖိုင် တင်ပါ။")
    if not meta["audio_tracks"]:
        p.log("warning: source has no audio track")
    subs = extract_embedded_subs(video, meta, p.path("source"))
    downloaded = [x.name for x in p.path("source").glob("video*.srt")]
    p.reload()
    p.manifest.source.update({"video": f"source/{video.name}", "probe": meta, "file_hash": hash_file(video),
                              "sub_files": downloaded + subs})
    if not p.manifest.title:
        p.manifest.title = Path(src.get("original_file") or video.name).stem
    p.save()
    return {"video": f"source/{video.name}"}
