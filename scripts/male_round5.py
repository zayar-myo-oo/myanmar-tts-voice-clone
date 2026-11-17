"""Round 5 (FIX3 base): levers other than filters — model style vector, pacing, pauses.

    .venv-nara\\Scripts\\python.exe scripts\\male_round5.py outputs/diag-male/round5
"""
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from voice_metrics import SR, loudness_match, measure  # noqa: E402

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
P = json.loads((ROOT / "config/voice_presets.json").read_text(encoding="utf-8"))["presets"]["male_calm"]
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())
ff = dsp.ffmpeg_path()
sess = adapter._session(P["voice"])
orig_styles = [list(s) for s in sess["meta"]["styles"]]


def finish(raw, tempo=1.0):
    r = 2 ** (P["pitch_semitones"] / 12)
    x = dsp._run_ffmpeg(ff, raw, SR, [f"rubberband=pitch={r:.5f}:tempo={tempo:.4f}:formant=preserved:pitchq=quality"])
    return dsp._run_ffmpeg(ff, dsp.vocos_resynth(x, SR), SR, [P["post_filter"]])


def synth(style_offset=0, gap=P["sentence_gap_s"], styles=None):
    sess["meta"]["styles"] = styles or orig_styles
    v = VoiceProfile(voice_id="m", display_name="m", adapter_id="nara-mini-v1", speaker=P["voice"],
                     style_offset=style_offset, sentence_gap_s=gap)
    try:
        return adapter.synthesize(text, v, gap)
    finally:
        sess["meta"]["styles"] = orig_styles


mean_style = [list(np.mean(np.asarray(orig_styles), axis=0))] * len(orig_styles)
long_style = [orig_styles[-1]] * len(orig_styles)  # style learned on the longest utterances
signals = {
    "R0_FIX3_current": finish(synth()),
    "R1_style_minus1": finish(synth(style_offset=-1)),
    "R2_style_plus1": finish(synth(style_offset=1)),
    "R3_style_average": finish(synth(styles=mean_style)),
    "R4_style_longform": finish(synth(styles=long_style)),
    "R5_slower_0.95": finish(synth(), tempo=0.95),
    "R6_longer_pauses_0.45s": finish(synth(gap=0.45)),
}
matched, level = loudness_match(signals)
rows = []
with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for i, (name, y) in enumerate(matched.items()):
        p = out / f"{name}.wav"
        sf.write(p, y, SR, subtype="PCM_16")
        z.write(p, p.name)
        rows.append({"file": p.name, "dur_s": round(y.size / SR, 2), **measure(y)})
(out / "measurements.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
keys = ["file", "dur_s", "f0_hz", "f0_sd_st", "periodicity", "centroid_hz", "bass_100_300"]
print(f"active RMS {level:.1f} dBFS"); print(" | ".join(keys))
for r in rows:
    print(" | ".join(str(r[k]) for k in keys))
