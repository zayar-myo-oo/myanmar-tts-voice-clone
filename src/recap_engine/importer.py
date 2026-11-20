"""Stage 1: import a local file or download a link with yt-dlp."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from .errors import RecapError
from .manifest import Project, hash_file
from .media import CREATE_NO_WINDOW, ffmpeg_bin, probe
from .pipeline import Context

SUB_LANGS = ["zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "zh.*"]


APP_SETTINGS = Path(__file__).resolve().parents[2] / "config" / "app_settings.json"
COOKIE_BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "chromium", "vivaldi")
_URL_RE = re.compile(r"https?://[^\s<>\"'，。！？、）)】]+")
_XHS_RE = re.compile(r"^https?://(?:www\.)?(?:xiaohongshu|rednote)\.com/(?:explore|discovery/item)/[\da-f]+", re.I)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0 Safari/537.36")


def site_of(url: str) -> str:
    u = url.lower()
    for key, name in (("xiaohongshu.com", "rednote"), ("rednote.com", "rednote"), ("xhslink.com", "rednote"),
                      ("douyin.com", "douyin"), ("bilibili.com", "bilibili"), ("b23.tv", "bilibili"),
                      ("youtube.com", "youtube"), ("youtu.be", "youtube"), ("tiktok.com", "tiktok")):
        if key in u:
            return name
    return "other"


def normalize_url(text: str, resolve: bool = True) -> str:
    """Accept a bare link or a whole pasted share text (RedNote / Douyin share messages wrap the link in
    Chinese text). Returns the first link; RedNote short links (xhslink.com) are followed to the note page,
    and rednote.com note pages are mapped to xiaohongshu.com, the domain yt-dlp's extractor knows."""
    m = _URL_RE.search(text or "")
    if not m:
        return (text or "").strip()
    url = m.group(0).rstrip(".,;")
    if resolve and "xhslink.com" in url.lower():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (https link the user pasted)
                url = r.geturl()
        except Exception:  # noqa: BLE001  (keep the short link; yt-dlp reports the real error)
            pass
    if _XHS_RE.match(url):
        url = re.sub(r"^https?://(?:www\.)?rednote\.com", "https://www.xiaohongshu.com", url, flags=re.I)
        url = url.replace("/discovery/item/", "/explore/")
    return url


def default_cookies_browser() -> str | None:
    try:
        b = json.loads(APP_SETTINGS.read_text("utf-8")).get("cookies_browser") or ""
    except (OSError, ValueError):
        return None
    return b if b in COOKIE_BROWSERS else None


def format_for(url: str) -> str:
    # RedNote: take the original upload (yt-dlp's "direct" format) - those clips are short and already
    # web-sized; everything else stays capped at 1080p.
    if site_of(url) == "rednote":
        return "bv*+ba/b"
    return "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"


def _ydl_error_my(msg: str, url: str = "") -> RecapError:
    low = msg.lower()
    if site_of(url) == "rednote" and ("no video formats" in low or "404" in low or "login" in low
                                       or "unsupported url" in low):
        why = ("RedNote (小红书) က login ဝင်ထားမှ ဒေါင်းခွင့်ပေးပါတယ် (သို့) ဒီ post မှာ ပုံပဲ ပါပြီး ဗီဒီယို မပါပါ။ "
               "Browser မှာ rednote.com ကို login ဝင်ပြီး Video Downloader စာမျက်နှာမှာ "
               "'Login cookies ယူမယ့် browser' ကို ရွေးပါ (Firefox က အလုပ်အဖြစ်ဆုံးပါ)။ "
               "App ထဲက 'Share → Copy link' နဲ့ ရတဲ့ link အသစ်ကို သုံးပါ။")
        return RecapError("download_failed", why, detail=msg)
    if ("could not copy" in low and "cookie" in low) or "failed to decrypt" in low:
        why = "Browser cookies ကို ဖတ်လို့ မရပါ — Chrome / Edge ကို ပိတ်ပြီး ပြန်စမ်းပါ (သို့) Firefox ကို ရွေးပါ။"
        return RecapError("download_failed", why, detail=msg)
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
    cookies_browser = cookies_browser or default_cookies_browser()
    opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "noprogress": True,
                            "http_headers": {"User-Agent": UA},
                            "ffmpeg_location": str(Path(ffmpeg_bin()).parent), "retries": 10,
                            "fragment_retries": 10, "continuedl": True, "socket_timeout": 30}
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def list_playlist(url: str, cookies_browser: str | None = None) -> dict[str, Any]:
    """Return {'is_playlist', 'title', 'entries':[{url,title,duration}]} without downloading."""
    import yt_dlp
    url = normalize_url(url)
    opts = _ydl_base_opts(None, cookies_browser) | {"extract_flat": "in_playlist", "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        raise _ydl_error_my(str(e), url) from e
    if info.get("_type") == "playlist" or info.get("entries"):
        entries = [{"url": e.get("url") or e.get("webpage_url"), "title": e.get("title"),
                    "duration": e.get("duration")} for e in (info.get("entries") or []) if e]
        return {"is_playlist": True, "title": info.get("title"), "entries": entries}
    return {"is_playlist": False, "title": info.get("title"),
            "entries": [{"url": url, "title": info.get("title"), "duration": info.get("duration")}]}


def download(ctx: Context, url: str, cookies_browser: str | None = None) -> Path:
    import yt_dlp
    url = normalize_url(url)
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
        "format": format_for(url),
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
        raise _ydl_error_my(str(e), url) from e
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
