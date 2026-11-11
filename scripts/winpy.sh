#!/usr/bin/env bash
# From WSL: runs a Python file with the Windows install's Python, in its app folder.
#   scripts/winpy.sh 'tmp\check.py' [arguments]   (paths as Windows sees them, from the install folder)
set -euo pipefail
script="$1"; shift
cd /mnt/c
powershell.exe -NoProfile -NonInteractive -Command "\$d = Join-Path \$env:USERPROFILE 'linux-speaking'; Set-Location \"\$d\\app\"; \$env:PYTHONUTF8 = '1'; & \"\$d\\venv\\Scripts\\python.exe\" \"\$d\\$script\" $* 2>&1 | ForEach-Object { \"\$_\" }; exit \$LASTEXITCODE" | tr -d '\r'
