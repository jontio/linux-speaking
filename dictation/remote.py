"""Having another computer do the listening.

Whisper is the slow part, and a faster computer on the same network can do it. That
computer shares its recogniser; this one sends each phrase's sound to it and gets the
words back. If it can't be reached, this computer does the work itself.

One request is a phrase. It is an HTTP POST whose body is a short JSON header (what kind
of listening, the text before the cursor, which model) and then the sound. Every request
is signed with a key both computers hold, so the key itself never travels and nobody else
on the network can use the recogniser. The sound and the words are not encrypted here:
use this on your own network, or over a VPN.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, config

MAX_BODY = 4 * 1024 * 1024  # a 20 second phrase is 640 kB
CONNECT_SECONDS = 2.0       # the other computer is near by, or it isn't there
ANSWER_SECONDS = 60.0       # a big model on a long phrase
RETRY_SECONDS = 20.0        # after a failure, how long this computer manages by itself
AUTH = "X-LS-Auth"


class RemoteError(Exception):
    """The other computer didn't do it. The message is for the person to read."""


# ---- what travels ----------------------------------------------------------------
def sign(key: str, method: str, path: str, body: bytes) -> str:
    """Proof that whoever sent this request holds the key."""
    start = f"{method} {path}\n".encode("utf-8")
    return hmac.new(key.encode("utf-8"), start + body, hashlib.sha256).hexdigest()


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


def parse_address(address: str) -> tuple:
    """(host, port) from "name", "name:port" or "[v6 address]:port"."""
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
    if not host or not 0 < number < 65536:
        raise RemoteError("That isn't an address: use a name such as  office-pc  or  office-pc:47614")
    return host, number


# ---- the computer that shares its recogniser ----------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "LinuxSpeaking/" + __version__
    timeout = 30  # a caller that goes quiet doesn't hold a thread for ever

    def log_message(self, *_) -> None:  # nothing about callers goes to the log
        pass

    def do_GET(self) -> None:
        self._serve(b"")

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True  # the body is left unread
            self._reply(413, {"ok": False, "why": "too big"})
            return
        self._serve(self.rfile.read(length))

    def _serve(self, body: bytes) -> None:
        owner = self.server.owner
        given = self.headers.get(AUTH, "")
        if not hmac.compare_digest(given, sign(owner.key, self.command, self.path, body)):
            self._reply(403, {"ok": False, "why": "wrong key"})
            return
        if self.command == "GET" and self.path == "/status":
            self._reply(200, {"ok": True, **owner.describe()})
        elif self.command == "POST" and self.path == "/hear":
            try:
                header, sound = unpack(body)
            except ValueError:
                self._reply(400, {"ok": False, "why": "not understood"})
                return
            try:
                self._reply(200, owner.hear(header, from_pcm(sound)))
            except Exception as e:  # the recogniser failed: say so, and stay up
                self._reply(500, {"ok": False, "why": f"error: {e}"})
        else:
            self._reply(404, {"ok": False, "why": "no such thing"})

    def _reply(self, code: int, answer: dict) -> None:
        data = json.dumps(answer).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the caller went away


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not config.WINDOWS  # on Windows this would let two programs share a port


class Server:
    """Lets other computers use this one's recogniser.

    `hear(header, audio)` does one piece of listening and returns the reply; `describe()`
    says what this computer offers. Both are called on the server's own threads.
    """

    def __init__(self, address: str, port: int, key: str, hear, describe):
        self.address, self.port, self.key = address, port, key
        self.hear, self.describe = hear, describe
        self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        """Start answering. Raises OSError if the address or port can't be had."""
        if self._server is not None:
            return
        server = _HTTPServer((self.address, self.port), _Handler)
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
class Client:
    """Asks another computer to do the listening."""

    def __init__(self, address: str, key: str):
        self.host, self.port = parse_address(address)
        self.key = key

    def status(self) -> dict:
        """What the other computer offers: its version and its models."""
        return self._send("GET", "/status", b"")

    def hear(self, kind: str, audio, awake: bool, prompt: str = "", model: str = "",
             otherwise=(), quick: bool = False, exact: bool = False, sure: bool = False,
             speech_only: bool = True) -> dict:
        """One piece of listening. `kind` is "phrase", or "alone" for a second or so of
        sound with nothing to go on. `model` is the one wanted there; if it hasn't got
        it, the first of `otherwise` that it has, else its own choice. `quick` asks for
        the quick way of listening (see quick.py). `sure` asks how sure the recogniser
        was of each word, which comes back as "sure" if it can say. `speech_only` has a
        noise that was written down as a word left out (see speech.py)."""
        header = {"kind": kind, "awake": bool(awake), "prompt": prompt, "model": model,
                  "otherwise": list(otherwise), "quick": bool(quick), "exact": bool(exact),
                  "sure": bool(sure), "speech_only": bool(speech_only)}
        return self._send("POST", "/hear", pack(header, to_pcm(audio)))

    def _send(self, method: str, path: str, body: bytes) -> dict:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=CONNECT_SECONDS)
        try:
            connection.connect()
            connection.sock.settimeout(ANSWER_SECONDS)
            connection.request(method, path, body=body or None,
                               headers={AUTH: sign(self.key, method, path, body),
                                        "Content-Type": "application/octet-stream"})
            reply = connection.getresponse()
            data = reply.read()
        except (OSError, http.client.HTTPException) as e:
            raise RemoteError("The other computer can't be reached.") from e
        finally:
            connection.close()
        if reply.status == 403:
            raise RemoteError("The other computer says the key doesn't match.")
        try:
            answer = json.loads(data.decode("utf-8"))
        except ValueError as e:
            raise RemoteError("Something else is answering at that address.") from e
        if not isinstance(answer, dict) or not answer.get("ok"):
            why = answer.get("why", "") if isinstance(answer, dict) else ""
            raise RemoteError(f"The other computer couldn't do it: {why or reply.status}.")
        return answer


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

    def transcribe(self, audio, awake: bool, prompt: str = "", exact: bool = False) -> str:
        too_long = not awake and len(audio) > config.WAKE_MAX_SECONDS * config.RATE
        if (awake or self.wake) and not too_long:
            reply = self._ask("phrase", audio, awake, prompt, exact)
            if reply is not None:
                self.not_speech = float(reply.get("not_speech", 0.0))
                self.ignored = str(reply.get("ignored", ""))
                return str(reply.get("text", ""))
        local = self._local()
        text = local.transcribe(audio, awake, prompt, **({"exact": True} if exact else {}))
        self.not_speech = getattr(local, "not_speech", 0.0)
        self.ignored = getattr(local, "ignored", "")
        return text

    def hear_alone(self, audio) -> str:
        reply = self._ask("alone", audio, True, "")
        if reply is not None:
            return str(reply.get("text", ""))
        return self._local().hear_alone(audio)

    def _ask(self, kind: str, audio, awake: bool, prompt: str, exact: bool = False):
        if self._clock() < self._down_until:
            return None
        try:
            reply = self.client.hear(kind, audio, awake, prompt, self.model, self.otherwise,
                                     self.quick, exact, speech_only=self.speech_only)
        except RemoteError as e:
            self._down_until = self._clock() + RETRY_SECONDS
            self._note(False, str(e))
            return None
        self.model_there = str(reply.get("model", ""))
        self._note(True, "")
        return reply

    def _note(self, there: bool, problem: str) -> None:
        if there != self.there or problem != self.problem:
            self.there, self.problem = there, problem
            self.on_where(there, problem)
