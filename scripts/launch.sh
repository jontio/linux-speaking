#!/usr/bin/env bash
# Starts Linux Speaking, and passes orders on to it. This is what the application menu's
# entry runs, and what a keyboard shortcut of your own can run.
#
#   launch.sh            start it if it isn't running, and show its window, so that
#                        clicking the menu entry always does something visible
#   launch.sh start      start it if it isn't running, and nothing more
#   launch.sh stop       stop it
#   launch.sh restart    stop it and start it again
#
#   launch.sh toggle     switch dictation: wake it if it is asleep or off, switch it off
#                        if it is awake. The one to bind to a key.
#   launch.sh wake | sleep | off | settings
#                        the same orders one by one, and the Settings window
#
# Where there is a login service (systemd) it is started and stopped through that, and the
# log is in the journal. Where there isn't, the program is started directly, and its log
# is ~/.local/state/linux-speaking/log.txt.
set -u
dir="$(cd "$(dirname "$0")/../.." && pwd -P)"
if [ ! -x "$dir/venv/bin/python" ]; then    # run from a copy of the source, not an install
  dir="${LS_INSTALL_DIR:-$HOME/linux-speaking}"
fi
export LS_INSTALL_DIR="$dir"
state="$HOME/.local/state/linux-speaking"
python="$dir/venv/bin/python"
[ -x "$python" ] || { echo "Linux Speaking isn't installed in $dir: there is no $python"; exit 1; }

has_service() {
  command -v systemctl >/dev/null 2>&1 && systemctl --user cat linux-speaking.service >/dev/null 2>&1
}
running() { pgrep -u "$(id -u)" -f -- "-m dictation.tray" >/dev/null 2>&1; }

start() {
  if has_service; then
    systemctl --user start linux-speaking.service
    return
  fi
  running && return 0
  # Directly, cut loose from whatever started it, so that closing a terminal doesn't end it.
  mkdir -p "$state"
  log="$state/log.txt"
  if [ "$(stat -c %s "$log" 2>/dev/null || echo 0)" -gt 1000000 ]; then : > "$log"; fi
  cd "$dir/app" || exit 1
  if command -v setsid >/dev/null 2>&1; then
    PYTHONUNBUFFERED=1 setsid "$python" -m dictation.tray >> "$log" 2>&1 < /dev/null &
  else
    PYTHONUNBUFFERED=1 nohup "$python" -m dictation.tray >> "$log" 2>&1 < /dev/null &
  fi
}

stop() {
  if has_service; then systemctl --user stop linux-speaking.service; fi
  # One that was started directly, too.
  running || return 0
  pkill -u "$(id -u)" -f -- "-m dictation.tray"
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    running || return 0
    sleep 0.5
  done
  pkill -9 -u "$(id -u)" -f -- "-m dictation.tray"
}

case "${1:-}" in
  "")
    mkdir -p "$state"
    touch "$state/show"
    start ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  toggle|wake|sleep|off|settings)
    cd "$dir/app" || exit 1
    exec "$python" -m dictation.control "$1" ;;
  *)
    echo "usage: launch.sh [start | stop | restart | toggle | wake | sleep | off | settings]"
    exit 2 ;;
esac
