"""Round 2 variants: notch the 2400 Hz-harmonic vocoder whine; lighter/brighter male options.

    .venv-nara\\Scripts\\python.exe scripts\\voice_variants2.py outputs/vf2
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile
from myanmar_voice_studio.engine import dsp

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
sr = 24000
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join(Path("outputs/passage.txt").read_text(encoding="utf-8").split())

NOTCH = ",".join(f"bandreject=f={f}:width_type=q:w=25" for f in (2400, 4800, 7200, 9600))
NOTCH_HI = ",".join(f"bandreject=f={f}:width_type=q:w=25" for f in (4800, 7200, 9600))
BASE = "highpass=f=80:p=2,deesser=i=0.4,lowpass=f=9000:p=2"

# name: (speaker, semitones, chain)
variants = {
    "F7_shoon_notch_hi": ("shoon", 0.0, f"{NOTCH_HI},{BASE}"),
    "F8_shoon_notch_all": ("shoon", 0.0, f"{NOTCH},{BASE}"),
    "M7_kobanyar_notch_less_bass": ("ko-banyar", 0.0, f"{NOTCH_HI},equalizer=f=160:t=q:w=1:g=-5,{BASE}"),
    "M8_kobanyar_up1_notch": ("ko-banyar", 1.0, f"{NOTCH_HI},{BASE}"),
    "M9_htetmyat_notch": ("htet-myat", 0.0, f"{NOTCH_HI},{BASE}"),
    "M10_htetmyat_notch_less_bass": ("htet-myat", 0.0, f"{NOTCH_HI},equalizer=f=160:t=q:w=1:g=-5,{BASE}"),
}


def tone_db(x, freqs=(4800, 7200, 9600)):
    n = 4096
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::1024] * np.hanning(n)
    S = np.abs(np.fft.rfft(fr, axis=1)).mean(0)
    f = np.fft.rfftfreq(n, 1 / sr)
    out = []
    for t in freqs:
        i = int(np.argmin(np.abs(f - t)))
        ring = np.r_[S[i - 40 : i - 5], S[i + 5 : i + 40]]
        out.append(20 * np.log10(S[i - 2 : i + 3].max() / np.median(ring)))
    return " ".join(f"{t}Hz:+{d:.1f}dB" for t, d in zip(freqs, out))


with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    raw_cache = {}
    for name, (spk, semis, chain) in variants.items():
        if spk not in raw_cache:
            v = VoiceProfile(voice_id=spk, display_name=spk, adapter_id="nara-mini-v1", speaker=spk, sentence_gap_s=0.28)
            raw_cache[spk] = adapter.synthesize(text, v, v.sentence_gap_s)
        wav = dsp.peak_normalize(dsp.pitch_tempo(raw_cache[spk], sr, semis, 1.0, "rubberband", chain))
        p = out / f"{name}.wav"
        sf.write(p, wav, sr, subtype="PCM_16")
        z.write(p, p.name)
        print(name, tone_db(wav))
