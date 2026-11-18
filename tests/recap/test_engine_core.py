"""Model-free tests: clip-range validation, cache reuse, cancel/resume, SRT timing,
stream checks, Myanmar caption rendering frame."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from recap_engine import api, captions, render, timeline
from recap_engine.burmese import is_zawgyi, normalize, split_phrases, wrap_two_lines, zawgyi_to_unicode
from recap_engine.errors import Cancelled
from recap_engine.manifest import Project
from recap_engine.media import probe
from recap_engine.pipeline import Context, Stage, run_stages
from recap_engine.qc import check_srt, silence_gaps
from recap_engine.script import dialogue_segments, rank_shots, validate_ranges
from recap_engine.settings import ProjectSettings
from recap_engine.transcribe import merge_sources, parse_srt

SHOTS = [{"id": 0, "start": 0.0, "end": 4.0}, {"id": 1, "start": 4.0, "end": 8.0}, {"id": 2, "start": 8.0, "end": 12.0}]
NARR = "ဒီနေ့ ဇာတ်လမ်းက အရမ်း စိတ်ဝင်စားဖို့ကောင်းတယ်။ သူမက သူ့ခင်ပွန်းရဲ့ လျှို့ဝှက်ချက်ကို သိသွားတယ်။"


# ------------------------------------------------------------ clip ranges
def test_validate_ranges_clamps_snaps_and_merges():
    r = validate_ranges([[-3, 2.0], [3.9, 6], [5, 7.7], [11.9, 99], ["x", 1], [5, 5.1], [float("nan"), 2]], 12.0, SHOTS)
    assert r == [[0.0, 2.0], [4.0, 8.0]]  # 11.9 snaps to 12 -> zero length -> dropped
    for a, b in r:
        assert 0 <= a < b <= 12.0


def test_validate_ranges_drops_tiny_and_reversed():
    assert validate_ranges([[6, 4]], 12.0, SHOTS) == [[4.0, 6.0]]
    assert validate_ranges([[3.0, 3.2]], 12.0, SHOTS) == []


def test_rank_and_timeline_fit_audio_exactly_without_repeats():
    beats = [{"id": 0, "source_ranges": [[0, 4]], "characters": [], "tts_seconds": 5.0},
             {"id": 1, "source_ranges": [[4, 8]], "characters": [], "tts_seconds": 3.0}]
    embs = np.eye(3, dtype=np.float32)
    rank_shots(beats, SHOTS, embs, np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32), [])
    assert beats[0]["candidates"][0]["shot"] == 0 and beats[1]["candidates"][0]["shot"] == 1
    tl = timeline.build_recap_timeline(beats, SHOTS, 12.0)
    used = [c["shot"] for seg in tl for c in seg["clips"] if c["shot"] is not None]
    assert len(used) == len(set(used))
    for b, seg in zip(beats, tl):
        foot = sum(c["src_end"] - c["src_start"] for c in seg["clips"])
        assert abs(foot - (b["tts_seconds"] + timeline.GAP)) < 1e-6
    assert tl[1]["out_start"] == pytest.approx(5.0 + timeline.GAP)


def test_pro_segments_slots():
    cues = [{"start": 0.5, "end": 2.0, "text": "你好"}, {"start": 2.1, "end": 2.4, "text": "嗯"},
            {"start": 5.0, "end": 7.0, "text": "再见"}]
    segs = dialogue_segments(cues, 10.0)
    assert segs[0]["max_duration"] <= 5.0 - 0.5 + 1e-6
    assert all(s["max_duration"] > 0 for s in segs)


# ------------------------------------------------------------ transcript merge
def test_merge_priority_subs_over_ocr_over_whisper():
    subs = [{"start": 0, "end": 2, "text": "A"}]
    ocr = [{"start": 0.2, "end": 1.8, "text": "A'", "source": "ocr"}, {"start": 3, "end": 4, "text": "B", "source": "ocr"}]
    wh = [{"start": 3.1, "end": 3.9, "text": "B2", "source": "whisper", "words": []},
          {"start": 6, "end": 7, "text": "C", "source": "whisper"}]
    m = merge_sources(subs, ocr, wh)
    assert [x["text"] for x in m] == ["A", "B", "C"]
    assert [x["source"] for x in m] == ["subs", "ocr", "whisper"]


# ------------------------------------------------------------ burmese
def test_zawgyi_detect_and_convert():
    zg = "ေမာင္"  # Zawgyi 'မောင်' (E-vowel first, 1039 as asat)
    assert is_zawgyi(zg)
    uni = zawgyi_to_unicode(zg)
    assert uni == "မောင်"
    assert not is_zawgyi(uni)
    assert normalize(uni) == uni


def test_phrase_split_two_lines():
    parts = split_phrases(NARR, 22)
    assert len(parts) >= 2
    for x in parts:
        assert wrap_two_lines(x, 22).count(r"\N") <= 1


# ------------------------------------------------------------ captions / SRT
def _beats():
    return [{"id": 0, "spoken_text": NARR, "out_start": 0.0, "out_end": 6.0, "tts_seconds": 6.0},
            {"id": 1, "spoken_text": "နောက်တစ်ပိုင်းမှာ ဆက်ကြည့်ကြရအောင်။", "out_start": 6.25, "out_end": 8.25, "tts_seconds": 2.0}]


def test_srt_monotonic_and_synced(tmp_path):
    beats = _beats()
    cues = captions.build_cues(beats)
    srt = tmp_path / "x.srt"
    srt.write_text(captions.to_srt(cues), "utf-8")
    back = parse_srt(srt.read_text("utf-8"))
    assert len(back) == len(cues)
    res = check_srt(srt, beats)
    assert res["monotonic"] and res["sync_ok"], res
    assert res["max_sync_error_s"] <= 0.15
    ass = captions.to_ass(cues, "9:16", ProjectSettings().caption)
    assert "PlayResY: 1920" in ass and "Dialogue:" in ass
    assert captions.to_vtt(cues).startswith("WEBVTT")


def test_silence_gap_detection(tmp_path):
    sr = 48000
    x = np.zeros((sr * 5, 2), dtype=np.float32)
    x[: sr] = 0.3
    x[int(sr * 2.6): sr * 5] = 0.3  # 1.6 s gap
    f = tmp_path / "n.wav"
    sf.write(f, x, sr)
    gaps = silence_gaps(f)
    assert len(gaps) == 1 and 1.5 <= gaps[0][1] - gaps[0][0] <= 1.7


# ------------------------------------------------------------ pipeline: cache, cancel, resume
def _toy_stages(counter: dict, block: threading.Event | None = None):
    def mk(name):
        def run(ctx):
            counter[name] = counter.get(name, 0) + 1
            if block is not None and name == "b":
                for _ in range(50):
                    ctx.progress(0.5, "working")
                    block.wait(0.02)
            ctx.project.path("render", f"{name}.txt").write_text(name)
            return {"out": f"render/{name}.txt"}
        return Stage(name, name, lambda ctx: {"n": name, "t": ctx.settings.target_seconds}, run)
    return [mk("a"), mk("b"), mk("c")]


def test_cache_reuse_and_invalidation(tmp_path):
    p = Project.create(projects_root=tmp_path)
    cnt: dict = {}
    run_stages(Context(p), _toy_stages(cnt))
    run_stages(Context(p), _toy_stages(cnt))
    assert cnt == {"a": 1, "b": 1, "c": 1}
    assert all(p.manifest.stages[n].cache_hit for n in "abc")
    p.manifest.settings.target_seconds = 60
    p.save()
    run_stages(Context(p), _toy_stages(cnt))
    assert cnt == {"a": 2, "b": 2, "c": 2}
    (p.path("render", "b.txt")).unlink()  # missing artifact -> rerun only b
    run_stages(Context(p), _toy_stages(cnt))
    assert cnt == {"a": 2, "b": 3, "c": 2}


def test_cancel_then_resume(tmp_path):
    p = Project.create(projects_root=tmp_path)
    cnt: dict = {}
    ev = threading.Event()
    ctx = Context(p, cancel_event=ev)
    calls = {"n": 0}

    def cb(e):
        calls["n"] += 1
        if e["stage"] == "b" and e["message"] == "working":
            ev.set()

    ctx.progress_cb = cb
    with pytest.raises(Cancelled):
        run_stages(ctx, _toy_stages(cnt, block=threading.Event()))
    p.reload()
    assert p.manifest.stages["a"].status == "done"
    assert p.manifest.stages["b"].status == "cancelled"
    assert "c" not in p.manifest.stages
    run_stages(Context(p), _toy_stages(cnt))  # resume
    assert cnt["a"] == 1 and cnt["b"] == 2 and cnt["c"] == 1
    p.reload()
    assert all(p.manifest.stages[n].status == "done" for n in "abc")


def test_crash_leaves_running_and_resumes(tmp_path):
    p = Project.create(projects_root=tmp_path)
    p.stage("a").status = "running"  # simulated crash mid-stage
    p.save()
    cnt: dict = {}
    run_stages(Context(p), _toy_stages(cnt))
    assert cnt["a"] == 1


# ------------------------------------------------------------ real ffmpeg: import, streams, render frame
def test_import_probe_and_render_myanmar_frame(tmp_path, fixture_video):
    """Import a local file, then render a short recap from synthetic narration through the
    real render + QC stages and check streams, duration and Myanmar caption shaping frame."""
    s = ProjectSettings(target_seconds=15, hardsub="blur", mirror=True, zoom=1.1, use_ocr=False)
    p = api.create_project(file=fixture_video, settings=s, projects_root=tmp_path)
    ctx = Context(p)
    from recap_engine import importer, qc
    run_stages(ctx, [api.STAGES[0], api.STAGES[1]])  # import + audio
    p.reload()
    meta = p.manifest.source["probe"]
    assert meta["width"] == 1280 and meta["streams"]["audio"] == 1 and abs(meta["duration"] - 12) < 0.2
    # synthetic narration (sine "speech") stands in for TTS in this model-free test
    sr = 24000
    beats = _beats()
    for b in beats:
        n = int(b["tts_seconds"] * sr)
        w = (0.3 * np.sin(np.arange(n) * 2 * np.pi * 180 / sr)).astype(np.float32)
        f = p.path("tts", f"beat_{b['id']:04d}_test.wav")
        sf.write(f, w, sr)
        b.update({"tts_path": f"tts/{f.name}", "narration": b["spoken_text"], "source_ranges": [[0, 12]],
                  "candidates": [], "importance": 3})
    rank_shots(beats, SHOTS, None, None, [])
    p.write_json("analysis/shots.json", SHOTS)
    p.write_json("script/beats.json", beats)
    p.write_json("analysis/ocr.json", {"region": {"x0": 0.3, "y0": 0.82, "x1": 0.7, "y1": 0.95}, "cues": []})
    st = {x.name: x for x in api.STAGES}
    run_stages(Context(p), [st["timeline"], st["captions"], st["render"], st["qc"]])
    out = p.path("export", "final.mp4")
    m = probe(out)
    assert m["streams"] == {"video": 1, "audio": 1, "subtitle": 0}
    assert (m["width"], m["height"]) == (1080, 1920)
    qcr = p.read_json("export/qc_report.json")
    assert qcr["streams_ok"] and qcr["duration_ok"] and qcr["resolution_ok"]
    assert qcr["srt"]["monotonic"] and qcr["srt"]["sync_ok"]
    assert qcr["loudness_ok"], qcr["lufs"]
    frame = p.path("export", "caption_frame.png")
    assert frame.exists() and frame.stat().st_size > 10_000
    # caption pixels exist in the lower part of the frame (white text on non-white background)
    from PIL import Image
    im = np.asarray(Image.open(frame).convert("L"), dtype=np.float32)
    band = im[int(im.shape[0] * 0.6): int(im.shape[0] * 0.85)]
    assert (band > 235).mean() > 0.002
    # edit -> second render reuses clip intermediates
    cnt_before = p.read_json("render/render_info.json")["clips"]
    run_stages(Context(p, force={"render"}), [st["render"]])
    info = p.read_json("render/render_info.json")
    assert info["reused"] == cnt_before
