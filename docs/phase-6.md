# Phase 6 — Windows desktop app (Tauri 2 + React)

## Objective and status

A desktop app for daily use: type Burmese, pick a voice, generate, listen, export. It also
renders voice-direction scripts. It uses the same engine as the CLI and MCP.

**Status (2026-11-17):** the app builds and runs in dev mode on Windows 11. The Rust bridge
was tested against the real Python worker: ping, voices, an error case, and a real
synthesis with the audio file. The UI was redesigned and reviewed in browser preview mode.
**Not yet done:** a click-through of the real window with the real engine (the user should
check this), the NSIS installer build, and SQLite history. Installers are Phase 10.

## Architecture

```text
React UI (Vite, TS, Tailwind)  ──invoke──►  Rust (Tauri 2)  ──stdin/stdout JSON lines──►  mvs-worker (Python)
  StudioClient interface              worker_call, read_output_audio        VoiceStudioService → engine (Nara)
  (Tauri client | preview mock)       spawn/restart worker, save dialog      one model load per app
```

- **Worker protocol** (`src/myanmar_voice_studio/worker/worker.py`): `{"id","method","params"}` →
  `{"id","result"}` or `{"id","error":{type,message}}`. Methods: ping, list_voices,
  capabilities, validate, preview, generate_speech, generate_directed, status, cancel,
  audio_path, export_to_path.
- **Rust** (`apps/desktop/src-tauri/src/`): starts the worker on first use, restarts it if it
  dies, and serialises requests. `read_output_audio` returns bytes for an `output_id`, so file
  paths never reach the UI. Exports go to a path the user picks in the native save dialog.
  Existing files are never overwritten (`.wav` or `.mp3`).
- **Worker location:** `MVS_WORKER`, else `<repo>/.venv-nara/Scripts/mvs-worker.exe`.
  `MVS_PROJECT_ROOT` is set automatically when the repo is found.
- **Types:** `src/api/voice-direction.d.ts` is generated from `schemas/voice-direction-1.0.json`
  (`npm run gen:types`).
- **Preview mode:** in a plain browser (no Tauri), the UI uses a fake engine (`src/api/demo.ts`)
  with a test tone. The sidebar labels it "Preview mode — အသံအတု".

## UI (redesign)

- Sidebar: Studio / Script / History, engine status (ready, loading or error, with a retry button).
- Studio: voice cards, Burmese editor with sample sentences and a character count,
  Ctrl+Enter to generate, progress shown in the button, a cancel button, and a result card
  under the editor. The result card has a custom player (seek, time), regenerate, export
  and a "not applied" notice.
- Delivery panel (sticky): speed, pitch and pause sliders with support badges (DSP/engine).
  Expression (emotion/delivery) is marked "မရပါ", with a plain explanation that it will
  not change the audio. Strict-mode checkbox.
- Script: segment table (voice, pause, per-segment "not applicable" flags after
  validation) or a JSON editor with live parse errors and Format.
- History: everything generated this session, with play and export. It is in memory only
  until SQLite (later phase).
- Toasts for export results and errors.
- **MCP page (on/off):** a switch for each AI client (Claude Desktop, Claude Code for this
  project). ON adds our `myanmar-voice-studio` entry to that client's config, and OFF removes
  only that entry. Other servers and settings are kept. The original file is backed up once
  to `*.mvs-backup`, and a file with invalid JSON is never overwritten. The sidebar shows
  MCP ON/OFF. The client must be restarted for a change to take effect. Code:
  `src/myanmar_voice_studio/mcp_server/registration.py`; worker methods `mcp_status`
  and `mcp_set_enabled`.

## Commands

The first time, open a new terminal so `cargo` is on PATH (Rust was installed with winget).

```bash
cd apps/desktop && npm install
```

```bash
cd apps/desktop && npm run tauri dev
```

```bash
cd apps/desktop && npm test
```

```bash
cd apps/desktop/src-tauri && cargo test
```

UI-only preview in a browser: `npm run dev`, then open http://localhost:1420.

## Verification performed

- MCP toggle: 5 Python tests (temp config paths only; the real Claude config was not
  touched by tests) and 1 Vitest test. The page was checked in browser preview.
- `npm test`: 9 Vitest tests pass (capability badges, generate → poll → player → export toast
  → history, strict refusal, worker-down screen, script table and validation, invalid JSON,
  polling, error mapping, cancelled save dialog).
- `tsc` strict typecheck and `vite build` succeed.
- `cargo build` succeeds. `cargo test` `real_worker_round_trip` passes against the real worker,
  including a real synthesis whose WAV is larger than 1 KB.
- Python: 58 tests pass (`.venv-nara`), including 4 worker protocol tests.
- Browser preview: Studio, Ctrl+Enter generation, result player, Script validation table and
  sidebar status were checked on screen.
- `npm run tauri dev` starts the app. **The real window was not inspected by Claude**,
  because the dev build cannot be granted to screen control.

## Common errors

- "Voice engine နဲ့ ချိတ်လို့ မရပါ": the worker was not found or failed. Check `MVS_WORKER` /
  `.venv-nara`, then press "ပြန်ချိတ်မယ်".
- `cargo` not found: open a new terminal after installing Rust.
- `link.exe` not found: the Visual Studio C++ Build Tools are missing.
- Port 1420 in use: stop the other Vite/Tauri dev process.

## Completion criteria

- [x] Tauri 2 + React + TS + Tailwind app; Studio, Script, History screens.
- [x] Real engine through the worker; playback; export through a native dialog with no overwrite.
- [x] Capability badges and "not applied" reporting in the UI.
- [x] Tests: Vitest, Rust worker round trip, Python worker protocol.
- [ ] User click-through in the real window.
- [ ] SQLite generation history and presets (Phase 9 scope).
- [ ] Installer (NSIS) build and clean-machine test (Phase 10).
