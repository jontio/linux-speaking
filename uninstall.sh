#!/usr/bin/env bash
# Removes Linux Speaking from your account.
#
#   ./uninstall.sh           asks before removing what you recorded and what was trained
#   ./uninstall.sh --purge   removes those too, without asking   (or LS_PURGE=1)
#   ./uninstall.sh --keep    keeps them, without asking          (or LS_KEEP=1)
#
# It finds the install folder by itself: from where this file is, from the login service,
# or from the menu entry. LS_INSTALL_DIR names it if it has to be told.
#
# It removes the program, its Python packages, the speech models, your settings, and what
# ties it into the desktop: the login service, the menu entry, the Writer and VS Code
# extensions, the setting added to Kate's and KWrite's launchers, and the line the app
# may have added to VS Code's argv.json. Only what the installer and the app put in the
# install folder is taken out of it, and the folder goes if it is then empty.
#
# What it can't remove, it says at the end. docs/LINUX.md lists the rest of what is left.
set -uo pipefail

purge="${LS_PURGE:-0}"
keep="${LS_KEEP:-0}"
for arg in "$@"; do
  case "$arg" in
    --purge) purge=1 ;;
    --keep) keep=1 ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "usage: uninstall.sh [--purge | --keep]"; exit 2 ;;
  esac
done
if [ "$purge" = 1 ] && [ "$keep" = 1 ]; then
  echo "Both --purge and --keep were asked for (or LS_PURGE and LS_KEEP). Choose one."
  exit 2
fi
[ "$(id -u)" != 0 ] || { echo "Run this as your normal user, not as root."; exit 1; }

here="$(cd "$(dirname "$0")" && pwd -P)"
state="$HOME/.local/state/linux-speaking"
settings="$HOME/.config/linux-speaking"
units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit="$units/linux-speaking.service"
menu="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
entry="$menu/linux-speaking.desktop"

# ---- which folder ------------------------------------------------------------------------
dir=""
found_by=""
if [ -n "${LS_INSTALL_DIR:-}" ]; then
  dir="$LS_INSTALL_DIR"; found_by="LS_INSTALL_DIR"
elif [ "$(basename "$here")" = app ] && [ -d "$here/dictation" ] && [ -e "$(dirname "$here")/venv" ]; then
  dir="$(dirname "$here")"; found_by="where this file is"
fi
if [ -z "$dir" ] && [ -f "$unit" ]; then
  # The service runs <folder>/venv/bin/python; "%h" in it stands for the home folder.
  dir="$(sed -n 's|^ExecStart=\(.*\)/venv/bin/python .*|\1|p' "$unit" | head -n 1 | sed "s|^%h|$HOME|")"
  found_by="the login service"
fi
if [ -z "$dir" ] && [ -f "$entry" ]; then
  dir="$(sed -n 's|^Exec=\(.*\)/app/scripts/launch\.sh.*|\1|p' "$entry" | head -n 1)"
  found_by="the menu entry"
fi
if [ -z "$dir" ]; then
  dir="$HOME/linux-speaking"; found_by="the usual place"
fi
dir="$(realpath -m "$dir")"

installed=1
if [ ! -e "$dir" ]; then
  installed=0
elif [ ! -d "$dir/app/dictation" ]; then
  # The program itself is the one sure sign. A folder that merely has a "models" or a
  # "venv" in it, as many a folder of somebody's own does, is not taken for an install.
  echo "$dir (from $found_by) doesn't look like Linux Speaking's folder: the"
  echo "program isn't in it (there is no app/dictation). Nothing has been removed."
  echo "If it is installed somewhere else, say where:  LS_INSTALL_DIR=/that/folder $0"
  exit 1
