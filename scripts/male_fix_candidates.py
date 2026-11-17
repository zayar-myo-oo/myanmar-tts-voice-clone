"""Minimal-change fix candidates for the male voice, compared with the required references
(original model output, processed without pitch change, current +2 st). Loudness-matched,
no clipping.

    .venv-nara\\Scripts\\python.exe scripts\\male_fix_candidates.py outputs/diag-male/compare
"""
import json
import sys
import zipfile
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tone_scan import scan  # noqa: E402
from voice_metrics import SR, loudness_match, measure  # noqa: E402

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
preset = json.loads((ROOT / "config/voice_presets.json").read_text(encoding="utf-8"))["presets"]["male_calm"]
CHAIN = preset["post_filter"]
parts = CHAIN.split(",")
NOTCH = ",".join(p for p in parts if p.startswith("bandreject"))
BASE = ",".join(p for p in parts if p.split("=")[0] in ("highpass", "deesser", "lowpass"))
MILD_EQ = "equalizer=f=200:t=q:w=0.9:g=-2.5,equalizer=f=3000:t=q:w=1:g=1"

eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())
v = VoiceProfile(voice_id="h", display_name="h", adapter_id="nara-mini-v1", speaker=preset["voice"],
                 sentence_gap_s=preset["sentence_gap_s"])
raw = adapter.synthesize(text, v, v.sentence_gap_s)
ff = dsp.ffmpeg_path()
filt = lambda x, c: dsp._run_ffmpeg(ff, x, SR, [c]) if c else x  # noqa: E731
voc = lambda x: dsp.vocos_resynth(x, SR)  # noqa: E731


def shift(x, semis, formant):
    r = 2 ** (semis / 12)
    return dsp._run_ffmpeg(ff, x, SR, [f"rubberband=pitch={r:.5f}:formant={formant}:pitchq=quality"])


signals = {
    "REF1_original_model": raw,
    "REF2_processed_no_pitch_change": filt(voc(raw), CHAIN),
    "REF3_current_plus2st": filt(voc(shift(raw, 2, "shifted")), CHAIN),
    "FIX1_no_pitch_vocos_notch_clean": filt(voc(raw), f"{NOTCH},{BASE}"),
    "FIX2_no_pitch_vocos_notch_mildEQ": filt(voc(raw), f"{NOTCH},{MILD_EQ},{BASE}"),
    "FIX3_plus1st_preserved_mildEQ": filt(voc(shift(raw, 1, "preserved")), f"{NOTCH},{MILD_EQ},{BASE}"),
    "FIX4_plus1st_shifted_mildEQ": filt(voc(shift(raw, 1, "shifted")), f"{NOTCH},{MILD_EQ},{BASE}"),
}
matched, level = loudness_match(signals)
rows = []
with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for i, (name, y) in enumerate(matched.items()):
        p = out / f"{i}_{name}.wav"
        sf.write(p, y, SR, subtype="PCM_16")
        z.write(p, p.name)
        m = measure(y)
        m["whine_db"] = round(float(max(d for t, d in scan(str(p), 1200) if t >= 3600)), 1)
        rows.append({"file": p.name, **m})
(out / "measurements.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"active RMS {level:.1f} dBFS for all files")
keys = list(rows[0])
print(" | ".join(keys))
for r in rows:
    print(" | ".join(str(r[k]) for k in keys))
