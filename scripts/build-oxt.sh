#!/usr/bin/env bash
# Builds build/linux-speaking.oxt: the extension plus copies of the rule modules.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build/oxt && mkdir -p build/oxt
cp -r extension/. build/oxt/
mkdir -p build/oxt/pythonpath/dictation
cp dictation/__init__.py dictation/formatting.py dictation/words.py dictation/selecting.py \
   build/oxt/pythonpath/dictation/
find build/oxt -name __pycache__ -prune -exec rm -rf {} +
rm -f build/linux-speaking.oxt
(cd build/oxt && zip -qr ../linux-speaking.oxt .)
echo "built build/linux-speaking.oxt"
