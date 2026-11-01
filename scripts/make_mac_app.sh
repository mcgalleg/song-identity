#!/bin/bash
# Wraps the menu bar app in a double-clickable "Song Identity.app" in /Applications
# (or ~/Applications if /Applications is not writable).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -w /Applications ]]; then
  APP="/Applications/Song Identity.app"
  rm -rf "$HOME/Applications/Song Identity.app"  # remove copy from older installs
else
  mkdir -p "$HOME/Applications"
  APP="$HOME/Applications/Song Identity.app"
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/MacOS/SongIdentity" <<EOF
#!/bin/bash
mkdir -p "\$HOME/Library/Logs"
exec "$ROOT/.venv/bin/python" -m song_identity menubar >> "\$HOME/Library/Logs/SongIdentity.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/SongIdentity"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Song Identity</string>
  <key>CFBundleDisplayName</key><string>Song Identity</string>
  <key>CFBundleIdentifier</key><string>com.songidentity.app</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SongIdentity</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Song Identity listens to the audio playing on this Mac (via BlackHole or the microphone) to recognise songs.</string>
</dict>
</plist>
EOF

codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
echo "Created: $APP"
