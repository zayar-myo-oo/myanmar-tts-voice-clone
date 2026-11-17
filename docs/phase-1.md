# Phase 1 — select the first evaluation model

## Decision and scope

Select `facebook/mms-tts-mya` for the **personal, noncommercial neutral baseline**.
This is not selection of the final commercial/expressive product model. It has a
documented Transformers inference API and a separate fine-tuning implementation,
without requiring an unverified reference recording or custom remote Python code.
The application remains model-adapter based so that this checkpoint can be replaced.

Objective: establish a pinned, inspectable candidate before local audio evaluation.
Tools: Python 3.11, PyTorch, Transformers, Hugging Face Hub, SHA-256.

## Evidence checked

The pinned upstream config has one speaker, no speaker embedding and 16 kHz output.
Tokenizer uses Burmese characters directly (`is_uroman=false`, `phonemize=false`).
Its 57-symbol vocabulary lacks numeric digits and Latin letters. Punctuation and
unsupported characters need explicit handling, not silent tokenizer filtering.
No emotion, cloning, whisper, shout or pitch API is available in this checkpoint.
Speaking rate exists in VITS, but is not claimed as validated until tested.

Safetensors weights contain 36,288,240 parameters; the selected weight file is
145,242,104 bytes. SHA-256 is pinned in `config/mms-baseline.json`. Inference uses
`VitsModel` and `VitsTokenizer`, `local_files_only=True`, `trust_remote_code=False`
and safetensors. No pickle weight file or upstream Python execution is necessary.

CC-BY-NC-4.0 is a noncommercial model license, not an unrestricted open-source
weight license. Keep model attribution, license URL and revision with results.
Do not bundle these weights into an unrestricted commercial release. The app's MIT
license covers our code only. Fine-tuned MMS derivatives retain model restrictions.

MyanmarTTS remains an alternative: small weights and claimed CC0 licensing, but
reference conditioning, dataset provenance and an exact matching fine-tuning recipe
need further verification. OmniVoice remains a later cloning experiment with its
own environment and noncommercial weight restrictions. XTTS-v2 lacks documented
native Burmese support. See the preliminary comparison for the full matrix.

## Fine-tuning and platforms

`ylacombe/finetune-hf-vits` supplies an MMS training path. Unlike inference, it needs
a discriminator conversion and compiled Cython alignment. Its broad requirements
are not a tested lock. Phase 7 must use an isolated training environment, check
Burmese conversion artifacts, permissioned data and measure a training step on 8 GB.
No promise is made that upstream speed/memory results transfer to this PC.

CPU/CUDA are the first evaluation devices. PyTorch worked in Phase 0; model inference
is a Phase 2 gate. Windows is our local test target. macOS CPU/MPS and Intel wheel
availability remain untested; a generic PyTorch API is not platform certification.

## Exact commands and files

```powershell
python -m uv pip install --python .venv/Scripts/python.exe -e '.[dev,inference]'
.venv\Scripts\python.exe -c "from transformers import VitsModel, VitsTokenizer; print('VITS imports OK')"
.venv\Scripts\python.exe scripts/prepare_mms.py
```

`config/mms-baseline.json` is the reproducibility manifest; `scripts/prepare_mms.py`
downloads only the required files at the fixed commit, validates the weight hash
and checks model/tokenizer configuration. `models/` is ignored by Git.
The inference dependency versions are pinned separately from the future training
framework. The preparation command requires network access; inference must not.

## Verification and common errors

The VITS classes import in the existing CUDA environment. The model config,
vocabulary, exact commit, weight size and upstream SHA-256 were inspected.
Selection gate: PASS for the stated evaluation scope. Next: download/check the
actual artifact and run CPU/CUDA inference; native-speaker listening is necessary
before Phase 2 can pass. No naturalness claim follows from selection alone.

Download error: rerun setup while online. Hash mismatch: stop; inspect the pinned
source and download integrity, never bypass the comparison. No matching wheel:
use Python 3.11. Unsupported text: write numbers and English words in Myanmar
pronunciation manually for now; automatic normalization is future work.

## Sources checked 2026-11-17

- [Pinned model repository](https://huggingface.co/facebook/mms-tts-mya/tree/052c6e19334199051a5353c73e7e0b8085490749)
- [VITS implementation at v4.57.1](https://github.com/huggingface/transformers/tree/v4.57.1/src/transformers/models/vits)
- [MMS fine-tuning implementation](https://github.com/ylacombe/finetune-hf-vits)
- [Weight license](https://creativecommons.org/licenses/by-nc/4.0/)
