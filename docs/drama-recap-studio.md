# Drama Recap Studio

ကိုယ့်ကွန်ပျူတာထဲမှာပဲ (local, free) တရုတ် drama တွေကို **မြန်မာ recap / dub / စာတန်းထိုး** လုပ်ပေးတဲ့ web app ပါ။
Optional အနေနဲ့ ကိုယ်ပိုင် API key (Claude, OpenAI, ElevenLabs, AssemblyAI, OpenRouter) တွေနဲ့လည်း သုံးလို့ရပါတယ်။

*A local-first Burmese recap / dub / subtitle studio for Chinese short dramas, plus an animation studio for
2D-characters-in-a-3D-world shorts. Runs on your own GPU; cloud APIs are optional.*

## Features
| | |
|---|---|
| **Modes** | AI Recap (story summary + Burmese narration), Pro Dub (line-by-line Burmese voice on the original timing), Subtitle (original audio + Burmese subtitles) |
| **Studio editor** | Draw blur boxes / crop on the video, drag & resize the caption, caption style (font, colour, outline, box, position, width), watermark / logo, frame border, moving watermark |
| **Quality** | Frame-accurate A/V sync, high-quality NVENC encode, -14 LUFS loudness, QC report, line-by-line script editing that only regenerates the changed line |
| **Speed** | Auto-scaling job workers, parallel clip render and TTS, one GPU model at a time (8 GB cards) |
| **Extras** | Voiceover (script → voice + SRT), Source Finder (find the original drama), video downloader, video splitter (Part 1/2/3), Post Kit (title, caption, hashtags, thumbnail), rights check |
| **Animation Studio** | Script → cartoon short: voice per speaker, scene code written by Claude (your API key), typecheck + visual check loop, Remotion render |
| **Models (local)** | Whisper large-v3-turbo, gemma4 (Ollama), Demucs, RapidOCR, OpenCLIP, YuNet, Nara Mini TTS |
| **Optional APIs** | Claude, OpenAI, ElevenLabs, AssemblyAI, OpenRouter, Microsoft neural voices (Thiha / Nilar) |

## Requirements
- Windows 10/11, NVIDIA GPU (8 GB+ VRAM), 32 GB RAM recommended
- Python 3.11, [FFmpeg](https://ffmpeg.org) on PATH, [Ollama](https://ollama.com) (`ollama pull gemma4:26b` and `gemma4:e4b`)
- The voice studio's Nara Mini venv (`.venv-nara`, see the main README) for local Burmese TTS
- Animation Studio only: Node.js + a Remotion shorts project (e.g. one made with the `cartoon-3d-short` skill)

## Install
```powershell
py -3.11 -m venv .venv-recap
.venv-recap\Scripts\pip install torch==2.7.1 torchaudio==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
.venv-recap\Scripts\pip install -r requirements-recap.txt
.venv-recap\Scripts\pip install -e . --no-deps
```
Optional face model for smart reframing: put `face_detection_yunet_2023mar.onnx`
([opencv_zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet), MIT) in `models/`.

## Run
Double-click **`Drama Recap Studio.bat`** (starts Ollama + the server and opens the app), or:
```powershell
.venv-recap\Scripts\python -m recap_engine.server
```
Then open http://127.0.0.1:8765. Command line: `python -m recap_engine.api new <video or URL> --mode recap|pro|subtitle`.

## API keys (optional)
Settings → ☁ Cloud / API Key. Keys are stored only in `config/api_keys.json` (git-ignored) and are sent only to
their own provider. Never paste keys into chats, issues or commits.

## Tests
```powershell
.venv-recap\Scripts\python -m pytest tests/recap -q
```

## Responsible use
Visual edits do **not** remove copyright and do not make a video "copyright-free". Use footage you own or have
permission for, credit the original, and use your own branding only. The rights check in the app is a reminder,
not legal advice.

## Third-party
See [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).
