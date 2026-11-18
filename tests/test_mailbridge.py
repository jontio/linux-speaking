import contextlib
import io
import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import secrets

from dictation import mailbridge
from dictation.mailbridge import MailBridge, own_key, prove

PORT = 47698


def post(body, origin="moz-extension://test"):
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/poll", data=json.dumps(body).encode(),
        headers={"Origin": origin} if origin else {}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


KEY = "5" * 64


class Addon:
    """One add-on's side of the talk with the engine, as background.js holds it."""

    def __init__(self, key=KEY):
        self.key, self.turn, self.sent = key, "", None

    def ask(self, replies=()):
        """One exchange. What the engine wants done ({} if nothing), or None if the answer
        didn't prove it came from an engine that holds the key."""
        nonce = secrets.token_hex(16)
        body = {"nonce": nonce}
        if self.turn:
            body["turn"] = self.turn
            body["payload"] = json.dumps({"replies": list(replies)})
            body["auth"] = prove(self.key, "poll", self.turn, nonce, body["payload"])
        self.sent = body
        answer = post(body)
        proved = answer.get("auth") == prove(self.key, "next", nonce, answer.get("turn", ""),
                                             answer.get("payload", ""))
        self.turn = answer.get("turn", "") if proved else ""
        return json.loads(answer["payload"]) if proved else None


class FakeAddon(threading.Thread):
    """Polls like the add-on does and answers each request with an echo."""

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        addon, replies = Addon(), []
        while self.running:
            try:
                got = addon.ask(replies)
            except OSError:
                return
            replies = []
            if got and got.get("id"):
                replies.append({"id": got["id"], "reply": {"ok": True, "echo": got["message"]}})


class Bridge(unittest.TestCase):
    def setUp(self):
        self.bridge = MailBridge(PORT, KEY)
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
                post({"nonce": "1" * 32}, origin=origin)
            self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.bridge.connected())

    def test_nothing_it_answers_is_to_be_kept_in_a_cache(self):
        # Whatever the answer, and whoever asked: Thunderbird stores every answer on the
        # disk unless it is told not to.
        asked = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/poll", data=json.dumps({"nonce": "1" * 32}).encode(),
            headers={"Origin": "moz-extension://test"}, method="POST")
        with urllib.request.urlopen(asked, timeout=30) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post({"nonce": "1" * 32}, origin="https://example.com")
        self.assertEqual(caught.exception.headers["Cache-Control"], "no-store")
        caught.exception.close()

    def test_second_engine_on_the_same_port_is_refused(self):
        self.assertFalse(MailBridge(PORT, KEY).start())


