"""Having another computer do the listening.

Whisper is the slow part, and a faster computer on the same network can do it. That
computer shares its recogniser; this one sends each phrase's sound to it and gets the
words back. If it can't be reached, this computer does the work itself.

One request is a phrase. It is an HTTP POST whose body is a short JSON header (what kind
of listening, the text before the cursor, which model) and then the sound.

Both computers hold a key, which never travels. What travels is proof of holding it:

- Before anything is sent, this computer says hello with a number it has just made up,
  and the other answers with a number of its own, a "turn", and proof made from the key
  and both numbers. So a computer that only answers to the right name is found out before
  it is given any sound.
- Every request carries a turn and is signed over it. A turn is good once, and for a
  minute, so a request that was overheard can't be sent again.
- Ahead of a request's body, in its first lines, comes a second and shorter proof, made
  over the turn, the request's own number and how much is to follow. The body is not read
  until that has been checked and the turn found good: so nobody without the key can have
  the sharing computer take in megabytes that it will only throw away.
- Every reply is signed over the request's numbers too, and brings the turn for the next
  request. A reply that isn't, is not believed: nothing it says is typed.

And what travels is encrypted: the sound, the text before the cursor, and the words that
come back. With the hello each computer sends half of a key made for the occasion (an
X25519 exchange); the proof covers both halves, so nobody in between can put in halves of
their own. The key the two then share is never sent, is used for one run of requests, and
is forgotten: so what was overheard can't be read later either, even by someone who has
since got hold of the key in Settings. Each request and each reply is sealed under a key
of its own made from that one (ChaCha20-Poly1305). This needs the "cryptography" package,
which the installer fetches. Without it the link is not used at all: nothing is sent in
the clear.

Still to be seen from outside: that phrases are being sent, when, and how long each is.

The sharing computer answers on the network, where anything can call it, with the key or
without. So that a stranger can do no more than be a nuisance to the sharing itself:

- Only a handful of callers are attended to at once. The rest are turned away at the
  door, unheard.
- A caller has one allowance of time for the whole of what it sends, however slowly it
  sends it, and a short one until it has shown that it holds the key.
- The turns given at hello, which anyone may ask for, are counted apart from those given
  with a signed reply: a stranger saying hello can't push out the turn that a real caller
  is about to use.

The asking computer is as careful of whatever answers at the address it was given: each
exchange has one allowance of time, a short one for the hello, and no more is read than
an answer could come to. And whatever goes wrong, of whatever kind, ends the same way:
this computer does the listening itself.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import io
import ipaddress
import re
import json
import secrets
import socket
import socketserver
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, config

MAX_BODY = 4 * 1024 * 1024  # a 20 second phrase is 640 kB
MAX_REPLY = 256 * 1024      # more than any answer comes to: the words, or the list of models
HEAD_BYTES = 16 * 1024      # more than the first lines of any request or answer come to
CONNECT_SECONDS = 2.0       # the other computer is near by, or it isn't there
HELLO_SECONDS = 5.0         # for the whole of a hello, which is no work to answer
ANSWER_SECONDS = 60.0       # for the whole of a request: a big model on a long phrase
RETRY_SECONDS = 20.0        # after a failure, how long this computer manages by itself
AUTH = "X-LS-Auth"          # proof of holding the key
ASK = "X-LS-Ask"            # the proof that comes ahead of a request's body
NONCE = "X-LS-Nonce"        # the asker's number, made up for this one request
TURN = "X-LS-Turn"          # the answerer's number that the request uses up
NEXT = "X-LS-Next"          # the turn for the asker's next request
KEY = "X-LS-Key"            # hello: the asker's half of the key for this run of requests
TURN_SECONDS = 60.0         # how long a turn is good for
MOST_TURNS = 512            # how many are kept waiting to be used, of each kind
MOST_CALLERS = 8            # how many callers are attended to at once
HEAD_SECONDS = 5.0          # what a caller has to say what it wants and show it holds the key
BODY_SECONDS = 30.0         # and what it then has to send the sound
MOST_BODY_SECONDS = 55.0    # at most, for a long phrase on a slow link: under ANSWER_SECONDS
SLOWEST_BYTES = 16000.0     # the slowest link allowed for, in bytes a second (128 kbit/s)
SPILL_SECONDS = 2.0         # how long a caller that was refused may go on sending, unread
PROVEN_SPILL_SECONDS = 6.0  # and one whose first lines were rightly signed, but whose turn has gone
REPLY_SECONDS = 10.0        # how long a caller has to take its answer
OLDER = "an older Linux Speaking"  # said to, and of, one that talks in an earlier way
# Which way of talking this is: the third since the first, which only signed each request.
# Then came the turns, then the sealing, and now the proof ahead of the body. The sharing
# computer says its number at hello, and one that says none, or a lower, is sent nothing:
# it is said to be older. A request made an older way is refused in the same words. The
# number goes up whenever a computer from before could no longer take part. It is not
# covered by the hello's proof and needn't be: someone in between who changed it would
# get a refusal, or nothing at all.
SPEAKS = 3


class RemoteError(Exception):
    """The other computer didn't do it. The message is for the person to read."""


