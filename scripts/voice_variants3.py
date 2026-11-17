"""Round 3: remove the full 1200 Hz-harmonic whine; compare notching vs Vocos re-synthesis;
male 'less deep' options. Run from .venv-f5 (needs torch + vocos for the V* variants).

    .venv-f5\\Scripts\\python.exe scripts\\voice_variants3.py outputs/vf3
"""
import sys
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from tone_scan import scan  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
SR = 24000
eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())

NOTCH_ALL = ",".join(f"bandreject=f={f}:width_type=q:w=20" for f in range(3600, 12000, 1200))
BASE = "highpass=f=80:p=2,deesser=i=0.4,lowpass=f=9000:p=2"
LESS_DEEP = "equalizer=f=200:t=q:w=0.9:g=-4,equalizer=f=3000:t=q:w=1:g=2"


def raw(speaker):
    v = VoiceProfile(voice_id=speaker, display_name=speaker, adapter_id="nara-mini-v1", speaker=speaker, sentence_gap_s=0.28)
    return adapter.synthesize(text, v, v.sentence_gap_s)


_vocos = None


def vocos_resynth(wav):
    """Re-synthesise through Vocos (mel 24 kHz, MIT) to replace the iSTFTNet output stage."""
    global _vocos
    from vocos import Vocos

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if _vocos is None:
        _vocos = Vocos.from_pretrained("charactr/vocos-mel-24khz").to(dev).eval()
    with torch.inference_mode():
        x = torch.from_numpy(np.asarray(wav, dtype=np.float32)).unsqueeze(0).to(dev)
        mel = _vocos.feature_extractor(x)
        y = _vocos.decode(mel)
    return y.squeeze().float().cpu().numpy()[: len(wav)]


def render(src, semis=0.0, chain=BASE, resynth=False):
    x = vocos_resynth(src) if resynth else src
    return dsp.peak_normalize(dsp.pitch_tempo(x, SR, semis, 1.0, "rubberband", chain))


shoon, htet = raw("shoon"), raw("htet-myat")
variants = {
    "F9_shoon_notch_all": render(shoon, chain=f"{NOTCH_ALL},{BASE}"),
    "F10_shoon_vocos": render(shoon, chain=BASE, resynth=True),
    "F11_shoon_vocos_notch_all": render(shoon, chain=f"{NOTCH_ALL},{BASE}", resynth=True),
    "M11_htet_notch_all_lessdeep": render(htet, chain=f"{NOTCH_ALL},{LESS_DEEP},{BASE}"),
    "M12_htet_vocos_lessdeep": render(htet, chain=f"{LESS_DEEP},{BASE}", resynth=True),
    "M13_htet_vocos_notch_all_lessdeep": render(htet, chain=f"{NOTCH_ALL},{LESS_DEEP},{BASE}", resynth=True),
}

with zipfile.ZipFile(out.parent / f"{out.name}.zip", "w") as z:
    for name, wav in variants.items():
        p = out / f"{name}.wav"
        sf.write(p, wav, SR, subtype="PCM_16")
        z.write(p, p.name)
        lines = scan(str(p), 1200)
        worst = max(d for t, d in lines if t >= 3600)
        print(f"{name:36} worst whine line {worst:+.0f} dB | " + " ".join(f"{int(t)}:{d:+.0f}" for t, d in lines if t >= 3600))
