"""Choosing where dictation goes: Thunderbird, Kate, VS Code, Word, Outlook or Writer.

Whichever has its window in front gets the words. All answer the same requests.
"""
from __future__ import annotations

import time

from . import client

REPICK_SECONDS = 0.7


class Targets:
    def __init__(self, mail=None, editor=None, vscode=None, office=None, other=None):
        self.mail = mail
        self.editor = editor  # Kate and KWrite
        self.vscode = vscode
        self.office = office  # Microsoft Word and Outlook, on Windows
        self.other = other    # on Windows, any other text box, typed into; asked last
        self.name = ""  # the program in front, such as "Writer", or "" when none is
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
        if self.vscode is not None and self.vscode.request({"op": "status"}).get("ready"):
            self._send, self.name = self.vscode.request, self.vscode.name
            return
        if self.office is not None and self.office.request({"op": "status"}).get("ready"):
            self._send, self.name = self.office.request, self.office.name
            return
        if self.other is not None and self.other.request({"op": "status"}).get("ready"):
            self._send, self.name = self.other.request, self.other.name
            return
        self._send = client.request
        self.name = "Writer" if client.request({"op": "status"}).get("ready") else ""

    def describe(self) -> str:
        """Each target's own answer to "are you in front?", for the log."""
        answers = {"writer": client.request({"op": "status"})}
        if self.editor is not None:
            answers["editor"] = self.editor.request({"op": "status"})
        if self.vscode is not None:
            answers["vscode"] = self.vscode.request({"op": "status"})
        if self.office is not None:
            answers["office"] = self.office.request({"op": "status"})
        if self.other is not None:
            answers["other"] = self.other.request({"op": "status"})
        if self.mail is not None:
            answers["mail"] = (self.mail.request({"op": "status"}, timeout=1.5)
                               if self.mail.connected() else "not connected")
        return ", ".join(f"{name}: {answer}" for name, answer in answers.items())

    def request(self, message: dict) -> dict:
        if time.monotonic() - self._picked > REPICK_SECONDS:
            self.pick()
        return self._send(message)

    def broadcast(self, message: dict) -> None:
        """Send to all, in front or not. Used to clear things that must not linger."""
        client.request(message)
        if self.mail is not None and self.mail.connected():
            self.mail.request(message, timeout=1.5)
        if self.vscode is not None:
            self.vscode.broadcast(message)
        if self.office is not None:
            self.office.broadcast(message)
