"""Load voice profiles from config/voice_presets.json."""
from __future__ import annotations

import json
from pathlib import Path

from .schemas import VoiceProfile


def load_voices(presets_file: Path) -> dict[str, VoiceProfile]:
    data = json.loads(presets_file.read_text(encoding="utf-8"))
    voices: dict[str, VoiceProfile] = {}
    for voice_id, p in data["presets"].items():
        voices[voice_id] = VoiceProfile(
            voice_id=voice_id,
            display_name=p.get("display_name", voice_id),
            adapter_id=p.get("adapter", "nara-mini-v1"),
            speaker=p["voice"],
            style_offset=p.get("style_offset", 0),
            style_mode=p.get("style_mode", "length"),
            lowpass_hz=p.get("lowpass_hz", 0.0),
            pitch_semitones=p.get("pitch_semitones", 0.0),
            tempo=p.get("tempo", 1.0),
            sentence_gap_s=p.get("sentence_gap_s", 0.2),
            pitch_method=p.get("pitch_method", "resample"),
            post_filter=p.get("post_filter", ""),
            resynth=p.get("resynth", ""),
            reference_audio=p.get("reference_audio", ""),
            reference_text=p.get("reference_text", ""),
            license_note=p.get("license_note", ""),
            user_rating=p.get("user_rating", ""),
        )
    return voices
