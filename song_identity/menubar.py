"""macOS menu bar app (uses `rumps`)."""

import os
import subprocess
import threading
import time

import rumps

from . import settings
from .audio import auto_device, list_input_devices
from .catalog import BY_ID, SONGS
from .engine import Engine
from .store import Library

IDLE_ICON = "♪"


def fmt_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def level_bar(level: float) -> str:
    # ~ -60 dB .. 0 dB mapped onto 10 blocks
    import math
    db = 20 * math.log10(max(level, 1e-6))
    n = max(0, min(10, int((db + 60) / 6)))
    return "▮" * n + "▯" * (10 - n)


def reset_submenu(item: rumps.MenuItem):
    """rumps' clear() crashes on an item whose submenu hasn't been created yet."""
    if item._menu is not None:
        item.clear()


class SongIdentityApp(rumps.App):
    def __init__(self):
        super().__init__("Song Identity", title=IDLE_ICON, quit_button=None)
        self.library = Library(seed_bundled=True)
        self.prefs = settings.load()
        self.notify = self.prefs.get("notify", True)
        self.engine = Engine(self.library, device=self._device_for(self.prefs.get("device", "auto")),
                             on_match=self._on_match)
        self._seen_version = -1
        self._busy_msg = None  # shown while saving a learned song
        self._pending_alert = None  # (title, message) to show from the main thread

        self.now_item = rumps.MenuItem("Not listening")
        self.level_item = rumps.MenuItem("")
        self.listen_item = rumps.MenuItem("Start Listening", callback=self.toggle_listening, key="l")
        self.finish_item = rumps.MenuItem("Finish Learning (save)")
        self.cancel_item = rumps.MenuItem("Cancel Learning")
        self.learn_menu = rumps.MenuItem("Learn a Song")
        self.history_menu = rumps.MenuItem("Recently Heard")
        self.device_menu = rumps.MenuItem("Input Device")
        self.notify_item = rumps.MenuItem("Show Notifications", callback=self.toggle_notify)
        self.notify_item.state = int(self.notify)

        self.menu = [
            self.now_item,
            self.level_item,
            None,
            self.listen_item,
            None,
            self.learn_menu,
            self.finish_item,
            self.cancel_item,
            None,
            self.history_menu,
            self.device_menu,
            self.notify_item,
            rumps.MenuItem("How To Set Up…", callback=self.show_help),
            rumps.MenuItem("Open Data Folder", callback=self.open_data),
            None,
            rumps.MenuItem("Quit Song Identity", callback=self.quit_app, key="q"),
        ]
        self._build_learn_menu()
        self._build_device_menu()
        self._build_history_menu()
        self.timer = rumps.Timer(self.tick, 0.5)
        self.timer.start()

        if not self.library.meta:
            self._pending_alert = (
                "Welcome to Song Identity",
                "Before it can recognise anything, teach it each song once:\n\n"
                "1. Start playing a song from the playlist.\n"
                "2. Menu bar ♪ → Learn a Song → pick that song.\n"
                "3. When the piece finishes, choose 'Finish Learning (save)'.\n\n"
                "Repeat for all 10, then choose 'Start Listening'.")

    # ---- device handling ----------------------------------------------
    @staticmethod
    def _device_for(choice: str | None):
        if choice in (None, "auto"):
            return auto_device()
        if choice == "default":
            return None
        return choice

    def _build_device_menu(self):
        choice = self.prefs.get("device", "auto")
        reset_submenu(self.device_menu)
        auto = auto_device()
        items = [("auto", f"Automatic ({auto or 'microphone'})"), ("default", "System Default Input")]
        try:
            items += [(n, n) for n in list_input_devices()]
        except Exception as e:
            items.append((None, f"Could not list devices: {e}"))
        for key, title in items:
            item = rumps.MenuItem(title, callback=(lambda s, k=key: self.choose_device(k)) if key else None)
            item.state = int(key == choice)
            self.device_menu.add(item)
        self.device_menu.add(None)
        self.device_menu.add(rumps.MenuItem("Refresh List", callback=lambda _: self._build_device_menu()))

    def choose_device(self, key):
        self.prefs["device"] = key
        settings.save(device=key)
        self._build_device_menu()
        try:
            self.engine.set_device(self._device_for(key))
        except Exception as e:
            rumps.alert("Audio input problem", str(e))

    # ---- learning -----------------------------------------------------
    def _build_learn_menu(self):
        reset_submenu(self.learn_menu)
        for s in SONGS:
            m = self.library.meta.get(s.id)
            title = f"{s.id}. {s.composer} – {s.short}"
            if m:
                title += f"   ({fmt_time(m['seconds'])} learned)"
            item = rumps.MenuItem(title, callback=lambda _, sid=s.id: self.learn(sid))
            item.state = int(bool(m))
            self.learn_menu.add(item)
        self.learn_menu.add(None)
        forget = rumps.MenuItem("Forget a Song")
        for s in SONGS:
            if self.library.is_learned(s.id):
                forget.add(rumps.MenuItem(f"{s.id}. {s.short}", callback=lambda _, sid=s.id: self.forget(sid)))
        if not self.library.meta:
            forget.add(rumps.MenuItem("(nothing learned yet)"))
        self.learn_menu.add(forget)

    def learn(self, song_id: int):
        song = BY_ID[song_id]
        replace = True
        if self.library.is_learned(song_id):
            r = rumps.alert(f"“{song.short}” is already learned",
                            "Replace it with a new recording, or add more to it "
                            "(e.g. a section that was missed)?",
                            ok="Replace", cancel="Cancel", other="Add More")
            if r == 0:
                return
            replace = r == 1
        r = rumps.alert(f"Learn #{song_id}: {song.short}",
                        f"{song.label}\n\nClick Start, then play the piece from the beginning. "
                        "When it ends, open the ♪ menu and choose 'Finish Learning (save)'.",
                        ok="Start", cancel="Cancel")
        if r != 1:
            return
        try:
            self.engine.start_learning(song_id, replace=replace)
        except Exception as e:
            rumps.alert("Audio input problem", str(e))

    def finish_learning(self, _):
        self._busy_msg = "Saving…"

        def work():
            try:
                sid = self.engine.finish_learning()
                m = self.library.meta[sid]
                self._pending_alert = ("Learned!", f"{BY_ID[sid].label}\n\n"
                                       f"{fmt_time(m['seconds'])} of audio memorised.")
            except Exception as e:
                self._pending_alert = ("Nothing was learned", str(e))
            self._busy_msg = None
            self._seen_version = -1  # force menu rebuild
        threading.Thread(target=work, daemon=True).start()

    def cancel_learning(self, _):
        self.engine.stop()

    def forget(self, song_id: int):
        if rumps.alert(f"Forget “{BY_ID[song_id].short}”?", "You will need to learn it again.",
                       ok="Forget", cancel="Cancel") == 1:
            self.library.forget(song_id)
            self._build_learn_menu()

    # ---- listening ----------------------------------------------------
    def toggle_listening(self, _):
        if self.engine.status().mode == "listening":
            self.engine.stop()
            return
        if not self.library.meta:
            rumps.alert("No songs learned yet", "Use 'Learn a Song' first.")
            return
        try:
            self.engine.start_listening()
        except Exception as e:
            rumps.alert("Audio input problem", str(e))

    def _on_match(self, match):  # called from the audio thread
        if self.notify:
            s = BY_ID[match.song_id]
            try:
                rumps.notification("Song Identity", f"#{s.id} {s.composer}", f"{s.title} (Ch. {s.chapter})")
            except Exception:
                pass

    def toggle_notify(self, sender):
        self.notify = not self.notify
        sender.state = int(self.notify)
        settings.save(notify=self.notify)

    def _build_history_menu(self):
        reset_submenu(self.history_menu)
        hist = self.engine.status().history
        if not hist:
            self.history_menu.add(rumps.MenuItem("(nothing yet)"))
        for h in hist[:20]:
            s = BY_ID[h.song_id]
            self.history_menu.add(rumps.MenuItem(
                f"{time.strftime('%H:%M', time.localtime(h.first_heard))}  #{s.id} {s.composer} – {s.short}"))

    # ---- periodic UI refresh -------------------------------------------
    def tick(self, _):
        if self._pending_alert:
            title, msg = self._pending_alert
            self._pending_alert = None
            rumps.alert(title, msg)
        st = self.engine.status()

        if self._busy_msg:
            self.title = f"{IDLE_ICON} {self._busy_msg}"
        elif st.mode == "learning":
            s = BY_ID[st.learning_song]
            self.title = f"● Learning #{s.id} {fmt_time(st.learning_seconds)}"
            self.now_item.title = f"Recording: {s.label}"
            self.level_item.title = f"Input level {level_bar(st.level)}" + (
                "   ⚠︎ silent?" if st.learning_seconds > 3 and st.level < 1e-4 else "")
        elif st.mode == "listening":
            if st.now_playing:
                s = BY_ID[st.now_playing.song_id]
                self.title = f"{IDLE_ICON} #{s.id} {s.short}"
                self.now_item.title = f"Now: {s.label}  @ {fmt_time(st.now_playing.position)}"
            else:
                self.title = f"{IDLE_ICON} …"
                self.now_item.title = "Listening… (no learned song heard)"
            self.level_item.title = f"Input level {level_bar(st.level)}"
        else:
            self.title = IDLE_ICON
            self.now_item.title = st.error or "Not listening"
            self.level_item.title = f"{len(self.library.meta)} of {len(SONGS)} songs learned"

        self.listen_item.title = "Stop Listening" if st.mode == "listening" else "Start Listening"
        learning = st.mode == "learning"
        self.finish_item.set_callback(self.finish_learning if learning else None)
        self.cancel_item.set_callback(self.cancel_learning if learning else None)
        self.listen_item.set_callback(None if learning else self.toggle_listening)

        if self.engine.version != self._seen_version:
            self._seen_version = self.engine.version
            self._build_history_menu()
            self._build_learn_menu()

    # ---- misc -----------------------------------------------------------
    def show_help(self, _):
        rumps.alert("Setting up system audio", (
            "To recognise what the Mac itself is playing, install BlackHole (the installer "
            "script does this), then:\n\n"
            "1. Open 'Audio MIDI Setup' (Applications ▸ Utilities).\n"
            "2. Click '+' at the bottom left ▸ 'Create Multi-Output Device'.\n"
            "3. Tick your speakers/headphones AND 'BlackHole 2ch'. Put the speakers first "
            "and tick 'Drift Correction' for BlackHole.\n"
            "4. System Settings ▸ Sound ▸ Output: choose 'Multi-Output Device'.\n"
            "5. Here: Input Device ▸ Automatic (should show BlackHole 2ch).\n\n"
            "You keep hearing audio normally; the app hears a copy. "
            "(Volume keys don't work on a Multi-Output Device – set volume in the app playing.)\n\n"
            "No BlackHole? Choose 'System Default Input' to listen via the microphone."))

    def open_data(self, _):
        subprocess.run(["open", str(self.library.dir)])

    def quit_app(self, _):
        self.engine.stop()
        rumps.quit_application()


def main():
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    SongIdentityApp().run()
