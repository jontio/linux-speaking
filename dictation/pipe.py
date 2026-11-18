"""Windows: talking to an extension over a named pipe, the stand-in for a socket file.

A socket file on Linux sits in a folder only its owner can open. Pipes are not like that:
their names are for every account on the computer to see, and anyone may make one with
any name. So before anything is sent down a pipe, it is checked to be this same person's:
what is dictated is not for another account's program that has only taken the right name.

Three things are asked, of the pipe that has been opened and not of its name, so nothing
can be changed between the asking and the sending:

- Who owns the pipe itself. Windows writes down, on everything a program makes, the
  account it was made by, and another account can't write this one's name there. This is
  the check that can't be got round.
- How far Windows trusts what made it. A program that is kept apart from the person's own
  (a web page's, in a browser) runs as the person all the same: but what it makes is
  labelled as made by such a one, and a pipe so labelled is not this person's to dictate
  into.
- Who the process at the other end runs as. By itself this could be got round: what
  Windows gives is the number of the process that made the pipe, which can have ended
  since, and its number have passed to somebody else's program, or to one of the
  person's own. It is kept as a second look.

A pipe that turns out to be another account's is not asked again for as long as it is
there. Nor is time spent waiting on a pipe that is busy before it has ever been found to
be this person's: another account could make any number of those, to slow every phrase.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import pywintypes
import win32event
import win32file
import win32pipe
import winerror

FOLDER = "\\\\.\\pipe\\"
# Asked for when a pipe is opened: its other end may learn who is calling, and no more.
SQOS_PRESENT, IDENTIFICATION = 0x00100000, 0x00010000
QUERY_LIMITED = 0x1000  # leave to ask a process only who it runs as
# What is asked of a pipe about itself: who owns it, and its label of trust.
OWNER, LABEL = 0x00000001, 0x00000010
KERNEL_OBJECT, FILE_OBJECT = 6, 1  # the two kinds of thing a pipe can be asked about as
MEDIUM = 0x2000         # the trust an ordinary program of the person's has: less is kept apart
BUSY_REST = 30.0        # seconds a pipe that was busy, and never yet found ours, is left alone

_ours: set = set()      # the pipes that have been found to be this person's
_left: dict = {}        # pipes not to be asked: path -> until when (for ever, if another account's)
_lock = threading.Lock()
_said: set = set()      # why a pipe couldn't be asked about itself: each said in the log once


def _say_once(what: str) -> None:
    """Put something in the log the first time it happens, not for every phrase."""
    if what not in _said and len(_said) < 20:
        _said.add(what)
        print(what, flush=True)


def _person(process) -> str:
    """The account a process runs as, as Windows writes it down."""
    import win32con
    import win32security
    token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
    try:
        return win32security.ConvertSidToStringSid(
            win32security.GetTokenInformation(token, win32security.TokenUser)[0])
    finally:
        token.Close()


def _mine() -> set:
    """The accounts whose pipes are this person's, as Windows writes them down: the one
    this program runs as, and the one written on whatever this program makes. They are
    the same, except for a program run as administrator, whose things are written down
    as the administrators' group's."""
    import win32api
    import win32con
    import win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        owner = win32security.GetTokenInformation(token, win32security.TokenOwner)
        return {win32security.ConvertSidToStringSid(user), win32security.ConvertSidToStringSid(owner)}
    finally:
        token.Close()


def _server_of(handle) -> int:
    """The process at the other end of a pipe that has been opened."""
    if hasattr(win32pipe, "GetNamedPipeServerProcessId"):
        return win32pipe.GetNamedPipeServerProcessId(handle)
    import ctypes
    from ctypes import wintypes
    found = wintypes.ULONG()
    ask = ctypes.WinDLL("kernel32", use_last_error=True).GetNamedPipeServerProcessId
    ask.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    ask.restype = wintypes.BOOL
    if not ask(int(handle), ctypes.byref(found)):
        raise OSError("the pipe won't say whose it is")
    return found.value


def _made_by(handle) -> tuple:
    """(the account that owns the pipe an opened handle is of, as Windows writes an
    account down; the pipe's label of trust, in Windows' own writing of such things, or
    "" if it has none). Raises OSError if the pipe won't say.

    Asked of Windows directly: GetSecurityInfo gives the owner as a pointer into a block
    that it makes, and each of the two conversions makes a text. All three are handed
    back with LocalFree, whatever happens in between."""
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    free = kernel.LocalFree
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    ask = advapi.GetSecurityInfo
    ask.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD] + [ctypes.POINTER(ctypes.c_void_p)] * 5
    ask.restype = wintypes.DWORD          # 0, or why not
    valid = advapi.IsValidSid
    valid.argtypes, valid.restype = [ctypes.c_void_p], wintypes.BOOL
    written = advapi.ConvertSidToStringSidW
    written.argtypes, written.restype = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)], wintypes.BOOL
    described = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    described.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                          ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
    described.restype = wintypes.BOOL

    def text_of(made) -> str:
        """The text Windows made at `made`, which is then handed back."""
        try:
            return ctypes.wstring_at(made.value)
        finally:
            free(made)

    # The owner and the label are asked for together. Should Windows not give the label
    # (it always should), the owner is asked for by itself: the owner is the check that
    # matters, and without it nothing is sent. A pipe answers as a "kernel object"; as a
    # "file" is tried in case.
    for wanted, kind in ((OWNER | LABEL, KERNEL_OBJECT), (OWNER | LABEL, FILE_OBJECT),
                         (OWNER, KERNEL_OBJECT), (OWNER, FILE_OBJECT)):
        owner, block = ctypes.c_void_p(), ctypes.c_void_p()
        why = ask(int(handle), kind, wanted, ctypes.byref(owner), None, None, None,
                  ctypes.byref(block))
        if why == 0 and block.value:
            break
        if block.value:
            free(block)
    else:
        raise OSError(f"the pipe won't say whose it is (Windows error {why})")
    try:
        if not owner.value or not valid(owner):
            raise OSError("the pipe has no owner written on it")
        made = ctypes.c_void_p()
        if not written(owner, ctypes.byref(made)) or not made.value:
            raise OSError(f"the pipe's owner can't be read (Windows error {ctypes.get_last_error()})")
        whose = text_of(made)
        if not wanted & LABEL:
            _say_once("a pipe would say who owns it, and not how far Windows trusts what made it")
            return whose, ""
        made = ctypes.c_void_p()
        if not described(block, 1, LABEL, ctypes.byref(made), None) or not made.value:
            # As when Windows won't hand the label over at all: who owns the pipe is
            # known, and decides. (Refusing here would stop dictation into VS Code
            # altogether, over the lesser of the two things asked.)
            _say_once("a pipe's label could not be put into words (Windows error "
                      f"{ctypes.get_last_error()}): going by its owner alone")
            return whose, ""
        return whose, text_of(made)
    finally:
        free(block)


def _kept_apart(label: str) -> bool:
    """Whether a pipe's label says it was made by a program that Windows trusts less than
    an ordinary one of the person's. The label is written like "S:(ML;;NW;;;LW)": LW is
    low trust, and a level without a short name of its own is written out as S-1-16 and
    a number. No label at all is the ordinary trust."""
    for level in re.findall(r"\(ML;[^;()]*;[^;()]*;[^;()]*;[^;()]*;([^;()]*)\)", label):
        if level == "LW":
            return True
        if level.startswith("S-1-16-"):
            if not level[7:].isdigit() or int(level[7:]) < MEDIUM:
                return True
    return False


def _whose(handle):
    """True if an opened pipe is this same person's, False if it is not, and None if it
    could not be asked: see the top of the file for what is asked."""
    import win32api
    try:
        whose, label = _made_by(handle)
        if whose not in _mine() or _kept_apart(label):
            return False
        process = win32api.OpenProcess(QUERY_LIMITED, False, _server_of(handle))
        try:
            return _person(process) == _person(win32api.GetCurrentProcess())
        finally:
            process.Close()
    except Exception as e:
        _say_once("a pipe could not be asked whose it is, so nothing is sent to it: "
                  f"{type(e).__name__}: {e}")
        return None


def ours(handle) -> bool:
    """Whether an opened pipe is this same person's. One that can't be asked, for
    whatever reason, is not taken on trust."""
    return _whose(handle) is True


def names(prefix: str) -> list:
    """The full paths of the pipes whose names start with `prefix`: but for those found
    to be another account's, and those that were busy before they were ever found to be
    this person's, which are left alone for a while."""
    try:
        found = {FOLDER + name for name in os.listdir(FOLDER) if name.startswith(prefix)}
    except OSError:
        return []
    now = time.monotonic()
    with _lock:
        for path in [path for path in _ours if path.startswith(FOLDER + prefix) and path not in found]:
            _ours.discard(path)           # it has gone: the next of that name is looked at afresh
        for path in [path for path, until in _left.items()
                     if until <= now or (path.startswith(FOLDER + prefix) and path not in found)]:
            del _left[path]
        return sorted(found - set(_left))


