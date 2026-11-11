import json
import threading
import unittest
import urllib.error
import urllib.request

from dictation.mailbridge import MailBridge

PORT = 47698


def post(body, origin="moz-extension://test"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/poll", data=json.dumps(body).encode(),
        headers={"Origin": origin} if origin else {}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


class FakeAddon(threading.Thread):
    """Polls like the add-on does and answers each request with an echo."""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        replies = []
        while self.running:
            try:
                got = post({"replies": replies})
            except OSError:
                return
            replies = []
            if got.get("id"):
                replies.append({"id": got["id"], "reply": {"ok": True, "echo": got["message"]}})


class Bridge(unittest.TestCase):
    def setUp(self):
        self.bridge = MailBridge(PORT)
        self.assertTrue(self.bridge.start())

    def tearDown(self):
        self.bridge.stop()

    def test_not_connected_until_the_addon_polls(self):
        self.assertFalse(self.bridge.connected())
        self.assertEqual(self.bridge.request({"op": "status"})["why"], "mail not running")

    def test_round_trip(self):
        addon = FakeAddon()
        addon.start()
        for _ in range(50):
            if self.bridge.connected():
                break
            threading.Event().wait(0.05)
        for n in range(3):
            reply = self.bridge.request({"op": "context", "n": n})
            self.assertEqual(reply, {"ok": True, "echo": {"op": "context", "n": n}})
        addon.running = False

    def test_web_pages_are_refused(self):
        for origin in ("https://example.com", "null"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                post({"replies": []}, origin=origin)
            self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.bridge.connected())

    def test_second_engine_on_the_same_port_is_refused(self):
        self.assertFalse(MailBridge(PORT).start())


if __name__ == "__main__":
    unittest.main()
