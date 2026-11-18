import contextlib
import http.client
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

try:
    import cryptography  # noqa: F401
except ImportError:  # what is sent to the other computer is encrypted with it
    raise unittest.SkipTest("the tests of the link to another computer need the cryptography package")

from dictation import config, remote
from dictation.settings import Settings

KEY = "0123456789abcdef0123456789abcdef"


def ask(port, method, path, body=b"", key=KEY, turn=None, nonce=None, auth=None, hello=True,
        run=None, sealed=None, first=None):
    """One request made by hand, as a computer that holds `key` would make it. Returns
    (status, the reply's headers, what it said, the turn and nonce that were used). What
    was last sent and got is kept on the function, for a test to look at or send again:
    ask.run (the run's key), ask.sealed (the request's body as it travelled) and ask.raw
    (the reply's). `auth` and `first` stand in for the proof over the whole request and
    for the one that comes ahead of its body."""
    def send(method, path, body, headers):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(method, path, body=body or None, headers=headers)
        answer = connection.getresponse()
        data = answer.read()
        connection.close()
        return answer.status, answer.headers, data

    if turn is None and hello:
        private, mine = remote.half()
        greeting = remote.number()
        said = json.loads(send("GET", "/hello", b"", {remote.NONCE: greeting, remote.KEY: mine})[2])
        turn, run = said["turn"], remote.agreed(private, said["key"], greeting, mine, said["key"])
    run = run or b"\0" * 32
    nonce = remote.number() if nonce is None else nonce
    if sealed is None:
        sealed = remote.seal(run, "request", turn or "", nonce, body, f"{method} {path}") if body else b""
    headers = {remote.NONCE: nonce,
               remote.AUTH: auth or remote.sign(key, method, path, sealed, turn or "", nonce)}
    if first is not False:                                     # False: as one from before it had one
        headers[remote.ASK] = (remote.ask(key, method, path, len(sealed), turn or "", nonce)
                               if first is None else first)
    if turn:
        headers[remote.TURN] = turn
    status, got, data = send(method, path, sealed, headers)
    ask.run, ask.sealed, ask.raw = run, sealed, data
    if got.get(remote.NEXT):                                   # a reply that was sealed
        data = remote.unseal(run, "reply", turn, nonce, data, f"reply {status}")
    return status, got, json.loads(data), turn, nonce


class Recogniser:
    """Stands in for Whisper on the computer that shares."""

    def __init__(self):
        self.asked = []
        self.fail = False

    def hear(self, header, audio):
        if self.fail:
            raise RuntimeError("model fell over")
        self.asked.append((header, len(audio), float(np.max(np.abs(audio))) if len(audio) else 0.0))
        return {"ok": True, "text": f"{header['kind']} of {len(audio)}", "model": header.get("model") or "own",
                "not_speech": 0.25, "ignored": ""}

    def describe(self):
        return {"version": "9.9", "models": [["small.en", "Small"], ["medium.en", "Medium"]],
                "model": "small.en"}


