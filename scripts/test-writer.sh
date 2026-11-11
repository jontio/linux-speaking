#!/usr/bin/env bash
# Tests the extension against a hidden LibreOffice with its own throwaway profile.
# Run on a machine with LibreOffice. Optional arguments: another test script and its arguments.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/build-oxt.sh
work=$(mktemp -d)
profile="-env:UserInstallation=file://$work/profile"
export LINUX_SPEAKING_SOCKET="$work/test.sock" LINUX_SPEAKING_NO_FOCUS_CHECK=1 LINUX_SPEAKING_CHOICE_SECONDS=2
unopkg add "$profile" build/linux-speaking.oxt >"$work/unopkg.log" 2>&1 || { cat "$work/unopkg.log"; exit 1; }
soffice "$profile" --headless --norestore --nologo private:factory/swriter >"$work/soffice.log" 2>&1 &
pid=$!
cleanup() { kill $pid 2>/dev/null || true; sleep 1; pkill -f "$work/profile" 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT
[ $# -gt 0 ] || set -- scripts/writer_test.py
${PYTHON:-python3} "$@" || { echo "--- soffice log"; tail -20 "$work/soffice.log"; exit 1; }
