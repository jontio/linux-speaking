#!/usr/bin/env bash
# Installs Linux Speaking for the current user on a KDE Plasma desktop.
#
#   git clone https://github.com/jontio/linux-speaking && cd linux-speaking && ./install.sh
#
# It asks for your password once, to install system packages. Everything else goes in
# your home folder. Run it again at any time to update. ./uninstall.sh removes it.
#
# Options, as environment variables:
#   LS_INSTALL_DIR=~/linux-speaking   where to install
#   LS_SKIP_PACKAGES=1                  don't install system packages
#   LS_SKIP_MODELS=1                    don't download the speech models
#   LS_SKIP_INTEGRATIONS=1              don't touch LibreOffice, Kate or the login service
#   LS_ENGINE_ONLY=1                    only copy the program and restart it (for development)
set -euo pipefail
cd "$(dirname "$0")"
dir="${LS_INSTALL_DIR:-$HOME/linux-speaking}"
say() { printf '\n== %s\n' "$*"; }

[ "$(id -u)" != 0 ] || { echo "Run this as your normal user, not as root."; exit 1; }

# ---- system packages -----------------------------------------------------------------
if [ "${LS_SKIP_PACKAGES:-0}" != 1 ]; then
  say "Installing system packages"
  if command -v apt-get >/dev/null; then          # Kubuntu, KDE neon, Debian
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip python3-numpy python3-pyqt6 \
      python3-gi gir1.2-atspi-2.0 at-spi2-core pulseaudio-utils zip unzip rsync \
      libreoffice-writer python3-uno hunspell-en-us
  elif command -v dnf >/dev/null; then            # Fedora KDE
    sudo dnf install -y python3 python3-pip python3-numpy python3-pyqt6 python3-gobject \
      at-spi2-core pulseaudio-utils zip unzip rsync libreoffice-writer libreoffice-pyuno \
      hunspell-en-US
  elif command -v pacman >/dev/null; then         # Arch, Manjaro, EndeavourOS
    sudo pacman -S --needed --noconfirm python python-pip python-numpy python-pyqt6 \
      python-gobject at-spi2-core libpulse zip unzip rsync libreoffice-fresh hunspell-en_us
  elif command -v zypper >/dev/null; then         # openSUSE
    sudo zypper install -y python3 python3-pip python3-numpy python3-PyQt6 python3-gobject \
      typelib-1_0-Atspi-2_0 at-spi2-core pulseaudio-utils zip unzip rsync \
      libreoffice-writer libreoffice-pyuno myspell-en_US
  else
    echo "I don't know this system's package manager. Install these yourself, then run"
    echo "again with LS_SKIP_PACKAGES=1: Python 3 with venv, numpy, PyQt6 and PyGObject,"
    echo "the AT-SPI typelib, parec (PulseAudio utilities), zip, rsync, LibreOffice Writer"
    echo "with its Python support, and an English Hunspell dictionary."
    exit 1
  fi
fi

for tool in python3 parec zip rsync; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool"; exit 1; }
done
python3 -c "import PyQt6.QtWidgets, numpy" 2>/dev/null \
  || { echo "Python can't find PyQt6 or numpy."; exit 1; }

# ---- the program ---------------------------------------------------------------------
say "Copying the program to $dir"
mkdir -p "$dir/app"
rsync -a --delete --exclude .git --exclude build --exclude __pycache__ ./ "$dir/app/"

if [ "${LS_ENGINE_ONLY:-0}" = 1 ]; then
  systemctl --user restart linux-speaking.service
  echo "Program updated and restarted."
  exit 0
fi

say "Setting up Python packages (this downloads a few hundred megabytes)"
# System packages stay visible, so the distribution's PyQt6 and numpy are used.
[ -x "$dir/venv/bin/python" ] || python3 -m venv --system-site-packages "$dir/venv"
"$dir/venv/bin/pip" install --quiet --upgrade faster-whisper

if [ "${LS_SKIP_MODELS:-0}" != 1 ]; then
  say "Downloading the speech models (about 650 MB, once)"
  "$dir/venv/bin/python" - "$dir/models" <<'PY'
