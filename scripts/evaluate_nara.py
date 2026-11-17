"""Generate Burmese speech with Nara Mini v1 (Kokoro-based ONNX, Apache-2.0), offline on CPU.

Mirrors the official Space pipeline (models/nara-space/app.py) without Gradio.

    .venv-nara\\Scripts\\python.exe scripts\\evaluate_nara.py --text-file outputs/passage.txt --output-dir outputs/nara-passage-1
    .venv-nara\\Scripts\\python.exe scripts\\evaluate_nara.py --baseline --output-dir outputs/nara-baseline-1

Each output directory must be new; existing audio is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "nara-mini-v1"
FRONTEND_DIR = ROOT / "third_party" / "nara_mini_v1"  # our refined fork of the upstream frontend
sys.path.insert(0, str(FRONTEND_DIR))

from frontend.english import to_tokens  # noqa: E402
from frontend.my_numbers import verbalize  # noqa: E402
from frontend.nara_frontend import phonemize, prepare_names  # noqa: E402
VOICES = ["shoon", "thazin", "ko-banyar", "htet-myat"]
SAMPLE_RATE = 24000
PIECE_GAP = 4800  # 0.2 s between pieces, as in the official app
PIECE_LIMIT = 200  # max characters per synthesized piece (official app: 200)
STYLE_OFFSET = 0  # shift the style-vector index chosen by length (experiment knob)


def split_speech(text: str, limit: int = 200) -> list[str]:
    units = []
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
    pieces, current = [], ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > limit:
            pieces.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        pieces.append(current)
    return pieces


def load_voice(voice: str) -> dict:
    base = MODEL_DIR / "onnx" / voice
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    enc = ort.InferenceSession(str(base / "encoder.onnx"), options, providers=["CPUExecutionProvider"])
    dec = ort.InferenceSession(str(base / "decoder.onnx"), options, providers=["CPUExecutionProvider"])
    meta = json.loads((base / "voice.json").read_text(encoding="utf-8"))
    return {"encoder": enc, "decoder": dec, "meta": meta}


def synthesize_piece(vd: dict, chars: str, speed: float = 1.0) -> np.ndarray:
    meta = vd["meta"]
    tokens = [meta["vocab"][c] for c in chars if c in meta["vocab"]]
    if not tokens or len(tokens) > 508:
        raise ValueError(f"unsupported piece length/content: {len(tokens)} tokens")
    index = int(np.argmin(np.abs(np.asarray(meta["centers"]) - len(tokens))))
    index = int(np.clip(index + STYLE_OFFSET, 0, len(meta["styles"]) - 1))
    style = np.asarray([meta["styles"][index]], dtype=np.float32)
    durations, prosody, encoded = vd["encoder"].run(
        ["durations", "prosody", "text"],
        {"tokens": np.asarray([[0, *tokens, 0]], dtype=np.int64), "style": style},
    )
    if durations.min() < 1 or not 1 <= durations.sum() <= 20000:
        raise ValueError("invalid predicted duration")
    if speed != 1.0:
        # Kokoro-style models control speed through predicted durations: scale frames by 1/speed.
        durations = np.maximum(1, np.round(durations / speed)).astype(np.int64)
    samples = vd["decoder"].run(
        None,
        {
            "prosody": np.repeat(prosody, durations[0], axis=2),
            "text": np.repeat(encoded, durations[0], axis=2),
            "style": style,
        },
    )[0].reshape(-1)
    if samples.size < 2400 or not np.isfinite(samples).all():
        raise ValueError("invalid audio")
    return np.clip(samples, -1, 1).astype(np.float32)


PITCH_SEMITONES = 0.0  # DSP pitch shift after synthesis
TEMPO = 1.0  # DSP tempo after synthesis (<1 slower)
LOWPASS_HZ = 0.0  # 0 = off; soft low-pass to tame high-frequency vocoder fizz


def soft_lowpass(wav: np.ndarray, cutoff: float, sr: int = SAMPLE_RATE, width: float = 1500.0) -> np.ndarray:
    """Zero-phase FFT low-pass with a cosine roll-off from cutoff-width/2 to cutoff+width/2."""
    spec = np.fft.rfft(wav)
    freqs = np.fft.rfftfreq(wav.size, 1 / sr)
    lo, hi = cutoff - width / 2, cutoff + width / 2
    gain = np.ones_like(freqs)
    band = (freqs > lo) & (freqs < hi)
    gain[band] = 0.5 * (1 + np.cos(np.pi * (freqs[band] - lo) / (hi - lo)))
    gain[freqs >= hi] = 0.0
    return np.fft.irfft(spec * gain, n=wav.size).astype(np.float32)


def pitch_tempo_dsp(wav: np.ndarray, semitones: float, tempo: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Pitch shift (semitones) and tempo change (1.0 = same) via ffmpeg. DSP, not native synthesis."""
    if semitones == 0 and tempo == 1.0:
        return wav
    import shutil
    import subprocess
    import tempfile
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found on PATH; required for pitch/tempo DSP")
    ratio = 2 ** (semitones / 12)
    atempo = tempo / ratio  # asetrate changes both pitch and speed; atempo restores speed, then applies tempo
    chain = f"asetrate={sr * ratio:.0f},aresample={sr},atempo={atempo:.4f}"
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        sf.write(src, wav, sr, subtype="FLOAT")
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-af", chain, str(dst)], check=True)
        out, _ = sf.read(dst, dtype="float32")
    return out


