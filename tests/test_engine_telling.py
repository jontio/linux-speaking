"""What the engine tells the person: notices, standing problems, and the things that
used to fail without a word."""
import queue
import threading
import unittest
from unittest import mock

import numpy as np

from dictation import audio, config
from dictation.commands import Command
from dictation.engine import Engine, named, no_model, nothing_to_type_into
from dictation.settings import Settings
from dictation.status import State, Status

from tests.test_engine_correct import Program


def bare(program=None, **states) -> Engine:
    """An engine with nothing behind it: no microphone, no models, no programs but
    `program`. What it tells is collected in .notices and .events."""
    engine = Engine.__new__(Engine)
    engine.status = Status()
    engine.status.state = State.AWAKE
    engine.settings = Settings.__new__(Settings)
    engine.settings.states = dict(states)
    engine.settings.path, engine.settings.model, engine.settings.microphone = None, "", ""
    engine.settings.shortcuts = {}
    engine.settings.words = ()
    engine.targets = program or Program()
    engine._selected_that, engine._explained_at, engine._choice_timer = False, -60.0, None
    engine.on_change = engine.on_level = lambda: None
    engine.events, engine.notices = [], []
    engine.on_event = engine.events.append
    engine.on_notice = lambda text, kind="info": engine.notices.append((kind, text))
    engine._told, engine._standing = {}, {}
    engine._mail, engine.share_problem = None, ""
    engine.lexicon, engine.keep_final = None, False
    engine._typed_sound = engine._heard_sound = None
    engine._holds, engine._running, engine._recorder = 0, True, None
    engine._lock = threading.Lock()
    engine._phrases = queue.Queue()
    engine._load_tried, engine._transcriber, engine._offload = 0.0, None, None
    return engine


class Quiet(unittest.TestCase):
    """Nothing here may write the log, or the file that remembers on and off."""

    def setUp(self):
        for patch in (mock.patch("dictation.engine.log"), mock.patch.object(Engine, "_save")):
            patch.start()
            self.addCleanup(patch.stop)


class WhatIsWrittenToTheDisk(unittest.TestCase):
    def test_on_and_off_is_only_written_when_it_changes(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "state", "state")
        engine = bare()
        written = []
        real = open

        def counting(file, mode="r", *more, **named):
            if file == path and "w" in mode:
                written.append(1)
            return real(file, mode, *more, **named)
        with mock.patch("dictation.engine.config.STATE_FILE", path), \
                mock.patch("dictation.engine.log"), mock.patch("builtins.open", counting):
            for state in (State.ASLEEP, State.AWAKE, State.ASLEEP, State.AWAKE, State.ASLEEP):
                engine._set(state)                       # waking and sleeping all day
            self.assertEqual(len(written), 1)            # "on", once
            engine._set(State.OFF)
            engine._set(State.OFF)
            self.assertEqual(len(written), 2)
            engine._set(State.ASLEEP)
            self.assertEqual(len(written), 3)
        with real(path) as f:
            self.assertEqual(f.read(), "on")


class NothingToTypeInto(Quiet):
    def test_the_person_is_told_and_told_what_would_work(self):
        engine = bare(Program())
        engine.targets.request = lambda message: {"ok": False, "why": "writer not running"}
        engine.handle_text("Hello there.", True)
        self.assertEqual(len(engine.notices), 1)
        kind, text = engine.notices[0]
        self.assertEqual(kind, "problem")
        self.assertTrue(text.startswith("Nothing to type into. Click in "))
        self.assertIn("Dictate into other programs' text boxes", text)
        self.assertEqual(engine.status.last_heard, "Hello there.  (nothing to type into)")
        self.assertNotIn("writer", engine.status.last_heard)
        self.assertTrue(engine.status.target_known)
        self.assertFalse(engine.status.writer_ready)

    def test_it_is_said_once_not_with_every_phrase(self):
        engine = bare(Program())
        engine.targets.request = lambda message: {"ok": False, "why": "mail not focused"}
        for _ in range(3):
            engine.handle_text("Hello there.", True)
        self.assertEqual(len(engine.notices), 1)

    def test_the_words_fit_the_system_and_the_setting(self):
        with mock.patch("dictation.engine.config.WINDOWS", True):
            self.assertIn("Word, Outlook or VS Code", nothing_to_type_into(False))
            self.assertNotIn("Writer", nothing_to_type_into(False))
        with mock.patch("dictation.engine.config.WINDOWS", False):
            self.assertIn("Writer, Thunderbird, Kate or VS Code", nothing_to_type_into(False))
        self.assertNotIn("tick", nothing_to_type_into(True))

    def test_a_refusal_with_a_reason_gives_the_reason(self):
        engine = bare(Program())
        engine.targets.name = "Word"
        engine.targets.request = lambda message: (
            {"ok": True, "before": "", "after": ""} if message["op"] == "context"
            else {"ok": False, "why": "error", "error": "This  document is\nprotected."})
        engine.handle_text("Hello there.", True)
        self.assertEqual(engine.status.last_heard,
                         "Hello there.  (Word wouldn't take it: This document is protected.)")


