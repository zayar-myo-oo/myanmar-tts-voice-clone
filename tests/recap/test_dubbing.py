"""Dubbing: the parts that need no GPU, no models and no network (sentence building, timing fit, caption chunks,
ASS output, text removal on a synthetic frame, job bookkeeping)."""
from __future__ import annotations

import numpy as np
import pytest

from recap_engine import dubbing


def _words(spec):
    return [{"word": w, "start": a, "end": b} for w, a, b in spec]


def test_sentences_break_at_punctuation_and_pauses():
    w = _words([("One", 0.0, 0.3), ("night,", 0.3, 0.7), ("you", 0.7, 0.9), ("think.", 0.9, 1.6),
                ("Scorpios", 1.7, 2.3), ("reload", 2.3, 2.7), ("slowly", 2.7, 3.4),      # pause, no punctuation
                ("So", 4.6, 4.8), ("use", 4.8, 5.1), ("a", 5.1, 5.2), ("catapult.", 5.2, 6.0)])
    s = dubbing.build_sentences(w)
    assert [x["en"] for x in s] == ["One night, you think.", "Scorpios reload slowly", "So use a catapult."]
    assert s[0]["start"] == 0.0 and s[2]["start"] == 4.6 and [x["id"] for x in s] == [0, 1, 2]


def test_a_one_word_sentence_joins_its_neighbour():
    w = _words([("Wrong.", 0.0, 0.4), ("They", 0.5, 0.7), ("were", 0.7, 0.9), ("deadly.", 0.9, 1.8)])
    assert [x["en"] for x in dubbing.build_sentences(w)] == ["Wrong. They were deadly."]


def test_caption_chunks_follow_the_translators_spaces():
    c = dubbing.chunk_caption("ရှေးခေတ်က ကျောက်တုံးပစ်စက်တွေ တကယ်ပဲ အသုံးမဝင်ခဲ့တာလား။", 14)
    assert c[0] == "ရှေးခေတ်က" or c[0].startswith("ရှေးခေတ်က")
    assert all("။" not in x for x in c) and "".join(c).replace(" ", "") == "ရှေးခေတ်ကကျောက်တုံးပစ်စက်တွေတကယ်ပဲအသုံးမဝင်ခဲ့တာလား"


def test_keywords_stay_short():
    assert dubbing._keywords("လမ်းမှာရှိတဲ့သူ အကုန်လုံးကို ရိုက်ချေပစ်လိုက်တယ်") != ["လမ်းမှာရှိတဲ့သူ အကုန်လုံးကို ရိုက်ချေပစ်လိုက်တယ်"]
    assert dubbing._keywords("သုံးရာ") == ["သုံးရာ"] and dubbing._keywords("") == []


def _lines(spec):
    return [{"id": i, "start": a, "end": b, "my": "က " * 3, "tts": f"tts/{i}.wav", "tts_seconds": d} for i, (a, b, d) in enumerate(spec)]


def test_timing_keeps_speed_when_the_line_fits():
    p = dubbing.plan_timing(_lines([(0.0, 2.0, 1.5), (2.2, 4.0, 1.2)]), 4.5)
    assert all(s["factor"] == 1.0 for s in p["segments"]) and all(v["tempo"] == 1.0 for v in p["voice"])
    assert p["voice"][1]["at"] == pytest.approx(2.2) and p["duration"] == pytest.approx(4.5)


def test_timing_speeds_the_voice_first_then_slows_the_picture():
    p = dubbing.plan_timing(_lines([(0.0, 2.0, 2.3), (2.0, 4.0, 3.4)]), 4.0)
    v0, v1 = p["voice"]
    s0, s1 = p["segments"]
    assert 1.0 < v0["tempo"] <= dubbing.MAX_TEMPO and s0["factor"] == 1.0          # a little long: only the voice changes
    assert v1["tempo"] == dubbing.MAX_TEMPO and 1.0 < s1["factor"] <= dubbing.MAX_STRETCH  # much longer: picture slows too
    assert p["duration"] > 4.0
    assert v1["at"] >= v0["at"] + v0["seconds"]                                     # lines never overlap


