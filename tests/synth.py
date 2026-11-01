"""Generate deterministic music-like test audio (random melodies + chords)."""

import numpy as np


def make_song(seed: int, seconds: float, sr: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * sr), np.float32)
    t0 = 0.0
    while t0 < seconds:
        dur = rng.choice([0.125, 0.25, 0.375, 0.5])
        n = int(dur * sr)
        start = int(t0 * sr)
        tt = np.arange(n) / sr
        env = np.minimum(1, tt * 40) * np.exp(-tt * rng.uniform(1.5, 5))
        for _ in range(rng.integers(1, 4)):  # notes in this chord
            freq = 110 * 2 ** (rng.integers(0, 40) / 12)
            vib = 1 + 0.003 * np.sin(2 * np.pi * 5 * tt)
            for h, amp in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)):
                out[start:start + n] += (amp * env * np.sin(2 * np.pi * freq * h * vib * tt))[: len(out) - start]
        t0 += dur
    return 0.3 * out / np.abs(out).max()
