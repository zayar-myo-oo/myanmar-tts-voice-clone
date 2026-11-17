"""Objective voice measurements shared by the diagnosis scripts (no listening involved)."""
from __future__ import annotations

import numpy as np

SR = 24000


def active(x):
    n = int(0.02 * SR)
    fr = x[: x.size // n * n].reshape(-1, n)
    r = np.sqrt((fr ** 2).mean(1))
    return fr[r > np.percentile(r, 40)].ravel()


def f0_track(x):
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


def measure(y):
    f0, strength = f0_track(y)
    v = f0[f0 > 0]
    st = 12 * np.log2(v / np.median(v))
    both = (f0[1:] > 0) & (f0[:-1] > 0)
    jit = np.abs(np.diff(12 * np.log2(np.where(f0 > 0, f0, 1))))[both]
    P = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(y.size, 1 / SR)
    return {
        "f0_hz": round(float(np.median(v)), 1),
        "f0_sd_st": round(float(st.std()), 2),
        "periodicity": round(float(strength.mean()), 3),
        "jitter_st": round(float(np.median(jit)), 3),
        "centroid_hz": round(float((f * P).sum() / P.sum())),
        "bass_100_300": round(float(P[(f > 100) & (f < 300)].sum() / P.sum()), 2),
        "peak_dbfs": round(float(20 * np.log10(np.abs(y).max())), 1),
    }


def loudness_match(signals: dict[str, np.ndarray], ceiling_db=-1.0, max_db=-20.0):
    """Equal active RMS for all; the common level keeps every peak <= ceiling (no limiter)."""
    rms = {k: np.sqrt((active(x) ** 2).mean()) for k, x in signals.items()}
    peak = {k: np.abs(x).max() for k, x in signals.items()}
    target = min(min(10 ** (ceiling_db / 20) * rms[k] / peak[k] for k in signals), 10 ** (max_db / 20))
    out = {k: (x * (target / rms[k])).astype(np.float32) for k, x in signals.items()}
    assert all(np.abs(y).max() <= 10 ** (ceiling_db / 20) + 1e-6 for y in out.values())
    return out, 20 * np.log10(target)
