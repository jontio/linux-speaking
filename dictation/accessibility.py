"""The desktop's accessibility switch.

Programs only describe their text boxes to other programs while this is on. A screen
reader turns it on; so does the "other programs" setting. It is put back the way it was
found when that setting is switched off, and by the uninstaller:

    python -m dictation.accessibility restore

The switch is a property on the session's message bus. It is reached with systemd's
busctl, or, on a system without systemd, with GLib's gdbus.
"""
from __future__ import annotations

import os
import subprocess
import sys

from . import config

_WHERE = ["org.a11y.Bus", "/org/a11y/bus"]
_WHAT = ["org.a11y.Status", "IsEnabled"]
_BUSCTL = ["busctl", "--user", "{verb}-property"] + _WHERE + _WHAT
_GDBUS = ["gdbus", "call", "--session", "--dest", _WHERE[0], "--object-path", _WHERE[1],
          "--method", "org.freedesktop.DBus.Properties.{verb}"] + _WHAT
MARKER = os.path.join(os.path.dirname(config.STATE_FILE), "accessibility-turned-on")


def _run(args: list):
    """What a command printed, or None if it isn't there, failed or took too long."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def is_on() -> bool | None:
    """Whether the switch is on, or None if that can't be told."""
    out = _run([a.format(verb="get") for a in _BUSCTL])
    if out is not None:
        words = out.split()
        return words[1] == "true" if len(words) == 2 and words[0] == "b" else None
    out = _run([a.format(verb="Get") for a in _GDBUS])    # it answers "(<true>,)"
    if out is not None and out.strip() in ("(<true>,)", "(<false>,)"):
        return "true" in out
    return None


def _set(on: bool) -> bool:
    word = "true" if on else "false"
    if _run([a.format(verb="set") for a in _BUSCTL] + ["b", word]) is not None:
        return True
    return _run([a.format(verb="Set") for a in _GDBUS] + [f"<{word}>"]) is not None


def apply(wanted: bool) -> str:
    """Make the switch match the setting. Returns a line for the log, or ""."""
    if wanted:
        if is_on() is False and _set(True):
            os.makedirs(os.path.dirname(MARKER), exist_ok=True)
            open(MARKER, "w").close()   # remember that it was off before
            return "desktop accessibility switched on"
        return ""
    if os.path.exists(MARKER) and _set(False):
        os.remove(MARKER)               # (kept if the switch couldn't be reached: tried again later)
        return "desktop accessibility switched back off"
    return ""


def main(args=None) -> int:
    args = sys.argv[1:] if args is None else list(args)
    if args != ["restore"]:
        print("usage: python -m dictation.accessibility restore")
        return 2
    said = apply(False)                 # nothing, unless it was this program that switched it on
    if said:
        print(said)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
