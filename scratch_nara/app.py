import spaces  # noqa: F401  (no-op off ZeroGPU; keeps the pattern valid if moved to GPU)

import json
import os
import re
from pathlib import Path

import gradio as gr
import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download

from frontend.english import to_tokens
from frontend.my_numbers import verbalize
from frontend.nara_frontend import phonemize, prepare_names

MODEL_ID = "YeeNyunn/nara-mini-v1"
VOICES = ["shoon", "thazin", "ko-banyar", "htet-myat"]
VOICE_LABELS = {
    "shoon": "Shoon (female)",
    "thazin": "Thazin (female)",
    "ko-banyar": "Ko Banyar (male)",
    "htet-myat": "Htet Myat (male)",
}
SAMPLE_RATE = 24000
MAX_CHARS = 2000
PIECE_GAP = 4800  # 0.2 s of silence between split pieces, as in synthesize.py

CSS = """
#col-container { max-width: 1100px; margin: 0 auto; }
.dark .gradio-container { color: var(--body-text-color); }
"""


def split_speech(text, limit=200):
    """Split text into synthesizable pieces (verbatim from the model's synthesize.py)."""
    units = []
    for sentence in re.split(r'(?<=[။!?…\n])\s*', text):
        for clause in re.split(r'(?<=၊)\s*', sentence):
            while len(clause) > limit:
                cut = clause.rfind(' ', 0, limit)
                if cut <= 0:
                    cut = limit
                units.append(clause[:cut])
                clause = clause[cut:].strip()
            if clause.strip():
                units.append(clause.strip())
    pieces = []
    current = ''
    for unit in units:
        if current and len(current) + 1 + len(unit) > limit:
            pieces.append(current)
            current = unit
        else:
            current = f'{current} {unit}'.strip()
    if current:
        pieces.append(current)
    return pieces


def _load_voice(voice):
    """Download a voice's ONNX graphs + metadata and build CPU inference sessions."""
    enc_path = hf_hub_download(MODEL_ID, f"onnx/{voice}/encoder.onnx", repo_type="model")
    dec_path = hf_hub_download(MODEL_ID, f"onnx/{voice}/decoder.onnx", repo_type="model")
    voice_path = hf_hub_download(MODEL_ID, f"onnx/{voice}/voice.json", repo_type="model")
    metadata = json.loads(Path(voice_path).read_text(encoding="utf-8"))
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 2))
    options.inter_op_num_threads = 1
    encoder = ort.InferenceSession(enc_path, options, providers=["CPUExecutionProvider"])
    decoder = ort.InferenceSession(dec_path, options, providers=["CPUExecutionProvider"])
    return {"encoder": encoder, "decoder": decoder, "meta": metadata}


VOICEDATA = {voice: _load_voice(voice) for voice in VOICES}


def synthesize_piece(voice_data, chars):
    """Run encoder + decoder for one phonemized piece. Mirrors synthesize.py exactly."""
    meta = voice_data["meta"]
    tokens = [meta["vocab"][c] for c in chars if c in meta["vocab"]]
    if not tokens:
        raise gr.Error("A passage produced no phonemes — please enter Burmese or English text.")
    if len(tokens) > 508:
        raise gr.Error("A passage exceeds the phoneme context limit — try shorter sentences.")
    index = int(np.argmin(np.abs(np.asarray(meta["centers"]) - len(tokens))))
    style = np.asarray([meta["styles"][index]], dtype=np.float32)
    durations, prosody, encoded_text = voice_data["encoder"].run(
        ["durations", "prosody", "text"],
        {"tokens": np.asarray([[0, *tokens, 0]], dtype=np.int64), "style": style},
    )
    if durations.min() < 1 or not 1 <= durations.sum() <= 20000:
        raise gr.Error("The model predicted an invalid duration for this text.")
    samples = voice_data["decoder"].run(
        None,
        {
            "prosody": np.repeat(prosody, durations[0], axis=2),
            "text": np.repeat(encoded_text, durations[0], axis=2),
            "style": style,
        },
    )[0].reshape(-1)
    if samples.size < 2400 or not np.isfinite(samples).all():
        raise gr.Error("The model produced invalid audio for this text.")
    return np.clip(samples, -1, 1).astype(np.float32)


