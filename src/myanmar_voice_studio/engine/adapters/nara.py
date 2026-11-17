"""Nara Mini v1 adapter (Kokoro-based ONNX, Apache-2.0), CPU via onnxruntime.

Text frontend: our refined fork in third_party/nara_mini_v1 (pronunciation fixes live there).
Weights: <models_dir>/nara-mini-v1/onnx/<speaker>/{encoder,decoder}.onnx + voice.json.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import threading
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ..dsp import edge_fade
from ..expression import DELIVERIES, EMOTIONS
from ..schemas import ControlCapability, ModelCapabilities, Support, VoiceProfile

SAMPLE_RATE = 24000
MAX_CHARS = 2000
PIECE_LIMIT = 200  # characters per synthesized piece, as in the upstream app
SPEAKERS = ["shoon", "thazin", "ko-banyar", "htet-myat"]


def split_speech(text: str, limit: int = PIECE_LIMIT) -> list[str]:
    """Split at sentence (။ ! ? …) and clause (၊) marks, then pack pieces up to `limit` chars."""
    units: list[str] = []
    for sentence in re.split(r"(?<=[။!?…\n])\s*", text):
        for clause in re.split(r"(?<=၊)\s*", sentence):
            while len(clause) > limit:
                cut = clause.rfind(" ", 0, limit)
                if cut <= 0:
                    cut = limit
                units.append(clause[:cut])
                clause = clause[cut:].strip()
            if clause.strip():
                units.append(clause.strip())
    pieces: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > limit:
            pieces.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        pieces.append(current)
    return pieces


class NaraAdapter:
    adapter_id = "nara-mini-v1"

    def __init__(self, models_dir: Path, frontend_dir: Path, threads: int = 4):
        self._onnx_dir = models_dir / "nara-mini-v1" / "onnx"
        self._frontend_dir = frontend_dir
        self._threads = threads
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._frontend = None

    # -- capability report -------------------------------------------------
    def capabilities(self) -> ModelCapabilities:
        c = ControlCapability
        controls = {
            "speed": c(name="speed", support=Support.DSP, min=0.5, max=2.0,
                       note="ffmpeg tempo after synthesis; duration scaling in the model had little effect"),
            "pitch": c(name="pitch", support=Support.DSP, min=-6, max=6,
                       note="ffmpeg pitch shift after synthesis; large shifts sound artificial"),
            "pause_before": c(name="pause_before", support=Support.ENGINE, note="inserted silence"),
            "pause_after": c(name="pause_after", support=Support.ENGINE, note="inserted silence"),
            "emotion": c(name="emotion", support=Support.DSP, values=sorted(EMOTIONS),
                         note="prosody approximation (speed/pitch/pause/level); not acted emotion"),
            "delivery": c(name="delivery", support=Support.DSP, values=sorted(DELIVERIES),
                          note="narrator/podcast/energetic/soft via prosody DSP; whisper and shout are not produced"),
            "energy": c(name="energy", support=Support.UNSUPPORTED),
            "emphasis": c(name="emphasis", support=Support.UNSUPPORTED),
        }
        return ModelCapabilities(
            adapter_id=self.adapter_id,
            model_id="YeeNyunn/nara-mini-v1",
            model_license="Apache-2.0 (voice data synthesized with VoxCPM2; review before release)",
            languages=["my-MM", "en"],
            devices=["cpu"],
            sample_rate=SAMPLE_RATE,
            max_chars=MAX_CHARS,
            controls=controls,
        )

    def speakers(self) -> list[str]:
        return [s for s in SPEAKERS if (self._onnx_dir / s / "encoder.onnx").exists()]

    # -- loading -------------------------------------------------------------
    def _load_frontend(self):
        if self._frontend is None:
            if not (self._frontend_dir / "frontend").is_dir():
                raise RuntimeError(f"Nara frontend fork not found at {self._frontend_dir}")
            if str(self._frontend_dir) not in sys.path:
                sys.path.insert(0, str(self._frontend_dir))
            english = importlib.import_module("frontend.english")
            numbers = importlib.import_module("frontend.my_numbers")
            nara = importlib.import_module("frontend.nara_frontend")
            self._frontend = (english.to_tokens, numbers.verbalize, nara.phonemize, nara.prepare_names)
        return self._frontend

    def _session(self, speaker: str) -> dict:
        with self._lock:
            if speaker not in self._sessions:
                import onnxruntime as ort

                base = self._onnx_dir / speaker
                if not (base / "encoder.onnx").exists():
                    raise RuntimeError(f"Nara speaker '{speaker}' is not installed in {self._onnx_dir}")
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = self._threads
                opts.inter_op_num_threads = 1
                providers = ["CPUExecutionProvider"]
                self._sessions[speaker] = {
                    "encoder": ort.InferenceSession(str(base / "encoder.onnx"), opts, providers=providers),
                    "decoder": ort.InferenceSession(str(base / "decoder.onnx"), opts, providers=providers),
                    "meta": json.loads((base / "voice.json").read_text(encoding="utf-8")),
                }
            return self._sessions[speaker]

    # -- synthesis -------------------------------------------------------------
    def phonemize(self, text: str) -> str:
        to_tokens, _, phonemize, prepare_names = self._load_frontend()
        return phonemize(to_tokens(prepare_names(text)))

    def _piece(self, sess: dict, chars: str, style_offset: int, style_mode: str = "length") -> NDArray[np.float32]:
        meta = sess["meta"]
        tokens = [meta["vocab"][c] for c in chars if c in meta["vocab"]]
        if not tokens:
            raise ValueError("Text produced no phonemes; enter Burmese or English text")
        if len(tokens) > 508:
            raise ValueError("A piece exceeds the phoneme context limit; use shorter sentences")
        index = int(np.argmin(np.abs(np.asarray(meta["centers"]) - len(tokens))))
        index = int(np.clip(index + style_offset, 0, len(meta["styles"]) - 1))
        if style_mode == "longform":  # style learned on the longest utterances, for every piece
            index = len(meta["styles"]) - 1
        if style_mode == "average":
            style = np.asarray([np.mean(np.asarray(meta["styles"]), axis=0)], dtype=np.float32)
        else:
            style = np.asarray([meta["styles"][index]], dtype=np.float32)
        durations, prosody, encoded = sess["encoder"].run(
            ["durations", "prosody", "text"],
            {"tokens": np.asarray([[0, *tokens, 0]], dtype=np.int64), "style": style},
        )
        if durations.min() < 1 or not 1 <= durations.sum() <= 20000:
            raise ValueError("The model predicted an invalid duration for this text")
        samples = sess["decoder"].run(
            None,
            {
                "prosody": np.repeat(prosody, durations[0], axis=2),
                "text": np.repeat(encoded, durations[0], axis=2),
                "style": style,
            },
        )[0].reshape(-1)
        if samples.size < 2400 or not np.isfinite(samples).all():
            raise ValueError("The model produced invalid audio for this text")
        return np.clip(samples, -1, 1).astype(np.float32)

    def synthesize(self, text: str, voice: VoiceProfile, gap_s: float) -> NDArray[np.float32]:
        _, verbalize, _, _ = self._load_frontend()
        sess = self._session(voice.speaker)
        gap = np.zeros(int(SAMPLE_RATE * gap_s), dtype=np.float32)
        chunks: list[NDArray[np.float32]] = []
        for piece in split_speech(verbalize(text)):
            if chunks:
                chunks.append(gap)
            chunks.append(edge_fade(self._piece(sess, self.phonemize(piece), voice.style_offset, voice.style_mode), SAMPLE_RATE))
        if not chunks:
            raise ValueError("No speakable text")
        return np.concatenate(chunks)
