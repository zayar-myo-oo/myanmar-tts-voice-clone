"""Scan a WAV for narrow tonal artifacts (vocoder whine) at multiples of a base frequency.

Reports, for each multiple, how many dB the line stands above its neighbourhood during speech.
    .venv-nara\\Scripts\\python.exe scripts\\tone_scan.py file.wav [file2.wav ...] [--base 1200]
"""
import argparse

import numpy as np
import soundfile as sf


def scan(path, base=1200.0, n=8192):
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    x = x.mean(1)
    hop = n // 4
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    S = np.abs(np.fft.rfft(fr, axis=1))
    energy = S.sum(1)
    S = S[energy > np.percentile(energy, 50)]  # speech frames only
    spec = 20 * np.log10(S.mean(0) + 1e-12)
    f = np.fft.rfftfreq(n, 1 / sr)
    df = f[1]
    res = []
    k = 1
    while base * k < sr / 2 - 200:
        t = base * k
        i = int(round(t / df))
        w = int(150 / df)
        peak = spec[i - 3 : i + 4].max()
        ring = np.r_[spec[i - w : i - 8], spec[i + 8 : i + w]]
        res.append((t, peak - np.median(ring)))
        k += 1
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--base", type=float, default=1200.0)
    a = ap.parse_args()
    for p in a.files:
        r = scan(p, a.base)
        print(p.split("\\")[-1].split("/")[-1])
        print("  " + "  ".join(f"{int(t)}:{d:+.0f}" for t, d in r))


if __name__ == "__main__":
    main()
