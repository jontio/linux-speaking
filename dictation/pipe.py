"""Windows: talking to an extension over a named pipe, the stand-in for a socket file."""
from __future__ import annotations

import json
import os
import time

import pywintypes
import win32event
import win32file
import win32pipe
import winerror

FOLDER = "\\\\.\\pipe\\"


def names(prefix: str) -> list:
    """The full paths of the pipes whose names start with `prefix`."""
    try:
        found = os.listdir(FOLDER)
    except OSError:
        return []
    return sorted(FOLDER + name for name in found if name.startswith(prefix))


def _wait(handle, overlapped, deadline: float) -> int:
    """Wait for a read or write to finish. Returns the number of bytes moved."""
    left = max(0, int((deadline - time.monotonic()) * 1000))
    if win32event.WaitForSingleObject(overlapped.hEvent, left) != win32event.WAIT_OBJECT_0:
        win32file.CancelIo(handle)
        raise TimeoutError("timed out")
    return win32file.GetOverlappedResult(handle, overlapped, False)


def send(path: str, message: dict, timeout: float = 6.0) -> dict:
    """Send one request to the pipe at `path` and return the reply. Raises OSError on failure."""
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                handle = win32file.CreateFile(
                    path, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                    win32file.OPEN_EXISTING, win32file.FILE_FLAG_OVERLAPPED, None)
                break
            except pywintypes.error as e:
                if e.winerror != winerror.ERROR_PIPE_BUSY or time.monotonic() > deadline:
                    raise
                win32pipe.WaitNamedPipe(path, 200)
        try:
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
