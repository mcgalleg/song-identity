import numpy as np
import pytest
from scipy.signal import resample_poly

from song_identity.audio import StreamResampler
from song_identity.engine import Engine
from song_identity.fingerprint import SAMPLE_RATE
from song_identity.store import Library

from .synth import make_song


class FakeCard:
    """Pretends to be a 48 kHz stereo sound card delivering 250 ms blocks."""

    def __init__(self, on_block, audio_48k):
        self.on_block, self.audio = on_block, audio_48k
        self.res = StreamResampler(48000)

    def start(self):
        stereo = np.stack([self.audio, self.audio * 0.8], axis=1)
        for i in range(0, len(stereo), 12000):
            self.on_block(self.res.process(stereo[i:i + 12000].mean(axis=1)))

    def stop(self):
        pass


def to_48k(x):
    return resample_poly(x, 640, 147).astype(np.float32)


@pytest.fixture(scope="module")
def songs():
    return {i: make_song(i + 10, 90, SAMPLE_RATE) for i in (3, 8)}


def test_resampler_matches_offline(songs):
    x48 = to_48k(songs[3][: SAMPLE_RATE * 5])
    r = StreamResampler(48000)
    out = np.concatenate([r.process(x48[i:i + 1000]) for i in range(0, len(x48), 1000)])
    assert abs(len(out) - SAMPLE_RATE * 5) <= 2
    ref = songs[3][: len(out)]
    # the streaming low-pass filter adds a few samples of delay; allow for it
    corr = max(np.corrcoef(out[200 + lag:-200], ref[200:-200 - lag])[0, 1] for lag in range(8))
    assert corr > 0.95


def test_learn_then_listen_through_sound_card(tmp_path, songs):
    lib = Library(tmp_path)
    playing = {}
    eng = Engine(lib, source_factory=lambda cb: FakeCard(cb, playing["audio"]))
    for sid in (3, 8):  # "learn mode": play each song once
        playing["audio"] = to_48k(songs[sid])
        eng.start_learning(sid)
        assert eng.finish_learning() == sid
    assert lib.is_learned(3) and lib.is_learned(8)

    heard = []
    eng.on_match = lambda m: heard.append(m.song_id)
    # later, part of song 8 then part of song 3 play back to back
    seg = np.concatenate([songs[8][SAMPLE_RATE * 30: SAMPLE_RATE * 50],
                          songs[3][SAMPLE_RATE * 10: SAMPLE_RATE * 30]])
    playing["audio"] = to_48k(seg)
    eng.start_listening()
    assert heard == [8, 3]
    st = eng.status()
    assert st.now_playing.song_id == 3
    assert abs(st.now_playing.position - 30) < 3
    assert [h.song_id for h in st.history] == [3, 8]


def test_learning_silence_is_rejected(tmp_path):
    eng = Engine(Library(tmp_path),
                 source_factory=lambda cb: FakeCard(cb, np.zeros(48000 * 10, np.float32)))
    eng.start_learning(1)
    with pytest.raises(ValueError, match="silence"):
        eng.finish_learning()
    assert not eng.library.is_learned(1)


def test_unlearned_music_is_never_announced(tmp_path, songs):
    lib = Library(tmp_path)
    playing = {"audio": to_48k(songs[3])}
    eng = Engine(lib, source_factory=lambda cb: FakeCard(cb, playing["audio"]))
    eng.start_learning(3)
    eng.finish_learning()
    heard = []
    eng.on_match = lambda m: heard.append(m.song_id)
    playing["audio"] = to_48k(np.concatenate([make_song(s, 30, SAMPLE_RATE) for s in range(200, 206)]))
    eng.start_listening()  # 3 minutes of music the app was never taught
    assert heard == []
    assert eng.status().now_playing is None
