# Proposed architecture

This is the target design, not a claim of implemented features.

React/TypeScript inside Tauri 2 owns the editor, playback and timeline. A Python
worker owns model loading, validated generation jobs and audio processing. A
standalone Python MCP stdio process calls the same engine package without needing
the desktop app. Initially each process owns one model cache; a shared local worker
can follow if simultaneous desktop/MCP memory usage warrants it. Do not promise
cross-process deduplication in the first implementation.

Pydantic is the source for the versioned direction JSON Schema. Generate TypeScript
types from that schema and validate at every boundary. Adapters translate only
supported parameters. Every request returns requested/applied/unsupported controls;
strict mode rejects unsupported directions before synthesis. Post-processing speed
or pitch is explicitly labelled as DSP, never as native emotion or whisper synthesis.

SQLite stores voices, presets, job status and history. Model files, references and
outputs stay in an OS-specific application data directory, with a configurable root.
MCP receives opaque output IDs; export uses an approved directory, exclusive creation,
and resolved-path checks. Worker stdout is protocol-only; logs go to stderr.

Model adapters advertise languages, devices, speaker/reference support, controls,
license, model revision and measured resource requirements. Offline mode resolves
only previously downloaded files. Downloads are a separate explicit setup operation.

Training remains a separate package/process so inference installs need no training
framework. Windows CUDA is the first measured backend. macOS CPU/MPS and Intel
wheel availability must be tested on actual Macs before compatibility claims.

## Directory ownership

```text
src/myanmar_voice_studio/  Python package (doctor implemented now)
apps/desktop/             Future Tauri/React UI
schemas/                  Future generated versioned contracts
training/                 Future dataset and fine-tuning pipeline
tests/                    Automated checks
docs/                     Phase guides and design
reports/                  Research and local verification reports
```

## Phase gates

0. ML environment, CPU/CUDA calculation, audio roundtrip; inventory desktop tools.
1. Review exact model artifacts, licenses, code and fine-tuning path; select candidate.
2. Generate Burmese evaluation corpus, listen with a native speaker, measure memory/time.
3–5. Shared engine, direction schema/renderer, standalone MCP with protocol tests.
6. Install/verify Rust and MSVC, then build desktop UI against proven engine.
7–9. Permissioned datasets, fine-tuning, measured expression, timeline and planner.
10–11. Clean-machine platform installers, licensing review, GitHub release.

No phase advances on a fabricated audio result or an untested model capability.
