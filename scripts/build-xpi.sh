#!/usr/bin/env bash
# Builds build/linux-speaking-thunderbird.xpi, the Thunderbird add-on.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p build
rm -f build/linux-speaking-thunderbird.xpi
(cd thunderbird && zip -q ../build/linux-speaking-thunderbird.xpi manifest.json background.js compose.js)
echo "built build/linux-speaking-thunderbird.xpi"
