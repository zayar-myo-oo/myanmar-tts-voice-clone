"""VoiceEngine: the single entry point used by the CLI, the desktop app and the MCP server."""
from __future__ import annotations

import unicodedata
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

from . import dsp, expression
from .adapters.base import TTSAdapter
from .schemas import (
    AppliedControl,
    ModelCapabilities,
    Support,
    SynthesisRequest,
    SynthesisResult,
    UnsupportedControlError,
    VoiceProfile,
)
from .settings import Settings
from .voices import load_voices


def write_wav_exclusive(path: Path, wav: np.ndarray, sr: int) -> Path:
    """Write 16-bit WAV; fail if the file already exists (never overwrite)."""
    with open(path, "xb") as handle:
        sf.write(handle, wav, sr, format="WAV", subtype="PCM_16")
    return path


class VoiceEngine:
    def __init__(self, voices: dict[str, VoiceProfile], adapters: dict[str, TTSAdapter]):
        self._voices = voices
        self._adapters = adapters

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "VoiceEngine":
        from .adapters.nara import NaraAdapter

        from .adapters.f5clone import F5CloneAdapter

        s = settings or Settings.from_env()
        nara = NaraAdapter(s.models_dir, s.third_party_dir / "nara_mini_v1")
        adapters: dict = {nara.adapter_id: nara}
        if F5CloneAdapter.available():  # GPU env with torch + f5-myanmar-tts
            f5 = F5CloneAdapter(s.project_root)
            adapters[f5.adapter_id] = f5
        return cls(load_voices(s.presets_file), adapters)

    # -- discovery -------------------------------------------------------------
    def list_voices(self) -> list[VoiceProfile]:
        """Voices whose model adapter is installed in this environment."""
        return [v for v in self._voices.values() if v.adapter_id in self._adapters]

    def voice(self, voice_id: str) -> VoiceProfile:
        try:
            return self._voices[voice_id]
        except KeyError:
            known = ", ".join(sorted(self._voices)) or "none"
            raise ValueError(f"Unknown voice '{voice_id}'. Installed voices: {known}") from None

    def _adapter(self, voice: VoiceProfile) -> TTSAdapter:
        try:
            return self._adapters[voice.adapter_id]
        except KeyError:
            raise ValueError(f"Adapter '{voice.adapter_id}' for voice '{voice.voice_id}' is not available") from None

    def capabilities(self, voice_id: str) -> ModelCapabilities:
        return self._adapter(self.voice(voice_id)).capabilities()

    # -- planning --------------------------------------------------------------
    def plan(self, request: SynthesisRequest) -> tuple[list[AppliedControl], list[str]]:
        """Translate requested controls into what this voice can apply. No audio is produced."""
        caps = self.capabilities(request.voice_id)
        applied: list[AppliedControl] = []
        unsupported: list[str] = []
        for name, value in request.requested_controls().items():
            support = caps.support_of(name, value)
            if support is Support.UNSUPPORTED:
                unsupported.append(f"{name}={value}")
            else:
                applied.append(AppliedControl(name=name, value=value, support=support))
        if unsupported and request.strict:
            raise UnsupportedControlError(unsupported)
        return applied, unsupported

    # -- synthesis -------------------------------------------------------------
    def render(self, request: SynthesisRequest) -> tuple[np.ndarray, int, list[AppliedControl], list[str], list[str]]:
        """Synthesize to memory: (audio, sample_rate, applied, unsupported, warnings)."""
        voice = self.voice(request.voice_id)
        adapter = self._adapter(voice)
        caps = adapter.capabilities()
        applied, unsupported = self.plan(request)
        warnings = [f"Not applied (unsupported by {caps.model_id}): {u}" for u in unsupported]

        text = unicodedata.normalize("NFC", request.text).strip()
        if not text:
            raise ValueError("Text is empty")
        if len(text) > caps.max_chars:
            raise ValueError(f"Text exceeds {caps.max_chars} characters; split it into segments")

        sr = caps.sample_rate
        wav = adapter.synthesize(text, voice, voice.sentence_gap_s)
        if voice.resynth not in ("", "vocos"):
            raise ValueError(f"unknown resynth '{voice.resynth}' for voice {voice.voice_id}")
        applied_names = {a.name for a in applied}
        prosody = expression.combine(
            request.emotion if "emotion" in applied_names else None,
            request.delivery if "delivery" in applied_names else None,
        )
        pitch = float(np.clip(voice.pitch_semitones + request.pitch_semitones + prosody.pitch, -12, 12))
        tempo = voice.tempo * request.speed * prosody.speed
        if voice.resynth == "vocos":
            # Pitch/tempo first, then Vocos re-synthesis cleans the stretcher's artifacts
            # (and the model's own vocoder whine), then the voice's filter chain.
            wav = dsp.pitch_tempo(wav, sr, pitch, tempo, voice.pitch_method)
            wav = dsp.vocos_resynth(wav, sr)
            pitch, tempo = 0.0, 1.0
        wav = dsp.soft_lowpass(wav, voice.lowpass_hz, sr)
        if prosody.lowpass_hz:
            wav = dsp.soft_lowpass(wav, prosody.lowpass_hz, sr)
        wav = dsp.pitch_tempo(wav, sr, pitch, tempo, voice.pitch_method, voice.post_filter)
        wav = dsp.peak_normalize(wav) * prosody.gain
        pause_after = request.pause_after_ms + prosody.pause_after_ms
        if request.pause_before_ms or pause_after:
            wav = np.concatenate([dsp.silence(request.pause_before_ms, sr), wav, dsp.silence(pause_after, sr)])
        if not np.isfinite(wav).all() or float(np.abs(wav).max()) < 1e-3:
            raise RuntimeError("Synthesis produced invalid or silent audio")
        return wav.astype(np.float32), sr, applied, unsupported, warnings

    def synthesize(self, request: SynthesisRequest, output_dir: Path) -> SynthesisResult:
        output_dir = Path(output_dir)
        if not output_dir.is_dir():
            raise ValueError(f"Output directory does not exist: {output_dir}")
        voice = self.voice(request.voice_id)
        adapter = self._adapter(voice)
        caps = adapter.capabilities()
        wav, sr, applied, unsupported, warnings = self.render(request)
        path = write_wav_exclusive(output_dir / f"{voice.voice_id}-{uuid.uuid4().hex[:12]}.wav", wav, sr)

        return SynthesisResult(
            output_path=path,
            sample_rate=sr,
            duration_s=round(wav.size / sr, 3),
            voice_id=voice.voice_id,
            adapter_id=adapter.adapter_id,
            model_id=caps.model_id,
            applied=applied,
            unsupported=unsupported,
            warnings=warnings,
        )
