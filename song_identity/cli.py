"""Command-line interface. Run `python -m song_identity --help`."""

import argparse
import sys
import time

from . import settings
from .audio import auto_device, download_url, list_input_devices, load_file
from .catalog import BY_ID, SONGS
from .engine import Engine
from .store import Library as _Library


def Library(data_dir=None):
    return _Library(data_dir, seed_bundled=data_dir is None)


def fmt_time(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def resolve_device(arg: str | None) -> str | None:
    if arg:
        return None if arg == "default" else arg
    saved = settings.load().get("device")
    if saved and saved != "auto":
        return None if saved == "default" else saved
    return auto_device()


def cmd_songs(args):
    lib = Library()
    for s in SONGS:
        m = lib.meta.get(s.id)
        mark = f"learned {fmt_time(m['seconds'])} ({m['sessions']} session(s))" if m else "not learned"
        print(f"{s.label:<90} {mark}")


def cmd_devices(args):
    print("Input devices:")
    for n in list_input_devices():
        print("  ", n)
    print("Automatic choice:", auto_device() or "system default input (microphone)")


def cmd_learn(args):
    lib = Library()
    song = BY_ID[args.song]
    if args.file or args.url:
        audio = load_file(args.file) if args.file else download_url(args.url, args.end)
        n = lib.learn(song.id, audio, replace=not args.add)
        print(f"Learned {song.label} ({len(audio) / 11025:.0f} s, {n} fingerprints).")
        return
    eng = Engine(lib, device=resolve_device(args.device))
    eng.start_learning(song.id, replace=not args.add)
    print(f"Recording {song.label}")
    print("Play the piece from the beginning now. Press Enter when it has finished"
          + (f" (or wait {args.seconds}s)." if args.seconds else "."))
    try:
        if args.seconds:
            end = time.time() + args.seconds
            while time.time() < end:
                st = eng.status()
                print(f"\r  {fmt_time(st.learning_seconds)}  level {st.level:.3f}   ", end="", flush=True)
                time.sleep(0.5)
        else:
            input()
    except KeyboardInterrupt:
        eng.stop()
        print("\nCancelled – nothing learned.")
        return
    print()
    eng.finish_learning()
    m = lib.meta[song.id]
    print(f"Learned {song.short}: {fmt_time(m['seconds'])} of audio, {m['hashes']} fingerprints.")


def cmd_listen(args):
    lib = Library()
    if not lib.meta:
        print("No songs learned yet. Use `learn` first.")
        return 1

    def on_match(m):
        print(f"[{time.strftime('%H:%M:%S')}] ♪ {BY_ID[m.song_id].label}  "
              f"(at {fmt_time(m.position)}, score {m.score})", flush=True)

    eng = Engine(lib, device=resolve_device(args.device), on_match=on_match)
    eng.start_listening()
    print("Listening… (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        eng.stop()


def cmd_identify(args):
    lib = Library()
    m = lib.match(load_file(args.file)[: 15 * 11025] if not args.full else load_file(args.file))
    if m:
        print(f"{BY_ID[m.song_id].label}  (at {fmt_time(m.position)}, score {m.score} vs {m.runner_up})")
    else:
        print("No match.")
        return 1


def cmd_train(args):
    """Learn every catalog song from its recording URL."""
    lib = Library(args.out)
    failed = 0
    for song in SONGS:
        if args.only and song.id not in args.only:
            continue
        if lib.is_learned(song.id) and not args.force:
            print(f"✓ {song.label} (already learned)")
            continue
        print(f"… {song.label}\n    {song.url}", flush=True)
        try:
            audio = download_url(song.url, song.end)
            lib.learn(song.id, audio)
            print(f"✓ learned {fmt_time(len(audio) / 11025)}", flush=True)
        except Exception as e:
            failed += 1
            print(f"✗ {e}", flush=True)
    return 1 if failed else 0


def cmd_forget(args):
    Library().forget(args.song)
    print(f"Forgot {BY_ID[args.song].label}")


def cmd_menubar(args):
    from .menubar import main
    main()


def main(argv=None):
    p = argparse.ArgumentParser(prog="song-identity", description="Recognise the class listening songs.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("menubar", help="run the macOS menu bar app (default on Mac)").set_defaults(fn=cmd_menubar)
    sub.add_parser("songs", help="list songs and whether they are learned").set_defaults(fn=cmd_songs)
    sub.add_parser("devices", help="list audio input devices").set_defaults(fn=cmd_devices)

    song_arg = dict(type=int, choices=sorted(BY_ID), metavar="SONG#")
    lp = sub.add_parser("learn", help="learn a song by playing it once")
    lp.add_argument("song", **song_arg)
    lp.add_argument("--file", help="learn from an audio file instead of live audio")
    lp.add_argument("--url", help="learn from a YouTube (or other yt-dlp supported) link")
    lp.add_argument("--end", type=int, help="with --url: only use the first N seconds")
    lp.add_argument("--seconds", type=int, help="stop recording automatically after N seconds")
    lp.add_argument("--add", action="store_true", help="add to what was learned before instead of replacing")
    lp.add_argument("--device", help="input device name ('default' = system default input)")
    lp.set_defaults(fn=cmd_learn)

    li = sub.add_parser("listen", help="listen and print songs as they are recognised")
    li.add_argument("--device", help="input device name ('default' = system default input)")
    li.set_defaults(fn=cmd_listen)

    ip = sub.add_parser("identify", help="identify an audio file")
    ip.add_argument("file")
    ip.add_argument("--full", action="store_true", help="use the whole file, not just the first 15 s")
    ip.set_defaults(fn=cmd_identify)

    tp = sub.add_parser("train", help="learn all songs from the recording links in the catalog")
    tp.add_argument("--force", action="store_true", help="re-learn songs that are already learned")
    tp.add_argument("--only", type=int, nargs="+", metavar="SONG#", help="only these songs")
    tp.add_argument("--out", help="library folder (default: the app's data folder)")
    tp.set_defaults(fn=cmd_train)

    fp = sub.add_parser("forget", help="delete what was learned for a song")
    fp.add_argument("song", **song_arg)
    fp.set_defaults(fn=cmd_forget)

    args = p.parse_args(argv)
    if not args.cmd:
        if sys.platform == "darwin":
            return cmd_menubar(args)
        p.print_help()
        return 0
    return args.fn(args) or 0
