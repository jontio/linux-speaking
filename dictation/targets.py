"""Choosing where dictation goes: a Thunderbird message, Kate, or Writer.

Whichever has its window in front gets the words. All answer the same requests.
"""
from __future__ import annotations

import time

from . import client

REPICK_SECONDS = 0.7


class Targets:
    def __init__(self, mail=None, editor=None):
        self.mail = mail
        self.editor = editor  # Kate and KWrite
        self.name = ""  # "Writer", "Thunderbird", or "" when neither is in front
        self._send = client.request
        self._picked = 0.0

    def pick(self) -> None:
        self._picked = time.monotonic()
        if self.mail is not None and self.mail.connected():
            if self.mail.request({"op": "status"}, timeout=1.5).get("ready"):
                self._send, self.name = self.mail.request, "Thunderbird"
                return
        if self.editor is not None and self.editor.request({"op": "status"}).get("ready"):
            self._send, self.name = self.editor.request, self.editor.name
            return
        self._send = client.request
        self.name = "Writer" if client.request({"op": "status"}).get("ready") else ""

    def request(self, message: dict) -> dict:
        if time.monotonic() - self._picked > REPICK_SECONDS:
            self.pick()
        return self._send(message)

    def broadcast(self, message: dict) -> None:
        """Send to both, in front or not. Used to clear things that must not linger."""
        client.request(message)
        if self.mail is not None and self.mail.connected():
            self.mail.request(message, timeout=1.5)
