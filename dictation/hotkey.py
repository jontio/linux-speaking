"""Windows: a key that works whichever program is in front.

Windows hands the key to this program and to nothing else while it is taken, so the
number pad's + no longer types a plus. That is why it can be switched off in Settings.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

NUMPAD_PLUS = 0x6B
MOD_NOREPEAT = 0x4000  # holding the key down counts once
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class Hotkey:
    """Calls `pressed` each time the key is pressed, on a thread of its own."""

    def __init__(self, pressed, key: int = NUMPAD_PLUS):
        self._pressed = pressed
        self._key = key
        self._thread = None
        self._thread_id = 0
        self._taken = False

    def start(self) -> bool:
        """Take the key. False if Windows refused, as when another program has it."""
        if self._thread is not None:
            return True
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(3)
        if not self._taken:
            self._thread = None
        return self._taken

    def stop(self) -> None:
        """Give the key back."""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(2)

    def _run(self, ready: threading.Event) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._thread_id = kernel32.GetCurrentThreadId()
        # Key presses arrive as messages to the thread that asked, so it asks and waits here.
        self._taken = bool(user32.RegisterHotKey(None, 1, MOD_NOREPEAT, self._key))
        ready.set()
        if not self._taken:
            return
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == WM_HOTKEY:
                    try:
                        self._pressed()
                    except Exception:
                        pass
        finally:
            user32.UnregisterHotKey(None, 1)
            self._taken = False
