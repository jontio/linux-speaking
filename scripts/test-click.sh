#!/usr/bin/env bash
# Tests "click OK": a scratch window with a button and a tick box, pressed by their names
# through the accessibility service. The window shows on screen for a few seconds.
set -euo pipefail
cd "$(dirname "$0")/.."
python="${PYTHON:-python3}"
made=$(mktemp -u)
unit="wd-click-test-$$"
systemd-run --user --collect --quiet --unit="$unit" \
  --setenv=QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 "$python" "$PWD/scripts/click_window.py" "$made"
cleanup() { systemctl --user stop "$unit" 2>/dev/null || true; systemctl --user reset-failed "$unit" 2>/dev/null || true; rm -f "$made".*; }
trap cleanup EXIT
sleep 3
"$python" scripts/click_test.py "$made"
