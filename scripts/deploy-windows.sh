#!/usr/bin/env bash
# From WSL: copies the engine to the Windows side of this computer, where install.ps1
# put the rest. For development; a normal install uses install.ps1 on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."
home=$(wslpath "$(cd /mnt/c && cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")
target="${LS_WINDOWS_DIR:-$home/linux-speaking}"
mkdir -p "$target/app"
rsync -a --delete --exclude __pycache__ dictation scripts LICENSE requirements.txt install.ps1 "$target/app/" 2>/dev/null \
  || rsync -a --delete --exclude __pycache__ dictation scripts LICENSE requirements.txt "$target/app/"
cp uninstall.ps1 "$target/uninstall.ps1" 2>/dev/null || true   # where install.ps1 keeps it
echo "copied to $target/app"
