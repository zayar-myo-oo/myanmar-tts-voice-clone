"""Explicit network setup for the pinned noncommercial MMS evaluation model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("config/mms-baseline.json"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/mms-tts-mya"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(f"Downloading {manifest['model_id']} ({manifest['license']}) at {manifest['revision']}")
    snapshot_download(repo_id=manifest["model_id"], revision=manifest["revision"],
                      allow_patterns=manifest["files"], local_dir=args.model_dir, token=False)
    weight = args.model_dir / manifest["weights_file"]
    with weight.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != manifest["weights_sha256"] or weight.stat().st_size != manifest["weights_bytes"]:
        raise ValueError("Weight checksum/size mismatch; do not load this model")
    config = json.loads((args.model_dir / "config.json").read_text(encoding="utf-8"))
    tokenizer = json.loads((args.model_dir / "tokenizer_config.json").read_text(encoding="utf-8"))
    for key, expected in manifest["expected"].items():
        actual = tokenizer[key] if key == "is_uroman" else config[key]
        if actual != expected:
            raise ValueError(f"Unexpected {key}: {actual!r}")
    print(f"Verified SHA-256 and model configuration. Local directory: {args.model_dir.resolve()}")


if __name__ == "__main__":
    main()
