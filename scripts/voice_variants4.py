"""Round 4: younger (~22) male from Htet Myat. Pitch up BEFORE Vocos so Vocos cleans the
pitch-shift artifacts, then whine notches + EQ + de-esser (same as M13).

    .venv-nara\\Scripts\\python.exe scripts\\voice_variants4.py outputs/vf4
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tone_scan import scan  # noqa: E402

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
SR = 24000
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())
v = VoiceProfile(voice_id="h", display_name="h", adapter_id="nara-mini-v1", speaker="htet-myat", sentence_gap_s=0.28)
raw = adapter.synthesize(text, v, v.sentence_gap_s)

NOTCH = ",".join(f"bandreject=f={f}:width_type=q:w=20" for f in range(3600, 12000, 1200))
BASE = "highpass=f=80:p=2,deesser=i=0.4,lowpass=f=9000:p=2"
LESS_DEEP = "equalizer=f=200:t=q:w=0.9:g=-4,equalizer=f=3000:t=q:w=1:g=2"
YOUNG_EQ = "equalizer=f=180:t=q:w=0.9:g=-6,equalizer=f=3200:t=q:w=1:g=3"


def shift(x, semis, formant):
    if semis == 0:
        return x
    r = 2 ** (semis / 12)
    return dsp._run_ffmpeg(dsp.ffmpeg_path(), x, SR, [f"rubberband=pitch={r:.5f}:formant={formant}:pitchq=quality"])


variants = {
    "Y0_M13_current": (0.0, "preserved", LESS_DEEP),
    "Y1_up1": (1.0, "preserved", LESS_DEEP),
    "Y2_up2": (2.0, "preserved", LESS_DEEP),
    "Y3_up1.5_young_timbre": (1.5, "shifted", LESS_DEEP),
    "Y4_up2_young_timbre_brighter": (2.0, "shifted", YOUNG_EQ),
}


def centroid(x):
    P = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(x.size, 1 / SR)
    return (f * P).sum() / P.sum(), P[(f > 100) & (f < 300)].sum() / P.sum()


def f0_median(x):
    """Rough median pitch via autocorrelation over voiced 40 ms frames."""
    n = int(0.04 * SR)
    vals = []
    for s in range(0, x.size - n, n):
        fr = x[s : s + n] - x[s : s + n].mean()
        if np.sqrt((fr ** 2).mean()) < 0.05:
            continue
        ac = np.correlate(fr, fr, "full")[n - 1 :]
        lo, hi = SR // 300, SR // 70
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.3 * ac[0]:
            vals.append(SR / lag)
    return float(np.median(vals)) if vals else 0.0


with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for name, (semis, formant, eq) in variants.items():
        x = dsp.vocos_resynth(shift(raw, semis, formant), SR)
        wav = dsp.peak_normalize(dsp._run_ffmpeg(dsp.ffmpeg_path(), x, SR, [f"{NOTCH},{eq},{BASE}"]))
        p = out / f"{name}.wav"
        sf.write(p, wav, SR, subtype="PCM_16")
        z.write(p, p.name)
        c, bass = centroid(wav)
        worst = max(d for t, d in scan(str(p), 1200) if t >= 3600)
        print(f"{name:30} pitch~{f0_median(wav):5.0f} Hz  centroid {c:4.0f} Hz  bass {bass:.2f}  whine {worst:+.0f} dB")
