"""Stage 8: validate output + QC report (Burmese warnings)."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .burmese import display_len, wrap_two_lines
from .media import CREATE_NO_WINDOW, extract_frame, ffmpeg_bin, probe
from .pipeline import Context
from .transcribe import parse_srt


def measure_loudness(path: Path) -> dict:
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    txt = r.stderr
    summ = txt[txt.rfind("Summary:"):] if "Summary:" in txt else txt
    i = re.search(r"I:\s*(-?[\d.]+) LUFS", summ)
    pk = re.search(r"Peak:\s*(-?[\d.]+|-inf) dBFS", summ)
    return {"lufs": float(i.group(1)) if i else None,
            "true_peak_dbfs": (float(pk.group(1)) if pk and pk.group(1) != "-inf" else None)}


def silence_gaps(narration_wav: Path, min_gap: float = 1.0, thresh: float = 0.005) -> list[list[float]]:
    x, sr = sf.read(str(narration_wav), dtype="float32", always_2d=True)
    env = np.abs(x).max(axis=1)
    hop = sr // 100
    frames = env[: len(env) // hop * hop].reshape(-1, hop).max(axis=1)
    quiet = frames < thresh
    gaps, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        if (not q or i == len(quiet) - 1) and start is not None:
            if (i - start) / 100 >= min_gap:
                gaps.append([round(start / 100, 2), round(i / 100, 2)])
            start = None
    # trailing silence after the last word is expected
    if gaps and gaps[-1][1] >= len(quiet) / 100 - 0.05:
        gaps.pop()
    return gaps


def check_srt(path: Path, beats: list[dict], tol: float = 0.15, beat_ids: list | None = None) -> dict:
    cues = parse_srt(path.read_text("utf-8"))
    mono = all(cues[i]["start"] <= cues[i + 1]["start"] and cues[i]["end"] <= cues[i + 1]["start"] + 1e-3
               for i in range(len(cues) - 1)) and all(c["end"] > c["start"] for c in cues)
    # sync: first cue of each beat starts with the beat's narration
    errs = []
    if beat_ids is not None and len(beat_ids) == len(cues):
        # exact: group cues by beat; a cue may end early only where the next line already starts
        by_id = {b["id"]: b for b in beats}
        for i, c in enumerate(cues):
            c["beat"] = beat_ids[i]
        for bid in {c["beat"] for c in cues}:
            b = by_id.get(bid)
            mine = [i for i, c in enumerate(cues) if c["beat"] == bid]
            if not b or not mine:
                continue
            errs.append(abs(cues[mine[0]]["start"] - b["out_start"]))
            last = mine[-1]
            exp_end = b["out_end"]
            if last + 1 < len(cues):
                exp_end = min(exp_end, cues[last + 1]["start"])
            errs.append(abs(cues[last]["end"] - exp_end))
        max_err = max(errs) if errs else 0.0
        return {"cues": len(cues), "monotonic": mono, "max_sync_error_s": round(max_err, 3), "sync_ok": max_err <= tol}
    for b in beats:
        first = min((c for c in cues if c["start"] >= b["out_start"] - 0.5), key=lambda c: abs(c["start"] - b["out_start"]),
                    default=None)
        if first:
            errs.append(abs(first["start"] - b["out_start"]))
        last_end = max((c["end"] for c in cues if c["start"] < b["out_end"] and c["end"] > b["out_start"]), default=None)
        if last_end is not None:
            errs.append(abs(last_end - b["out_end"]))
    max_err = max(errs) if errs else 0.0
    return {"cues": len(cues), "monotonic": mono, "max_sync_error_s": round(max_err, 3), "sync_ok": max_err <= tol}


def caption_overflow(cues: list[dict], max_chars: int) -> list[dict]:
    bad = []
    for c in cues:
        lines = wrap_two_lines(c["text"], max_chars).split(r"\N")
        if len(lines) > 2 or any(display_len(x) > max_chars * 1.25 for x in lines):
            bad.append({"start": c["start"], "text": c["text"]})
    return bad


def qc_inputs(ctx: Context) -> Any:
    return {"render": ctx.project.stage("render").input_hash, "at": ctx.project.stage("render").finished, "v": 3}


def stage_qc(ctx: Context) -> dict[str, str]:
    p = ctx.project
    s = ctx.settings
    out = p.path(p.stage("render").artifacts.get("video", "export/final.mp4"))
    info = p.read_json("render/render_info.json", {})
    beats = p.read_json("script/beats.json", [])
    cues = p.read_json("render/cues.json", [])
    meta = probe(out)
    exp_w, exp_h = info.get("size", [0, 0])
    checks: dict[str, Any] = {
        "streams_ok": meta["streams"]["video"] == 1 and meta["streams"]["audio"] == 1,
        "duration_s": round(meta["duration"], 3), "expected_duration_s": info.get("duration"),
        "duration_ok": abs(meta["duration"] - float(info.get("duration") or 0)) <= 1.0,
        "resolution": [meta["width"], meta["height"]], "resolution_ok": [meta["width"], meta["height"]] == list(info.get("size", [])),
        "video_codec": meta["video_codec"],
    }
    ctx.progress(0.3, "အသံ ကျယ်/တိုး စစ်နေပါတယ်")
    loud = measure_loudness(out)
    checks |= loud
    checks["loudness_ok"] = loud["lufs"] is not None and abs(loud["lufs"] + 14) <= 1.5
    checks["clipping"] = loud["true_peak_dbfs"] is not None and loud["true_peak_dbfs"] > -0.5
    gaps = silence_gaps(p.path("render", "narration.wav"))
    checks["silence_gaps_gt_1s"] = gaps if s.mode not in ("pro", "subtitle") else []  # pro mode follows original pauses
    srt = check_srt(p.path("export", "final.srt"), beats, beat_ids=[c.get("beat") for c in cues] if cues else None)
    checks["srt"] = srt
    checks["caption_overflow"] = caption_overflow(cues, s.caption.max_chars_per_line)
    # caption frame for visual check of Myanmar shaping
    if cues:
        mid = cues[min(len(cues) - 1, 1)]
        extract_frame(out, (mid["start"] + mid["end"]) / 2, p.path("export", "caption_frame.png"), width=exp_w or 1080)
    stages = {k: v.seconds for k, v in p.manifest.stages.items() if v.seconds is not None}
    checks["stage_seconds"] = stages
    checks["vram_peak_mib"] = p.manifest.source.get("vram_peak_mib")
    warnings = []
    if not checks["streams_ok"]:
        warnings.append("ဗီဒီယိုထဲမှာ video/audio stream မပြည့်စုံပါ။")
    if not checks["duration_ok"]:
        warnings.append("ဗီဒီယို အရှည် မျှော်မှန်းထားတာနဲ့ မကိုက်ပါ။")
    if not checks["loudness_ok"]:
        warnings.append(f"အသံကျယ်မှု {loud['lufs']} LUFS ဖြစ်နေပါတယ် (-14 ဖြစ်သင့်)။")
    if checks["clipping"]:
        warnings.append("အသံ clipping (အက်ကွဲသံ) ဖြစ်နိုင်ပါတယ်။")
    if checks["silence_gaps_gt_1s"]:
        warnings.append(f"နောက်ခံပြောသံ ၁ စက္ကန့်ထက် ပိုတိတ်နေတဲ့နေရာ {len(gaps)} ခု ရှိပါတယ်။")
    if not srt["monotonic"]:
        warnings.append("SRT အချိန်တွေ အစီအစဉ် မမှန်ပါ။")
    if not srt["sync_ok"]:
        warnings.append(f"စာတန်းထိုးနဲ့ ပြောသံ {srt['max_sync_error_s']}s ကွာနေပါတယ်။")
    if checks["caption_overflow"]:
        warnings.append(f"စာတန်းထိုး {len(checks['caption_overflow'])} ခု ရှည်လွန်းပါတယ်။")
    if s.transform.enabled and s.transform.verify:
        tfc = transform_checks(ctx, out)
        checks["transform"] = tfc
        if not tfc["av_sync_ok"]:
            warnings.append(f"Video နဲ့ audio အရှည် {tfc['av_diff_s']}s ကွာနေပါတယ်။")
        if tfc.get("original_audio_intact") is False:
            warnings.append("မူရင်း တရုတ်အသံ ပြောင်းသွားပုံ ရပါတယ်။ Audio enhance ကို ပိတ်ကြည့်ပါ။")
        if not s.transform.loudnorm and "loudness_ok" in checks:
            warnings = [w for w in warnings if "LUFS" not in w]  # user turned loudness normalisation off
    checks["warnings_my"] = warnings
    checks["passed"] = not warnings
    p.write_json("export/qc_report.json", checks)
    return {"qc": "export/qc_report.json"}


def _stream_durations(path: Path) -> tuple[float, float]:
    from .media import ffprobe_bin
    r = subprocess.run([ffprobe_bin(), "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "csv=p=0",
                        str(path)], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    d = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) == 2 and parts[1] not in ("", "N/A"):
            d[parts[0]] = float(parts[1])
    return d.get("video", 0.0), d.get("audio", 0.0)


def _pcm(path: Path, start: float, dur: float, sr: int = 8000) -> np.ndarray:
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(path),
                        "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True,
                       creationflags=CREATE_NO_WINDOW)
    return np.frombuffer(r.stdout, dtype=np.float32)


def transform_checks(ctx: Context, out: Path) -> dict:
    p = ctx.project
    v, a = _stream_durations(out)
    res = {"video_s": round(v, 3), "audio_s": round(a, 3), "av_diff_s": round(abs(v - a), 3),
           "av_sync_ok": abs(v - a) <= 0.25}
    if ctx.settings.mode == "subtitle":  # Mode B: output audio must still be the original Chinese track
        x = _pcm(out, 0, 30)
        y = _pcm(p.path("analysis", "audio.wav"), 0, 30)
        n = min(len(x), len(y))
        if n > 8000:
            hop = 160  # 20 ms RMS envelopes: robust to AAC priming delay and gain changes
            k = n // hop
            x = np.sqrt((x[: k * hop].reshape(k, hop) ** 2).mean(axis=1))
            y = np.sqrt((y[: k * hop].reshape(k, hop) ** 2).mean(axis=1))
            x, y = x - x.mean(), y - y.mean()
            corr = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
            res["original_audio_corr"] = round(corr, 3)
            res["original_audio_intact"] = corr > 0.6
    return res