class Commands(Quiet):
    def test_what_was_selected_is_said(self):
        engine = bare(Program(has=("cat",)))
        engine.handle_text("Select cat.", True)
        self.assertEqual(engine.notices, [("info", "Selected: cat")])

    def test_a_command_the_program_has_not_got_is_said_to_be_that(self):
        engine = bare(Program())
        engine.targets.request = lambda message: (
            {"ok": True, "before": "", "after": ""} if message["op"] == "context"
            else {"ok": False, "why": "unknown command"})
        engine.handle_text("Indent.", True)
        self.assertEqual(engine.notices, [("problem", 'Writer can\'t do "indent".')])

    def test_one_that_fails_says_why(self):
        engine = bare(Program())
        engine.handle_text("That was a noise.", True)      # nothing was written
        engine.settings.states = {"noise": True}
        engine.notices.clear()
        engine.handle_text("That was a noise.", True)
        self.assertEqual(engine.notices,
                         [("problem", '"that was a noise" couldn\'t be done: nothing was just written.')])

    def test_numbers_to_choose_from_are_asked_for(self):
        engine = bare(Program())
        engine.targets.request = lambda message: {"ok": True, "choices": 3}
        with mock.patch("dictation.engine.threading.Timer"):
            engine.handle_text("Select cat.", True)
        self.assertEqual(engine.notices, [("info", 'Say a number, 1 to 3, or "cancel".')])
        self.assertEqual(engine.status.choosing, 3)


class TheTabKey(Quiet):
    def pressed(self, said, knows=True):
        engine = bare(Program())
        sent = []

        def request(message):
            sent.append(message)
            if message["op"] == "command" and not knows:
                return {"ok": False, "why": "unknown command"}
            return {"ok": True}
        engine.targets.request = request
        engine.handle_text(said, True)
        return [(m["op"], m.get("name") or m.get("text")) for m in sent]

    def test_once_as_ever(self):
        self.assertEqual(self.pressed("Tab."), [("command", "tab")])

    def test_as_many_times_as_asked(self):
        self.assertEqual(self.pressed("Tab three times."), [("command", "tab")] * 3)

    def test_where_there_is_no_tab_command_the_character_is_typed_as_often(self):
        self.assertEqual(self.pressed("Tab twice.", knows=False),
                         [("command", "tab"), ("insert", "\t"), ("insert", "\t")])


class WhileNumbersShow(Quiet):
    def setUp(self):
        super().setUp()
        self.engine = bare(Program())
        self.engine.status.choosing = 3
        self.engine.targets.broadcast = lambda message: None

    def test_a_single_word_that_is_no_number_is_not_typed(self):
        self.engine.handle_text("Tree.", True)
        self.assertEqual(self.engine.targets.asked, [])        # nothing went to the document
        self.assertEqual(self.engine.status.choosing, 3)       # and the numbers are still up
        self.assertEqual(self.engine.notices[0][1], 'That wasn\'t a number. Say a number, 1 to 3, or "cancel".')

    def test_the_second_one_is_a_choice(self):
        self.engine.handle_text("The second one.", True)
        self.assertEqual(self.engine.targets.asked, [("choose", "2")])
        self.assertEqual(self.engine.status.choosing, 0)

    def test_more_than_a_word_is_typed_as_before_and_the_numbers_go(self):
        for said in ("Thank you.", "I will leave it as it is for now."):
            self.engine.status.choosing = 3
            self.engine.targets.asked.clear()
            self.engine.handle_text(said, True)
            self.assertEqual(self.engine.status.choosing, 0, said)
            self.assertIn("insert", [name for name, _ in self.engine.targets.asked], said)

    def test_a_shortcut_of_one_word_is_still_a_shortcut(self):
        self.engine.settings.shortcuts = {"btw": "by the way"}
        self.engine.handle_text("BTW.", True)
        self.assertEqual(self.engine.status.choosing, 0)
        self.assertIn("insert", [name for name, _ in self.engine.targets.asked])

    def test_a_command_is_still_a_command(self):
        self.engine.handle_text("Scratch that.", True)
        self.assertEqual(self.engine.status.choosing, 0)
        self.assertIn("scratch", [name for name, _ in self.engine.targets.asked])


