"""Linux: pressing keys in whatever program has the keyboard, with the desktop's leave.

A Wayland desktop lets no program press keys in another unless the person at the computer
has said it may. The way to ask is the desktop's "remote desktop" portal, the one remote
control programs use. The first time, the desktop shows a window asking whether Linux
Speaking may control the keyboard. Once that is allowed, the desktop hands back a token,
and with it the leave is kept for next time without asking again.

Only the keyboard is asked for. Nothing is seen of the screen.

Used for text boxes that can be read but not written through the accessibility interface:
those of a web browser, and of programs built from one, such as VS Code's panels.
"""
from __future__ import annotations

import os
import random
import threading
import time

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REMOTE = "org.freedesktop.portal.RemoteDesktop"
REQUEST = "org.freedesktop.portal.Request"
KEYBOARD = 1
UNTIL_REVOKED = 2
ANSWER_SECONDS = 120.0   # how long the person has to answer the desktop's question

# Keys by name, as X and Wayland number them (keysyms).
KEYSYMS = {"enter": 0xFF0D, "backspace": 0xFF08, "delete": 0xFFFF, "tab": 0xFF09,
           "home": 0xFF50, "end": 0xFF57, "left": 0xFF51, "up": 0xFF52, "right": 0xFF53,
           "down": 0xFF54, "shift": 0xFFE1, "ctrl": 0xFFE3, "alt": 0xFFE9, "escape": 0xFF1B,
           # ... and the rest, for commands of the person's own that press keys.
           "win": 0xFFEB, "space": 0x20, "pageup": 0xFF55, "pagedown": 0xFF56, "insert": 0xFF63,
           "plus": 0x2B, "minus": 0x2D, "comma": 0x2C, "period": 0x2E, "slash": 0x2F,
           **{f"f{n}": 0xFFBD + n for n in range(1, 13)}}


class NotAllowed(Exception):
    """Keys can't be pressed. The message is for the person to read."""


def keysym(character: str) -> int:
    """The key for a character: Latin-1 characters are their own number, and any other
    character is its Unicode number with a mark that says so."""
    code = ord(character)
    if character == "\n":
        return KEYSYMS["enter"]
    if character == "\t":
        return KEYSYMS["tab"]
    return code if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF else 0x01000000 + code


# Characters the keyboard hasn't got are not typed at all by the desktop, so they are
# put as the nearest thing it has.
_PLAIN = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
          "\u2026": "...", "\u00a0": " ", "\u2022": "*", "\u00d7": "x", "\u2212": "-",
          "\u00df": "ss", "\u00e6": "ae", "\u00c6": "AE", "\u00f8": "o", "\u00d8": "O"}


def typable(text: str) -> str:
    """`text` as it can be typed on a plain keyboard: accents taken off letters, curly
    quotes and long dashes made plain, and anything else the keyboard hasn't got left
    out. Line breaks and tabs are kept."""
    import unicodedata
    out = []
    for character in text:
        if character in "\n\t" or 0x20 <= ord(character) <= 0x7E:
            out.append(character)
        elif character in _PLAIN:
            out.append(_PLAIN[character])
        else:
            bare = "".join(c for c in unicodedata.normalize("NFKD", character)
                           if 0x20 <= ord(c) <= 0x7E)
            out.append(bare)
    return "".join(out)


