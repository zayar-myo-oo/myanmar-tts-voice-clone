"""Burmese text utilities: Zawgyi detection/conversion, normalisation,
pronunciation dictionary, phrase splitting for captions."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

MY = re.compile(r"[က-႟ꩠ-ꩿ]")
# Characters/sequences that appear (almost) only in Zawgyi encoded text.
ZG_HINTS = re.compile(r"[ၚၠ-႗]|ေ[က-အ]|ျ[က-အ]|^ေ|\sေ|္[^က-အ]")
UNI_HINTS = re.compile(r"[ှဿၐ-ၙ]|္[က-အ]|[က-အ]ျ|[က-အ]ေ")


def is_zawgyi(text: str) -> bool:
    if not MY.search(text):
        return False
    try:  # prefer Google's probabilistic detector if installed
        from myanmartools import ZawgyiDetector  # type: ignore
        return ZawgyiDetector().get_zawgyi_probability(text) > 0.95
    except Exception:
        pass
    return len(ZG_HINTS.findall(text)) > len(UNI_HINTS.findall(text))


# Minimal rule-based Zawgyi -> Unicode (covers the common cases; Rabbit-style).
_ZG_RULES: list[tuple[str, str]] = [
    ("ၪ", "ဉ"), ("ဥ(?=[္ာ])", "ဉ"), ("ဦ", "ဦ"),
    ("ၫ", "ည"), ("႐", "ရ"), ("၀", "၀"), ("ႏ", "န"),
    ("ဒ", "ဒ"), ("ဓ", "ဓ"), ("[ွႇ]", "ှ"), ("ြ", "ွ"),
    ("[ျၾ-ႄ]", "ြ"), ("[်ၽ]", "ျ"), ("္", "်"),
    ("ၮ", "ဍ္ဍ"), ("ၯ", "ဍ္ဎ"), ("႑", "ဏ္ဍ"),
    ("႒", "ဋ္ဌ"), ("႗", "ဋ္ဋ"), ("၎", "၎င်း"),
    ("ႆ", "ဿ"), ("ၚ", "ါ်"), ("ဳ", "ု"), ("ဴ", "ူ"),
    ("ႈ", "ှု"), ("ႉ", "ှူ"), ("ႊ", "ွှ"),
    ("ၤ", "င်္"), ("ႋ", "င်္ိ"), ("ႌ", "င်္ီ"),
    ("ႍ", "င်္ံ"), ("႔|႕", "့"), ("ၠ", "္က"),
    ("ၡ", "္ခ"), ("ၢ", "္ဂ"), ("ၣ", "္ဃ"), ("ၥ", "္စ"),
    ("[ၦၧ]", "္ဆ"), ("ၨ", "္ဇ"), ("ၩ", "္ဈ"),
    ("ၬ", "္ဋ"), ("ၭ", "္ဌ"), ("ၰ", "္ဏ"),
    ("[ၱၲ]", "္တ"), ("႖", "္တွ"), ("[ၳၴ]", "္ထ"),
    ("ၵ", "္ဒ"), ("ၶ", "္ဓ"), ("ၷ", "္န"), ("ၸ", "္ပ"),
    ("ၹ", "္ဖ"), ("ၺ", "္ဗ"), ("ၻ", "္ဘ"), ("ၼ", "္မ"),
    ("ႅ", "္လ"),
]


def zawgyi_to_unicode(text: str) -> str:
    try:
        from icu import Transliterator  # type: ignore
        return Transliterator.createInstance("Zawgyi-my").transliterate(text)
    except Exception:
        pass
    s = text
    for a, b in _ZG_RULES:
        s = re.sub(a, b, s)
    # reorder: E-vowel (1031) and medial ra (103C) typed before the consonant in Zawgyi
    s = re.sub(r"ေ([က-အဿ])((?:္[က-အ])?)([ျ-ှ]*)", r"\1\2\3ေ", s)
    s = re.sub(r"ြ([က-အ])((?:္[က-အ])?)", r"\1\2ြ", s)
    s = re.sub(r"([ြ])([ျ])", r"\2\1", s)
    s = re.sub(r"(ှ)(ွ)", r"\2\1", s)
    s = re.sub(r"(ံ)(ု)", r"\2\1", s)
    s = re.sub(r"(့)(်)", r"\2\1", s)
    return s


def normalize(text: str) -> str:
    if is_zawgyi(text):
        text = zawgyi_to_unicode(text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("​", "").replace("‌", "")
    text = re.sub(r"[ \t]+", " ", text)
    # common typing errors: 0 (U+1040 zero) vs ဝ (wa)
    text = re.sub(r"(?<![၀-၉])၀(?=[ါ-ှ])", "ဝ", text)
    return text.strip()


# ---------------------------------------------------------------- pronunciation dictionary
def dict_path() -> Path:
    env = os.environ.get("RECAP_PRONUNCIATION")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "config" / "recap_pronunciation.json"


def load_pronunciations(path: Path | None = None) -> dict[str, str]:
    p = path or dict_path()
    if not p.exists():
        return {}
    data = json.loads(p.read_text("utf-8"))
    return {k: v for k, v in data.get("entries", data).items() if isinstance(v, str)}


def save_pronunciations(entries: dict[str, str], path: Path | None = None) -> None:
    p = path or dict_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), "utf-8")


def apply_pronunciations(text: str, entries: dict[str, str]) -> str:
    for k in sorted(entries, key=len, reverse=True):
        text = text.replace(k, entries[k])
    return text


# ---------------------------------------------------------------- phrase splitting
SENT_END = re.compile(r"(?<=[။!?])\s*")
PHRASE_END = re.compile(r"(?<=[၊,])\s*|\s+")
# Burmese syllable boundary: before a consonant that is not followed by asat/virama (stacked).
SYL = re.compile(r"(?<![္])(?=[က-ဪဿ၌-၏](?![်္]))")


def syllables(text: str) -> list[str]:
    parts = [x for x in SYL.split(text) if x]
    return parts


def display_len(text: str) -> int:
    """Approximate visual width in 'syllable-ish' units (combining marks don't count)."""
    return sum(1 for ch in text if unicodedata.category(ch) not in ("Mn", "Mc") and ch not in "်္")


def split_phrases(text: str, max_chars: int = 22) -> list[str]:
    """Split narration into caption chunks at sentence/phrase/space boundaries,
    falling back to syllable boundaries; each chunk <= 2 lines of max_chars."""
    chunks: list[str] = []
    for sent in [s for s in SENT_END.split(text) if s.strip()]:
        words = [w for w in PHRASE_END.split(sent) if w]
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip() if cur else w
            if display_len(cand) <= max_chars * 2:
                cur = cand
                continue
            if cur:
                chunks.append(cur)
            if display_len(w) <= max_chars * 2:
                cur = w
            else:  # very long run without spaces -> split by syllables
                cur = ""
                for syl in syllables(w):
                    if display_len(cur + syl) > max_chars * 2 and cur:
                        chunks.append(cur)
                        cur = syl
                    else:
                        cur += syl
        if cur:
            chunks.append(cur)
    return [c.strip() for c in chunks if c.strip()]


def wrap_two_lines(text: str, max_chars: int = 22) -> str:
    """Return text with at most one '\\N' line break near the middle at a boundary."""
    if display_len(text) <= max_chars:
        return text
    cands = [m.start() for m in re.finditer(r"\s", text)]
    if not cands:
        syl = syllables(text)
        acc, pos = 0, []
        for s in syl:
            acc += len(s)
            pos.append(acc)
        cands = pos[:-1]
    mid = len(text) / 2
    cut = min(cands, key=lambda i: abs(i - mid)) if cands else len(text) // 2
    return text[:cut].strip() + r"\N" + text[cut:].strip()
