# Phase 4 — voice-direction schema and segment renderer

## Objective and status

Define one versioned JSON contract for "how a script should be spoken". Then render
a whole script, segment by segment, into one narration file. The desktop app, MCP tools,
preset files and script exports all use this contract.

**Status (2026-11-17):** schema 1.0, preview (plan without audio), renderer, CLI and tests
are done. 36 tests pass in `.venv-nara`. A three-segment example with two voices was
rendered (7.86 s). Phase 5 (MCP server) has not started.

## The contract (schema 1.0)

- Pydantic source: `src/myanmar_voice_studio/engine/direction.py`.
- Exported JSON Schema: `schemas/voice-direction-1.0.json`. A test fails if it is out of
  date. The TypeScript app will generate its types from this file in Phase 6.
- Example: `schemas/examples/stickman-story.json`.

```json
{
  "schema_version": "1.0",
  "project_name": "Stickman Story",
  "voice_id": "male_calm",
  "global_settings": {"speed": 1.0, "pitch": 0, "energy": 0.75, "pause_scale": 1.0},
  "segments": [
    {"id": "segment_001", "text": "မင်းသိလား။", "emotion": "curious", "pause_after_ms": 700},
    {"id": "segment_003", "text": "...", "voice_id": "female_warm", "delivery": "shout"}
  ]
}
```

Rules enforced by validation: unknown fields are rejected, segment ids are unique and
`[A-Za-z0-9_-]`, text is not blank, numbers are range-checked, and emotion/delivery
come from fixed lists. Each segment can override the voice, speed (multiplied) and pitch
(added). `pause_scale` multiplies every pause.

## How rendering works

1. **Validate** the JSON with Pydantic.
2. **Preview / plan**: each segment becomes a `SynthesisRequest`. The engine compares it with
   the voice's capabilities. The result lists applied and unsupported controls per segment.
   No audio is produced. In strict mode any unsupported control stops the run here.
3. **Render**: each segment goes through the Phase 3 engine (synthesis → DSP → pauses).
   The segments are joined in order.
4. **Write**, never overwriting: `<project>-<id>.wav`, `<project>-<id>.report.json` (timings,
   applied/unsupported per segment, the full direction), and optionally a
   `<project>-<id>-segments/` folder with one WAV per segment. The per-segment files are
   for previewing and regenerating single segments later (Phase 9 timeline).

With the current Nara voices, emotion, delivery, energy and emphasis are reported as
**unsupported**. Only pauses (engine), speed and pitch (DSP) are applied.

## Commands

```bash
.venv-nara/Scripts/mvs-speak.exe preview schemas/examples/stickman-story.json
```

```bash
.venv-nara/Scripts/mvs-speak.exe preview schemas/examples/stickman-story.json --strict
```

```bash
.venv-nara/Scripts/mvs-speak.exe render schemas/examples/stickman-story.json --out outputs/phase4 --segments
```

```bash
.venv-nara/Scripts/mvs-speak.exe schema > schemas/voice-direction-1.0.json
```

## Verification performed

- `pytest`: 36 passed in `.venv-nara`. The pinned `.venv` result is recorded in the handoff.
- Preview of the example: 9 unsupported controls are listed per segment (emotion, delivery,
  energy, emphasis). Pauses are marked applied by the engine.
- Strict preview: refused with exit code 2.
- Render: `outputs/phase4/stickman-story-b59de1f3e1.wav`, 7.864 s. Segment timings
  0–2.101, 2.101–5.139 and 5.139–7.864 s. Segment 3 uses `female_warm`.
- **Not verified by listening** yet.

## Common errors

- `invalid direction file`: the message names the field, e.g. a duplicate id or an
  emotion outside the list.
- `Unknown voice`: use a `voice_id` from `mvs-speak voices`.
- `Unsupported controls`: expected with `--strict` for emotion/delivery on Nara voices.
- `sample rate ... expected`: all voices in one document must share a sample rate.
  The current Nara voices all use 24 kHz.

## Completion criteria

- [x] Versioned schema shared as Pydantic + exported JSON Schema, with an example.
- [x] Capability-aware translation; unsupported directions reported, never faked.
- [x] Multi-segment, multi-voice render with timings, a report and optional per-segment files.
- [x] Tests for validation, merging, strict mode, timing and no-overwrite.
- [ ] Presets (`preset` field) are stored but not applied yet. That is Phase 9.

Next: Phase 5, a standalone MCP server (stdio) that exposes these engine functions.