class OverTheNetwork(unittest.TestCase):
    def setUp(self):
        self.recogniser = Recogniser()
        self.server = remote.Server("127.0.0.1", 0, KEY, self.recogniser.hear, self.recogniser.describe)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.address = f"127.0.0.1:{self.server.port}"

    def test_status(self):
        answer = remote.Client(self.address, KEY).status()
        self.assertEqual(answer["models"], [["small.en", "Small"], ["medium.en", "Medium"]])
        self.assertEqual(answer["model"], "small.en")

    def test_a_phrase_goes_there_and_the_words_come_back(self):
        audio = np.linspace(-0.5, 0.5, 16000, dtype=np.float32)
        answer = remote.Client(self.address, KEY).hear(
            "phrase", audio, True, "Dear Sam,\n“Thanks”", "medium.en", ["small.en"])
        self.assertEqual(answer["text"], "phrase of 16000")
        header, length, peak = self.recogniser.asked[0]
        self.assertEqual(header, {"kind": "phrase", "awake": True, "prompt": "Dear Sam,\n“Thanks”",
                                  "model": "medium.en", "otherwise": ["small.en"], "quick": False,
                                  "exact": False, "sure": False, "speech_only": True})
        self.assertEqual(length, 16000)
        self.assertAlmostEqual(peak, 0.5, places=3)

    def test_a_voice_test_asks_how_sure_it_was(self):
        audio = np.zeros(1600, dtype=np.float32)
        remote.Client(self.address, KEY).hear("phrase", audio, True, "", "small.en", sure=True)
        self.assertIs(self.recogniser.asked[0][0]["sure"], True)

    def test_a_wrong_key_is_refused_and_nothing_is_done(self):
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.address, "f" * 32).hear("phrase", np.zeros(100, dtype=np.float32), True)
        self.assertIn("key", str(raised.exception))
        with self.assertRaises(remote.RemoteError):
            remote.Client(self.address, "").status()
        self.assertEqual(self.recogniser.asked, [])

    def test_a_signature_for_one_request_does_not_open_another(self):
        body = remote.pack({"kind": "phrase"}, b"\0\0")
        turn = ask(self.server.port, "GET", "/hello")[3]
        nonce = remote.number()
        status = ask(self.server.port, "POST", "/hear", body, turn=turn, nonce=nonce,
                     auth=remote.sign(KEY, "GET", "/status", b"", turn, nonce))[0]
        self.assertEqual(status, 403)
        self.assertEqual(self.recogniser.asked, [])

    def test_a_request_cannot_be_sent_a_second_time(self):
        body = remote.pack({"kind": "phrase"}, b"\0\0")
        status, _, said, turn, nonce = ask(self.server.port, "POST", "/hear", body)
        self.assertEqual((status, said["ok"]), (200, True))
        again = ask(self.server.port, "POST", "/hear", turn=turn, nonce=nonce, sealed=ask.sealed)
        self.assertEqual(again[0], 401)                        # overheard and sent again
        self.assertEqual(len(self.recogniser.asked), 1)

    def test_what_travels_cannot_be_read(self):
        words = "Dear Sam, the private words before the cursor"
        body = remote.pack({"kind": "phrase", "prompt": words}, b"\x01\x02" * 800)
        status, _, said, _, _ = ask(self.server.port, "POST", "/hear", body)
        self.assertEqual((status, said["text"]), (200, "phrase of 800"))
        for travelled in (ask.sealed, ask.raw):
            self.assertNotIn(b"private", travelled)
            self.assertNotIn(b"phrase", travelled)
            self.assertNotIn(b"\x01\x02\x01\x02", travelled)
        self.assertEqual(self.recogniser.asked[0][0]["prompt"], words)      # and arrives whole

    def test_a_request_that_was_changed_on_the_way_is_not_done(self):
        body = remote.pack({"kind": "phrase"}, b"\0\0")
        turn = ask(self.server.port, "GET", "/hello")[3]
        run, nonce = ask.run, remote.number()
        sealed = bytearray(remote.seal(run, "request", turn, nonce, body, "POST /hear"))
        sealed[5] ^= 1
        # Even signed by someone who holds the key, it doesn't open.
        status = ask(self.server.port, "POST", "/hear", turn=turn, nonce=nonce, run=run,
                     sealed=bytes(sealed))[0]
        self.assertEqual((status, self.recogniser.asked), (400, []))

    def test_without_a_turn_nothing_is_done_even_with_the_key(self):
        body = remote.pack({"kind": "phrase"}, b"\0\0")
        self.assertEqual(ask(self.server.port, "POST", "/hear", body, hello=False)[0], 401)
        self.assertEqual(ask(self.server.port, "POST", "/hear", body, turn=remote.number())[0], 401)
        self.assertEqual(self.recogniser.asked, [])

    def test_the_reply_is_signed_and_brings_the_next_turn(self):
        status, headers, said, turn, nonce = ask(self.server.port, "GET", "/status")
        following, run = headers[remote.NEXT], ask.run
        self.assertEqual(headers[remote.AUTH],
                         remote.prove(KEY, "reply 200", turn, nonce, following, body=ask.raw))
        self.assertEqual(ask(self.server.port, "GET", "/status", turn=following, run=run)[0], 200)

    def test_one_hello_does_for_a_run_of_requests(self):
        client, hellos = remote.Client(self.address, KEY), []
        real = client._hello
        client._hello = lambda: hellos.append(1) or real()
        for _ in range(3):
            client.status()
        self.assertEqual(len(hellos), 1)

    def test_a_turn_gone_stale_there_is_asked_for_again(self):
        client = remote.Client(self.address, KEY)
        client.status()
        self.server.turns = remote.Turns()                     # as after a restart there
        self.assertTrue(client.status()["ok"])

    def test_so_it_is_with_a_long_phrase_already_on_its_way(self):
        # The refusal comes before the sound is read: the asker, which sends the sound
        # with the request, has still to get as far as reading it, and ask again.
        client, hellos = remote.Client(self.address, KEY), []
        real = client._hello
        client._hello = lambda: hellos.append(1) or real()
        client.status()
        self.server.turns = remote.Turns()
        answer = client.hear("phrase", np.zeros(20 * 16000, dtype=np.float32), True)   # 640 kB
        self.assertEqual(answer["text"], "phrase of 320000")
        self.assertEqual((len(hellos), len(self.recogniser.asked)), (2, 1))

    def test_a_computer_from_before_the_turns_is_told_to_update(self):
        for path, headers in (("/status", {remote.AUTH: "0" * 64}),            # before the turns
                              ("/hello", {remote.NONCE: remote.number()})):    # before the sealing
            connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
            connection.request("GET", path, headers=headers)
            answer = connection.getresponse()
            self.assertEqual(answer.status, 400, path)
            self.assertIn("older Linux Speaking", json.loads(answer.read())["why"])
            connection.close()

    def test_too_big_is_refused_unread(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.putrequest("POST", "/hear")
        connection.putheader("Content-Length", str(remote.MAX_BODY + 1))
        connection.endheaders()
        self.assertEqual(connection.getresponse().status, 413)
        connection.close()

    def test_nonsense_is_refused(self):
        for method, path, body, expected in (("GET", "/elsewhere", b"", 404),
                                             ("POST", "/hear", b"\0\0\0\x09{}", 400),
                                             ("POST", "/hear", b"xx", 400)):
            self.assertEqual(ask(self.server.port, method, path, body)[0], expected, (method, path))

    def test_a_failure_there_is_reported_and_the_server_stays_up(self):
        self.recogniser.fail = True
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.address, KEY).hear("phrase", np.zeros(10, dtype=np.float32), True)
        self.assertIn("model fell over", str(raised.exception))
        self.recogniser.fail = False
        self.assertTrue(remote.Client(self.address, KEY).status()["ok"])

    def test_nobody_there(self):
        self.server.stop()
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.address, KEY).status()
        self.assertIn("can't be reached", str(raised.exception))

    def test_the_port_cannot_be_had_twice(self):
        again = remote.Server("127.0.0.1", self.server.port, KEY, self.recogniser.hear,
                              self.recogniser.describe)
        with self.assertRaises(OSError):
            again.start()
        self.assertFalse(again.running)

    def test_whatever_goes_wrong_in_the_asking_is_said_as_the_other_computer_not_doing_it(self):
        # Such as a "cryptography" package that is there, and built without what is used.
        with mock.patch.object(remote, "half", side_effect=RuntimeError("X25519 is not supported")):
            with self.assertRaises(remote.RemoteError):
                remote.Client(self.address, KEY).status()

    def test_a_name_that_is_slow_to_be_found_is_not_waited_on(self):
        asked = []

        def slow(host, *_, **more):       # stands in for the system's lookup: no name is really looked up
            if more.get("flags"):
                raise socket.gaierror("a name, not numbers")
            asked.append(host)
            time.sleep(1.5)
            raise socket.gaierror("no such name")

        with mock.patch.object(remote.socket, "getaddrinfo", slow), \
                mock.patch.object(remote, "CONNECT_SECONDS", 0.2):
            client, began = remote.Client("somewhere-else", KEY), time.monotonic()
            for _ in range(2):
                with self.assertRaises(remote.RemoteError) as raised:
                    client.status()
                self.assertIn("can't be reached", str(raised.exception))
            self.assertLess(time.monotonic() - began, 1.2)
            self.assertEqual(asked, ["somewhere-else"])        # the one still looking is waited on again


class Local:
    """This computer's own recogniser."""

    not_speech, ignored = 0.9, "bump"

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, awake, prompt=""):
        self.calls.append(("phrase", awake))
        return "heard here"

    def hear_alone(self, audio):
        self.calls.append(("alone", True))
        return "alone here"


