#!/usr/bin/env bash
# Builds build/linux-speaking.vsix, the Visual Studio Code extension.
set -euo pipefail
# It needs nothing but Python itself. The system's own is asked for by name, so that a
# python3 put first on PATH by conda, pyenv and their like is not what runs it.
python=/usr/bin/python3
[ -x "$python" ] || python=python3
exec "$python" "$(dirname "$0")/build_vsix.py" "$@"
