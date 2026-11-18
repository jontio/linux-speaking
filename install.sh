#!/usr/bin/env bash
# Installs Linux Speaking for the current user on a Linux desktop. It was built on KDE
# Plasma. Dictation and its commands are in English only.
#
#   git clone https://github.com/jontio/linux-speaking linux-speaking-source
#   cd linux-speaking-source && ./install.sh
#
# (Cloned under another name than the folder it installs into, ~/linux-speaking.)
#
# It asks for your password once, to install system packages, and says which first.
# Everything else goes in your home folder. To update: git pull, then run it again.
# ./uninstall.sh removes it. The Windows installer is install.ps1.
#
# Options, as environment variables:
#   LS_INSTALL_DIR=~/linux-speaking   where to install: a folder of its own
#   LS_SKIP_PACKAGES=1                  don't install system packages
#   LS_SKIP_MODELS=1                    don't download the speech models
#   LS_SKIP_INTEGRATIONS=1              don't touch LibreOffice, Thunderbird, VS Code, Kate,
#                                       the menu or the login service, and don't start it
#   LS_NO_AUTOSTART=1                   don't start it at every login (0 turns that back on;
#                                       left unset, an update keeps what was chosen before)
#   LS_NO_START=1                       don't start it now
#   LS_PYTHON=/usr/bin/python3.12       the Python to build on, if not the system's own
#   LS_ENGINE_ONLY=1                    only copy the program and restart it (for development)
set -euo pipefail
cd "$(dirname "$0")"
dir="${LS_INSTALL_DIR:-$HOME/linux-speaking}"
say() { printf '\n== %s\n' "$*"; }
stop() { printf '%s\n' "$@"; exit 1; }

[ "$(id -u)" != 0 ] || stop "Run this as your normal user, not as root."

