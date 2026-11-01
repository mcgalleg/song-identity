#!/bin/bash
# One-time setup on the Mac. Run from Terminal:   bash scripts/install_mac.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This installer is for macOS." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it from https://brew.sh then run this script again." >&2
  exit 1
fi

say "Installing Python, BlackHole (system-audio driver), ffmpeg and yt-dlp via Homebrew"
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
brew list yt-dlp >/dev/null 2>&1 || brew install yt-dlp
if ! brew list --cask blackhole-2ch >/dev/null 2>&1; then
  echo "BlackHole's installer will ask for your Mac password."
  brew install --cask blackhole-2ch
fi
PY="$(brew --prefix python@3.12)/bin/python3.12"

say "Creating the app's Python environment"
"$PY" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --quiet --upgrade pip
"$ROOT/.venv/bin/pip" install --quiet -e "$ROOT[mac]"

# rumps notifications need an Info.plist next to the Python executable
PYBIN_DIR="$(dirname "$("$ROOT/.venv/bin/python" -c 'import sys; print(sys.executable)')")"
if [[ ! -f "$PYBIN_DIR/Info.plist" ]]; then
  /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string "com.songidentity.python"' "$PYBIN_DIR/Info.plist" >/dev/null 2>&1 || true
fi

say "Building 'Song Identity.app'"
bash "$ROOT/scripts/make_mac_app.sh"

say "Done!"
cat <<'EOF'
Last step (once): route the Mac's sound to BlackHole as well as your speakers
  1. Open "Audio MIDI Setup" (Applications ▸ Utilities).
  2. Click "+" (bottom left) ▸ "Create Multi-Output Device".
  3. Tick your speakers/headphones AND "BlackHole 2ch" (speakers first;
     tick "Drift Correction" next to BlackHole).
  4. System Settings ▸ Sound ▸ Output ▸ choose "Multi-Output Device".
  If BlackHole doesn't appear, restart the Mac.

Then open "Song Identity" from your Applications folder. A ♪ appears in the
menu bar; choose "Start Listening". Allow microphone access when macOS asks
(that is how macOS labels access to BlackHole).
EOF
