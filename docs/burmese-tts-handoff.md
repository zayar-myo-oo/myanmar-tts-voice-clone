# Burmese TTS — handoff notes (read this first)

Last updated: 2026-11-17. Purpose: let any agent or person continue Burmese voice
work without repeating the investigation. Read this file before changing code.

> **Current state (latest, read first):** voices = `male_calm` (htet-myat FIX3 + long-form style),
> `female_warm` (shoon W3), `male_deep`, and `zayar` (the user's own voice, F5-Myanmar zero-shot clone,
> CC-BY-NC personal use, reference `recordings/zayar_take2/nr028.wav`). `zayar` needs the GPU env
> `.venv-f5` (torch cu128 + f5-myanmar-tts), which now has the full engine installed. The desktop app's Rust
> worker launcher prefers `.venv-f5` and falls back to `.venv-nara`; voices whose adapter is missing are hidden
> (`VoiceEngine.list_voices`). F5's stdout prints are redirected to stderr (protocol safety, verified).
> Adapter: `engine/adapters/f5clone.py`; profile fields `reference_audio`, `reference_text`.
> Tests: Python 79 (CPU env), Rust worker round-trip passes via the GPU env. The GPU-env pytest run was
> still in progress at the time of writing. Detailed history follows in the sections below.

## 1. Where things stand

| Item | Status |
|---|---|
| Phase 0 (ML env, CUDA, audio roundtrip) | Done (`docs/phase-0.md`) |
| Phase 1 (model review, licenses) | Done (`reports/Myanmar TTS model feasibility.md`) |
| Phase 2, MMS `facebook/mms-tts-mya` baseline | Generated. **User listening result: naturalness 1/5, judged not acceptable.** Phase 2 is NOT passed. |
| Phase 2, MyanmarTTS `freococo/MyanmarTTS` candidate | Generated 4 clips (`outputs/myanmartts-r1`). **Not yet listened to by a native speaker. No quality claim yet.** |
| Phase 3+ (audio mixing, animation, UI) | Not started. Do not start until Phase 2 passes. |

Do not claim Burmese speech quality passed unless a native speaker has listened and
recorded a rating. Automated checks (finite, non-silent, duration) only prove the
file is valid audio.

## 2. Candidate comparison

| Candidate | Weights license | Voice control | Result so far |
|---|---|---|---|
| MMS `mya` (VITS, 16 kHz, one speaker) | CC-BY-NC-4.0 | speed only | Naturalness 1/5 (user listening) |
| MyanmarTTS (StableTTS DiT + flow matching, Vocos vocoder, 44.1 kHz) | Weights CC0-1.0; vocoder MIT (per publisher) | reference-audio cloning, `length_scale`, `cfg`, `step` | Clips generated; awaiting listening |
| OmniVoice (`k2-fsa`) | Code Apache-2.0, **weights CC-BY-NC** | reference cloning, voice design | Not tested. Burmese reliability unverified |
| XTTS-v2 | — | — | Excluded: Burmese not supported |

Source of the candidate comparison: `reports/Myanmar TTS model feasibility.md`.

## 3. Files and folders

```text
docs/burmese-tts-handoff.md          This file
evaluation/burmese-baseline.json     Test sentences (ids, text, expected generate/reject)
scripts/evaluate_mms.py              MMS evaluation (pinned .venv)
scripts/evaluate_myanmartts.py       MyanmarTTS evaluation (separate .venv-myanmartts)
models/mms-tts-mya/                  MMS weights (git-ignored, do not commit)
models/myanmartts/                   MyanmarTTS weights + vocos + sample_0.wav reference
models/package-audit/myanmartts-1.0.2-py3-none-any.whl   Wheel supplying the inference code
outputs/mms-baseline-{cpu,cuda}/     MMS clips + report.json (git-ignored)
outputs/myanmartts-r1/               MyanmarTTS clips + report.json (git-ignored)
.venv/                               Pinned inference env (torch 2.7.1+cu128). Do not add packages.
.venv-myanmartts/                    Candidate env, CPU torch 2.15.0, numba, torchaudio, torchdiffeq
```

