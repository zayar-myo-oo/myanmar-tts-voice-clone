"""Advanced Video Transformation + Rights Analysis tests (model-free, real ffmpeg)."""
from __future__ import annotations

import numpy as np
import soundfile as sf

from recap_engine import api, render, rights, transform as tf
from recap_engine.manifest import Project
from recap_engine.media import probe
from recap_engine.pipeline import Context, run_stages
from recap_engine.script import rank_shots
from recap_engine.settings import ColorSettings, ProjectSettings, TransformSettings
from test_engine_core import SHOTS, _beats


def test_disabled_keeps_render_hash_unchanged(tmp_path):
    p = Project.create(projects_root=tmp_path)
    a = render.render_inputs(Context(p))
    p.manifest.settings.transform = TransformSettings(enabled=False, preset="cinematic_drama", smart_reframe=True)
    assert render.render_inputs(Context(p)) == a  # OFF -> identical cache key -> identical output
    p.manifest.settings.transform = TransformSettings(enabled=True)
    assert render.render_inputs(Context(p)) != a


def test_presets_and_color_are_subtle():
    t = tf.effective(TransformSettings(enabled=True, preset="vertical_recap"))
    assert t.smart_reframe and t.subtitle_background == "frosted"
    chain = ",".join(tf.color_chain(ColorSettings(preset="dark_thriller")))
    assert "eq=" in chain and "colortemperature=temperature=7200" in chain
    for name in tf.COLOR_PRESETS:  # no preset pushes contrast/saturation beyond +-15%
        c = tf.COLOR_PRESETS[name]
        assert 0.85 <= c.get("contrast", 1) <= 1.15 and 0.85 <= c.get("saturation", 1) <= 1.15


def test_crop_track_keeps_faces_and_moves_smoothly():
    # one face drifting right; a scene cut at t=5 jumps to a face on the left
    samples = [{"t": t / 2, "faces": [[0.5 + t * 0.02, 0.3, 0.6 + t * 0.02, 0.5]]} for t in range(10)]
    samples += [{"t": 5 + t / 2, "faces": [[0.05, 0.3, 0.15, 0.5]]} for t in range(6)]
    tr = tf.crop_track(samples, [5.0], 0.32)
    xs = [c for _, c in tr]
    steps = [abs(xs[i + 1] - xs[i]) for i in range(9)]
    assert max(steps) <= 0.12 * 0.32 * 0.5 + 1e-6  # speed-limited before the cut
    assert abs(xs[10] - 0.16) < 1e-6  # after the cut: re-centred at once, clamped inside frame
    for t, c in tr:  # crop window always inside the frame
        assert 0.16 - 1e-6 <= c <= 0.84 + 1e-6


def test_rights_never_claims_clear_and_flags_unknown():
    assert rights.footage_usage([{"clips": [{"src_start": 0, "src_end": 4, "out_start": 0, "out_end": 4},
                                            {"src_start": 2, "src_end": 6, "out_start": 4, "out_end": 8}]}],
                                12)["source_seconds_used"] == 6
    assert "copyright-free" not in rights.DISCLAIMER_MY.lower()
    assert set(rights.STATUS_MY) == {"user_owned", "licensed", "permission_unknown", "requires_review"}


def test_transform_render_end_to_end(tmp_path, fixture_video):
    logo = tmp_path / "logo.png"
    from PIL import Image
    Image.new("RGBA", (200, 80), (255, 0, 0, 255)).save(logo)
    s = ProjectSettings(target_seconds=15, use_ocr=False, transform=TransformSettings(
        enabled=True, preset="custom", smart_reframe=True, color=True, stabilize=True, audio_enhance=True,
        subtitle_background="frosted", watermark=True, scene_chapters=True, resolution="720", codec="h264",
        wm={"text": "ကျွန်တော့် Channel", "logo_path": str(logo), "position": "top_left"}))
    p = api.create_project(file=fixture_video, settings=s, projects_root=tmp_path)
    run_stages(Context(p), [api.STAGES[0], api.STAGES[1]])
    p.reload()
    sr = 24000
    beats = _beats()
    for b in beats:
        n = int(b["tts_seconds"] * sr)
        f = p.path("tts", f"beat_{b['id']:04d}_t.wav")
        sf.write(f, (0.3 * np.sin(np.arange(n) * 2 * np.pi * 180 / sr)).astype(np.float32), sr)
        b.update({"tts_path": f"tts/{f.name}", "narration": b["spoken_text"], "source_ranges": [[0, 12]],
                  "candidates": [], "importance": 3})
    rank_shots(beats, SHOTS, None, None, [])
    p.write_json("analysis/shots.json", SHOTS)
    p.write_json("script/beats.json", beats)
    p.write_json("analysis/ocr.json", {"region": {"x0": 0.3, "y0": 0.82, "x1": 0.7, "y1": 0.95}, "cues": []})
    st = {x.name: x for x in api.STAGES}
    run_stages(Context(p), [st["timeline"], st["captions"], st["render"], st["qc"], st["rights"]])
    m = probe(p.path("export", "final.mp4"))
    assert (m["width"], m["height"]) == (720, 1280)
    qcr = p.read_json("export/qc_report.json")
    assert qcr["transform"]["av_sync_ok"] and qcr["srt"]["sync_ok"] and qcr["duration_ok"], qcr
    assert p.path("export", "chapters.txt").exists() and p.path("export", "compare.png").exists()
    rr = p.read_json("export/rights_report.json")
    assert rr["status"] == "permission_unknown" and rr["flags_my"]
    # visual-only change: only the render re-runs; clip cache keyed by filter
    p.manifest.settings.transform.col.preset = "warm_romance"
    p.save()
    run_stages(Context(p), [st["timeline"], st["captions"], st["render"]])
    assert p.stage("timeline").cache_hit and p.stage("captions").cache_hit and not p.stage("render").cache_hit


def test_compact_timeline_cuts_silence_keeps_sync():
    from recap_engine.timeline import build_compact_timeline
    b = [{"source_start": 1, "source_end": 2, "tts_seconds": 1.2}, {"source_start": 2.3, "source_end": 3, "tts_seconds": 0.7},
         {"source_start": 10, "source_end": 11, "tts_seconds": 1}]
    tl = build_compact_timeline(b, 20, max_gap=0.6)
    clips = tl[0]["clips"]
    assert len(clips) == 2 and tl[0]["out_end"] < 5  # 7 s of silence removed
    for x in b:  # each line starts where its own footage lands in the output
        c = next(c for c in clips if c["src_start"] <= x["source_start"] <= c["src_end"])
        assert abs(x["out_start"] - (c["out_start"] + x["source_start"] - c["src_start"])) < 1e-6
