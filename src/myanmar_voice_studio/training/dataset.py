"""Phase 7 dataset check: validate own-voice recordings before fine-tuning.

    mvs-dataset check recordings/zayar --script docs/recording-script.md

Checks every WAV (format, length, clipping, loudness, noise floor, edge silence), pairs it
with its transcript (rNNN IDs from the script table, or a same-name .txt for long-form),
and writes a QC report plus train/validation manifests for the accepted clips.
Nothing in the recordings folder is modified.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from pydantic import BaseModel

MIN_SR = 24000
LOSSY_EXT = {".mp3", ".ogg", ".m4a", ".aac", ".opus", ".amr", ".wma"}


class ClipReport(BaseModel):
    file: str
    id: str
    ok: bool
    problems: list[str]
    warnings: list[str]
    sample_rate: int | None = None
    channels: int | None = None
    subtype: str | None = None
    duration_s: float | None = None
    peak_dbfs: float | None = None
    rms_dbfs: float | None = None
    noise_floor_dbfs: float | None = None
    snr_db: float | None = None
    lead_silence_s: float | None = None
    trail_silence_s: float | None = None
    text: str | None = None


class DatasetReport(BaseModel):
    folder: str
    speaker: dict
    clips: list[ClipReport]
    accepted: int
    rejected: int
    accepted_minutes: float
    target_minutes: dict[str, float]
    missing_ids: list[str]
    advice: list[str]


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def load_script_table(path: Path) -> dict[str, str]:
    rows = re.findall(r"^\| (r\d{3,}) \| (.+?) \|\s*$", path.read_text(encoding="utf-8"), re.M)
    return {i: t.strip() for i, t in rows}


def analyse(path: Path, text: str | None) -> ClipReport:
    rid = path.stem
    rep = ClipReport(file=path.name, id=rid, ok=False, problems=[], warnings=[], text=text)
    if path.suffix.lower() in LOSSY_EXT:
        rep.problems.append(f"lossy format {path.suffix} — re-record or export as WAV")
        return rep
    try:
        info = sf.info(path)
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception as exc:  # unreadable file
        rep.problems.append(f"cannot read audio: {exc}")
        return rep
    rep.sample_rate, rep.channels, rep.subtype = sr, info.channels, info.subtype
    mono = audio.mean(axis=1)
    rep.duration_s = round(mono.size / sr, 3)
    if info.channels > 1:
        rep.warnings.append("stereo — will be mixed to mono")
    if sr < MIN_SR:
        rep.problems.append(f"sample rate {sr} Hz < {MIN_SR} Hz")
    if rep.duration_s < 1.0:
        rep.problems.append("shorter than 1 s")
    elif rep.duration_s > 20.0:
        rep.problems.append("longer than 20 s — split into sentences (or use long-form .txt pairing)")
    peak = float(np.abs(mono).max()) if mono.size else 0.0
    rep.peak_dbfs = round(_db(peak), 1)
    clipped = float(np.mean(np.abs(mono) >= 0.999)) if mono.size else 0.0
    if clipped > 0.0005:
        rep.problems.append(f"clipping ({clipped * 100:.2f}% of samples at full scale)")
    elif peak < 10 ** (-20 / 20):
        rep.problems.append(f"too quiet (peak {rep.peak_dbfs} dBFS)")
    # 20 ms frames: noise floor = quietest 10%, speech level = loudest 50% median
    hop = max(1, int(sr * 0.02))
    frames = mono[: mono.size // hop * hop].reshape(-1, hop) if mono.size >= hop else mono.reshape(1, -1)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    if rms.size:
        srt = np.sort(rms)
        noise = float(srt[: max(1, srt.size // 10)].mean())
        speech = float(np.median(srt[srt.size // 2 :]))
        rep.rms_dbfs = round(_db(float(np.sqrt((mono.astype(np.float64) ** 2).mean()))), 1)
        rep.noise_floor_dbfs = round(_db(noise), 1)
        rep.snr_db = round(_db(speech) - _db(noise), 1)
        if rep.noise_floor_dbfs > -50:
            rep.problems.append(f"noisy background (floor {rep.noise_floor_dbfs} dBFS; want below -55)")
        elif rep.noise_floor_dbfs > -60:
            rep.warnings.append(f"background noise {rep.noise_floor_dbfs} dBFS (ok, quieter is better)")
        voiced = rms > max(noise * 4, 10 ** (-45 / 20))
        if voiced.any():
            first, last = int(np.argmax(voiced)), int(voiced.size - 1 - np.argmax(voiced[::-1]))
            rep.lead_silence_s = round(first * hop / sr, 2)
            rep.trail_silence_s = round((voiced.size - 1 - last) * hop / sr, 2)
            if rep.lead_silence_s < 0.1 or rep.trail_silence_s < 0.1:
                rep.warnings.append("speech touches the start/end — keep ~0.5 s silence")
            if rep.lead_silence_s > 2 or rep.trail_silence_s > 2:
                rep.warnings.append("more than 2 s silence at an edge — will be trimmed")
        else:
            rep.problems.append("no speech detected")
    if not text:
        rep.problems.append("no transcript (ID not in script table and no same-name .txt)")
    rep.ok = not rep.problems
    return rep


def check(folder: Path, script: Path | None, out: Path | None = None, val_ratio: float = 0.05, seed: int = 7) -> DatasetReport:
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"folder not found: {folder}")
    table = load_script_table(script) if script and Path(script).exists() else {}
    meta_path = folder / "metadata.json"
    speaker = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    audio_files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".wav", ".flac", *LOSSY_EXT})
    audio_files = [p for p in audio_files if not p.with_suffix(".rejected").exists()]  # user-excluded
    clips = []
    for p in audio_files:
        txt = p.with_suffix(".txt")
        text = txt.read_text(encoding="utf-8").strip() if txt.exists() else table.get(p.stem)
        clips.append(analyse(p, text))
    ok = [c for c in clips if c.ok]
    minutes = round(sum(c.duration_s or 0 for c in ok) / 60, 2)
    present = {c.id for c in clips}
    missing = [i for i in table if i not in present]
    advice: list[str] = []
    if not speaker:
        advice.append("add metadata.json (speaker, consent) — see docs/recording-guide.md §6")
    elif not speaker.get("consent"):
        advice.append("metadata.json has no consent statement")
    if any("lossy" in pr for c in clips for pr in c.problems):
        advice.append("some files are MP3/OGG — record WAV (48 kHz, mono)")
    if minutes < 30:
        advice.append(f"{minutes} min accepted; need at least 30 min (good: 60–120 min) before fine-tuning")
    report = DatasetReport(
        folder=str(folder), speaker=speaker, clips=clips, accepted=len(ok), rejected=len(clips) - len(ok),
        accepted_minutes=minutes, target_minutes={"minimum": 30.0, "good": 60.0, "best": 120.0},
        missing_ids=missing, advice=advice,
    )
    if out:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "qc_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        rng = random.Random(seed)
        items = [{"audio": str((folder / c.file).resolve()), "text": c.text, "duration_s": c.duration_s} for c in ok]
        rng.shuffle(items)
        n_val = max(1, int(len(items) * val_ratio)) if len(items) >= 20 else 0
        for name, part in (("val", items[:n_val]), ("train", items[n_val:])):
            with open(out / f"{name}.jsonl", "w", encoding="utf-8") as fh:
                for it in part:
                    fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="mvs-dataset")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate a recordings folder and write QC report + manifests")
    c.add_argument("folder", type=Path)
    c.add_argument("--script", type=Path, default=Path("docs/recording-script.md"))
    c.add_argument("--out", type=Path, help="where to write qc_report.json, train.jsonl, val.jsonl")
    args = ap.parse_args(argv)
    rep = check(args.folder, args.script, args.out)
    for clip in rep.clips:
        mark = "OK " if clip.ok else "BAD"
        detail = "; ".join(clip.problems + clip.warnings)
        print(f"{mark} {clip.file:28} {clip.duration_s or 0:6.2f}s  SNR {clip.snr_db}  {detail}")
    print(f"\naccepted {rep.accepted}, rejected {rep.rejected}, {rep.accepted_minutes} min usable")
    if rep.missing_ids:
        print(f"not recorded yet: {len(rep.missing_ids)} script lines ({rep.missing_ids[0]} …)")
    for a in rep.advice:
        print(f"- {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
