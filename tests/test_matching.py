import numpy as np
import pytest
from scipy.signal import resample_poly

from song_identity.fingerprint import SAMPLE_RATE
from song_identity.store import Library

from .synth import make_song

SR = SAMPLE_RATE


@pytest.fixture(scope="module")
def songs():
    return {i: make_song(i, 120, SR) for i in (1, 2, 3, 4)}


@pytest.fixture
def lib(tmp_path, songs):
    lib = Library(tmp_path)
    for i in (1, 2, 3):  # song 4 is never learned
        lib.learn(i, songs[i])
    return lib


def clip(x, start, seconds=8):
    return x[int(start * SR): int((start + seconds) * SR)]


@pytest.mark.parametrize("song_id", [1, 2, 3])
@pytest.mark.parametrize("start", [0.3, 37.77, 101.1])
def test_identifies_clean_excerpt(lib, songs, song_id, start):
    m = lib.match(clip(songs[song_id], start))
    assert m is not None and m.song_id == song_id
    assert abs(m.position - (start + 8)) < 0.2


def test_survives_noise_volume_and_resampling(lib, songs):
    rng = np.random.default_rng(0)
    x = clip(songs[2], 55.5)
    # round-trip through 48 kHz like a real sound card, quieter, plus noise
    x = resample_poly(resample_poly(x, 640, 147), 147, 640).astype(np.float32)
    x = 0.2 * x
    noise_rms = np.sqrt((x**2).mean()) * 10 ** (-10 / 20)  # 10 dB signal-to-noise
    x = x + noise_rms * rng.standard_normal(len(x)).astype(np.float32)
    m = lib.match(x)
    assert m is not None and m.song_id == 2


def test_unknown_song_and_silence_not_matched(lib, songs):
    assert lib.match(clip(songs[4], 20)) is None
    assert lib.match(np.zeros(SR * 8, np.float32)) is None
    rng = np.random.default_rng(1)
    assert lib.match(0.1 * rng.standard_normal(SR * 8).astype(np.float32)) is None


def test_persistence_append_and_forget(tmp_path, songs):
    lib = Library(tmp_path)
    lib.learn(1, clip(songs[1], 0, 60))
    lib.learn(1, clip(songs[1], 60, 60), replace=False)  # learned in two sessions
    lib2 = Library(tmp_path)  # reload from disk
    assert lib2.meta[1]["sessions"] == 2
    m = lib2.match(clip(songs[1], 80))
    assert m and m.song_id == 1 and abs(m.position - 28) < 0.2  # 20 s into session 2 + 8
    lib2.forget(1)
    assert Library(tmp_path).match(clip(songs[1], 10)) is None


def test_single_learned_song_rejects_unlearned_music(tmp_path, songs):
    # regression: with only one song learned there is no runner-up to compare against
    lib = Library(tmp_path)
    lib.learn(1, songs[1])
    false_hits = [lib.match(make_song(seed, 10, SR)) for seed in range(100, 140)]
    assert [m for m in false_hits if m] == []
    assert lib.match(clip(songs[1], 50)).song_id == 1
