"""Adapter interface: one implementation per TTS model family."""
from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from ..schemas import ModelCapabilities, VoiceProfile


class TTSAdapter(Protocol):
    adapter_id: str

    def capabilities(self) -> ModelCapabilities:
        """What this adapter supports, natively or via engine/DSP."""
        ...

    def speakers(self) -> list[str]:
        """Model speaker names usable in voice profiles."""
        ...

    def synthesize(self, text: str, voice: VoiceProfile, gap_s: float) -> NDArray[np.float32]:
        """Return mono float32 audio at capabilities().sample_rate for neutral delivery.

        `gap_s` is the silence placed between sentences the adapter splits internally.
        """
        ...
