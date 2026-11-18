# Myanmar Voice Studio

ကိုယ်ပိုင်စက်ထဲမှာပဲ (offline) အလုပ်လုပ်တဲ့ မြန်မာ AI အသံထုတ် (Text-to-Speech) စနစ်ပါ။
**Desktop app**၊ **command line** နဲ့ AI assistant တွေ ခေါ်သုံးနိုင်တဲ့ **MCP server** သုံးမျိုးလုံးက
voice engine တစ်ခုတည်းကို မျှသုံးပါတယ်။ Cloud API မလိုပါဘူး။

*An offline-first Burmese text-to-speech studio: one Python voice engine shared by a Tauri
desktop app, a CLI and an MCP server.*

> **Status (2026-11-18):** Phases 0–5 are done and Phase 6 is mostly done (desktop app runs
> in dev mode). Phase 7 (fine-tuning with your own voice) has started and is waiting for recordings.
> Installers (Phase 10) have not started. Details: [docs/burmese-tts-handoff.md](docs/burmese-tts-handoff.md).

---

## ဘာတွေ လုပ်နိုင်လဲ

- မြန်မာစာကို အသံထုတ်တာ (voice ၂ မျိုး: **Male — Calm Narrator**, **Female — Warm Natural**)
- Speed၊ pitch၊ ရပ်နားချိန် ချိန်ညှိတာ
- ဇာတ်ညွှန်း (voice-direction JSON) ကို segment အလိုက် voice/ရပ်နားချိန် သတ်မှတ်ပြီး ဖိုင်တစ်ခုတည်း ထုတ်တာ
- WAV / MP3 export
- Expression: calm, sad, happy, excited, surprised, curious, suspenseful, angry + narrator/podcast/energetic/soft (DSP နဲ့ အနီးစပ်ဆုံး ဖန်တီးတာ၊ whisper/shout မရသေး)
- Claude/Codex လို AI tool တွေက MCP ကနေ တိုက်ရိုက် ခေါ်သုံးတာ (app ထဲက **Connections** မှာ ခလုတ်တစ်ချက်နဲ့ `http://127.0.0.1:17863/mcp` ဖွင့်)

**ရိုးသားမှု စည်းမျဉ်း:** model က မလုပ်နိုင်တာ (emotion၊ whisper၊ shout) ကို တောင်းရင် လုပ်ပေးပြီးသလို
မဟန်ဆောင်ပါဘူး။ ရလဒ်ထဲမှာ "not applied" လို့ ပြပါတယ်။ `strict` mode ဆိုရင် လုံးဝ မထုတ်ပါ။

---

## ဘာနဲ့ ရေးထားလဲ (Tech stack)

