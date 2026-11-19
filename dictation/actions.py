"""Commands of your own that do something: press keys, open a thing, run a program.

They are written in Settings beside the shortcuts that type a text, one to a line, "what
is said = what is done":

    new tab      = keys: ctrl+t
    my notes     = open: ~/notes.txt
    build it     = run: make -C ~/project
    morning news = open: https://example.org/news
        wait: 2
        keys: ctrl+l

What is done is one of

    keys: ctrl+shift+t         keys held together; several, one after another: ctrl+k ctrl+s
    open: a file, a folder or a web page, with the program that usually opens it
    run:  a program, with whatever is to be given to it
    type: a text, typed as a shortcut's is
    wait: so many seconds, for a program to be ready for the next step
    ask first                  "say yes" has to be said before the rest is done

A line that begins with a space, under one of these, is a further step, done after it.
Under a shortcut that types a text it is another line of the text, as it always was:
but for a line of keys, or a wait, which is a step there too, so that a text can be typed
and Enter pressed after it:

    git status = git status --short
        keys: enter

Only what is written there is ever done. A command has to be said by itself, as a phrase
of its own, word for word; nothing that is said is passed to a program, or to a shell:
there is no shell. Running programs is switched off until it is switched on in Settings,
and a command that runs one has to be two words or more, because one short word is what a
noise or a slip of the tongue is most easily taken for.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time

from . import config

KINDS = ("keys", "open", "run", "type", "wait")
ASK = "ask first"
MOST_STEPS = 12
LONGEST_WAIT = 10.0     # seconds, for one step
MOST_WAITING = 30.0     # and for all the waits of one command
ASK_WAIT = 20.0         # how long the desktop's question about keys is waited for (Linux)
BETWEEN_KEYS = 0.05     # between one press and the next

# Keys by the names they may be written with. Letters and figures are themselves.
_NAMED = ("ctrl shift alt win enter tab escape space backspace delete insert home end "
          "pageup pagedown left right up down plus minus comma period slash").split()
KEY_NAMES = frozenset(_NAMED) | {f"f{n}" for n in range(1, 13)} \
    | set("abcdefghijklmnopqrstuvwxyz0123456789")
_OTHER_NAMES = {"control": "ctrl", "esc": "escape", "return": "enter", "del": "delete",
                "ins": "insert", "pgup": "pageup", "pgdn": "pagedown", "pgdown": "pagedown",
                "windows": "win", "super": "win", "meta": "win", "spacebar": "space",
                "dot": "period", "fullstop": "period"}
MODIFIERS = ("ctrl", "shift", "alt", "win")


class ActionError(Exception):
    """A step couldn't be done. Its text is for the person to read."""


def chords(text: str) -> list:
    """The key presses `text` asks for, each as "ctrl+shift+t": names in small letters,
    as this program knows them. Raises ValueError, in words for the person, if a key
    isn't known."""
    text = " ".join(text.lower().replace(",", " ").split())
    text = text.replace("page up", "pageup").replace("page down", "pagedown")
    text = text.replace("space bar", "space").replace("full stop", "period")
    found = []
    for chord in text.split():
        names = [_OTHER_NAMES.get(name, name) for name in chord.split("+")]
        for name in names:
            if name not in KEY_NAMES:
                raise ValueError(f"\"{name or chord}\" is not a key this program knows")
        if all(name in MODIFIERS for name in names):
            raise ValueError(f"\"{chord}\" holds keys down and presses none")
        found.append("+".join(names))
    if not found:
        raise ValueError("no keys are given")
    return found


def _step(line: str):
    """One step from its line: or None if the line is not one."""
    line = line.strip()
    if line.lower() == ASK:
        return ("ask",)
    kind, colon, rest = line.partition(":")
    kind, rest = kind.strip().lower(), rest.strip()
    if not colon or kind not in KINDS:
        return None
    if kind == "keys":
        return ("keys", chords(rest))
    if kind == "wait":
        try:
            seconds = float(rest.lower().removesuffix("seconds").removesuffix("second")
                            .removesuffix("s").strip())
        except ValueError:
            raise ValueError(f"\"{rest}\" is not a number of seconds to wait") from None
        if not 0 < seconds <= LONGEST_WAIT:
            raise ValueError(f"a wait is up to {LONGEST_WAIT:g} seconds")
        return ("wait", seconds)
    if not rest:
        raise ValueError(f"nothing is given after \"{kind}:\"")
    if kind == "run":
        try:
            if not _arguments(rest):
                raise ValueError("no program is named")
        except ValueError as e:
            raise ValueError(f"the line after \"run:\" can't be read ({e})") from None
    return (kind, rest)