fi
case "$here/" in
  "$dir"/app/*) ;;
  "$dir"/*)
    # An old mishap: a clone that was installed into itself. Only the install's own
    # things are taken out of it below; the clone stays.
    echo "This folder is inside $dir. Only what the installer put there will be removed." ;;
esac
if [ "$installed" = 1 ]; then
  echo "Removing Linux Speaking from $dir (found from $found_by)."
else
  echo "There is no folder $dir (looked for from $found_by), so only what ties"
  echo "Linux Speaking into the desktop, and its settings, are being removed. If the program"
  echo "is installed somewhere else, run this again and say where:"
  echo "  LS_INSTALL_DIR=/that/folder $0"
fi

# ---- what is yours ---------------------------------------------------------------------
size() { du -sh "$1" 2>/dev/null | cut -f1; }
count() { find "$1" -type f -name "$2" 2>/dev/null | wc -l | tr -d ' '; }
yours=()
readings=0; noises=0
if [ -d "$state/training" ]; then readings="$(count "$state/training" '*.wav')"; fi
if [ -d "$state/noises" ]; then noises="$(count "$state/noises" '*.wav')"; fi
many() { if [ "$1" = 1 ]; then echo "1 $2"; else echo "$1 $2s"; fi; }
[ "$readings" = 0 ] || yours+=("$(many "$readings" sentence) read aloud for training ($(size "$state/training")), in $state/training")
[ ! -f "$state/voice-test.wav" ] || yours+=("the recording made for the voice test ($(size "$state/voice-test.wav")), $state/voice-test.wav")
[ "$noises" = 0 ] || yours+=("$(many "$noises" sound) marked \"that was a noise\" ($(size "$state/noises")), in $state/noises")
samples=0
if [ -d "$state/samples" ]; then samples="$(count "$state/samples" 'sample.json')"; fi
[ "$samples" = 0 ] || yours+=("$(many "$samples" "dictation sample") ($(size "$state/samples")), in $state/samples")
retrained=()   # models retrained to your voice: each has a trained.json in its folder
for about in "$dir"/models/*/trained.json; do
  [ -f "$about" ] || continue
  retrained+=("$(dirname "$about")")
  yours+=("the retrained model \"$(basename "$(dirname "$about")")\" ($(size "$(dirname "$about")")), in $dir/models")
done

if [ "${#yours[@]}" -gt 0 ] && [ "$purge" != 1 ] && [ "$keep" != 1 ]; then
  echo
  echo "These are yours, and can't be got back once they are removed:"
  printf '  - %s\n' "${yours[@]}"
  if [ -t 0 ]; then
    printf 'Remove them as well? Type "yes" to remove them; anything else keeps them: '
    read -r answer || answer=""
    case "$answer" in yes|Yes|YES|y|Y) purge=1 ;; *) keep=1 ;; esac
  else
    echo "Nobody is here to ask, so they are kept. (--purge removes them without asking.)"
    keep=1
  fi
fi

# ---- LibreOffice ---------------------------------------------------------------------------
office_open() { pgrep -u "$(id -u)" -x soffice.bin >/dev/null 2>&1; }
if office_open && [ -t 0 ]; then
  echo
  echo "LibreOffice is open, and its extension can only be taken out while it is closed."
  printf 'Close LibreOffice, then press Enter to carry on (or Ctrl-C to stop here, with nothing removed): '
  read -r _ || true
fi

# ---- stop it -------------------------------------------------------------------------------
systemd=0
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then systemd=1; fi
[ "$systemd" = 0 ] || systemctl --user disable --now linux-speaking.service >/dev/null 2>&1
pkill -u "$(id -u)" -f -- "-m dictation.tray" 2>/dev/null     # one that was started directly
# A training run, or an install of the training tools, goes on by itself: stop those too.
pkill -u "$(id -u)" -f -- "-m dictation.trainer" 2>/dev/null
pkill -u "$(id -u)" -f -- "scripts/install-training.sh" 2>/dev/null

# ---- put back what was changed ---------------------------------------------------------------
# While the program's own files are still here to do it with. (Both need only Python itself.)
python=/usr/bin/python3
[ -x "$python" ] || python="$(command -v python3 || true)"
source="$here"
[ -d "$source/dictation" ] || source="$dir/app"
if [ -n "$python" ] && [ -d "$source/dictation" ]; then
  # The desktop's accessibility switch, if it was "other programs' text boxes" that
  # switched it on, and the line that setting added to VS Code's argv.json.
  (cd "$source" && PYTHONDONTWRITEBYTECODE=1 "$python" -m dictation.accessibility restore) 2>/dev/null
  (cd "$source" && PYTHONDONTWRITEBYTECODE=1 "$python" -m dictation.vscode_args --remove) 2>/dev/null
fi
if [ -f "$source/scripts/enable-editor-accessibility.sh" ]; then
  bash "$source/scripts/enable-editor-accessibility.sh" --undo
fi