class There:
    """The other computer, as the client sees it."""

    host = "elsewhere"

    def __init__(self):
        self.calls, self.down = [], False

    def hear(self, kind, audio, awake, prompt="", model="", otherwise=(), quick=False,
             exact=False, speech_only=True):
        self.quick_asked, self.exact_asked, self.speech_only_asked = quick, exact, speech_only
        self.calls.append((kind, awake, prompt, model, tuple(otherwise)))
        if self.down:
            raise remote.RemoteError("The other computer can't be reached.")
        return {"ok": True, "text": f"{kind} there", "model": "medium.en", "not_speech": 0.1, "ignored": ""}


class Offloading(unittest.TestCase):
    def setUp(self):
        self.local, self.there, self.now, self.moves = Local(), There(), [100.0], []
        self.offload = remote.Offload(
            lambda: self.local, self.there, "medium.en", ("small.en",),
            on_where=lambda there, problem: self.moves.append((there, problem)),
            clock=lambda: self.now[0])
        self.audio = np.zeros(16000, dtype=np.float32)

    def test_awake_phrases_go_there(self):
        self.assertEqual(self.offload.transcribe(self.audio, True, "before"), "phrase there")
        self.assertEqual(self.offload.hear_alone(self.audio), "alone there")
        self.assertEqual(self.there.calls[0], ("phrase", True, "before", "medium.en", ("small.en",)))
        self.assertEqual(self.local.calls, [])
        self.assertEqual(self.moves, [(True, "")])
        self.assertEqual(self.offload.model_there, "medium.en")

    def test_the_quick_way_is_asked_for_when_it_is_switched_on(self):
        self.offload.transcribe(self.audio, True)
        self.assertFalse(self.there.quick_asked)
        self.offload.quick = True
        self.offload.transcribe(self.audio, True)
        self.assertTrue(self.there.quick_asked)

    def test_listening_that_leans_on_the_prompt_says_so(self):
        self.offload.transcribe(self.audio, True, "letters", exact=True)
        self.assertTrue(self.there.exact_asked)
        self.offload.transcribe(self.audio, True, "prose")
        self.assertFalse(self.there.exact_asked)

    def test_the_other_computer_is_told_whether_to_leave_noises_out(self):
        self.offload.transcribe(self.audio, True)
        self.assertTrue(self.there.speech_only_asked)
        self.offload.speech_only = False
        self.offload.transcribe(self.audio, True)
        self.assertFalse(self.there.speech_only_asked)

    def test_asleep_stays_here_unless_asked(self):
        self.assertEqual(self.offload.transcribe(self.audio, False), "heard here")
        self.assertEqual((self.offload.not_speech, self.offload.ignored), (0.9, "bump"))
        self.assertEqual(self.there.calls, [])
        self.offload.wake = True
        self.assertEqual(self.offload.transcribe(self.audio, False), "phrase there")
        self.assertEqual(self.offload.not_speech, 0.1)

    def test_too_long_to_be_wake_up_is_never_sent(self):
        self.offload.wake = True
        long = np.zeros(int((config.WAKE_MAX_SECONDS + 1) * config.RATE), dtype=np.float32)
        self.assertEqual(self.offload.transcribe(long, False), "heard here")
        self.assertEqual(self.there.calls, [])

    def test_when_it_cannot_be_reached_this_computer_answers(self):
        self.there.down = True
        self.assertEqual(self.offload.transcribe(self.audio, True), "heard here")
        self.assertEqual(self.offload.hear_alone(self.audio), "alone here")
        self.assertEqual(len(self.there.calls), 1)  # the second didn't wait on it
        self.assertEqual(self.moves, [(False, "The other computer can't be reached.")])

    def test_it_is_tried_again_after_a_while(self):
        self.there.down = True
        self.offload.transcribe(self.audio, True)
        self.there.down = False
        self.now[0] += remote.RETRY_SECONDS - 1
        self.assertEqual(self.offload.transcribe(self.audio, True), "heard here")
        self.now[0] += 2
        self.assertEqual(self.offload.transcribe(self.audio, True), "phrase there")
        self.assertEqual([there for there, _ in self.moves], [False, True])

    def test_a_failure_of_any_other_kind_is_answered_here_too_and_no_phrase_lost(self):
        def broken(*_, **__):
            raise UnicodeError("encoding with 'idna' codec failed")

        self.there.hear = broken
        self.assertEqual(self.offload.transcribe(self.audio, True), "heard here")
        self.assertFalse(self.offload.there)
        self.assertIn("UnicodeError", self.offload.problem)
        self.there.hear = lambda *_, **__: self.fail("asked again before its time")
        self.assertEqual(self.offload.hear_alone(self.audio), "alone here")    # left alone for a while
        self.there.hear = lambda *_, **__: "not a set of values"
        self.now[0] += remote.RETRY_SECONDS + 1
        self.assertEqual(self.offload.transcribe(self.audio, True), "heard here")

    def test_an_odd_figure_beside_the_words_does_not_lose_them(self):
        for odd in ("high", None, [0.5], float("nan"), 7, -1):
            self.there.hear = lambda *_, **__: {"ok": True, "text": "the words", "not_speech": odd}
            self.assertEqual(self.offload.transcribe(self.audio, True), "the words", odd)
            self.assertEqual(self.offload.not_speech, 0.0, odd)