def test_timing_with_intro_puts_the_hook_first():
    p = dubbing.plan_timing(_lines([(0.5, 2.0, 1.0)]), 3.0, {"a": 1.0, "b": 3.0, "tts": "tts/hook.wav", "seconds": 2.0})
    assert p["segments"][0]["intro"] and p["voice"][0]["id"] == "hook"
    assert p["voice"][1]["at"] >= 2.0


def test_ass_has_burmese_pop_events_and_highlight():
    lines = [{"id": 0, "start": 0.0, "end": 2.0, "my": "ရှေးခေတ်က ကျောက်တုံးပစ်စက်တွေ အသုံးမဝင်ဘူးလား", "kw": "ကျောက်တုံးပစ်စက်တွေ",
              "tts": "tts/0.wav", "tts_seconds": 1.8}]
    plan = dubbing.plan_timing(lines, 2.5)
    ass, cues = dubbing.build_ass(lines, plan, {"w": 1080, "h": 1920, "text_h": 90, "cx": 540, "cy": 1380}, {"highlight": True, "max_chars": 14})
    assert "Noto Sans Myanmar" in ass and r"\pos(540,1380)" in ass and r"\t(0,70" in ass
    assert any(c["hot"] for c in cues) and not all(c["hot"] for c in cues)
    assert cues[0]["start"] == pytest.approx(0.0, abs=0.01) and cues[-1]["end"] <= 2.2
    _, plain = dubbing.build_ass(lines, plan, {"w": 1080, "h": 1920}, {"highlight": False})
    assert not any(c["hot"] for c in plain)


def _frame_with_text():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(1)
    f = np.full((400, 800, 3), (40, 140, 60), np.uint8) + rng.integers(0, 12, (400, 800, 3), dtype=np.uint8)
    clean = f.copy()
    cv2.putText(f, "CATAPULT", (150, 230), cv2.FONT_HERSHEY_DUPLEX, 3.0, (0, 0, 0), 14)
    cv2.putText(f, "CATAPULT", (150, 230), cv2.FONT_HERSHEY_DUPLEX, 3.0, (255, 255, 255), 5)
    return f, clean, [[150, 160, 650, 240]]


@pytest.mark.parametrize("mode", ["inpaint", "auto", "blur"])
def test_text_removal_covers_the_letters_and_leaves_the_rest(mode):
    f, clean, boxes = _frame_with_text()
    out = dubbing.remove_text(f.copy(), boxes, 80, mode)
    roi = (slice(150, 250), slice(140, 660))
    assert (out[roi].max(axis=2) > 200).mean() < 0.01                 # no white letters left
    assert np.array_equal(out[:60], f[:60])                           # far from the box: untouched
    if mode != "blur":                                                # inpaint gives back the plain background
        assert np.abs(out[roi].astype(int) - clean[roi].astype(int)).mean() < 12


def test_auto_mode_blurs_on_a_white_background():
    cv2 = pytest.importorskip("cv2")
    f = np.full((300, 600, 3), 245, np.uint8)
    cv2.putText(f, "SNOW", (150, 180), cv2.FONT_HERSHEY_DUPLEX, 3.0, (0, 0, 0), 12)
    cv2.putText(f, "SNOW", (150, 180), cv2.FONT_HERSHEY_DUPLEX, 3.0, (255, 255, 255), 4)
    out = dubbing.remove_text(f.copy(), [[150, 110, 450, 190]], 80, "auto")
    assert (out[120:180, 170:430].min(axis=2) < 60).mean() < 0.02     # the black outline is smeared away


def test_boxes_follow_the_nearest_tracked_frames():
    cap = {"step": 2, "boxes": {"10": [[1, 1, 5, 5]], "12": [[2, 2, 6, 6]], "40": [[9, 9, 12, 12]]}}
    assert dubbing.boxes_at(cap, 11) == [[1, 1, 5, 5], [2, 2, 6, 6]]
    assert dubbing.boxes_at(cap, 14) == [[2, 2, 6, 6]] and dubbing.boxes_at(cap, 20) == []