# ---- where it goes ---------------------------------------------------------------------
# The program is copied to "$dir/app". From a folder that is $dir itself, or inside it,
# the copy would go into itself. A clone made in the home folder under its own name is
# exactly that.
here="$(pwd -P)"
there="$(realpath -m "$dir")"
case "$here/" in
  "$there"/*)
    echo "This folder is $here, and Linux Speaking installs itself into $there."
    echo "Installing from here would copy the program into itself. Move this folder and"
    echo "run the installer again, for example:"
    echo "  mv \"$here\" \"$HOME/linux-speaking-source\" && cd \"$HOME/linux-speaking-source\" && ./install.sh"
    echo "or install into another folder of its own:  LS_INSTALL_DIR=~/apps/linux-speaking ./install.sh"
    exit 1 ;;
esac
dir="$there"
# The folder's name goes into the login service and the menu entry, which can't hold
# every character.
case "$dir" in
  *[[:space:]\"\'\\%\|\&]*)
    stop "The install folder, $dir, has a space or one of \" ' \\ % | & in its name." \
         "The login service and the menu entry can't be given such a name. Choose another:" \
         "  LS_INSTALL_DIR=~/linux-speaking ./install.sh" ;;
esac
# A folder that already holds other things is not taken over: the program wants one to
# itself. (What an install of its own leaves there is no such thing: an install that was
# cut short can be carried on.)
others_in() {
  local entry
  for entry in "$1"/* "$1"/.[!.]*; do
    [ -e "$entry" ] || [ -L "$entry" ] || continue
    case "$(basename "$entry")" in
      app|venv|models|training|dictionaries|pending.oxt|linux-speaking.png) ;;
      linux-speaking*.xpi|linux-speaking*.vsix) ;;
      *) return 0 ;;
    esac
  done
  return 1
}
if [ -d "$dir" ] && [ ! -d "$dir/app/dictation" ] && others_in "$dir"; then
  stop "$dir is a folder with other things in it, and not an earlier install." \
       "Linux Speaking wants a folder of its own. Name one that doesn't exist yet, such as:" \
       "  LS_INSTALL_DIR=\"$dir/linux-speaking\" ./install.sh"
fi

# ---- room on the disk ------------------------------------------------------------------
# Checked before anything is fetched: a disk that fills half-way leaves half an install.
megabytes_free() {  # on the disk that holds $1, which need not exist yet
  local at="$1"
  while [ ! -e "$at" ]; do at="$(dirname "$at")"; done
  df -Pm "$at" 2>/dev/null | awk 'NR == 2 { print $4 }'
}
if [ "${LS_ENGINE_ONLY:-0}" != 1 ]; then
  need=200
  [ -x "$dir/venv/bin/python" ] || need=$((need + 600))             # the Python packages
  if [ "${LS_SKIP_MODELS:-0}" != 1 ] && [ ! -e "$dir/models/small.en/model.bin" ]; then
    need=$((need + 700))                                             # the two speech models
  fi
  free="$(megabytes_free "$dir" || true)"
  case "$free" in
    ''|*[!0-9]*) ;;                                                  # couldn't be told: carry on
    *) [ "$free" -ge "$need" ] || stop \
         "There isn't enough free disk space. This needs about $need MB in $(dirname "$dir")," \
         "and $free MB is free there. Nothing has been changed." ;;
  esac
fi

# ---- Python ------------------------------------------------------------------------------
# The system's own Python, whatever comes first on PATH: a python3 from conda, pyenv, asdf
# or mise can't see the distribution's PyQt6, which the windows are drawn with.
python=""
python_checked=""
find_python() {
  if [ -n "${LS_PYTHON:-}" ]; then
    python="$(command -v "$LS_PYTHON" || true)"
    [ -n "$python" ] || stop "LS_PYTHON is set to $LS_PYTHON, and there is no such program."
  elif [ -x /usr/bin/python3 ]; then
    python=/usr/bin/python3
  else
    python="$(command -v python3 || true)"
  fi
  [ -n "$python" ]
}
check_python() {
  local version
  [ "$python_checked" != "$python" ] || return 0
  python_checked="$python"
  version="$("$python" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
  [ -n "$version" ] || stop "$python doesn't run, so the install can't go on."
  echo "Using Python $version ($python)"
  "$python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || stop \
    "Linux Speaking needs Python 3.10 or newer, and this is $version." \
    "If a newer one is installed beside it, name it:  LS_PYTHON=/usr/bin/python3.12 ./install.sh" \
    "Nothing has been changed."
}
if find_python; then check_python; fi   # before anything is installed, if it can be told yet

# ---- system packages -----------------------------------------------------------------
packages_failed() {
  echo
  echo "The system packages could not be installed: the lines above say why. Nothing else"
  echo "has been changed. When that is put right, run this again. If the packages are"
  echo "already there, or you would rather install them yourself, skip this step with:"
  echo "  LS_SKIP_PACKAGES=1 ./install.sh"
  exit 1
}
if [ "${LS_SKIP_PACKAGES:-0}" != 1 ]; then
  say "Installing system packages"
  if command -v apt-get >/dev/null; then          # Kubuntu, KDE neon, Debian
    packages=(python3 python3-venv python3-pip python3-numpy python3-pyqt6
      python3-gi gir1.2-atspi-2.0 at-spi2-core pulseaudio-utils zip unzip rsync
      libreoffice-writer python3-uno hunspell-en-us)
    install=(sudo apt-get install -y)
  elif command -v dnf >/dev/null; then            # Fedora KDE
    packages=(python3 python3-pip python3-numpy python3-pyqt6 python3-gobject
      at-spi2-core pulseaudio-utils zip unzip rsync libreoffice-writer libreoffice-pyuno
      hunspell-en-US)
    install=(sudo dnf install -y)
  elif command -v pacman >/dev/null; then         # Arch, Manjaro, EndeavourOS
    packages=(python python-pip python-numpy python-pyqt6
      python-gobject at-spi2-core libpulse zip unzip rsync libreoffice-fresh hunspell-en_us)
    install=(sudo pacman -S --needed --noconfirm)
  elif command -v zypper >/dev/null; then         # openSUSE
    packages=(python3 python3-pip python3-numpy python3-PyQt6 python3-gobject
      typelib-1_0-Atspi-2_0 at-spi2-core pulseaudio-utils zip unzip rsync
      libreoffice-writer libreoffice-pyuno myspell-en_US)
    install=(sudo zypper install -y)
  else
    echo "I don't know this system's package manager. Install these yourself, then run"
    echo "again with LS_SKIP_PACKAGES=1: Python 3.10 or newer with venv, numpy, PyQt6 and"
    echo "PyGObject, the AT-SPI typelib, parec (PulseAudio utilities), zip, rsync,"
    echo "LibreOffice Writer with its Python support, and an English Hunspell dictionary."
    exit 1
  fi
  echo "These are asked of the system's package manager, which needs your password. Those"
  echo "already installed are left as they are:"
  printf '%s\n' "${packages[*]}" | fold -s -w 78 | sed 's/^/  /'
  echo "(To install them yourself instead, stop now with Ctrl-C and run this again with"
  echo "LS_SKIP_PACKAGES=1.)"
  if command -v apt-get >/dev/null; then
    # One source that no longer answers, such as a PPA left from an older release, makes
    # this fail while every package wanted can still be had.
    sudo apt-get update || echo "The package lists could not all be refreshed (see above). Carrying on with what is known."
  fi
  "${install[@]}" "${packages[@]}" || packages_failed
fi

find_python || stop "Python 3 wasn't found. Install it (3.10 or newer), then run this again."
check_python
for tool in parec zip rsync; do
  command -v "$tool" >/dev/null || stop \
    "Missing: $tool. Install it and run this again. (parec comes with the PulseAudio utilities.)"
done
"$python" -c "import PyQt6.QtWidgets, numpy" 2>/dev/null || stop \
  "This Python can't find PyQt6 or numpy:  $python" \
  "They come as system packages (python3-pyqt6 and python3-numpy, or your distribution's" \
  "names for them). Install those and run this again. If the Python named above is not" \
  "your system's own, say which one is:  LS_PYTHON=/usr/bin/python3 ./install.sh"

# ---- the program ---------------------------------------------------------------------
have_systemd() { command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; }
have_service() { have_systemd && systemctl --user cat linux-speaking.service >/dev/null 2>&1; }
running() { pgrep -u "$(id -u)" -f -- "-m dictation.tray" >/dev/null 2>&1; }

update=0
[ ! -d "$dir/app/dictation" ] || update=1   # an install was here already: this is an update
say "Copying the program to $dir"
mkdir -p "$dir/app"
# (What an install keeps beside the program is left out too: a folder that was once
# installed into, and has since been moved aside, would bring all of it along.)
rsync -a --delete --exclude .git --exclude build --exclude __pycache__ \
  --exclude /app --exclude /venv --exclude /models --exclude /training --exclude /dictionaries \
  --exclude /pending.oxt --exclude '/linux-speaking*.xpi' --exclude '/linux-speaking*.vsix' \
  ./ "$dir/app/"

if [ "${LS_ENGINE_ONLY:-0}" = 1 ]; then
  if have_service; then
    systemctl --user restart linux-speaking.service
    echo "Program updated and restarted."
  elif running; then
    "$dir/app/scripts/launch.sh" restart
    echo "Program updated and restarted."
  else
    echo "Program updated. It isn't running: start it with $dir/app/scripts/launch.sh"
  fi
  exit 0
fi

say "Setting up Python packages (the first time, this downloads a few hundred megabytes)"
# The packages are built for one version of Python. After a distribution upgrade the
# system's Python is a newer one, and the old packages no longer load: they are thrown
# away and fetched again. The same if the Python they were built on has gone.
was_running=0
built_on() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2], sys.base_prefix)' 2>/dev/null || true; }
if [ -e "$dir/venv" ] && [ "$(built_on "$dir/venv/bin/python")" != "$(built_on "$python")" ]; then
  echo "The Python packages here were set up for another Python than $python"
  echo "(the system's has been upgraded, perhaps). Setting them up again from nothing."
  if running; then
    was_running=1
    "$dir/app/scripts/launch.sh" stop || true   # it can't go on running on packages that are going
  fi
  "$python" -m venv --clear --system-site-packages "$dir/venv"
fi
# System packages stay visible, so the distribution's PyQt6 and numpy are used.
[ -x "$dir/venv/bin/python" ] || "$python" -m venv --system-site-packages "$dir/venv"
# The list of packages and versions is requirements.txt, which install.ps1 uses too.
"$dir/venv/bin/python" -m pip install --upgrade --disable-pip-version-check -r requirements.txt || stop "" \
  "The Python packages could not be installed: the lines above say why. If it was the" \
  "connection, run this again and it carries on. If a package \"could not be found\" or" \
  "\"failed to build\", there may be none made yet for this version of Python: open an" \
  "issue with those lines, and the version, which the first line of this output gives."

if [ "${LS_SKIP_MODELS:-0}" != 1 ]; then
  say "Downloading the speech models (about 650 MB, once)"
  "$dir/venv/bin/python" "$dir/app/scripts/fetch_models.py" "$dir/models" || exit 1
fi

say "Checking that speech recognition loads (ten seconds or so)"
(cd "$dir/app" && LS_INSTALL_DIR="$dir" "$dir/venv/bin/python" scripts/check_install.py) || exit 1

# ---- LibreOffice, Thunderbird, VS Code, Kate, and starting at login -----------------------
writer=""        # what became of the Writer extension: in, waiting, none or failed
editors=""       # the VS Codes its extension went into
editors_failed=""
kate=0           # whether Kate or KWrite is here
started=0        # whether it is running at the end
autostart=""     # yes, no, kept-off, or none where there is no systemd
packaged_office=""   # a LibreOffice that can't be reached: "a Flatpak", "a Snap"

if [ "${LS_SKIP_INTEGRATIONS:-0}" != 1 ]; then
  cd "$dir/app"
  say "Installing the LibreOffice Writer extension"
  ./scripts/build-oxt.sh >/dev/null
  if pgrep -u "$(id -u)" -x soffice.bin >/dev/null; then
    cp build/linux-speaking.oxt "$dir/pending.oxt"
    writer=waiting
    echo "LibreOffice is open. The extension will install itself once you close it."
  elif command -v unopkg >/dev/null; then
    unopkg remove io.github.jontio.linuxspeaking >/dev/null 2>&1 || true
    if unopkg add build/linux-speaking.oxt; then writer=in; else writer=failed; fi
  else
    writer=none
    echo "LibreOffice's unopkg wasn't found, so the Writer extension was skipped."
  fi
  # A LibreOffice from Flatpak or Snap keeps its extensions somewhere else, and is shut
  # off from the rest of the desktop: the extension above is not in it, and it could not
  # be talked to if it were.
  if command -v flatpak >/dev/null 2>&1 && flatpak info org.libreoffice.LibreOffice >/dev/null 2>&1; then
    packaged_office="a Flatpak"
  elif [ -d /var/lib/flatpak/app/org.libreoffice.LibreOffice ] \
      || [ -d "${XDG_DATA_HOME:-$HOME/.local/share}/flatpak/app/org.libreoffice.LibreOffice" ]; then
    packaged_office="a Flatpak"
  elif [ -d /snap/libreoffice ]; then
    packaged_office="a Snap"
  fi
  if [ -n "$packaged_office" ]; then
    echo "A LibreOffice installed as $packaged_office is on this computer. Linux Speaking can't"
    echo "reach that one. Dictate into the LibreOffice from your distribution's own packages."
  fi

  say "Building the Thunderbird add-on"
  ./scripts/build-xpi.sh >/dev/null
  cp -p build/linux-speaking-thunderbird.xpi "$dir/linux-speaking-thunderbird.xpi"  # it holds a key: yours to read only

  say "Installing the Visual Studio Code extension"
  "$dir/venv/bin/python" scripts/build_vsix.py >/dev/null
  cp build/linux-speaking.vsix "$dir/linux-speaking.vsix"
  for editor in code codium code-insiders; do
    command -v "$editor" >/dev/null || continue
    if "$editor" --install-extension "$dir/linux-speaking.vsix" --force >/dev/null 2>&1; then
      editors="$editors $editor"
      echo "Installed in $editor. If it is open, restart it."
    else
      editors_failed="$editors_failed $editor"
      echo "Could not install in $editor. Try: $editor --install-extension \"$dir/linux-speaking.vsix\""
    fi
  done
  [ -n "$editors$editors_failed" ] \
    || echo "VS Code wasn't found. To add it later: code --install-extension \"$dir/linux-speaking.vsix\""

  say "Letting Kate and KWrite be dictated into"
  if ./scripts/enable-editor-accessibility.sh; then
    for app in org.kde.kate org.kde.kwrite; do
      if [ -f "/usr/share/applications/$app.desktop" ]; then kate=1; fi
    done
  fi

  say "Adding it to the application menu"
  ./scripts/install-menu-entry.sh "$dir"

  if have_systemd; then
    units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    # An update keeps what was chosen before: a service that was there and had been set
    # not to start at login is not set to start again, unless that is asked for.
    chosen_off=0
    if [ -f "$units/linux-speaking.service" ] \
        && ! systemctl --user is-enabled --quiet linux-speaking.service 2>/dev/null; then
      chosen_off=1
    fi
    mkdir -p "$units"
    sed "s|%h/linux-speaking|$dir|g" systemd/linux-speaking.service > "$units/linux-speaking.service"
    if [ "$dir" != "$HOME/linux-speaking" ]; then
      sed -i "s|^\[Service\]|[Service]\nEnvironment=LS_INSTALL_DIR=$dir|" "$units/linux-speaking.service"
    fi
    systemctl --user daemon-reload
    case "${LS_NO_AUTOSTART:-}" in
      1) autostart=no ;;
      0) autostart=yes ;;
      *) if [ "$chosen_off" = 1 ]; then autostart=kept-off; else autostart=yes; fi ;;
    esac
    if [ "$autostart" = yes ]; then
      say "Setting it to start at every login"
      systemctl --user enable linux-speaking.service
    else
      systemctl --user disable linux-speaking.service >/dev/null 2>&1 || true
    fi
    if [ "${LS_NO_START:-0}" != 1 ]; then
      say "Starting it"
      systemctl --user restart linux-speaking.service && started=1
    fi
  else
    autostart=none
    say "Starting it"
    echo "This system has no systemd user session, which is what would start Linux Speaking"
    echo "at login and from its menu entry. So no login service has been set up: the menu"
    echo "entry starts the program itself."
    if [ "${LS_NO_START:-0}" != 1 ]; then
      if ./scripts/launch.sh restart; then started=1; fi
    fi
  fi
elif [ "$was_running" = 1 ]; then
  "$dir/app/scripts/launch.sh" start && started=1   # it was stopped above, for its packages
fi

# ---- what was done, and what to do next ----------------------------------------------------
launcher="$dir/app/scripts/launch.sh"
echo
echo "Done. Linux Speaking is installed in $dir."
echo
if [ "$started" = 1 ]; then
  echo "It is running: look for the microphone icon in your system tray. It is purple while"
  echo "the speech models load, then orange: asleep, and listening only for \"wake up\"."
  if [ "$update" = 0 ]; then
    echo "This first time, a welcome window opens. It shows whether the microphone hears you,"
    echo "has a box to try dictating into, and a button that fetches Parakeet Unified, the"
    echo "recommended speech model. It is \"Getting started\" in the icon's menu afterwards."
  fi
else
  echo "It has not been started. Start it from the application menu (\"Linux Speaking\","
  echo "under Utilities), or with:  $launcher"
fi
case "$autostart" in
  yes)      echo "It will start by itself at every login." ;;
  no)       echo "It will not start at login. To change that:  systemctl --user enable linux-speaking" ;;
  kept-off) echo "It was set not to start at login, and that has been kept. To change it:"
            echo "  systemctl --user enable linux-speaking" ;;
  none)     echo "It will not start at login by itself. To have that, add this command to your"
            echo "desktop's autostart settings:  $launcher start" ;;
esac
echo
echo "To dictate, click into a document, say \"wake up\", and talk. Say \"go to sleep\" to"
echo "stop. Dictation and its commands are in English only. Where it works:"
case "$writer" in
  in)      echo "  - LibreOffice Writer: ready. If Writer is open, close it and open it again." ;;
  waiting) echo "  - LibreOffice Writer: NOT YET. LibreOffice was open, so its extension is waiting."
           echo "    Save your work and close LibreOffice. A notice says when Writer is ready"
           echo "    (about ten seconds), and it can then be opened again." ;;
  none)    echo "  - LibreOffice Writer: NOT SET UP, because LibreOffice's unopkg wasn't found."
           echo "    Install LibreOffice Writer from your distribution's packages and run this again." ;;
  failed)  echo "  - LibreOffice Writer: NOT SET UP. Its extension could not be added (see the lines"
           echo "    from unopkg above). Close LibreOffice and run this again." ;;
esac
[ -z "$packaged_office" ] || echo "    (Not the LibreOffice installed as $packaged_office: that one can't be reached.)"
if [ "${LS_SKIP_INTEGRATIONS:-0}" != 1 ]; then
  [ -z "$editors" ] || echo "  - VS Code ($(echo $editors | sed 's/ /, /g')): ready once it has been restarted."
  [ -z "$editors_failed" ] || echo "  - VS Code ($(echo $editors_failed | sed 's/ /, /g')): NOT SET UP. Its extension could not be added (see above)."
  [ "$kate" = 0 ] || echo "  - Kate and KWrite: close them, and start them from the application menu."
  echo "  - Thunderbird: one step is left for you, below."
  echo "  - Any other program's text boxes: tick \"Dictate into other programs' text boxes\""
  echo "    in Settings."
  cat <<DONE

Right-click the tray icon for "What can I say?", the microphone level, and Settings.

ONE STEP IS LEFT FOR YOU, and only if you use Thunderbird. Its add-on has to be added by
hand, because Thunderbird doesn't let a program install one for you:

  1. In Thunderbird, open the menu and choose "Add-ons and Themes".
  2. Click the gear icon near the top and choose "Install Add-on From File".
  3. Pick this file:  $dir/linux-speaking-thunderbird.xpi
  4. Click Add, then open a new message or reply. Windows that were already open
     won't have it.

That file is for this computer only: don't pass it on. If you had the add-on from an
earlier version, add it again from this file, or Thunderbird is no longer answered.
DONE
else
  echo "  - Nothing has been tied into LibreOffice, Thunderbird, VS Code, Kate or the menu,"
  echo "    because LS_SKIP_INTEGRATIONS=1 was set."
fi
echo
echo "A headset microphone works best. To update later: git pull in this folder, then"
echo "./install.sh again. To remove it: ./uninstall.sh (a copy is kept in $dir/app)."
