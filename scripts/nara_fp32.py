"""Run Nara Mini v1 with its full-precision PyTorch weights (Kokoro architecture).

The published ONNX decoder is INT8-quantized; this script tests whether the fp32 decoder
removes the background fizz/buzz. Uses the refined text frontend (third_party/nara_mini_v1).

    .venv-f5\\Scripts\\python.exe scripts\\nara_fp32.py --voice htet-myat --text-file outputs/passage.txt --out outputs/fp32
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from safetensors.torch import load_file

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "nara-mini-v1"
sys.path.insert(0, str(ROOT / "third_party" / "nara_mini_v1"))
sys.path.insert(0, str(ROOT / "src"))

from frontend.english import to_tokens  # noqa: E402
from frontend.my_numbers import verbalize  # noqa: E402
from frontend.nara_frontend import phonemize, prepare_names  # noqa: E402

from myanmar_voice_studio.engine.adapters.nara import split_speech  # noqa: E402

SR = 24000


def load_model(voice: str, device: str):
    from kokoro import KModel

    meta = json.loads((MODEL / "onnx" / voice / "voice.json").read_text(encoding="utf-8"))
    cfg = json.loads((MODEL / "config.json").read_text(encoding="utf-8"))
    dec = {k: v for k, v in cfg["decoder"].items() if k != "type"}
    kcfg = {**cfg, "vocab": meta["vocab"], "plbert": {k: v for k, v in cfg["bert"].items() if k != "vocab_size"}, "istftnet": dec, "text_encoder_kernel_size": 5}
    grouped: dict[str, dict] = defaultdict(dict)
    for key, tensor in load_file(str(MODEL / "weights" / voice / "model.safetensors")).items():
        module, rest = key.split(".", 1)
        # Newer torch weight-norm names -> the legacy names Kokoro's modules use.
        rest = rest.replace("parametrizations.weight.original0", "weight_g")
        rest = rest.replace("parametrizations.weight.original1", "weight_v")
        grouped[module][rest] = tensor
    with tempfile.TemporaryDirectory() as tmp:
        pth = Path(tmp) / "model.pth"
        torch.save(dict(grouped), pth)
        model = KModel(repo_id="hexgrad/Kokoro-82M", config=kcfg, model=str(pth))
    return model.to(device).eval(), meta


@torch.inference_mode()
def synth(model, meta, text: str, device: str, gap_s: float = 0.28) -> np.ndarray:
    chunks = []
    for piece in split_speech(verbalize(text)):
        chars = phonemize(to_tokens(prepare_names(piece)))
        tokens = [meta["vocab"][c] for c in chars if c in meta["vocab"]]
        idx = int(np.argmin(np.abs(np.asarray(meta["centers"]) - len(tokens))))
        ref_s = torch.tensor([meta["styles"][idx]], dtype=torch.float32, device=device)
        ids = torch.tensor([[0, *tokens, 0]], dtype=torch.long, device=device)
        audio, _ = model.forward_with_tokens(ids, ref_s)
        if chunks:
            chunks.append(np.zeros(int(SR * gap_s), dtype=np.float32))
        chunks.append(audio.float().cpu().numpy())
    return np.concatenate(chunks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="htet-myat")
    ap.add_argument("--text-file", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    model, meta = load_model(args.voice, args.device)
    text = " ".join(args.text_file.read_text(encoding="utf-8").split())
    wav = synth(model, meta, text, args.device)
    dest = args.out / f"{args.voice}_fp32.wav"
    sf.write(dest, wav, SR, subtype="FLOAT")
    print(dest, f"{wav.size / SR:.2f}s", f"peak={np.abs(wav).max():.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