def parse(written: str):
    """The steps of a command, from what stands after its equals sign (further lines
    after line breaks): [("keys", ["ctrl+t"]), ("open", "~/notes.txt"), ("run", "make"),
    ("type", "a text"), ("wait", 2.0), ("ask",)]. None if it is not a command but a text
    to be typed: a shortcut, as there always were.

    Raises ValueError, in words for the person, for a command that can't be understood.
    """
    lines = written.split("\n")
    first = _step(lines[0])
    if first is None:
        # A text to type. If keys are to be pressed after it (or there is a wait), it is
        # a command all the same: the text, and then those. Only those two: a line of an
        # address may well begin "open:" or "type:", and is still part of the address.
        at = next((n for n, line in enumerate(lines)
                   if n and line.strip().lower().partition(":")[0].strip() in ("keys", "wait")
                   and ":" in line), None)
        if at is None:
            return None
        first, lines = ("type", "\n".join(lines[:at])), [""] + lines[at:]
    steps = [first]
    for line in lines[1:]:
        step = _step(line)
        if step is None:
            raise ValueError(f"\"{_short(line.strip())}\" is not a step: a step begins with "
                             + ", ".join(f"\"{kind}:\"" for kind in KINDS))
        steps.append(step)
    if ("ask",) in steps[1:]:
        raise ValueError(f"\"{ASK}\" has to be the first step")
    if steps == [("ask",)]:
        raise ValueError(f"nothing is done after \"{ASK}\"")
    if len(steps) > MOST_STEPS:
        raise ValueError(f"a command has up to {MOST_STEPS} steps")
    if sum(step[1] for step in steps if step[0] == "wait") > MOST_WAITING:
        raise ValueError(f"the waits come to more than {MOST_WAITING:g} seconds")
    return steps


def problem(said: str, written: str) -> str:
    """What is wrong with a command as it is written, in words for the person: "" if
    nothing is, or if it is a shortcut that types a text."""
    try:
        steps = parse(written)
    except ValueError as e:
        return str(e)
    if steps and runs_programs(steps) and len(said.split()) < 2:
        return "a command that runs a program has to be two words or more"
    return ""


def runs_programs(steps) -> bool:
    return any(step[0] == "run" for step in steps)


def kinds(steps) -> str:
    """What a command does, by kind only, for the log: nothing of what was written."""
    return ", ".join(step[0] for step in steps)


def _short(text: str, most: int = 60) -> str:
    return text if len(text) <= most else text[:most - 3] + "..."


def done(step) -> str:
    """What to say of a step that was done, where it leaves nothing to see: "" where the
    doing shows itself."""
    if step[0] == "run":
        return "Ran: " + _short(step[1])
    if step[0] == "open":
        return "Opened: " + _short(step[1])
    return ""


# ---- doing them ---------------------------------------------------------------------------
def _arguments(line: str) -> list:
    """A command line as the program and what is given to it. No shell reads it: a "|"
    or a ">" is only a character. "~" and names such as $HOME (%USERPROFILE% on
    Windows) are filled in."""
    parts = shlex.split(line, posix=not config.WINDOWS)
    if config.WINDOWS:
        parts = [part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
                 for part in parts]
    return [os.path.expanduser(os.path.expandvars(part)) for part in parts]


def _away(command: list) -> list:
    """`command` as it is started so as to outlive this program. On Linux this program
    is a service, and what a service starts is ended with it: so it is started in a
    place of its own, where the system offers the means."""
    if not config.WINDOWS and os.environ.get("INVOCATION_ID") and shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--quiet", "--"] + command
    return command