class Guests(unittest.TestCase):
    """The sharing computer's side: which model a guest gets."""

    def setUp(self):
        import threading
        from dictation import engine
        self.folder = tempfile.mkdtemp()
        for name in ("small.en", "base.en", "medium.en", "large-v3"):
            os.makedirs(os.path.join(self.folder, name))
            open(os.path.join(self.folder, name, "model.bin"), "w").close()
        self.old_dir, config.MODEL_DIR = config.MODEL_DIR, self.folder
        self.addCleanup(setattr, config, "MODEL_DIR", self.old_dir)
        heard = self.heard = []

        class Quiet(engine.Transcriber):
            def __init__(self):  # no real models
                self.lock = threading.RLock()
                self._loaded = {"small.en": object(), "base.en": object()}
                self._guests, self.wake_name, self.dictation_name = [], "small.en", "base.en"
                self.not_speech, self.ignored, self.quick = 0.7, "tap", False

            def _model(self, name):
                return self._loaded.setdefault(name, object())

            def _transcribe(self, audio, awake, prompt, model, quickly):
                self._model(model)
                heard.append((awake, prompt, model, quickly))
                return "words"

            def hear_alone(self, audio):
                return "alone"

        self.transcriber = Quiet()

    def test_the_model_asked_for_if_it_is_here(self):
        answer = self.transcriber.answer({"kind": "phrase", "awake": True, "prompt": "x", "model": "medium.en"}, [])
        self.assertEqual((answer["ok"], answer["text"], answer["model"]), (True, "words", "medium.en"))
        self.assertEqual(self.heard, [(True, "x", "medium.en", False)])

    def test_the_quick_way_is_the_guests_choice_not_this_computers(self):
        self.transcriber.quick = True
        self.transcriber.answer({"kind": "phrase", "model": "medium.en"}, [])
        self.transcriber.answer({"kind": "phrase", "model": "medium.en", "quick": True}, [])
        self.assertEqual([quickly for *_, quickly in self.heard], [False, True])

    def test_else_the_first_other_choice_that_is_here_else_its_own(self):
        ask = lambda **header: self.transcriber.answer({"kind": "phrase", **header}, [])["model"]
        self.assertEqual(ask(model="huge", otherwise=["nope", "large-v3", "medium.en"]), "large-v3")
        self.assertEqual(ask(model="", otherwise=[]), "base.en")
        self.assertEqual(ask(model="../../etc", otherwise="medium.en"), "base.en")
        self.assertEqual(ask(model=7, otherwise=[None, {"a": 1}]), "base.en")

    def test_three_models_are_kept_for_guests(self):
        for name in ("tiny.en", "distil-small.en"):
            os.makedirs(os.path.join(self.folder, name))
            open(os.path.join(self.folder, name, "model.bin"), "w").close()
        ask = lambda model: self.transcriber.answer({"kind": "phrase", "model": model}, [])
        for model in ("medium.en", "large-v3", "tiny.en", "medium.en"):
            ask(model)        # a guest asking for three in turn keeps all three
        self.assertEqual(sorted(self.transcriber._loaded),
                         ["base.en", "large-v3", "medium.en", "small.en", "tiny.en"])
        ask("distil-small.en")  # a fourth: the one used longest ago goes
        self.assertEqual(sorted(self.transcriber._loaded),
                         ["base.en", "distil-small.en", "medium.en", "small.en", "tiny.en"])
        ask("small.en")       # this computer's own: nothing is dropped for it
        self.assertEqual(sorted(self.transcriber._loaded),
                         ["base.en", "distil-small.en", "medium.en", "small.en", "tiny.en"])

    def test_a_transducer_takes_dictation_but_not_what_leans_on_the_prompt(self):
        os.makedirs(os.path.join(self.folder, "parakeet-x"))
        for name in ("encoder.int8.onnx", "tokens.txt"):
            open(os.path.join(self.folder, "parakeet-x", name), "w").close()
        asked = []
        self.transcriber._by_transducer = lambda name, audio, sure=False, speech_only=None: (
            asked.append(speech_only), f"by {name}")[1]
        ask = lambda **header: self.transcriber.answer({"kind": "phrase", "model": "parakeet-x", **header}, [])
        self.assertEqual(ask()["text"], "by parakeet-x")
        self.assertEqual(self.heard, [])
        ask(speech_only=False)   # a guest that wants noises left in says so
        ask(speech_only=True)
        self.assertEqual(asked, [None, False, True])  # one that doesn't say gets this computer's choice
        spelled = ask(exact=True)
        self.assertEqual((spelled["text"], spelled["model"]), ("words", "small.en"))  # Whisper
        self.assertEqual(self.heard[-1][2], "small.en")
        self.assertEqual(ask(awake=False)["model"], "small.en")  # "wake up": Whisper

    def test_asleep_uses_the_wake_model_and_says_how_sure_it_was(self):
        answer = self.transcriber.answer({"kind": "phrase", "awake": False, "model": "medium.en"}, [])
        self.assertEqual((answer["model"], answer["not_speech"], answer["ignored"]), ("small.en", 0.7, "tap"))

    def test_a_short_listen(self):
        answer = self.transcriber.answer({"kind": "alone"}, [])
        self.assertEqual((answer["text"], answer["model"]), ("alone", "small.en"))


class TextBefore(unittest.TestCase):
    def test_distil_models_are_shown_none(self):
        from dictation.engine import shown
        self.assertEqual(shown("small.en", "Dear Sam,"), "Dear Sam,")
        self.assertEqual(shown("large-v3-turbo", "Dear Sam,"), "Dear Sam,")
        for name in ("distil-medium.en", "distil-large-v3", "en_fasterwhisper_distil_small"):
            self.assertEqual(shown(name, "Dear Sam,"), "", name)


