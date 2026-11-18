"""The engine's side of the link to the Thunderbird add-on.

The add-on can't be reached from outside, so it calls us: it keeps one HTTP request
open to this server (a "long poll"), we answer it with the next thing to do, and it
sends the result back with its next request.

The server listens on this computer only, but so can anything else on it: another
person's program, or one kept apart from your files that may still use the network. So
the two ends prove themselves to each other with a key that the installer makes for this
computer and builds into the add-on's file:

- The add-on's first request brings a number it has made up. The answer proves the
  engine holds the key (it is made from the key and that number) and brings a number of
  the engine's, a "turn".
- Every request after that is signed over its turn, which is good once, and every answer
  over the request's number. Only such a request is given anything to do, so what is
  dictated never goes to a stranger; and the add-on does only what such an answer tells
  it, so a stranger sitting on the port can neither read the message nor change it.

Nor can a stranger come between the two. The turn the add-on holds is not given up
because somebody else has asked for one: the turns given to requests that proved nothing
are kept apart from those given to requests that did (remote.py's Turns). Only so many
callers are attended to at once, and each has a few seconds to send the whole of its
request, however slowly it sends it.

An add-on from before this has no key. It is told nothing: and it is kept waiting as long
as an idle poll is, because it asks again the moment it is answered and would otherwise
ask thousands of times a second. The log says to install the new one, and `problem` says
it in words for the person. An add-on made for another key than this computer's now holds
is noticed too, by its asking over and over and never proving anything.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler

from . import config
from .remote import HEAD_BYTES, LimitedServer, Measured, Turns

POLL_SECONDS = 20      # how long an idle poll is held open
ALIVE_SECONDS = 30     # no poll for this long means Thunderbird isn't there
MAX_BODY = 1024 * 1024  # more than any answer of the add-on's
READ_SECONDS = 5       # what a caller has to send the whole of a request
MOST_CALLERS = 16      # how many callers are attended to at once
UNPROVED = 3           # so many requests running that proved nothing: it is not this key's add-on
AGAIN = ("Add it again: Add-ons and Themes, the gear, Install Add-on From File…, and choose "
         "linux-speaking-thunderbird.xpi in ")  # and then the folder


def prove(key: str, *parts: str) -> str:
    """Proof of holding the key, made over the parts of what is being said. The add-on
    makes the same from the same (background.js)."""
    # Half a letter by itself, which only a stranger would send, is no reason to fail.
    said = "\n".join(parts).encode("utf-8", "surrogatepass")
    return hmac.new(key.encode("utf-8"), said, hashlib.sha256).hexdigest()


def _is_number(text) -> bool:
    """Whether `text` is a number as either end makes one up: 32 figures, 0 to 9 and a to f."""
    return isinstance(text, str) and len(text) == 32 and all(c in "0123456789abcdef" for c in text)


def read_key(text: str) -> str:
    """The key out of what its file holds: the figures 0 to 9 and a to f in it, and no
    others. scripts/build-xpi.sh reads the file the same way, so that the engine and the
    add-on make the same key of a file that somebody has written by hand."""
    return "".join(c for c in text.lower() if c in "0123456789abcdef")


def own_key(path: str) -> str:
    """This computer's key for the link, made the first time it is asked for. "" if it
    can't be kept, and then there is no link."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            key = read_key(f.read())
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                       encoding="utf-8") as f:
            f.write(key + "\n")
    except OSError:
        return ""
    return key


class _Server(LimitedServer):
    called = "the link to Thunderbird"

    def most(self) -> int:
        return MOST_CALLERS


