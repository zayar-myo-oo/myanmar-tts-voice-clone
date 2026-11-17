"""Zero-shot clone of the user's own voice with F5-Myanmar-TTS (CC-BY-NC: personal use only).

    .venv-f5\\Scripts\\python.exe scripts\\clone_f5.py outputs/clone-f5 recordings/zayar_take2/nr028.wav [more refs]

Reference transcript = the approved .txt next to each reference WAV.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
refs = [Path(p) for p in sys.argv[2:]]
ROOT = Path(__file__).resolve().parents[1]
texts = {
    "passage": " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split()),
    "video": "မင်္ဂလာပါ။ ဒီနေ့ ဗီဒီယိုမှာ စိတ်ဝင်စားစရာ အကြောင်းလေး တစ်ခု ပြောပြပါမယ်။ အဆုံးထိ ကြည့်ပေးပါနော်။",
}

from f5_myanmar_tts import MyanmarTTS  # noqa: E402

tts = MyanmarTTS()
for ref in refs:
    ref_text = ref.with_suffix(".txt").read_text(encoding="utf-8").strip()
    # F5 works best with a clean reference trimmed of long silences; 24 kHz mono copy.
    trimmed = out / f"ref_{ref.stem}.wav"
    subprocess.run(["ffmpeg", "-n", "-loglevel", "error", "-i", str(ref), "-af",
                    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,apad=pad_dur=0.3",
                    "-ac", "1", "-ar", "24000", str(trimmed)], check=True)
    for name, text in texts.items():
        dest = out / f"clone_{ref.stem}_{name}.wav"
        tts.speak(text=text, ref_audio=str(trimmed), ref_text=ref_text, output_file=str(dest))
        x, sr = sf.read(dest)
        print(dest.name, f"{len(x) / sr:.2f}s", f"peak={np.abs(x).max():.2f}")