class Pieces(unittest.TestCase):
    def test_pack_and_unpack(self):
        header, sound = remote.unpack(remote.pack({"kind": "alone", "prompt": "é\n"}, b"\x01\x02"))
        self.assertEqual((header, sound), ({"kind": "alone", "prompt": "é\n"}, b"\x01\x02"))
        for bad in (b"", b"\0\0\0\xff{}", b"\0\0\0\x02[]", b"\0\0\0\x03{x}"):
            with self.assertRaises(ValueError):
                remote.unpack(bad)

    def test_sound_survives_the_journey(self):
        audio = np.array([0.0, 0.5, -0.5, 1.5, -1.5], dtype=np.float32)
        back = remote.from_pcm(remote.to_pcm(audio))
        np.testing.assert_allclose(back, [0.0, 0.5, -0.5, 1.0, -1.0], atol=1e-4)
        self.assertEqual(len(remote.from_pcm(b"\x01\x02\x03")), 1)

    def test_signature_depends_on_everything(self):
        one, two = "1" * 32, "2" * 32
        base = remote.sign(KEY, "POST", "/hear", b"abc", one, two)
        self.assertEqual(len(base), 64)
        for other in (remote.sign(KEY + "x", "POST", "/hear", b"abc", one, two),
                      remote.sign(KEY, "GET", "/hear", b"abc", one, two),
                      remote.sign(KEY, "POST", "/status", b"abc", one, two),
                      remote.sign(KEY, "POST", "/hear", b"abd", one, two),
                      remote.sign(KEY, "POST", "/hear", b"abc", two, two),
                      remote.sign(KEY, "POST", "/hear", b"abc", one, one),
                      remote.prove(KEY, "hello", one, two), remote.prove(KEY, "reply 200", one, two, body=b"abc")):
            self.assertNotEqual(base, other)

    def test_the_proof_ahead_of_the_body_depends_on_everything_too(self):
        one, two = "1" * 32, "2" * 32
        base = remote.ask(KEY, "POST", "/hear", 3, one, two)
        for other in (remote.ask(KEY + "x", "POST", "/hear", 3, one, two),
                      remote.ask(KEY, "GET", "/hear", 3, one, two),
                      remote.ask(KEY, "POST", "/status", 3, one, two),
                      remote.ask(KEY, "POST", "/hear", 4, one, two),
                      remote.ask(KEY, "POST", "/hear", 3, two, two),
                      remote.ask(KEY, "POST", "/hear", 3, one, one),
                      # And it can't pass for the proof over the whole request, nor that for it.
                      remote.sign(KEY, "POST", "/hear", b"3\n", one, two),
                      remote.sign(KEY, "ask", "POST /hear", b"3\n", one, two)):
            self.assertNotEqual(base, other)

    def test_a_turn_is_good_once_and_for_a_minute(self):
        now = [100.0]
        turns = remote.Turns(clock=lambda: now[0])
        first, second = turns.give(b"one run's key"), turns.give(b"another's")
        self.assertTrue(turns.good(first))
        self.assertEqual(turns.use(first), b"one run's key")
        self.assertIsNone(turns.use(first))
        self.assertIsNone(turns.use("f" * 32))
        now[0] += remote.TURN_SECONDS + 1
        self.assertIsNone(turns.use(second))

    def test_two_computers_agree_a_key_that_is_never_sent(self):
        mine, sent_mine = remote.half()
        theirs, sent_theirs = remote.half()
        nonce = remote.number()
        one = remote.agreed(mine, sent_theirs, nonce, sent_mine, sent_theirs)
        two = remote.agreed(theirs, sent_mine, nonce, sent_mine, sent_theirs)
        self.assertEqual((one, len(one)), (two, 32))
        self.assertNotIn(one.hex(), sent_mine + sent_theirs)
        other = remote.agreed(remote.half()[0], sent_theirs, nonce, sent_mine, sent_theirs)
        self.assertNotEqual(one, other)                        # someone else's half gives another key
        with self.assertRaises(ValueError):
            remote.agreed(mine, "not a half", nonce, sent_mine, sent_theirs)

    def test_what_is_sealed_opens_only_with_the_same_key_for_the_same_thing(self):
        run, turn, nonce = b"k" * 32, "1" * 32, "2" * 32
        sealed = remote.seal(run, "request", turn, nonce, b"the words", "POST /hear")
        self.assertNotIn(b"the words", sealed)
        self.assertEqual(remote.unseal(run, "request", turn, nonce, sealed, "POST /hear"), b"the words")
        for wrong in (dict(run=b"j" * 32), dict(what="reply"), dict(turn="3" * 32),
                      dict(nonce="3" * 32), dict(about="GET /status"),
                      dict(sealed=sealed[:-1] + bytes([sealed[-1] ^ 1]))):
            given = dict(run=run, what="request", turn=turn, nonce=nonce, sealed=sealed, about="POST /hear")
            given.update(wrong)
            with self.assertRaises(ValueError):
                remote.unseal(**given)
        # The same words in another request don't look the same.
        self.assertNotEqual(sealed, remote.seal(run, "request", "3" * 32, nonce, b"the words", "POST /hear"))

    def test_only_so_many_turns_are_kept_waiting(self):
        turns = remote.Turns()
        given = [turns.give() for _ in range(remote.MOST_TURNS + 5)]
        self.assertFalse(turns.good(given[0]))
        self.assertTrue(turns.good(given[-1]))
        self.assertEqual(len(turns._offered), remote.MOST_TURNS)

    def test_turns_given_at_hello_do_not_push_out_one_given_to_a_proven_caller(self):
        turns = remote.Turns()
        earned = turns.give(b"a real caller's", proven=True)
        for _ in range(remote.MOST_TURNS + 5):                 # anyone may say hello, as often as they like
            turns.give(b"a stranger's")
        self.assertTrue(turns.good(earned))
        self.assertEqual(turns.use(earned), b"a real caller's")
        self.assertIsNone(turns.use(earned))                   # and it is still good only once
        # Nor are those kept without end.
        given = [turns.give(b"k", proven=True) for _ in range(remote.MOST_TURNS + 5)]
        self.assertFalse(turns.good(given[0]))
        self.assertEqual(len(turns._earned), remote.MOST_TURNS)

    def test_addresses(self):
        self.assertEqual(remote.parse_address(" office-pc "), ("office-pc", config.SHARE_PORT))
        self.assertEqual(remote.parse_address("office-pc:5000"), ("office-pc", 5000))
        self.assertEqual(remote.parse_address("10.0.0.7:47614"), ("10.0.0.7", 47614))
        self.assertEqual(remote.parse_address("[fd00::1]:5000"), ("fd00::1", 5000))
        self.assertEqual(remote.parse_address("fd00::1"), ("fd00::1", config.SHARE_PORT))
        for bad in ("", ":5000", "office-pc:abc", "office-pc:0", "office-pc:70000"):
            with self.assertRaises(remote.RemoteError):
                remote.parse_address(bad)

    def test_what_could_not_be_an_address_is_refused_when_it_is_typed(self):
        # Each of these used to be taken, and then lost every phrase that was sent to it.
        for bad in ("office pc", "office..pc", ".office", "a" * 64, "office-pc:47614:1",
                    "http://office-pc:47614", "office/pc", "fd00::zz", "office\tpc", ".", "a." + "b" * 64):
            with self.assertRaises(remote.RemoteError, msg=bad):
                remote.parse_address(bad)
        for good, host in (("office-pc.", "office-pc."), ("office_pc.lan:5000", "office_pc.lan"),
                           ("büro", "büro"), ("[fe80::1%eth0]:5000", "fe80::1%eth0"),
                           ("a" * 63 + ".example", "a" * 63 + ".example")):
            self.assertEqual(remote.parse_address(good)[0], host)


