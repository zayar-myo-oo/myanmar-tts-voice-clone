# Myanmar TTS model feasibility

Preliminary research checked 2026-11-17. No model was installed, executed, or listened to in this investigation. This informs Phase 1; it does not complete model selection or Phase 2 pronunciation verification.

## Which models merit evaluation?

### Takeaway
Evaluate MMS as a conservative Burmese baseline, MyanmarTTS as a small permissively licensed candidate, and OmniVoice as a cloning candidate. Do not select XTTS-v2 for native Burmese without substantial new language adaptation.

### Cited Findings
- **MMS Burmese:** `facebook/mms-tts-mya` explicitly supplies a Burmese checkpoint and documented `VitsModel`/`AutoTokenizer` inference. Its weights use CC-BY-NC-4.0, so they do not satisfy an unrestricted commercial release. [Model card](https://huggingface.co/facebook/mms-tts-mya)
- The actual MMS configuration has one speaker, no speaker embedding, 16 kHz sampling, and `speaking_rate=1.0`. This checkpoint is not a ready-made four-voice system. [Configuration](https://huggingface.co/facebook/mms-tts-mya/resolve/main/config.json)
- **MyanmarTTS:** the publisher describes a 31M-parameter Burmese StableTTS model, about 63 MB in fp16, plus Vocos. Burmese sample texts are supplied. The publisher claims CPU and GPU inference and reference voice cloning. These are upstream claims, not local results. [Model card](https://huggingface.co/freococo/MyanmarTTS)
- MyanmarTTS's notice identifies model weights and outputs as CC0, adapted code as MIT, and the reused Vocos vocoder as MIT. Preserve upstream notices for those MIT components. [NOTICE](https://huggingface.co/freococo/MyanmarTTS/resolve/main/NOTICE)
- **OmniVoice:** its language table explicitly includes Burmese (`my`, `mya`) and lists 12.14 hours. [Language table](https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md)
- OmniVoice's model card reports 0.6B parameters, voice cloning, and voice design. Crucially, it distinguishes Apache-2.0 code from **CC-BY-NC pretrained weights**, citing training-data constraints. Do not describe the whole model package as Apache-2.0. [Model card](https://huggingface.co/k2-fsa/OmniVoice)
- **XTTS-v2 exclusion:** Burmese is absent from the published 17-language list. The card claims cloning and fine-tuning but identifies the separate Coqui Public Model License. English-language cloning capability is not evidence of Burmese support. [Model card](https://huggingface.co/coqui/XTTS-v2)

### Inferences
- Keep application source licensing separate from model licensing. Support user-installed model adapters and record weight revision, license, and notices per installation.
- Small MyanmarTTS weights make it a worthwhile memory-conscious candidate; weight size alone cannot predict peak inference or training memory.
- A preliminary ordering is MMS for a reproducible baseline, MyanmarTTS for a potentially permissive alternative, and OmniVoice for reference-based voices. Final ordering should depend on listening and dependency checks.

### Gaps
- No independently verified pronunciation, naturalness, MOS, or cloning similarity scores were established for these candidates on the user's scripts.
- MyanmarTTS training-data permission and voice consent provenance were not established by the model card's aggregate description. CC0 labeling does not itself establish underlying recording rights.
- Exact MMS checkpoint download size was not established here.

## What expression and training controls actually exist?

### Takeaway
Expose capabilities separately from desired directions. Reference conditioning, stochastic variation, and loudness changes are not proof of deliberate emotion control.

### Cited Findings
- MMS uses a stochastic duration predictor; the published inference example accepts tokenized text and returns a waveform, without emotion, whisper, shout, or reference-audio parameters. [Model card](https://huggingface.co/facebook/mms-tts-mya)
- A dedicated MMS/VITS fine-tuning implementation exists, with Cython alignment compilation and checkpoint preparation. The author notes that derived MMS checkpoints retain the noncommercial license. Treat its training-time examples as author claims, not forecasts for this GPU. [Fine-tuning repository](https://github.com/ylacombe/finetune-hf-vits)
- MyanmarTTS's checked source exposes `inference(text, ref_audio, language, step, temperature=1.0, length_scale=1.0, solver=None, cfg=3.0)`. It phonemizes Burmese and uses reference mel features. No named emotion, whisper, shout, or pitch control appears in that API. [Inference source](https://huggingface.co/freococo/MyanmarTTS/blob/main/api.py)
- OmniVoice documents reference audio and transcript conditioning, speed and duration parameters, and descriptive voice attributes. It explicitly warns that voice design was trained on Chinese and English and may be unstable in low-resource languages. [README](https://github.com/k2-fsa/OmniVoice)
- OmniVoice provides full and LoRA fine-tuning scripts, JSONL data preparation, and an SDPA configuration for broader GPU compatibility. [Training examples](https://raw.githubusercontent.com/k2-fsa/OmniVoice/master/examples/README.md)
- When reference audio and instructions conflict, OmniVoice generally follows the reference style; very short unconditioned clips may be unreliable. [Tips](https://github.com/k2-fsa/OmniVoice/blob/master/docs/tips.md)

### Inferences
- Implement pauses in the renderer as explicit inserted silence. Mark DSP speed/pitch adjustments separately from native model controls; lowering volume must never be reported as whispering.
- Start with sentence-length generations. Validate voice consistency before making phrase-level generation a default.
- Burmese emotion and whisper/shout controls should stay experimental or unsupported until blinded listening demonstrates the requested delivery reliably.

### Gaps
- No tested MyanmarTTS fine-tuning recipe matching this published checkpoint and 8 GB GPU was verified.
- No supported numeric expression-intensity or word-emphasis contract shared by these models was found.

## How realistic is local cross-platform use?

### Takeaway
Use replaceable adapters and CPU fallback. The 8 GB RTX 3070 Ti is a credible evaluation target, but no candidate's peak VRAM or throughput has been measured locally.

### Cited Findings
- OmniVoice documents NVIDIA PyTorch installation and Apple Silicon MPS inference. Providing a reference transcript avoids its optional automatic Whisper transcription path. [README](https://github.com/k2-fsa/OmniVoice)
- MyanmarTTS claims CPU and GPU execution; its small model and separate 57 MB vocoder are described in its file list. [Model card](https://huggingface.co/freococo/MyanmarTTS)
- Transformers documents VITS inference and tokenizer-controlled romanization with `uroman`; check `tokenizer.is_uroman` for the actual checkpoint rather than assuming Myanmar preprocessing requirements. [VITS documentation](https://huggingface.co/docs/transformers/model_doc/vits)

### Inferences
- Begin with short batch-size-one CPU and CUDA smoke tests and record peak GPU memory, latency, output duration, clipping, and failures. CPU fallback is an implementation target, not a completed compatibility claim.
- For OmniVoice, supply a manually verified Burmese reference transcript to avoid loading a second speech model and compounding transcription errors.
- For fine-tuning, first measure a single training step with short clips and small batches; consider accumulation, mixed precision where stable, and LoRA where supported. Do not promise full-model training fits in 8 GB.
- Native Windows dependencies and Unix-oriented training scripts may require adaptations or a separately documented WSL training environment.

### Gaps
- Native Windows installation and inference have not been tested for any candidate in this investigation.
- Apple Silicon support is documented upstream for OmniVoice but not tested locally. MMS/MyanmarTTS MPS operation and Intel macOS feasibility remain unverified.
- Offline cache completeness, tokenizer edge cases, exact pinned dependencies, installation size, and redistribution inventories need Phase 1/2 checks.
