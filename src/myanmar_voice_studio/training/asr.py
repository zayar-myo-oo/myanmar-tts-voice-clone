"""Burmese ASR for the own-voice dataset (freococo/myanmar_asr, Apache-2.0, 23.8M Conformer CTC).

Two jobs:
1. Free speech: draft transcripts for recordings without text -> `<name>.draft.txt`
   (the user reviews and renames to `.txt`; drafts are never used for training as-is).
2. Script reading: compare what was heard with the script line and flag likely misreads
   by syllable error rate (SER).

Needs torch + torchaudio (run from .venv-f5). Model files: models/myanmar_asr/.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

# Burmese syllable break (sylbreak-style): a new syllable starts at a consonant/independent
# vowel that is not stacked (preceded by ္) and not killed (followed by optional ့/း and ် or ္).
_CONS = "က-အဣ-ဧဩဪဿ၌-၏"
_SYL = re.compile(rf"(?<!္)([{_CONS}])(?![ှ]?[့း]?[်္])")


def syllables(text: str) -> list[str]:
    text = re.sub(r"[\s၊။!?,.\"'()\-:;]+", "", text)
    marked = _SYL.sub(r"|\1", text)
    return [s for s in marked.split("|") if s]


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def ser(reference: str, hypothesis: str) -> float:
    ref, hyp = syllables(reference), syllables(hypothesis)
    return edit_distance(ref, hyp) / max(1, len(ref))


class BurmeseASR:
    def __init__(self, model_dir: Path, device: str | None = None):
        import torch
        import torchaudio

        self.torch, self.torchaudio = torch, torchaudio
        model_dir = Path(model_dir)
        spec = importlib.util.spec_from_file_location("myanmar_asr_model", model_dir / "model.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # reviewed: pure PyTorch module definitions
        self.blank = mod.BLANK_ID
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.token2id = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))
        self.id2token = {v: k for k, v in self.token2id.items()}
        cmvn = json.loads((model_dir / "cmvn.json").read_text(encoding="utf-8"))
        self.mean = torch.tensor(cmvn["mean"], dtype=torch.float32, device=self.device)
        self.std = torch.tensor(cmvn["std"], dtype=torch.float32, device=self.device)
        self.model = mod.load_model(weights_path=str(model_dir / "model.safetensors"),
                                    vocab_size=len(self.token2id), device=self.device)
        self.mel = torchaudio.transforms.MelSpectrogram(sample_rate=16000, n_fft=400, win_length=400,
                                                        hop_length=160, n_mels=80).to(self.device)

    def transcribe_array(self, wav: np.ndarray, sr: int) -> str:
        torch = self.torch
        with torch.inference_mode():
            x = torch.from_numpy(np.asarray(wav, dtype=np.float32)).unsqueeze(0)
            if sr != 16000:
                x = self.torchaudio.functional.resample(x, sr, 16000)
            if x.shape[-1] < 8000:
                return ""
            mel = torch.log(self.mel(x.to(self.device)).clamp(min=1e-5))
            mel = ((mel - self.mean.unsqueeze(-1)) / (self.std.unsqueeze(-1) + 1e-9)).transpose(1, 2)
            logits, lens = self.model(mel)
            ids = torch.argmax(logits, dim=-1)[0, : int(lens[0])].cpu().tolist()
        out, prev = [], -1
        for i in ids:
            if i != prev and i != self.blank:
                out.append(i)
            prev = i
        return "".join(self.id2token[i] for i in out if self.id2token.get(i))

    def transcribe_file(self, path: Path) -> str:
        import soundfile as sf

        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        return self.transcribe_array(audio.mean(axis=1), sr)


def best_script_match(heard: str, table: dict[str, str]) -> tuple[str | None, float]:
    """Find the script line closest to what was heard (lowest SER)."""
    best_id, best = None, 9.9
    h = syllables(heard)
    for rid, text in table.items():
        ref = syllables(text)
        if abs(len(ref) - len(h)) > max(4, len(ref)):  # cheap length filter
            continue
        s = edit_distance(ref, h) / max(1, len(ref))
        if s < best:
            best_id, best = rid, s
    return best_id, round(best, 3)


def match_folder(folder: Path, script: Path, model_dir: Path, accept_ser: float = 0.0) -> list[dict]:
    """For clips with arbitrary names: identify which script line was read.

    SER <= accept_ser (default 0: exact) -> `<name>.txt` with the script text (correct spelling).
    Any difference could be a changed word, so it must be reviewed: the ASR text goes to a draft.
    Otherwise -> `<name>.draft.txt` with the ASR text for the user to fix (free speech / changed wording).
    Existing .txt / .draft.txt files are never overwritten.
    """
    from .dataset import load_script_table

    table = load_script_table(script)
    asr = BurmeseASR(model_dir)
    rows = []
    for wav in sorted(Path(folder).glob("*.wav")):
        heard = asr.transcribe_file(wav)
        rid, s = best_script_match(heard, table) if heard else (None, 9.9)
        row = {"file": wav.name, "heard": heard, "match": rid, "ser": s,
               "expected": table.get(rid, "") if rid else ""}
        txt, draft = wav.with_suffix(".txt"), wav.with_name(wav.stem + ".draft.txt")
        if txt.exists():
            row["status"] = "has-txt"
        elif rid and s <= accept_ser:
            txt.write_text(table[rid] + "\n", encoding="utf-8")
            row["status"] = "ok"
        else:
            if not draft.exists():
                draft.write_text(heard + "\n", encoding="utf-8")
            row["status"] = "draft"
        rows.append(row)
    # Machine-readable results for the desktop review screen.
    (Path(folder) / "asr_matches.json").write_text(
        json.dumps({r["file"]: {k: r[k] for k in ("heard", "match", "ser", "expected")} for r in rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def run(folder: Path, script: Path | None, model_dir: Path, mismatch_ser: float = 0.25) -> list[dict]:
    from .dataset import load_script_table

    folder = Path(folder)
    table = load_script_table(script) if script and Path(script).exists() else {}
    asr = BurmeseASR(model_dir)
    rows = []
    for wav in sorted(folder.glob("*.wav")):
        heard = asr.transcribe_file(wav)
        row = {"file": wav.name, "heard": heard}
        txt = wav.with_suffix(".txt")
        expected = txt.read_text(encoding="utf-8").strip() if txt.exists() else table.get(wav.stem)
        if expected:
            row["expected"] = expected
            row["ser"] = round(ser(expected, heard), 3)
            row["status"] = "ok" if row["ser"] <= mismatch_ser else "check"
        else:
            draft = wav.with_name(wav.stem + ".draft.txt")
            if not draft.exists():
                draft.write_text(heard + "\n", encoding="utf-8")
            row["status"] = "draft"
            row["draft"] = draft.name
        rows.append(row)
    return rows


def write_review(rows: list[dict], dest: Path) -> Path:
    lines = ["# Transcript review", "",
             "- **ok**: matches the script. **check**: likely misread — listen and re-record or edit the text.",
             "- **draft**: free speech — fix the `.draft.txt`, then rename it to `.txt`.", "",
             "| file | status | SER | heard (ASR) | expected |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['file']} | {r['status']} | {r.get('ser', '')} | {r['heard']} | {r.get('expected', '')} |")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="mvs-asr")
    ap.add_argument("folder", type=Path)
    ap.add_argument("--script", type=Path, default=Path("docs/recording-script.md"))
    ap.add_argument("--model-dir", type=Path, default=Path("models/myanmar_asr"))
    ap.add_argument("--max-ser", type=float, default=0.25, help="flag script lines above this syllable error rate")
    ap.add_argument("--match-script", action="store_true",
                    help="clips have arbitrary names: find which script line each one is")
    args = ap.parse_args(argv)
    if args.match_script:
        rows = match_folder(args.folder, args.script, args.model_dir, accept_ser=0.0)
        lines = ["# Script matching", "", "- **ok**: matched a script line; `.txt` written with the exact script text.",
                 "- **draft**: no close match (free speech or changed wording) — fix `.draft.txt`, rename to `.txt`.", "",
                 "| file | status | match | SER | heard (ASR) | script |", "|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['file']} | {r['status']} | {r['match'] or ''} | {r['ser']} | {r['heard']} | {r['expected']} |")
        review = args.folder / "transcript_review.md"
        review.write_text("\n".join(lines) + "\n", encoding="utf-8")
        counts = {s: sum(r["status"] == s for r in rows) for s in ("ok", "draft", "has-txt")}
        for r in rows:
            print(f"{r['status']:6} {r['file']:14} {r['match'] or '-':5} {r['ser']:>6}  {r['heard']}")
        print(f"\n{counts} — review: {review}")
        return 0
    rows = run(args.folder, args.script, args.model_dir, args.max_ser)
    review = write_review(rows, args.folder / "transcript_review.md")
    counts = {s: sum(r["status"] == s for r in rows) for s in ("ok", "check", "draft")}
    for r in rows:
        print(f"{r['status']:5} {r['file']:20} {r.get('ser', ''):>6}  {r['heard']}")
    print(f"\n{counts} — review: {review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
