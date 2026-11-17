"""Create controlled low-processing voice variants from one raw synthesis per speaker.

The same raw waveform feeds every variant, so differences come only from post-processing.
This is an objective screening tool; a listener still makes the final naturalness choice.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tone_scan import scan  # noqa: E402
from voice_metrics import measure  # noqa: E402
from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

SR = 24000
TEXT = "ရန်ကုန်မြို့သည် မြန်မာနိုင်ငံ၏ အကြီးဆုံးမြို့ ဖြစ်သည်။ ကမ္ဘာကြီးက တည်ရှိနေတာ ကြာပြီ။ အသံကြည်လင်ပြီး နားထောင်ရ အဆင်ပြေစေရန် စမ်းသပ်ထားပါသည်။"


def process(raw, pitch: float, chain: str):
    audio = dsp.pitch_tempo(raw, SR, pitch, 1.0, "rubberband") if pitch else raw
    audio = dsp.vocos_resynth(audio, SR)
    audio = dsp.pitch_tempo(audio, SR, 0.0, 1.0, "rubberband", chain)
    return dsp.peak_normalize(audio)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--text", default=TEXT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    engine = VoiceEngine.from_settings()
    adapter = engine._adapter(engine.voice("male_calm"))
    specs = {
        "male": ("htet-myat", 0.28, {
            "M_current_up1": (1.0, "bandreject=f=6000:width_type=q:w=8,highpass=f=75:p=2,deesser=i=0.25,lowpass=f=9500:p=2"),
            "M_natural_no_pitch": (0.0, "bandreject=f=6000:width_type=q:w=8,highpass=f=75:p=2,deesser=i=0.20,lowpass=f=9500:p=2"),
        }),
        "female": ("shoon", 0.20, {
            "F_current_deess25": (0.0, "bandreject=f=7200:width_type=q:w=8,highpass=f=75:p=2,deesser=i=0.25,lowpass=f=9500:p=2"),
            "F_clear_deess15": (0.0, "bandreject=f=7200:width_type=q:w=8,highpass=f=75:p=2,deesser=i=0.15,lowpass=f=9500:p=2"),
        }),
    }
    report = {"text": args.text, "note": "Objective screening only; listening review required", "variants": {}}
    for group, (speaker, gap, variants) in specs.items():
        voice = VoiceProfile(voice_id=group, display_name=group, adapter_id="nara-mini-v1",
                             speaker=speaker, sentence_gap_s=gap, style_mode="longform")
        raw = adapter.synthesize(args.text, voice, gap)
        for name, (pitch, chain) in variants.items():
            audio = process(raw, pitch, chain)
            path = args.output / f"{name}.wav"
            sf.write(path, audio, SR, subtype="PCM_16")
            metrics = measure(audio)
            tones = {str(int(freq)): round(float(delta), 2) for freq, delta in scan(str(path), 1200.0) if freq >= 3600}
            worst = max(tones.values())
            report["variants"][name] = {"speaker": speaker, "pitch_semitones": pitch,
                "filter": chain, "metrics": metrics, "tone_delta_db": tones,
                "worst_tone_delta_db": worst, "tone_check_passed": worst < 3.0}
            print(f"{name}: periodicity={metrics['periodicity']:.3f}, jitter={metrics['jitter_st']:.3f} st, "
                  f"centroid={metrics['centroid_hz']} Hz, worst tone={worst:+.1f} dB")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
