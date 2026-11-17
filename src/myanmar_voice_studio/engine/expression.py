"""Expression presets realised as prosody DSP (speed, pitch, pauses, level).

These are approximations: they change rate, pitch, pauses and loudness after synthesis.
They are NOT acted emotion from the model, and are reported with support "dsp".
Whisper and shout need voice-quality changes (breath, strain) that DSP cannot create, so
they stay unsupported until an expressive model or dataset exists.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prosody:
    speed: float = 1.0  # multiplier
    pitch: float = 0.0  # semitones added
    pause_after_ms: int = 0  # extra pause
    gain: float = 1.0  # output level multiplier after normalization (<=1)
    lowpass_hz: float = 0.0  # extra softening; 0 = none


EMOTIONS: dict[str, Prosody] = {
    "calm": Prosody(speed=0.92, pitch=-0.5, pause_after_ms=150),
    "sad": Prosody(speed=0.86, pitch=-1.2, pause_after_ms=250, gain=0.85),
    "happy": Prosody(speed=1.05, pitch=1.0),
    "excited": Prosody(speed=1.12, pitch=1.8),
    "surprised": Prosody(speed=1.06, pitch=2.2),
    "curious": Prosody(speed=0.97, pitch=0.8, pause_after_ms=200),
    "suspenseful": Prosody(speed=0.84, pitch=-0.8, pause_after_ms=500, gain=0.9),
    "angry": Prosody(speed=1.08, pitch=0.6),
}

DELIVERIES: dict[str, Prosody] = {
    "narrator": Prosody(speed=0.95, pause_after_ms=150),
    "podcast": Prosody(speed=1.03),
    "energetic": Prosody(speed=1.12, pitch=1.2),
    "soft": Prosody(speed=0.94, pitch=-0.4, gain=0.7, lowpass_hz=6500),
}

UNSUPPORTED_DELIVERIES = ("whisper", "shout")


def combine(emotion: str | None, delivery: str | None) -> Prosody:
    """Merge emotion and delivery: speeds multiply, pitches/pauses add, gains multiply."""
    parts = [p for p in (EMOTIONS.get(emotion or ""), DELIVERIES.get(delivery or "")) if p]
    out = Prosody()
    for p in parts:
        out = Prosody(
            speed=out.speed * p.speed,
            pitch=out.pitch + p.pitch,
            pause_after_ms=out.pause_after_ms + p.pause_after_ms,
            gain=out.gain * p.gain,
            lowpass_hz=min(x for x in (out.lowpass_hz or 1e9, p.lowpass_hz or 1e9)) if (out.lowpass_hz or p.lowpass_hz) else 0.0,
        )
    return out
