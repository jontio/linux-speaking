#!/usr/bin/env bash
# Builds build/linux-speaking.vsix, the Visual Studio Code extension.
set -euo pipefail
exec python3 "$(dirname "$0")/build_vsix.py" "$@"
