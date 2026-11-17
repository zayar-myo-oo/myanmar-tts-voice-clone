"""Post-synthesis audio processing. Everything here is DSP, never native synthesis."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

Audio = NDArray[np.float32]


def soft_lowpass(wav: Audio, cutoff: float, sr: int, width: float = 1500.0) -> Audio:
    """Zero-phase FFT low-pass with a cosine roll-off around `cutoff` (tames vocoder fizz)."""
    if cutoff <= 0 or wav.size == 0:
        return wav
    spec = np.fft.rfft(wav)
    freqs = np.fft.rfftfreq(wav.size, 1 / sr)
    lo, hi = cutoff - width / 2, cutoff + width / 2
    gain = np.ones_like(freqs)
    band = (freqs > lo) & (freqs < hi)
    gain[band] = 0.5 * (1 + np.cos(np.pi * (freqs[band] - lo) / (hi - lo)))
    gain[freqs >= hi] = 0.0
    return np.fft.irfft(spec * gain, n=wav.size).astype(np.float32)


def edge_fade(wav: Audio, sr: int, ms: float = 8.0) -> Audio:
    """Short fade in/out so joined pieces do not click."""
    n = min(int(sr * ms / 1000), wav.size // 2)
    if n <= 0:
        return wav
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out = wav.copy()
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def peak_normalize(wav: Audio, target_peak: float = 0.89) -> Audio:
    """Scale so the peak sits at about -1 dBFS."""
    peak = float(np.abs(wav).max()) if wav.size else 0.0
    return (wav * (target_peak / peak)).astype(np.float32) if peak > 0 else wav


_VOCOS = None
VOCOS_REPO = "charactr/vocos-mel-24khz"  # MIT


def vocos_resynth(wav: Audio, sr: int) -> Audio:
    """Re-synthesise audio through the Vocos 24 kHz mel vocoder (MIT).

    Replaces the TTS model's own iSTFTNet output stage, which leaves narrow whine lines at
    multiples of 1200 Hz. Needs torch + vocos; the model is cached locally after first use.
    """
    global _VOCOS
    if sr != 24000:
        raise ValueError("Vocos re-synthesis expects 24 kHz audio")
    import torch
    from vocos import Vocos

    if _VOCOS is None:
        try:
            from huggingface_hub import snapshot_download

            local = snapshot_download(VOCOS_REPO, local_files_only=True)
            _VOCOS = Vocos.from_hparams(f"{local}/config.yaml")
            state = torch.load(f"{local}/pytorch_model.bin", map_location="cpu", weights_only=True)
            _VOCOS.load_state_dict(state)
        except Exception:
            _VOCOS = Vocos.from_pretrained(VOCOS_REPO)  # first run: downloads once
        _VOCOS.eval()
    with torch.inference_mode():
        x = torch.from_numpy(np.asarray(wav, dtype=np.float32)).unsqueeze(0)
        y = _VOCOS.decode(_VOCOS.feature_extractor(x))
    return y.squeeze().float().numpy()[: len(wav)].astype(np.float32)


def silence(ms: int, sr: int) -> Audio:
    return np.zeros(int(sr * ms / 1000), dtype=np.float32)


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def pitch_tempo(wav: Audio, sr: int, semitones: float, tempo: float,
                method: str = "resample", post_filter: str = "") -> Audio:
    """Shift pitch (semitones) and change tempo (1.0 = unchanged) with ffmpeg.

    method="rubberband" uses ffmpeg's rubberband filter (formant-preserving, fewer clicks);
    "resample" uses asetrate+atempo. `post_filter` is an extra ffmpeg filter chain.
    """
    if semitones == 0 and tempo == 1.0 and not post_filter:
        return wav
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not on PATH; it is required for pitch/tempo processing")
    ratio = 2 ** (semitones / 12)
    if semitones == 0 and tempo == 1.0:
        # Only filtering requested: never pass audio through a time/pitch stretcher for nothing
        # (a no-op phase-vocoder pass still adds a "robotic" colour).
        return _run_ffmpeg(ffmpeg, wav, sr, [post_filter])
    if method in ("rubberband", "rubberband_shifted"):
        # "rubberband_shifted" moves formants with the pitch: a younger/brighter timbre.
        formant = "shifted" if method == "rubberband_shifted" else "preserved"
        filters = [f"rubberband=pitch={ratio:.5f}:tempo={tempo:.5f}:formant={formant}:pitchq=quality"]
        if post_filter:
            filters.append(post_filter)
        return _run_ffmpeg(ffmpeg, wav, sr, filters)
    atempo = tempo / ratio  # asetrate shifts pitch and speed; atempo restores speed then applies tempo
    filters = [f"asetrate={sr * ratio:.0f}", f"aresample={sr}"]
    # ffmpeg's atempo accepts 0.5..2.0 per stage; chain stages for larger changes.
    while atempo > 2.0:
        filters.append("atempo=2.0")
        atempo /= 2.0
    while atempo < 0.5:
        filters.append("atempo=0.5")
        atempo /= 0.5
    filters.append(f"atempo={atempo:.5f}")
    if post_filter:
        filters.append(post_filter)
    return _run_ffmpeg(ffmpeg, wav, sr, filters)


def _run_ffmpeg(ffmpeg: str, wav: Audio, sr: int, filters: list[str]) -> Audio:
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        sf.write(src, wav, sr, subtype="FLOAT")
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-af", ",".join(filters), str(dst)],
            check=True,
        )
        out, _ = sf.read(dst, dtype="float32")
    return out.astype(np.float32)