import os, sys
from huggingface_hub import snapshot_download
for name in ("base.en", "small.en"):
    target = os.path.join(sys.argv[1], name)
    if os.path.exists(os.path.join(target, "model.bin")):
        print(name, "already here")
        continue
    print("downloading", name, flush=True)
    snapshot_download("Systran/faster-whisper-" + name, local_dir=target,
                      allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
PY
fi

say "Checking that speech recognition loads"
(cd "$dir/app" && LS_INSTALL_DIR="$dir" "$dir/venv/bin/python" - <<'PY'
import os
from dictation import config
for name in (config.ASLEEP_MODEL, config.AWAKE_MODEL):
    path = os.path.join(config.MODEL_DIR, name)
    assert os.path.exists(os.path.join(path, "model.bin")), "no speech model at " + path
from dictation.engine import Transcriber
Transcriber()
print("speech models load from", config.MODEL_DIR)
PY
)

# ---- LibreOffice, Thunderbird, Kate, and starting at login -------------------------------
if [ "${LS_SKIP_INTEGRATIONS:-0}" != 1 ]; then
  cd "$dir/app"
  say "Installing the LibreOffice Writer extension"
  ./scripts/build-oxt.sh >/dev/null
  if pgrep -x soffice.bin >/dev/null; then
    cp build/linux-speaking.oxt "$dir/pending.oxt"
    echo "LibreOffice is open. The extension will install itself once you close it."
  elif command -v unopkg >/dev/null; then
    unopkg remove io.github.jontio.linuxspeaking >/dev/null 2>&1 || true
    unopkg add build/linux-speaking.oxt
  else
    echo "LibreOffice's unopkg wasn't found, so the Writer extension was skipped."
  fi

  say "Building the Thunderbird add-on"
  ./scripts/build-xpi.sh >/dev/null
  cp build/linux-speaking-thunderbird.xpi "$dir/linux-speaking-thunderbird.xpi"

  say "Installing the Visual Studio Code extension"
  ./scripts/build-vsix.sh >/dev/null
  cp build/linux-speaking.vsix "$dir/linux-speaking.vsix"
  found=0
  for editor in code codium code-insiders; do
    command -v "$editor" >/dev/null || continue
    found=1
    if "$editor" --install-extension "$dir/linux-speaking.vsix" --force >/dev/null 2>&1; then
      echo "Installed in $editor. If it is open, restart it."
    else
      echo "Could not install in $editor. Try: $editor --install-extension $dir/linux-speaking.vsix"
    fi
  done
  [ "$found" = 1 ] || echo "VS Code wasn't found. To add it later: code --install-extension $dir/linux-speaking.vsix"

  say "Letting Kate and KWrite be dictated into"
  ./scripts/enable-editor-accessibility.sh || true

  say "Adding it to the application menu"
  ./scripts/install-menu-entry.sh "$dir"

  say "Starting it now and at every login"
  mkdir -p "$HOME/.config/systemd/user"
  sed "s|%h/linux-speaking|$dir|g" systemd/linux-speaking.service \
    > "$HOME/.config/systemd/user/linux-speaking.service"
  if [ "$dir" != "$HOME/linux-speaking" ]; then
    sed -i "s|^\[Service\]|[Service]\nEnvironment=LS_INSTALL_DIR=$dir|" \
      "$HOME/.config/systemd/user/linux-speaking.service"
  fi
  systemctl --user daemon-reload
  systemctl --user enable linux-speaking.service
  systemctl --user restart linux-speaking.service
fi

cat <<DONE

Done. A microphone icon is now in your system tray, and "Linux Speaking" is in
your application menu.

  - Open LibreOffice Writer, say "wake up", and dictate. Say "go to sleep" to stop.
  - Right-click the tray icon for Settings and the microphone level meter.
  - Kate, KWrite and VS Code: close them and start them again.

ONE STEP IS LEFT FOR YOU, and only if you use Thunderbird. Its add-on has to be added by
hand, because Thunderbird doesn't let a program install one for you:

  1. In Thunderbird, open the menu and choose "Add-ons and Themes".
  2. Click the gear icon near the top and choose "Install Add-on From File".
  3. Pick this file:  $dir/linux-speaking-thunderbird.xpi
  4. Click Add, then open a new message or reply. Windows that were already open
     won't have it.

A headset microphone works best.
DONE