class Shortcuts(Quiet):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.engine = bare(Program())
        self.engine.targets.request = lambda message: (
            self.sent.append(message) or {"ok": True, "before": "I live at ", "after": ""})
        self.engine.settings.shortcuts = {"my address": "12 High Street\nDunedin 9016",
                                          "btw": "by the way"}

    def typed(self):
        return [message["text"] for message in self.sent if message["op"] == "insert"]

    def test_said_by_itself_it_types_the_text_as_written(self):
        self.engine.handle_text("My address.", True)
        self.assertEqual(self.typed(), ["12 High Street\u2028Dunedin 9016"])
        self.assertEqual(self.engine.status.last_heard, "My address.")

    def test_every_letter_is_as_it_was_written_even_at_the_start_of_a_sentence(self):
        self.engine.settings.shortcuts = {"my email": "jo@example.com", "the site": "https://example.org/a"}
        self.engine.targets.request = lambda message: (
            self.sent.append(message) or {"ok": True, "before": "", "after": ""})
        self.engine.handle_text("My email.", True)
        self.engine.handle_text("The site.", True)
        self.assertEqual(self.typed(), ["jo@example.com", "https://example.org/a"])

    def test_as_part_of_a_sentence_it_is_only_words(self):
        self.engine.handle_text("What is my address again?", True)
        self.assertEqual(self.typed(), ["what is my address again"])

    def test_asleep_nothing_is_typed(self):
        self.engine.handle_text("My address.", False)
        self.assertEqual(self.typed(), [])

    def test_with_none_set_nothing_changes(self):
        self.engine.settings.shortcuts = {}
        self.engine.handle_text("My address.", True)
        self.assertEqual(self.typed(), ["my address"])


class ThisProgramsWindows(Quiet):
    def said(self, engine, arg):
        with mock.patch("dictation.engine.interpret", return_value=Command("app", arg)):
            engine.handle_text("Close that window." if arg == "close" else "What can I say?", True)

    def test_the_tray_is_asked_to_open_them(self):
        engine = bare(Program())
        self.said(engine, "help")
        self.assertEqual(engine.events, ["app:help"])
        self.assertEqual(engine.targets.asked, [])

    def test_close_that_window_with_none_open_is_only_words(self):
        engine = bare(Program())
        self.said(engine, "close")
        self.assertEqual(engine.events, [])
        self.assertIn("insert", [name for name, _ in engine.targets.asked])
        engine.status.own_windows = 1
        engine.targets.asked.clear()
        self.said(engine, "close")
        self.assertEqual((engine.events, engine.targets.asked), (["app:close"], []))


class TheMicrophone(Quiet):
    def test_waking_without_one_says_why_and_wakes_nothing(self):
        engine = bare()
        engine.status.state = State.OFF
        with mock.patch("dictation.engine.audio.open_microphone",
                        side_effect=audio.MicrophoneError("The microphone can't be opened. Plug one in.")):
            engine.wake()
        self.assertEqual(engine.events, ["problems"])          # and no "wake"
        self.assertIs(engine.status.state, State.OFF)
        self.assertEqual(engine.notices, [("problem", "The microphone can't be opened. Plug one in.")])
        self.assertEqual(engine.status.problems, ["The microphone can't be opened. Plug one in."])

    def test_once_it_opens_the_problem_is_gone(self):
        engine = bare()
        engine.status.state = State.OFF
        engine._standing["microphone"] = "The microphone can't be opened."
        engine._problems()
        recorder = mock.Mock()
        recorder.read.return_value = b""
        with mock.patch("dictation.engine.audio.open_microphone", return_value=recorder), \
                mock.patch("dictation.engine.threading.Thread"):
            engine.wake()
        self.assertEqual(engine.status.problems, [])
        self.assertEqual(engine.events[-1], "wake")
        self.assertIs(engine.status.state, State.AWAKE)

    def test_one_that_stops_by_itself_is_said_and_tried_again(self):
        engine = bare()
        recorder = mock.Mock()
        recorder.read.return_value = b""                       # it has ended
        recorder.why.return_value = "Device unavailable"
        engine._recorder = recorder
        with mock.patch("dictation.engine.threading.Thread") as thread:
            engine._listen(recorder)
        self.assertIs(engine.status.state, State.OFF)
        self.assertIn("off", engine.events)
        self.assertEqual(engine.notices[0][0], "problem")
        self.assertIn("The microphone stopped: Device unavailable", engine.notices[0][1])
        self.assertIn("come back asleep", engine.status.problems[0])
        self.assertEqual(thread.call_args.kwargs["target"], engine._come_back)

    def test_it_comes_back_asleep_when_it_can(self):
        engine = bare()
        engine.status.state = State.OFF
        engine._standing["microphone"] = "The microphone stopped."
        engine._problems()
        engine.events.clear()
        with mock.patch("dictation.engine.audio.works", side_effect=[False, False, True]) as tried, \
                mock.patch("dictation.engine.audio.open_microphone", return_value=mock.Mock()), \
                mock.patch("dictation.engine.threading.Thread"), \
                mock.patch("dictation.engine.time.sleep"):
            engine._come_back()
        self.assertEqual(tried.call_count, 3)
        self.assertIs(engine.status.state, State.ASLEEP)
        self.assertEqual(engine.notices, [])                   # its own tries are made quietly
        self.assertEqual(engine.status.problems, [])
        self.assertEqual(engine.events, ["problems", "sleep"])  # nothing said until it was back

    def test_one_that_keeps_stopping_is_left_for_the_person_to_try(self):
        engine = bare()
        recorder = mock.Mock()
        recorder.read.return_value = b""
        recorder.why.return_value = ""
        with mock.patch("dictation.engine.threading.Thread") as thread:
            for _ in range(config.MICROPHONE_DROPS):
                engine._recorder = recorder
                engine.status.state = State.ASLEEP
                engine._listen(recorder)
        self.assertEqual(thread.call_count, config.MICROPHONE_DROPS - 1)   # the last isn't tried again
        self.assertIn("It keeps stopping", engine.status.problems[0])

    def test_switched_off_by_hand_it_does_not_come_back(self):
        engine = bare()
        engine.status.state = State.OFF
        engine._standing["microphone"] = "The microphone stopped."
        engine.turn_off()                                      # the person's own doing
        with mock.patch("dictation.engine.audio.open_microphone") as opened, \
                mock.patch("dictation.engine.time.sleep"):
            engine._come_back()
        opened.assert_not_called()
        self.assertIs(engine.status.state, State.OFF)


