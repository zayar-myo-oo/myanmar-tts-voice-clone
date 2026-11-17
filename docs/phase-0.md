# Phase 0 — establish a working ML environment

## Objective and tools

Verify the actual PC and build a small, isolated environment before downloading a
speech model. Python runs the engine; PyTorch performs tensor calculations on CPU
or GPU; SoundFile reads/writes audio; FFmpeg will handle later audio exports.
Git tracks source. The desktop toolchain is inventoried here and installed in
Phase 6, so it cannot delay the initial speech feasibility test.

Use PowerShell from the project root. Activation is optional: explicit interpreter
paths below avoid PowerShell execution-policy issues and accidental system installs.

## Reproduce the setup

```powershell
python -m pip install uv==0.13.8
python -m uv python install 3.11
python -m uv venv --python 3.11 .venv
python -m uv pip install --python .venv/Scripts/python.exe torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128
python -m uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m myanmar_voice_studio.doctor --require-cuda --output reports/environment.json
```

Run venv creation only for a new environment. The report refuses overwrites; use a
new report filename on subsequent runs. Installation requires internet; diagnostics
run offline. uv installs a standalone Python without replacing system Python.

The PyTorch pin is a provisional environment baseline, not a final model dependency
decision. Phase 1 must reconcile the selected adapter's requirements, audit versions,
and update the lock before inference. CUDA wheels are large (roughly 3 GiB here).
The CUDA version in `nvidia-smi` is driver capability, not proof PyTorch works; the
doctor actually calculates on the GPU. A separate CUDA toolkit is unnecessary for
this prebuilt wheel check.

For CPU-only Windows, use the same torch pin with the official `.../whl/cpu` index
instead and omit `--require-cuda`. macOS is not verified on this Windows machine;
do not use a CUDA wheel there. Platform-specific pinned environments follow model
selection and testing on real hardware.

## Source and verification

`src/myanmar_voice_studio/doctor.py` contains typed diagnostic results and the CLI.
`tests/test_doctor.py` checks that required failures block the gate and optional
desktop tools do not, and that missing executables produce useful results.
The real diagnostic is an integration check: CPU matrix multiplication, CUDA matrix
multiplication, finite PCM WAV data and Unicode filename roundtrip.

Completion criteria for the Phase 0 ML gate: Python 3.11, Git, FFmpeg, CPU calculation,
audio roundtrip, and CUDA calculation on this NVIDIA PC all pass; tests pass.
Rust/MSVC and desktop compilation are a separate mandatory gate before Phase 6.
No model pronunciation, training memory or macOS behavior is certified by this check.

## Observed hardware inventory

On 2026-11-17: Windows 11 Home, Intel Core i7-14700F, approximately 31.8 GiB usable
RAM, NVIDIA RTX 3070 Ti with 8192 MiB VRAM; driver 621.01. About 660 GiB disk was
free at inspection. System Python was 3.15.2; the isolated environment is 3.11.18.
Git 2.55.0, Node 26.13.0 and FFmpeg were found. WebView2 157.0.4341.46 was present.
Rust/Cargo were not found; the VS installer query did not find MSVC C++ tools.
Node/Vite compatibility must be verified when the frontend dependencies are selected.

## Common errors

- No matching wheel: use the project Python 3.11 executable, not system Python 3.15.
- CUDA unavailable: verify the NVIDIA driver and wheel index; rerun with
  `--require-cuda`. A detected GPU alone does not mean CUDA computation works.
- FFmpeg missing: install FFmpeg, reopen the terminal and verify `ffmpeg -version`.
- Import error: run the editable install using the explicit `.venv` interpreter.
- Existing report: choose another output filename; reports never overwrite files.
- CUDA out of memory later: close GPU workloads, shorten segments, reduce batch
  size; measure adapter peak memory before selecting a training strategy.

## Official references

- [uv Python installation](https://docs.astral.sh/uv/guides/install-python/)
- [PyTorch version-specific wheel commands](https://pytorch.org/get-started/previous-versions/)
- [Tauri 2 prerequisites](https://v2.tauri.app/start/prerequisites/)

Next gate is Phase 1: inspect exact model/code artifacts and license obligations,
then select a candidate. Do not treat preliminary model research as completed inference.

## Verification result

The Phase 0 ML gate passed on this PC on 2026-11-17: two pytest tests passed;
CPU and CUDA calculations passed; the Unicode WAV roundtrip passed. `uv pip check`
reported all 24 installed packages compatible. Detailed local output is in
`reports/environment.json` (ignored by Git). Python's platform string reports the
Windows NT 10 kernel; the Windows product inventory identifies Windows 11 Home.

`requirements-windows-phase0.txt` records the installed package versions. It is a
Windows CUDA environment snapshot, not a portable or hash-verified release lock.
To reproduce it in a fresh Python 3.11 environment:

```powershell
python -m uv pip install --python .venv/Scripts/python.exe -r requirements-windows-phase0.txt --extra-index-url https://download.pytorch.org/whl/cu128
python -m uv pip install --python .venv/Scripts/python.exe --no-deps -e .
```

Desktop build readiness remains incomplete until Rust, MSVC and a Tauri build are
verified. No model downloads, inference, training or publishing occurred in Phase 0.
