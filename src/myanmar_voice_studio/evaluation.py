"""Small evaluation utilities, not the Phase 3 production voice engine."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class PreparedText:
    original: str
    spoken: str
    warnings: tuple[str, ...]


def prepare_text(text: str, vocabulary: set[str], max_chars: int = 400) -> PreparedText:
    """Preserve Burmese marks; replace punctuation with spaces; reject lost content."""
    if not text.strip():
        raise ValueError("Text is empty")
    if len(text) > max_chars:
        raise ValueError(f"Use a short segment of at most {max_chars} characters")
    normalized = unicodedata.normalize("NFC", text)
    warnings: list[str] = []
    if normalized != text:
        warnings.append("Unicode NFC normalization applied")
    unsupported: set[str] = set()
    converted: list[str] = []
    removed_punctuation: set[str] = set()
    for char in normalized:
        if char in vocabulary:
            converted.append(char)
        elif char.isspace():
            converted.append(" ")
        elif unicodedata.category(char).startswith("P"):
            converted.append(" ")
            removed_punctuation.add(char)
        else:
            unsupported.add(char)
    if unsupported:
        labels = ", ".join(f"{char!r} (U+{ord(char):04X})" for char in sorted(unsupported))
        raise ValueError(f"Unsupported characters: {labels}. Write numbers/foreign words in Burmese words.")
    spoken = " ".join("".join(converted).split())
    if not spoken or not any("\u1000" <= char <= "\u109f" for char in spoken):
        raise ValueError("No supported Burmese text remains")
    if removed_punctuation:
        warnings.append("Punctuation replaced by spaces; sentence pauses/intonation are not guaranteed")
    return PreparedText(text, spoken, tuple(warnings))


def audio_metrics(audio: NDArray[np.floating], sample_rate: int) -> dict[str, float | int | bool]:
    if audio.ndim != 1 or audio.size == 0 or sample_rate <= 0:
        raise ValueError("Expected nonempty mono audio and a positive sample rate")
    if not np.isfinite(audio).all():
        raise ValueError("Generated waveform contains non-finite values")
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    clipping = float(np.mean(np.abs(audio) >= 1.0))
    return {"samples": int(audio.size), "duration_seconds": audio.size / sample_rate,
            "peak": peak, "rms": rms, "clipped_fraction": clipping,
            "signal_check_passed": rms > 1e-5 and clipping < 0.001}
