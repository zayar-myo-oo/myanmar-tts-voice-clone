"""Dataset QC tests with synthetic recordings."""
from __future__ import annotations

import json

import numpy as np
import soundfile as sf

from myanmar_voice_studio.training.dataset import check

SR = 48000


def speech(seconds=3.0, level=0.3, noise=1e-4, lead=0.5, trail=0.5, seed=0):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    body = level * np.sin(2 * np.pi * 140 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
    pad = lambda s: np.zeros(int(SR * s))  # noqa: E731
    x = np.concatenate([pad(lead), body, pad(trail)])
    return (x + rng.normal(0, noise, x.size)).astype(np.float32)


def test_good_bad_and_manifests(tmp_path):
    rec = tmp_path / "rec"
    rec.mkdir()
    script = tmp_path / "script.md"
    script.write_text("| ID | t |\n|---|---|\n| r001 | မင်္ဂလာပါ။ |\n| r002 | ဒုတိယ |\n| r003 | တတိယ |\n"
                      "| r004 | စတုတ္ထ |\n| r005 | ပဉ္စမ |\n", encoding="utf-8")
    sf.write(rec / "r001.wav", speech(), SR, subtype="PCM_24")
    clipped = speech(level=1.5)
    sf.write(rec / "r002.wav", np.clip(clipped, -1, 1), SR, subtype="PCM_16")
    sf.write(rec / "r003.wav", speech(noise=0.02, seed=1), SR, subtype="PCM_16")
    sf.write(rec / "r004.wav", speech(), 16000, subtype="PCM_16")
    (rec / "r005.ogg").write_bytes(b"fake")
    sf.write(rec / "story01.wav", speech(seconds=6, seed=2), SR)
    (rec / "story01.txt").write_text("စာရှည် တစ်ပိုဒ်", encoding="utf-8")
    sf.write(rec / "x999.wav", speech(), SR)  # no transcript

    rep = check(rec, script, tmp_path / "out")
    by = {c.id: c for c in rep.clips}
    assert by["r001"].ok and by["r001"].text == "မင်္ဂလာပါ။" and by["r001"].snr_db > 30
    assert any("clipping" in p for p in by["r002"].problems)
    assert any("noisy" in p for p in by["r003"].problems)
    assert any("sample rate" in p for p in by["r004"].problems)
    assert any("lossy" in p for p in by["r005"].problems)
    assert by["story01"].ok and by["story01"].text == "စာရှည် တစ်ပိုဒ်"
    assert any("no transcript" in p for p in by["x999"].problems)
    assert rep.accepted == 2 and rep.missing_ids == []
    assert any("metadata.json" in a for a in rep.advice) and any("30 min" in a for a in rep.advice)
    lines = (tmp_path / "out" / "train.jsonl").read_text(encoding="utf-8").splitlines()
    assert {json.loads(x)["text"] for x in lines} == {"မင်္ဂလာပါ။", "စာရှည် တစ်ပိုဒ်"}
    assert json.loads((tmp_path / "out" / "qc_report.json").read_text(encoding="utf-8"))["accepted"] == 2


def test_edge_silence_warning_and_metadata(tmp_path):
    rec = tmp_path / "rec"
    rec.mkdir()
    (rec / "metadata.json").write_text(json.dumps({"speaker_id": "z", "consent": "yes"}), encoding="utf-8")
    sf.write(rec / "r001.wav", speech(lead=0.0, trail=0.0), SR)
    rep = check(rec, None)
    clip = rep.clips[0]
    assert any("start/end" in w for w in clip.warnings)
    assert not any("metadata" in a for a in rep.advice)