class HowTheSoundGoes(Quiet):
    """What the engine says of how sound goes to the other computer."""

    def test_asking_the_other_computer_says_how_sound_will_go_to_it(self):
        from dictation import remote
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("needs the cryptography package")
        server = remote.Server("127.0.0.1", 0, "0123456789abcdef", lambda header, sound: {"ok": True},
                               lambda: {"version": "1", "models": [["small.en", "Small"]], "model": "small.en"})
        server.start()
        self.addCleanup(server.stop)
        engine = bare()
        engine.settings.remote = {"on": True, "address": f"127.0.0.1:{server.port}",
                                  "key": "0123456789abcdef", "model": "", "wake": False, "sound": "flac"}
        with mock.patch.object(remote, "_sounds", ("flac", "opus", "pcm")):
            server.sounds = ("flac", "opus", "pcm")
            answer = engine.check_remote()
            self.assertEqual((answer["ok"], answer["sound"], answer["sound_there"]), (True, "flac", True))
            self.assertEqual(answer["models"], [["small.en", "Small"]])
            server.sounds = ("pcm",)                            # as an earlier version would be
            answer = engine.check_remote()
            self.assertEqual((answer["sound"], answer["sound_there"]), ("pcm", False))
            engine.settings.remote["sound"] = "opus"
            server.sounds = ("flac", "pcm")
            self.assertEqual(engine.check_remote()["sound"], "flac")

    def test_the_log_says_how_it_goes_and_when_that_is_not_as_chosen(self):
        import dictation.engine as module
        engine = bare()
        engine.settings.remote = {"sound": "flac"}
        engine._sound_sent("flac")
        self.assertEqual(module.log.call_args[0][0], "sound goes to the other computer packed as FLAC")
        engine._sound_sent("pcm")
        said = module.log.call_args[0][0]
        self.assertTrue(said.startswith("sound goes to the other computer as it is (raw): packed as FLAC "
                                        "was chosen"), said)

    def test_the_way_chosen_is_kept_when_the_rest_is_set_without_it(self):
        engine = bare()
        engine.settings.remote = {"on": True, "address": "office-pc", "key": "k", "model": "", "wake": False,
                                  "sound": "opus"}
        engine.settings.set_remote = lambda **chosen: engine.settings.remote.update(chosen)
        engine._apply_remote = lambda: None
        engine._transcriber = mock.Mock()
        engine.set_remote(True, "office-pc", "k", "", False)
        self.assertEqual(engine.settings.remote["sound"], "opus")
        engine.set_remote(True, "office-pc", "k", "", False, "pcm")
        self.assertEqual(engine.settings.remote["sound"], "pcm")


