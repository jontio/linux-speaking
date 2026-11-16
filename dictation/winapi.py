"""Windows: which window has the keyboard, and reaching a program through that window."""
from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
oleacc = ctypes.OleDLL("oleacc")

OBJID_NATIVEOM = -16  # "give me this window's own automation object"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
IID_IDISPATCH = uuid.UUID("{00020400-0000-0000-C000-000000000046}").bytes_le


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
oleacc.AccessibleObjectFromWindow.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]


def focused() -> tuple:
    """(program, window class, window handle) of the control that has the keyboard.

    The program is its file name in lower case, such as "winword.exe". Empty strings and
    None when that can't be told.
    """
    window = user32.GetForegroundWindow()
    if not window:
        return "", "", None
    process = wintypes.DWORD()
    thread = user32.GetWindowThreadProcessId(window, ctypes.byref(process))
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)) or not info.hwndFocus:
        return "", "", None
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(info.hwndFocus, name, 256)
    program = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, process.value)
    if handle:
        path = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            program = os.path.basename(path.value).lower()
        kernel32.CloseHandle(handle)
    return program, name.value, info.hwndFocus


# ---- Windows' own edit boxes, asked and told by message -----------------------------
# These are messages Windows itself carries the text across for, so the box can belong
# to another program. Nothing here presses a key or uses the accessibility interface.
WM_GETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000E
EM_GETSEL, EM_SETSEL, EM_SCROLLCARET, EM_REPLACESEL, EM_GETPASSWORDCHAR = 0x00B0, 0x00B1, 0x00B7, 0x00C2, 0x00D2
GWL_STYLE, ES_PASSWORD, ES_READONLY, SMTO_ABORTIFHUNG = -16, 0x0020, 0x0800, 0x0002

user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t, wintypes.UINT,
    wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_size_t
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG


def _ask(window, message: int, first: int = 0, second: int = 0, timeout_ms: int = 1500):
    """A window's answer to a message, or None if it gave none in time."""
    result = ctypes.c_size_t()
    if not user32.SendMessageTimeoutW(window, message, first, second, SMTO_ABORTIFHUNG,
                                      timeout_ms, ctypes.byref(result)):
        return None
    return result.value


def window_process(window) -> int:
    """The number of the process a window belongs to, or 0."""
    process = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window, ctypes.byref(process))
    return process.value


SCI_GETREADONLY = 2140


def edit_refuses(window, scintilla: bool = False) -> str:
    """Why an edit box is not to be typed into: "password", "read only", or "" if it may
    be. `scintilla` is for the editing area of Notepad++ and its like, which has its own
    way of saying it is read only."""
    if scintilla:
        return "read only" if _ask(window, SCI_GETREADONLY) else ""
    style = user32.GetWindowLongW(window, GWL_STYLE)
    if style & ES_PASSWORD or _ask(window, EM_GETPASSWORDCHAR):
        return "password"
    return "read only" if style & ES_READONLY else ""


def edit_text(window, most: int):
    """(all the text of an edit box, where its selection starts, where it ends), or None
    if it holds more than `most` characters or doesn't answer.

    The places count characters as the box itself counts them, which is how the text is
    given back: a rich edit box counts a line break as one character, a plain one as two.
    """
    length = _ask(window, WM_GETTEXTLENGTH)
    if length is None or length > most:
        return None
    buffer = ctypes.create_unicode_buffer(length + 2)
    if _ask(window, WM_GETTEXT, length + 1, ctypes.addressof(buffer)) is None:
        return None
    first, last = wintypes.DWORD(), wintypes.DWORD()
    if _ask(window, EM_GETSEL, ctypes.addressof(first), ctypes.addressof(last)) is None:
        return None
    return buffer.value, first.value, last.value


def select_in_edit(window, first: int, last: int) -> bool:
    """Select from `first` to `last` in an edit box, and bring that into view."""
    if _ask(window, EM_SETSEL, first, last) is None:
        return False
    _ask(window, EM_SCROLLCARET)
    return True


def replace_selection(window, text: str, timeout_ms: int = 2000) -> bool:
    """Put `text` in place of what is selected in an edit box, or at its cursor if nothing
    is: the whole of it at once, as one step that Undo takes back. No keys are pressed.
    False if the window didn't take it in time.
    """
    buffer = ctypes.create_unicode_buffer(text)
    if _ask(window, EM_REPLACESEL, 1, ctypes.addressof(buffer), timeout_ms) is None:
        return False
    _ask(window, EM_SCROLLCARET, 0, 0, timeout_ms)
    return True


WM_KEYDOWN, WM_KEYUP, VK_SHIFT = 0x0100, 0x0101, 0x10


def tap_shift(window) -> None:
    """Tell a window that Shift was pressed and let go, as two messages put in its queue.
    Nothing is typed and no key is held: the keyboard itself isn't touched.

    For after replace_selection(). Windows 11's Notepad takes its text cursor off the
    screen a few seconds after text arrives with no key pressed, and puts it back at the
    next key. A key that does nothing is enough.
    """
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW(window, WM_KEYDOWN, VK_SHIFT, 0x002A0001)
    user32.PostMessageW(window, WM_KEYUP, VK_SHIFT, 0xC02A0001 - (1 << 32))


def child_of_class(top, kind: str):
    """The first window inside `top` whose class is `kind`, or None. For tests."""
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(window, _):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(window, name, 256)
        if name.value == kind:
            found.append(window)
            return False
        return True

    user32.EnumChildWindows(top, callback_type(visit), 0)
    return found[0] if found else None


def native_object(window):
    """The automation object behind a window, such as Word's Window for its editing area.

    Raises OSError if the window offers none.
    """
    import pythoncom
    import win32com.client.dynamic
    pointer = ctypes.c_void_p()
    oleacc.AccessibleObjectFromWindow(
        window, OBJID_NATIVEOM & 0xFFFFFFFF, IID_IDISPATCH, ctypes.byref(pointer))
    if not pointer.value:
        raise OSError("the window has no automation object")
    try:
        return win32com.client.dynamic.Dispatch(
            pythoncom.ObjectFromAddress(pointer.value, pythoncom.IID_IDispatch))
    finally:
        # ObjectFromAddress took its own reference; give back the one handed to us.
        _release(pointer.value)


def running(name: str):
    """A program that is already running, such as "Outlook.Application". Raises
    pythoncom.com_error if it isn't.

    Always spoken to the plain way, whatever speed-ups pywin32 has cached on this
    computer, so that it behaves the same everywhere.
    """
    import pythoncom
    import win32com.client.dynamic
    return win32com.client.dynamic.Dispatch(
        pythoncom.GetActiveObject(name).QueryInterface(pythoncom.IID_IDispatch))


def _release(address: int) -> None:
    """Call IUnknown::Release on a raw interface pointer."""
    vtable = ctypes.cast(address, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    release(address)
