"""Render filter variants of a Nara speaker for listening tests (no pitch/tempo change).

    .venv-nara\\Scripts\\python.exe scripts\\voice_filter_variants.py ko-banyar outputs/vf-male P
"""
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile
from myanmar_voice_studio.engine import dsp

speaker, out, prefix = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
out.mkdir(parents=True, exist_ok=False)
sr = 24000
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join(Path("outputs/passage.txt").read_text(encoding="utf-8").split())
voice = VoiceProfile(voice_id="v", display_name="v", adapter_id="nara-mini-v1", speaker=speaker, sentence_gap_s=0.28)
raw = adapter.synthesize(text, voice, voice.sentence_gap_s)

chains = {
    "1_raw": "",
    "2_hp80": "highpass=f=80:p=2",
    "3_hp80_lp9500": "highpass=f=80:p=2,lowpass=f=9500:p=2",
    "4_hp80_lp8000": "highpass=f=80:p=2,lowpass=f=8000:p=2",
    "5_denoise_lp8500": "highpass=f=80:p=2,afftdn=nr=8:nf=-40,lowpass=f=8500:p=2",
    "6_deess_lp9000": "highpass=f=80:p=2,deesser=i=0.4,lowpass=f=9000:p=2",
}


def metrics(x):
    X = np.abs(np.fft.rfft(x))
    P = X ** 2
    f = np.fft.rfftfreq(x.size, 1 / sr)
    d2 = np.abs(np.diff(x, 2))
    return (f"hf>7k={X[f > 7000].sum() / X.sum():.3f} LF<80={P[f < 80].sum() / P.sum():.3f} "
            f"clicks={(d2 > 80 * np.median(d2[d2 > 0])).sum()}")


ffmpeg = dsp.ffmpeg_path()
with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for name, chain in chains.items():
        wav = dsp._run_ffmpeg(ffmpeg, raw, sr, [chain]) if chain else raw
        wav = dsp.peak_normalize(wav)
        p = out / f"{prefix}{name}.wav"
        sf.write(p, wav, sr, subtype="PCM_16")
        z.write(p, p.name)
        print(p.name, metrics(wav))
