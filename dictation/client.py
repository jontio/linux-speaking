"""Talking to the Writer extension over a local socket."""
from __future__ import annotations

import json
import os
import socket


def socket_path() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.environ.get("LINUX_SPEAKING_SOCKET") or os.path.join(base, "linux-speaking.sock")


def request(message: dict, timeout: float = 6.0) -> dict:
    """Send one request and return the reply. Never raises."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(socket_path())
            s.sendall((json.dumps(message) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode("utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "why": "writer not running", "error": str(e)}
