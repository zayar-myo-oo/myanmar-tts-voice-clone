"""Create synthetic test clips for the ASR check (script lines, one wrong line, one free-speech clip).

    .venv-nara\\Scripts\\python.exe scripts\\make_asr_test_clips.py outputs/asr-test
"""
import sys
from pathlib import Path

import soundfile as sf

from myanmar_voice_studio.engine import SynthesisRequest, VoiceEngine
from myanmar_voice_studio.training.dataset import load_script_table

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)  # new folder only
table = load_script_table(Path("docs/recording-script.md"))
engine = VoiceEngine.from_settings()


def make(name: str, text: str, voice: str = "male_calm") -> None:
    wav, sr, *_ = engine.render(SynthesisRequest(text=text, voice_id=voice))
    sf.write(out / f"{name}.wav", wav, sr)


for rid in ["r001", "r046", "r150", "r300"]:
    make(rid, table[rid])
make("r002", table["r100"])  # wrong line read for r002 -> should be flagged
make("free01", "ဒီနေ့ ကျွန်တော် ဗီဒီယို အသစ် တစ်ခု လုပ်နေတယ်။", "female_warm")  # free speech
print("made", len(list(out.glob("*.wav"))))
