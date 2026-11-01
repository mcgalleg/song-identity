"""Landmark audio fingerprinting (the technique Shazam is built on).

Audio -> spectrogram -> local peaks ("constellation") -> pairs of peaks hashed
as (freq1, freq2, time gap). A clip matches a song when many of its hashes are
found in the song *at the same relative time offset*.
"""

import numpy as np
from scipy.ndimage import maximum_filter
from scipy.signal import stft

SAMPLE_RATE = 11025  # everything is analysed at this rate, mono
N_FFT = 1024
HOP = 256  # ~23 ms per frame
PEAK_NEIGHBORHOOD = (15, 11)  # (freq bins, frames) a peak must dominate
PEAK_FLOOR_DB = -10.0  # ignore near-silence
PEAK_RANGE_DB = 45.0  # ignore peaks this far below the loudest bin in their frame
FAN_OUT = 12  # pair each anchor peak with this many following peaks
MAX_DT = 63  # max frame gap in a pair (6 bits)

FRAMES_PER_SECOND = SAMPLE_RATE / HOP


def peaks(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (frame_index, freq_bin) of spectral peaks, sorted by time then freq."""
    samples = np.asarray(samples, dtype=np.float32)
    if len(samples) < N_FFT:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    _, _, z = stft(samples, fs=SAMPLE_RATE, window="hann", nperseg=N_FFT,
                   noverlap=N_FFT - HOP, boundary=None, padded=False, scaling="spectrum")
    spec = 20 * np.log10(np.abs(z) * N_FFT + 1e-9)  # (freq, time)
    spec[0, :] = -200  # drop DC
    local_max = maximum_filter(spec, size=PEAK_NEIGHBORHOOD, mode="constant", cval=-200)
    frame_max = spec.max(axis=0, keepdims=True)
    mask = (spec == local_max) & (spec > PEAK_FLOOR_DB) & (spec > frame_max - PEAK_RANGE_DB)
    f, t = np.nonzero(mask)
    order = np.lexsort((f, t))
    return t[order].astype(np.int64), f[order].astype(np.int64)


def fingerprint(samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (hashes, anchor_frame_offsets) for mono audio at SAMPLE_RATE."""
    t, f = peaks(samples)
    hashes, offsets = [], []
    for k in range(1, FAN_OUT + 1):
        if len(t) <= k:
            break
        dt = t[k:] - t[:-k]
        ok = (dt >= 1) & (dt <= MAX_DT)
        hashes.append((f[:-k][ok] << 16) | (f[k:][ok] << 6) | dt[ok])
        offsets.append(t[:-k][ok])
    if not hashes:
        return np.empty(0, np.int64), np.empty(0, np.int64)
    return np.concatenate(hashes), np.concatenate(offsets)