# ---- what ties it into the desktop --------------------------------------------------------
rm -f "$unit"
rm -rf "$units/linux-speaking.service.d"      # extra settings added with "systemctl --user edit"
if [ "$systemd" = 1 ]; then
  systemctl --user daemon-reload
  systemctl --user reset-failed linux-speaking.service >/dev/null 2>&1
fi
rm -f "$entry"
left=()   # what is still there, to be said at the end
if office_open; then
  left+=("The Writer extension is still in LibreOffice, which is open. Remove it there, under Tools > Extensions (or Extension Manager), or close LibreOffice and run:  unopkg remove io.github.jontio.linuxspeaking")
elif command -v unopkg >/dev/null 2>&1; then
  unopkg remove io.github.jontio.linuxspeaking >/dev/null 2>&1
fi
for editor in code codium code-insiders; do
  command -v "$editor" >/dev/null 2>&1 && "$editor" --uninstall-extension jontio.linux-speaking >/dev/null 2>&1
done

# ---- the files -------------------------------------------------------------------------------
if [ "$installed" = 1 ]; then
  rm -rf "$dir/app" "$dir/venv" "$dir/training" "$dir/dictionaries" "$dir/pending.oxt" \
    "$dir/linux-speaking.png" "$dir"/linux-speaking*.xpi "$dir"/linux-speaking*.vsix
  if [ "$keep" = 1 ] && [ "${#retrained[@]}" -gt 0 ]; then
    for model in "$dir"/models/* "$dir"/models/.[!.]*; do
      [ -e "$model" ] || [ -L "$model" ] || continue
      [ -f "$model/trained.json" ] || rm -rf "$model"
    done
  else
    rm -rf "$dir/models"
  fi
  rmdir "$dir/models" 2>/dev/null
  rmdir "$dir" 2>/dev/null
fi
# The training tools, if they were put somewhere else and this was told where.
if [ -n "${LS_TRAINING_DIR:-}" ] && [ -d "$LS_TRAINING_DIR/boot" ]; then
  rm -rf "$LS_TRAINING_DIR/boot" "$LS_TRAINING_DIR/venv" "$LS_TRAINING_DIR/python" "$LS_TRAINING_DIR/cache"
  rmdir "$LS_TRAINING_DIR" 2>/dev/null
fi
rm -rf "$settings"
if [ "$keep" = 1 ] && [ -d "$state" ]; then
  for thing in "$state"/* "$state"/.[!.]*; do
    [ -e "$thing" ] || [ -L "$thing" ] || continue
    case "$(basename "$thing")" in
      training|noises|samples|voice-test.wav|voice-test.json) ;;
      *) rm -rf "$thing" ;;
    esac
  done
  rmdir "$state" 2>/dev/null
else
  rm -rf "$state"
fi

# ---- what happened ---------------------------------------------------------------------------
echo
failed=0
if [ -e "$dir/app" ] || [ -e "$dir/venv" ]; then
  failed=1
  echo "NOT ALL OF IT COULD BE REMOVED. The program is still in $dir:"
  echo "something there could not be deleted (the lines above say what). Put that right and"
  echo "run this again, or delete the folder yourself."
elif [ "$installed" = 1 ]; then
  echo "Linux Speaking has been removed: the program, its Python packages, the speech models,"
  echo "your settings, the login service and the menu entry."
else
  echo "Linux Speaking's settings, login service and menu entry have been removed. No program"
  echo "folder was found at $dir, so none was removed."
fi
if [ "$keep" = 1 ] && [ "${#yours[@]}" -gt 0 ]; then
  echo
  echo "Kept, as they were:"
  printf '  - %s\n' "${yours[@]}"
  echo "A later install finds them again. To be rid of them, delete those folders."
fi
if [ -d "$dir" ] && [ "$failed" = 0 ]; then
  if [ -n "$(find "$dir" -mindepth 1 -maxdepth 1 ! -name models 2>/dev/null | head -n 1)" ]; then
    left+=("$dir is still there, because it holds other things than Linux Speaking's. They have not been touched.")
  fi
fi
left+=("In Thunderbird, remove the Linux Speaking add-on yourself: Add-ons and Themes, then Remove.")
left+=("The system packages the installer asked for (LibreOffice Writer among them) are still installed, and so is the folder you installed from. \"Uninstalling\" in docs/LINUX.md lists these and the few other things that stay.")
echo
echo "Left for you:"
printf '  - %s\n' "${left[@]}" | fold -s -w 88 | sed '/^  - /!s/^/    /'
exit "$failed"
