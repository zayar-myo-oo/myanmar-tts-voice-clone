---
title: Nara Mini v1 TTS
emoji: 🗣️
colorFrom: indigo
colorTo: green
sdk: gradio
sdk_version: 6.32.0
app_file: app.py
short_description: Burmese & English TTS with four preset voices
python_version: "3.12"
license: apache-2.0
---

# Nara Mini v1 — Burmese & English Text-to-Speech

A demo of [YeeNyunn/nara-mini-v1](https://huggingface.co/YeeNyunn/nara-mini-v1), a
Kokoro-based TTS model adapted for Burmese (မြန်မာ) and English with four preset
voices: **Shoon**, **Thazin**, **Ko Banyar**, and **Htet Myat**.

- Type text in Burmese, English, or mix both languages in one sentence.
- Optional Burmese number normalization reads digits aloud (e.g. ၁၂၀၀ → တစ်ထောင့်နှစ်ရာ).
- The app runs the model's official ONNX encoder/decoder pipeline on CPU
  (24 kHz mono output).

## Acknowledgments

- Base model: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) by hexgrad (Apache 2.0)
- Synthetic speech for the voices: [VoxCPM2](https://huggingface.co/openbmb/VoxCPM2) by OpenBMB (Apache 2.0)
- Nara Mini v1 is released under Apache 2.0 — see the
  [model card](https://huggingface.co/YeeNyunn/nara-mini-v1) for details.