class WhereItIsShared(Quiet):
    """Which of this computer's addresses other computers are answered on."""

    def engine(self, where, here=()):
        from dictation import remote
        engine = bare()
        engine._server = engine._share_timer = None
        engine._share_lock = threading.RLock()
        engine.settings.share = {"on": True, "key": "0123456789abcdef", "where": where}
        engine.settings.set_share = lambda **chosen: engine.settings.share.update(chosen)
        self.here, self.asked = dict(here), []
        for patch in (mock.patch.object(config, "SHARE_PORT", 0),
                      mock.patch.object(remote, "networks",
                                        lambda: self.asked.append(1) or list(self.here.items()))):
            patch.start()
            self.addCleanup(patch.stop)

        def stop():
            engine._running = False
            engine._apply_sharing()
        self.addCleanup(stop)
        return engine

    def answers_on(self, engine):
        return engine._server._server.server_address[0]

    def test_on_every_network_unless_chosen_otherwise(self):
        engine = self.engine("")
        engine._apply_sharing()
        self.assertEqual((self.answers_on(engine), engine.share_address, engine.share_problem),
                         ("0.0.0.0", "", ""))
        self.assertEqual(self.asked, [])                       # the networks aren't so much as looked at
        self.assertIsNone(engine._share_timer)                 # and there is nothing to watch

    def test_kept_to_one_network_it_answers_on_its_address_there_alone(self):
        engine = self.engine("office-vpn", {"Wi-Fi": "192.168.1.20", "office-vpn": "127.0.0.1"})
        engine._apply_sharing()
        self.assertEqual((self.answers_on(engine), engine.share_address, engine.share_problem),
                         ("127.0.0.1", "127.0.0.1", ""))

    def test_when_this_computer_is_not_on_that_network_nobody_is_answered_and_it_tries_again(self):
        engine = self.engine("office-vpn", {"Wi-Fi": "127.0.0.1"})
        engine._apply_sharing()
        self.assertIsNone(engine._server)                      # never every network instead
        self.assertEqual(engine.share_problem, 'this computer isn\'t on the network "office-vpn" just now')
        self.assertIsNotNone(engine._share_timer)
        engine._problems()
        self.assertIn("isn't on the network", " ".join(engine.status.problems))
        self.here["office-vpn"] = "127.0.0.1"                  # the VPN is switched on
        engine._apply_sharing()                                # as the timer would
        self.assertEqual((self.answers_on(engine), engine.share_problem), ("127.0.0.1", ""))

    def test_an_address_that_changes_is_followed(self):
        engine = self.engine("office-vpn", {"office-vpn": "127.0.0.1"})
        engine._apply_sharing()
        first = engine._server
        self.assertIsNotNone(engine._share_timer)              # it is watched
        engine._share_timer.cancel()
        engine._watch_sharing()                                # half a minute on: nothing has changed
        self.assertIs(engine._server, first)
        self.assertIsNotNone(engine._share_timer)
        engine._share_timer.cancel()
        self.here["office-vpn"] = "127.0.0.2"                  # a new address on the same network
        engine._watch_sharing()
        self.assertIsNot(engine._server, first)
        self.assertEqual((self.answers_on(engine), engine.share_address), ("127.0.0.2", "127.0.0.2"))
        engine._share_timer.cancel()
        del self.here["office-vpn"]                            # and then the network goes away
        engine._watch_sharing()
        self.assertIsNone(engine._server)
        self.assertIn("isn't on the network", engine.share_problem)

    def test_a_new_key_shuts_out_whoever_holds_the_old_one(self):
        from dictation import remote
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("needs the cryptography package")
        engine = self.engine("")
        engine._describe = lambda: {"version": "1", "models": [], "model": ""}
        engine._apply_sharing()
        old = engine.settings.share["key"]

        def asks(key):
            return remote.Client(f"127.0.0.1:{engine._server.port}", key).status()
        self.assertTrue(asks(old)["ok"])
        engine.new_share_key()
        new = engine.settings.share["key"]
        self.assertNotEqual(new, old)
        self.assertRegex(new, "^[0-9a-f]{32}$")
        self.assertTrue(engine.settings.share["on"])               # it goes on sharing
        self.assertTrue(asks(new)["ok"])
        with self.assertRaises(remote.RemoteError) as raised:
            asks(old)
        self.assertIn("key doesn't match", str(raised.exception))
        engine.new_share_key()                                     # and each new one is another
        self.assertNotIn(engine.settings.share["key"], (old, new))

    def test_an_address_said_when_it_was_started_is_used_whatever_was_chosen(self):
        engine = self.engine("office-vpn", {})
        with mock.patch.object(config, "SHARE_ADDRESS", "127.0.0.1"):
            engine._apply_sharing()
            self.assertEqual((self.answers_on(engine), engine.share_problem, self.asked),
                             ("127.0.0.1", "", []))
            self.assertIsNone(engine._share_timer)             # that address is not watched

    def test_changing_the_choice_moves_it(self):
        engine = self.engine("", {"office-vpn": "127.0.0.1"})
        engine._apply_sharing()
        self.assertEqual(self.answers_on(engine), "0.0.0.0")
        engine.set_sharing(True, "office-vpn")
        self.assertEqual(self.answers_on(engine), "127.0.0.1")
        engine.set_sharing(True)                               # left out: it stays as it was
        self.assertEqual((engine.settings.share["where"], self.answers_on(engine)),
                         ("office-vpn", "127.0.0.1"))
        engine.set_sharing(True, "")                           # and back to every network
        self.assertEqual((engine.settings.share["where"], self.answers_on(engine)), ("", "0.0.0.0"))


