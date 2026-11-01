# Song Identity

A Shazam-style recogniser for the class listening playlist. It runs in the macOS
menu bar, listens to what the Mac is playing, and shows which of the 10 pieces is
on (with the chapter and how far into the piece it is).

It comes **pre-trained** on these recordings (`song_identity/catalog.py`):

| # | Piece | Ch. | Source |
|---|-------|-----|--------|
| 1 | Tchaikovsky – Nutcracker, Dance of the Sugar Plum Fairy | 49 | youtu.be/zV1qLYukTH8 |
| 2 | Tchaikovsky – Nutcracker, Trepak | 49 | youtu.be/z2ISRMSIyX8 |
| 3 | Puccini – Madame Butterfly, "Un bel dì" | 50 | youtu.be/c-r2vu4t9-g |
| 4 | Debussy – Prelude to "The Afternoon of a Faun" | 51 | youtu.be/Y9iDOt2WbjY |
| 5 | Dvořák – String Quartet Op. 96 "American", I (0:00–9:03 only) | 52 | youtu.be/_b_rwtDlUXA |
| 6 | Swing Low, Sweet Chariot (arr. Fisk) | 53 | youtu.be/GUvBGZnL9rE |
| 7 | Swing Low, Sweet Chariot (arr. Burleigh) | 53 | youtu.be/yeaMOAwYc5M |
| 8 | Joplin – Maple Leaf Rag | 54 | youtu.be/bCxLAr_bwpA |
| 9 | Brahms – A German Requiem, IV | 48 | youtu.be/Fc3v6mded4g |
| 10 | Brahms – Symphony No. 3, III | 45 | youtu.be/-JXvjejaVEc |

Like Shazam, it recognises **these specific recordings**. A different
performance of the same piece will not match – teach it that recording too
(see "Adding or replacing a recording").

## Install on the Mac (once)

1. Install [Homebrew](https://brew.sh) if it isn't already.
2. Copy this folder to the Mac, open Terminal in it and run:
   ```bash
   bash scripts/install_mac.sh
   ```
   This installs Python, the free **BlackHole** audio driver, ffmpeg and yt-dlp,
   and creates **~/Applications/Song Identity.app**.
3. Let the Mac's sound reach BlackHole *and* your speakers:
   - Open **Audio MIDI Setup** (Applications ▸ Utilities).
   - **+** (bottom left) ▸ **Create Multi-Output Device**.
   - Tick your speakers/headphones **and** "BlackHole 2ch" (speakers first;
     tick *Drift Correction* for BlackHole).
   - **System Settings ▸ Sound ▸ Output** ▸ choose **Multi-Output Device**.
   - (If BlackHole isn't listed, restart the Mac.)
4. Open **Song Identity** from ~/Applications. A ♪ appears in the menu bar.
   Choose **Start Listening** and allow microphone access when asked (macOS
   labels BlackHole access as "microphone").

Note: volume keys don't control a Multi-Output Device – change the volume in the
player instead, or switch Sound Output back to your speakers when you're done.

## Using it

- **♪ ▸ Start Listening** – the menu bar shows e.g. `♪ #8 Maple Leaf Rag` within
  ~5–8 seconds of the music being heard. The menu shows the full title, chapter
  and position; **Recently Heard** keeps a list.
- **Input Device** – *Automatic* picks BlackHole; choose *System Default Input*
  to listen through the microphone instead (e.g. music from another device).
- The *Input level* bar in the menu helps confirm audio is arriving.

## Adding or replacing a recording

From the menu: **Learn a Song ▸ pick the song**, play the recording from the
beginning, then **Finish Learning (save)**. ("Add More" keeps the existing
recording and adds a second one.)

From Terminal (in this folder):
```bash
.venv/bin/song-identity learn 3 --url "https://www.youtube.com/watch?v=..."
.venv/bin/song-identity learn 3 --file ~/Music/un_bel_di.mp3 --add
.venv/bin/song-identity songs            # what's learned
.venv/bin/song-identity listen           # print matches in the terminal
.venv/bin/song-identity identify clip.m4a
```

Data lives in `~/Library/Application Support/SongIdentity`; logs in
`~/Library/Logs/SongIdentity.log`.

## How it works

Landmark fingerprinting (the technique behind Shazam): audio is resampled to
11 kHz mono, turned into a spectrogram, and its strongest peaks are paired into
hashes of (freq₁, freq₂, Δt). A 10-second window from the live audio matches a
song when many of its hashes line up at the *same time offset* in that song.
A song is announced only after two consecutive windows agree on the song and on
its position, which suppresses look-alike passages.

Measured on the real recordings: 80/80 clean clips identified, 79/79 through a
simulated noisy microphone (15 dB SNR), 0 false matches in 16 minutes of the
Dvořák quartet's *other* movements.

## Development (Linux / any OS)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest                # 19 tests; the menu bar is tested with a fake rumps
.venv/bin/song-identity train --force --out song_identity/bundled_library   # rebuild the bundled fingerprints
```
On Linux `listen` captures the default PipeWire sink's monitor.
