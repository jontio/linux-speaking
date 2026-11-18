#!/usr/bin/env bash
# Makes Kate and KWrite start with their accessibility interface on, which dictation
# needs. Only those two programs are affected.
#
#   enable-editor-accessibility.sh          switch it on (the installer runs this)
#   enable-editor-accessibility.sh --undo   put things back (the uninstaller runs this)
#
# A program's launcher in ~/.local/share/applications is used in place of the system's.
# So a copy of each of the two launchers is put there with one setting added to its
# command, and made afresh from the system's at every install, so that it keeps up with
# the distribution's. If you already have a launcher of your own there, it is not
# replaced: the setting is added to it where it is, and a copy of it as it was is kept
# beside it, ending in ".before-linux-speaking". Undoing takes the setting out of yours
# again, and removes the copies that were made here.
set -euo pipefail
target="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
setting="QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1"
undo=0
case "${1:-}" in
  "") ;;
  --undo) undo=1 ;;
  *) echo "usage: enable-editor-accessibility.sh [--undo]"; exit 2 ;;
esac

add_setting='s/^Exec=(env +)?(QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 +)?/Exec=env QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 /'
# Out again, and "env" with it unless it has other settings to carry.
drop_setting='s/^Exec=env +QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 +/Exec=env /; s/^Exec=env +([^= ]+)( |$)/Exec=\1\2/'

for app in org.kde.kate org.kde.kwrite; do
  system="/usr/share/applications/$app.desktop"
  mine="$target/$app.desktop"
  before="$mine.before-linux-speaking"
  if [ "$undo" = 1 ]; then
    if [ -f "$before" ]; then                      # your own launcher: the setting comes out
      sed -i -E "$drop_setting" "$mine" 2>/dev/null || cp -p "$before" "$mine"
      rm -f "$before"
      echo "$app: your own launcher is as it was"
    elif grep -q "$setting" "$mine" 2>/dev/null; then   # a copy made here
      rm -f "$mine"
      echo "$app: back to the system's launcher"
    fi
    continue
  fi
  mkdir -p "$target"
  if [ -f "$mine" ] && { [ -f "$before" ] || ! grep -q "$setting" "$mine"; }; then
    # A launcher of your own. Changed where it is, once.
    if ! grep -q "$setting" "$mine"; then
      [ -f "$before" ] || cp -p "$mine" "$before"
      sed -i -E "$add_setting" "$mine"
      echo "$app: you have a launcher of your own, so the setting was added to it. A copy"
      echo "  of it as it was: $before"
    fi
  elif [ -f "$system" ]; then
    sed -E "$add_setting" "$system" > "$mine"
  else
    continue
  fi
  echo "$app: $(grep -m1 '^Exec=' "$mine")"
done
command -v kbuildsycoca6 >/dev/null \
  && XDG_MENU_PREFIX="${XDG_MENU_PREFIX:-plasma-}" kbuildsycoca6 >/dev/null 2>&1 || true