class Proving(unittest.TestCase):
    """Each end shows the other that it holds this computer's key."""

    def setUp(self):
        self.bridge = MailBridge(PORT, KEY)
        self.assertTrue(self.bridge.start())
        self.addCleanup(self.bridge.stop)

    def waiting(self, message):
        """Have the engine want something done, as when a phrase has been said."""
        self.bridge._last_poll = __import__("time").monotonic()
        threading.Thread(target=lambda: self.bridge.request(message, timeout=3), daemon=True).start()
        for _ in range(100):
            if not self.bridge._requests.empty():
                return
            threading.Event().wait(0.01)

    def test_the_first_answer_proves_the_engine_and_tells_nothing(self):
        self.waiting({"op": "insert", "text": "private words"})
        addon = Addon()
        self.assertEqual(addon.ask(), {})                    # proved, and nothing to do yet
        self.assertFalse(self.bridge._requests.empty())      # the words are still waiting
        self.assertEqual(addon.ask()["message"], {"op": "insert", "text": "private words"})

    def test_a_stranger_asking_is_given_nothing_to_do(self):
        self.waiting({"op": "insert", "text": "private words"})
        seen = self.bridge._last_poll
        for stranger in (Addon("6" * 64), Addon("")):
            self.assertIsNone(stranger.ask())                # it can't even tell who answered
            stranger.turn = "0" * 32
            stranger.ask()
            self.assertFalse(self.bridge._requests.empty())
        self.assertEqual(self.bridge._last_poll, seen)       # nor does it count as Thunderbird being there

    def test_a_request_cannot_be_sent_a_second_time(self):
        addon = Addon()
        addon.ask()
        self.waiting({"op": "context"})
        self.assertEqual(addon.ask()["message"], {"op": "context"})
        overheard = addon.sent
        self.waiting({"op": "insert", "text": "private words"})
        again = post(overheard)
        self.assertEqual(json.loads(again["payload"]), {})   # nothing told the second time
        self.assertFalse(self.bridge._requests.empty())

    def test_an_addon_from_before_the_key_is_noticed_and_told_nothing(self):
        self.short(POLL_SECONDS=0.1)
        self.waiting({"op": "insert", "text": "private words"})
        self.assertEqual(post({"replies": []}), {})
        self.assertTrue(self.bridge.outdated)
        self.assertFalse(self.bridge._requests.empty())

    def short(self, **limits):
        for name, value in limits.items():
            patch = mock.patch.object(mailbridge, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_it_is_kept_waiting_as_an_idle_poll_is_and_the_person_is_told_what_to_do(self):
        # That add-on asks again the moment it is answered: answered at once, it and the
        # engine would do nothing else.
        self.short(POLL_SECONDS=1.0)
        self.assertEqual(self.bridge.problem, "")
        began, answers = time.monotonic(), []
        first = threading.Thread(target=lambda: answers.append(post({"replies": []})), daemon=True)
        first.start()
        for _ in range(100):
            if self.bridge._holding.locked():
                break
            time.sleep(0.01)
        # Only one is kept waiting. Another meanwhile gets no answer at all, which that
        # add-on takes for the engine not being there: it then waits a while itself.
        with self.assertRaises(urllib.error.HTTPError) as caught:
            post({"replies": []})
        self.assertEqual(caught.exception.code, 503)
        self.assertEqual(answers, [])                        # at once: the first is still waiting
        first.join(5)
        self.assertEqual(answers, [{}])
        self.assertGreaterEqual(time.monotonic() - began, 0.95)
        problem = self.bridge.problem
        self.assertIn("Thunderbird's add-on is an older one. Add it again", problem)
        self.assertIn("Install Add-on From File", problem)
        self.assertIn("linux-speaking-thunderbird.xpi", problem)
        addon = Addon()                                      # the new one is added, and asks
        addon.ask()
        self.short(POLL_SECONDS=0.05)
        addon.ask()
        self.assertEqual(self.bridge.problem, "")

    def test_a_stranger_asking_does_not_take_the_addons_turn_from_it(self):
        addon = Addon()
        self.assertEqual(addon.ask(), {})
        self.waiting({"op": "insert", "text": "private words"})
        for stranger in ({"nonce": secrets.token_hex(16)},
                         {"nonce": secrets.token_hex(16), "turn": addon.turn, "payload": "{}", "auth": "0" * 64},
                         {"nonce": secrets.token_hex(16), "turn": "f" * 32, "payload": "{}", "auth": ""}):
            self.assertEqual(json.loads(post(stranger)["payload"]), {})
        # The add-on's own next request is still taken, and is given the words.
        self.assertEqual(addon.ask()["message"], {"op": "insert", "text": "private words"})

    def test_odd_values_from_a_stranger_are_refused_and_nothing_is_signed_for_them(self):
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            for odd in ({"nonce": "a", "turn": "é"}, {"nonce": "zzz"}, {"nonce": "1" * 31},
                        {"nonce": "x" * 100_000}, {"nonce": 7}, {"nonce": ["1" * 32]}):
                with self.assertRaises(urllib.error.HTTPError, msg=odd) as caught:
                    post(odd)
                self.assertEqual(caught.exception.code, 400)
                caught.exception.close()   # or a newer Python warns, on the way out, that nobody did
            # Half a letter by itself, an answer that is no text, a turn that is no number.
            for odd in ({"payload": "\ud800"}, {"payload": 7, "auth": [1]}, {"turn": "é" * 32},
                        {"turn": {"a": 1}}, {"auth": "\ud800é"}):
                asked = {"nonce": secrets.token_hex(16), "turn": "1" * 32, "payload": "{}", "auth": "x", **odd}
                self.assertEqual(json.loads(post(asked)["payload"]), {}, odd)
            self.assertEqual(Addon().ask(), {})              # and it goes on answering
        self.assertEqual(said.getvalue(), "")                # with nothing raised on the way

    def test_an_addon_made_for_another_key_is_noticed(self):
        self.assertEqual(self.bridge.problem, "")
        other, said = Addon("6" * 64), io.StringIO()
        with contextlib.redirect_stdout(said):
            for _ in range(mailbridge.UNPROVED + 2):         # it can't check the answer, and starts again
                self.assertIsNone(other.ask())
        self.assertIn("another key", self.bridge.problem)
        self.assertIn("Install Add-on From File", self.bridge.problem)
        self.assertEqual(said.getvalue().count("without this computer's key"), 1)   # said once
        addon = Addon()                                      # the right one: nothing is wrong any more
        addon.ask()
        self.short(POLL_SECONDS=0.05)
        addon.ask()
        self.assertEqual(self.bridge.problem, "")
        addon.ask()
        Addon().ask()                                        # one that starts, as after Thunderbird is restarted
        self.bridge._last_poll = float("-inf")
        self.assertEqual(self.bridge.problem, "")            # is no run of strangers

    def test_a_caller_has_one_allowance_of_time_however_slowly_it_sends(self):
        self.short(READ_SECONDS=0.5)
        caller = socket.create_connection(("127.0.0.1", PORT), timeout=5)
        self.addCleanup(caller.close)
        began, hung_up = time.monotonic(), None
        try:
            for _ in range(40):           # a byte now and then: each one in good time, by itself
                caller.sendall(b"X")
                caller.settimeout(0.1)
                try:
                    if caller.recv(1) == b"":
                        hung_up = time.monotonic() - began
                        break
                except socket.timeout:
                    pass
        except OSError:
            hung_up = time.monotonic() - began
        self.assertIsNotNone(hung_up)
        self.assertLess(hung_up, 2.5)

    def test_only_so_many_callers_are_attended_to_at_once(self):
        self.short(MOST_CALLERS=2, READ_SECONDS=1.5)
        idle = [socket.create_connection(("127.0.0.1", PORT), timeout=5) for _ in range(6)]
        for caller in idle:
            self.addCleanup(caller.close)

        def hung_up_on() -> int:
            count = 0
            for caller in idle:
                caller.settimeout(0.01)
                try:
                    count += caller.recv(1, socket.MSG_PEEK) == b""
                except socket.timeout:
                    pass                  # still being attended to
                except OSError:
                    count += 1
            return count

        began = time.monotonic()
        while hung_up_on() != 4 and time.monotonic() - began < 1.0:
            time.sleep(0.02)
        self.assertEqual(hung_up_on(), 4)                    # the rest, unheard, and at once
        self.assertLess(time.monotonic() - began, 1.0)
        while hung_up_on() != 6 and time.monotonic() - began < 4.0:
            time.sleep(0.05)              # when those two have had their time, there is room again
        self.assertEqual(Addon().ask(), {})
        if os.name != "nt":
            self.assertTrue(self.bridge._server.allow_reuse_address)
        else:                             # there, it would let another program share the port
            self.assertFalse(self.bridge._server.allow_reuse_address)

    def test_too_much_is_refused_unread(self):
        request = urllib.request.Request(f"http://127.0.0.1:{PORT}/poll", data=b"x", method="POST",
                                         headers={"Content-Length": str(2 * 1024 * 1024)})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 413)

    def test_the_key_is_made_once_and_kept_to_its_owner(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "sub", "mail-key")
        key = own_key(path)
        self.assertEqual((len(key), own_key(path)), (64, key))
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o077, 0)
        self.assertEqual(own_key(os.path.join(os.devnull, "nowhere", "mail-key")), "")

    def test_a_key_written_by_hand_is_read_as_the_installer_reads_it(self):
        import subprocess
        import tempfile
        written = "AB12 cd34-EF56:7890 abcdef0123456789ABCDEF, my own\n"
        path = os.path.join(tempfile.mkdtemp(), "mail-key")
        with open(path, "w") as f:
            f.write(written)
        self.assertEqual(own_key(path), "ab12cd34ef567890abcdef0123456789abcdef")
        with open(path) as f:
            self.assertEqual(f.read(), written)               # and the file is left as it was
        # What scripts/build-xpi.sh does with the file, to the letter.
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "scripts", "build-xpi.sh")
        with open(script) as f:
            line = next(line for line in f if line.startswith('key="$('))
        self.assertIn("""tr 'A-F' 'a-f' < "$key_file" | tr -cd '0-9a-f'""", line)
        if os.name != "nt":
            made = subprocess.run(["sh", "-c", "tr 'A-F' 'a-f' < \"$1\" | tr -cd '0-9a-f'", "sh", path],
                                  capture_output=True, text=True).stdout
            self.assertEqual(made, own_key(path))


class GivenUpOn(unittest.TestCase):
    """A request nobody waited out is not carried out when the add-on next asks."""

    def setUp(self):
        self.bridge = MailBridge(PORT, KEY)
        self.assertTrue(self.bridge.start())
        self.addCleanup(self.bridge.stop)

    def test_it_is_not_handed_over_late(self):
        self.bridge._last_poll = __import__("time").monotonic()      # as if the add-on had just asked
        self.assertEqual(self.bridge.request({"op": "insert", "text": "late"}, timeout=0.05)["why"],
                         "mail not answering")
        answers, addon = [], Addon()
        addon.ask()
        asking = threading.Thread(target=lambda: answers.append(addon.ask()), daemon=True)
        asking.start()
        reply = {}
        waiting = threading.Thread(
            target=lambda: reply.update(self.bridge.request({"op": "status"}, timeout=5)), daemon=True)
        waiting.start()
        asking.join(10)
        self.assertEqual(answers[0]["message"], {"op": "status"})    # not the insert given up on


if __name__ == "__main__":
    unittest.main()