class Saved(unittest.TestCase):
    def test_nothing_is_saved_until_set_up(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        settings = Settings.load(path)
        self.assertEqual(settings.remote, {"on": False, "address": "", "key": "", "model": "", "wake": False})
        self.assertEqual(settings.share, {"on": False, "key": ""})
        settings.set("scratch", False)
        with open(path) as f:
            saved = json.load(f)
        self.assertNotIn("remote", saved)
        self.assertNotIn("share", saved)

    def test_round_trip(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        settings = Settings.load(path)
        settings.set_remote(on=True, address=" office-pc:47614 ", key=KEY, wake=True)
        settings.set_share(on=True, key="abc")
        again = Settings.load(path)
        self.assertEqual(again.remote, {"on": True, "address": "office-pc:47614", "key": KEY,
                                        "model": "", "wake": True})
        self.assertEqual(again.share, {"on": True, "key": "abc"})

    def test_damaged_blocks_are_ignored(self):
        path = os.path.join(tempfile.mkdtemp(), "settings.json")
        with open(path, "w") as f:
            f.write('{"states": {}, "remote": "office-pc", "share": [1, 2]}')
        settings = Settings.load(path)
        self.assertFalse(settings.remote["on"])
        self.assertEqual(settings.share["key"], "")


class OddCallers(unittest.TestCase):
    def setUp(self):
        self.recogniser = Recogniser()
        self.server = remote.Server("127.0.0.1", 0, KEY, self.recogniser.hear, self.recogniser.describe)
        self.server.start()
        self.addCleanup(self.server.stop)

    def ask(self, auth):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.putrequest("GET", "/status")
        connection.putheader(remote.AUTH, auth)
        connection.endheaders()
        answer = connection.getresponse()
        return answer.status, answer.getheader("Server") or "", json.loads(answer.read())

    def test_a_key_with_odd_characters_in_it_is_simply_the_wrong_key(self):
        odd = "\u00e9\u00e8".encode("utf-8").decode("latin-1")
        status, _, said, _, _ = ask(self.server.port, "GET", "/status", auth=odd)
        self.assertEqual((status, said["why"]), (403, "wrong key"))

    def test_the_server_does_not_say_which_version_it_is(self):
        self.assertEqual(self.ask("x")[1].strip(), "LinuxSpeaking")


class Impostors(unittest.TestCase):
    """A computer that answers at the address without holding the key."""

    def serve(self, hello, hear=None):
        """Something answering at an address: `hello(nonce)` and `hear()` each give
        (status, what it says, headers). Returns its address and what was sent to it."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        got = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def answer(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                got.append((self.command, self.path, len(body)))
                status, said, headers = (hello(self.headers.get(remote.NONCE, ""),
                                               self.headers.get(remote.KEY, ""))
                                         if self.path == "/hello" else hear())
                data = json.dumps(said).encode()
                self.send_response(status)
                for name, value in dict(headers, **{"Content-Length": str(len(data))}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = answer

        server = HTTPServer(("127.0.0.1", 0), Handler)
        import threading
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"127.0.0.1:{server.server_address[1]}", got

    def hear(self, address):
        return remote.Client(address, KEY).hear("phrase", np.zeros(1600, dtype=np.float32), True, "private words")

    def test_it_is_found_out_before_it_is_sent_any_sound(self):
        half = remote.half()[1]
        address, got = self.serve(lambda nonce, theirs: (
            200, {"ok": True, "turn": "a" * 32, "key": half}, {remote.AUTH: "0" * 64}))
        with self.assertRaises(remote.RemoteError) as raised:
            self.hear(address)
        self.assertIn("key doesn't match", str(raised.exception))
        self.assertEqual(got, [("GET", "/hello", 0)])          # and nothing after it

    def test_words_that_are_not_signed_are_not_believed(self):
        # It has got past hello somehow (say it sits between the two computers), and
        # answers a phrase with words of its own.
        turn, half = "b" * 32, remote.half()[1]
        address, got = self.serve(
            lambda nonce, theirs: (200, {"ok": True, "turn": turn, "key": half, "speaks": remote.SPEAKS},
                                   {remote.AUTH: remote.prove(KEY, "hello", nonce, turn, theirs, half)}),
            lambda: (200, {"ok": True, "text": "select all delete that"}, {}))
        with self.assertRaises(remote.RemoteError) as raised:
            self.hear(address)
        self.assertIn("didn't come from a computer that holds the key", str(raised.exception))
        # And what it was sent it can't read: it is sealed with a key it never had a half of.
        self.assertEqual([what[:2] for what in got], [("GET", "/hello"), ("POST", "/hear")])

    def test_the_engine_then_does_the_listening_itself(self):
        address, _ = self.serve(lambda nonce, theirs: (200, {"ok": True, "turn": "a" * 32}, {}))

        class Local:
            not_speech, ignored = 0.0, ""

            def transcribe(self, audio, awake, prompt):
                return "heard here"

        offload = remote.Offload(Local, remote.Client(address, KEY))
        self.assertEqual(offload.transcribe(np.zeros(1600, dtype=np.float32), True), "heard here")
        self.assertFalse(offload.there)

    def test_one_from_before_the_turns_is_said_to_need_updating(self):
        address, _ = self.serve(lambda nonce, theirs: (403, {"ok": False, "why": "wrong key"}, {}))
        with self.assertRaises(remote.RemoteError) as raised:
            self.hear(address)
        self.assertIn("older Linux Speaking", str(raised.exception))

    def test_so_is_one_from_before_the_sealing_and_it_is_sent_nothing(self):
        turn = "c" * 32
        address, got = self.serve(lambda nonce, theirs: (
            200, {"ok": True, "turn": turn}, {remote.AUTH: remote.prove(KEY, "hello", nonce, turn)}))
        with self.assertRaises(remote.RemoteError) as raised:
            self.hear(address)
        self.assertIn("older Linux Speaking", str(raised.exception))
        self.assertEqual(got, [("GET", "/hello", 0)])

    def test_so_is_one_from_before_the_proof_ahead_of_the_body(self):
        # It holds the key and seals what it sends, but says no number for its way of
        # talking: it is one that anybody could stop, and is to be updated.
        turn, half = "d" * 32, remote.half()[1]
        address, got = self.serve(lambda nonce, theirs: (
            200, {"ok": True, "turn": turn, "key": half},
            {remote.AUTH: remote.prove(KEY, "hello", nonce, turn, theirs, half)}))
        with self.assertRaises(remote.RemoteError) as raised:
            self.hear(address)
        self.assertIn("has an older Linux Speaking: update it there", str(raised.exception))
        self.assertEqual(got, [("GET", "/hello", 0)])          # and it is sent nothing

    def test_a_later_one_is_believed_that_it_is_this_one_which_is_older(self):
        turn, half = "e" * 32, remote.half()[1]
        refusing = lambda nonce, theirs: (
            400, {"ok": False, "why": f"{remote.OLDER} is asking: update it on that computer"}, {})
        ahead = lambda nonce, theirs: (
            200, {"ok": True, "turn": turn, "key": half, "speaks": remote.SPEAKS + 1},
            {remote.AUTH: remote.prove(KEY, "hello", nonce, turn, theirs, half)})
        for hello in (refusing, ahead):
            address, got = self.serve(hello)
            with self.assertRaises(remote.RemoteError) as raised:
                self.hear(address)
            self.assertIn("this one has an older Linux Speaking: update it here", str(raised.exception))
            self.assertEqual(got, [("GET", "/hello", 0)])


class AnswersWithoutEnd(unittest.TestCase):
    """What answers at the address may not hold the key, and may not mean well: it is
    not waited on for ever, nor read for ever, before it is found out."""

    def answering(self, answer):
        """Something at an address that does `answer(connection)` for each caller."""
        listening = socket.socket()
        listening.bind(("127.0.0.1", 0))
        listening.listen(5)
        self.addCleanup(listening.close)

        def serve():
            while True:
                try:
                    connection, _ = listening.accept()
                except OSError:
                    return
                threading.Thread(target=answer, args=(connection,), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()
        return f"127.0.0.1:{listening.getsockname()[1]}"

    def short(self, seconds):
        patch = mock.patch.object(remote, "HELLO_SECONDS", seconds)
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_endless_answer_to_hello_is_not_read_to_its_end(self):
        whole, sent = 48 * 1024 * 1024, [0]

        def endless(connection):
            connection.recv(4096)
            try:
                connection.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
                while sent[0] < whole:
                    connection.sendall(b"x" * 65536)
                    sent[0] += 65536
            except OSError:
                pass
            connection.close()

        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.answering(endless), KEY).status()
        self.assertIn("Something else is answering", str(raised.exception))
        self.assertLess(sent[0], whole // 2)                   # it was hung up on long before the end

    def test_an_answer_that_comes_a_byte_at_a_time_has_one_allowance_for_all_of_it(self):
        def dripping(connection):
            connection.recv(4096)
            try:
                for _ in range(50):       # each byte in good time, by itself
                    connection.sendall(b"x")
                    time.sleep(0.1)
            except OSError:
                pass
            connection.close()

        self.short(0.5)
        began = time.monotonic()
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.answering(dripping), KEY).status()
        self.assertLess(time.monotonic() - began, 2.5)
        self.assertIn("too long", str(raised.exception))

    def test_one_that_says_nothing_to_hello_is_soon_given_up_on(self):
        def silent(connection):
            time.sleep(3)
            connection.close()

        self.short(0.5)                   # and not what a big model has for a long phrase
        began = time.monotonic()
        with self.assertRaises(remote.RemoteError):
            remote.Client(self.answering(silent), KEY).status()
        self.assertLess(time.monotonic() - began, 2.5)

    def test_endless_first_lines_are_not_read_for_ever_either(self):
        def lines(connection):
            connection.recv(4096)
            try:
                connection.sendall(b"HTTP/1.0 200 OK\r\n")
                while True:
                    connection.sendall(b"X-More: " + b"y" * 1000 + b"\r\n")
            except OSError:
                pass
            connection.close()

        began = time.monotonic()
        with self.assertRaises(remote.RemoteError):
            remote.Client(self.answering(lines), KEY).status()
        self.assertLess(time.monotonic() - began, 2.5)


def hung_up_on(callers) -> int:
    """How many of these connections the other end has closed."""
    count = 0
    for caller in callers:
        caller.settimeout(0.01)
        try:
            count += caller.recv(1, socket.MSG_PEEK) == b""
        except socket.timeout:
            pass                          # still being attended to
        except OSError:
            count += 1
    return count


class CallersWithoutTheKey(unittest.TestCase):
    """The sharing computer answers anything that can reach it. What has no key can be a
    nuisance to the sharing, and no more: it can't use up the computer."""

    def setUp(self):
        self.recogniser = Recogniser()
        self.server = remote.Server("127.0.0.1", 0, KEY, self.recogniser.hear, self.recogniser.describe)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.port, self.address = self.server.port, f"127.0.0.1:{self.server.port}"

    def with_(self, **limits):
        for name, value in limits.items():
            patch = mock.patch.object(remote, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def callers(self) -> int:
        return self.server._server._callers

    def settled(self, count, seconds=3.0) -> bool:
        """Whether the callers being attended to come to `count` within `seconds`."""
        until = time.monotonic() + seconds
        while time.monotonic() < until and self.callers() != count:
            time.sleep(0.01)
        return self.callers() == count

    def begun(self, *headers, length=100_000):
        """A POST whose first lines have been sent, and none of its `length` of body."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        self.addCleanup(connection.close)
        connection.putrequest("POST", "/hear")
        connection.putheader("Content-Length", str(length))
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders()
        return connection

    def test_only_a_handful_are_attended_to_and_the_rest_are_turned_away_at_once(self):
        self.with_(MOST_CALLERS=3, HEAD_SECONDS=1.5)
        idle = [socket.create_connection(("127.0.0.1", self.port), timeout=5) for _ in range(10)]
        for caller in idle:
            self.addCleanup(caller.close)
        began = time.monotonic()
        while hung_up_on(idle) != 7 and time.monotonic() - began < 1.0:
            time.sleep(0.02)
        self.assertEqual(hung_up_on(idle), 7)                  # the rest, unheard
        self.assertLess(time.monotonic() - began, 1.0)         # and at once: not when their time was up
        self.assertEqual(self.callers(), 3)
        # And when those three have used up what they are allowed, there is room again.
        self.assertTrue(self.settled(0, 4.0))
        self.assertTrue(remote.Client(self.address, KEY).status()["ok"])
        self.assertTrue(self.settled(0))

    def test_a_caller_has_one_allowance_of_time_however_slowly_it_sends(self):
        self.with_(HEAD_SECONDS=0.5)
        caller = socket.create_connection(("127.0.0.1", self.port), timeout=5)
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
        self.assertTrue(self.settled(0))

    def test_no_body_is_read_until_the_caller_has_shown_the_key_and_has_a_turn(self):
        turn, nonce = ask(self.port, "GET", "/hello")[3], remote.number()
        right = remote.ask(KEY, "POST", "/hear", 100_000, turn, nonce)
        for expected, headers in (
                (400, [(remote.NONCE, nonce), (remote.TURN, turn)]),                # no proof at all
                (403, [(remote.NONCE, nonce), (remote.TURN, turn),
                       (remote.ASK, remote.ask("f" * 32, "POST", "/hear", 100_000, turn, nonce))]),
                (403, [(remote.NONCE, nonce), (remote.TURN, turn),                  # for less than is coming
                       (remote.ASK, remote.ask(KEY, "POST", "/hear", 10, turn, nonce))]),
                (403, [(remote.NONCE, nonce), (remote.TURN, turn),                  # for another request
                       (remote.ASK, remote.ask(KEY, "GET", "/status", 100_000, turn, nonce))]),
                (401, [(remote.NONCE, nonce), (remote.TURN, "0" * 32),              # the key, but no turn
                       (remote.ASK, remote.ask(KEY, "POST", "/hear", 100_000, "0" * 32, nonce))])):
            began = time.monotonic()
            answer = self.begun(*headers).getresponse()        # none of the body was sent, or waited for
            self.assertEqual(answer.status, expected)
            self.assertLess(time.monotonic() - began, 2.0)
            self.assertNotIn(remote.NEXT, answer.headers)
        self.assertEqual(self.recogniser.asked, [])
        # The turn was not used up by any of that: with the right proof the body is waited for.
        waited = self.begun((remote.NONCE, nonce), (remote.TURN, turn), (remote.ASK, right))
        waited.sock.settimeout(0.5)
        with self.assertRaises(socket.timeout):
            waited.getresponse()

    def test_what_a_refused_caller_goes_on_sending_is_not_waited_for_long(self):
        self.with_(SPILL_SECONDS=0.3)
        refused = self.begun((remote.NONCE, remote.number()))
        self.assertEqual(refused.getresponse().status, 400)
        self.assertTrue(self.settled(0, 2.0))                  # though it has not hung up, nor sent its body

    def test_an_older_one_that_sends_its_sound_at_once_still_reads_that_it_is_older(self):
        # As the first version did: the whole request in one piece, the sound in the clear.
        sound = remote.pack({"kind": "phrase"}, b"\0\0" * 320_000)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("POST", "/hear", body=sound,
                           headers={remote.AUTH: remote.prove(KEY, "POST /hear", body=sound)})
        answer = connection.getresponse()
        self.assertEqual(answer.status, 400)
        self.assertIn("older Linux Speaking is asking", json.loads(answer.read())["why"])
        # And as the one before the proof ahead of the body did: hello, then all of it.
        status, _, said, _, _ = ask(self.port, "POST", "/hear", sound, first=False)
        self.assertEqual(status, 400)
        self.assertIn("older Linux Speaking is asking", said["why"])
        self.assertEqual(self.recogniser.asked, [])

    def test_hellos_without_the_key_do_not_cost_a_real_caller_its_turn(self):
        self.with_(MOST_TURNS=8)
        client, hellos = remote.Client(self.address, KEY), []
        real = client._hello
        client._hello = lambda: hellos.append(1) or real()
        client.status()
        half = remote.half()[1]
        for _ in range(20):               # more than are kept
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            connection.request("GET", "/hello", headers={remote.NONCE: remote.number(), remote.KEY: half})
            self.assertEqual(connection.getresponse().status, 200)
            connection.close()
        client.status()
        self.assertEqual(len(hellos), 1)

    def test_a_failure_while_answering_writes_nothing_about_the_caller(self):
        mine = remote.half()[1]
        said = io.StringIO()
        with mock.patch.object(remote, "half", side_effect=RuntimeError("no cipher after all")), \
                contextlib.redirect_stderr(said), contextlib.redirect_stdout(said):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            self.addCleanup(connection.close)
            connection.request("GET", "/hello", headers={remote.NONCE: remote.number(), remote.KEY: mine})
            self.assertEqual(connection.getresponse().status, 400)   # answered, all the same
            self.assertTrue(self.settled(0))
        self.assertNotIn("127.0.0.1", said.getvalue())
        self.assertNotIn("Traceback", said.getvalue())

    def test_starting_looks_no_name_up_and_tries_the_cipher(self):
        again = remote.Server("127.0.0.1", 0, KEY, self.recogniser.hear, self.recogniser.describe)
        with mock.patch("socket.getfqdn", side_effect=AssertionError("this computer's name was looked up")):
            again.start()
        again.stop()
        # A "cryptography" package that is there, and can't do what is needed.
        with mock.patch.object(remote, "half", side_effect=RuntimeError("X25519 is not supported")):
            with self.assertRaises(OSError):
                again.start()
        self.assertFalse(again.running)


class WithNothingToEncryptWith(unittest.TestCase):
    """Where the "cryptography" package is missing, the link is not used at all."""

    def setUp(self):
        import unittest.mock
        def missing():
            raise remote.RemoteError('the "cryptography" package is missing')
        patch = unittest.mock.patch.object(remote, "_box", missing)
        patch.start()
        self.addCleanup(patch.stop)

    def test_nothing_is_sent_in_the_clear(self):
        import socket
        listening = socket.socket()
        listening.bind(("127.0.0.1", 0))
        listening.listen(1)
        listening.settimeout(0.3)
        self.addCleanup(listening.close)
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(f"127.0.0.1:{listening.getsockname()[1]}", KEY).hear(
                "phrase", np.zeros(160, dtype=np.float32), True)
        self.assertIn("cryptography", str(raised.exception))
        with self.assertRaises(socket.timeout):
            listening.accept()                                 # it never even connected

    def test_and_nobody_is_answered(self):
        recogniser = Recogniser()
        server = remote.Server("127.0.0.1", 0, KEY, recogniser.hear, recogniser.describe)
        with self.assertRaises(OSError):
            server.start()
        self.assertFalse(server.running)


if __name__ == "__main__":
    unittest.main()
