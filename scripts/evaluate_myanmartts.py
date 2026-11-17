"""Generate Burmese evaluation clips with the MyanmarTTS candidate (CPU, offline).

Run after models/myanmartts is populated (see docs/burmese-tts-handoff.md):
    .venv-myanmartts\\Scripts\\python.exe scripts\\evaluate_myanmartts.py --output-dir outputs/myanmartts-r1

Each output directory must be new; existing audio is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import random

from pathlib import Path

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "myanmartts"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--reference", type=Path, default=MODEL_DIR / "samples" / "sample_0.wav")
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--cfg", type=float, default=3.0)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--text-file", type=Path, help="UTF-8 text to synthesize as one clip (id: custom)")
    args = parser.parse_args()

    if args.output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing directory: {args.output_dir}")

    import myanmar_tts.api as mtts_api
    import torchaudio
    from myanmar_tts.text.burmese import burmese_to_ipa2

    def _load_reference(path: str, target_sr: int) -> torch.Tensor:
        # torchcodec is not installed; soundfile + torchaudio give the same mono (1, T) tensor.
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        wav = torch.from_numpy(data.mean(axis=1)).unsqueeze(0)
        if sr != target_sr:
            wav = torchaudio.functional.resample(wav, sr, target_sr)
        return wav

    mtts_api.load_and_resample_audio = _load_reference
    StableTTSAPI = mtts_api.StableTTSAPI

    cases = json.loads((ROOT / "evaluation" / "burmese-baseline.json").read_text(encoding="utf-8"))
    cases = [c for c in cases if c["expected"] == "generate"]
    if args.text_file:
        text = " ".join(args.text_file.read_text(encoding="utf-8").split())
        cases = [{"id": "custom", "text": text, "expected": "generate"}]

    torch.set_num_threads(4)
    model = StableTTSAPI(str(MODEL_DIR / "model_fp16.pt"), str(MODEL_DIR / "vocos.pt"), "vocos")
    model.g2p_mapping["burmese"] = burmese_to_ipa2
    model.eval()

    args.output_dir.mkdir(parents=True)
    report = {"model": "freococo/MyanmarTTS", "reference": str(args.reference.name),
              "steps": args.steps, "cfg": args.cfg, "length_scale": args.length_scale,
              "seed": args.seed, "device": "cpu", "clips": []}

    for case in cases:
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        audio, _ = model.inference(case["text"], str(args.reference), "burmese",
                                   step=args.steps, length_scale=args.length_scale,
                                   solver="dopri5", cfg=args.cfg)
        wav = audio.squeeze().float().cpu().numpy()
        out = args.output_dir / f"{case['id']}.wav"
        sf.write(out, wav, 44100, subtype="FLOAT")
        finite = bool(np.isfinite(wav).all())
        peak = float(np.max(np.abs(wav))) if wav.size else 0.0
        report["clips"].append({"id": case["id"], "text": case["text"],
                                "duration_s": round(len(wav) / 44100, 3),
                                "finite": finite, "peak": round(peak, 4),
                                "silent": peak < 1e-3})
        print(f"{case['id']}: {len(wav)/44100:.2f}s peak={peak:.3f} finite={finite}")

    (args.output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
