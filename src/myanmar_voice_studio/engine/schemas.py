"""Typed contracts shared by the engine, the future desktop app and the MCP server.

These models describe what a caller *wants*. Adapters report what they *applied*.
Nothing here promises that a model can produce an emotion or delivery style.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Support(str, Enum):
    """How a control is realised by a given adapter."""

    NATIVE = "native"  # the model itself produces it
    DSP = "dsp"  # post-processing after synthesis (labelled as such)
    ENGINE = "engine"  # assembled by the engine, e.g. inserted silence
    UNSUPPORTED = "unsupported"


class ControlCapability(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    support: Support
    note: str = ""
    min: float | None = None
    max: float | None = None
    values: list[str] | None = None  # for enum controls: the values that can be applied


class ModelCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter_id: str
    model_id: str
    model_license: str
    languages: list[str]
    devices: list[str]
    sample_rate: int
    max_chars: int
    controls: dict[str, ControlCapability]

    def support_of(self, control: str, value: object = None) -> Support:
        cap = self.controls.get(control)
        if cap is None:
            return Support.UNSUPPORTED
        if cap.values is not None and value is not None and str(value) not in cap.values:
            return Support.UNSUPPORTED
        return cap.support


class VoiceProfile(BaseModel):
    """A named voice: model speaker plus default delivery settings."""

    model_config = ConfigDict(frozen=True)

    voice_id: str
    display_name: str
    adapter_id: str
    speaker: str
    style_offset: int = 0
    style_mode: str = "length"  # "length" (default), "longform", "average"
    lowpass_hz: float = 0.0
    pitch_semitones: float = 0.0
    tempo: float = 1.0
    sentence_gap_s: float = 0.2
    pitch_method: str = "resample"  # or "rubberband" (fewer artifacts)
    post_filter: str = ""  # extra ffmpeg filter chain after pitch/tempo
    reference_audio: str = ""  # clone adapters: path relative to the project root
    reference_text: str = ""  # exact words spoken in reference_audio
    resynth: str = ""  # "vocos" = re-synthesise through Vocos before filtering
    license_note: str = ""
    user_rating: str = ""


class SynthesisRequest(BaseModel):
    """One sentence or segment to synthesize."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    voice_id: str
    speed: float = Field(1.0, ge=0.5, le=2.0, description="relative to the voice default")
    pitch_semitones: float = Field(0.0, ge=-6.0, le=6.0, description="added to the voice default")
    emotion: str | None = None
    delivery: str | None = None  # e.g. whisper, shout, narrator
    energy: float | None = Field(None, ge=0.0, le=1.0)
    emphasis: float | None = Field(None, ge=0.0, le=1.0)
    pause_before_ms: int = Field(0, ge=0, le=10000)
    pause_after_ms: int = Field(0, ge=0, le=10000)
    strict: bool = Field(False, description="reject instead of warn when a control is unsupported")

    def requested_controls(self) -> dict[str, object]:
        """Controls the caller changed from neutral defaults."""
        wanted: dict[str, object] = {}
        if self.speed != 1.0:
            wanted["speed"] = self.speed
        if self.pitch_semitones != 0.0:
            wanted["pitch"] = self.pitch_semitones
        for name in ("emotion", "delivery", "energy", "emphasis"):
            value = getattr(self, name)
            if value is not None:
                wanted[name] = value
        if self.pause_before_ms:
            wanted["pause_before"] = self.pause_before_ms
        if self.pause_after_ms:
            wanted["pause_after"] = self.pause_after_ms
        return wanted


class AppliedControl(BaseModel):
    name: str
    value: object
    support: Support


class SynthesisResult(BaseModel):
    output_path: Path
    sample_rate: int
    duration_s: float
    voice_id: str
    adapter_id: str
    model_id: str
    applied: list[AppliedControl]
    unsupported: list[str]
    warnings: list[str]


class UnsupportedControlError(ValueError):
    """Raised in strict mode when a requested control cannot be applied."""

    def __init__(self, controls: list[str]):
        self.controls = controls
        super().__init__(f"Unsupported controls for this voice: {', '.join(controls)}")