def edge_fade(wav: np.ndarray, ms: float = 8.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    n = min(int(sr * ms / 1000), wav.size // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        wav = wav.copy()
        wav[:n] *= ramp
        wav[-n:] *= ramp[::-1]
    return wav


def loudness_normalize(wav: np.ndarray, target_peak: float = 0.89) -> np.ndarray:
    peak = float(np.abs(wav).max())
    return wav * (target_peak / peak) if peak > 0 else wav


def generate(text: str, vd: dict, normalize_numbers: bool, speed: float = 1.0) -> np.ndarray:
    if normalize_numbers:
        text = verbalize(text)
    chunks, has_audio = [], False
    for piece in split_speech(text, PIECE_LIMIT):
        chars = phonemize(to_tokens(prepare_names(piece)))
        samples = edge_fade(synthesize_piece(vd, chars, speed))
        if has_audio:
            chunks.append(np.zeros(PIECE_GAP, dtype=np.float32))
        chunks.append(samples)
        has_audio = True
    wav = np.concatenate(chunks)
    if LOWPASS_HZ > 0:
        wav = soft_lowpass(wav, LOWPASS_HZ)
    wav = pitch_tempo_dsp(wav, PITCH_SEMITONES, TEMPO)
    return loudness_normalize(wav)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--text-file", type=Path, help="UTF-8 text file")
    parser.add_argument("--script-table", type=Path, help="markdown table rows '| rNNN | text |'")
    parser.add_argument("--baseline", action="store_true", help="use evaluation/burmese-baseline.json")
    parser.add_argument("--voices", nargs="+", default=VOICES, choices=VOICES)
    parser.add_argument("--no-number-normalize", action="store_true")
    parser.add_argument("--piece-limit", type=int, default=200, help="max chars per piece (default 200)")
    parser.add_argument("--style-offset", type=int, default=0, help="shift style index (experiment)")
    parser.add_argument("--preset", help="name in config/voice_presets.json (sets voice and DSP)")
    parser.add_argument("--pitch", type=float, default=0.0, help="DSP pitch shift in semitones")
    parser.add_argument("--tempo", type=float, default=1.0, help="DSP tempo (<1 slower)")
    parser.add_argument("--lowpass", type=float, default=0.0, help="soft low-pass cutoff Hz (0=off), e.g. 8000")
    parser.add_argument("--speed", type=float, default=1.0, help="<1 slower, >1 faster (duration scaling)")
    args = parser.parse_args()
    global PIECE_LIMIT, STYLE_OFFSET, LOWPASS_HZ, PITCH_SEMITONES, TEMPO, PIECE_GAP
    LOWPASS_HZ, PITCH_SEMITONES, TEMPO = args.lowpass, args.pitch, args.tempo
    if args.preset:
        preset = json.loads((ROOT / "config" / "voice_presets.json").read_text(encoding="utf-8"))["presets"][args.preset]
        args.voices = [preset["voice"]]
        args.style_offset = preset.get("style_offset", 0)
        LOWPASS_HZ = preset.get("lowpass_hz", 0)
        PITCH_SEMITONES = preset.get("pitch_semitones", 0)
        TEMPO = preset.get("tempo", 1.0)
        PIECE_GAP = int(SAMPLE_RATE * preset.get("sentence_gap_s", 0.2))
    PIECE_LIMIT, STYLE_OFFSET = args.piece_limit, args.style_offset

    if args.output_dir.exists():
        raise SystemExit(f"Refusing to overwrite: {args.output_dir}")

    if args.baseline:
        cases = [c for c in json.loads((ROOT / "evaluation" / "burmese-baseline.json").read_text(encoding="utf-8"))
                 if c["expected"] == "generate"]
    elif args.script_table:
        import re as _re
        rows = _re.findall(r"^\| (r\d{3}) \| (.+?) \|$", args.script_table.read_text(encoding="utf-8"), _re.M)
        cases = [{"id": i, "text": t} for i, t in rows]
    elif args.text_file:
        cases = [{"id": "custom", "text": " ".join(args.text_file.read_text(encoding="utf-8").split())}]
    else:
        raise SystemExit("Provide --text-file, --baseline or --script-table")

    args.output_dir.mkdir(parents=True)
    report = {"model": "YeeNyunn/nara-mini-v1", "license": "Apache-2.0", "sample_rate": SAMPLE_RATE,
              "device": "cpu", "clips": []}
    for voice in args.voices:
        vd = load_voice(voice)
        for case in cases:
            wav = generate(case["text"], vd, not args.no_number_normalize, args.speed)
            peak = float(np.abs(wav).max())
            name = f"{case['id']}__{voice}.wav"
            sf.write(args.output_dir / name, wav, SAMPLE_RATE, subtype="FLOAT")
            report["clips"].append({"file": name, "text": case["text"], "duration_s": round(len(wav) / SAMPLE_RATE, 3),
                                    "peak": round(peak, 4)})
            print(f"{name}: {len(wav)/SAMPLE_RATE:.2f}s peak={peak:.3f}")
    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