## 4. Commands

Generate MyanmarTTS clips (CPU, offline, new output dir each run):

```bash
.venv-myanmartts/Scripts/python.exe scripts/evaluate_myanmartts.py --output-dir outputs/myanmartts-r2
```

Useful flags: `--reference <wav>` (speaker prompt), `--steps` (default 32),
`--cfg` (default 3.0), `--length-scale` (speaking rate, default 1.0), `--seed` (42).

Re-download weights (only if `models/myanmartts/` is missing):

```bash
.venv-myanmartts/Scripts/python.exe -c "from huggingface_hub import hf_hub_download as d; [d('freococo/MyanmarTTS', f, local_dir='models/myanmartts') for f in ['model_fp16.pt','vocos.pt','config.json','vocab.txt','samples/sample_0.wav','transcripts.json']]"
```

## 5. Known issues

1. **Clipping:** `numbers_spelled` peaks at 1.80 (float WAV, above full scale). Any
   16-bit export must normalize or apply limiting first. Other clips peak at 0.85–1.01.
2. **Reference speaker:** the only reference used is the publisher's `sample_0.wav`,
   a female voice. Output timbre follows the reference. This is not one of the
   target voices. Target voices need permissioned reference audio.
3. **Torchcodec missing:** `myanmar_tts` loads references with torchcodec. The script
   patches `load_and_resample_audio` with soundfile + torchaudio. Keep the patch.
4. **Digits and English are unsupported** by this G2P. Spell numbers as Burmese words.
   Same rule as the MMS harness (`evaluation/burmese-baseline.json` rejects digits).
5. **Punctuation:** the baseline text uses `။` and `၊`. Whether these produce pauses
   is untested.
6. **Speed and emotion:** only `length_scale` and reference audio are exposed. Do not
   mark whisper, shout, or emotion as supported. Those need separate evidence.
7. Ran on CPU only. The CUDA path is untested for this model.

## 6. Listening protocol (native speaker)

For each clip in the output folder, record:

1. Missing, repeated, or wrong words, with the exact word.
2. Understandable: yes/no.
3. Naturalness 1 (robotic) to 5 (natural).
4. Noise, abrupt cutoffs, bad pacing, clipping.

Pass condition: a neutral clip reaches naturalness ≥ 3 with no missing words, and the
clipping issue is fixed. Only then update Phase 2 status. Rating results go in
`reports/` as a new file, not in this handoff.

## 7. Next steps (in order)

1. Native speaker listens to `outputs/myanmartts-r1/*.wav` and rates them using §6.
2. If naturalness is poor, try: a different `--reference`, `--steps 64`, `--cfg` 2.0 or
   4.0, and `--length-scale` 0.95–1.05. Each run goes to a new output folder.
3. Fix clipping: normalize peaks to about -1 dBFS in the export step. Do not change the
   model output itself.
4. If MyanmarTTS passes neutral Burmese, research a permissioned speaker reference for
   the target voices before any cloning claim.
5. If it fails, evaluate OmniVoice Burmese output, noting its non-commercial weights.
6. Do not start fine-tuning (Phase 7) or any full video render until Phase 2 passes.

## 7a. Findings log (2026-11-17, latest session)

| Run | Settings | Output | Notes |
|---|---|---|---|
| r1 | length 1.0, cfg 3.0, steps 32 | `outputs/myanmartts-r1` | numbers_spelled peak 1.80 (clipping) |
| s1 | length 0.9, cfg 2.0, steps 32 | `outputs/myanmartts-s1` | normalized `*_norm.wav` |
| s2 | length 0.8, cfg 3.0, steps 32 | `outputs/myanmartts-s2` | normalized; faster, not preferred |
| s3 | length 0.9, cfg 4.0, steps 64 | `outputs/myanmartts-s3` | narration peak 1.53 before normalize |
| passage-a | length 1.0, cfg 3.0, steps 32 | `outputs/passage-a/custom_norm.wav` | 20.97 s, Yangon passage |
| passage-b | length 0.9, cfg 2.0, steps 64 | `outputs/passage-b/custom_norm.wav` | 18.87 s, Yangon passage |

