"""The engine's side of the link to the Thunderbird add-on.

The add-on can't be reached from outside, so it calls us: it keeps one HTTP request
open to this server (a "long poll"), we answer it with the next thing to do, and it
sends the result back with its next request. Only this computer can connect.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

POLL_SECONDS = 20      # how long an idle poll is held open
ALIVE_SECONDS = 30     # no poll for this long means Thunderbird isn't there


class MailBridge:
    def __init__(self, port: int):
        self.port = port
        self._requests: queue.Queue = queue.Queue()
        self._waiting: dict = {}  # request id -> event
        self._replies: dict = {}  # request id -> reply
        self._lock = threading.Lock()
        self._next_id = 0
        self._last_poll = 0.0
        self._server = None

    def start(self) -> bool:
        """Start listening. False if the port is taken (another engine is running)."""
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                # Web pages must not be able to talk to this, and a browser always
                # names the page a request like this comes from. Only an add-on may.
                origin = self.headers.get("Origin")
                if self.path != "/poll" or (
                        origin is not None and not origin.startswith("moz-extension://")):
                    self.send_response(403)
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                data = json.dumps(bridge._poll(body.get("replies", []))).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError:
            return False
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _poll(self, replies: list) -> dict:
        if not self.connected():
            print("Thunderbird add-on connected", flush=True)
        self._last_poll = time.monotonic()
        with self._lock:
            for item in replies:
                event = self._waiting.pop(item.get("id"), None)
                if event:
                    self._replies[item.get("id")] = item.get("reply") or {
                        "ok": False, "why": "no reply"}
                    event.set()
        try:
            request_id, message = self._requests.get(timeout=POLL_SECONDS)
        except queue.Empty:
            return {}
        finally:
            self._last_poll = time.monotonic()
        return {"id": request_id, "message": message}

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
