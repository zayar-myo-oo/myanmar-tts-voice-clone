"""F5-Myanmar-TTS zero-shot clone adapter (freococo/F5-Myanmar-TTS, CC-BY-NC-4.0: personal use only).

A voice profile points at a reference recording of the speaker plus its exact transcript.
Requires torch + f5-myanmar-tts (GPU strongly recommended). Output 24 kHz mono.
"""
from __future__ import annotations

import contextlib
import sys
import threading
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..dsp import edge_fade
from ..expression import DELIVERIES, EMOTIONS
from ..schemas import ControlCapability, ModelCapabilities, Support, VoiceProfile
from .nara import split_speech

SAMPLE_RATE = 24000


class F5CloneAdapter:
    adapter_id = "f5-myanmar"

    def __init__(self, project_root: Path, steps: int = 32):
        self._root = Path(project_root)
        self._steps = steps
        self._tts = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        try:
            import f5_myanmar_tts  # noqa: F401
            import torch  # noqa: F401
        except Exception:
            return False
        return True

    def capabilities(self) -> ModelCapabilities:
        c = ControlCapability
        return ModelCapabilities(
            adapter_id=self.adapter_id,
            model_id="freococo/F5-Myanmar-TTS (zero-shot clone)",
            model_license="CC-BY-NC-4.0 weights: personal / non-commercial use only",
            languages=["my-MM"],
            devices=["cuda", "cpu"],
            sample_rate=SAMPLE_RATE,
            max_chars=1200,
            controls={
                "speed": c(name="speed", support=Support.DSP, min=0.5, max=2.0),
                "pitch": c(name="pitch", support=Support.DSP, min=-6, max=6),
                "pause_before": c(name="pause_before", support=Support.ENGINE),
                "pause_after": c(name="pause_after", support=Support.ENGINE),
                "emotion": c(name="emotion", support=Support.DSP, values=sorted(EMOTIONS),
                             note="prosody approximation; delivery follows the reference recording"),
                "delivery": c(name="delivery", support=Support.DSP, values=sorted(DELIVERIES)),
                "energy": c(name="energy", support=Support.UNSUPPORTED),
                "emphasis": c(name="emphasis", support=Support.UNSUPPORTED),
            },
        )

    def speakers(self) -> list[str]:
        return []

    def _model(self):
        with self._lock:
            if self._tts is None:
                from f5_myanmar_tts import MyanmarTTS

                # The library prints progress to stdout; stdout is our protocol channel.
                with contextlib.redirect_stdout(sys.stderr):
                    self._tts = MyanmarTTS()
            return self._tts

    def _reference(self, voice: VoiceProfile) -> tuple[str, str]:
        if not voice.reference_audio:
            raise ValueError(f"voice '{voice.voice_id}' has no reference_audio")
        audio = (self._root / voice.reference_audio).resolve()
        if not audio.is_file():
            raise ValueError(f"reference audio not found: {voice.reference_audio}")
        text = voice.reference_text
        if not text:
            txt = audio.with_suffix(".txt")
            text = txt.read_text(encoding="utf-8").strip() if txt.exists() else ""
        if not text:
            raise ValueError(f"voice '{voice.voice_id}' needs reference_text (exact words of the reference clip)")
        return str(audio), text

    def synthesize(self, text: str, voice: VoiceProfile, gap_s: float) -> NDArray[np.float32]:
        ref_audio, ref_text = self._reference(voice)
        tts = self._model()
        gap = np.zeros(int(SAMPLE_RATE * gap_s), dtype=np.float32)
        chunks: list[NDArray[np.float32]] = []
        for piece in split_speech(text, limit=160):
            with contextlib.redirect_stdout(sys.stderr):
                wav = tts.speak(text=piece, ref_audio=ref_audio, ref_text=ref_text, steps=self._steps)
            x = wav.float().numpy().astype(np.float32)
            if chunks:
                chunks.append(gap)
            chunks.append(edge_fade(x, SAMPLE_RATE))
        if not chunks:
            raise ValueError("No speakable text")
        return np.concatenate(chunks)