- **User rating (natural):** about **2.5 / 5**. Judged "correct" but still AI-sounding
  and slow. Passage clips were sent for listening; no word-level error list yet.
- **Reference comparison:** user pointed to the commercial SpeechGen Burmese TTS
  (`https://speechgen.io/en/tts-burmese/`) as the quality target. The page is marketing
  text only; its own voice samples were not audited. It is a cloud service, so it is a
  quality benchmark, not an offline option.
- **Pending items:** word-level error list from the listener; a decision on whether
  passage-a or passage-b is the base for further tuning.
- **Phase 2 status:** still not passed.
- **Spec note:** the user supplied a revised "Myanmar Voice Studio" master prompt
  (Phases 0–11). Treat it as the project spec. Phase 2 remains open until the listening
  criteria in §6 are met.

## 7b. Nara Mini v1 (current primary candidate, 2026-11-17)

- Model: `YeeNyunn/nara-mini-v1`, Kokoro-82M based, ONNX, Apache-2.0 (code and model
  card). Burmese + English, four preset voices: shoon, thazin, ko-banyar, htet-myat.
  Model files: `models/nara-mini-v1/` (git-ignored). Official Space: `models/nara-space/`.
- **Caution:** the model card says the voice data was synthesized with VoxCPM2
  (Apache-2.0). Check that this does not restrict commercial use before any release.
- Env: `.venv-nara` (CPU, onnxruntime 1.32.0, misaki 0.9.4, phonemizer-fork 3.3.2).
- Script: `scripts/evaluate_nara.py` (mirrors the official app; no Gradio).
  Example: `.venv-nara\Scripts\python.exe scripts\evaluate_nara.py --text-file outputs/passage.txt --output-dir outputs/nara-passage-1`
- Result `outputs/nara-passage-1` (shoon, ko-banyar): 16.9 s and 15.1 s, peak ≈0.5–0.6,
  no clipping. Faster and cleaner than MyanmarTTS on the same passage (by peak/duration
  only). **Natural rating not yet given by the user.**
- User decision: adopt Nara Mini as the base, then improve on it.
- **User ratings (natural, 1–5):** Shoon **3.8**, Ko Banyar **2.9** on the default run.
- Speed knob (`--speed`, duration scaling): effect is small. Passage 16.93 s at 1.0,
  17.07 s at 0.92, 16.77 s at 1.08 (Shoon). Duration scaling alone does not change
  pace much; a real speed control needs model-side work.
- Loudness normalization (peak -1 dBFS) added to `scripts/evaluate_nara.py`.
- Variant folders: `outputs/nara-s092`, `outputs/nara-s085`, `outputs/nara-s108`.
- **Pronunciation complaints (user):** "ဘုရားဖူးစခန်း" and "ကမ္ဘာကြီး" unclear.
  Diagnosis: the frontend produces phonemes for both (`pʰə ja↗ pʰu↗ sa↓ kʰaɴ↗`,
  `kaɴ→ ba→ ʤi↗`). No phonemes are dropped by the voice vocabulary. The lexicon
  override for ကမ္ဘာ (coda `m`) was tried and dropped syllables, so it was removed.
  The unclear part is therefore in the acoustic model, not the text frontend. A
  quick lexicon fix is not available; fixing it needs model-side work.
- Still open to beat 3.8: fine-tuning or a better Burmese frontend (Phase 7 gate).
  Post-processing (normalize, speed) cannot add naturalness on its own.

## 7c. Nara refinement status (latest)

- **Goal (user):** own Burmese voice model for personal use → desktop app → GitHub →
  MCP server → narration for videos. Nara Mini is the base; we refine it ourselves.