def let_come_forward() -> bool:
    """Windows: let the window that is about to be opened come to the front.

    Windows keeps a program that isn't in front from putting a window there: what it
    opens is left behind the others, with its button flashing on the taskbar. This
    program is never in front, it lives in the tray, so a folder opened by voice opened
    out of sight. Two things put that right. An input event with nothing in it (a mouse
    that neither moves nor clicks) makes this program the one that last had input, which
    is what Windows goes by; and then it may say that any program may come forward,
    which holds until the person next presses a key or clicks. True if both were done."""
    if not config.WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class MouseInput(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("mi", MouseInput)]

        user32 = ctypes.WinDLL("user32")
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        nothing = Input(type=0)           # a mouse event: no movement, no button
        sent = user32.SendInput(1, ctypes.byref(nothing), ctypes.sizeof(Input)) == 1
        return bool(user32.AllowSetForegroundWindow(0xFFFFFFFF)) and sent   # any program
    except Exception:
        return False


def _start(command: list) -> None:
    home = os.path.expanduser("~")
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 cwd=home if os.path.isdir(home) else None)
    if config.WINDOWS:
        # A window of its own for a program that writes to one, as a double click gives.
        flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(command, creationflags=flags, close_fds=True, **quiet)
    else:
        subprocess.Popen(_away(command), start_new_session=True, close_fds=True, **quiet)


class Doer:
    """Does the steps that reach outside this program. A stand-in takes its place in
    tests."""

    def __init__(self):
        self._asking = None

    def press(self, chord: str) -> str:
        """Press keys held together, in whatever program has the keyboard. Returns that
        program's name where it can be told (Windows), for the log: "" where it can't."""
        if config.WINDOWS:
            from . import keys_target
            try:
                return keys_target.press_keys(chord)
            except OSError:
                raise ActionError(
                    "Windows wouldn't take the key presses. It takes none for a program "
                    "that is run as administrator.") from None
        from . import portal_keys
        keys = portal_keys.shared()
        if not keys.ready():
            # The desktop asks the person, the first time. Waited for, for a while.
            if self._asking is None or not self._asking.is_alive():
                self._asking = threading.Thread(target=_quietly, args=(keys.allow,), daemon=True)
                self._asking.start()
            self._asking.join(ASK_WAIT)
            if not keys.ready():
                raise ActionError(
                    "The desktop has to let this program press keys. If it is asking on the "
                    "screen, answer it, and say the command again.")
        try:
            keys.press(chord)
        except portal_keys.NotAllowed as e:
            raise ActionError(f"The keys couldn't be pressed: {e}") from None
        return ""

    def open(self, what: str) -> None:
        """Open a file, a folder or a web page with the program that usually opens it."""
        target = what if "://" in what or what.lower().startswith("mailto:") \
            else os.path.expanduser(os.path.expandvars(what))
        if "://" not in target and not target.lower().startswith("mailto:") \
                and not os.path.exists(target):
            raise ActionError(f"There is nothing to open at {_short(target)}.")
        try:
            if config.WINDOWS:
                let_come_forward()
                os.startfile(target)  # noqa: S606  (the person's own line, from Settings)
            else:
                opener = shutil.which("xdg-open")
                if not opener:
                    raise ActionError("The desktop's \"xdg-open\" isn't installed, so "
                                      "nothing can be opened.")
                _start([opener, target])
        except OSError as e:
            raise ActionError(f"{_short(target)} couldn't be opened: {e.strerror or e}.") from None

    def run(self, line: str) -> None:
        """Start a program and leave it running. It is not waited for."""
        try:
            command = _arguments(line)
        except ValueError as e:
            raise ActionError(f"The line to run can't be read: {e}.") from None
        if not command:
            raise ActionError("No program is named to run.")
        found = shutil.which(command[0])
        if not found:
            raise ActionError(f"There is no program called {_short(command[0])}.")
        try:
            let_come_forward()
            _start([found] + command[1:])
        except OSError as e:
            raise ActionError(f"{_short(command[0])} couldn't be started: {e.strerror or e}.") from None

    def wait(self, seconds: float) -> None:
        time.sleep(seconds)

    def in_front(self) -> str:
        """The name of the program in front, where it can be told (Windows): for the log,
        to show whether what was opened came forward."""
        if not config.WINDOWS:
            return ""
        try:
            from . import keys_target
            return keys_target.program_in_front()
        except Exception:
            return ""


def _quietly(call) -> None:
    try:
        call()
    except Exception:
        pass
