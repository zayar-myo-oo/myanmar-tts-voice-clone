# Phase 3 — shared voice engine and capability system

## Objective and status

Build one Python voice engine that the CLI, the future desktop app (Phase 6) and the MCP
server (Phase 5) all call. It must report honestly which voice controls it can apply.

**Status (2026-11-17):** engine, Nara Mini adapter, capability reporting, CLI and tests are
implemented. 22 tests pass in `.venv-nara`, including two end-to-end Nara tests. The engine
reproduces the user-approved `male_calm` voice. Phase 4 (voice-direction schema and segment
renderer) has not started.

## What it does, and why it is built this way

```text
caller (CLI / app / MCP)
   │  SynthesisRequest (text, voice_id, speed, pitch, emotion, delivery, pauses, strict)
   ▼
VoiceEngine ── plan(): compare requested controls with the adapter's capabilities
   │              → applied (native / dsp / engine)  + unsupported (reported, never faked)
   ▼
Adapter (NaraAdapter) ── text frontend fork → ONNX encoder/decoder → neutral audio
   ▼
DSP chain ── low-pass → pitch/tempo (ffmpeg) → peak normalize → inserted pauses
   ▼
WAV written with exclusive create (never overwrites) + SynthesisResult
```

- **Adapters** keep the model replaceable. A new model adds one adapter file. Nothing in
  the app or MCP changes.
- **Capabilities** label each control `native`, `dsp`, `engine` or `unsupported`. Nara has
  no emotion, delivery (whisper/shout), energy or emphasis control. Those are reported
  as unsupported. Speed and pitch are DSP after synthesis. Pauses are inserted silence.
- **Strict mode** rejects a request with any unsupported control before synthesis.
  Without strict mode, the audio is produced and the result lists what was not applied.
- **Voice profiles** come from `config/voice_presets.json`, so new voices need no code.

## Files

```text
src/myanmar_voice_studio/engine/
  schemas.py        Pydantic contracts: SynthesisRequest/Result, ModelCapabilities, VoiceProfile
  engine.py         VoiceEngine: list_voices, capabilities, plan, synthesize
  adapters/base.py  TTSAdapter protocol
  adapters/nara.py  Nara Mini v1 adapter (CPU onnxruntime, session cache, thread lock)
  dsp.py            low-pass, edge fade, normalize, silence, ffmpeg pitch/tempo
  voices.py         loads config/voice_presets.json
  settings.py       finds project root/models (MVS_PROJECT_ROOT, MVS_MODELS_DIR)
  cli.py            mvs-speak command
config/voice_presets.json      male_calm, female_warm
third_party/nara_mini_v1/      refined text frontend fork (Apache-2.0)
tests/test_engine.py           fake-adapter unit tests + Nara end-to-end tests
```

## Exact commands

Install (engine environment, CPU):

```bash
.venv-nara/Scripts/python.exe -m pip install -e ".[dev,nara]"
```

Run tests:

```bash
.venv-nara/Scripts/python.exe -m pytest -q
```

Use the CLI (the output directory must already exist):

```bash
.venv-nara/Scripts/mvs-speak.exe voices
```

```bash
.venv-nara/Scripts/mvs-speak.exe caps male_calm
```

```bash
.venv-nara/Scripts/mvs-speak.exe say male_calm "မင်္ဂလာပါ" --out outputs/engine-check
```

```bash
.venv-nara/Scripts/mvs-speak.exe say male_calm "မင်္ဂလာပါ" --out outputs/engine-check --delivery whisper --strict
```

The last command exits with code 2: whisper is unsupported, so strict mode refuses it.

## Verification performed

- `pytest`: 22 passed in `.venv-nara`. In the pinned `.venv` (no onnxruntime): 20 passed, 2
  Nara tests skipped.
- CLI `say male_calm` on the Yangon passage with `--emotion excited --pause-after-ms 300`:
  17.654 s output (17.35 s earlier `male_calm` render + 0.3 s pause), with
  `emotion=excited` listed as unsupported and in warnings.
- Strict whisper request: refused, exit code 2, no file written.
- Frontend fork check: `ကမ္ဘာကြီး` phonemizes as `ɡə ba ʤi`.
- **Not verified by listening:** the engine output is assumed equal to the approved
  `male_calm` render because it uses the same pipeline and settings. Durations match.

## Common errors

- `Cannot locate the project root`: run inside the repository or set `MVS_PROJECT_ROOT`.
- `Nara speaker ... is not installed`: download the ONNX files into `models/nara-mini-v1/`
  (see `docs/burmese-tts-handoff.md`).
- `ffmpeg is not on PATH`: install ffmpeg. `male_calm` needs it for pitch/tempo.
- `Output directory does not exist`: create it first. The engine never creates or
  overwrites paths silently.
- `Unsupported controls`: expected with `--strict`; remove the control or drop strict.

## Completion criteria

- [x] One engine API used by the CLI; adapters replaceable.
- [x] Capabilities reported per control; unsupported controls never claimed.
- [x] Safe output: exclusive file creation, validated directory, length limits.
- [x] Tests pass; end-to-end Nara synthesis works.
- [ ] Optional: `scripts/evaluate_nara.py` still has its own copy of the pipeline. Switch
  it to the engine when convenient.

Next: Phase 4, the versioned voice-direction JSON schema and the multi-segment renderer.