- **Frontend fork:** `third_party/nara_mini_v1/` (Apache-2.0, LICENSE/NOTICE kept,
  changes in `CHANGES.md`). `scripts/evaluate_nara.py` loads the frontend from there and
  ONNX weights from `models/nara-mini-v1/onnx/`.
- **Pronunciation fixes:** `ကမ္ဘာ` → `ɡə ba` and `ကမ္ဘာကြီး` → `ɡə ba ʤi` (was heard as
  "Canva"). **User confirmed fixed.** Add further fixes to the fork's
  `frontend/lexicon_exceptions.tsv` and log them in `CHANGES.md`.
- **"ဂျစ်ဂျစ်" background noise:** no clipping or sample jumps found; treated as
  vocoder high-frequency fizz. `--lowpass` (soft FFT low-pass) added; variants at
  9000/7500/6000 Hz sent. **User has not picked a cutoff yet;** presets use 9000 Hz.
- **Voice presets:** `config/voice_presets.json`, used via `--preset`.
  - `male_calm`: htet-myat, pitch -1.5 st, tempo 0.95, 0.28 s gap, low-pass 9000.
    **User preferred this one** (from `htet-myat_deep_calm_dsp`).
  - `female_warm`: shoon (rated 3.8/5).
  - Pitch/tempo are **ffmpeg DSP after synthesis**, not native model control. Label them
    that way in the app and MCP capability reports.
- Renders with `male_calm`: `outputs/male-calm-{passage,baseline,script}` and
  `outputs/male-calm-pack.zip`. Not rated yet.
- Still open: "ဘုရားဖူးစခန်း" is still unclear (user has not said what it sounds like);
  choice of low-pass cutoff; ratings for `male_calm` renders.
- **Voice signed off by user (2026-11-17):** `male_calm` approved. Phase 2 closed for the
  Nara-based neutral voice.
- **Phase 3 done:** shared engine in `src/myanmar_voice_studio/engine/`, see
  `docs/phase-3.md`. Use `mvs-speak` or `VoiceEngine` rather than the evaluation scripts.
  Next is Phase 4 (voice-direction schema + segment renderer).
- **Phase 4 done:** schema 1.0 (`schemas/voice-direction-1.0.json`), preview + renderer
  (`engine/direction.py`, `engine/renderer.py`), CLI `mvs-speak preview|render|schema`.
  See `docs/phase-4.md`. 36 tests pass in `.venv-nara`. Next is Phase 5 (MCP server).
- **Phase 5 done:** stdio MCP server `mvs-mcp` (`src/myanmar_voice_studio/mcp_server/`,
  official `mcp` SDK 1.30), 10 tools, job queue, safe export (WAV/MP3). See
  `docs/phase-5.md`; client configs in `config/mcp/`. 49 tests pass in `.venv-nara`,
  including a real stdio protocol test. Not yet tried in the user's Claude Desktop/Code.
  Next is Phase 6 (Tauri desktop app; check Rust + MSVC first).
- **Phase 6 (mostly done):** Rust 1.100 + VS 2022 C++ Build Tools installed via winget.
  Desktop app in `apps/desktop/` (Tauri 2, React, TS, Tailwind), redesigned UI (sidebar,
  voice cards, player, script table, history, toasts), Python `mvs-worker` bridge. See
  `docs/phase-6.md`. Tests: Python 53, Vitest 8, Rust 1 (real worker). Open items: the user's
  click-through of the real window, SQLite history, and the installer (Phase 10).
  MCP on/off page added (registers/unregisters in Claude Desktop / project `.mcp.json`).

## 8. Not verified yet

- Burmese pronunciation and naturalness of any model in this folder.
- CUDA performance, memory, and reproducibility of MyanmarTTS.
- Stability across the other baseline sentences in `evaluation/burmese-baseline.json`
  beyond the four generated clips.
- Whether `models/package-audit/myanmartts-1.0.2` (the wheel) matches the published
  upstream code. It is a local copy; treat it as unaudited.

## 7d. Latest additions (2026-11-17, later)

