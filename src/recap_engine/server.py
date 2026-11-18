"""Drama Recap Studio — local web app (FastAPI). Run: python -m recap_engine.server

Job workers: several projects process at once. Workers are added automatically while jobs
are waiting (up to max_workers) and retire when idle. GPU-model stages are still serialised by
pipeline.gpu_lock (8 GB card), so extra workers overlap CPU/NVENC work with GPU work.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api
from .errors import RecapError
from .manifest import Project, default_projects_root
from .settings import ProjectSettings

WEB = Path(__file__).with_name("web")
ROOT = default_projects_root()
ROOT.mkdir(parents=True, exist_ok=True)


def auto_max_workers() -> int:
    env = os.environ.get("RECAP_JOB_WORKERS_MAX")
    if env and env.isdigit():
        return max(1, int(env))
    return max(1, min(4, (os.cpu_count() or 4) // 4))


class JobManager:
    IDLE_RETIRE_S = 30.0

    def __init__(self, min_workers: int = 1, max_workers: int | None = None):
        self.min_workers = min_workers
        self.max_workers = max_workers or auto_max_workers()
        self.queue: collections.deque[dict] = collections.deque()
        self.jobs: dict[str, dict] = {}  # project_id -> job state
        self.cv = threading.Condition()
        self.workers: dict[int, dict] = {}
        self._wid = 0

    # ---- public
    def submit(self, pid: str, force: set[str] | None = None, until: str | None = None) -> dict:
        with self.cv:
            j = self.jobs.get(pid)
            if j and j["state"] in ("queued", "running"):
                return j
            j = {"project_id": pid, "state": "queued", "stage": "", "progress": 0.0, "message": "တန်းစီနေပါတယ်",
                 "force": sorted(force or []), "until": until, "error": None, "queued_at": time.time(),
                 "cancel": threading.Event(), "worker": None}
            self.jobs[pid] = j
            self.queue.append(j)
            self._scale()
            self.cv.notify()
            return j

    def cancel(self, pid: str) -> bool:
        with self.cv:
            j = self.jobs.get(pid)
            if not j:
                return False
            if j["state"] == "queued":
                self.queue.remove(j)
                j["state"] = "cancelled"
            j["cancel"].set()
            return True

    def set_max(self, n: int) -> None:
        with self.cv:
            self.max_workers = max(1, int(n))  # no upper cap: user decides
            self._scale()
            self.cv.notify_all()  # surplus idle workers retire

    def status(self) -> dict:
        with self.cv:
            from .render import render_workers
            return {"max_workers": self.max_workers, "min_workers": self.min_workers,
                    "render_workers": render_workers(), "cpu_count": os.cpu_count(),
                    "tts_workers": __import__("recap_engine.tts", fromlist=["x"]).TTSClient.workers(),
                    "workers": [{"id": k, "busy": v["busy"]} for k, v in self.workers.items()],
                    "queued": [j["project_id"] for j in self.queue],
                    "running": [p for p, j in self.jobs.items() if j["state"] == "running"]}

    def public(self, pid: str) -> dict | None:
        j = self.jobs.get(pid)
        return None if j is None else {k: v for k, v in j.items() if k != "cancel"}

    # ---- internals
    def _scale(self) -> None:
        busy = sum(1 for w in self.workers.values() if w["busy"])
        want = min(self.max_workers, max(self.min_workers, busy + len(self.queue)))
        while len(self.workers) < want:  # queue growing -> add a worker
            self._wid += 1
            wid = self._wid
            self.workers[wid] = {"busy": False}
            threading.Thread(target=self._loop, args=(wid,), daemon=True, name=f"recap-worker-{wid}").start()

    def _loop(self, wid: int) -> None:
        idle_since = time.time()
        while True:
            with self.cv:
                while not self.queue:
                    too_many = len(self.workers) > self.max_workers
                    idle_long = time.time() - idle_since > self.IDLE_RETIRE_S and len(self.workers) > self.min_workers
                    if too_many or idle_long:  # retire
                        del self.workers[wid]
                        return
                    self.cv.wait(timeout=5)
                if len(self.workers) > self.max_workers:
                    del self.workers[wid]
                    return
                j = self.queue.popleft()
                j["state"], j["worker"], j["started_at"] = "running", wid, time.time()
                self.workers[wid]["busy"] = True
            self._run(j)
            with self.cv:
                self.workers[wid]["busy"] = False
                idle_since = time.time()
                self._scale()

    def _run(self, j: dict) -> None:
        def cb(e: dict) -> None:
            j.update(stage=e.get("stage", ""), progress=float(e.get("progress") or 0), message=e.get("message") or "")
        try:
            p = Project(ROOT / j["project_id"])
            api.run_project(p, cb, j["cancel"], force=set(j["force"]), until=j["until"])
            j["state"], j["progress"], j["message"] = "done", 1.0, "ပြီးပါပြီ"
        except Exception as e:  # noqa: BLE001
            if j["cancel"].is_set():
                j["state"], j["message"] = "cancelled", "ရပ်လိုက်ပါပြီ"
            else:
                j["state"] = "failed"
                j["error"] = e.to_dict() if isinstance(e, RecapError) else {"code": "error", "message": str(e)}
                j["message"] = j["error"]["message"]
        j["finished_at"] = time.time()
        up = j.get("upload")
        try:
            if up and Project(ROOT / j["project_id"]).stage("import").status == "done":
                shutil.rmtree(up, ignore_errors=True)
                j["upload"] = None
        except Exception:  # noqa: BLE001
            pass


jobs = JobManager()
app = FastAPI(title="Drama Recap Studio")


def _project(pid: str) -> Project:
    d = (ROOT / pid).resolve()
    if d.parent != ROOT.resolve() or not (d / "manifest.json").exists():
        raise HTTPException(404, "project not found")
    return Project(d)


@app.middleware("http")
async def _no_cache_ui(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):  # UI updates show up without a hard refresh
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.exception_handler(RecapError)
def _recap_err(_, e: RecapError):
    return JSONResponse(status_code=400, content=e.to_dict())


@app.get("/api/health")
def health() -> dict:
    from .llm import list_models
    from .media import has_nvenc
    return {"ok": True, "ollama": bool(list_models()), "nvenc": has_nvenc(), "projects_root": str(ROOT)}


@app.get("/api/workers")
def workers() -> dict:
    return jobs.status()


@app.put("/api/workers")
def set_workers(body: dict) -> dict:
    if "max_workers" in body:
        jobs.set_max(int(body["max_workers"]))
    if "tts_workers" in body:
        os.environ["RECAP_TTS_WORKERS"] = str(max(1, int(body["tts_workers"])))
    if "render_workers" in body:  # parallel clip encoders per video (read on each render)
        os.environ["RECAP_RENDER_WORKERS"] = str(max(1, int(body["render_workers"])))
    return jobs.status()


@app.get("/api/projects")
def projects() -> list[dict]:
    out = api.list_projects(ROOT)
    for x in out:
        j = jobs.public(x["project_id"])
        if j:
            x["job"] = j
    return out


@app.post("/api/projects")
def new_project(settings: str = Form("{}"), url: str = Form(""), title: str = Form(""),
                      file: UploadFile | None = File(None)) -> dict:
    try:
        s = ProjectSettings.model_validate(json.loads((settings or "{}").lstrip("﻿")))
    except ValueError as e:
        raise HTTPException(400, f"settings မမှန်ပါ: {e}") from e
    if s.mode == "subtitle":
        s.original_audio = "keep_all"
    e = engine()
    if e["mode"] == "cloud":  # API-key mode: cloud ASR + LLM + vision, no GPU stages
        s.whisper_model = "assemblyai"
        s.llm_model = "or:" + e["llm"]
        s.vision_model = "or:" + e["vision"]
        if s.original_audio == "remove_vocals":  # Demucs is GPU-heavy; on CPU it is very slow
            s.original_audio = "keep_all" if s.mode == "subtitle" else "mute_all"
    tmpdir = None
    try:
        src = None
        if file is not None and file.filename:
            (ROOT / "_uploads").mkdir(exist_ok=True)
            tmpdir = Path(tempfile.mkdtemp(prefix="up_", dir=ROOT / "_uploads"))
            src = tmpdir / Path(file.filename).name
            with src.open("wb") as f:
                shutil.copyfileobj(file.file, f, 8 << 20)
        elif not url.strip():
            raise HTTPException(400, "ဗီဒီယိုဖိုင် သို့မဟုတ် URL ထည့်ပါ။")
        p = api.create_project(url=url.strip() or None, file=src, settings=s, projects_root=ROOT,
                               title=title or (src.stem if src else ""))
    except BaseException:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    j = jobs.submit(p.manifest.project_id)
    j["upload"] = str(tmpdir) if tmpdir else None  # deleted once the import stage has copied it
    return {"project_id": p.manifest.project_id}


@app.get("/api/projects/{pid}")
def project(pid: str) -> dict:
    p = _project(pid)
    m = json.loads(p.manifest.model_dump_json())
    m["job"] = jobs.public(pid)
    m["status"] = api.overall_status(p)
    m["stage_order"] = [{"name": s.name, "label": s.label_my} for s in api.STAGES]
    for name, rel in (("qc", "export/qc_report.json"), ("rights", "export/rights_report.json"),
                      ("post_kit", "export/post_kit.json")):
        m[name] = p.read_json(rel)
    m["files"] = sorted(str(f.relative_to(p.root)).replace("\\", "/") for f in p.path("export").glob("*") if f.is_file())
    return m


@app.post("/api/projects/{pid}/run")
def run(pid: str, body: dict | None = None) -> dict:
    _project(pid)
    body = body or {}
    return jobs.public(jobs.submit(pid, set(body.get("force", [])), body.get("until"))["project_id"])


@app.post("/api/projects/{pid}/cancel")
def cancel(pid: str) -> dict:
    _project(pid)
    return {"ok": jobs.cancel(pid)}


@app.patch("/api/projects/{pid}/settings")
def patch_settings(pid: str, body: dict) -> dict:
    p = _project(pid)
    rerun = body.pop("rerun", True)
    data = p.manifest.settings.model_dump()
    for k, v in body.items():  # one level of nested merge (caption / transform / rights)
        data[k] = {**data[k], **v} if isinstance(v, dict) and isinstance(data.get(k), dict) else v
    p.manifest.settings = ProjectSettings.model_validate(data)
    p.save()
    if rerun:
        jobs.submit(pid)
    return {"settings": p.manifest.settings.model_dump()}


@app.patch("/api/projects/{pid}/beats/{bid}")
def patch_beat(pid: str, bid: int, body: dict) -> dict:
    p = _project(pid)
    api.edit_beat(p, bid, narration=body.get("narration"), voice_id=body.get("voice_id"))
    jobs.submit(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/file/{rel:path}")
def file(pid: str, rel: str):
    p = _project(pid)
    f = (p.root / rel).resolve()
    if p.root not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


# ------------------------------------------------------------------ studio extras
from fastapi.responses import Response  # noqa: E402

from . import cloud  # noqa: E402

ASSETS = ROOT / "_assets"
VOICEOVER = ROOT / "_voiceover"
SAMPLE_MY = "မင်္ဂလာပါ။ ဒီနေ့ ဇာတ်လမ်းလေးတစ်ပုဒ်ကို အတူတူ ကြည့်ကြရအောင်။"
VOICES = [{"id": "male_calm", "name": "အေးချမ်း (ကျား)", "gender": "male"},
          {"id": "male_deep", "name": "သြဇာ (ကျား)", "gender": "male"},
          {"id": "female_warm", "name": "နွေးထွေး (မ)", "gender": "female"},
          {"id": "edge_thiha", "name": "Thiha (ကျား, Microsoft)", "gender": "male"},
          {"id": "edge_nilar", "name": "Nilar (မ, Microsoft)", "gender": "female"}]


@app.get("/api/keys")
def keys() -> dict:
    return cloud.masked()


@app.put("/api/keys")
def put_keys(body: dict) -> dict:
    cloud.save_keys({k: v for k, v in body.items() if k in ("openrouter", "assemblyai")})
    return cloud.masked()


@app.post("/api/keys/test")
def test_keys(body: dict) -> dict:
    return cloud.test_key(body.get("name", "openrouter"))


@app.get("/api/voices")
def voices() -> list[dict]:
    return VOICES


@app.get("/api/voices/{vid}/preview")
def voice_preview(vid: str, speed: float = 1.0):
    from . import tts
    from .pipeline import STAGE_LOCKS
    d = VOICEOVER / "_preview"
    d.mkdir(parents=True, exist_ok=True)
    with STAGE_LOCKS["voice"]:
        r = tts.synth_cached(SAMPLE_MY, vid, d, f"pv_{vid}", max(0.6, min(1.6, speed)))
    return FileResponse(r["path"], media_type="audio/wav")


@app.post("/api/voiceover")
def voiceover(body: dict) -> dict:
    """Script -> Burmese voice wav + SRT (sentence by sentence, with a pause between)."""
    import re
    import uuid

    import numpy as np
    import soundfile as sf

    from . import tts
    from .burmese import split_phrases, wrap_two_lines
    from .captions import _ts
    from .pipeline import STAGE_LOCKS
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "စာသား ထည့်ပါ။")
    vid, speed = body.get("voice", "male_calm"), float(body.get("speed", 1.0))
    pause = max(0.0, float(body.get("pause_ms", 150)) / 1000)
    chars, lines = int(body.get("srt_chars", 32)), int(body.get("srt_lines", 1))
    sents = [x.strip() for x in re.split(r"(?<=[။!?\n])", text) if x.strip()]
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    d = VOICEOVER / jid
    d.mkdir(parents=True)
    pieces, cues, t, sr = [], [], 0.0, 24000
    with STAGE_LOCKS["voice"]:
        for i, s in enumerate(sents):
            r = tts.synth_cached(s, vid, d, f"s{i:04d}", speed)
            x, sr = sf.read(str(r["path"]), dtype="float32", always_2d=True)
            parts = split_phrases(s, chars * lines) or [s]
            w = [max(1, len(p)) for p in parts]
            dur = len(x) / sr
            a = t
            for ptxt, pw in zip(parts, w):
                b = a + dur * pw / sum(w)
                cues.append((a, b, wrap_two_lines(ptxt, chars) if lines == 2 else ptxt))
                a = b
            pieces += [x, np.zeros((int(pause * sr), x.shape[1]), dtype=np.float32)]
            t += dur + pause
    sf.write(str(d / "voiceover.wav"), np.concatenate(pieces), sr, subtype="PCM_16")
    srt = "\n".join(f"{i}\n{_ts(a)} --> {_ts(b)}\n{txt.replace(chr(92) + 'N', chr(10))}\n"
                    for i, (a, b, txt) in enumerate(cues, 1))
    (d / "voiceover.srt").write_text(srt, "utf-8")
    (d / "meta.json").write_text(json.dumps({"text": text, "voice": vid, "speed": speed, "seconds": round(t, 2),
                                             "created": time.time()}, ensure_ascii=False), "utf-8")
    for f in d.glob("s*.wav"):
        f.unlink(missing_ok=True)
    return {"id": jid, "seconds": round(t, 2), "wav": f"/api/voiceover/{jid}/voiceover.wav",
            "srt": f"/api/voiceover/{jid}/voiceover.srt"}


@app.get("/api/voiceover")
def voiceover_history() -> list[dict]:
    out = []
    for m in sorted(VOICEOVER.glob("*/meta.json"), reverse=True)[:50]:
        x = json.loads(m.read_text("utf-8"))
        out.append({"id": m.parent.name, **x, "wav": f"/api/voiceover/{m.parent.name}/voiceover.wav",
                    "srt": f"/api/voiceover/{m.parent.name}/voiceover.srt"})
    return out


@app.get("/api/voiceover/{jid}/{name}")
def voiceover_file(jid: str, name: str):
    f = (VOICEOVER / jid / name).resolve()
    if VOICEOVER.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@app.post("/api/assets")
def upload_asset(file: UploadFile = File(...)) -> dict:
    ASSETS.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "x.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        raise HTTPException(400, "PNG / JPG / WebP / SVG ပဲ ရပါတယ်။")
    import uuid
    out = ASSETS / f"{uuid.uuid4().hex[:10]}{ext}"
    with out.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(out), "url": f"/api/assets/{out.name}"}


@app.get("/api/assets/{name}")
def asset(name: str):
    f = (ASSETS / name).resolve()
    if ASSETS.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f)


@app.get("/api/projects/{pid}/log")
def project_log(pid: str, lines: int = 80) -> Response:
    p = _project(pid)
    f = p.path("logs", "engine.log")
    txt = f.read_text("utf-8", errors="replace").splitlines()[-lines:] if f.exists() else []
    return Response("\n".join(txt), media_type="text/plain; charset=utf-8")


@app.post("/api/projects/{pid}/open")
def open_folder(pid: str) -> dict:
    p = _project(pid)
    os.startfile(str(p.path("export")))  # local desktop app: show the export folder in Explorer
    return {"ok": True}


# ------------------------------------------------------------------ engine mode (local GPU / cloud)
ENGINE_FILE = Path(__file__).resolve().parents[2] / "config" / "app_settings.json"
ENGINE_DEFAULT = {"mode": "local", "llm": "google/gemini-2.5-flash", "vision": "google/gemini-2.5-flash"}


def engine() -> dict:
    try:
        return {**ENGINE_DEFAULT, **json.loads(ENGINE_FILE.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(ENGINE_DEFAULT)


def _apply_engine(e: dict) -> None:
    os.environ["RECAP_CPU_ONLY"] = "1" if e["mode"] == "cloud" else "0"


_apply_engine(engine())


@app.get("/api/engine")
def get_engine() -> dict:
    return {**engine(), "keys": cloud.masked()}


@app.put("/api/engine")
def put_engine(body: dict) -> dict:
    e = {**engine(), **{k: v for k, v in body.items() if k in ENGINE_DEFAULT}}
    if e["mode"] == "cloud":
        k = cloud.masked()
        if not (k["openrouter"]["set"] and k["assemblyai"]["set"]):
            raise HTTPException(400, "Cloud mode အတွက် AssemblyAI နဲ့ OpenRouter key ၂ ခုလုံး အရင် ထည့်ပါ။")
    ENGINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_FILE.write_text(json.dumps(e, indent=2), "utf-8")
    _apply_engine(e)
    return get_engine()


@app.get("/api/openrouter/models")
def openrouter_models() -> list[dict]:
    """Public model list (no key needed) -> id, name, price per 1M tokens, image input."""
    import httpx
    try:
        data = httpx.get("https://openrouter.ai/api/v1/models", timeout=20).json().get("data", [])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"OpenRouter model list ယူလို့ မရပါ: {e}") from e
    out = []
    for m in data:
        pr = m.get("pricing", {})
        try:
            pin, pout = float(pr.get("prompt", 0)) * 1e6, float(pr.get("completion", 0)) * 1e6
        except (TypeError, ValueError):
            continue
        mods = (m.get("architecture") or {}).get("input_modalities") or []
        out.append({"id": m["id"], "name": m.get("name", m["id"]), "in": round(pin, 3), "out": round(pout, 3),
                    "vision": "image" in mods})
    return sorted(out, key=lambda x: (x["in"] + x["out"], x["id"]))


# ------------------------------------------------------------------ source finder + downloader
DOWNLOADS = ROOT / "_downloads"


@app.post("/api/source-finder")
def source_finder(body: dict) -> dict:
    from .source_finder import find_sources
    pid = body.get("project_id")
    return find_sources(_project(pid) if pid else None, body.get("query", ""))


@app.post("/api/download")
def download(body: dict) -> dict:
    """YouTube / Bilibili / Douyin downloader (best <=1080p mp4)."""
    import subprocess
    import sys
    url = (body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "URL မှန်မှန် ထည့်ပါ။")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                        "--merge-output-format", "mp4", "--no-playlist", "--restrict-filenames",
                        "-o", str(DOWNLOADS / "%(title).80s-%(id)s.%(ext)s"), "--print", "after_move:filepath", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    lines = [x for x in r.stdout.splitlines() if x.strip()]
    if r.returncode != 0 or not lines:
        raise HTTPException(400, "ဒေါင်းလို့ မရပါ: " + (r.stderr.strip().splitlines() or ["unknown"])[-1][:300])
    f = Path(lines[-1])
    return {"name": f.name, "url": f"/api/downloads/{f.name}", "mb": round(f.stat().st_size / 1e6, 1)}


@app.get("/api/downloads/{name}")
def downloaded(name: str):
    f = (DOWNLOADS / name).resolve()
    if DOWNLOADS.resolve() not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, filename=f.name)


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")


def main() -> None:
    import argparse
    import webbrowser

    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--workers", type=int, default=None, help="max job workers (auto)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.workers:
        jobs.set_max(a.workers)
    if not a.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{a.port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