class LoadingAModel(Quiet):
    def test_with_none_to_load_it_says_so_and_what_to_do(self):
        engine = bare()
        with mock.patch("dictation.engine.Transcriber", side_effect=RuntimeError("no such folder")), \
                mock.patch("dictation.engine.available_models", return_value=[]):
            engine._load("")
        self.assertEqual(engine.status.failed,
                         'No speech model is installed. Open Settings and press "Install or remove '
                         'models\u2026", or have another computer do the listening: "Another computer", '
                         'further down in Settings.')
        self.assertEqual(engine.events, ["failed"])
        self.assertEqual(engine.status.label(), "No speech model")
        self.assertFalse(engine.status.ready)

    def test_with_none_installed_and_another_computer_listening_nothing_is_wrong(self):
        engine = bare()
        engine._offload = mock.Mock()
        with mock.patch("dictation.engine.Transcriber", side_effect=RuntimeError("no such folder")), \
                mock.patch("dictation.engine.available_models", return_value=[]):
            self.assertTrue(engine._no_model_here())
            engine._load("")
            self.assertEqual((engine.status.failed, engine.status.ready), ("", True))
            self.assertEqual(engine.events, ["ready"])
            self.assertEqual(engine.status.label(), "Awake")
        # With a model installed, that it won't load is still a failure.
        engine = bare()
        engine._offload = mock.Mock()
        with mock.patch("dictation.engine.Transcriber", side_effect=RuntimeError("damaged")), \
                mock.patch("dictation.engine.available_models", return_value=[("small.en", "Small")]):
            self.assertFalse(engine._no_model_here())
            engine._load("")
            self.assertFalse(engine.status.ready)
            self.assertIn("could not be loaded", engine.status.failed)

    def test_with_none_installed_what_is_heard_goes_to_the_other_computer(self):
        engine = bare()
        engine._offload = mock.Mock()
        engine._offload.transcribe.return_value = "hello there"
        engine._offload.measured = None
        engine._only_breath = lambda audio: False
        heard = []
        engine.handle_text = lambda text, awake: heard.append((text, awake))
        with mock.patch("dictation.engine.Transcriber", side_effect=RuntimeError("no")) as made, \
                mock.patch("dictation.engine.available_models", return_value=[]):
            engine.handle_audio(np.ones(16000, dtype=np.float32) * 0.1)
            engine.status.state = State.ASLEEP
            engine.handle_audio(np.ones(16000, dtype=np.float32) * 0.1)
        made.assert_not_called()                     # there is nothing to load, and it isn't tried
        self.assertEqual(heard, [("hello there", True), ("hello there", False)])

    def test_with_none_installed_it_says_when_the_other_computer_cant_be_reached(self):
        engine = bare()
        engine._offload = mock.Mock()
        engine._offload.client.host = "office-pc"
        engine._listening_moved(False, "The other computer can't be reached.")
        self.assertEqual(engine.status.listening_on, "nowhere: the other computer can't be reached")
        self.assertEqual(len(engine.status.problems), 1)
        self.assertEqual(engine.status.problems[0],
                         "Nothing you say can be heard. This computer has no speech model of its own, "
                         "and the other computer does the listening: The other computer can't be "
                         "reached. It is asked again as you speak.")
        self.assertIn("problems", engine.events)
        engine._listening_moved(True, "")
        self.assertEqual((engine.status.listening_on, engine.status.problems), ("office-pc", []))
        # With a model here it carries on by itself, and that is no problem to report.
        engine._transcriber = mock.Mock()
        engine._listening_moved(False, "The other computer can't be reached.")
        self.assertEqual(engine.status.listening_on, "this computer: the other can't be reached")
        self.assertEqual(engine.status.problems, [])

    def test_with_none_installed_choosing_or_dropping_the_other_computer_decides_it(self):
        engine = bare()
        engine.settings.remote = {"on": True, "address": "office-pc", "key": "k", "model": "", "wake": False,
                                  "sound": "flac"}
        engine.settings.set_remote = lambda **chosen: engine.settings.remote.update(chosen)

        def apply():
            engine._offload = mock.Mock() if engine.settings.remote["on"] else None
        engine._apply_remote = apply
        with mock.patch("dictation.engine.available_models", return_value=[]):
            engine.set_remote(True, "office-pc", "k", "", False)
            self.assertEqual((engine.status.failed, engine.status.ready), ("", True))
            engine.set_remote(False, "office-pc", "k", "", False)
            self.assertFalse(engine.status.ready)
            self.assertIn("No speech model is installed", engine.status.failed)
            self.assertIn("Another computer", engine.status.failed)
            engine.set_remote(True, "office-pc", "k", "", False)
            self.assertEqual((engine.status.failed, engine.status.ready), ("", True))

    def test_the_first_model_installed_on_a_computer_with_none_is_put_to_use(self):
        engine = bare()
        asked = []
        engine.set_model = asked.append
        engine.model_installed("small.en")
        self.assertEqual(asked, ["small.en"])
        engine._transcriber = mock.Mock()            # with one loaded, the choice is the person's
        engine.model_installed("medium.en")
        self.assertEqual(asked, ["small.en"])

    def test_a_sound_does_not_try_again_at_once_but_does_later(self):
        engine = bare()
        with mock.patch("dictation.engine.Transcriber", side_effect=RuntimeError("no")) as made, \
                mock.patch("dictation.engine.available_models", return_value=[]):
            engine._load("")
            engine.handle_audio(np.zeros(16000, dtype=np.float32))
            self.assertEqual(made.call_count, 1)
            engine._load_tried -= config.LOAD_AGAIN + 1
            engine.handle_audio(np.zeros(16000, dtype=np.float32))
            self.assertEqual(made.call_count, 2)

    def test_a_choice_that_will_not_load_is_put_back_and_said(self):
        engine = bare()
        engine._transcriber = mock.Mock(dictation_name="small.en")
        engine._transcriber.use.side_effect = RuntimeError("damaged")
        engine.settings.model = "medium.en"
        with mock.patch.object(Settings, "save"):
            engine._load("medium.en", before="small.en")
        self.assertEqual(engine.settings.model, "small.en")
        self.assertEqual(engine.notices, [("problem", "Medium could not be loaded. Still using Small.")])
        self.assertIn("model", engine.events)
        self.assertEqual(engine.status.failed, "")
        self.assertTrue(engine.status.ready)

    def test_words_for_it(self):
        self.assertEqual(named("parakeet-unified-en-0.6b"), "Parakeet Unified")
        self.assertEqual(named("something-else"), "something-else")
        missing = ImportError("No module named 'sherpa_onnx'", name="sherpa_onnx")
        self.assertIn("Run the installer again", no_model(missing))
        with mock.patch("dictation.engine.available_models", return_value=[("small.en", "Small")]):
            self.assertIn("could not be loaded (the file is damaged)", no_model(RuntimeError("the file is damaged")))


