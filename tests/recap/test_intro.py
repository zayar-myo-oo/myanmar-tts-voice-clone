from types import SimpleNamespace

from recap_engine.script import recap_seconds
from recap_engine.settings import ProjectSettings
from recap_engine.timeline import MONTAGE_CLIP, build_recap_timeline


def test_intro_takes_its_time_from_the_recap_budget():
    ctx = SimpleNamespace(settings=ProjectSettings(target_seconds=180, hook_intro=True, intro_seconds=12))
    assert recap_seconds(ctx) == 168
    ctx = SimpleNamespace(settings=ProjectSettings(target_seconds=180))
    assert recap_seconds(ctx) == 180


def test_intro_montage_is_short_cuts_across_the_video_and_does_not_steal_shots():
    shots = [{"id": i, "start": i * 10.0, "end": i * 10.0 + 10} for i in range(12)]
    intro = {"id": 0, "kind": "intro", "tts_seconds": 11.0, "source_ranges": [[12, 15], [55, 58], [101, 104]], "candidates": []}
    beat1 = {"id": 1, "tts_seconds": 8.0, "source_ranges": [[50, 60]], "candidates": [{"shot": 5, "score": 1.0}]}
    tl = build_recap_timeline([intro, beat1], shots, 120.0)
    clips = intro["clips"]
    assert all(c["src_end"] - c["src_start"] <= MONTAGE_CLIP + 0.3 for c in clips)  # +sliver stretch on the last cut
    covered = sum(c["src_end"] - c["src_start"] for c in clips)
    assert abs(covered - (11.0 + 0.25)) < 0.01         # the intro voice (+ gap) is fully covered
    assert {round(c["src_start"]) // 40 for c in clips} >= {0, 1, 2}  # beginning, middle and end
    assert beat1["clips"][0]["shot"] == 5                # the recap still gets shot 5 even though the intro used it
    assert tl
