"""Offline environment checks; never downloads or loads a speech model."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class Check(BaseModel):
    name: str
    passed: bool
    detail: str
    required: bool = True


class Report(BaseModel):
    timestamp: str
    platform: str
    checks: list[Check] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.required)


def command_check(name: str, args: list[str], required: bool = True) -> Check:
    executable = shutil.which(name)
    if executable is None:
        return Check(name=name, passed=False, detail="Not on PATH", required=required)
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True,
                                errors="replace", timeout=20, check=False)
        detail = (result.stdout + result.stderr).strip().splitlines()
        return Check(name=name, passed=result.returncode == 0,
                     detail=detail[0] if detail else f"Exit {result.returncode}", required=required)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check(name=name, passed=False, detail=str(exc), required=required)


def inspect_environment(require_cuda: bool = False) -> Report:
    report = Report(timestamp=datetime.now(timezone.utc).isoformat(), platform=platform.platform())
    report.checks.append(Check(name="python", passed=sys.version_info[:2] == (3, 11),
                               detail=sys.version.split()[0]))
    for name, args, required in [
        ("git", ["--version"], True), ("ffmpeg", ["-version"], True),
        ("node", ["--version"], False), ("rustc", ["--version"], False),
        ("cargo", ["--version"], False),
    ]:
        report.checks.append(command_check(name, args, required))
    try:
        import numpy as np
        import soundfile as sf
        with tempfile.TemporaryDirectory(prefix="mvs-doctor-") as directory:
            path = Path(directory) / "မြန်မာ.wav"
            samples = np.zeros(1600, dtype=np.float32)
            sf.write(path, samples, 16000, subtype="PCM_16")
            audio, rate = sf.read(path)
            ok = rate == 16000 and len(audio) == len(samples) and np.isfinite(audio).all()
        report.checks.append(Check(name="audio_unicode_roundtrip", passed=bool(ok),
                                   detail=f"SoundFile {importlib.metadata.version('soundfile')}; 16 kHz PCM WAV"))
    except Exception as exc:
        report.checks.append(Check(name="audio_unicode_roundtrip", passed=False, detail=str(exc)))
    try:
        import torch
        cpu = torch.tensor([[1., 2.], [3., 4.]])
        expected = torch.tensor([[7., 10.], [15., 22.]])
        report.checks.append(Check(name="torch_cpu", passed=bool(torch.equal(cpu @ cpu, expected)),
                                   detail=torch.__version__))
        available = torch.cuda.is_available()
        if available:
            gpu = cpu.to("cuda")
            ok = bool(torch.allclose((gpu @ gpu).cpu(), expected))
            torch.cuda.synchronize()
            props = torch.cuda.get_device_properties(0)
            detail = f"{props.name}; {props.total_memory / 1024**3:.1f} GiB; torch CUDA {torch.version.cuda}"
        else:
            ok, detail = False, "CUDA unavailable; CPU fallback only"
        report.checks.append(Check(name="torch_cuda", passed=ok, detail=detail, required=require_cuda))
    except Exception as exc:
        report.checks.append(Check(name="torch", passed=False, detail=str(exc)))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-cuda", action="store_true")
    parser.add_argument("--output", type=Path, help="New JSON report path; existing files are never overwritten")
    args = parser.parse_args()
    report = inspect_environment(args.require_cuda)
    payload = report.model_dump() | {"passed": report.passed}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
