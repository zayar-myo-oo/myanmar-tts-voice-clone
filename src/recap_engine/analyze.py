"""Stage 2: audio extraction, Demucs separation, shots + frames, hard-sub OCR,
vision captions and CLIP embeddings."""
from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .errors import RecapError
from .media import CREATE_NO_WINDOW, extract_audio, extract_frame, ffmpeg_bin, run as ff_run
from .pipeline import Context, gpu_lock


def _dur(ctx: Context) -> float:
    return float(ctx.project.manifest.source.get("probe", {}).get("duration") or 0)


# --------------------------------------------------------------------- audio
def audio_inputs(ctx: Context) -> Any:
    return {"src": ctx.project.manifest.source.get("file_hash")}


def stage_audio(ctx: Context) -> dict[str, str]:
    p = ctx.project
    out = p.path("analysis", "audio.wav")
    if not p.manifest.source.get("probe", {}).get("audio_tracks"):
        # silent source: make a silent track so the rest of the pipeline is uniform
        ff_run([ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{_dur(ctx):.3f}", "-c:a", "pcm_s16le", str(out)])
    else:
        extract_audio(p.source_video, out, cancel=ctx.cancelled)
    return {"audio": "analysis/audio.wav"}


# --------------------------------------------------------------------- demucs
def separate_inputs(ctx: Context) -> Any:
    return {"src": ctx.project.manifest.source.get("file_hash"), "model": "htdemucs", "v": 2}


def stage_separate(ctx: Context) -> dict[str, str]:
    p = ctx.project
    audio = p.path("analysis", "audio.wav")
    tmp = p.path("analysis", "_demucs")
    shutil.rmtree(tmp, ignore_errors=True)
    dev = "cuda" if _cuda() else "cpu"
    # --segment keeps peak VRAM well under 8 GB; demucs splits long audio internally.
    cmd = [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-d", dev,
           "--segment", "7", "--overlap", "0.1", "-j", "0", "-o", str(tmp), str(audio)]
    with gpu_lock(p, "demucs"):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        buf = ""
        tail: list[str] = []
        assert proc.stdout
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if ch in "\r\n":
                line, buf = buf, ""
                if line:
                    tail = (tail + [line])[-30:]
                    if "%|" in line:
                        try:
                            pct = float(line.split("%|")[0].strip().split()[-1])
                            ctx.progress(pct / 100 * 0.98, f"အသံခွဲနေပါတယ် (Demucs) {pct:.0f}%")
                        except (ValueError, IndexError):
                            pass
                if ctx.cancelled():
                    proc.kill()
                    ctx.check_cancel()
            else:
                buf += ch
        proc.wait()
    if proc.returncode != 0:
        msg = "\n".join(tail)
        if "out of memory" in msg.lower():
            raise RecapError("out_of_vram", "Demucs အတွက် VRAM မလောက်ပါ။ တခြား GPU app တွေ ပိတ်ပြီး Retry လုပ်ပါ။", msg)
        raise RecapError("stage_failed", "အသံခွဲ (Demucs) မအောင်မြင်ပါ။ Model Manager မှာ Demucs ကို စစ်ပါ။", msg)
    stem_dir = tmp / "htdemucs" / "audio"
    shutil.move(str(stem_dir / "vocals.wav"), p.path("analysis", "vocals.wav"))
    shutil.move(str(stem_dir / "no_vocals.wav"), p.path("analysis", "accompaniment.wav"))
    shutil.rmtree(tmp, ignore_errors=True)
    return {"vocals": "analysis/vocals.wav", "accompaniment": "analysis/accompaniment.wav"}


def _cuda() -> bool:
    try:
        import torch
        from .pipeline import cpu_only
        return torch.cuda.is_available() and not cpu_only()
    except Exception:
        return False


# --------------------------------------------------------------------- shots
def shots_inputs(ctx: Context) -> Any:
    return {"src": ctx.project.manifest.source.get("file_hash"), "v": 2}


def detect_shots(video: Path, duration: float, ctx: Context | None = None) -> list[dict]:
    from scenedetect import ContentDetector, SceneManager, open_video
    v = open_video(str(video))
    sm = SceneManager()
    sm.auto_downscale = True
    sm.add_detector(ContentDetector(threshold=27.0, min_scene_len=12))
    total = v.duration.get_frames() if v.duration else 0

    def cb(frame_img, pos):  # noqa: ARG001
        frame_num = pos.get_frames() if hasattr(pos, "get_frames") else int(pos)
        if ctx and total and frame_num % 200 == 0:
            ctx.progress(0.7 * frame_num / total, "Shot တွေ ခွဲနေပါတယ်")

    sm.detect_scenes(v, callback=cb, show_progress=False)
    scenes = sm.get_scene_list()
    shots = []
    for i, (a, b) in enumerate(scenes):
        shots.append({"id": i, "start": round(a.get_seconds(), 3), "end": round(b.get_seconds(), 3)})
    if not shots:
        shots = [{"id": 0, "start": 0.0, "end": round(duration, 3)}]
    # split very long shots into <=8 s pieces so clip choice has granularity
    out: list[dict] = []
    for s in shots:
        a, b = s["start"], s["end"]
        n = max(1, int(np.ceil((b - a) / 8.0)))
        step = (b - a) / n
        for k in range(n):
            out.append({"start": round(a + k * step, 3), "end": round(a + (k + 1) * step, 3),
                        "scene": s["id"]})
    for i, s in enumerate(out):
        s["id"] = i
    return out


def stage_shots(ctx: Context) -> dict[str, str]:
    p = ctx.project
    shots = detect_shots(p.source_video, _dur(ctx), ctx)
    fdir = p.path("analysis", "frames")
    fdir.mkdir(exist_ok=True)
    for i, s in enumerate(shots):
        if i % 10 == 0:
            ctx.progress(0.7 + 0.3 * i / len(shots), f"Frame ထုတ်နေပါတယ် {i}/{len(shots)}")
        t = (s["start"] + s["end"]) / 2
        name = f"shot_{s['id']:05d}.jpg"
        extract_frame(p.source_video, t, fdir / name)
        s["frame"] = f"analysis/frames/{name}"
    p.write_json("analysis/shots.json", shots)
    return {"shots": "analysis/shots.json"}


# --------------------------------------------------------------------- OCR
def ocr_inputs(ctx: Context) -> Any:
    return {"src": ctx.project.manifest.source.get("file_hash"), "on": ctx.settings.use_ocr, "v": 4}


class _Rapid:
    """RapidOCR (PP-OCR models, ONNX) on CUDA: ~40x faster than Paddle CPU on Windows."""

    def __init__(self):
        import torch  # noqa: F401  (loads CUDA/cuDNN DLLs for onnxruntime-gpu)
        from rapidocr import RapidOCR
        self.engine = RapidOCR(params={"EngineConfig.onnxruntime.use_cuda": _cuda(),
                                       "Global.use_cls": False, "Global.log_level": "error"})

    def run(self, img_path: str) -> list[tuple[str, float, list[float]]]:
        r = self.engine(img_path)
        if r is None or getattr(r, "txts", None) is None:
            return []
        out = []
        for t, sc, box in zip(r.txts, r.scores, r.boxes):
            arr = np.asarray(box, dtype=float)
            out.append((t, float(sc), [arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()]))
        return out


def _make_ocr():
    try:
        return _Rapid()
    except Exception:  # noqa: BLE001  fall back to Paddle CPU
        pass
    try:
        from paddleocr import PaddleOCR
    except ImportError as e:
        raise RecapError("missing_model", "PaddleOCR မရှိသေးပါ။ Model Manager မှာ install လုပ်ပါ။") from e
    try:  # PaddleOCR 3.x
        return PaddleOCR(lang="ch", use_doc_orientation_classify=False, use_doc_unwarping=False,
                         use_textline_orientation=False, enable_mkldnn=False)  # oneDNN PIR bug on Windows
    except TypeError:  # 2.x
        return PaddleOCR(lang="ch", use_angle_cls=False, show_log=False)


def _ocr_image(ocr, img_path: str) -> list[tuple[str, float, list[float]]]:
    """-> [(text, score, [x0,y0,x1,y1])] normalised to the image."""
    res: list[tuple[str, float, list[float]]] = []
    if isinstance(ocr, _Rapid):
        return ocr.run(img_path)
    if hasattr(ocr, "predict"):
        out = ocr.predict(img_path)
        for r in out or []:
            d = r if isinstance(r, dict) else getattr(r, "json", {}).get("res", {}) if hasattr(r, "json") else {}
            if not isinstance(d, dict) or "rec_texts" not in d:
                try:
                    d = dict(r)
                except Exception:
                    continue
            polys = d.get("rec_polys") if d.get("rec_polys") is not None else d.get("dt_polys", [])
            for t, sc, poly in zip(d.get("rec_texts", []), d.get("rec_scores", []), polys):
                arr = np.asarray(poly, dtype=float)
                res.append((t, float(sc), [arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()]))
    else:
        out = ocr.ocr(img_path, cls=False)
        for line in (out[0] if out else []) or []:
            poly, (t, sc) = line
            arr = np.asarray(poly, dtype=float)
            res.append((t, float(sc), [arr[:, 0].min(), arr[:, 1].min(), arr[:, 0].max(), arr[:, 1].max()]))
    return res


_HAN = __import__("re").compile(r"[一-鿿]")


def stage_ocr(ctx: Context) -> dict[str, str]:
    p = ctx.project
    pr = p.manifest.source.get("probe", {})
    W, H, dur = pr.get("width", 1920), pr.get("height", 1080), _dur(ctx)
    if not ctx.settings.use_ocr:
        p.write_json("analysis/ocr.json", {"region": None, "cues": [], "skipped": True})
        return {"ocr": "analysis/ocr.json"}
    step = 1.0 if dur <= 1800 else 1.5
    crop_top = 0.55  # subtitles live in the lower part of the frame
    sdir = p.path("analysis", "_ocr_frames")
    shutil.rmtree(sdir, ignore_errors=True)
    sdir.mkdir()
    ctx.progress(0.02, "Subtitle frame တွေ ထုတ်နေပါတယ်")
    ff_run([ffmpeg_bin(), "-y", "-v", "error", "-progress", "pipe:1", "-nostats", "-i", str(p.source_video),
            "-vf", f"fps={1 / step},crop=iw:ih*{1 - crop_top:.2f}:0:ih*{crop_top:.2f},scale=960:-2",
            "-q:v", "4", str(sdir / "f_%06d.jpg")], cancel=ctx.cancelled,
           progress=lambda f: ctx.progress(0.02 + 0.18 * f, "Subtitle frame တွေ ထုတ်နေပါတယ်"),
           total_seconds=dur)
    frames = sorted(sdir.glob("f_*.jpg"))
    ocr = _make_ocr()
    hits: list[dict] = []
    from PIL import Image
    fw, fh = (Image.open(frames[0]).size if frames else (960, 1))
    def read(f):
        return [x for x in _ocr_image(ocr, str(f)) if x[1] >= 0.75 and len(_HAN.findall(x[0])) >= 2]

    # quick probe: 24 evenly spaced frames; no Chinese subtitle at all -> skip the full pass
    probe_idx = sorted(set(np.linspace(0, len(frames) - 1, min(24, len(frames))).astype(int).tolist())) if frames else []
    if probe_idx and not any(read(frames[k]) for k in probe_idx):
        p.log("ocr: no burned-in Chinese subtitles found in probe frames; skipped")
        frames = []
    prev_small, prev_lines, skipped = None, [], 0
    for i, f in enumerate(frames):
        if i % 20 == 0:
            ctx.progress(0.2 + 0.75 * i / max(1, len(frames)), f"မူရင်း စာတန်းထိုး ဖတ်နေပါတယ် {i}/{len(frames)}")
        t = i * step
        small = np.asarray(Image.open(f).convert("L").resize((96, 24)), dtype=np.float32)
        if prev_small is not None and np.abs(small - prev_small).mean() < 2.0:
            lines, skipped = prev_lines, skipped + 1  # identical subtitle area -> reuse
        else:
            lines = read(f)
        prev_small, prev_lines = small, lines
        for text, sc, (x0, y0, x1, y1) in lines:
            cx = (x0 + x1) / 2 / fw
            if abs(cx - 0.5) > 0.2:  # subtitles are horizontally centred
                continue
            # map back to full-frame normalised coords
            ny0 = crop_top + (y0 / fh) * (1 - crop_top)
            ny1 = crop_top + (y1 / fh) * (1 - crop_top)
            hits.append({"t": round(t, 3), "text": text.strip(), "score": round(sc, 3),
                         "box": [round(x0 / fw, 4), round(ny0, 4), round(x1 / fw, 4), round(ny1, 4)]})
    del ocr
    shutil.rmtree(sdir, ignore_errors=True)
    region = subtitle_region(hits)
    cues = group_ocr_cues(hits, step)
    p.write_json("analysis/ocr.json", {"region": region, "cues": cues, "step": step, "frames": len(frames),
                                        "hits": len(hits), "frame_size": [W, H]})
    return {"ocr": "analysis/ocr.json"}


def subtitle_region(hits: list[dict]) -> dict | None:
    """Robust bounding region of burned-in subs, normalised [0..1], padded."""
    if len(hits) < 3:
        return None
    b = np.array([h["box"] for h in hits])
    # the dominant subtitle band: median y-centre, keep boxes near it
    yc = (b[:, 1] + b[:, 3]) / 2
    med = np.median(yc)
    keep = b[np.abs(yc - med) < 0.08]
    if len(keep) < 3:
        keep = b
    x0, y0 = np.percentile(keep[:, 0], 3), np.percentile(keep[:, 1], 3)
    x1, y1 = np.percentile(keep[:, 2], 97), np.percentile(keep[:, 3], 97)
    pad_x, pad_y = 0.03, 0.015
    return {"x0": round(max(0.0, x0 - pad_x), 4), "y0": round(max(0.0, y0 - pad_y), 4),
            "x1": round(min(1.0, x1 + pad_x), 4), "y1": round(min(1.0, y1 + pad_y), 4),
            "samples": int(len(keep))}


def group_ocr_cues(hits: list[dict], step: float) -> list[dict]:
    by_t: dict[float, list[dict]] = {}
    for h in hits:
        by_t.setdefault(h["t"], []).append(h)
    cues: list[dict] = []
    for t in sorted(by_t):
        text = "".join(x["text"] for x in sorted(by_t[t], key=lambda x: x["box"][1]))
        if cues and difflib.SequenceMatcher(None, cues[-1]["text"], text).ratio() > 0.7 \
                and t - cues[-1]["end"] <= step * 2.01:
            cues[-1]["end"] = round(t + step, 3)
            if len(text) > len(cues[-1]["text"]):
                cues[-1]["text"] = text
        else:
            cues.append({"start": t, "end": round(t + step, 3), "text": text, "source": "ocr"})
    return [c for c in cues if c["end"] - c["start"] >= step * 1.5 or len(cues) < 5]


# --------------------------------------------------------------------- vision + clip
def vision_inputs(ctx: Context) -> Any:
    from .llm import list_models, pick_vision_model
    p = ctx.project
    saved = p.read_json("analysis/vlm.json")
    models = list_models()
    pref = ctx.settings.vision_model
    keep = saved is not None and (not pref or pref == saved.get("vlm")) and \
        (not models or saved.get("vlm") is None or saved.get("vlm") in models)
    if keep:
        # Ollama down, or the project's model is still installed: keep it (installing another
        # model must not silently redo vision -> script -> voice)
        vlm = saved.get("vlm")
    else:
        vlm = pick_vision_model(ctx.settings.vision_model)
        p.write_json("analysis/vlm.json", {"vlm": vlm})
    return {"shots": p.stage("shots").input_hash, "vlm": vlm,
            "clip": CLIP_MODEL, "v": 2}


CLIP_MODEL = ("ViT-B-32", "laion2b_s34b_b79k")


def clip_model():
    import open_clip
    import torch
    dev = "cuda" if _cuda() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(CLIP_MODEL[0], pretrained=CLIP_MODEL[1], device=dev)
    tok = open_clip.get_tokenizer(CLIP_MODEL[0])
    model.eval()
    return model, preprocess, tok, dev


def embed_images(paths: list[Path], ctx: Context | None = None) -> np.ndarray:
    import torch
    from PIL import Image
    model, preprocess, _, dev = clip_model()
    embs = []
    with torch.no_grad():
        for i in range(0, len(paths), 32):
            if ctx:
                ctx.progress(0.05 + 0.25 * i / max(1, len(paths)), f"Frame embedding {i}/{len(paths)}")
            batch = torch.stack([preprocess(Image.open(x).convert("RGB")) for x in paths[i:i + 32]]).to(dev)
            e = model.encode_image(batch)
            embs.append((e / e.norm(dim=-1, keepdim=True)).float().cpu().numpy())
    del model
    return np.concatenate(embs) if embs else np.zeros((0, 512), dtype=np.float32)


def embed_texts(texts: list[str]) -> np.ndarray:
    import torch
    model, _, tok, dev = clip_model()
    with torch.no_grad():
        e = model.encode_text(tok(texts).to(dev))
        e = (e / e.norm(dim=-1, keepdim=True)).float().cpu().numpy()
    del model
    return e


def stage_vision(ctx: Context) -> dict[str, str]:
    from .llm import caption_image, pick_vision_model, unload
    p = ctx.project
    shots = p.read_json("analysis/shots.json", [])
    frames = [p.path(s["frame"]) for s in shots]
    with gpu_lock(p, "clip"):
        embs = embed_images(frames, ctx)
    np.save(p.path("analysis", "clip_frames.npy"), embs)
    vlm = pick_vision_model(ctx.settings.vision_model)
    captions: dict[str, str] = {}
    if vlm:
        # caption at most ~60 shots: evenly spread, so silent beats are understood
        idx = list(range(len(shots)))
        if len(idx) > 60:
            idx = sorted(set(np.linspace(0, len(shots) - 1, 60).astype(int).tolist()))
        with gpu_lock(p, f"vision:{vlm}"):
            for k, i in enumerate(idx):
                ctx.progress(0.3 + 0.7 * k / max(1, len(idx)), f"ပုံတွေကို နားလည်အောင် ကြည့်နေပါတယ် {k}/{len(idx)}")
                try:
                    captions[str(shots[i]["id"])] = caption_image(vlm, frames[i])
                except RecapError:
                    raise
                except Exception as e:  # noqa: BLE001
                    p.log(f"vision caption failed for shot {i}: {e}")
            unload(vlm)
    else:
        p.log("no local vision model found in Ollama; visual captions skipped")
    p.write_json("analysis/vision.json", {"model": vlm, "captions": captions, "clip": list(CLIP_MODEL)})
    return {"vision": "analysis/vision.json", "clip": "analysis/clip_frames.npy"}
