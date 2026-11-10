"""A socket server inside LibreOffice. Requests are run on LibreOffice's main thread."""
import json
import os
import socket
import threading
import traceback

import unohelper
from com.sun.star.awt import XCallback

import ls_ops

_started = False
_lock = threading.Lock()


def socket_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    return os.environ.get("LINUX_SPEAKING_SOCKET") or os.path.join(base, "linux-speaking.sock")


class _Call(unohelper.Base, XCallback):
    """Runs one request on the main thread and hands the reply back."""

    def __init__(self, ops, message):
        self.ops = ops
        self.message = message
        self.reply = None
        self.done = threading.Event()

    def notify(self, data):
        try:
            self.reply = self.ops.handle(self.message)
        except Exception as e:
            self.reply = {"ok": False, "why": "error", "error": str(e),
                          "trace": traceback.format_exc()}
        self.done.set()


def _serve(ctx, server):
    smgr = ctx.ServiceManager
    poster = smgr.createInstanceWithContext("com.sun.star.awt.AsyncCallback", ctx)
    ops = ls_ops.Ops(ctx)
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            with conn:
                conn.settimeout(5)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                try:
                    message = json.loads(data.decode("utf-8"))
                    call = _Call(ops, message)
                    poster.addCallback(call, None)
                    if call.done.wait(5):
                        reply = call.reply
                    else:
                        reply = {"ok": False, "why": "writer busy"}
                except ValueError:
                    reply = {"ok": False, "why": "bad request"}
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        except Exception:
            pass


def start(ctx):
    global _started
    with _lock:
        if _started:
            return
        path = socket_path()
        try:
            os.unlink(path)
        except OSError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(4)
        threading.Thread(target=_serve, args=(ctx, server), daemon=True).start()
        _started = True
