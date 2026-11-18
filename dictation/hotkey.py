"""Windows: a key that works whichever program is in front, and switches dictation
between off and awake.

Windows hands the key to this program and to nothing else while it is taken: with the
number pad's + chosen, that key no longer types a plus anywhere. So no key is taken until
one is chosen, in the welcome window or in Settings, and the choice is of keys that few
programs use.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

MOD_ALT, MOD_CONTROL = 0x0001, 0x0002
MOD_NOREPEAT = 0x4000  # holding the key down counts once
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# The keys that can be chosen, by the name Settings shows and keeps: what goes with the
# key (Ctrl, Alt), and Windows' number for the key itself. Both are what RegisterHotKey
# asks for. No key at all is kept as "".
KEYS = {
    "Number pad +": (0, 0x6B),
    "Pause": (0, 0x13),
    "Scroll Lock": (0, 0x91),
    "F9": (0, 0x78),
    "Ctrl+Alt+D": (MOD_CONTROL | MOD_ALT, 0x44),
    "Ctrl+Alt+Space": (MOD_CONTROL | MOD_ALT, 0x20),
}
NUMPAD_PLUS = "Number pad +"  # the key it always was, before there was a choice

# What taking a key costs, where it costs something: said beside the chooser.
COSTS = {
    "Number pad +": "While it is chosen, the + of the number pad no longer types a plus.",
    "Pause": "While it is chosen, the Pause key does nothing else.",
    "Scroll Lock": "While it is chosen, the Scroll Lock key no longer switches scroll lock.",
    "F9": "While it is chosen, F9 does nothing else in any program: Word and Outlook use "
          "it to update fields and to send and receive.",
}


def chosen(name) -> str:
    """The name of a key that can be taken, or "" for none: anything else that was kept,
    by an older version or by hand, counts as none."""
    return name if name in KEYS else ""


class _Windows:
    """The few calls to Windows that taking a key needs. Made and used on the thread that
    waits for the key, apart from wake(), which ends that wait from another."""

    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self.user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.thread_id = 0

    def take(self, modifiers: int, key: int) -> bool:
        # Key presses arrive as messages to the thread that asked, so it asks and waits here.
        self.thread_id = self.kernel32.GetCurrentThreadId()
        return bool(self.user32.RegisterHotKey(None, 1, modifiers, key))

    def wait(self) -> bool:
        """Wait for the key. True each time it is pressed; False when told to stop."""
        message = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == WM_HOTKEY:
                return True
        return False

    def give_back(self) -> None:
        self.user32.UnregisterHotKey(None, 1)

    def wake(self) -> None:
        self.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


class Hotkey:
    """Calls `pressed` each time the chosen key is pressed, on a thread of its own.
    `windows` stands in for Windows in the tests."""

    def __init__(self, pressed, windows=_Windows):
        self._pressed = pressed
        self._windows = windows
        self._thread = None
        self._at = None       # the calls to Windows of the thread that is waiting
        self._taken = False
        self.name = ""        # the key it holds, "" while it holds none

    def start(self, name: str = NUMPAD_PLUS) -> bool:
        """Take the key called `name`, giving back any other it held. False if there is
        no such key, or Windows refused it, as when another program has it."""
        if self._thread is not None and self.name == name:
            return True
        self.stop()
        if name not in KEYS:
            return False
        modifiers, key = KEYS[name]
        ready = threading.Event()
        thread = threading.Thread(target=self._run, args=(ready, modifiers, key), daemon=True)
        thread.start()
        ready.wait(3)
        if self._taken:
            self._thread, self.name = thread, name
        return self._taken

    def stop(self) -> None:
        """Give the key back."""
        thread, self._thread, self.name = self._thread, None, ""
        if thread is None:
            return
        if self._at is not None:
            self._at.wake()
        thread.join(2)

    def _run(self, ready: threading.Event, modifiers: int, key: int) -> None:
        at = None
        try:
            at = self._at = self._windows()
            self._taken = at.take(modifiers | MOD_NOREPEAT, key)
        except Exception:
            self._taken = False
        ready.set()
        if not self._taken:
            return
        try:
            while at.wait():
                try:
                    self._pressed()
                except Exception:
                    pass
        finally:
            at.give_back()
            self._taken = False