def generate(text, voice, normalize_numbers, progress=gr.Progress()):
    """Convert Burmese or English text to speech with a Nara Mini v1 preset voice.

    Args:
        text: Text to speak — Burmese, English, or a mix of both.
        voice: One of shoon, thazin, ko-banyar, htet-myat.
        normalize_numbers: Read numbers aloud in Burmese before synthesis.
        progress: Gradio progress bar.
    Returns:
        24 kHz mono audio.
    """
    text = (text or "").strip()
    if not text:
        raise gr.Error("Please enter some text to synthesize.")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        gr.Warning(f"Text truncated to {MAX_CHARS} characters.")

    voice_data = VOICEDATA[voice]
    if normalize_numbers:
        text = verbalize(text)

    pieces = split_speech(text)
    chunks, has_audio = [], False
    for i, piece in enumerate(pieces):
        chars = phonemize(to_tokens(prepare_names(piece)))
        samples = synthesize_piece(voice_data, chars)
        if has_audio:
            chunks.append(np.zeros(PIECE_GAP, dtype=np.float32))
        chunks.append(samples)
        has_audio = True
        progress((i + 1) / len(pieces), desc=f"Synthesized {i + 1}/{len(pieces)} pieces")
    return (SAMPLE_RATE, np.concatenate(chunks))


with gr.Blocks() as demo:
    with gr.Column(elem_id="col-container"):
        gr.Markdown(
            """
            # 🇲🇲 Nara Mini v1 — Burmese & English Text-to-Speech
            Kokoro-based TTS adapted for **Burmese (မြန်မာ)** and **English**, with four
            preset voices. Enter text in either language — or mix both in one sentence.
            Runs the model's official ONNX pipeline on CPU. [Model card](https://huggingface.co/YeeNyunn/nara-mini-v1)
            """
        )
        with gr.Row():
            with gr.Column():
                text = gr.Textbox(
                    label="Text",
                    placeholder="မင်္ဂလာပါ။ Type Burmese or English here…",
                    lines=5,
                    max_lines=12,
                )
                voice = gr.Radio(
                    choices=[(VOICE_LABELS[v], v) for v in VOICES],
                    value="shoon",
                    label="Voice",
                )
                with gr.Accordion("Options", open=False):
                    normalize_numbers = gr.Checkbox(
                        value=True,
                        label="Read numbers aloud in Burmese (e.g. ၁၂၀၀ → တစ်ထောင့်နှစ်ရာ)",
                    )
                run = gr.Button("Synthesize", variant="primary")
            with gr.Column():
                audio_out = gr.Audio(
                    label="Generated speech",
                    type="numpy",
                    waveform_options=gr.WaveformOptions(sample_rate=SAMPLE_RATE),
                )

        run.click(
            generate,
            inputs=[text, voice, normalize_numbers],
            outputs=audio_out,
            api_name="generate",
        )

        gr.Examples(
            examples=[
                # Mixed Burmese + English — the model card's own showcase example
                ["မင်္ဂလာပါ။ Hello world.", "shoon", True],
                # Number normalization: digits read aloud in Burmese
                ["ကျွန်တော် ၁၉၇၅ ခုနှစ် မှာ မွေးဖွားခဲ့ပါတယ်။", "ko-banyar", True],
                # Plain Burmese sentence
                ["ဒီနေ့ ရာသီဥတု က အရမ်းကောင်းပါတယ်။", "thazin", True],
                # English-only
                ["Hello! This is English speech from the Nara Mini model.", "htet-myat", True],
                # Numbers kept as digits (normalization off)
                ["ငါးနာရီ မှာ ဘူတာရုံ မှာ တွေ့ကြစို့။", "shoon", False],
            ],
            inputs=[text, voice, normalize_numbers],
            outputs=audio_out,
            fn=generate,
            cache_examples=True,
            cache_mode="lazy",
        )

demo.launch(mcp_server=True, theme=gr.themes.Citrus(), css=CSS)
