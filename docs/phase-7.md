# Phase 7 — own-voice dataset and fine-tuning

## Objective and status

Fine-tune Nara Mini v1 on the user's own permissioned voice so the app has a clean voice
of its own, without the preset voices' fizz or hum.

**Status (2026-11-17):** started.

- **Done:** recording guide (`docs/recording-guide.md`), script r001–r100
  (`docs/recording-script.md`), a dataset QC tool (`mvs-dataset check`), and full-precision
  model loading (`scripts/nara_fp32.py`).
- **Blocked on data:** we have 0 usable minutes. The 32 earlier clips were OGG, unnamed and
  had no transcript; their SNR was good (~59–65 dB). We need 30+ minutes.
- **Not started:** the training loop. Neither Nara nor Kokoro publishes official training
  code; see "Fine-tuning path".

## Finding: the background noise comes from the voices themselves

The Nara model card says the ONNX decoder is INT8-quantised, and full-precision weights are
published. `scripts/nara_fp32.py` loads them into the Kokoro architecture. It renames the
torch weight-norm keys `parametrizations.weight.original0/1` → `weight_g/weight_v`; all
548 tensors were checked as equal after loading. FP32 versus INT8 on the same passage:

| | >7 kHz share | <80 Hz share |
|---|---|---|
| htet-myat INT8 (ONNX) | 0.126 | 0.069 |
| htet-myat FP32 | 0.115 | 0.068 |
| male_calm (INT8 + G chain) | 0.053 | 0.023 |
| male_calm FP32 + same chain | 0.049 | 0.020 |

So quantisation is **not** the main cause. The fizz and hum are part of the preset voices.
They were trained on synthetic VoxCPM2 speech (model card). DSP can reduce them but not
remove them. Fine-tuning on clean, real recordings is the real fix. A/B files:
`outputs/fp32-compare.zip`.

## Dataset QC tool

```bash
.venv-nara/Scripts/mvs-dataset.exe check recordings/zayar --out datasets/zayar
```

Per file it checks: lossy format, sample rate ≥ 24 kHz, 1–20 s length, clipping, too quiet,
noise floor (problem above −50 dBFS, warning above −60), SNR, edge silence, and that a
transcript exists. Transcripts come from `rNNN` IDs in the script table or a same-name
`.txt` file (long-form). It writes `qc_report.json` and shuffled `train.jsonl` / `val.jsonl`
(5% validation once there are 20+ clips), and gives advice (metadata/consent, minutes left).
The recordings folder is never modified.

## ASR tool (free speech + misread check)

Model: [freococo/myanmar_asr](https://huggingface.co/freococo/myanmar_asr). Apache-2.0, a 23.8M
Conformer-CTC trained on 1.66M Burmese utterances, with 9.4% syllable error rate (SER)
reported by the publisher. The code was reviewed before use: pure PyTorch and safetensors,
no network calls. It is loaded by `src/myanmar_voice_studio/training/asr.py`, which does not
run the publisher's CLI.

```bash
.venv-f5/Scripts/mvs-asr.exe recordings/zayar
```

- Files with a transcript (an `rNNN` script ID or a `.txt`) get SER against the expected
  text. If SER is above 0.25, the file is marked **check** (likely misread).
- Files without a transcript get a `<name>.draft.txt` (never overwritten). The user fixes
  it and renames it to `.txt`. `mvs-dataset check` uses only `.txt`, never drafts.
- Writes `transcript_review.md` in the folder.
- Verified on synthetic clips (`outputs/asr-test1`): 4 script lines ok (SER 0.0–0.17);
  a wrong line read for r002 was flagged (SER 1.17); free speech was transcribed exactly.
  Syllable splitting and SER have unit tests.

## Fine-tuning path (plan)

1. Data: 30–120 min of clean WAV, checked by `mvs-dataset`.
2. Preprocess: resample to 24 kHz mono, trim edges, phonemise transcripts with the refined
   frontend, and compute token IDs with the Nara vocab (178 symbols).
3. Training code: Kokoro is StyleTTS2-based (iSTFTNet decoder, ALBERT duration model).
   Options: (a) a community Kokoro fine-tuning trainer, or (b) StyleTTS2 second-stage
   training code adapted to Kokoro's module names. Start from `weights/htet-myat` (male) or
   `shoon` (female), not from scratch. The licences of the chosen trainer must be checked.
4. Resource check on the RTX 3070 Ti 8 GB: one training step with batch 1 and short clips
   first; mixed precision; gradient accumulation.
5. New voice style vectors: average style embeddings from the speaker's clips to make
   `voice.json` styles (8 length bins).
6. Export to ONNX (fp32 decoder, no INT8) and add an adapter preset.
7. Evaluation: held-out sentences, native-speaker rating against `male_calm` / `female_warm`.

## Common errors

- `no transcript`: name files `r001.wav` … to match the script, or add `name.txt`.
- `lossy format`: record WAV directly (Audacity → WAV, 48 kHz, mono).
- `noisy background`: switch off fans/AC and move away from the window; floor must be below −55 dBFS.
- FP32 script: needs `.venv-f5` (CUDA torch) with `kokoro==0.9.4`.

## Completion criteria

- [x] Recording guide and script (r001–r100)
- [x] QC tool + tests
- [x] ASR draft transcripts + misread check (`mvs-asr`)
- [x] FP32 model load verified (basis for fine-tuning)
- [ ] ≥ 30 min accepted recordings
- [ ] Training loop runs one step on 8 GB
- [ ] Fine-tuned voice beats preset voices in a listening test