def test_job_files_and_line_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_PROJECTS_DIR", str(tmp_path))
    job = dubbing.Job("abc123def456")
    job.meta.update(source="source.mp4", title="t")
    job.save()
    job.write("lines.json", {"lines": [{"id": 0, "start": 0, "end": 1, "en": "Hi.", "my": "ဟိုင်း", "kw": ""}], "hook": "", "hook_line": 0})
    dubbing.JOBS.pop(job.id, None)
    j = dubbing.get(job.id)
    assert dubbing.update_lines(j, [{"id": 0, "my": "မင်္ဂလာပါ   ဗျာ", "kw": "ဗျာ"}], hook="ကြည့်ပါ", opts={"remove": "blur", "bogus": 1}) == "voice"
    d = j.read("lines.json")
    assert d["lines"][0]["my"] == "မင်္ဂလာပါ ဗျာ" and d["hook"] == "ကြည့်ပါ"
    assert j.opts["remove"] == "blur" and "bogus" not in j.opts
    pub = dubbing.public(j, full=True)
    assert pub["lines"][0]["kw"] == "ဗျာ" and pub["final"] is False
    with pytest.raises(dubbing.RecapError):
        dubbing.get("../../etc")
    dubbing.JOBS.pop(job.id, None)


def test_glossary_is_saved_cleaned_and_matched_on_whole_words(tmp_path, monkeypatch):
    monkeypatch.setattr(dubbing, "GLOSSARY_FILE", tmp_path / "g.json")
    assert dubbing.load_glossary() == {}
    g = dubbing.save_glossary({" catapult ": "ကျောက်တုံးပစ်စက်", "Scorpio": "မြားပစ်စက်", "": "x", "empty": " ", "cat": "ကြောင်"})
    assert g == {"catapult": "ကျောက်တုံးပစ်စက်", "Scorpio": "မြားပစ်စက်", "cat": "ကြောင်"}
    used = dubbing.glossary_for("Why are we using scorpios instead of Catapults?", g)
    assert used == {"catapult": "ကျောက်တုံးပစ်စက်", "Scorpio": "မြားပစ်စက်"}   # "cat" inside "catapults" is not a match
    assert dubbing.glossary_for("Nothing here.", g) == {}


def test_hook_choices_start_with_the_translated_line_and_drop_repeats():
    assert dubbing.pick_hooks(["  ခ  ခ ", "က", "", "ဂ", "ဃ", "င"], "က") == ["က", "ခ ခ", "ဂ", "ဃ"]
    assert dubbing.pick_hooks(None, "က") == ["က"] and dubbing.pick_hooks("bad", "") == []


def test_keyword_only_translations_are_detected():
    sents = [{"id": 0, "en": "One night you start thinking, why are we using scorpios?"},
             {"id": 1, "en": "So during the next battle, you use a catapult."}, {"id": 2, "en": "Wrong."}]
    bad = [{"id": 0, "my": "မြားပစ်စက်"}, {"id": 1, "my": "ကျောက်တုံးပစ်စက်"}, {"id": 2, "my": "မှားတယ်"}]
    good = [{"id": 0, "my": "တစ်ညမှာ မင်းစဉ်းစားမိတယ် မြားပစ်စက်ကို ဘာလို့ သုံးနေတာလဲ"},
            {"id": 1, "my": "ဒါနဲ့ နောက်တိုက်ပွဲမှာ ကျောက်တုံးပစ်စက်ကို သုံးလိုက်တယ်"}, {"id": 2, "my": "မှားတယ်"}]
    assert dubbing.looks_collapsed(sents, bad) and not dubbing.looks_collapsed(sents, good)
    assert dubbing.looks_collapsed(sents, []) and not dubbing.looks_collapsed([sents[2]], [])


def test_review_gate_pauses_after_translate_and_resumes_from_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("RECAP_PROJECTS_DIR", str(tmp_path))
    ran: list[str] = []
    monkeypatch.setattr(dubbing, "STAGES", [(n, (lambda job, prog, n=n: ran.append(n)), 1.0)
                                            for n in ("audio", "transcribe", "captions", "translate", "voice", "render")])
    job = dubbing.Job("feedfacecafe")
    job.meta.update(source="source.mp4", title="t")
    dubbing.run(job)
    assert ran == ["audio", "transcribe", "captions", "translate"] and job.meta["state"] == "review"
    dubbing.run(job, "voice")                                   # what the page does after the creator checked the lines
    assert ran[-2:] == ["voice", "render"] and job.meta["state"] == "done"
    ran.clear()
    job.meta["opts"] = {**job.opts, "review": False}
    dubbing.run(job)
    assert ran[-1] == "render" and len(ran) == 6 and job.meta["state"] == "done"
