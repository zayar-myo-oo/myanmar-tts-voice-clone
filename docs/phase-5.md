# Phase 5 — standalone MCP server (stdio)

## Objective and status

Let any MCP-compatible AI assistant (Claude Desktop, Claude Code, others) generate Burmese
narration with the same engine as the CLI and the future desktop app. It must work
without the desktop app open.

**Status (2026-11-17):** the server exposes 10 tools over stdio. 49 tests pass in
`.venv-nara`, including a real protocol test. That test starts the server, calls it with
the official MCP client, renders the example script and exports an MP3. The server has
not yet been connected to a real Claude Desktop/Code session; that step is for the user
(see "Connect a client").

## Design

```text
AI assistant ──stdio (JSON-RPC)──► mvs-mcp (FastMCP, official SDK 1.30)
                                     │  tools → VoiceStudioService
                                     │    • lazy single VoiceEngine (model loaded once per process)
                                     │    • job queue (1 worker thread): queued → running → completed/failed/cancelled
                                     │    • outputs in MVS_OUTPUT_DIR/<job_id>/ ; clients get opaque output_id
                                     │    • export only into MVS_EXPORT_DIR, plain file names, never overwrite
                                     ▼
                               Phase 3/4 engine + renderer (Nara adapter)
```

- **stdout carries only the protocol.** Logs go to stderr. No network port is opened
  (stdio only; HTTP is optional later).
- **The service layer** (`mcp_server/service.py`) holds all logic, so it is unit-tested
  without a client. `server.py` only maps tools to service calls.
- **Typed schemas:** each tool's input and output are Pydantic types. Clients receive
  structured JSON, e.g. `JobInfo`, `ValidationReport`, `ModelCapabilities`.
- **Honesty:** every result carries `unsupported` and `warnings`. The server instructions
  tell assistants never to claim emotion, whisper or shout were applied.

## Tools

| Tool | What it does |
|---|---|
| `list_voices` | voice profiles + per-control support |
| `list_presets` | direction presets: currently an empty list with a note (Phase 9) |
| `get_model_capabilities` | languages, devices, sample rate, limits, controls |
| `validate_voice_config` | schema 1.0 validation: field errors, unknown voices, unsupported controls |
| `preview_voice_direction` | segment plan without audio |
| `generate_speech` | one text → job (waits up to `wait_s`, default 120 s) |
| `generate_directed_speech` | segmented script → job with progress |
| `get_generation_status` | status, progress, output_id, errors |
| `cancel_generation` | queued jobs never start; directed jobs stop before the next segment |
| `export_audio` | WAV copy or MP3 (ffmpeg) into the export folder |

Cancellation limit: a single sentence that is already being synthesized finishes first.
The result says so.

## Commands

Install (engine env):

```bash
.venv-nara/Scripts/python.exe -m pip install -e ".[dev,nara,mcp]"
```

Run tests:

```bash
.venv-nara/Scripts/python.exe -m pytest -q
```

Start the server manually (it waits for a client on stdin; stop with Ctrl+C):

```bash
.venv-nara/Scripts/mvs-mcp.exe
```

Environment variables: `MVS_PROJECT_ROOT` (repo folder), `MVS_MODELS_DIR` (default
`<root>/models`), `MVS_OUTPUT_DIR` (default `<root>/outputs/mcp`), `MVS_EXPORT_DIR`
(default `<root>/exports`), `MVS_LOG_LEVEL`.

## Connect a client

Examples with placeholder paths (replace `C:\path\to\aivoiceclone`):

- Claude Desktop: `config/mcp/claude_desktop_config.example.json` → merge into
  `%APPDATA%\Claude\claude_desktop_config.json`, then restart Claude Desktop.
- Claude Code: `config/mcp/claude_code.mcp.example.json` → copy to `.mcp.json` in a project.

macOS: use `.venv-nara/bin/mvs-mcp` and POSIX paths. Not yet tested on a Mac.

Example request to an assistant: *"Use myanmar-voice-studio to read this Burmese script with
male_calm, pause 700 ms after the first sentence, and export it as an MP3 called intro."*

## Verification performed

- Unit tests with a fake engine: job completion, unsupported reporting, strict refusal
  before queueing, cancelling a queued job, validation errors, unknown jobs, export
  before ready, and unsafe names (`../evil`, `a/b`, `C:\x`, hidden, too long) rejected
  without writing files. Exporting the same name twice is refused.
- Real stdio protocol test (`test_stdio_protocol_end_to_end`): 10 tools listed,
  `list_voices`, `validate_voice_config`, `generate_directed_speech` (completed, > 3 s audio),
  `export_audio` MP3 (> 1 KB).
- Full suite: 49 passed (`.venv-nara`); 34 passed, 3 skipped (pinned `.venv`, no Nara/MCP).

## Common errors

- Client shows no tools: check the `command` path and that `MVS_PROJECT_ROOT` points to the
  repo. Run `mvs-mcp.exe` manually; errors print to stderr.
- `Unknown voice`: call `list_voices` first.
- `already exists in the export directory`: pick another `filename`; nothing is overwritten.
- `ffmpeg is required for MP3 export`: install ffmpeg or export WAV.
- Burmese text garbled in logs: set `PYTHONIOENCODING=utf-8` (protocol JSON is unaffected).

## Completion criteria

- [x] Standalone stdio server, independent of the desktop app, using the official SDK.
- [x] All 10 required tools with typed input/output and useful validation errors.
- [x] Async jobs with status, progress and cancellation (with the stated limit).
- [x] Safe local paths: opaque output IDs, allowlisted export folder, no overwrite.
- [x] Protocol test with the official client; client config examples.
- [ ] Manual check in Claude Desktop/Code by the user.

Next: Phase 6, the Windows desktop app (Tauri 2 + React). It needs Rust and the MSVC
build tools; check them first.