- **MCP Connections page** (desktop app): one "Enable MCP connection" switch starts a
  localhost-only streamable-HTTP MCP endpoint at `http://127.0.0.1:17863/mcp` inside the
  worker (shares the loaded model; lives only while the app is open). It lists the tools and
  has a copy-URL box plus "Copy Codex command" / "Copy Claude Code command". DNS-rebinding
  protection only allows localhost Host/Origin headers. The choice is remembered and restored
  at app start. Code: `mcp_server/http.py`; worker methods `mcp_http_status|start|stop`.
  Port 17863 avoids the separate Nara Mini app (17862). The old stdio config registration is
  under "Advanced". Tested with the official streamable-HTTP client. **The Codex command
  (`codex mcp add NAME --url URL`) has not been tested against a real Codex install.**
- **Expressions** (`engine/expression.py`): emotions calm, sad, happy, excited, surprised,
  curious, suspenseful, angry and deliveries narrator, podcast, energetic, soft are applied
  as prosody DSP (speed, pitch, extra pause, level, softening). They are reported as support
  `dsp` with per-value capability lists (`ControlCapability.values`). These are
  approximations, not acted emotion. **Whisper and shout stay unsupported.**
  Samples: `outputs/expressions.zip`, not yet rated by the user.
- **Male voice fizz:** the raw Nara htet-myat output already has high-frequency fizz
  (>7 kHz ≈ 12.6% of spectrum). The asetrate/atempo pitch shift adds clicks. Variants A–F,
  including rubberband pitch shifting, are in `outputs/male-fix.zip`. The user has not
  picked one yet; `male_calm` is unchanged until then.
- **Datasets needed to really fix quality/expression:** see the next section.

## 7e. What data is needed (fine-tuning, Phase 7–8)

| Goal | Data | Amount (rough) |
|---|---|---|
| Own neutral voice, clean (no fizz) | One speaker, quiet room, 24–48 kHz WAV, with an exact transcript per clip, 3–15 s clips | 30–60 min minimum, 2–5 h good |
| Better pronunciation in general | Many speakers, accurate Burmese transcripts (news, stories), numbers written out | 10+ h |
| Real emotions | The same speaker reading the same kind of text in each emotion, with an emotion label per clip | ~15–30 min **per emotion** |
| Whisper / shout | Real whispered and shouted recordings with labels | ~15–30 min each |

You must have permission to use every recording. Your own voice, or people who consent, is
the cleanest option. Common Voice Burmese is CC0 but read-speech quality varies.
Current own recordings: ~2.4 min in `recordings/zayar/`, too little for fine-tuning.

## 7f. male_calm option E + motor hum (2026-11-17, latest)

- `male_calm` now uses option E: `pitch_method: rubberband` (formant preserved), no FFT low-pass,
  `post_filter: lowpass=f=7000:p=2`. New `VoiceProfile.pitch_method` and `post_filter` fields;
  `dsp.pitch_tempo(..., method, post_filter)`. Engine output matches E (clicks 1444 → 550).
