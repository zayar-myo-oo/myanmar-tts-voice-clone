"""Stage-by-stage diagnosis of the male voice chain (same text, loudness-matched, no clipping).

    .venv-nara\\Scripts\\python.exe scripts\\male_stage_diagnosis.py outputs/diag-male/stages

Stages isolate: pitch shift (formant preserved vs shifted), Vocos re-synthesis, and each part
of the filter chain. All files are scaled by one rule: active-speech RMS equal across files,
with the common level chosen so every file peaks at or below -1 dBFS (no limiter, no clipping).
Prints objective measurements only; it cannot judge naturalness by ear.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tone_scan import scan  # noqa: E402

from myanmar_voice_studio.engine import VoiceEngine, VoiceProfile  # noqa: E402
from myanmar_voice_studio.engine import dsp  # noqa: E402

SR = 24000
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=False)
preset = json.loads((ROOT / "config/voice_presets.json").read_text(encoding="utf-8"))["presets"]["male_calm"]
CHAIN = preset["post_filter"]
parts = CHAIN.split(",")
NOTCH = ",".join(p for p in parts if p.startswith("bandreject"))
EQ = ",".join(p for p in parts if p.startswith("equalizer"))
BASE = ",".join(p for p in parts if p.split("=")[0] in ("highpass", "deesser", "lowpass"))

eng = VoiceEngine.from_settings()
adapter = eng._adapter(eng.voice("male_calm"))
text = " ".join((ROOT / "outputs/passage.txt").read_text(encoding="utf-8").split())
v = VoiceProfile(voice_id="h", display_name="h", adapter_id="nara-mini-v1", speaker=preset["voice"], sentence_gap_s=preset["sentence_gap_s"])
raw = adapter.synthesize(text, v, v.sentence_gap_s)
ff = dsp.ffmpeg_path()


def filt(x, chain):
    return dsp._run_ffmpeg(ff, x, SR, [chain]) if chain else x


def shift(x, semis, formant):
    r = 2 ** (semis / 12)
    return dsp._run_ffmpeg(ff, x, SR, [f"rubberband=pitch={r:.5f}:formant={formant}:pitchq=quality"])


voc = lambda x: dsp.vocos_resynth(x, SR)  # noqa: E731
p_pres, p_shift = shift(raw, 2, "preserved"), shift(raw, 2, "shifted")
vs = voc(p_shift)
stages = {
    "A0_raw_model": raw,
    "A1_raw+filters": filt(raw, CHAIN),
    "A2_raw+vocos": voc(raw),
    "A3_raw+vocos+filters (no pitch change)": filt(voc(raw), CHAIN),
    "B1_+2st_formant_preserved": p_pres,
    "B2_+2st_formant_shifted": p_shift,
    "B3_+2st_shifted+vocos": vs,
    "B4_CURRENT (+2st shifted+vocos+filters)": filt(vs, CHAIN),
    "C1_B3+notch_only": filt(vs, NOTCH),
    "C2_B3+EQ_only": filt(vs, EQ),
    "C3_B3+hp_deesser_lp_only": filt(vs, BASE),
}


def active(x):
    n = int(0.02 * SR)
    fr = x[: x.size // n * n].reshape(-1, n)
    r = np.sqrt((fr ** 2).mean(1))
    return fr[r > np.percentile(r, 40)].ravel()


def f0_track(x):
    """10 ms hop, 40 ms window autocorrelation pitch; returns f0 (Hz, 0=unvoiced) and voicing strength."""
    n, hop = int(0.04 * SR), int(0.01 * SR)
    f0, strength = [], []
    lo, hi = SR // 350, SR // 60
    for s in range(0, x.size - n, hop):
        fr = x[s : s + n] - x[s : s + n].mean()
        e = (fr ** 2).sum()
        if e < 1e-6 * n:
            f0.append(0.0)
            continue
        ac = np.correlate(fr, fr, "full")[n - 1 :] / e
        lag = lo + int(np.argmax(ac[lo:hi]))
        voiced = ac[lag] > 0.45
        f0.append(SR / lag if voiced else 0.0)
        if voiced:
            strength.append(ac[lag])
    return np.array(f0), np.array(strength)


def lpc_formants(x, order=12):
    """Median F1/F2 over voiced frames (LPC on 10 kHz-resampled audio)."""

    xr = np.interp(np.arange(0, x.size, SR / 10000), np.arange(x.size), x)
    n, hop, fs = 300, 100, 10000
    F1, F2 = [], []
    for s in range(0, xr.size - n, hop):
        fr = xr[s : s + n] * np.hamming(n)
        if (fr ** 2).mean() < 1e-4:
            continue
        fr = np.append(fr[0], fr[1:] - 0.63 * fr[:-1])
        r = np.correlate(fr, fr, "full")[n - 1 : n + order]
        if r[0] <= 0:
            continue
        a = np.zeros(order + 1)
        a[0], err = 1.0, r[0]
        for i in range(1, order + 1):  # Levinson-Durbin
            k = -(r[i] + a[1:i] @ r[i - 1 : 0 : -1]) / err
            a[1:i] = a[1:i] + k * a[i - 1 : 0 : -1]
            a[i] = k
            err *= 1 - k * k
        roots = [z for z in np.roots(a) if z.imag > 0]
        fr_hz = sorted(np.angle(z) * fs / (2 * np.pi) for z in roots if np.abs(z) > 0.9)
        fr_hz = [f for f in fr_hz if f > 200]
        if len(fr_hz) >= 2:
            F1.append(fr_hz[0])
            F2.append(fr_hz[1])
    return (float(np.median(F1)), float(np.median(F2))) if F1 else (0.0, 0.0)


# Common loudness: equal active RMS, level chosen so the loudest-peaking file sits at -1 dBFS.
rms = {k: np.sqrt((active(x) ** 2).mean()) for k, x in stages.items()}
peak = {k: np.abs(x).max() for k, x in stages.items()}
target = min(10 ** (-1 / 20) * rms[k] / peak[k] for k in stages)
target = min(target, 10 ** (-20 / 20))
rows = []
for i, (name, x) in enumerate(stages.items()):
    y = (x * (target / rms[name])).astype(np.float32)
    assert np.abs(y).max() <= 10 ** (-1 / 20) + 1e-6
    fname = f"{i:02d}_{name.split(' ')[0]}.wav"
    sf.write(out / fname, y, SR, subtype="PCM_16")
    f0, strength = f0_track(y)
    v = f0[f0 > 0]
    st = 12 * np.log2(v / np.median(v))
    jit = np.abs(np.diff(12 * np.log2(f0[1:][(f0[1:] > 0) & (f0[:-1] > 0)] / f0[:-1][(f0[1:] > 0) & (f0[:-1] > 0)])))
    P_ = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(y.size, 1 / SR)
    F1, F2 = lpc_formants(y)
    whine = max(d for t, d in scan(str(out / fname), 1200) if t >= 3600)
    rows.append({
        "stage": name, "file": fname,
        "f0_median_hz": round(float(np.median(v)), 1), "f0_range_st(sd)": round(float(st.std()), 2),
        "voiced_%": round(100 * v.size / max(1, (f0 >= 0).sum()), 1),
        "periodicity": round(float(strength.mean()), 3), "pitch_jitter_st": round(float(np.median(jit)), 3),
        "F1_hz": round(F1), "F2_hz": round(F2),
        "centroid_hz": round(float((f * P_).sum() / P_.sum())), "bass_100_300": round(float(P_[(f > 100) & (f < 300)].sum() / P_.sum()), 2),
        "whine_db": round(float(whine), 1), "peak_dbfs": round(float(20 * np.log10(np.abs(y).max())), 1),
    })

(out / "measurements.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
cols = ["file", "f0_median_hz", "f0_range_st(sd)", "periodicity", "pitch_jitter_st", "F1_hz", "F2_hz", "centroid_hz", "bass_100_300", "whine_db", "peak_dbfs"]
print(f"common active RMS = {20 * np.log10(target):.1f} dBFS")
print(" | ".join(cols))
for r in rows:
    print(" | ".join(str(r[c]) for c in cols))