class WhatIsWrong(Quiet):
    def test_the_list_is_gathered_from_where_things_go_wrong(self):
        engine = bare()
        engine._mail = mock.Mock(problem="Thunderbird's add-on is an older one. Add it again.")
        engine.targets.other = mock.Mock(problem="")
        engine._standing["office"] = "Dictation into Word and Outlook is off."
        engine._problems()
        self.assertEqual(engine.status.problems, ["Dictation into Word and Outlook is off.",
                                                  "Thunderbird's add-on is an older one. Add it again."])
        self.assertEqual(engine.events, ["problems"])
        engine._problems()
        self.assertEqual(engine.events, ["problems"])          # only said when it changes
        engine._mail.problem = ""
        engine.targets.other.problem = "The desktop didn't let this program press keys."
        engine._problems()
        self.assertEqual(engine.status.problems, ["Dictation into Word and Outlook is off.",
                                                  "The desktop didn't let this program press keys."])


class WhereTheWordsWillGo(Quiet):
    def test_looking_says_which_program_is_in_front(self):
        engine = bare(Program())
        changes = []
        engine.on_change = lambda: changes.append(1)
        engine._look()
        self.assertEqual((engine.status.target, engine.status.writer_ready, engine.status.target_known),
                         ("Writer", True, True))
        self.assertEqual(len(changes), 1)
        engine._look()
        self.assertEqual(len(changes), 1)                      # nothing new, nothing redrawn
        engine.targets.name = ""
        engine._look()
        self.assertEqual((engine.status.writer_ready, len(changes)), (False, 2))

    def test_asleep_nobody_looks(self):
        engine = bare(Program())
        engine.status.state = State.ASLEEP
        engine.targets.pick = mock.Mock()
        engine._look()
        engine.targets.pick.assert_not_called()


class ANoiseInAnotherProgram(Quiet):
    def test_the_other_program_s_last_phrase_is_left_alone(self):
        import os
        import tempfile
        folder = os.path.join(tempfile.mkdtemp(), "noises")
        engine = bare(Program(), noise=True)
        with mock.patch("dictation.engine.config.NOISE_DIR", folder):
            engine._heard_sound = (np.zeros(1600, dtype=np.float32), "Yeah.", "a-model", None)
            engine.handle_text("Yeah.", True)                  # written in Writer
            engine.targets.asked.clear()
            engine.targets.name = "Thunderbird"                # and now that is in front
            engine.handle_text("That was a noise.", True)
        self.assertNotIn("scratch", [name for name, _ in engine.targets.asked])
        self.assertEqual(len([n for n in os.listdir(folder) if n.endswith(".wav")]), 1)
        self.assertIn("is in Writer", engine.notices[-1][1])


class InitialsInAProgramThatSearchesForItself(Quiet):
    def test_they_are_asked_for_as_separate_letters_too(self):
        asked = []
        engine = bare(Program())

        def request(message):
            if message["op"] != "command":
                return {"ok": True, "before": "", "after": ""}
            asked.append(message["arg"])
            return {"ok": True} if message["arg"] == "the u s" else {"ok": False, "why": "can't find that"}
        engine.targets.request = request
        engine.handle_text("Select the U.S.", True)
        self.assertEqual(asked, ["the us", "the u s"])
        self.assertEqual(engine.notices, [("info", "Selected: the us")])

    def test_without_dots_nothing_more_is_asked(self):
        asked = []
        engine = bare(Program())
        engine.targets.request = lambda message: (
            asked.append(message.get("arg")) or {"ok": False, "why": "can't find that"}
            if message["op"] == "command" else {"ok": True, "before": "", "after": ""})
        engine.handle_text("Select zebra.", True)
        self.assertEqual(asked, ["zebra"])


