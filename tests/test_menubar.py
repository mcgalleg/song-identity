"""Drive the menu bar app with a fake `rumps` so its logic runs on any OS."""

import sys
import types

import numpy as np
import pytest
from scipy.signal import resample_poly

from song_identity.audio import StreamResampler
from song_identity.fingerprint import SAMPLE_RATE

from .synth import make_song


class FakeItem:
    def __init__(self, title="", callback=None, key=None):
        self.title, self.callback, self.state = title, callback, 0
        self._menu = None
        self.children = []

    def add(self, item):
        self._menu = True
        self.children.append(item)

    def clear(self):
        self.children = []

    def set_callback(self, cb, key=None):
        self.callback = cb


def make_fake_rumps(alert_answers):
    m = types.ModuleType("rumps")
    m.MenuItem = FakeItem
    m.alerts = []

    def alert(title=None, message="", ok=None, cancel=None, other=None):
        m.alerts.append(title)
        return alert_answers.pop(0) if alert_answers else 1

    class App:
        def __init__(self, name, title=None, quit_button=None):
            self.title = title

    class Timer:
        def __init__(self, cb, interval):
            pass

        def start(self):
            pass

    m.App, m.Timer, m.alert = App, Timer, alert
    m.notification = lambda *a, **k: None
    m.quit_application = lambda: None
    return m


class SilentCard:
    def __init__(self, on_block, audio):
        self.on_block, self.audio = on_block, audio

    def start(self):
        r = StreamResampler(48000)
        for i in range(0, len(self.audio), 12000):
            self.on_block(r.process(self.audio[i:i + 12000]))

    def stop(self):
        pass


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SONG_IDENTITY_DATA", str(tmp_path))
    import song_identity.store as store
    monkeypatch.setattr(store, "BUNDLED", tmp_path / "no-bundle")  # start with an empty library
    answers = []
    monkeypatch.setitem(sys.modules, "rumps", make_fake_rumps(answers))
    sys.modules.pop("song_identity.menubar", None)
    import song_identity.menubar as mb
    monkeypatch.setattr(mb, "list_input_devices", lambda: ["MacBook Pro Microphone", "BlackHole 2ch"])
    monkeypatch.setattr(mb, "auto_device", lambda: "BlackHole 2ch")
    a = mb.SongIdentityApp()
    a._answers = answers
    yield a
    sys.modules.pop("song_identity.menubar", None)


def test_full_flow(app):
    rumps = sys.modules["rumps"]
    app.tick(None)
    assert rumps.alerts == ["Welcome to Song Identity"]
    assert "0 of 10" in app.level_item.title
    assert len([c for c in app.learn_menu.children if c]) == 11  # 10 songs + Forget submenu

    song = make_song(99, 60, SAMPLE_RATE)
    audio48 = resample_poly(song, 640, 147).astype(np.float32)
    app.engine._source_factory = lambda cb: SilentCard(cb, audio48)

    app.learn(8)  # alert "Start" -> 1
    app.tick(None)
    assert app.title.startswith("● Learning #8")
    assert app.finish_item.callback is not None
    app.finish_learning(None)
    import time
    for _ in range(50):
        if app._busy_msg is None:
            break
        time.sleep(0.1)
    app.tick(None)
    assert rumps.alerts[-1] == "Learned!"
    assert app.library.is_learned(8)
    assert app.learn_menu.children[7].state == 1

    clip = resample_poly(song[SAMPLE_RATE * 20: SAMPLE_RATE * 35], 640, 147).astype(np.float32)
    app.engine._source_factory = lambda cb: SilentCard(cb, clip)
    app.toggle_listening(None)
    app.tick(None)
    assert app.title == "♪ #8 Maple Leaf Rag"
    assert app.now_item.title.startswith("Now: #8 Joplin")
    assert "Maple Leaf Rag" in app.history_menu.children[0].title

    app.toggle_listening(None)
    app.tick(None)
    assert app.title == "♪"

    app.choose_device("BlackHole 2ch")
    assert [c.state for c in app.device_menu.children if c and c.title == "BlackHole 2ch"] == [1]

    app._answers.append(1)  # confirm "Forget"
    app.forget(8)
    assert not app.library.is_learned(8)


def test_fresh_install_uses_bundled_library(tmp_path, monkeypatch):
    monkeypatch.setenv("SONG_IDENTITY_DATA", str(tmp_path / "data"))
    monkeypatch.setitem(sys.modules, "rumps", make_fake_rumps([]))
    sys.modules.pop("song_identity.menubar", None)
    import song_identity.menubar as mb
    monkeypatch.setattr(mb, "list_input_devices", lambda: [])
    monkeypatch.setattr(mb, "auto_device", lambda: None)
    a = mb.SongIdentityApp()
    a.tick(None)
    assert sys.modules["rumps"].alerts == []  # no "teach me" welcome needed
    assert "10 of 10" in a.level_item.title
    sys.modules.pop("song_identity.menubar", None)
