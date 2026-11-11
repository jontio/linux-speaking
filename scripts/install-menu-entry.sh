#!/usr/bin/env bash
# Adds "Linux Speaking" to the application menu. Argument: the install folder.
set -euo pipefail
dir="${1:-$HOME/linux-speaking}"
target="$HOME/.local/share/applications"
mkdir -p "$target"
# The green microphone from the tray, as the menu icon.
icon="$dir/linux-speaking.png"
(cd "$dir/app" && "$dir/venv/bin/python" -m dictation.tray --write-icon "$icon") 2>/dev/null \
  || icon=audio-input-microphone
cat > "$target/linux-speaking.desktop" <<ENTRY
[Desktop Entry]
Type=Application
Name=Linux Speaking
GenericName=Voice Dictation
Comment=Dictate into LibreOffice Writer, Thunderbird, Kate, KWrite and VS Code
Exec=$dir/app/scripts/launch.sh
Icon=$icon
Terminal=false
Categories=Utility;Accessibility;
Keywords=dictation;speech;voice;dragon;whisper;
ENTRY
# Refresh the menu. Without the desktop's menu name, as in a remote login, this would do nothing.
command -v kbuildsycoca6 >/dev/null \
  && XDG_MENU_PREFIX="${XDG_MENU_PREFIX:-plasma-}" kbuildsycoca6 >/dev/null 2>&1 || true
echo "menu entry: Linux Speaking"
