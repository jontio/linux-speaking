"""Dictating into Visual Studio Code, through its Linux Speaking extension.

Each VS Code window runs its own copy of the extension, listening on its own socket in
the user's runtime folder. The engine asks each which one is in front.
"""
from __future__ import annotations

import glob
import os

from . import client

PATTERN = "linux-speaking-vscode-*.sock"
PIPE_PREFIX = "linux-speaking-vscode-"  # Windows: named pipes instead of socket files
NOT_FOCUSED = {"ok": False, "why": "editor not focused"}


class VSCodeTarget:
    name = "VS Code"

    def __init__(self, folder: str | None = None):
        self.folder = folder or client.runtime_dir()
        self._path = None  # the socket of the window in front

    def _sockets(self) -> list:
        if os.name == "nt":
            from . import pipe
            return pipe.names(PIPE_PREFIX)
        return sorted(glob.glob(os.path.join(self.folder, PATTERN)))

    def _ask(self, path: str, message: dict, timeout: float) -> dict | None:
        """One request to one window. None if that window has gone."""
        try:
            return client.send(path, message, timeout)
        except (ConnectionRefusedError, FileNotFoundError):
            try:
                os.unlink(path)  # left behind by a window that was closed or crashed
            except OSError:
                pass
            return None
        except (OSError, ValueError) as e:
            return {"ok": False, "why": "editor not answering", "error": str(e)}

    def request(self, message: dict) -> dict:
        """Answer one request, in the same form as the Writer extension. Never raises."""
        if message.get("op") == "status":
            self._path = None
            for path in self._sockets():
                reply = self._ask(path, message, 1.5)
                if reply and reply.get("ready"):
                    self._path = path
                    return reply
            return {"ok": True, "ready": False}
        if self._path is None:
            return dict(NOT_FOCUSED)
        reply = self._ask(self._path, message, 6.0)
        if reply is None:
            self._path = None
            return dict(NOT_FOCUSED)
        return reply

    def broadcast(self, message: dict) -> None:
        """Send to every window, in front or not."""
        for path in self._sockets():
            self._ask(path, message, 1.5)
