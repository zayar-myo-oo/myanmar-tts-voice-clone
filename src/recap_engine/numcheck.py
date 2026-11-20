"""Number consistency check between a Chinese line and its translation (catches 30 -> 20 style errors).

Source numbers: Arabic digits and Chinese numerals (三十, 两百, 4.5亿 ...). Target numbers: Arabic, Burmese
(၀-၉) and Thai (๐-๙) digits. A line is flagged only when the translation contains a number that matches
none of the source's readings (e.g. 45亿 may be written 45, 4.5 billion or 4500000000). Numbers spelled out in
words in the translation are not checked (no false alarms for "thirty" / "သုံးဆယ်").
"""
from __future__ import annotations

import re

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}
CN_BIG = {"万": 10_000, "亿": 100_000_000}
CN_RUN = re.compile(r"[零〇一二两三四五六七八九十百千万亿]+")
NUM = re.compile(r"\d+(?:\.\d+)?")
TRANS = str.maketrans("၀၁၂၃၄၅၆၇၈၉๐๑๒๓๔๕๖๗๘๙", "01234567890123456789")


def cn2num(s: str) -> float | None:
    total, section, digit = 0, 0, None
    for ch in s:
        if ch in CN_DIGIT:
            digit = CN_DIGIT[ch]
        elif ch in CN_UNIT:
            section += (1 if digit is None else digit) * CN_UNIT[ch]
            digit = None
        elif ch in CN_BIG:
            section += digit or 0
            total += (section or 1) * CN_BIG[ch]
            section, digit = 0, None
    val = total + section + (digit or 0)
    return float(val) if (val or "零" in s or "〇" in s) else None


def _readings(v: float) -> set[float]:
    """All the ways a translator may legitimately write the same quantity."""
    out = {v}
    for scale in (1e3, 1e4, 1e6, 1e8, 1e9):
        if v >= scale:
            out.add(round(v / scale, 2))
    return {round(x, 2) for x in out}


def source_numbers(zh: str) -> set[float]:
    vals: set[float] = set()
    text = zh.replace(",", "")
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([万亿千百]?)", text):  # 4.5亿, 30, 10万
        base = float(m.group(1))
        vals |= _readings(base) | _readings(base * {"万": 1e4, "亿": 1e8, "千": 1e3, "百": 1e2, "": 1}[m.group(2)])
    for m in CN_RUN.finditer(text):
        run = m.group(0)
        if run in ("一", "两") or (len(run) == 1 and run not in "十百千万亿"):  # "一个人", "两人" -> often idiomatic
            v = cn2num(run)
            if v is not None:
                vals |= _readings(v)
            continue
        v = cn2num(run)
        if v is not None:
            vals |= _readings(v)
    return vals


def target_numbers(text: str) -> set[float]:
    t = (text or "").translate(TRANS).replace(",", "")
    return {round(float(x), 2) for x in NUM.findall(t)}


def mismatch(zh: str, translated: str) -> dict | None:
    """None when fine; otherwise which numbers the translation has that the source does not."""
    tgt = target_numbers(translated)
    if not tgt:
        return None
    src = source_numbers(zh)
    extra = sorted(x for x in tgt if x not in src)
    if not extra:
        return None
    return {"source": sorted(src)[:8], "translation": sorted(tgt), "unexpected": extra}
