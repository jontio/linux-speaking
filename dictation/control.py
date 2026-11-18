"""Asking the running app to do something, from a command line or from a second start.

    python -m dictation.control toggle|wake|sleep|off|settings

run from the app folder, with the Python the app itself runs on. It is there to be bound
to a key of your own in the desktop's shortcut settings: "toggle" does what a click on
the tray icon does. It prints one line, and ends with 1 if the app isn't running.

The asking is done by leaving a word in a small file that the app looks for a few times a
second: the same file the application menu's entry touches to have Settings shown. Only
one copy of the app may run, since two would both type what is said; the same lock that
sees to that is how this tells whether there is anyone to ask.
"""
from __future__ import annotations

import os
import sys
import time

from . import APP_NAME, config

# What can be asked for on the command line, and what is said back.
COMMANDS = {
    "toggle": "Asked it to switch: awake if it was asleep or off, off if it was awake.",
    "wake": "Asked it to wake up.",
    "sleep": "Asked it to go to sleep.",
    "off": "Asked it to turn the microphone off.",
    "settings": "Asked it to show its Settings window.",
}
SHOW = "show"  # what a second start asks of the first, and what an empty file means
MUTEX = "Local\\LinuxSpeaking"  # Windows: held by the one app that is running

_held = None  # the lock, kept for as long as this program runs


def request_file() -> str:
    return config.SHOW_FILE


def lock_file() -> str:
    return os.path.join(os.path.dirname(config.STATE_FILE), "running")


def ask(word: str, path: str = "") -> None:
    """Leave a request for the running app. Added to any that are waiting, so that two
    asked in quick succession are both done."""
    path = path or request_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Written whole under another name and then put in place: the app looks several
    # times a second, and a file it found made but not yet written would read as the
    # empty one that asks only for the window to be shown.
    waiting = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            waiting = f.read()
    except OSError:
        pass
    new = f"{path}.{os.getpid()}.new"
    with open(new, "w", encoding="utf-8") as f:
        f.write(waiting + word + "\n")
    os.replace(new, path)


def taken(path: str = "") -> list:
    """The requests left since this last looked, the oldest first; they are removed. An
    empty file, as the menu entry's launcher leaves, asks for the app to show itself."""
    path = path or request_file()
    mine = path + ".taken"
    try:
        # Taken whole, under another name: a request written a moment later starts a
        # new file, and is found the next time round.
        os.replace(path, mine)
    except OSError:
        return []  # nothing asked, or (Windows) it is being written just now
    try:
        with open(mine, encoding="utf-8", errors="replace") as f:
            words = [line.strip().lower() for line in f.read().splitlines()]
    except OSError:
        words = []
    try:
        os.remove(mine)
    except OSError:
        pass
    return [word for word in words if word][:20] or [SHOW]


def only_one(path: str = "") -> bool:
    """Claim to be the one copy of the app that runs. False if another has that already.
    Where it can't be told, this one runs."""
    global _held
    if config.WINDOWS:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _held = kernel32.CreateMutexW(None, False, MUTEX)
        return ctypes.get_last_error() != 183  # 183: it already exists
    import fcntl
    path = path or lock_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path, "a")
    except OSError:
        return True
    for last in (False, False, False, False, True):
        try:
            # Let go by the system when the program ends, however it ends: nothing stale
            # is left behind by a crash.
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            # Another copy has it: or something only asking whether one is running,
            # which holds it for an instant to find out. So it is tried a few times.
            if last:
                lock.close()
                return False
            time.sleep(0.1)
        except OSError:  # a folder that can't lock, such as some network ones
            lock.close()
            return True
    _held = lock
    return True


def running(path: str = "") -> bool:
    """Whether the app is running, for this person. Where it can't be told, yes: the
    request is then left for it all the same."""
    if config.WINDOWS:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenMutexW(0x00100000, False, MUTEX)  # only to see that it is there
        if handle:
            kernel32.CloseHandle(handle)
        return bool(handle)
    import fcntl
    path = path or lock_file()
    try:
        lock = open(path, "r")
    except OSError:
        return False  # no app has ever run here
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return True
    finally:
        lock.close()  # and with it the lock, if this got it
    return False


def main(argv=None, out=print) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1 or args[0] not in COMMANDS:
        out("Say what to ask of it: python -m dictation.control " + "|".join(COMMANDS))
        return 2
    if not running():
        out(f"{APP_NAME} isn't running. Start it from the application menu first.")
        return 1
    try:
        ask(args[0])
    except OSError as e:
        out(f"{APP_NAME} could not be asked: {e.strerror or e}")
        return 1
    out(COMMANDS[args[0]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
