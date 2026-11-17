"""Offline CPU/CUDA baseline evaluation; human pronunciation review remains required."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import time

# No inference-time network access. This guard also catches accidental dependency requests.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def deny_network(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Network disabled during offline evaluation; run prepare_mms.py first")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

import numpy as np
import soundfile as sf
import torch
from transformers import VitsModel, VitsTokenizer

from myanmar_voice_studio.evaluation import audio_metrics, prepare_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("config/mms-baseline.json"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/mms-tts-mya"))
    parser.add_argument("--corpus", type=Path, default=Path("evaluation/burmese-baseline.json"))
    parser.add_argument("--output-dir", type=Path, required=True, help="Must not exist")
    parser.add_argument("--device", choices=["cpu", "cuda"], required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error("--threads must be positive")
    if args.device == "cuda" and not torch.cuda.is_available():
        parser.error("CUDA requested but unavailable; no silent CPU fallback")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    for item in corpus:
        if not isinstance(item["id"], str) or not item["id"].isascii() or not item["id"].replace("_", "").isalnum():
            raise ValueError("Corpus IDs must use ASCII letters, digits or underscores")
        if item["expected"] not in ("generate", "reject"):
            raise ValueError("Invalid expected result")
    if len({item["id"] for item in corpus}) != len(corpus) or not corpus:
        raise ValueError("Corpus IDs must be unique and corpus must not be empty")
    with (args.model_dir / manifest["weights_file"]).open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != manifest["weights_sha256"]:
            raise ValueError("Weight checksum mismatch")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    tokenizer = VitsTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    model = VitsModel.from_pretrained(args.model_dir, local_files_only=True,
                                     trust_remote_code=False, use_safetensors=True).to(args.device).eval()
    if args.device == "cuda":
        torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    rate = model.config.sampling_rate
    vocabulary = set(tokenizer.get_vocab())
    results: list[dict] = []
    for item in corpus:
        record = dict(item)
        try:
            prepared = prepare_text(item["text"], vocabulary)
        except ValueError as exc:
            record.update(status="rejected", error=str(exc), passed=item["expected"] == "reject")
            results.append(record)
            continue
        if item["expected"] == "reject":
            record.update(status="unexpected_accept", passed=False)
            results.append(record)
            continue
        try:
            inputs = tokenizer(prepared.spoken, return_tensors="pt").to(args.device)
            torch.manual_seed(args.seed)
            if args.device == "cuda":
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.synchronize()
            started = time.perf_counter()
            with torch.inference_mode():
                waveform = model(**inputs).waveform[0].float().cpu().numpy()
            if args.device == "cuda":
                torch.cuda.synchronize()
            seconds = time.perf_counter() - started
            metrics = audio_metrics(waveform, rate)
            filename = f"{item['id']}.wav"
            # Float WAV preserves raw peaks for inspection; no silent normalization.
            with (args.output_dir / filename).open("xb") as handle:
                sf.write(handle, waveform, rate, format="WAV", subtype="FLOAT")
            reread, reread_rate = sf.read(args.output_dir / filename, dtype="float32")
            roundtrip = reread_rate == rate and np.array_equal(reread, waveform)
            record.update(status="generated", normalized_text=prepared.spoken,
                          warnings=list(prepared.warnings), audio_file=filename, sample_rate=rate,
                          inference_seconds=seconds, real_time_factor=seconds / metrics["duration_seconds"],
                          metrics=metrics, file_roundtrip_passed=roundtrip,
                          peak_cuda_allocated_mib=torch.cuda.max_memory_allocated() / 1024**2 if args.device == "cuda" else None,
                          peak_cuda_reserved_mib=torch.cuda.max_memory_reserved() / 1024**2 if args.device == "cuda" else None,
                          passed=bool(metrics["signal_check_passed"] and roundtrip),
                          listening_review="pending")
            print(f"{item['id']}: {metrics['duration_seconds']:.2f}s audio in {seconds:.2f}s", flush=True)
        except Exception as exc:
            record.update(status="error", error=f"{type(exc).__name__}: {exc}", passed=False)
        results.append(record)
    report = {"model": manifest, "device": args.device, "seed": args.seed, "threads": args.threads,
              "offline_network_guard": True, "load_seconds": load_seconds,
              "versions": {name: importlib.metadata.version(name) for name in
                           ["torch", "transformers", "soundfile", "numpy", "safetensors", "huggingface-hub"]},
              "results": results, "automated_checks_passed": all(row["passed"] for row in results),
              "phase_2_complete": False, "remaining_gate": "Native-speaker pronunciation and naturalness review"}
    with (args.output_dir / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"Report: {args.output_dir / 'report.json'}", flush=True)
    return 0 if report["automated_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