def _wait(handle, overlapped, deadline: float) -> int:
    """Wait for a read or write to finish. Returns the number of bytes moved."""
    left = max(0, int((deadline - time.monotonic()) * 1000))
    if win32event.WaitForSingleObject(overlapped.hEvent, left) != win32event.WAIT_OBJECT_0:
        win32file.CancelIo(handle)
        raise TimeoutError("timed out")
    return win32file.GetOverlappedResult(handle, overlapped, False)


def _leave(path: str, seconds: float) -> None:
    with _lock:
        _ours.discard(path)
        _left[path] = time.monotonic() + seconds


def send(path: str, message: dict, timeout: float = 6.0) -> dict:
    """Send one request to the pipe at `path` and return the reply. Raises OSError on failure."""
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                handle = win32file.CreateFile(
                    path, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                    win32file.OPEN_EXISTING,
                    win32file.FILE_FLAG_OVERLAPPED | SQOS_PRESENT | IDENTIFICATION, None)
                break
            except pywintypes.error as e:
                if e.winerror != winerror.ERROR_PIPE_BUSY:
                    raise
                with _lock:
                    known = path in _ours
                if not known:
                    # Busy, and never yet found to be this person's: no time is spent
                    # waiting on it, and it is left alone for a while.
                    _leave(path, BUSY_REST)
                    raise
                left = int((deadline - time.monotonic()) * 1000)
                if left <= 0:
                    raise
                try:
                    win32pipe.WaitNamedPipe(path, max(1, min(200, left)))
                except pywintypes.error as waited:
                    if waited.winerror != winerror.ERROR_SEM_TIMEOUT:
                        raise             # it has gone, or can't be waited on
                    # Still busy: it is tried again until the time is up, not given up
                    # on at the first wait.
        try:
            whose = _whose(handle)
            if whose is not True:
                # Another account's: left alone for as long as it is there. One that
                # couldn't be asked is left for a while, and asked again.
                _leave(path, float("inf") if whose is False else BUSY_REST)
                raise PermissionError(f"{path} is another account's, or won't say whose it is: "
                                      "nothing is sent to it")
            with _lock:
                _ours.add(path)
            overlapped = pywintypes.OVERLAPPED()
            overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
            win32file.WriteFile(handle, (json.dumps(message) + "\n").encode("utf-8"), overlapped)
            _wait(handle, overlapped, deadline)
            data = b""
            buffer = win32file.AllocateReadBuffer(65536)
            while not data.endswith(b"\n"):
                win32event.ResetEvent(overlapped.hEvent)
                try:
                    win32file.ReadFile(handle, buffer, overlapped)
                    count = _wait(handle, overlapped, deadline)
                except pywintypes.error as e:
                    if e.winerror == winerror.ERROR_BROKEN_PIPE:
                        break  # the other end has said all it will
                    raise
                if not count:
                    break
                data += bytes(buffer[:count])
        finally:
            handle.Close()
    except pywintypes.error as e:
        if e.winerror == winerror.ERROR_FILE_NOT_FOUND:
            raise FileNotFoundError(path) from e
        raise OSError(f"{e.funcname}: {e.strerror}") from e
    return json.loads(data.decode("utf-8"))
