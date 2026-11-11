#!/usr/bin/env bash
# Installs or updates Linux Speaking on another computer, over ssh.
#
#   scripts/deploy.sh user@host
#
# It copies this folder there and runs install.sh on it. Options for install.sh, such as
# LS_ENGINE_ONLY=1 or LS_SKIP_PACKAGES=1, are passed along. System packages are skipped by
# default, because installing them needs a password typed at that computer.
set -euo pipefail
cd "$(dirname "$0")/.."
host="${1:?usage: scripts/deploy.sh user@host}"
rsync -a --delete --exclude .git --exclude build --exclude __pycache__ ./ "$host:.cache/linux-speaking-source/"
ssh -o BatchMode=yes "$host" "cd .cache/linux-speaking-source && \
  LS_SKIP_PACKAGES=${LS_SKIP_PACKAGES:-1} LS_ENGINE_ONLY=${LS_ENGINE_ONLY:-0} \
  LS_SKIP_MODELS=${LS_SKIP_MODELS:-0} LS_SKIP_INTEGRATIONS=${LS_SKIP_INTEGRATIONS:-0} ./install.sh"