class TheirOwnNames(Quiet):
    def test_a_name_of_theirs_keeps_its_capital_at_the_start_of_a_phrase(self):
        from dictation.words import Lexicon
        sent = []
        engine = bare(Program())
        engine.lexicon = Lexicon(lower=("rose", "spoke", "to", "i"))
        engine.targets.request = lambda message: sent.append(message) or {
            "ok": True, "before": "I spoke to ", "after": ""}
        engine.handle_text("Rose.", True)
        engine.settings.words = ("Rose",)
        engine.handle_text("Rose.", True)
        self.assertEqual([m["text"] for m in sent if m["op"] == "insert"], ["rose", "Rose"])


class ASentenceEndThatWasSaid(Quiet):
    """After "p.m." the next phrase starts a sentence only if "full stop" was said."""

    def setUp(self):
        super().setUp()
        from dictation.words import Lexicon
        self.doc = ""
        self.engine = bare(Program())
        self.engine.lexicon = Lexicon(lower=("on", "we", "meet", "the", "meeting", "starts", "at",
                                             "from", "there", "go", "then", "home"))

        def request(message):
            if message["op"] == "insert":
                self.doc += message["text"]
            return {"ok": True, "before": self.doc, "after": ""}
        self.engine.targets.request = request

    def say(self, *phrases):
        for phrase in phrases:
            self.engine.handle_text(phrase, True)
        return self.doc

    def test_a_pause_after_a_shortening_carries_on_the_sentence(self):
        self.assertEqual(self.say("The meeting starts at 3 p.m.", "On Tuesday."),
                         "The meeting starts at 3 p.m. on Tuesday")

    def test_full_stop_said_in_the_phrase_starts_a_new_one(self):
        self.assertEqual(self.say("The meeting starts at 3 p.m. full stop", "From there we go home."),
                         "The meeting starts at 3 p.m. From there we go home")

    def test_full_stop_said_by_itself_adds_no_second_stop_and_is_remembered(self):
        self.assertEqual(self.say("The meeting starts at 3 p.m.", "Full stop.", "From there we go home."),
                         "The meeting starts at 3 p.m. From there we go home")

    def test_it_is_forgotten_when_the_text_is_no_longer_as_it_was_left(self):
        self.say("The meeting starts at 3 p.m.")
        self.doc = "Somewhere else at 3 p.m."            # the cursor has been moved
        self.assertEqual(self.say("On Tuesday."), "Somewhere else at 3 p.m. On Tuesday")

    def test_a_command_in_between_and_nothing_is_assumed(self):
        self.say("The meeting starts at 3 p.m.")
        self.engine.handle_text("Go to end of line.", True)
        self.assertIsNone(self.engine._last_typed)

    def test_ordinary_sentences_are_as_they_always_were(self):
        self.assertEqual(self.say("We meet full stop", "Then we go home."), "We meet. Then we go home")
        self.doc = ""
        self.engine._last_typed = None
        self.assertEqual(self.say("We meet", "Then we go home."), "We meet then we go home")


class WhatAParakeetModelWrote(unittest.TestCase):
    def test_it_is_put_together_from_the_models_own_pieces(self):
        from types import SimpleNamespace
        from dictation.engine import from_pieces
        # As the library hands it over: its text has lost the space the model wrote, as a
        # piece of its own, before the dollar sign.
        result = SimpleNamespace(text=" Today I spent$120.",
                                 tokens=[" To", "day", " I", " sp", "ent", " ", "$", "1", "2", "0", "."])
        self.assertEqual(from_pieces(result), "Today I spent $120.")
        plain = SimpleNamespace(text=" Hello there.", tokens=[" Hello", " there", "."])
        self.assertEqual(from_pieces(plain), "Hello there.")
        self.assertEqual(from_pieces(SimpleNamespace(text=" only the text ", tokens=[])), "only the text")
        self.assertEqual(from_pieces(SimpleNamespace(text="", tokens=None)), "")


class SumsOfMoney(Quiet):
    def typed(self, engine, said):
        sent = []
        engine.targets.request = lambda message: sent.append(message) or {"ok": True, "before": "", "after": ""}
        engine.handle_text(said, True)
        return [message["text"] for message in sent if message["op"] == "insert"]

    def test_they_are_typed_in_figures_whichever_way_they_were_written(self):
        self.assertEqual(self.typed(bare(Program()), "Today I spent a hundred and fifty dollars."),
                         ["Today I spent $150"])
        self.assertEqual(self.typed(bare(Program()), "Today I spent $120."), ["Today I spent $120"])

    def test_unticked_they_are_left_as_written(self):
        self.assertEqual(self.typed(bare(Program(), money=False), "Today I spent a hundred and fifty dollars."),
                         ["Today I spent a hundred and fifty dollars"])


class TheLastMark(Quiet):
    def typed(self, engine):
        sent = []
        engine.targets.request = lambda message: sent.append(message) or {"ok": True, "before": "", "after": ""}
        engine.handle_text("Is that right?", True)
        return [message["text"] for message in sent if message["op"] == "insert"]

    def test_it_is_left_off_unless_asked_for(self):
        self.assertEqual(self.typed(bare(Program())), ["Is that right"])
        self.assertEqual(self.typed(bare(Program(), keep_final=True)), ["Is that right?"])


if __name__ == "__main__":
    unittest.main()
