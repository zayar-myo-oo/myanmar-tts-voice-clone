"""Stage 3: Faster-Whisper on vocals.wav + merge with downloaded/embedded subs and OCR."""
from __future__ import annotations

import difflib
import os
import re
from pathlib import Path
from typing import Any

from .errors import RecapError
from .pipeline import Context, gpu_lock

TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [x for x in block.strip().split("\n") if x.strip()]
        tl = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if tl is None:
            continue
        a, b = lines[tl].split("-->")
        ma, mb = TS.search(a), TS.search(b)
        if not ma or not mb:
            continue

        def sec(m):
            h, mi, s, ms = m.groups()
            return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000

        txt = re.sub(r"<[^>]+>|\{[^}]+\}", "", " ".join(lines[tl + 1:])).strip()
        if txt:
            cues.append({"start": round(sec(ma), 3), "end": round(sec(mb), 3), "text": txt})
    return cues


def transcribe_inputs(ctx: Context) -> Any:
    p = ctx.project
    return {"sep": p.stage("separate").input_hash, "ocr": p.stage("ocr").input_hash,
            "subs": p.manifest.source.get("sub_files"), "model": ctx.settings.whisper_model, "v": 2}


WHISPER_ALIASES = {  # local CTranslate2 conversions (models/), else a faster-whisper hub name
    "belle-zh": "belle-whisper-large-v3-turbo-zh-ct2",  # Chinese fine-tune of large-v3-turbo (Apache-2.0)
}


def resolve_whisper(name: str) -> str:
    local = Path(__file__).resolve().parents[2] / "models" / WHISPER_ALIASES.get(name, name)
    if (local / "model.bin").exists():
        return str(local)
    return "large-v3-turbo" if name in WHISPER_ALIASES else name  # alias not downloaded -> stock model


def run_whisper(ctx: Context, audio: Path) -> list[dict]:
    if ctx.settings.whisper_model == "assemblyai":  # Own-key mode: cloud ASR
        from .cloud import assemblyai_transcribe
        return assemblyai_transcribe(audio, ctx.cancelled, ctx.progress)
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RecapError("missing_model", "faster-whisper မရှိသေးပါ။ Model Manager မှာ install လုပ်ပါ။") from e
    name = ctx.settings.whisper_model
    import torch
    from .pipeline import cpu_only
    dev = "cuda" if torch.cuda.is_available() and not cpu_only() else "cpu"
    with gpu_lock(ctx.project, f"whisper:{name}"):
        try:
            model = WhisperModel(resolve_whisper(name), device=dev, compute_type="float16" if dev == "cuda" else "int8")
        except Exception as e:  # noqa: BLE001
            if "out of memory" in str(e).lower():
                raise RecapError("out_of_vram", f"Whisper {name} အတွက် VRAM မလောက်ပါ။ Settings မှာ 'medium' ရွေးပါ။") from e
            raise
        kw = dict(language="zh", word_timestamps=True, vad_filter=True,
                  vad_parameters={"min_silence_duration_ms": 400}, beam_size=5,
                  condition_on_previous_text=False, initial_prompt="以下是普通话的句子。")
        bs = int(os.environ.get("RECAP_WHISPER_BATCH", "1"))  # batched merges lines into huge segments -> off
        if bs > 1 and dev == "cuda":
            # chunked: VAD splits the audio, chunks are decoded together on the GPU (several x faster)
            from faster_whisper import BatchedInferencePipeline
            segs, info = BatchedInferencePipeline(model=model).transcribe(str(audio), batch_size=bs, **kw)
        else:
            segs, info = model.transcribe(str(audio), **kw)
        out = []
        for s in segs:
            ctx.progress(min(0.98, s.end / max(1.0, info.duration)), f"စကားပြော နားထောင်နေပါတယ် {s.end:.0f}/{info.duration:.0f}s")
            text = s.text.strip()
            if not text or s.no_speech_prob > 0.8:
                continue
            out.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": text, "source": "whisper",
                        "conf": round(float(s.avg_logprob), 3),
                        "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "w": w.word}
                                  for w in (s.words or [])]})
        del model
    return out


def _overlap(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / max(1e-3, min(a["end"] - a["start"], b["end"] - b["start"]))


def merge_sources(subs: list[dict], ocr: list[dict], whisper: list[dict]) -> list[dict]:
    """Priority: subs > OCR > Whisper. Lower-priority cues are only kept where no
    higher-priority cue overlaps in time with similar text (or at all, for subs)."""
    merged: list[dict] = [dict(c, source=c.get("source", "subs")) for c in subs]
    for group in (ocr, whisper):
        for c in group:
            clash = [m for m in merged if _overlap(m, c) > 0.3]
            if not clash:
                merged.append(dict(c))
                continue
            # keep whisper word timings by attaching them to the overlapping higher-priority cue
            if c.get("words"):
                for m in clash:
                    m.setdefault("alt", []).append(c["text"])
            for m in clash:
                if m["source"] == "ocr" and difflib.SequenceMatcher(None, m["text"], c["text"]).ratio() < 0.3:
                    m.setdefault("alt", []).append(c["text"])
    merged.sort(key=lambda x: x["start"])
    for i, m in enumerate(merged):
        m["id"] = i
    return merged


def stage_transcribe(ctx: Context) -> dict[str, str]:
    p = ctx.project
    subs: list[dict] = []
    for name in p.manifest.source.get("sub_files", []) or []:
        f = p.path("source", name)
        if f.exists() and re.search(r"zh|chi|und|embedded", name, re.I):
            subs = [dict(c, source="subs") for c in parse_srt(f.read_text("utf-8", errors="replace"))]
            if subs:
                p.log(f"using subtitle file {name} ({len(subs)} cues)")
                break
    ocr = p.read_json("analysis/ocr.json", {}).get("cues", [])
    vocals = p.path("analysis", "vocals.wav")
    if not vocals.exists():
        vocals = p.path("analysis", "audio.wav")
    whisper = run_whisper(ctx, vocals)
    p.write_json("analysis/whisper.json", whisper)
    merged = merge_sources(subs, ocr, whisper)
    p.write_json("analysis/transcript.json", {"cues": merged, "counts": {"subs": len(subs), "ocr": len(ocr),
                                                                         "whisper": len(whisper)}})
    return {"transcript": "analysis/transcript.json", "whisper": "analysis/whisper.json"}
