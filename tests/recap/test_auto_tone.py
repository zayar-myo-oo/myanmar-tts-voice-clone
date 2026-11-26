"""Recap: captions placed automatically on the detected subtitle band; narration tone (normal / rude / funny)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from recap_engine import captions, dubbing, script
from recap_engine.settings import ProjectSettings, TransformSettings


def _project(tmp_path, region, w=1280, h=720):
    (tmp_path / "analysis").mkdir(exist_ok=True)
    (tmp_path / "analysis" / "ocr.json").write_text(json.dumps({"region": region}), "utf-8")
    return SimpleNamespace(root=tmp_path, path=lambda *a: tmp_path.joinpath(*a),
                           read_json=lambda name, d=None: json.loads((tmp_path / name).read_text("utf-8")) if (tmp_path / name).exists() else d,
                           manifest=SimpleNamespace(source={"probe": {"width": w, "height": h}}))


def _settings(**kw):
    s = ProjectSettings(**kw)
    s.caption = s.caption.model_copy(update={"position": "auto"})
    return s


def test_source_height_maps_into_the_output_frame():
    orig = ProjectSettings(transform=TransformSettings(enabled=True, aspect_original=True))
    assert captions.src_to_out_y(orig, 1280, 720, 0.9) == pytest.approx(0.9)
    fill = ProjectSettings(aspect="9:16", reframe="blur_fill")           # 16:9 picture letterboxed in the middle of 9:16
    assert captions.src_to_out_y(fill, 1920, 1080, 0.5) == pytest.approx(0.5)
    assert captions.src_to_out_y(fill, 1920, 1080, 1.0) == pytest.approx(0.5 + 607.5 / 2 / 1920, abs=1e-3)
    crop = ProjectSettings(aspect="9:16", reframe="center_crop")         # height fills the frame: unchanged
    assert captions.src_to_out_y(crop, 1920, 1080, 0.85) == pytest.approx(0.85)
    zoom = ProjectSettings(transform=TransformSettings(enabled=True, aspect_original=True), zoom=1.25)
    assert captions.src_to_out_y(zoom, 1280, 720, 0.5) == pytest.approx(0.5) and captions.src_to_out_y(zoom, 1280, 720, 0.9) == pytest.approx(1.0)


def test_auto_puts_captions_on_the_band_and_widens_the_blur(tmp_path):
    region = {"x0": 0.2, "y0": 0.80, "x1": 0.8, "y1": 0.93, "samples": 50}
    s = _settings(transform=TransformSettings(enabled=True, aspect_original=True))
    proj = _project(tmp_path, region)
    out = captions.resolve_auto(proj, s)
    assert out.caption.position == "custom" and 0.80 < out.caption.pos_pct < 0.93
    (box,) = out.blur_boxes
    assert box["auto"] and box["y0"] < 0.80 and box["y1"] > 0.93 and box["x0"] < 0.2 and box["x1"] > 0.8
    assert s.caption.position == "auto" and s.blur_boxes == []            # the saved settings are not touched
    assert captions.resolve_auto(proj, s) is out   # cached while ocr.json is unchanged


def test_auto_without_a_band_falls_back_to_bottom(tmp_path):
    out = captions.resolve_auto(_project(tmp_path, None), _settings())
    assert out.caption.position == "bottom" and out.blur_boxes == []


def test_auto_keeps_user_boxes_and_respects_keep(tmp_path):
    region = {"x0": 0.2, "y0": 0.80, "x1": 0.8, "y1": 0.93}
    mine = {"x0": 0, "y0": 0, "x1": 0.3, "y1": 0.1, "strength": 20}
    s = _settings(hardsub="keep", blur_boxes=[mine])
    out = captions.resolve_auto(_project(tmp_path, region), s)
    assert out.blur_boxes == [mine] and out.caption.position == "custom"  # "keep" = show the original subtitles


def test_tone_rules():
    assert script.tone_rule("normal") == "" and script.tone_rule("") == ""
    rude, funny = script.tone_rule("rude"), script.tone_rule("funny")
    assert "ခွေးကောင်" in rude and "EVENTS stay exactly the same" in rude and "never a new plot event" in rude
    assert "No swearing" in funny and "never a new plot event" in funny
    assert ProjectSettings(tone="rude").tone == "rude"
    with pytest.raises(ValueError):
        ProjectSettings(tone="angry")


def test_changing_the_tone_of_a_dub_translates_again(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_PROJECTS_DIR", str(tmp_path))
    job = dubbing.Job("0123456789ab")
    job.meta.update(source="source.mp4", title="t")
    job.save()
    job.write("lines.json", {"lines": [{"id": 0, "start": 0, "end": 1, "en": "Hi.", "my": "ဟိုင်း", "kw": ""}], "hook": ""})
    assert dubbing.update_lines(job, [], opts={"remove": "blur"}) == "voice"
    assert dubbing.update_lines(job, [], opts={"tone": "funny"}) == "translate"
    assert not (job.dir / "lines.json").exists() and (job.dir / "lines.normal.json.bak").exists()


def test_original_aspect_only_counts_when_the_transform_path_is_on():
    off = ProjectSettings(aspect="9:16", reframe="blur_fill", transform=TransformSettings(enabled=False, aspect_original=True))
    assert captions.src_to_out_y(off, 1280, 720, 0.95) == pytest.approx((0.95 * 607.5 + 656.25) / 1920, abs=1e-3)
