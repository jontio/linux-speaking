import http.client
import json
import os
import tempfile
import unittest

import numpy as np

from dictation import config, remote
from dictation.settings import Settings

KEY = "0123456789abcdef0123456789abcdef"


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
                                  "exact": False})
        self.assertEqual(length, 16000)
        self.assertAlmostEqual(peak, 0.5, places=3)

    def test_a_wrong_key_is_refused_and_nothing_is_done(self):
        with self.assertRaises(remote.RemoteError) as raised:
            remote.Client(self.address, "f" * 32).hear("phrase", np.zeros(100, dtype=np.float32), True)
        self.assertIn("key", str(raised.exception))
        with self.assertRaises(remote.RemoteError):
            remote.Client(self.address, "").status()
        self.assertEqual(self.recogniser.asked, [])

    def test_a_signature_for_one_request_does_not_open_another(self):
        body = remote.pack({"kind": "phrase"}, b"\0\0")
        connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
        connection.request("POST", "/hear", body=body,
                           headers={remote.AUTH: remote.sign(KEY, "GET", "/status", b"")})
        self.assertEqual(connection.getresponse().status, 403)
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
            connection = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)
            connection.request(method, path, body=body or None,
                               headers={remote.AUTH: remote.sign(KEY, method, path, body)})
            self.assertEqual(connection.getresponse().status, expected, (method, path))
            connection.close()

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
             exact=False):
        self.quick_asked, self.exact_asked = quick, exact
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
        self.transcriber._by_transducer = lambda name, audio: f"by {name}"
        ask = lambda **header: self.transcriber.answer({"kind": "phrase", "model": "parakeet-x", **header}, [])
        self.assertEqual(ask()["text"], "by parakeet-x")
        self.assertEqual(self.heard, [])
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
        base = remote.sign(KEY, "POST", "/hear", b"abc")
        self.assertEqual(len(base), 64)
        for other in (remote.sign(KEY + "x", "POST", "/hear", b"abc"), remote.sign(KEY, "GET", "/hear", b"abc"),
                      remote.sign(KEY, "POST", "/status", b"abc"), remote.sign(KEY, "POST", "/hear", b"abd")):
            self.assertNotEqual(base, other)

    def test_addresses(self):
        self.assertEqual(remote.parse_address(" office-pc "), ("office-pc", config.SHARE_PORT))
        self.assertEqual(remote.parse_address("office-pc:5000"), ("office-pc", 5000))
        self.assertEqual(remote.parse_address("10.0.0.7:47614"), ("10.0.0.7", 47614))
        self.assertEqual(remote.parse_address("[fd00::1]:5000"), ("fd00::1", 5000))
        self.assertEqual(remote.parse_address("fd00::1"), ("fd00::1", config.SHARE_PORT))
        for bad in ("", ":5000", "office-pc:abc", "office-pc:0", "office-pc:70000"):
            with self.assertRaises(remote.RemoteError):
                remote.parse_address(bad)


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


if __name__ == "__main__":
    unittest.main()