- The user then heard a **"water motor" hum**. The silence noise floor is clean (−94 dB), so the
  hum is low-frequency rumble during speech (energy <80 Hz was 10% in E). High-pass variants
  G/H/I/J are in `outputs/male-fix-2.zip` (<80 Hz energy cut to 0.5–2%). **User picked G (2026-11-17); applied:** `post_filter = highpass=f=90:p=2,lowpass=f=7000:p=2`. (Was: waiting for the
  user to pick one.** Then set `post_filter` to e.g. `highpass=f=90:p=2,lowpass=f=7000:p=2`.
- Own-voice recording: full guide `docs/recording-guide.md`; script extended to r001–r100.

## 7g. Phase 7 started (2026-11-17)

- See `docs/phase-7.md`. FP32 weights load (`scripts/nara_fp32.py`, `.venv-f5` + `kokoro==0.9.4`,
  weight-norm key rename). FP32 vs INT8 noise is about the same, so the fizz/hum is in the
  preset voices, and fine-tuning on clean real recordings is the fix.
- `mvs-dataset check <folder> --out datasets/<name>` gives QC + train/val manifests (64 Python tests pass).
- Other male speaker samples (ko-banyar K/L/M, htet-myat no-pitch N): `outputs/male-alt.zip` — not rated yet.
- Blocked on data: the user must record r001–r100 (WAV) plus more lines or own scripts, to reach 30+ min.
- **Male voice switched (user picked K, 2026-11-17):** `male_calm` = ko-banyar, no pitch shift, tempo 1.0,
  `post_filter highpass 90 Hz + lowpass 7 kHz`. The previous htet-myat chain is kept as preset `male_deep`.
- Script extended to r001–r400 (`docs/recording-script.md`, no digits/Latin). The user prefers
  free speaking, so `mvs-asr` (freococo/myanmar_asr, Apache-2.0, run from `.venv-f5`) makes
  `.draft.txt` transcripts and flags misread script lines. See `docs/phase-7.md`.
- **Voices finalised by the user (2026-11-17):** `male_calm` = ko-banyar M6, `female_warm` = shoon F6.
  Both use no pitch/tempo change and `post_filter highpass=f=80:p=2,deesser=i=0.4,lowpass=f=9000:p=2`.
  The DSP fix skips rubberband when pitch/tempo are unchanged, because a no-op stretch made the male voice sound robotic.
- **Final voices (user, 2026-11-17, latest):** `male_calm` = htet-myat **M9**; `female_warm` = shoon **F7**.
  The chain notches the vocoder whine at 4800/7200/9600 Hz (harmonics of 2400 Hz; the user heard it as "crickets"),
  then high-pass 80 Hz, de-esser 0.4, low-pass 9 kHz. No pitch/tempo change (pitching down made it "too deep").
  `male_deep` keeps the old pitched-down htet-myat, now with the notches added. Script: `scripts/voice_variants2.py`.
- **Final voices v3 (user, 2026-11-17):** `female_warm` = **F11**, `male_calm` = **M13**.
  Root cause of the "cricket/whine": iSTFTNet (n_fft 20 @ 24 kHz) leaves narrow lines at **every multiple of
  1200 Hz** (3600–10800 Hz, +5…+13 dB). The earlier fix only notched 3 of the 7 lines.
  Fix: `resynth: "vocos"` (re-synthesise through charactr/vocos-mel-24khz, MIT; `dsp.vocos_resynth`, CPU torch
  + `vocos==0.1.0` now in `.venv-nara`), then notches at all 7 lines, then HP 80 Hz + de-esser + LP 9 kHz.
  Male adds a less-deep EQ (−4 dB @200 Hz, +2 dB @3 kHz; no pitch shift): bass share 65%→55%.
  Verified with `scripts/tone_scan.py`: all lines −6…−16 dB. Regression test `test_presets_have_no_vocoder_whine`.
  68 tests pass.
- **Own recordings take 2 (2026-11-17):** 140 m4a clips (AAC 58 kbps, 48 kHz mono, ~9.1 min) in `recordings/zayar/`
  ("New Recording 25…185"). WAV copies are in `recordings/zayar_take2/nrNNN.wav`; the originals are untouched.
  QC: median SNR 52 dB, floor −69 dBFS, no clipping. `mvs-asr --match-script` labels clips with an exact script
  match (41 clips, `.txt`); the other 99 got ASR `.draft.txt` for user review, because the user paraphrases freely.
  Only exact matches get script text, so that changed wording is never mislabelled. Review: `recordings/zayar_take2/transcript_review.md`.
- Younger male variants (pitch up before Vocos): `outputs/vf4.zip` (Y0–Y4), not chosen yet.
- **Male voice v4 (user picked Y2, 2026-11-17):** `male_calm` ("Male — Young Narrator") = htet-myat, **+2 st pitch
  (rubberband, formant preserved) applied BEFORE Vocos**, then whine notches + less-deep EQ + base chain.
  The engine now runs pitch/tempo → Vocos → filters when `resynth: vocos` (`engine.render`). Engine output equals
  the Y2 sample (pitch ~123 Hz, bass 0.64, whine −7 dB). Female `female_warm` (F11) unchanged and approved.
- **Male voice v5 (user picked Y4, 2026-11-17):** +2 st with `pitch_method: rubberband_shifted` (formants move →
  younger timbre) before Vocos, young EQ (−6 dB @180 Hz, +3 dB @3.2 kHz). Engine output equals the Y4 sample. The user
  still finds the preset voices "AI-like"; only fine-tuning/cloning on real speech fixes that.
- **Own-voice clone test (F5-Myanmar zero-shot, CC-BY-NC → personal use only):** `scripts/clone_f5.py`, refs =
  the user's approved clips nr028/nr158/nr087; samples in `outputs/clone-f5.zip`. Not rated yet.
- **Desktop Review screen** ("အသံ စစ်ဆေး"): lists clips of a `recordings/<folder>` (default = newest), plays audio
  (`read_review_audio` Rust command → worker `review_audio_path`, confined to recordings/<folder>/<name>.wav),
  shows ASR text + matched script line, edit → approve (`.txt`), use script/ASR text, reject (`.rejected` marker;
  `mvs-dataset check` skips rejected). Shortcuts Ctrl+Enter / Alt+S. Backend `training/review.py` + tests.
  Python 78, Vitest 10 pass.
- **Male naturalness diagnosis (2026-11-17, user-requested protocol):** backup `config/backups/male_calm-20261117-194631.json`.
  The given WAV is bit-identical to a fresh render with the current config (Y4). Stage files + metrics:
  `outputs/diag-male/{stages.zip,compare.zip}` (scripts `male_stage_diagnosis.py`, `male_fix_candidates.py`,
  `voice_metrics.py`). Measured: the "young EQ" alone doubles the spectral centroid (557→1091 Hz) and cuts the
  100–300 Hz share 0.66→0.43, the biggest single-stage change. Vocos and the notches change periodicity only a little
  (0.65–0.69 everywhere). The f0-range drop after filtering may be a pitch-tracker artifact (low confidence).
  Candidates FIX1–4 are waiting for the user's pick; **the default preset is unchanged (still Y4).** Nothing was judged by ear.
- **Male default = FIX3 (user pick, 2026-11-17):** htet-myat, +1 st rubberband (formants preserved) → Vocos →
  whine notches → mild EQ (−2.5 dB @200 Hz, +1 dB @3 kHz) → HP 80 / de-esser / LP 9 kHz. It replaces Y4's strong
  "young EQ" and formant shift. Engine output correlates 1.00000 with the FIX3 sample (only the output level differs:
  engine peak-normalises to −1 dBFS). Previous Y4 preset: `config/backups/male_calm-20261117-194631.json`.
- **Male default = FIX3 + R4 (2026-11-17):** new `VoiceProfile.style_mode` ("length" default | "longform" | "average");
  `male_calm` uses `longform` (Nara's last style vector for every piece). Widest measured intonation (f0 sd 4.52 st
  vs 4.23). User rated FIX3 3.8 before this change. Round-5 samples: `outputs/diag-male/round5.zip`.
- **Nara decoder is stochastic:** each synthesis call in a process differs slightly. The first call in a fresh process
  is reproducible. Repeated runs: f0-sd spread ±0.05 st, and long-form style is consistently +0.11 st over default,
  so R4's effect is real but small. Sample-level correlation only works for first calls.
- Female "sweeter" variants W0–W4 (warm/soft EQ cuts 2.5–5 kHz energy by ~55%): `outputs/diag-female/sweet.zip`.
  F11 is still the default until the user picks. Desktop app restarted at 19:55 (window confirmed).
- **Female default = W3 (2026-11-17):** F11 + style_mode longform + warm/soft EQ (+1.5 dB @250, −2.5 dB @3.5k, −2 dB @7k). Backup of previous presets in config/backups/.
