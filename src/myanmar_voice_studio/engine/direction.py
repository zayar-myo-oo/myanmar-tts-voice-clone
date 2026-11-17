"""Versioned voice-direction contract (schema 1.0).

The same JSON document is used by the desktop app, the MCP tools, preset files and script
exports. It describes the *desired* delivery. The renderer reports which parts each voice
could actually apply.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

Emotion = Literal[
    "neutral", "curious", "excited", "calm", "angry", "sad", "suspenseful", "happy", "surprised",
]
Delivery = Literal[
    "normal", "soft", "whisper", "shout", "narrator", "podcast", "energetic",
]


class GlobalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speed: float = Field(1.0, ge=0.5, le=2.0)
    pitch: float = Field(0.0, ge=-6.0, le=6.0, description="semitones added to the voice default")
    energy: float | None = Field(None, ge=0.0, le=1.0)
    pause_scale: float = Field(1.0, ge=0.0, le=4.0, description="multiplies every segment pause")


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    text: str = Field(min_length=1, max_length=2000)
    voice_id: str | None = Field(None, description="overrides the document voice")
    emotion: Emotion | None = None
    delivery: Delivery | None = None
    emphasis: float | None = Field(None, ge=0.0, le=1.0)
    energy: float | None = Field(None, ge=0.0, le=1.0)
    speed: float | None = Field(None, ge=0.5, le=2.0, description="multiplied with global speed")
    pitch: float | None = Field(None, ge=-6.0, le=6.0, description="added to global pitch")
    pause_before_ms: int = Field(0, ge=0, le=10000)
    pause_after_ms: int = Field(0, ge=0, le=10000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("segment text is blank")
        return v


class VoiceDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_name: str = Field("Untitled", max_length=200)
    voice_id: str
    preset: str | None = None
    language: Literal["my-MM", "en"] = "my-MM"
    global_settings: GlobalSettings = GlobalSettings()
    segments: list[Segment] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _unique_ids(self) -> "VoiceDirection":
        seen: set[str] = set()
        for seg in self.segments:
            if seg.id in seen:
                raise ValueError(f"duplicate segment id: {seg.id}")
            seen.add(seg.id)
        return self


def json_schema() -> dict:
    """JSON Schema for tools and the TypeScript app (written to schemas/voice-direction-1.0.json)."""
    schema = VoiceDirection.model_json_schema()
    schema["$id"] = "https://github.com/myanmar-voice-studio/schemas/voice-direction-1.0.json"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
