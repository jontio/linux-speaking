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