| အပိုင်း | နည်းပညာ | ဘာအတွက်လဲ |
|---|---|---|
| TTS model | [Nara Mini v1](https://huggingface.co/YeeNyunn/nara-mini-v1) (Kokoro-82M အခြေခံ, ONNX, Apache-2.0) | မြန်မာ အသံထုတ်တဲ့ model |
| Model run | `onnxruntime` (CPU) | GPU မလိုဘဲ run နိုင်အောင် |
| Text frontend | Nara frontend ကို fork လုပ်ထားတာ (`third_party/nara_mini_v1/`) | မြန်မာစာ → အသံထွက် (G2P)။ "ကမ္ဘာ" လို အသံထွက် ပြင်ဆင်ချက်တွေ ဒီထဲမှာ |
| Voice engine | **Python 3.11**, **Pydantic 2**, NumPy, SoundFile | engine၊ capability စနစ်၊ schema |
| Audio DSP | NumPy (low-pass, fade, normalize), **FFmpeg** (pitch/tempo, MP3) | ဂျစ်ဂျစ်သံ လျှော့၊ အသံနိမ့်ချ၊ MP3 |
| MCP server | Official **MCP Python SDK** 1.30 (FastMCP), stdio + localhost streamable HTTP (uvicorn) | AI assistant တွေ ခေါ်သုံးဖို့ |
| Desktop app | **Tauri 2** (Rust) + **React 18** + **TypeScript** (strict) + **Vite** + **Tailwind CSS** | Windows app |
| App ↔ engine | Python worker process ကို stdin/stdout JSON-lines နဲ့ ချိတ် | model ကို တစ်ကြိမ်ပဲ load |
| Tests | **pytest**, **Vitest** + Testing Library, `cargo test` | စစ်ဆေးမှု |

---

## ဘယ်လို တည်ဆောက်ထားလဲ (Architecture)

```text
        Desktop app (Tauri 2)                 AI assistant (Claude)            Terminal
  React + TS + Tailwind UI                         │ MCP (stdio)                  │
        │ invoke                                    ▼                              ▼
  Rust: worker_call, read_output_audio        mvs-mcp (10 tools)              mvs-speak (CLI)
        │ stdin/stdout JSON lines                   │                              │
        ▼                                           ▼                              │
  mvs-worker (Python) ──────────►  VoiceStudioService (jobs, export, MCP on/off)   │
                                            │                                      │
                                            ▼                                      ▼
                     ┌──────────────── VoiceEngine (Phase 3) ◄──────────────────────┘
                     │  plan(): requested controls → native / dsp / engine / unsupported
                     │  render(): adapter → DSP → pauses
                     ▼
        Renderer (Phase 4): voice-direction JSON → segments → one WAV + report
                     │
                     ▼
        NaraAdapter: text frontend (fork) → ONNX encoder/decoder → 24 kHz audio
                     │
                     ▼
        DSP: low-pass (fizz) → pitch/tempo (ffmpeg) → peak normalize → silence
```

အဓိက အယူအဆ:

1. **Engine တစ်ခုတည်း:** app၊ CLI၊ MCP အားလုံး `VoiceEngine` ကိုပဲ ခေါ်ပါတယ်။ ဒါကြောင့် feature တစ်ခု ပြင်ရင် နေရာတိုင်းမှာ ပါသွားပါတယ်။
2. **Adapter:** model တစ်ခုချင်းစီကို adapter ဖိုင်တစ်ခုနဲ့ ချိတ်ပါတယ်။ နောက် model ပြောင်းရင် adapter အသစ် တစ်ခုပဲ ထည့်ရပါမယ်။
3. **Capability စနစ်:** control တစ်ခုချင်းကို `native` (model လုပ်)၊ `dsp` (ထွက်ပြီးမှ ပြင်)၊ `engine` (အသံတိတ် ထည့်)၊ `unsupported` (မရ) လို့ ခွဲပြီး ရလဒ်မှာ ရှင်းရှင်းလင်းလင်း ပြပါတယ်။
4. **Voice-direction schema 1.0:** ဇာတ်ညွှန်း format တစ်ခုတည်းကို app၊ MCP၊ preset အားလုံး သုံးပါတယ်။ Pydantic က အရင်းအမြစ် ဖြစ်ပြီး JSON Schema → TypeScript type ကို အလိုအလျောက် ထုတ်ပါတယ်။
5. **လုံခြုံရေး:** ရှိပြီးသား ဖိုင်ကို ဘယ်တော့မှ overwrite မလုပ်ပါ။ MCP ကို network port မဖွင့်ဘဲ stdio နဲ့ပဲ ချိတ်ပါတယ်။ Export ကို ခွင့်ပြုထားတဲ့ folder ထဲမှာပဲ ရေးပါတယ်။ UI ကို ဖိုင်လမ်းကြောင်း မပေးဘဲ `output_id` ပဲ ပေးပါတယ်။

---

## Folder ဖွဲ့စည်းပုံ

```text
src/myanmar_voice_studio/
  engine/            Voice engine: schemas, engine, adapters/nara.py, dsp, direction (schema), renderer, cli
  mcp_server/        MCP server (server.py), jobs/export (service.py), MCP on/off (registration.py)
  worker/            Desktop app အတွက် JSON-lines worker
  evaluation.py      Phase 2 evaluation helpers
apps/desktop/        Tauri 2 desktop app
  src/               React UI (components/, api/ client + preview mock)
  src-tauri/         Rust: worker bridge (worker.rs), commands (lib.rs)
third_party/nara_mini_v1/   ပြင်ဆင်ထားတဲ့ Nara text frontend (Apache-2.0, CHANGES.md)
config/
  voice_presets.json        Voice profile များ (male_calm, female_warm)
  mcp/                      Claude Desktop / Code config နမူနာ
schemas/             voice-direction-1.0.json + examples/
scripts/             Model evaluation script များ (MMS, MyanmarTTS, Nara)
tests/               Python tests
docs/                Phase တစ်ခုချင်းစီ လမ်းညွှန် + handoff
models/, outputs/, exports/, recordings/   Git ထဲ မပါ (weights၊ ထုတ်ထားတဲ့ အသံ၊ ကိုယ်ပိုင် အသံသွင်းချက်)
```

---

## Setup (Windows)

လိုအပ်တာ: Python 3.11 ([uv](https://github.com/astral-sh/uv) နဲ့ ထည့်ထား)၊ Node.js 20+၊ FFmpeg (PATH ထဲ)၊
desktop app အတွက် Rust + Visual Studio C++ Build Tools။

1. Engine environment ဖန်တီးပြီး package ထည့်ပါ:

```bash
python -m venv .venv-nara
```

```bash
.venv-nara/Scripts/python.exe -m pip install -e ".[dev,nara,mcp]"
```

2. Nara model ဖိုင် ဒေါင်းပါ (`models/nara-mini-v1/`, Git ထဲ မပါ):

```bash
.venv-nara/Scripts/python.exe -c "from huggingface_hub import snapshot_download as s; s('YeeNyunn/nara-mini-v1', local_dir='models/nara-mini-v1', allow_patterns=['onnx/*','config.json','LICENSE','NOTICE'])"
```

3. စမ်းကြည့်ပါ:

```bash
.venv-nara/Scripts/mvs-speak.exe say male_calm "မင်္ဂလာပါ" --out outputs
```

## အသုံးပြုနည်း

| ဘာလုပ်ချင်လဲ | Command |
|---|---|
| Voice စာရင်း | `.venv-nara/Scripts/mvs-speak.exe voices` |
| ဘာ control ရလဲ ကြည့် | `.venv-nara/Scripts/mvs-speak.exe caps male_calm` |
| ဇာတ်ညွှန်း စစ် | `.venv-nara/Scripts/mvs-speak.exe preview schemas/examples/stickman-story.json` |
| ဇာတ်ညွှန်း ထုတ် | `.venv-nara/Scripts/mvs-speak.exe render schemas/examples/stickman-story.json --out outputs --segments` |
| MCP server | `.venv-nara/Scripts/mvs-mcp.exe` (Claude ကနေ ဖွင့်ပါတယ်။ app ထဲက MCP page မှာ ON လုပ်ပါ) |
| Desktop app (dev) | `cd apps/desktop && npm install && npm run tauri dev` |
| UI ကိုပဲ browser မှာ | `cd apps/desktop && npm run dev` → http://localhost:1420 (preview mode, အသံအတု) |

## Tests

```bash
.venv-nara/Scripts/python.exe -m pytest -q
```

```bash
cd apps/desktop && npm test
```

```bash
cd apps/desktop/src-tauri && cargo test
```

လက်ရှိ: Python 78၊ Vitest 11၊ Rust 1 (worker အစစ်နဲ့ အသံထုတ်တာ အပါအဝင်) — အားလုံး pass ဖြစ်ပါတယ်။

---

## Phase အခြေအနေ

| Phase | အကြောင်းအရာ | အခြေအနေ | လမ်းညွှန် |
|---|---|---|---|
| 0 | Environment, GPU စစ် | ✅ | [phase-0](docs/phase-0.md) |
| 1 | Model ရွေးချယ်မှု | ✅ | [phase-1](docs/phase-1.md) |
| 2 | မြန်မာ အသံ အကဲဖြတ် (MMS → MyanmarTTS → F5 → **Nara**) | ✅ `male_calm` ကို user အတည်ပြု | [phase-2](docs/phase-2.md), [handoff](docs/burmese-tts-handoff.md) |
| 3 | Voice engine + capability စနစ် | ✅ | [phase-3](docs/phase-3.md) |
| 4 | Voice-direction schema + renderer | ✅ | [phase-4](docs/phase-4.md) |
| 5 | MCP server | ✅ (user ရဲ့ Claude နဲ့ မစမ်းရသေး) | [phase-5](docs/phase-5.md) |
| 6 | Desktop app | 🟡 dev mode မှာ run ပြီ။ installer နဲ့ SQLite history မပြီးသေး | [phase-6](docs/phase-6.md) |
| 7 | ကိုယ်ပိုင် အသံနဲ့ fine-tune | 🟡 QC tool + FP32 model ပြီး၊ အသံသွင်းချက် ၃၀ မိနစ်+ စောင့်နေ | [phase-7](docs/phase-7.md), [recording-guide](docs/recording-guide.md) |
| 8–11 | Expressive speech၊ timeline/presets၊ installers၊ GitHub release | ⏳ | [architecture](docs/architecture.md) |

---

## လိုင်စင်

- ဒီ project ရဲ့ source code: **MIT** ([LICENSE](LICENSE))
- Nara Mini v1 model နဲ့ frontend: **Apache-2.0** ([third_party/nara_mini_v1/LICENSE](third_party/nara_mini_v1/LICENSE))။ Model ရဲ့ voice data ကို VoxCPM2 နဲ့ ဖန်တီးထားပါတယ်။ Public release မလုပ်ခင် ပြန်စစ်ပါ။
- Evaluation မှာ သုံးခဲ့တဲ့ MMS နဲ့ F5-Myanmar-TTS က **CC-BY-NC** ဖြစ်လို့ စီးပွားဖြစ် မသုံးရပါ။ App ထဲမှာ မပါပါ။
- FFmpeg၊ model weights နဲ့ dataset တွေမှာ သီးသန့် လိုင်စင်တွေ ရှိပါတယ်။ Model weights နဲ့ ကိုယ်ပိုင် အသံသွင်းချက်တွေကို Git ထဲ မထည့်ပါ။
#   m y a n m a r - t t s - v o i c e - c l o n e  
 #   d r a m a - r e c a p - a i  
 