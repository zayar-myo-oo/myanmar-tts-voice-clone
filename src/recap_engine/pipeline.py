"""Stage runner: idempotent, hash-cached, cancellable, resumable, progress-reporting.

Each stage declares ``inputs(ctx) -> obj`` (hashed) and ``run(ctx) -> artifacts``.
If the stored input hash matches and every artifact still exists, the stage is a
cache hit and is skipped. A crash leaves the stage "running" -> it simply re-runs.
"""
from __future__ import annotations

import contextlib
import gc
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import Cancelled, RecapError
from .manifest import Project, hash_obj

ProgressCb = Callable[[dict], None]

# ---- GPU lock: only one GPU model at a time, across threads AND processes ----
_gpu_thread_lock = threading.Lock()
_gpu_local = threading.local()
# stages that load a GPU model: with several job workers these run one at a time;
# CPU/NVENC stages (import, shots, voice, timeline, captions, render, qc, ...) run in parallel
GPU_STAGES = {"separate", "ocr", "vision", "transcribe", "script"}
# stages sharing one process-wide resource (the TTS subprocess) also run one at a time
STAGE_LOCKS: dict[str, threading.RLock] = {"voice": threading.RLock()}


@contextlib.contextmanager
def gpu_lock(project: Project | None = None, name: str = ""):
    if getattr(_gpu_local, "depth", 0):  # re-entrant within one thread (stage lock + inner lock)
        _gpu_local.depth += 1
        try:
            yield
        finally:
            _gpu_local.depth -= 1
        return
    with _gpu_lock_inner(project, name):
        _gpu_local.depth = 1
        try:
            yield
        finally:
            _gpu_local.depth = 0


@contextlib.contextmanager
def _gpu_lock_inner(project: Project | None = None, name: str = ""):
    lock_path = Path(os.environ.get("RECAP_GPU_LOCK", str(Path.home() / ".recap_gpu.lock")))
    with _gpu_thread_lock:
        fh = open(lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                while True:
                    try:
                        fh.seek(0)
                        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.5)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX)
            if project:
                project.log(f"GPU lock acquired: {name}")
            yield
        finally:
            free_gpu()
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            fh.close()


def cpu_only() -> bool:
    """Cloud (API key) mode: never touch the GPU (OCR/CLIP/Whisper on CPU, x264 instead of NVENC)."""
    return os.environ.get("RECAP_CPU_ONLY") == "1"


def free_gpu() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


class VramMonitor:
    """Samples nvidia-smi used memory in a background thread; reports the peak in MiB."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak = 0
        self.baseline = None
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _sample(self) -> int | None:
        import subprocess
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return int(out.stdout.strip().splitlines()[0])
        except Exception:
            return None

    def __enter__(self):
        self.baseline = self._sample()

        def loop():
            while not self._stop.is_set():
                v = self._sample()
                if v is not None:
                    self.peak = max(self.peak, v)
                self._stop.wait(self.interval)

        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t:
            self._t.join(timeout=3)


@dataclass
class Context:
    project: Project
    progress_cb: ProgressCb | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    stage_name: str = ""
    stage_index: int = 0
    stage_count: int = 1
    force: set[str] = field(default_factory=set)

    @property
    def settings(self):
        return self.project.manifest.settings

    def cancelled(self) -> bool:
        if self.cancel_event.is_set():
            return True
        flag = self.project.path("CANCEL")
        return flag.exists()

    def check_cancel(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def progress(self, frac: float, message: str = "") -> None:
        self.check_cancel()
        overall = (self.stage_index + max(0.0, min(1.0, frac))) / max(1, self.stage_count)
        evt = {"project_id": self.project.manifest.project_id, "stage": self.stage_name,
               "stage_progress": round(frac, 4), "progress": round(overall, 4), "message": message,
               "time": time.time()}
        if message:
            self.project.log(f"[{self.stage_name}] {int(frac * 100)}% {message}")
        if self.progress_cb:
            self.progress_cb(evt)


@dataclass
class Stage:
    name: str
    label_my: str
    inputs: Callable[[Context], Any]
    run: Callable[[Context], dict[str, str]]
    enabled: Callable[[Context], bool] = lambda ctx: True


def _artifacts_exist(project: Project, artifacts: dict[str, str]) -> bool:
    return all(project.path(p).exists() for p in artifacts.values())


def run_stages(ctx: Context, stages: list[Stage]) -> None:
    p = ctx.project
    with contextlib.suppress(FileNotFoundError):
        p.path("CANCEL").unlink()
    active = [s for s in stages if s.enabled(ctx)]
    ctx.stage_count = len(active)
    for i, st in enumerate(active):
        ctx.stage_name, ctx.stage_index = st.name, i
        ctx.check_cancel()
        state = p.stage(st.name)
        h = hash_obj({"stage": st.name, "inputs": st.inputs(ctx)})
        if (st.name not in ctx.force and state.status == "done" and state.input_hash == h
                and _artifacts_exist(p, state.artifacts)):
            state.cache_hit = True
            p.save()
            p.log(f"[{st.name}] cache hit ({h})")
            ctx.progress(1.0, f"{st.label_my} — cache ကို ပြန်သုံးပါတယ်")
            continue
        state.status, state.started, state.error, state.cache_hit = "running", time.time(), None, False
        p.save()
        ctx.progress(0.0, st.label_my)
        try:
            with (gpu_lock(p, st.name) if st.name in GPU_STAGES else contextlib.nullcontext()), \
                    STAGE_LOCKS.get(st.name, contextlib.nullcontext()):
                arts = st.run(ctx) or {}
        except Cancelled:
            state.status = "cancelled"
            p.save()
            raise
        except RecapError as e:
            state.status, state.error = "failed", e.message_my + ("\n" + e.detail if e.detail else "")
            p.save()
            p.log(f"[{st.name}] FAILED {e}")
            raise
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc()
            msg = str(e)
            if "out of memory" in msg.lower() or "CUDA_ERROR_OUT_OF_MEMORY" in msg:
                err = RecapError("out_of_vram", "GPU memory (VRAM) မလောက်ပါ။ Settings မှာ model အသေး ရွေးပြီး ဒီအဆင့်ကို Retry လုပ်ပါ။", tb)
            else:
                err = RecapError("stage_failed", f"'{st.label_my}' အဆင့် မအောင်မြင်ပါ။ Retry နှိပ်ပြီး ပြန်စမ်းပါ။", tb)
            state.status, state.error = "failed", err.message_my + "\n" + tb[-3000:]
            p.save()
            p.log(f"[{st.name}] FAILED\n{tb}")
            raise err from e
        p.reload()
        state = p.stage(st.name)
        state.status, state.finished = "done", time.time()
        state.seconds = round(state.finished - (state.started or state.finished), 2)
        state.input_hash, state.artifacts = h, arts
        p.save()
        ctx.progress(1.0, f"{st.label_my} ပြီးပါပြီ ({state.seconds}s)")


def invalidate(project: Project, *names: str) -> None:
    for n in names:
        if n in project.manifest.stages:
            project.manifest.stages[n].status = "pending"
            project.manifest.stages[n].input_hash = None
    project.save()


def request_cancel(project_root: Path) -> None:
    (Path(project_root) / "CANCEL").write_text("1")