class MailBridge:
    def __init__(self, port: int, key: str):
        self.port = port
        self.key = key
        self.outdated = False   # an add-on without the key is asking: an older one
        self._turns = Turns()   # the numbers a next request may be signed over
        self._requests: queue.Queue = queue.Queue()
        self._waiting: dict = {}  # request id -> event
        self._replies: dict = {}  # request id -> reply
        self._lock = threading.Lock()
        self._next_id = 0
        never = float("-inf")
        self._last_poll = never      # when the add-on last asked, having proved itself
        self._last_older = never     # when an add-on from before the key last asked
        self._unproved = 0           # requests running that proved nothing,
        self._polls = 0            # how many signed polls there have been: the last is the live one
        self._last_unproved = never  # and when the last of them came
        self._holding = threading.Lock()  # held while an older add-on is kept waiting
        self._stopped = threading.Event()
        self._server = None

    def start(self) -> bool:
        """Start listening. False if the port is taken (another engine is running)."""
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def setup(self):
                super().setup()
                # The whole of a request is read with one allowance of time, however
                # slowly it is sent, and no more of it than it could come to.
                self.rfile.close()
                self._until = time.monotonic() + READ_SECONDS
                self._coming = Measured(self.connection, READ_SECONDS, HEAD_BYTES)
                self.rfile = io.BufferedReader(self._coming)

            def handle(self):
                self.close_connection = True  # one request to a connection: the allowance is for one
                self.handle_one_request()

            def do_POST(self):
                # Web pages must not be able to talk to this, and a browser always
                # names the page a request like this comes from. Only an add-on may.
                origin = self.headers.get("Origin")
                if self.path != "/poll" or (
                        origin is not None and not origin.startswith("moz-extension://")):
                    self._say(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if not 0 <= length <= MAX_BODY:
                    self._say(413)
                    return
                self._coming.allow(self._until - time.monotonic(), length)
                try:
                    sent = self.rfile.read(length)
                except OSError:
                    return                # too slow about it, or gone
                if len(sent) != length:
                    return                # it went away part of the way through
                try:
                    body = json.loads(sent or b"{}")
                except (ValueError, RecursionError):
                    body = None
                if not isinstance(body, dict):
                    self._say(400)        # not anything an add-on of any age sends
                    return
                answer = bridge._answer(body)
                if isinstance(answer, dict):
                    self._say(200, json.dumps(answer).encode("utf-8"))
                else:
                    self._say(answer)

            def _say(self, code: int, data: bytes = b"") -> None:
                try:
                    self.connection.settimeout(READ_SECONDS)  # the reading left it at what was left
                    self.send_response(code)
                    if data:
                        self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    # Thunderbird keeps what it is sent in its cache on the disk unless it
                    # is told not to: a file for every answer, thousands a day at the best
                    # of times, and a million in a day when an old add-on once asked as
                    # fast as it could. None of it is ever wanted again.
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

        try:
            self._server = _Server(("127.0.0.1", self.port), Handler)
        except OSError:
            return False
        self._stopped.clear()
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        self._stopped.set()               # an older add-on being kept waiting is let go
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def problem(self) -> str:
        """What is wrong with the add-on that is asking, and what to do about it, in
        words for the person: or "" if the add-on is connected, or none is asking."""
        if self._server is None or self.connected():
            return ""
        now = time.monotonic()
        with self._lock:
            older = now - self._last_older < ALIVE_SECONDS
            stranger = self._unproved >= UNPROVED and now - self._last_unproved < ALIVE_SECONDS
        if older:
            return f"Thunderbird's add-on is an older one. {AGAIN}{config.INSTALL_DIR}."
        if stranger:
            return ("Thunderbird's add-on was made for another key than this computer has now. "
                    f"{AGAIN}{config.INSTALL_DIR}. If that doesn't mend it, run the installer "
                    "again first: it makes that file afresh.")
        return ""

    def _signed(self, nonce: str, payload: dict, proven: bool = False) -> dict:
        """An answer the add-on will believe: signed over its own number, with the turn
        for its next request. `proven` says the request it answers was signed: the turns
        of those that were not are kept apart, and can't push out the add-on's."""
        turn = self._turns.give(b"mail", proven=proven)
        text = json.dumps(payload)
        return {"turn": turn, "payload": text, "auth": prove(self.key, "next", nonce, turn, text)}

    def _answer(self, body: dict):
        """One request of the add-on's, checked before anything is done with it. Gives
        the answer to send: or a number, for a refusal that says nothing at all."""
        nonce, turn = body.get("nonce"), body.get("turn")
        if nonce in (None, ""):
            # An add-on from before the key sends its replies and nothing else. Anything
            # else with no number in it is not an add-on at all, and nobody is told to
            # install one again on its account.
            return self._older() if isinstance(body.get("replies"), list) else 400
        if not _is_number(nonce):
            return 400                    # no number of the add-on's: nothing is signed over it
        if turn in (None, ""):
            self._proved_nothing()
            return self._signed(nonce, {})    # its first: who we are, and its first turn
        payload, auth = body.get("payload", ""), body.get("auth", "")
        proved = (
            _is_number(turn) and isinstance(payload, str) and isinstance(auth, str)
            and self._turns.good(turn)
            and hmac.compare_digest(auth.encode("utf-8", "replace"),
                                    prove(self.key, "poll", turn, nonce, payload).encode("utf-8"))
            # Used up only now, by a request that was rightly signed: and only once, should
            # the same request come twice at the same moment.
            and self._turns.use(turn) is not None)
        if not proved:
            self._proved_nothing()
            return self._signed(nonce, {})    # nothing done, nothing told: it may start again
        try:
            said = json.loads(payload)
            replies = said.get("replies", []) if isinstance(said, dict) else []
        except (ValueError, RecursionError):
            replies = []
        return self._signed(nonce, self._poll(replies if isinstance(replies, list) else []),
                            proven=True)

    def _older(self):
        """A request with no number in it: from an add-on from before the key. It is
        told nothing, after being kept waiting as long as an idle poll is: that add-on
        asks again the moment it is answered. One is kept waiting at a time. Another
        meanwhile is refused at once with no answer at all, which that add-on takes for
        the engine not being there, and waits a few seconds itself."""
        with self._lock:
            self._last_older = time.monotonic()
            first, self.outdated = not self.outdated, True
        if first:
            print("the Thunderbird add-on is an older one, without this computer's key: "
                  "install the new one in Add-ons and Themes", flush=True)
        if not self._holding.acquire(blocking=False):
            return 503
        try:
            self._stopped.wait(POLL_SECONDS)
        finally:
            self._holding.release()
        with self._lock:
            self._last_older = time.monotonic()
        return {}

    def _proved_nothing(self) -> None:
        """Count a request that proved nothing. The add-on makes one when it starts, and
        its next is signed. One made for another key (the key's file has been made
        afresh since, say) can't check the engine's answer, so it starts again every few
        seconds and never signs anything."""
        with self._lock:
            self._unproved += 1
            self._last_unproved = time.monotonic()
            first = self._unproved == UNPROVED
        if first:
            print("something keeps asking for the Thunderbird add-on's work without this "
                  "computer's key. If it is the add-on, it was made for another key: install "
                  "the one the installer made, in Add-ons and Themes", flush=True)

    def _poll(self, replies: list) -> dict:
        if not self.connected():
            print("Thunderbird add-on connected", flush=True)
        self._last_poll = time.monotonic()
        with self._lock:
            self._unproved = 0            # the add-on that is here holds the key
            self.outdated = False         # and is not the older one, whatever asked before
            self._polls += 1
            mine = self._polls
            for item in replies:
                if not isinstance(item, dict):
                    continue
                event = self._waiting.pop(item.get("id"), None)
                if event:
                    self._replies[item.get("id")] = item.get("reply") or {
                        "ok": False, "why": "no reply"}
                    event.set()
        until = time.monotonic() + POLL_SECONDS
        while True:
            with self._lock:
                if self._polls != mine:
                    # A later poll has come in. The add-on asks one at a time, so this
                    # one was left behind by an add-on that has been loaded again: a
                    # request handed to it would go nowhere.
                    return {}
            left = until - time.monotonic()
            if left <= 0:
                return {}
            try:
                request_id, message = self._requests.get(timeout=min(left, 0.5))
            except queue.Empty:
                continue
            with self._lock:
                if self._polls != mine:
                    self._requests.put((request_id, message))   # for the poll that is live
                    return {}
                if request_id in self._waiting:
                    return {"id": request_id, "message": message}
            # Nobody is waiting for that one any more: carried out now, it would come as
            # a surprise, and twice if it was said again.

    def connected(self) -> bool:
        return self._server is not None and time.monotonic() - self._last_poll < ALIVE_SECONDS

    def request(self, message: dict, timeout: float = 4.0) -> dict:
        """Send one request to the add-on and return its reply. Never raises."""
        if not self.connected():
            return {"ok": False, "why": "mail not running"}
        event = threading.Event()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._waiting[request_id] = event
        self._requests.put((request_id, message))
        if not event.wait(timeout):
            with self._lock:
                self._waiting.pop(request_id, None)
            return {"ok": False, "why": "mail not answering"}
        with self._lock:
            return self._replies.pop(request_id)
