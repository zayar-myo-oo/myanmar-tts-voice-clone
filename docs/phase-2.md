# Phase 2 — local Burmese speech evaluation

## Objective and current status

Generate actual Burmese speech from the pinned MMS baseline and verify CPU, CUDA,
offline operation, output integrity and text handling. **Automated checks passed;
pronunciation and naturalness are awaiting native-speaker review.** Phase 2 is not
complete and Phase 3 has not begun.

This is a sentence-sized evaluation harness, not the shared production engine.
The same model runs on CPU or CUDA, with device selection explicit. Network socket
connections are blocked during evaluation, in addition to Hugging Face offline
flags and local-only loading. Downloading is a separate setup command.

## Tools, files and exact commands

Tools: the Phase 0 Python/PyTorch environment, pinned Transformers dependencies,
Hugging Face Hub for setup only, NumPy, SoundFile, pytest.

```powershell
python -m uv pip install --python .venv/Scripts/python.exe -e '.[dev,inference]'
.venv\Scripts\python.exe scripts/prepare_mms.py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/evaluate_mms.py --device cuda --output-dir outputs/my-cuda-review
.venv\Scripts\python.exe scripts/evaluate_mms.py --device cpu --output-dir outputs/my-cpu-review
```

Every output directory must be new; existing audio is never overwritten. Use another
name on subsequent runs. No reference recording, account, paid API, cloud inference
or external speech service is required. The model remains CC-BY-NC-4.0.

```text
config/mms-baseline.json             Model revision, hash, license and limits
scripts/prepare_mms.py               Explicit online setup and integrity check
scripts/evaluate_mms.py              Offline benchmark and WAV generation
src/myanmar_voice_studio/evaluation.py Text validation and signal measurements
evaluation/burmese-baseline.json     Four speech samples and two rejection cases
tests/test_evaluation.py             Text-loss and waveform validation checks
outputs/mms-baseline-{cpu,cuda}/      WAVs and detailed report.json (Git-ignored)
requirements-windows-phase2.txt      Installed Windows CUDA dependency snapshot
```

The manifest pins upstream revision `052c6e19334199051a5353c73e7e0b8085490749`.
The actual downloaded safetensors SHA-256 matched the upstream hash. Inference
also verifies it before loading. Only data and safetensors are loaded from the
model repository; remote Python and pickle weights are not used.

## How text is handled

Unicode NFC normalization preserves Burmese combining marks. Known vocabulary
symbols are preserved. Other punctuation becomes spaces with a warning, so these
samples do not prove punctuation-driven pauses. Unsupported digits, Latin text,
emoji and unknown characters cause clear rejection. Numbers written in Burmese
words are accepted. This avoids treating silently omitted text as valid speech.
Zawgyi conversion and a complete Burmese number/pronunciation normalizer are not
implemented. Inputs are limited to 400 characters for these experiments.

## Observed results on 2026-11-17

Windows 11, RTX 3070 Ti 8 GB, Python 3.11.18, torch 2.7.1+cu128, Transformers 4.57.1,
four CPU threads, seed 42, batch size one, float32. Each row is one measurement,
not a statistical performance benchmark. Timing excludes model loading, text
tokenization and file writing; includes synchronization and waveform transfer.

| Sample | CUDA audio duration | CUDA inference | CPU inference |
|---|---:|---:|---:|
| Greeting | 3.152 s | 0.428 s | 0.48 s |
| Narration | 6.112 s | 0.090 s | 0.78 s |
| Question | 4.128 s | 0.184 s | 0.53 s |
| Numbers as words | 6.528 s | 0.061 s | 0.83 s |

Peak torch CUDA allocation across these clips was about 227.3 MiB; peak torch
reserved memory was 282 MiB. These exclude driver/context allocations and other
applications and **do not estimate fine-tuning memory**. The first sample includes
kernel warm-up effects. Same seed does not guarantee identical CPU/GPU audio;
the narration duration was 6.128 s on CPU versus 6.112 s on CUDA.

All eight waveforms were finite, non-silent, unclipped, and round-tripped through
float WAV without sample changes. Float WAV intentionally preserves the original
signal; no loudness normalization was applied. Each device rejected the two
unsupported-input cases. Thirteen tests passed; all 36 installed packages passed
`uv pip check`. Small signal checks do not measure pronunciation or speech quality.

## Listening review and completion criteria

Listen to all four CUDA files and compare the spoken words with the original text
in `evaluation/burmese-baseline.json`. Check the CPU versions too if output differs.
For each clip record:

1. Any missing, repeated or incorrectly pronounced words, with the exact word.
2. Whether the speech is understandable (yes/no).
3. Naturalness from 1 (very robotic) to 5 (natural).
4. Unwanted noise, abrupt cutoffs, or unsuitable pacing.

Phase 2 passes only after the listener confirms the neutral baseline is usable,
or issues are resolved and the affected clips are regenerated. A failing baseline
requires investigating text preprocessing or evaluating another model. Do not mark
emotion, whisper, shout, cloning or the four target identities as supported.

## Common errors

- Missing local files: run preparation online once, then rerun evaluation offline.
- Existing output directory: choose a new directory to protect previous results.
- Unsupported characters: spell out the words in Burmese; do not delete content.
- CUDA unavailable: repair the CUDA installation or explicitly select CPU.
- Quiet speech: use playback volume for listening; evaluation preserves model output.
- `signal_check_passed` is false: inspect the failed waveform/report before proceeding.
- Dependency conflicts: restore the pinned environment snapshot; training dependencies
  belong in a separate environment, not this inference environment.

Source reference: [MMS model and license](https://huggingface.co/facebook/mms-tts-mya).
