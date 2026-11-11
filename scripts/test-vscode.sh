#!/usr/bin/env bash
# Tests the VS Code extension in a separate VS Code window with its own settings and a
# scratch Markdown file. The window shows on screen for a few seconds. Your own VS Code
# windows and settings are not touched. Run from the repo root, in a desktop session.
# Optional argument: another test script to run against the window.
set -euo pipefail
cd "$(dirname "$0")/.."
code="${CODE:-code}"
work="$PWD/build/vscode-test"
rm -rf "$work" && mkdir -p "$work"
: > "$work/test.md"
: > "$work/test.cpp"
mkdir -p "$work/data/User"
echo '{ "workbench.startupEditor": "none", "telemetry.telemetryLevel": "off", "update.mode": "none" }' \
  > "$work/data/User/settings.json"
# If the clangd extension is installed for you, lend a copy to the test window, so the
# language-server parts can be tested as well.
mkdir -p "$work/extensions"
for found in "$HOME"/.vscode/extensions/llvm-vs-code-extensions.vscode-clangd-*; do
  [ -d "$found" ] && cp -r "$found" "$work/extensions/" && break
done
unit="ls-vscode-test-$$"
systemd-run --user --collect --quiet --unit="$unit" \
  --setenv=LINUX_SPEAKING_VSCODE_SOCKET="$work/test.sock" --setenv=LINUX_SPEAKING_NO_FOCUS_CHECK=1 \
  "$code" --user-data-dir "$work/data" --extensions-dir "$work/extensions" \
  --extensionDevelopmentPath="$PWD/vscode" --disable-workspace-trust --skip-welcome \
  --skip-release-notes --disable-telemetry --new-window "$work/test.md"
cleanup() {
  # Ask the window to quit, so VS Code doesn't report it as crashed. Force it only if
  # it is still there ten seconds later.
  PYTHONPATH="$PWD" python3 -c 'import sys; from dictation import client
try: client.send(sys.argv[1], {"op": "quit"}, 3)
except Exception: pass' "$work/test.sock" || true
  for _ in $(seq 20); do pgrep -f "[-]-user-data-dir $work/data" >/dev/null || break; sleep 0.5; done
  pkill -f "[-]-user-data-dir $work/data" 2>/dev/null || true
  systemctl --user reset-failed "$unit" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
python3 "${1:-scripts/vscode_test.py}" "$work/test.sock"
