#!/usr/bin/env bash
# Removes Linux Speaking from your account. System packages are left installed.
set -uo pipefail
dir="${LS_INSTALL_DIR:-$HOME/linux-speaking}"
systemctl --user disable --now linux-speaking.service 2>/dev/null
rm -f "$HOME/.config/systemd/user/linux-speaking.service"
systemctl --user daemon-reload
if pgrep -x soffice.bin >/dev/null; then
  echo "LibreOffice is open: close it and run this again to remove its extension."
else
  unopkg remove io.github.jontio.linuxspeaking 2>/dev/null
fi
for app in org.kde.kate org.kde.kwrite; do
  file="$HOME/.local/share/applications/$app.desktop"
  grep -q QT_LINUX_ACCESSIBILITY_ALWAYS_ON "$file" 2>/dev/null && rm -f "$file"
done
rm -f "$HOME/.local/share/applications/linux-speaking.desktop"
rm -rf "$dir" "$HOME/.config/linux-speaking" "$HOME/.local/state/linux-speaking"
echo "Removed. In Thunderbird, remove the Linux Speaking add-on from Add-ons and Themes."
