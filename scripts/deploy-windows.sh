#!/usr/bin/env bash
# From WSL: copies the engine to the Windows side of this computer, where install.ps1
# put the rest. For development; a normal install uses install.ps1 on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."
home=$(wslpath "$(cd /mnt/c && cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")
target="${LS_WINDOWS_DIR:-$home/linux-speaking}"
mkdir -p "$target/app"
rsync -a --delete --exclude __pycache__ dictation scripts LICENSE install.ps1 "$target/app/" 2>/dev/null \
  || rsync -a --delete --exclude __pycache__ dictation scripts LICENSE "$target/app/"
echo "copied to $target/app"
