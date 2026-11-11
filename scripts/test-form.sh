#!/usr/bin/env bash
# Tests dictation into an ordinary program's text boxes, using a small form window with
# accessibility switched on for that window only. The window shows for a few seconds.
set -euo pipefail
cd "$(dirname "$0")/.."
unit="ls-form-test-$$"
systemd-run --user --collect --quiet --unit="$unit" \
  --setenv=QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 python3 "$PWD/scripts/form_window.py"
cleanup() { systemctl --user stop "$unit" 2>/dev/null || true; systemctl --user reset-failed "$unit" 2>/dev/null || true; }
trap cleanup EXIT
sleep 2
python3 scripts/form_test.py
