import json
import os
import socket
import tempfile
import threading
import unittest

from dictation.vscode_target import VSCodeTarget


class FakeWindow(threading.Thread):
    """Stands in for one VS Code window's extension."""

    def __init__(self, folder, name, ready):
        super().__init__(daemon=True)
        self.path = os.path.join(folder, f"linux-speaking-vscode-{name}.sock")
        self.ready = ready
        self.seen = []
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(4)
        self.start()

    def run(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                message = json.loads(conn.makefile().readline())
                self.seen.append(message)
                if message["op"] == "status":
                    reply = {"ok": True, "ready": self.ready}
                else:
                    reply = {"ok": True, "from": os.path.basename(self.path)}
                conn.sendall((json.dumps(reply) + "\n").encode())

    def close(self):
        self.server.close()


class Windows(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.target = VSCodeTarget(self.folder)

    def test_no_windows(self):
        self.assertEqual(self.target.request({"op": "status"}), {"ok": True, "ready": False})
        self.assertEqual(self.target.request({"op": "context"})["why"], "editor not focused")

    def test_requests_go_to_the_window_in_front(self):
        back, front = FakeWindow(self.folder, "1", False), FakeWindow(self.folder, "2", True)
        self.assertTrue(self.target.request({"op": "status"})["ready"])
        reply = self.target.request({"op": "insert", "text": "hello"})
        self.assertEqual(reply["from"], "linux-speaking-vscode-2.sock")
        self.assertEqual([m["op"] for m in back.seen], ["status"])
        back.close()
        front.close()

    def test_none_in_front(self):
        window = FakeWindow(self.folder, "1", False)
        self.assertFalse(self.target.request({"op": "status"})["ready"])
        self.assertEqual(self.target.request({"op": "context"})["why"], "editor not focused")
        window.close()

    def test_a_closed_window_is_forgotten(self):
        stale = os.path.join(self.folder, "linux-speaking-vscode-9.sock")
        dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        dead.bind(stale)
        dead.close()  # the file stays, but nothing is listening
        self.assertFalse(self.target.request({"op": "status"})["ready"])
        self.assertFalse(os.path.exists(stale))

    def test_broadcast_reaches_every_window(self):
        a, b = FakeWindow(self.folder, "1", False), FakeWindow(self.folder, "2", False)
        self.target.broadcast({"op": "command", "name": "cancel_choices"})
        self.assertEqual((len(a.seen), len(b.seen)), (1, 1))
        a.close()
        b.close()


if __name__ == "__main__":
    unittest.main()
