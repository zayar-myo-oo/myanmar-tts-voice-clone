# Third-party licenses — Drama Recap Studio (`recap_engine`)

Everything below runs locally. Nothing is uploaded anywhere. Versions are the ones installed in
`.venv-recap` on 2026-11-18.

## Models

| Model | Used for | License | Notes |
|---|---|---|---|
| Nara Mini v1 (`YeeNyunn/nara-mini-v1`) | Burmese TTS (via the existing voice studio) | Apache-2.0 | Already in `models/nara-mini-v1`, see voice studio docs |
| Demucs `htdemucs` (v4) | Vocal / accompaniment separation | MIT (code + weights) | Downloaded to the torch hub cache on first run |
| Whisper `large-v3` / `medium` (CTranslate2 conversion by Systran) | Mandarin speech recognition | MIT | Downloaded to the Hugging Face cache on first run |
| PP-OCRv5 (PaddleOCR) Chinese detection + recognition | Hard-sub OCR | Apache-2.0 | Downloaded by PaddleX on first run |
| OpenCLIP ViT-B-32 `laion2b_s34b_b79k` | Matching narration to frames | MIT (code + weights) | Trained on LAION-2B |
| Qwen3 4B / 8B (Ollama) | Story analysis, script, translation | Apache-2.0 | `ollama pull qwen3:8b` |
| Optional vision model in Ollama (e.g. Qwen2.5-VL 3B/7B, Gemma) | Frame captions | Qwen2.5-VL 3B: Qwen Research License (non-commercial); 7B: Apache-2.0; Gemma: Gemma Terms of Use | Picked automatically only if already installed. Personal use only. |

## Libraries

| Library | License |
|---|---|
| yt-dlp | Unlicense |
| FFmpeg / ffprobe (gyan.dev full build) | GPL-3.0 (build includes GPL parts); libass ISC, HarfBuzz MIT |
| faster-whisper, CTranslate2 | MIT |
| demucs | MIT |
| PaddleOCR, PaddleX, PaddlePaddle | Apache-2.0 |
| PySceneDetect | BSD-3-Clause |
| OpenCV (opencv-python-headless) | Apache-2.0 |
| open_clip_torch | MIT |
| PyTorch, torchaudio, torchvision | BSD-3-Clause |
| FastAPI, Pydantic | MIT |
| httpx | BSD-3-Clause |
| NumPy | BSD-3-Clause |
| soundfile | BSD-3-Clause |
| Pillow | MIT-CMU (HPND) |
| Ollama | MIT |

## Fonts

| Font | License | Bundled? |
|---|---|---|
| Noto Sans Myanmar (Regular, Bold) | SIL Open Font License 1.1 | Yes, `fonts/` |
| Padauk Book (Regular, Bold) | SIL Open Font License 1.1 | Yes, `fonts/` (copied from Windows) |
| Myanmar Text | Microsoft Windows system font | No. Used from Windows if present. |
| Pyidaungsu | Myanmar government font; no clear redistribution license | No. Used only if you have it installed. |

## Product reference

The DeepRecap workflow was used only as a feature reference. No branding, text or assets were copied.

## YuNet face detector (face_detection_yunet_2023mar.onnx)
- Source: https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- License: MIT (Shiqi Yu et al.). Used locally by recap_engine.transform for smart reframing; file kept in models/ (git-ignored).


## Belle-whisper-large-v3-turbo-zh (CTranslate2 conversion)
- Source: https://huggingface.co/BELLE-2/Belle-whisper-large-v3-turbo-zh (CT2: flateon/Belle-whisper-large-v3-turbo-zh-ct2)
- License: Apache-2.0. Stored in models/ (git-ignored).

## Gemma 4 (gemma4:e4b / 12b / 26b via Ollama)
- Source: https://ai.google.dev/gemma — used locally through Ollama; license terms per the Gemma model card.

