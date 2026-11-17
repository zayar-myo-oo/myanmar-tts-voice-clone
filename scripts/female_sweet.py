"""Female 'sweeter' variants on top of F11 (Shoon): style, warmth/softness EQ, slight pitch lift.

    .venv-nara\\Scripts\\python.exe scripts\\female_sweet.py outputs/diag-female/sweet
"""
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tone_scan import scan  # noqa: E402
from voice_metrics import SR, loudness_match, measure  # noqa: E402

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
P = json.loads((ROOT / "config/voice_presets.json").read_text(encoding="utf-8"))["presets"]["female_warm"]
CHAIN = P["post_filter"]
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("female_warm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())
ff = dsp.ffmpeg_path()

# Warm + soft: a little body at 250 Hz, less harshness at 3.5 kHz, gentler sibilance, slightly softer top.
WARM = "equalizer=f=250:t=q:w=1:g=1.5,equalizer=f=3500:t=q:w=1.2:g=-2.5"
SOFT_TOP = "equalizer=f=7000:t=q:w=1:g=-2"


def raw(mode="length"):
    v = VoiceProfile(voice_id="f", display_name="f", adapter_id="nara-mini-v1", speaker=P["voice"],
                     sentence_gap_s=P["sentence_gap_s"], style_mode=mode)
    return adapter.synthesize(text, v, v.sentence_gap_s)


def finish(x, extra="", semis=0.0):
    if semis:
        r = 2 ** (semis / 12)
        x = dsp._run_ffmpeg(ff, x, SR, [f"rubberband=pitch={r:.5f}:formant=preserved:pitchq=quality"])
    x = dsp.vocos_resynth(x, SR)
    return dsp._run_ffmpeg(ff, x, SR, [CHAIN + (f",{extra}" if extra else "")])


r_len, r_long = raw("length"), raw("longform")
signals = {
    "W0_F11_current": finish(r_len),
    "W1_longform_style": finish(r_long),
    "W2_warm_soft_EQ": finish(r_len, f"{WARM},{SOFT_TOP}"),
    "W3_longform+warm_soft": finish(r_long, f"{WARM},{SOFT_TOP}"),
    "W4_W3+lift_0.5st": finish(r_long, f"{WARM},{SOFT_TOP}", semis=0.5),
}
matched, level = loudness_match(signals)
rows = []
with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for name, y in matched.items():
        p = out / f"{name}.wav"
        sf.write(p, y, SR, subtype="PCM_16")
        z.write(p, p.name)
        P_ = np.abs(np.fft.rfft(y)) ** 2
        f = np.fft.rfftfreq(y.size, 1 / SR)
        harsh = P_[(f > 2500) & (f < 5000)].sum() / P_.sum()
        rows.append({"file": p.name, **measure(y), "harsh_2.5-5k": round(float(harsh), 4),
                     "whine_db": round(float(max(d for t, d in scan(str(p), 1200) if t >= 3600)), 1)})
(out / "measurements.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
keys = ["file", "f0_hz", "f0_sd_st", "centroid_hz", "bass_100_300", "harsh_2.5-5k", "whine_db", "peak_dbfs"]
print(f"active RMS {level:.1f} dBFS"); print(" | ".join(keys))
for r in rows:
    print(" | ".join(str(r[k]) for k in keys))
