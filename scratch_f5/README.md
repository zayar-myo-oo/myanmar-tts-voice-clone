---
language:
- my
license: cc-by-nc-4.0
tags:
- text-to-speech
- tts
- burmese
- myanmar
- f5-tts
- voice-cloning
- flow-matching
- mya
pipeline_tag: text-to-speech
---

# 🇲🇲 F5-TTS Burmese v2 (1,025,604 Updates Foundation Model)

The official **v2 release** of the F5-TTS (Flow-Matching Diffusion Transformer) Burmese speech foundation model, trained on **794.5+ hours of Burmese speech** across **36 full epochs (1,025,604 updates)**.

> *"They are fighting for people's freedom. I am fighting for the language's freedom.  
> I just want to preserve their beautiful, lovely, and brave voices embedded in AI to last forever — marking the first time in history for a massive Burmese open-source TTS foundation model."*

---

## 🌟 What's New in v2
- **Over 1 Million Updates:** Pushed training from 569,780 steps (v1) to **1,025,604 updates (36 epochs)** for significantly tighter phonetic alignment and tone clarity.
- **50% Smaller Model (FP16):** Pruned weights down from 1.35 GB to **674 MB** for 2x faster downloads and lower GPU VRAM consumption.
- **Production-Grade Zero-Shot Voice Cloning:** Natural conversational cadence, improved tone handling on conjuncts and Pāḷi loanwords, and zero cut-offs.
- **Raw Checkpoints Available:** Intermediate checkpoints (`model_1020000.pt`, `model_1025000.pt`, and `model_last.pt`) are included under `checkpoints/` for developers wanting to continue fine-tuning.

---

## ⚡ Quickstart: Python Package (`f5-myanmar-tts`)

The easiest way to use this model is with the official PyPI package:

```bash
pip install --upgrade f5-myanmar-tts
```

### Python (Just 3 lines):
```python
from f5_myanmar_tts import MyanmarTTS

# Auto-downloads lightweight v2 FP16 model (~674MB) on first run
tts = MyanmarTTS()

# Generate Burmese speech
tts.speak(
    "လူသားတွေ အားလုံးကို အယုတ်အလတ်အမြတ်မရွေး ချစ်ခင်လေးစားပါ", 
    output_file="speech.wav"
)
```

### Voice Cloning (Clone any voice in 3–5 seconds):
```python
tts.speak(
    text="ဒါကြောင့် အုံ့မှိုင်းနေတဲ့ ကောင်းကင်ကို အမိန့်ပေးပြီး မိုးကောင်းကင် တံခါးတွေကို ဖွင့်လိုက်တယ်",
    ref_audio="my_voice.wav",
    ref_text="အပြင် မသွားရလို့ စိတ်ညစ်နေပါတယ် မိုးတွေ တအား ရွာနေပါတယ်",
    output_file="cloned_speech.wav"
)
```

---

## 📊 Model Specifications

| Parameter | Specification |
| :--- | :--- |
| **Architecture** | Diffusion Transformer (DiT Base) |
| **Parameters** | 337,138,310 (~337M) |
| **Layers / Heads / Dim** | 22 layers, 16 heads, dim=1024, text_dim=512 |
| **Training Steps** | **36 Epochs (1,025,604 updates)** |
| **Training Audio** | **794.5+ Hours** Burmese Speech |
| **Sampling Rate** | 24,000 Hz |
| **Vocoder** | Vocos (24kHz Mel) |
| **Vocabulary** | 2,626 Burmese & Pāḷi Unicode Tokens |
| **Format** | Safetensors (674 MB FP16 Pruned EMA weights) |
| **License** | Creative Commons Attribution-NonCommercial 4.0 (CC BY-NC 4.0) |

---

## 🕊️ Dedication & Acknowledgements
1. **GEMINI AI (Google):** Co-engineering partner through every line of code, architecture debugging, memory optimizations, and fine-tuning pipelines.
2. **F5-TTS Research Team:** Yushen Chen and the creators of F5-TTS for open-sourcing this world-class flow-matching speech architecture.
3. **The Brave Voices of Freedom:** National Unity Government (NUG), PVTV broadcasters, independent journalists, and creators whose voices form the backbone of this heritage preservation project.

## 📜 License
Released under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** license. Dedicated to free public research, language preservation, education, and open-source innovation.