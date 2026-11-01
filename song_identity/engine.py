"""Listening / learning state machine shared by the menu bar app and the CLI."""

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .audio import LiveSource
from .catalog import BY_ID
from .fingerprint import SAMPLE_RATE
from .store import Library, Match

WINDOW_SECONDS = 10  # how much recent audio each identification attempt looks at
STEP_SECONDS = 2.5  # how often to attempt an identification
MIN_SECONDS = 4  # don't try until we have at least this much audio
FORGET_AFTER = 12  # seconds without a match before "now playing" clears
MAX_LEARN_SECONDS = 30 * 60
SILENCE_RMS = 1e-4


@dataclass
class HistoryEntry:
    song_id: int
    first_heard: float
    last_heard: float


@dataclass
class Status:
    mode: str = "idle"  # idle | listening | learning
    now_playing: Match | None = None
    last_heard: float = 0.0
    level: float = 0.0  # recent input RMS (0..1)
    learning_song: int | None = None
    learning_seconds: float = 0.0
    error: str | None = None
    history: list[HistoryEntry] = field(default_factory=list)


class Engine:
    def __init__(self, library: Library, device: str | None = None,
                 on_match: Callable[[Match], None] | None = None,
                 source_factory=None):
        self.library = library
        self.device = device
        self.on_match = on_match  # called when a *new* song starts being heard
        self._source_factory = source_factory or (lambda cb: LiveSource(cb, self.device))
        self._lock = threading.RLock()
        self._source = None
        self._status = Status()
        self._history: deque[HistoryEntry] = deque(maxlen=50)
        self._ring = np.zeros(0, np.float32)
        self._since_check = 0
        self._audio_clock = 0.0  # seconds of audio received while listening
        self._candidates: deque[tuple[float, Match]] = deque(maxlen=3)
        self._learn_blocks: list[np.ndarray] = []
        self._learn_replace = True
        self.version = 0  # bumps whenever history / now-playing changes

    # ---- public API --------------------------------------------------
    def status(self) -> Status:
        with self._lock:
            s = Status(**{k: getattr(self._status, k) for k in Status.__dataclass_fields__})
            s.history = list(self._history)
            return s

    def start_listening(self):
        with self._lock:
            self._stop_source()
            self._ring = np.zeros(0, np.float32)
            self._since_check = 0
            self._candidates.clear()
            self._status.mode = "listening"
            self._status.error = None
            self._start_source()

    def start_learning(self, song_id: int, replace: bool = True):
        if song_id not in BY_ID:
            raise ValueError(f"Unknown song #{song_id}")
        with self._lock:
            self._stop_source()
            self._learn_blocks = []
            self._learn_replace = replace
            self._status.mode = "learning"
            self._status.learning_song = song_id
            self._status.learning_seconds = 0.0
            self._status.error = None
            self._start_source()

    def finish_learning(self) -> int:
        """Stop recording and save the fingerprints. Returns the song id learned."""
        with self._lock:
            if self._status.mode != "learning":
                raise RuntimeError("Not currently learning")
            self._stop_source()
            song_id = self._status.learning_song
            audio = np.concatenate(self._learn_blocks) if self._learn_blocks else np.zeros(0, np.float32)
            self._learn_blocks = []
            self._status.mode = "idle"
            self._status.learning_song = None
        if len(audio) < SAMPLE_RATE * 5:
            raise ValueError("Recorded less than 5 seconds of audio – nothing was learned.")
        if np.sqrt(np.mean(audio**2)) < SILENCE_RMS:
            raise ValueError("Only silence was recorded. Check that the computer's audio is "
                             "reaching the app (see 'Input Device' / BlackHole setup).")
        self.library.learn(song_id, audio, replace=self._learn_replace)
        return song_id

    def stop(self):
        with self._lock:
            self._stop_source()
            self._learn_blocks = []
            self._status.mode = "idle"
            self._status.learning_song = None
            self._status.level = 0.0

    def set_device(self, device: str | None):
        with self._lock:
            mode = self._status.mode
            self.device = device
            if mode == "listening":
                self.start_listening()

    # ---- audio handling ----------------------------------------------
    def _start_source(self):
        self._source = self._source_factory(self._on_block)
        try:
            self._source.start()
        except Exception as e:
            self._source = None
            self._status.mode = "idle"
            self._status.error = f"Could not open audio input: {e}"
            raise

    def _stop_source(self):
        if self._source is not None:
            src, self._source = self._source, None
            src.stop()

    def _on_block(self, block: np.ndarray):
        level = float(np.sqrt(np.mean(block**2))) if len(block) else 0.0
        with self._lock:
            self._status.level = 0.7 * self._status.level + 0.3 * level
            mode = self._status.mode
            if mode == "learning":
                self._learn_blocks.append(block)
                self._status.learning_seconds += len(block) / SAMPLE_RATE
                if self._status.learning_seconds > MAX_LEARN_SECONDS:
                    self._status.error = "Learning stopped automatically after 30 minutes."
                    threading.Thread(target=self._safe_finish, daemon=True).start()
                return
            if mode != "listening":
                return
            self._ring = np.concatenate([self._ring, block])[-WINDOW_SECONDS * SAMPLE_RATE:]
            self._since_check += len(block)
            self._audio_clock += len(block) / SAMPLE_RATE
            if self._since_check < STEP_SECONDS * SAMPLE_RATE or len(self._ring) < MIN_SECONDS * SAMPLE_RATE:
                return
            self._since_check = 0
            window = self._ring.copy()
            clock = self._audio_clock
        self._identify(window, clock)

    def _safe_finish(self):
        try:
            self.finish_learning()
        except Exception as e:
            with self._lock:
                self._status.error = str(e)

    def _confirmed(self, match: Match, clock: float) -> bool:
        """A new song must be seen twice, at positions consistent with the time between."""
        st = self._status
        if st.now_playing and st.now_playing.song_id == match.song_id:
            return True
        ok = any(c.song_id == match.song_id
                 and abs((match.position - c.position) - (clock - t)) < 1.5
                 for t, c in self._candidates)
        self._candidates.append((clock, match))
        return ok

    def _identify(self, window: np.ndarray, clock: float):
        now = time.time()
        match = self.library.match(window) if np.sqrt(np.mean(window**2)) > SILENCE_RMS else None
        new_song = None
        with self._lock:
            st = self._status
            if match and not self._confirmed(match, clock):
                match = None  # unconfirmed: wait for the next window
            if match:
                top = self._history[0] if self._history else None
                if top and top.song_id == match.song_id and now - top.last_heard < 60:
                    top.last_heard = now  # same performance continuing
                else:
                    new_song = match
                    self._history.appendleft(HistoryEntry(match.song_id, now, now))
                st.now_playing = match
                st.last_heard = now
                self.version += 1
            elif st.now_playing and now - st.last_heard > FORGET_AFTER:
                st.now_playing = None
                self.version += 1
        if new_song and self.on_match:
            try:
                self.on_match(new_song)
            except Exception:
                pass