# ---- what travels ----------------------------------------------------------------
def prove(key: str, what: str, *numbers: str, body: bytes = b"") -> str:
    """Proof of holding the key, made over what is being said and the numbers that make
    it fresh. `what` says which kind of thing it is, so one proof can't pass for another."""
    start = "\n".join((what,) + numbers).encode("utf-8") + b"\n"
    return hmac.new(key.encode("utf-8"), start + body, hashlib.sha256).hexdigest()


def sign(key: str, method: str, path: str, body: bytes, turn: str = "", nonce: str = "") -> str:
    """Proof that whoever sent this request holds the key, and sent it for this turn."""
    return prove(key, f"{method} {path}", turn, nonce, body=body)


def ask(key: str, method: str, path: str, length: int, turn: str, nonce: str) -> str:
    """The proof that comes ahead of a request's body: that whoever is sending holds the
    key, means this turn, and has so many bytes to send. It is checked before any of
    them is read. ("ask" stands on a line of its own: no request's own first line can be
    that, so this proof and the one over a whole request can't pass for each other.)"""
    return prove(key, "ask", f"{method} {path}", turn, nonce, str(length))


def number() -> str:
    """A number made up on the spot, that nobody could guess."""
    return secrets.token_hex(16)


# ---- keeping it from being read on the way ---------------------------------------------
def _box():
    """The parts of the "cryptography" package that are used: the key exchange and the
    cipher. Raises RemoteError where the package is missing."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import x25519
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    except ImportError as e:
        raise RemoteError("Nothing can be encrypted on this computer, so the other one is not "
                          "used: the \"cryptography\" package is missing. Run the installer "
                          "again.") from e
    return serialization, x25519, ChaCha20Poly1305


def half() -> tuple:
    """(this computer's half of a key to be agreed, to keep; the same as it is sent)."""
    serialization, x25519, _ = _box()
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
    return private, public.hex()


def _is_half(text: str) -> bool:
    return len(text) == 64 and all(c in "0123456789abcdef" for c in text)


def agreed(private, theirs: str, nonce: str, asker: str, answerer: str) -> bytes:
    """The key two computers share for one run of requests, from this one's half and the
    other's. Raises ValueError if the other's half is not a fit one."""
    _, x25519, _ = _box()
    try:
        secret = private.exchange(x25519.X25519PublicKey.from_public_bytes(bytes.fromhex(theirs)))
    except Exception as e:  # one made up to give a key that could be guessed
        raise ValueError("not a half of a key") from e
    said = f"run\n{nonce}\n{asker}\n{answerer}".encode("utf-8")
    return hmac.new(secret, said, hashlib.sha256).digest()


def _own_key(run: bytes, what: str, turn: str, nonce: str) -> bytes:
    """The key for one request or one reply: each has its own, so none is used twice."""
    return hmac.new(run, f"{what}\n{turn}\n{nonce}".encode("utf-8"), hashlib.sha256).digest()


def seal(run: bytes, what: str, turn: str, nonce: str, data: bytes, about: str) -> bytes:
    """`data` made unreadable to anyone without the run's key, and unchangeable. `about`
    says what it is for, and must be the same when it is opened."""
    cipher = _box()[2](_own_key(run, what, turn, nonce))
    return cipher.encrypt(b"\0" * 12, data, about.encode("utf-8"))


def unseal(run: bytes, what: str, turn: str, nonce: str, sealed: bytes, about: str) -> bytes:
    """What seal() was given. Raises ValueError if it was sealed with another key, for
    something else, or has been changed."""
    cipher = _box()[2](_own_key(run, what, turn, nonce))
    try:
        return cipher.decrypt(b"\0" * 12, sealed, about.encode("utf-8"))
    except Exception as e:
        raise ValueError("could not be opened") from e


def _check() -> None:
    """Try the key exchange and the cipher once, as they will be used. Raises RemoteError
    if nothing can be encrypted here: the package is missing, or is one built without
    what is needed."""
    try:
        (mine, sent), (theirs, got) = half(), half()
        run = agreed(mine, got, "", sent, got)
        if run != agreed(theirs, sent, "", sent, got) or unseal(
                run, "try", "", "", seal(run, "try", "", "", b"try", "try"), "try") != b"try":
            raise ValueError("it doesn't give back what it was given")
    except RemoteError:
        raise
    except Exception as e:
        raise RemoteError("Nothing can be encrypted on this computer, so the other one is not "
                          "used: the \"cryptography\" package here can't do what is needed "
                          f"({type(e).__name__}).") from e


def _is_number(text: str) -> bool:
    return len(text) == 32 and all(c in "0123456789abcdef" for c in text)


def _same(given: str, wanted: str) -> bool:
    """Whether two proofs are the same, taking as long whether or not they are."""
    return hmac.compare_digest(given.encode("utf-8", "replace"), wanted.encode("utf-8"))


class Turns:
    """The turns a sharing computer has given out and not yet seen used.

    Those given at hello, to whoever asked, are kept apart from those given with a
    signed reply, to a caller that had shown it holds the key. Only so many are kept, and
    anyone may say hello as often as they like: kept together, a stranger's hellos would
    push out the turn a real caller was about to use."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        # Each is turn -> (when it stops being good, its run's key).
        self._offered, self._earned = {}, {}
        self._lock = threading.Lock()

    def give(self, run: bytes = b"", proven: bool = False) -> str:
        """A new turn, for a request that will be sealed with the key `run`. `proven`
        says it goes with a signed reply, to a caller that holds the key."""
        turn, now = number(), self._clock()
        with self._lock:
            kept = self._earned if proven else self._offered
            for old in [t for t, (until, _) in kept.items() if until <= now]:
                del kept[old]
            while len(kept) >= MOST_TURNS:
                del kept[next(iter(kept))]                 # the oldest: it had its chance
            kept[turn] = (now + TURN_SECONDS, run)
        return turn

    def good(self, turn: str) -> bool:
        with self._lock:
            until = max(kept.get(turn, (0.0, b""))[0] for kept in (self._offered, self._earned))
        return until > self._clock()

    def use(self, turn: str):
        """Use a turn up. Its run's key, or None if the turn was never given, has been
        used, or is too old."""
        with self._lock:
            until, run = self._earned.pop(turn, None) or self._offered.pop(turn, (0.0, b""))
        return run if until > self._clock() else None


class _TooMuch(OSError):
    """More came in on a connection than what was being read could come to."""


class Measured(io.RawIOBase):
    """What comes in on a connection, with one allowance of time and one of size for the
    whole of what is being read, however slowly or however much the other end sends. (A
    time limit set on the connection itself starts again with every byte that arrives:
    one byte a minute would be waited on for ever.) The link to Thunderbird reads its
    callers through this too (mailbridge.py)."""

    def __init__(self, connection, seconds: float, most: int):
        self._connection = connection
        self.allow(seconds, most)

    def allow(self, seconds: float, most: int) -> None:
        """So long, and so many bytes, from now."""
        self._until, self._most = time.monotonic() + seconds, most

    def readable(self) -> bool:
        return True

    def readinto(self, into) -> int:
        left = self._until - time.monotonic()
        if self._most <= 0:
            raise _TooMuch("more than it could be")
        if left <= 0:
            raise socket.timeout("too slow")
        self._connection.settimeout(left)
        got = self._connection.recv_into(into, min(len(into), self._most))
        self._most -= got
        return got


class _Timed:
    """A connection to the other computer on which a whole exchange has one allowance of
    time, and from which only so much is read. It is what http.client is given in place
    of the connection itself, and has the three things that is asked for."""

    def __init__(self, connection, until: float, most: int):
        self._connection, self._until, self._most = connection, until, most

    def sendall(self, data) -> None:
        left = self._until - time.monotonic()
        if left <= 0:
            raise socket.timeout("out of time")
        self._connection.settimeout(left)  # for the whole of the sending, not for each piece
        self._connection.sendall(data)

    def makefile(self, *_, **__):
        return io.BufferedReader(
            Measured(self._connection, self._until - time.monotonic(), self._most))

    def close(self) -> None:
        # Asked for as soon as the first lines of an answer are in, with the rest of it
        # still to be read: so the connection is left for whoever made it to close.
        pass


def pack(header: dict, sound: bytes) -> bytes:
    """A request's body: how long the header is, the header, then the sound."""
    head = json.dumps(header).encode("utf-8")
    return struct.pack(">I", len(head)) + head + sound


def unpack(body: bytes) -> tuple:
    """(header, sound) from a request's body. Raises ValueError if it isn't one."""
    if len(body) < 4:
        raise ValueError("too short")
    (length,) = struct.unpack(">I", body[:4])
    if length > len(body) - 4:
        raise ValueError("header runs past the end")
    header = json.loads(body[4:4 + length].decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("header is not a set of values")
    return header, body[4 + length:]


def to_pcm(audio) -> bytes:
    """Sound as it travels: 16-bit, one channel, config.RATE samples a second."""
    import numpy as np
    return (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()


def from_pcm(sound: bytes):
    import numpy as np
    return np.frombuffer(sound[:len(sound) // 2 * 2], dtype="<i2").astype(np.float32) / 32767


def _is_host(host: str) -> bool:
    """Whether `host` could be a computer's address or its name: nothing is looked up.
    One that could not (a space in it, two dots together, a part too long) would only
    fail later, and less plainly, each time a phrase was sent."""
    try:
        address, sign, network = host.partition("%")  # after a % comes which network, for some
        ipaddress.ip_address(address)
        return not sign or bool(re.fullmatch(r"[A-Za-z0-9_.\-]{1,32}", network))
    except ValueError:
        pass
    try:
        name = host.encode("idna")        # as the name travels, if it has letters beyond a to z
    except UnicodeError:
        return False
    parts = name[:-1].split(b".") if name.endswith(b".") else name.split(b".")
    plain = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return len(name) <= 253 and all(
        0 < len(part) <= 63 and all(c in plain for c in part) for part in parts)


def parse_address(address: str) -> tuple:
    """(host, port) from "name", "name:port" or "[v6 address]:port". Raises RemoteError
    if it could not be the address of anything."""
    address = address.strip()
    if address.startswith("["):
        host, _, rest = address[1:].partition("]")
        port = rest.lstrip(":")
    elif address.count(":") == 1:
        host, port = address.split(":")
    else:
        host, port = address, ""
    try:
        number = int(port) if port else config.SHARE_PORT
    except ValueError:
        number = 0
    if not host or not 0 < number < 65536 or not _is_host(host):
        raise RemoteError("That isn't an address: use a name such as  office-pc  or  office-pc:47614")
    return host, number


# ---- the computer that shares its recogniser ----------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "LinuxSpeaking", ""  # which version is nobody's business

    def log_message(self, *_) -> None:  # nothing about callers goes to the log
        pass

    def setup(self) -> None:
        super().setup()
        # What the caller sends is read with one allowance of time and of size for the
        # whole of it: at first a short one, for it to say what it wants.
        self.rfile.close()
        self._coming = Measured(self.connection, HEAD_SECONDS, HEAD_BYTES)
        self.rfile = io.BufferedReader(self._coming)

    def handle(self) -> None:
        self.close_connection = True      # one request to a connection: the allowance is for one
        self.handle_one_request()

    def do_GET(self) -> None:
        self._serve(0)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self._refuse(413, "too big", length)
            return
        self._serve(length)

    def _serve(self, length: int) -> None:
        """Answer a request whose body, `length` bytes of it, has not been read yet."""
        owner = self.server.owner
        nonce = self.headers.get(NONCE, "")
        if not _is_number(nonce):
            # From before the turns: it is told so, in words its own window will show.
            self._refuse(400, f"{OLDER} is asking: update it on that computer", length)
            return
        if self.command == "GET" and self.path == "/hello":
            # Anyone may say hello. What they get proves this computer holds the key, and
            # is of no use to them unless they hold it too. With it goes this computer's
            # half of the key that the run of requests will be sealed with.
            theirs = self.headers.get(KEY, "")
            if not _is_half(theirs):
                self._refuse(400, f"{OLDER} is asking: update it on that computer")
                return
            try:
                private, mine = half()
                run = agreed(private, theirs, nonce, theirs, mine)
            except Exception:             # a half that isn't a fit one, or no cipher after all
                self._refuse(400, "not understood")
                return
            turn = owner.turns.give(run)
            self._reply(200, {"ok": True, "turn": turn, "key": mine, "speaks": SPEAKS},
                        proof=prove(owner.key, "hello", nonce, turn, theirs, mine))
            return
        turn, first = self.headers.get(TURN, ""), self.headers.get(ASK)
        if first is None:
            # From before the proof that comes ahead of the body: told the same.
            self._refuse(400, f"{OLDER} is asking: update it on that computer", length)
            return
        if not _same(first, ask(owner.key, self.command, self.path, length, turn, nonce)):
            self._refuse(403, "wrong key", length)
            return
        if not owner.turns.good(turn):
            self._refuse(401, "say hello first", length, proven=True)
            return
        # Only now is the body read: from a caller that holds the key and has a turn.
        # The time it is given grows with what it has said it will send, up to what the
        # asking computer waits in all: a twenty-second phrase over a slow link needs
        # more than a short one, and was otherwise cut off without a word.
        self._coming.allow(min(MOST_BODY_SECONDS, BODY_SECONDS + length / SLOWEST_BYTES), length)
        try:
            body = self.rfile.read(length)
        except OSError:
            return                        # too slow about it, or gone
        if len(body) != length:
            return                        # it went away part of the way through
        if not _same(self.headers.get(AUTH, ""),
                     sign(owner.key, self.command, self.path, body, turn, nonce)):
            self._refuse(403, "wrong key")
            return
        run = owner.turns.use(turn)
        if not run:                       # used by another request while this one was read
            self._refuse(401, "say hello first")
            return
        try:
            if self.command == "GET" and self.path == "/status":
                code, answer = 200, {"ok": True, **owner.describe()}
            elif self.command == "POST" and self.path == "/hear":
                try:
                    header, sound = unpack(unseal(run, "request", turn, nonce, body,
                                                  f"{self.command} {self.path}"))
                except (ValueError, RemoteError):
                    code, answer = 400, {"ok": False, "why": "not understood"}
                else:
                    code, answer = 200, owner.hear(header, from_pcm(sound))
            else:
                code, answer = 404, {"ok": False, "why": "no such thing"}
        except Exception as e:            # the recogniser failed: say so, and stay up
            code, answer = 500, {"ok": False, "why": f"error: {e}"}
        self._reply(code, answer, turn, nonce, run=run)

    def _refuse(self, code: int, why: str, length: int = 0, proven: bool = False) -> None:
        """Say no to a request, `length` bytes of whose body have not been read. They
        are not kept, but for a moment they are let come and thrown away: a caller that
        is cut off while it is still sending never gets to read why, and an older Linux
        Speaking, which sends its sound at once, has to be able to read that it is
        older. `proven` says the first lines were rightly signed, and it is given a
        little longer: but not as long as the sound would have had, because those lines
        prove only that somebody once held the key. Overheard, they can be sent again
        at any time, and each time would hold one of the few places for as long."""
        self._reply(code, {"ok": False, "why": why})
        left = min(length, MAX_BODY)
        self._coming.allow(PROVEN_SPILL_SECONDS if proven else SPILL_SECONDS, left)
        try:
            while left > 0:
                came = len(self.rfile.read1(min(left, 65536)))
                if not came:
                    break
                left -= came
        except OSError:
            pass

    def _reply(self, code: int, answer: dict, turn: str = "", nonce: str = "",
               proof: str = "", run: bytes = b"") -> None:
        """Answer. With the request's `turn`, `nonce` and `run` (its key), the answer is
        sealed, signed over those numbers, and brings the turn for the asker's next
        request."""
        data = json.dumps(answer).encode("utf-8")
        following = self.server.owner.turns.give(run, proven=True) if turn else ""
        if turn:
            data = seal(run, "reply", turn, nonce, data, f"reply {code}")
            proof = prove(self.server.owner.key, f"reply {code}", turn, nonce, following, body=data)
        try:
            self.connection.settimeout(REPLY_SECONDS)  # the reading left it at what was left
            self.send_response(code)
            self.send_header("Content-Type", "application/octet-stream" if turn else "application/json")
            self.send_header("Content-Length", str(len(data)))
            if proof:
                self.send_header(AUTH, proof)
            if following:
                self.send_header(NEXT, following)
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the caller went away


class LimitedServer(ThreadingHTTPServer):
    """A server that anything may call, kept from being used up by its callers. The link
    to Thunderbird answers through one too (mailbridge.py)."""

    daemon_threads = True
    allow_reuse_address = not config.WINDOWS  # on Windows this would let two programs share a port
    called = "sharing the recogniser"         # what it goes by in the log

    def __init__(self, *args):
        self._callers, self._counting = 0, threading.Lock()
        super().__init__(*args)

    def most(self) -> int:
        """How many callers are attended to at once."""
        return MOST_CALLERS

    def server_bind(self) -> None:
        # Not the usual way, which also has this computer's name looked up on the
        # network: nothing uses the name, and where the network is slow to answer the
        # looking up holds up whoever switched the sharing on.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def process_request(self, request, client_address) -> None:
        """Attend to a caller on a thread of its own, unless there are as many as will
        be attended to already: then it is turned away at the door, unheard. Each caller
        costs a thread and an open file for as long as it is here, and there is only so
        much of either: without this, callers with no key could use them all up."""
        with self._counting:
            room = self._callers < self.most()
            self._callers += room
        if not room:
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._gone()                  # no thread could be started for it
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._gone()

    def _gone(self) -> None:
        with self._counting:
            self._callers -= 1

    def handle_error(self, request, client_address) -> None:
        # The usual way writes down the caller's address and all that led up to the
        # failure. Nothing about callers goes to the log, and one that hangs up in the
        # middle of a request is nothing to write down at all.
        kind = sys.exc_info()[0]
        if kind is not None and not issubclass(kind, OSError):
            print(f"{self.called}: a request could not be answered ({kind.__name__})",
                  flush=True)


class Server:
    """Lets other computers use this one's recogniser.

    `hear(header, audio)` does one piece of listening and returns the reply; `describe()`
    says what this computer offers. Both are called on the server's own threads.
    """

    def __init__(self, address: str, port: int, key: str, hear, describe):
        self.address, self.port, self.key = address, port, key
        self.hear, self.describe = hear, describe
        self.turns = Turns()
        self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        """Start answering. Raises OSError if the address or port can't be had, or if
        nothing could be encrypted here: then nobody is answered at all."""
        if self._server is not None:
            return
        try:
            _box()
        except RemoteError as e:
            raise OSError("nothing can be encrypted here: the \"cryptography\" package is "
                          "missing. Run the installer again.") from e
        try:
            _check()                      # the package is there: and does what is needed?
        except RemoteError as e:
            raise OSError("nothing can be encrypted here: the \"cryptography\" package can't "
                          "do what is needed. Run the installer again.") from e
        server = LimitedServer((self.address, self.port), _Handler)
        server.owner = self
        self._server = server
        self.port = server.server_address[1]  # the real one, if 0 was asked for
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()


# ---- the computer that uses it --------------------------------------------------------
class _Lookup(threading.Thread):
    """Finds a computer's addresses from its name. The system does the looking up, and
    where the network is slow to answer it can take many seconds, with no way to hurry
    it: so it is done on a thread of its own, which nobody has to wait for."""

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host, self.port, self.found = host, port, None
        self.start()

    def run(self) -> None:
        try:
            self.found = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        except Exception:
            pass                          # no such name: nothing found


class Client:
    """Asks another computer to do the listening."""

    def __init__(self, address: str, key: str):
        self.host, self.port = parse_address(address)
        self.key = key
        # The turn for the next request, how long it is good, and the key of its run.
        self._turn = ("", 0.0, b"")
        self._lookup = None  # the looking up of the other computer's name, while it goes on
        self._lock = threading.Lock()

    def status(self) -> dict:
        """What the other computer offers: its version and its models."""
        return self._send("GET", "/status", b"")

    def hear(self, kind: str, audio, awake: bool, prompt: str = "", model: str = "",
             otherwise=(), quick: bool = False, exact: bool = False, sure: bool = False,
             speech_only: bool = True, wake_same: bool = True, code: bool = False) -> dict:
        """One piece of listening. `kind` is "phrase", or "alone" for a second or so of
        sound with nothing to go on. `model` is the one wanted there; if it hasn't got
        it, the first of `otherwise` that it has, else its own choice. `quick` asks for
        the quick way of listening (see quick.py). `sure` asks how sure the recogniser
        was of each word, which comes back as "sure" if it can say. `speech_only` has a
        noise that was written down as a word left out (see speech.py). `wake_same` has
        what is heard asleep listened to by `model` too, as everything else is: a
        computer with an earlier version takes no notice, and uses its own Whisper.
        `code` says that it is source code, which the other computer may keep a bigger
        Whisper for."""
        header = {"kind": kind, "awake": bool(awake), "prompt": prompt, "model": model,
                  "otherwise": list(otherwise), "quick": bool(quick), "exact": bool(exact),
                  "sure": bool(sure), "speech_only": bool(speech_only),
                  "wake_same": bool(wake_same), "code": bool(code)}
        return self._send("POST", "/hear", pack(header, to_pcm(audio)))

    def _addresses(self, until: float) -> list:
        """Where the other computer is, in the form a connection is made from."""
        try:  # written as numbers, it needs no looking up
            return socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM,
                                      flags=socket.AI_NUMERICHOST)
        except (socket.gaierror, UnicodeError):
            pass
        with self._lock:                  # one looking up at a time: a slow one is waited on again
            if self._lookup is None or not self._lookup.is_alive():
                self._lookup = _Lookup(self.host, self.port)
            lookup = self._lookup
        lookup.join(max(0.0, min(CONNECT_SECONDS, until - time.monotonic())))
        if lookup.is_alive() or not lookup.found:
            raise OSError("the name was not found, or not soon enough")
        return lookup.found

    def _connect(self, until: float):
        """A connection to the other computer, made in what CONNECT_SECONDS allows for
        finding it and for each of its addresses, and never later than `until`."""
        problem = OSError("no address")
        for family, kind, protocol, _, address in self._addresses(until):
            left = min(CONNECT_SECONDS, until - time.monotonic())
            if left <= 0:
                break
            connection = socket.socket(family, kind, protocol)
            try:
                connection.settimeout(left)
                connection.connect(address)
                return connection
            except OSError as e:
                problem = e
                connection.close()
        raise problem

    def _exchange(self, method: str, path: str, body: bytes, headers: dict,
                  seconds: float) -> tuple:
        """One request and its reply: (status, the reply's headers, its body). The whole
        of it has `seconds`, and the reply may be no longer than a reply could be: what
        answers there may not hold the key, and is not waited on or read for ever.
        Whatever goes wrong, it is a RemoteError that is raised."""
        until, connection = time.monotonic() + seconds, None
        try:
            try:
                connection = self._connect(until)
            except Exception as e:
                raise RemoteError("The other computer can't be reached.") from e
            talk = http.client.HTTPConnection(self.host, self.port)
            talk.sock = _Timed(connection, until, HEAD_BYTES + MAX_REPLY)
            talk.request(method, path, body=body or None,
                         headers=dict(headers, **{"Content-Type": "application/octet-stream"}))
            reply = talk.getresponse()
            data = reply.read(MAX_REPLY + 1)
            if len(data) > MAX_REPLY:
                raise RemoteError("Something else is answering at that address.")
            return reply.status, reply.headers, data
        except RemoteError:
            raise
        except _TooMuch as e:
            raise RemoteError("Something else is answering at that address.") from e
        except socket.timeout as e:
            raise RemoteError("The other computer took too long to answer.") from e
        except Exception as e:
            raise RemoteError("The other computer can't be reached.") from e
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _said(data: bytes):
        try:
            answer = json.loads(data.decode("utf-8"))
        except ValueError:
            return None
        return answer if isinstance(answer, dict) else None

    def _hello(self) -> tuple:
        """Have the other computer prove it holds the key, before it is sent anything,
        and agree with it the key that this run of requests is sealed with. Returns
        (the turn it gives for the first request, that key)."""
        private, mine = half()
        nonce = number()
        status, headers, data = self._exchange("GET", "/hello", b"", {NONCE: nonce, KEY: mine},
                                               HELLO_SECONDS)
        answer = self._said(data)
        if answer is None:
            raise RemoteError("Something else is answering at that address.")
        newer = RemoteError("The other computer says this one has an older Linux Speaking: "
                            "update it here.")
        if status == 400 and OLDER in str(answer.get("why", "")):
            raise newer                   # a later one, which no longer talks this way
        turn, theirs = str(answer.get("turn", "")), str(answer.get("key", ""))
        if status != 200 or not _is_half(theirs):
            # One from before the turns asks for the key first; one from before the
            # sealing sends no half of a key. Neither is sent anything.
            raise RemoteError(f"The other computer has {OLDER}: update it there, then try again.")
        if not _is_number(turn) or not _same(headers.get(AUTH, ""),
                                             prove(self.key, "hello", nonce, turn, mine, theirs)):
            raise RemoteError("The key doesn't match the other computer's, or something else "
                              "is answering at that address.")
        speaks = answer.get("speaks")
        if type(speaks) is not int or speaks < SPEAKS:
            # One from before the proof ahead of the body says no number. It would answer
            # all the same, but it is one that anybody can stop: better that it is updated.
            raise RemoteError(f"The other computer has {OLDER}: update it there, then try again.")
        if speaks > SPEAKS:
            raise newer
        try:
            return turn, agreed(private, theirs, nonce, mine, theirs)
        except ValueError as e:
            raise RemoteError("Something else is answering at that address.") from e

    def _take_turn(self) -> tuple:
        with self._lock:
            (turn, until, run), self._turn = self._turn, ("", 0.0, b"")
        return (turn, run) if turn and time.monotonic() < until else self._hello()

    def _send(self, method: str, path: str, body: bytes) -> dict:
        """One request, and what the other computer said to it. Whatever goes wrong, it
        is a RemoteError that is raised: whoever asked then does the work here."""
        try:
            return self._sent(method, path, body)
        except RemoteError:
            raise
        except Exception as e:            # none is known of: but no phrase is to be lost to one
            raise RemoteError(f"The other computer couldn't be asked ({type(e).__name__}: {e}).") from e

    def _sent(self, method: str, path: str, body: bytes) -> dict:
        for attempt in range(2):
            (turn, run), nonce = self._take_turn(), number()
            sealed = seal(run, "request", turn, nonce, body, f"{method} {path}") if body else b""
            status, headers, data = self._exchange(method, path, sealed, {
                TURN: turn, NONCE: nonce,
                ASK: ask(self.key, method, path, len(sealed), turn, nonce),
                AUTH: sign(self.key, method, path, sealed, turn, nonce)}, ANSWER_SECONDS)
            if status != 401 or attempt:
                break                     # else the turn had gone stale there: say hello again
        answer = self._said(data)         # of a refusal, which is not sealed
        following = headers.get(NEXT, "")
        if not _same(headers.get(AUTH, ""),
                     prove(self.key, f"reply {status}", turn, nonce, following, body=data)):
            # Not signed, so not believed: these are refusals from before the key was looked at.
            if status == 403:
                raise RemoteError("The other computer says the key doesn't match.")
            if status == 400 and answer and OLDER in str(answer.get("why", "")):
                raise RemoteError("The other computer says this one has an older Linux "
                                  "Speaking: update it here.")
            if status == 413:
                raise RemoteError("The other computer couldn't do it: too big.")
            raise RemoteError("The answer didn't come from a computer that holds the key.")
        if _is_number(following):
            with self._lock:
                self._turn = (following, time.monotonic() + TURN_SECONDS - 10, run)
        try:
            answer = self._said(unseal(run, "reply", turn, nonce, data, f"reply {status}"))
        except ValueError as e:
            raise RemoteError("The answer couldn't be read.") from e
        if answer is None:
            raise RemoteError("Something else is answering at that address.")
        if not answer.get("ok"):
            raise RemoteError(f"The other computer couldn't do it: {answer.get('why', '') or status}.")
        return answer


def _likelihood(value) -> float:
    """A figure from 0 to 1 out of a reply, or 0 if it isn't one. A reply is wanted for
    its words: an odd figure beside them must not lose them."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if 0.0 <= value <= 1.0 else 0.0


class Offload:
    """Stands where the recogniser stands, and hands the work to another computer.

    Whatever goes wrong there, this computer's own recogniser answers instead, and the
    other one is left alone for a little while so each phrase doesn't wait on it.
    """

    def __init__(self, local, client: Client, model: str = "", otherwise=(), wake: bool = False,
                 on_where=lambda there, problem: None, clock=time.monotonic):
        self._local = local      # called for this computer's recogniser, when it is needed
        self.client = client
        self.model = model
        self.otherwise = tuple(otherwise)
        self.wake = wake         # send what is heard while asleep, too
        self.quick = False       # ask for the quick way of listening
        self.speech_only = True  # and for noises written as words to be left out
        self.on_where = on_where
        self._clock = clock
        self._down_until = 0.0
        self.there = None        # whether the last listening was done there; None before any
        self.problem = ""
        self.model_there = ""    # the model the other computer used
        self.not_speech = 0.0
        self.ignored = ""

    def transcribe(self, audio, awake: bool, prompt: str = "", exact: bool = False,
                   code: bool = False) -> str:
        too_long = not awake and len(audio) > config.WAKE_MAX_SECONDS * config.RATE
        if (awake or self.wake) and not too_long:
            reply = self._ask("phrase", audio, awake, prompt, exact, code)
            if reply is not None:
                self.not_speech = _likelihood(reply.get("not_speech"))
                self.ignored = str(reply.get("ignored", ""))
                return str(reply.get("text", ""))
        local = self._local()
        text = local.transcribe(audio, awake, prompt, **({"exact": True} if exact else {}),
                                **({"code": True} if code else {}))
        self.not_speech = getattr(local, "not_speech", 0.0)
        self.ignored = getattr(local, "ignored", "")
        return text

    def hear_alone(self, audio) -> str:
        reply = self._ask("alone", audio, True, "")
        if reply is not None:
            return str(reply.get("text", ""))
        return self._local().hear_alone(audio)

    def _ask(self, kind: str, audio, awake: bool, prompt: str, exact: bool = False,
             code: bool = False):
        if self._clock() < self._down_until:
            return None
        try:
            reply = self.client.hear(kind, audio, awake, prompt, self.model, self.otherwise,
                                     self.quick, exact, speech_only=self.speech_only,
                                     code=code)
            if not isinstance(reply, dict):
                raise RemoteError("The other computer's answer was not understood.")
        except Exception as e:
            # Of whatever kind: a RemoteError says why in words for the person, and
            # anything else is not known of. Either way the phrase is heard here.
            self._down_until = self._clock() + RETRY_SECONDS
            self._note(False, str(e) if isinstance(e, RemoteError) else
                       f"The other computer couldn't be asked ({type(e).__name__}: {e}).")
            return None
        self.model_there = str(reply.get("model", ""))
        self._note(True, "")
        return reply

    def _note(self, there: bool, problem: str) -> None:
        if there != self.there or problem != self.problem:
            self.there, self.problem = there, problem
            self.on_where(there, problem)
