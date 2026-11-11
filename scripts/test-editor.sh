#!/usr/bin/env bash
# Tests dictation into Kate's editor, using a scratch KWrite window with accessibility
# switched on for that window only. The window shows on screen for a few seconds.
set -euo pipefail
cd "$(dirname "$0")/.."
file=$(mktemp --suffix=.txt)
unit="wd-editor-test-$$"
systemd-run --user --collect --quiet --unit="$unit" \
  --setenv=QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 kwrite "$file"
cleanup() { pkill -9 -f "kwrite $file" 2>/dev/null || true; systemctl --user reset-failed "$unit" 2>/dev/null || true; rm -f "$file"; }
trap cleanup EXIT
sleep 3
python3 scripts/editor_test.py
