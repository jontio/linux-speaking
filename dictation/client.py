"""Talking to an extension over a local socket: one JSON line out, one back."""
from __future__ import annotations

import json
import os
import socket


def runtime_dir() -> str:
    """The user's private runtime folder, where the sockets live."""
    if os.name == "nt":
        return "\\\\.\\pipe\\"
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def socket_path() -> str:
    """The LibreOffice Writer extension's socket."""
    return os.environ.get("LINUX_SPEAKING_SOCKET") or os.path.join(
        runtime_dir(), "linux-speaking.sock")


def send(path: str, message: dict, timeout: float = 6.0) -> dict:
    """Send one request to the socket at `path` and return the reply. Raises on failure."""
    if os.name == "nt":  # a named pipe there
        from . import pipe
        return pipe.send(path, message, timeout)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((json.dumps(message) + "\n").encode("utf-8"))
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


def request(message: dict, timeout: float = 6.0) -> dict:
    """Send one request to Writer and return the reply. Never raises."""
    if os.name == "nt":  # the Writer extension isn't on Windows yet
        return {"ok": False, "why": "writer not running"}
    try:
        return send(socket_path(), message, timeout)
    except (OSError, ValueError) as e:
        return {"ok": False, "why": "writer not running", "error": str(e)}
