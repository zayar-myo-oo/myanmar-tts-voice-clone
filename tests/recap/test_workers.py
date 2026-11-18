"""Job workers scale up with the queue (capped) and retire when idle; GPU lock is re-entrant."""
from __future__ import annotations

import threading
import time

from recap_engine import pipeline, server


def test_workers_scale_up_cap_and_retire(monkeypatch):
    jm = server.JobManager(min_workers=1, max_workers=3)
    jm.IDLE_RETIRE_S = 0.3
    gate = threading.Event()
    peak = {"n": 0}
    lock = threading.Lock()
    running = {"n": 0}

    def fake_run(j):
        with lock:
            running["n"] += 1
            peak["n"] = max(peak["n"], running["n"])
        gate.wait(5)
        with lock:
            running["n"] -= 1
        j["state"] = "done"

    monkeypatch.setattr(jm, "_run", fake_run)
    for i in range(5):
        jm.submit(f"p{i}")
    time.sleep(0.5)
    assert len(jm.workers) == 3 and peak["n"] == 3  # 5 jobs -> scaled to the cap, not beyond
    assert len(jm.queue) == 2
    gate.set()
    t0 = time.time()
    while any(j["state"] != "done" for j in jm.jobs.values()) and time.time() - t0 < 5:
        time.sleep(0.05)
    assert all(j["state"] == "done" for j in jm.jobs.values())
    time.sleep(6)  # idle workers retire down to min_workers
    assert len(jm.workers) == 1


def test_gpu_lock_reentrant_and_exclusive(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_GPU_LOCK", str(tmp_path / "gpu.lock"))
    order = []
    with pipeline.gpu_lock(None, "outer"):
        with pipeline.gpu_lock(None, "inner"):  # same thread: no deadlock
            order.append("in")

        def other():
            with pipeline.gpu_lock(None, "other"):
                order.append("other")
        t = threading.Thread(target=other)
        t.start()
        time.sleep(0.3)
        order.append("outer-end")
    t.join(5)
    assert order == ["in", "outer-end", "other"]
