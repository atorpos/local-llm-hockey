#!/bin/bash
# Run daily.py every hour in the background (macOS launchd).
#   ./schedule_hourly.sh           install / reinstall the hourly job
#   ./schedule_hourly.sh --remove  stop and remove it
set -euo pipefail

LABEL="local.nhl-game-tracker"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ "${1:-}" == "--remove" ]]; then
  rm -f "$PLIST"
  echo "Removed the hourly job."
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  echo "No virtual environment at $DIR/.venv. Create it first (see README)." >&2
  exit 1
fi

mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$DIR/daily.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/logs/daily.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/daily.log</string>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Hourly job installed. It runs now and then every hour."
echo "Log:     tail -f \"$DIR/logs/daily.log\""
echo "Results: $DIR/out/games/"
