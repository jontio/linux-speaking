#!/usr/bin/env bash
# Makes Kate and KWrite start with their accessibility interface on, which dictation
# needs. Only those two programs are affected. It copies their launchers into
# ~/.local/share/applications with one setting added. To undo, delete those two files.
set -euo pipefail
target="$HOME/.local/share/applications"
mkdir -p "$target"
for app in org.kde.kate org.kde.kwrite; do
  source="/usr/share/applications/$app.desktop"
  [ -f "$source" ] || continue
  sed -E 's/^Exec=(env +)?(QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 +)?/Exec=env QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 /' \
    "$source" > "$target/$app.desktop"
  echo "$app: $(grep -m1 '^Exec=' "$target/$app.desktop")"
done
command -v kbuildsycoca6 >/dev/null \
  && XDG_MENU_PREFIX="${XDG_MENU_PREFIX:-plasma-}" kbuildsycoca6 >/dev/null 2>&1 || true
