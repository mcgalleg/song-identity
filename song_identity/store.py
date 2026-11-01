"""On-disk library of learned fingerprints, plus an in-memory lookup index."""

import json
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fingerprint import FRAMES_PER_SECOND, SAMPLE_RATE, fingerprint

MIN_SCORE = 20  # aligned hash matches needed before we trust a match
MIN_MARGIN = 2.0  # best song must beat the runner-up by this factor
MIN_SHARPNESS = 15.0  # best offset must stand this far above the song's background (tuned on real recordings)
SESSION_SPAN = 100_000  # frames (~38 min); each learned session starts on a multiple of this


def default_data_dir() -> Path:
    if env := os.environ.get("SONG_IDENTITY_DATA"):
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SongIdentity"
    return Path.home() / ".local" / "share" / "song-identity"


@dataclass
class Match:
    song_id: int
    score: int  # number of time-aligned hash matches
    position: float  # seconds into the learned recording at the END of the clip
    runner_up: int
    sharpness: float = 0.0  # how far the winning offset stands above background


BUNDLED = Path(__file__).parent / "bundled_library"  # pre-trained from the catalog URLs


class Library:
    def __init__(self, data_dir: Path | None = None, seed_bundled: bool = False):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self._meta_path = self.dir / "library.json"
        if seed_bundled and not self._meta_path.exists() and (BUNDLED / "library.json").exists():
            shutil.copytree(BUNDLED, self.dir, dirs_exist_ok=True)
        (self.dir / "fingerprints").mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.meta: dict[int, dict] = {}
        if self._meta_path.exists():
            self.meta = {int(k): v for k, v in json.loads(self._meta_path.read_text()).items()}
        self._build_index()

    # ---- persistence -------------------------------------------------
    def _fp_path(self, song_id: int) -> Path:
        return self.dir / "fingerprints" / f"song_{song_id:02d}.npz"

    def _save_meta(self):
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({str(k): v for k, v in sorted(self.meta.items())}, indent=2))
        tmp.replace(self._meta_path)

    def is_learned(self, song_id: int) -> bool:
        return song_id in self.meta

    def learn(self, song_id: int, samples: np.ndarray, replace: bool = True) -> int:
        """Fingerprint audio (mono, SAMPLE_RATE) and store it for song_id.

        replace=False appends to what was learned before (e.g. to fill in a
        part of the piece that was missed). Returns the number of hashes added.
        """
        hashes, offsets = fingerprint(samples)
        if len(hashes) == 0:
            raise ValueError("No usable audio was captured (was anything playing?)")
        seconds = len(samples) / SAMPLE_RATE
        with self._lock:
            path = self._fp_path(song_id)
            prev = self.meta.get(song_id) if not replace else None
            if prev and path.exists():
                old = np.load(path)
                base = (int(old["offsets"].max()) // SESSION_SPAN + 1) * SESSION_SPAN
                hashes = np.concatenate([old["hashes"], hashes])
                offsets = np.concatenate([old["offsets"], offsets + base])
                prev_seconds, sessions = prev["seconds"], prev["sessions"]
            else:
                prev_seconds, sessions = 0.0, 0
            np.savez_compressed(path, hashes=hashes.astype(np.int64), offsets=offsets.astype(np.int64))
            self.meta[song_id] = {
                "seconds": round(prev_seconds + seconds, 1),
                "sessions": sessions + 1,
                "hashes": int(len(hashes)),
                "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save_meta()
            self._build_index()
        return len(hashes)

    def forget(self, song_id: int):
        with self._lock:
            self._fp_path(song_id).unlink(missing_ok=True)
            self.meta.pop(song_id, None)
            self._save_meta()
            self._build_index()

    # ---- matching ----------------------------------------------------
    def _build_index(self):
        hs, ss, os_ = [], [], []
        for song_id in self.meta:
            path = self._fp_path(song_id)
            if not path.exists():
                continue
            d = np.load(path)
            hs.append(d["hashes"])
            os_.append(d["offsets"])
            ss.append(np.full(len(d["hashes"]), song_id, np.int64))
        if hs:
            h, s, o = np.concatenate(hs), np.concatenate(ss), np.concatenate(os_)
            order = np.argsort(h, kind="stable")
            self._h, self._s, self._o = h[order], s[order], o[order]
        else:
            self._h = self._s = self._o = np.empty(0, np.int64)

    def match(self, samples: np.ndarray) -> Match | None:
        """Identify a clip (mono, SAMPLE_RATE). Returns None if not confident."""
        qh, qo = fingerprint(samples)
        with self._lock:
            H, S, O = self._h, self._s, self._o
        if len(qh) == 0 or len(H) == 0:
            return None
        left = np.searchsorted(H, qh, "left")
        right = np.searchsorted(H, qh, "right")
        counts = right - left
        hit = counts > 0
        if not hit.any():
            return None
        left, counts, qo = left[hit], counts[hit], qo[hit]
        # expand each query hash into all of its database hits
        total = int(counts.sum())
        starts = np.repeat(left - np.concatenate([[0], np.cumsum(counts)[:-1]]), counts)
        idx = starts + np.arange(total)
        song = S[idx]
        delta = O[idx] - np.repeat(qo, counts)

        best: dict[int, tuple[int, int, float]] = {}  # song -> (score, delta, sharpness)
        for song_id in np.unique(song):
            d = delta[song == song_id]
            lo = d.min()
            hist = np.bincount(d - lo)
            if len(hist) >= 3:  # tolerate +-1 frame jitter
                hist = np.convolve(hist, [1, 1, 1], mode="same")
            i = int(hist.argmax())
            # chance coincidences scatter over many offsets; a real match piles up on one
            background = max(1.0, float(np.percentile(hist[hist > 0], 90)))
            best[int(song_id)] = (int(hist[i]), int(i + lo), hist[i] / background)
        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)
        song_id, (score, d, sharpness) = ranked[0]
        runner_up = ranked[1][1][0] if len(ranked) > 1 else 0
        if score < MIN_SCORE or score < MIN_MARGIN * runner_up or sharpness < MIN_SHARPNESS:
            return None
        clip_seconds = len(samples) / SAMPLE_RATE
        position = max(0.0, (d % SESSION_SPAN) / FRAMES_PER_SECOND + clip_seconds)
        return Match(song_id, score, position, runner_up, round(float(sharpness), 1))

