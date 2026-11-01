"""Audio input: capture from a sound device (or a file) as mono SAMPLE_RATE blocks."""

import os
import queue
import shutil
import subprocess
import sys
import threading
from typing import Callable

import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi

from .fingerprint import SAMPLE_RATE

BlockCallback = Callable[[np.ndarray], None]


class StreamResampler:
    """Continuous (block-boundary-safe) downsampler: low-pass + linear interpolation."""

    def __init__(self, in_rate: float, out_rate: float = SAMPLE_RATE):
        self.step = in_rate / out_rate
        self.passthrough = abs(self.step - 1) < 1e-9
        self.sos = butter(8, 0.45 * out_rate, fs=in_rate, output="sos")
        self.zi = None
        self.tail = np.empty(0, np.float32)
        self.pos = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, np.float32)
        if self.passthrough or len(x) == 0:
            return x
        if self.zi is None:
            self.zi = sosfilt_zi(self.sos) * x[0]
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        buf = np.concatenate([self.tail, y.astype(np.float32)])
        last = len(buf) - 1
        n = int((last - self.pos) // self.step) + 1 if last >= self.pos else 0
        p = self.pos + self.step * np.arange(n)
        out = np.interp(p, np.arange(len(buf)), buf).astype(np.float32)
        self.pos = self.pos + self.step * n - last
        self.tail = buf[-1:]
        return out


def list_input_devices() -> list[str]:
    import sounddevice as sd
    return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]


def auto_device() -> str | None:
    """Pick the best device for hearing what the computer itself is playing."""
    names = list_input_devices()
    if sys.platform == "darwin":
        for n in names:
            if "blackhole" in n.lower():
                return n
        return None  # fall back to the default input (microphone)
    if sys.platform.startswith("linux"):
        # Dev convenience: record the monitor of the default PipeWire/Pulse sink.
        if shutil.which("pactl"):
            try:
                sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True,
                                      text=True, timeout=3).stdout.strip()
                if sink:
                    os.environ.setdefault("PULSE_SOURCE", sink + ".monitor")
                    os.environ.setdefault("PIPEWIRE_NODE", sink)
                    os.environ.setdefault("PIPEWIRE_PROPS", "{ stream.capture.sink=true }")
            except Exception:
                pass
        for n in ("pulse", "pipewire"):
            if n in names:
                return n
    return None


class LiveSource:
    """Captures from a sound device and delivers mono SAMPLE_RATE blocks to a callback."""

    def __init__(self, on_block: BlockCallback, device: str | None = None):
        self.on_block = on_block
        self.device = device
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self._stream = None
        self._worker = None
        self._running = False

    def start(self):
        import sounddevice as sd
        info = sd.query_devices(self.device, "input")
        rate = float(info["default_samplerate"])
        channels = max(1, min(2, int(info["max_input_channels"])))
        self._resampler = StreamResampler(rate)
        self._running = True
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

        def cb(indata, frames, time_info, status):
            try:
                self._q.put_nowait(indata.copy())
            except queue.Full:
                pass

        self._stream = sd.InputStream(device=self.device, channels=channels, samplerate=rate,
                                      blocksize=int(rate // 4), dtype="float32", callback=cb)
        self._stream.start()
        self.device_name = info["name"]

    def _work(self):
        while self._running:
            try:
                block = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            mono = block.mean(axis=1) if block.ndim == 2 else block
            out = self._resampler.process(mono)
            if len(out):
                self.on_block(out)

    def stop(self):
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None


def load_file(path: str) -> np.ndarray:
    """Decode any audio file ffmpeg understands into mono SAMPLE_RATE float32."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to read audio files (brew install ffmpeg)")
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32).copy()


def download_url(url: str, end: int | None = None) -> np.ndarray:
    """Fetch a recording's audio with yt-dlp (optionally only the first `end` seconds)."""
    import tempfile
    exe = shutil.which("yt-dlp")
    if not exe:
        raise RuntimeError("yt-dlp is required to learn from a link (brew install yt-dlp)")
    with tempfile.TemporaryDirectory() as tmp:
        base = [exe, "--no-warnings", "-q", "--no-playlist", "-f", "bestaudio/best",
                "-o", os.path.join(tmp, "audio.%(ext)s")]
        if end:
            base += ["--download-sections", f"*0-{end}"]
        attempts = [[], ["--extractor-args", "youtube:player_client=web_safari,tv"]]
        err = ""
        for extra in attempts:
            r = subprocess.run(base + extra + ["--", url], capture_output=True, text=True)
            files = os.listdir(tmp)
            if r.returncode == 0 and files:
                audio = load_file(os.path.join(tmp, files[0]))
                return audio[: end * SAMPLE_RATE] if end else audio
            err = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["unknown error"]
            err = err[0]
            for f in files:
                os.remove(os.path.join(tmp, f))
        raise RuntimeError(f"Could not download {url}: {err}")
