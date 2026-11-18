#!/usr/bin/env bash
# Builds build/linux-speaking-thunderbird.xpi, the Thunderbird add-on, for this computer.
#
# The add-on and the engine prove themselves to each other with a key (see
# dictation/mailbridge.py). It is made here the first time, kept where the engine reads
# it, and written into the add-on's file. So the file is this computer's own: it is not
# for passing on, and only you can read it.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
key_file="${LS_MAIL_KEY_FILE:-}"
[ -n "$key_file" ] || key_file="$(dirname "${LS_SETTINGS_FILE:-$HOME/.config/linux-speaking/settings.json}")/mail-key"
if [ ! -s "$key_file" ]; then
  mkdir -p "$(dirname "$key_file")"
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$key_file"
  echo >> "$key_file"
fi
# Read as the engine reads it (read_key in dictation/mailbridge.py): the figures 0 to 9 and
# a to f, capitals made small, and nothing else. So a key that somebody has written by
# hand comes out the same at both ends.
key="$(tr 'A-F' 'a-f' < "$key_file" | tr -cd '0-9a-f')"
[ "${#key}" -ge 32 ] || { echo "the key in $key_file is not one: delete that file and run this again"; exit 1; }
rm -rf build/xpi && mkdir -p build/xpi
cp thunderbird/manifest.json thunderbird/background.js thunderbird/compose.js build/xpi/
printf '// The key of the computer this file was made on. See key.js in the source.\n"use strict";\n\nconst LINUX_SPEAKING_KEY = "%s";\n' "$key" > build/xpi/key.js
rm -f build/linux-speaking-thunderbird.xpi
(cd build/xpi && zip -q ../linux-speaking-thunderbird.xpi manifest.json key.js background.js compose.js)
rm -rf build/xpi
echo "built build/linux-speaking-thunderbird.xpi"
