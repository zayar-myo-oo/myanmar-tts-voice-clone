"""Review backend tests (temp project root)."""
import json

import numpy as np
import pytest
import soundfile as sf

from myanmar_voice_studio.training import review
from myanmar_voice_studio.training.dataset import check


@pytest.fixture()
def proj(tmp_path):
    f = tmp_path / "recordings" / "take"
    f.mkdir(parents=True)
    tone = (0.2 * np.sin(np.arange(48000 * 2) / 48000 * 2 * np.pi * 150)).astype(np.float32)
    for n in ("a01", "a02", "a03"):
        sf.write(f / f"{n}.wav", np.r_[np.zeros(24000), tone, np.zeros(24000)], 48000)
    (f / "a01.txt").write_text("မင်္ဂလာပါ\n", encoding="utf-8")
    (f / "a02.draft.txt").write_text("ဒီနေ့ နေကောင်းလား\n", encoding="utf-8")
    (f / "asr_matches.json").write_text(json.dumps({"a02.wav": {"heard": "ဒီနေ့နေကောင်းလား", "match": "r001",
                                                                "ser": 0.1, "expected": "ဒီနေ့ နေကောင်းလား။"}}),
                                        encoding="utf-8")
    return tmp_path


def test_summary_statuses(proj):
    s = review.summary(proj)
    by = {i.file: i for i in s.items}
    assert s.folder == "take" and s.folders == ["take"]
    assert by["a01.wav"].status == "approved" and by["a02.wav"].status == "draft"
    assert by["a02.wav"].script_id == "r001" and by["a03.wav"].status == "missing"
    assert s.approved == 1 and s.draft == 2 and s.approved_minutes > 0


def test_approve_reject_roundtrip_and_dataset_skips_rejected(proj):
    item = review.approve(proj, "take", "a02.wav", "  ဒီနေ့   နေကောင်းလား။ ")
    assert item.status == "approved" and item.text == "ဒီနေ့ နေကောင်းလား။"
    assert review.reject(proj, "take", "a03.wav").status == "rejected"
    rep = check(proj / "recordings" / "take", None)
    assert {c.file for c in rep.clips} == {"a01.wav", "a02.wav"}  # a03 excluded
    assert review.reject(proj, "take", "a03.wav", rejected=False).status == "missing"
    assert (proj / "recordings" / "take" / "a03.wav").exists()  # audio never deleted


@pytest.mark.parametrize("folder,file", [("..", "a01.wav"), ("take", "../x.wav"), ("take", "a01.txt"), ("nope", "a01.wav")])
def test_paths_are_confined(proj, folder, file):
    with pytest.raises(ValueError):
        review.audio_path(proj, folder, file)


@pytest.mark.parametrize("text", ["", "hello", "မနက် ၉ နာရီ", "9 နာရီ"])
def test_approve_validates_text(proj, text):
    with pytest.raises(ValueError):
        review.approve(proj, "take", "a03.wav", text)
