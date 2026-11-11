"""The desktop's accessibility switch.

Programs only describe their text boxes to other programs while this is on. A screen
reader turns it on; so does the "other programs" setting. It is put back the way it was
found when that setting is switched off.
"""
from __future__ import annotations

import os
import subprocess

from . import config

_ARGS = ["busctl", "--user", "{verb}-property", "org.a11y.Bus", "/org/a11y/bus",
         "org.a11y.Status", "IsEnabled"]
MARKER = os.path.join(os.path.dirname(config.STATE_FILE), "accessibility-turned-on")


def is_on() -> bool | None:
    """Whether the switch is on, or None if that can't be told."""
    try:
        out = subprocess.run([a.format(verb="get") for a in _ARGS],
                             capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return out[1] == "true" if len(out) == 2 and out[0] == "b" else None


def _set(on: bool) -> bool:
    try:
        done = subprocess.run([a.format(verb="set") for a in _ARGS] + ["b", "true" if on else "false"],
                              capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def apply(wanted: bool) -> str:
    """Make the switch match the setting. Returns a line for the log, or ""."""
    if wanted:
        if is_on() is False and _set(True):
            os.makedirs(os.path.dirname(MARKER), exist_ok=True)
            open(MARKER, "w").close()   # remember that it was off before
            return "desktop accessibility switched on"
        return ""
    if os.path.exists(MARKER):
        os.remove(MARKER)
        if _set(False):
            return "desktop accessibility switched back off"
    return ""