class Keys:
    """`token_path` is where the desktop's token is kept between runs."""

    def __init__(self, token_path: str):
        self.token_path = token_path
        self._bus = None
        self._session = ""
        self._lock = threading.Lock()
        self.problem = ""    # why keys couldn't be pressed, the last time they couldn't

    # ---- asking the desktop ---------------------------------------------------------
    def ready(self) -> bool:
        return bool(self._session)

    def allow(self) -> None:
        """Get the desktop's leave, showing its question if it hasn't been answered
        before. Raises NotAllowed. Waits for the answer, so not for a thread that draws
        windows or listens."""
        with self._lock:
            if self._session:
                return
            try:
                self._open()
                self.problem = ""
            except NotAllowed as e:
                self._session, self.problem = "", str(e)
                raise

    def _open(self) -> None:
        from gi.repository import Gio, GLib
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            raise NotAllowed(f"The desktop's message bus can't be reached: {e.message}") from e
        session_token = _token()
        created = self._ask("CreateSession", "(a{sv})", [{
            "session_handle_token": GLib.Variant("s", session_token)}])
        session = str(created.get("session_handle", ""))
        if not session:
            raise NotAllowed("The desktop gave no session for pressing keys.")
        choice = {"types": GLib.Variant("u", KEYBOARD), "persist_mode": GLib.Variant("u", UNTIL_REVOKED)}
        kept = self._kept_token()
        if kept:
            choice["restore_token"] = GLib.Variant("s", kept)
        self._ask("SelectDevices", "(oa{sv})", [session, choice])
        started = self._ask("Start", "(osa{sv})", [session, "", {}])
        if not int(started.get("devices", 0)) & KEYBOARD:
            raise NotAllowed("The desktop didn't allow the keyboard.")
        self._keep_token(str(started.get("restore_token", "")))
        self._session = session

    def _ask(self, method: str, signature: str, arguments: list) -> dict:
        """Call one of the portal's methods that answers later, and wait for the answer."""
        from gi.repository import Gio, GLib
        token = _token()
        sender = self._bus.get_unique_name()[1:].replace(".", "_")
        expected = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        answer, loop = {}, GLib.MainLoop()

        def on_response(_bus, _sender, _path, _iface, _signal, parameters):
            answer["code"], answer["results"] = parameters.unpack()
            loop.quit()

        listening = self._bus.signal_subscribe(
            BUS, REQUEST, "Response", expected, None, Gio.DBusSignalFlags.NONE, on_response)
        try:
            arguments = list(arguments)
            arguments[-1] = dict(arguments[-1], handle_token=GLib.Variant("s", token))
            try:
                self._bus.call_sync(BUS, PATH, REMOTE, method, GLib.Variant(signature, tuple(arguments)),
                                    None, Gio.DBusCallFlags.NONE, 10000, None)
            except GLib.Error as e:
                raise NotAllowed(f"The desktop can't be asked to press keys: {e.message}") from e
            GLib.timeout_add(int(ANSWER_SECONDS * 1000), loop.quit)
            loop.run()
        finally:
            self._bus.signal_unsubscribe(listening)
        if "code" not in answer:
            raise NotAllowed("The desktop's question about controlling the keyboard wasn't answered.")
        if answer["code"] != 0:
            raise NotAllowed("Controlling the keyboard wasn't allowed on this computer.")
        return answer["results"]

    def _kept_token(self) -> str:
        try:
            with open(self.token_path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""

    def _keep_token(self, token: str) -> None:
        if not token:
            return
        try:
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                      encoding="utf-8") as f:
                f.write(token)
        except OSError:
            pass

    # ---- pressing keys ----------------------------------------------------------------
    def _key(self, sym: int, down: bool) -> None:
        from gi.repository import Gio, GLib
        try:
            self._bus.call_sync(
                BUS, PATH, REMOTE, "NotifyKeyboardKeysym",
                GLib.Variant("(oa{sv}iu)", (self._session, {}, sym, 1 if down else 0)),
                None, Gio.DBusCallFlags.NONE, 3000, None)
        except GLib.Error as e:
            self._session = ""            # the session has gone: ask again next time
            raise NotAllowed(f"The desktop stopped taking key presses: {e.message}") from e

    def type(self, text: str, pause: float = 0.0) -> None:
        """Type `text`, character by character. Raises NotAllowed."""
        self.allow()
        with self._lock:
            for character in text:
                sym = keysym(character)
                self._key(sym, True)
                self._key(sym, False)
                if pause:
                    time.sleep(pause)

    def press(self, keys: str, times: int = 1) -> None:
        """Press keys held together, such as "shift+enter" or "ctrl+z", `times` times."""
        self.allow()
        names = keys.split("+")
        syms = [KEYSYMS[name] if name in KEYSYMS else keysym(name) for name in names]
        with self._lock:
            for _ in range(times):
                for sym in syms:
                    self._key(sym, True)
                for sym in reversed(syms):
                    self._key(sym, False)

    def close(self) -> None:
        from gi.repository import Gio
        with self._lock:
            session, self._session = self._session, ""
            if session and self._bus is not None:
                try:
                    self._bus.call_sync(BUS, session, "org.freedesktop.portal.Session", "Close",
                                        None, None, Gio.DBusCallFlags.NONE, 2000, None)
                except Exception:
                    pass


_shared = None


def shared() -> Keys:
    """The one set of keys for the whole program. The desktop's leave is kept under one
    token, which is handed over anew each time it is used: two sets would each spend
    the other's."""
    global _shared
    if _shared is None:
        from . import config
        _shared = Keys(os.path.join(os.path.dirname(config.STATE_FILE), "keys-token"))
    return _shared


def _token() -> str:
    return "linuxspeaking" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
