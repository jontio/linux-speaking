"""How the engine passes "correct ..." on to the program being typed into."""
import os
import unittest
from unittest import mock

from dictation.engine import Engine
from dictation.settings import Settings
from dictation.status import State, Status


class Program:
    """Stands in for a program that is typed into. `knows` is whether its link to the
    engine was made since "correct" was added; `has` is what its text holds."""

    name = "Writer"

    def __init__(self, knows=True, has=("cat",)):
        self.knows, self.has, self.asked = knows, has, []

    other = None

    def describe(self):
        return "nothing in front"

    def pick(self):
        pass

    def request(self, message):
        self.asked.append((message.get("name") or message["op"], message.get("arg", "")))
        if message["op"] != "command":
            return {"ok": True, "before": "", "after": ""}
        if message["name"] == "correct" and not self.knows:
            return {"ok": False, "why": "unknown command"}
        if message["name"] in ("select", "correct") and message["arg"] not in self.has:
            return {"ok": False, "why": "can't find that"}
        return {"ok": True}


class Correct(unittest.TestCase):
    def engine(self, program):
        engine = Engine.__new__(Engine)
        engine.status = Status()
        engine.status.state = State.AWAKE
        engine.settings = Settings.__new__(Settings)
        engine.settings.states = {}
        engine.settings.words = ()
        engine.targets = program
        engine._selected_that, engine._explained_at, engine._choice_timer = False, -60.0, None
        engine.on_change = lambda: None
        engine.on_event = lambda name: None
        engine.notices = []
        engine.on_notice = lambda text, kind="info": engine.notices.append((kind, text))
        engine._told, engine._standing = {}, {}
        return engine

    def say(self, program, text):
        with mock.patch("dictation.engine.log"):
            engine = self.engine(program)
            engine.handle_text(text, True)
        return engine.status.last_heard

    def test_it_is_passed_on_as_itself(self):
        program = Program()
        self.assertEqual(self.say(program, "Correct cat."), "Correct cat.")
        self.assertEqual(program.asked, [("correct", "cat")])

    def test_a_program_that_does_not_know_it_selects_the_words_instead(self):
        program = Program(knows=False)
        heard = self.say(program, "Correct cat.")
        self.assertEqual(program.asked, [("correct", "cat"), ("select", "cat")])
        # And the person is told the cursor won't be going back.
        self.assertTrue(heard.startswith("Correct cat.  (the cursor will stay there"), heard)

    def test_it_says_when_the_cursor_was_too_far_away_to_go_back(self):
        program = Program()
        program.request = lambda message: (
            {"ok": True, "text": "x", "too_far": True} if message["op"] == "insert"
            else {"ok": True, "before": "", "after": ""})
        with mock.patch("dictation.engine.log"):
            engine = self.engine(program)
            engine.lexicon, engine.keep_final = None, False
            engine.handle_text("lion", True)
        self.assertEqual(engine.status.last_heard,
                         "lion  (too far to go back: the cursor is after the new words)")

    def test_words_that_sound_the_same_are_tried_as_for_select(self):
        program = Program(has=("2",))
        self.say(program, "Correct two.")
        self.assertEqual(program.asked, [("correct", "two"), ("correct", "2")])
        program = Program(knows=False, has=("2",))
        self.say(program, "Correct two.")
        self.assertEqual(program.asked, [("correct", "two"), ("select", "two"), ("select", "2")])

    def test_words_that_are_not_there_make_it_a_sentence_and_it_is_typed(self):
        program = Program()
        with mock.patch("dictation.engine.log"):
            engine = self.engine(program)
            engine.lexicon, engine.keep_final = None, False
            engine.handle_text("Correct me if I'm wrong.", True)
        self.assertEqual(engine.status.last_heard, "Correct me if I'm wrong.")
        self.assertEqual([name for name, _ in program.asked], ["correct", "context", "insert"])

    def test_select_does_the_same(self):
        program = Program()
        with mock.patch("dictation.engine.log"):
            engine = self.engine(program)
            engine.lexicon, engine.keep_final = None, False
            engine.handle_text("Select the best option.", True)
        self.assertEqual(engine.status.last_heard, "Select the best option.")
        self.assertEqual([name for name, _ in program.asked], ["select", "context", "insert"])

    def test_words_that_are_there_are_selected_and_nothing_is_typed(self):
        program = Program()
        self.say(program, "Select cat.")
        self.assertEqual(program.asked, [("select", "cat")])

    def test_only_not_finding_them_makes_it_a_sentence(self):
        program = Program()
        program.request = lambda message: {"ok": False, "why": "can't select here"}
        self.assertEqual(self.say(program, "Select the dog."), "Select the dog.  (can't select here)")

    def test_nothing_is_typed_where_there_is_nothing_to_type_into(self):
        program = Program()
        program.request = lambda message: {"ok": False, "why": "writer not focused"}
        heard = self.say(program, "Correct the dog.")
        self.assertEqual(heard, "Correct the dog.  (nothing to type into)")

    def test_the_log_says_when_scratch_that_put_words_back(self):
        # The words themselves never go in the log: only that they are back.
        program = Program()
        program.request = lambda message: {"ok": True, "restored": True}
        with mock.patch("dictation.engine.log") as log:
            engine = self.engine(program)
            engine.handle_text("Scratch that.", True)
        self.assertEqual(log.call_args[0][0],
                         "command scratch: ok, and the words it was said over are back")
        program.request = lambda message: {"ok": True}
        with mock.patch("dictation.engine.log") as log:
            engine = self.engine(program)
            engine.handle_text("Scratch that.", True)
        self.assertEqual(log.call_args[0][0], "command scratch: ok")

    def test_switched_off_it_is_only_words(self):
        program = Program()
        with mock.patch("dictation.engine.log"):
            engine = self.engine(program)
            engine.settings.states = {"correct": False}
            engine.lexicon, engine.keep_final = None, False
            engine.handle_text("Correct cat.", True)
        self.assertEqual([name for name, _ in program.asked], ["context", "insert"])


class ARetrainedModel(unittest.TestCase):
    """A model made again under the name it is loaded by is loaded again."""

    def ears(self, loaded, in_use):
        from dictation.engine import Transcriber
        import threading
        ears = Transcriber.__new__(Transcriber)
        ears.lock, ears._guests = threading.RLock(), []
        ears._loaded = dict(loaded)
        ears.dictation_name, ears.helper_name = in_use, "base.en"
        ears._extras = {}
        ears._is_transducer = lambda name: True
        ears.made = []
        ears._transducer = lambda name: ears._loaded.setdefault(name, ears.made.append(name) or "new")
        return ears

    def test_the_one_in_use_is_loaded_afresh(self):
        ears = self.ears({"mine": "old", "base.en": "wake"}, in_use="mine")
        self.assertTrue(ears.renewed("mine"))
        self.assertEqual((ears._loaded["mine"], ears.made), ("new", ["mine"]))

    def test_one_only_tried_in_a_test_is_let_go(self):
        ears = self.ears({"mine": "old", "other": "x"}, in_use="other")
        self.assertTrue(ears.renewed("mine"))
        self.assertEqual((sorted(ears._loaded), ears.made), (["other"], []))

    def test_one_that_was_never_loaded_is_nothing_to_do(self):
        ears = self.ears({"other": "x"}, in_use="other")
        self.assertFalse(ears.renewed("mine"))


class Whispering(unittest.TestCase):
    """With "Leave out whispering" ticked, a phrase without a voice in it goes no further."""

    def setUp(self):
        import numpy as np
        from dictation import config
        patch = mock.patch("dictation.engine.log")
        self.log = patch.start()
        self.addCleanup(patch.stop)
        self.engine = Correct.engine(self, Program())
        t = np.arange(config.RATE) / config.RATE
        self.voice = sum(np.sin(2 * np.pi * 120 * n * t) / n for n in range(1, 25)) * 3000
        self.breath = np.random.default_rng(0).normal(size=config.RATE) * 3000
        self.engine._transcriber = mock.Mock()
        self.engine._ears = lambda: self.engine._transcriber
        self.engine._transcriber.transcribe.return_value = ""

    def heard(self, sound, **states):
        self.engine.settings.states = states
        self.engine._transcriber.transcribe.reset_mock()
        self.engine.status.state, self.engine.status.last_heard = State.THINKING, ""
        left_out = self.engine._only_breath(sound)
        return left_out, self.engine.status.state, self.engine.status.last_heard

    def test_it_is_not_asked_unless_ticked(self):
        self.assertEqual(self.heard(self.breath), (False, State.THINKING, ""))
        self.log.assert_not_called()

    def test_a_whisper_is_left_out_and_the_tray_says_so(self):
        left_out, state, said = self.heard(self.breath, aloud=True)
        self.assertEqual((left_out, state), (True, State.AWAKE))
        self.assertIn("whisper", said)
        self.assertIn("left out", self.log.call_args[0][0])
        self.assertNotIn("3000", self.log.call_args[0][0])   # figures about it, never the sound

    def test_a_voice_goes_on_to_be_recognised(self):
        self.assertEqual(self.heard(self.voice, aloud=True), (False, State.THINKING, ""))

    def test_a_whisper_never_reaches_the_recogniser(self):
        self.engine.settings.states = {"aloud": True}
        self.engine.status.state = State.THINKING
        self.engine.handle_audio(self.breath)
        self.engine._transcriber.transcribe.assert_not_called()

    def test_asleep_it_stays_asleep_and_says_nothing(self):
        self.engine.settings.states = {"aloud": True}
        self.engine.status.state, self.engine.status.last_heard = State.ASLEEP, ""
        self.assertTrue(self.engine._only_breath(self.breath))
        self.assertEqual((self.engine.status.state, self.engine.status.last_heard), (State.ASLEEP, ""))


class ThatWasANoise(unittest.TestCase):
    """What was written for a noise is taken back and its sound kept."""

    def setUp(self):
        import tempfile
        self.folder = os.path.join(tempfile.mkdtemp(), "noises")
        for patch in (mock.patch("dictation.engine.log"),
                      mock.patch("dictation.engine.config.NOISE_DIR", self.folder)):
            patch.start()
            self.addCleanup(patch.stop)
        self.program = Program()
        self.engine = Correct.engine(self, self.program)
        self.engine.settings.states = {"noise": True}   # off until it is ticked
        self.engine.lexicon, self.engine.keep_final = None, False
        self.engine._typed_sound = None

    def test_unticked_as_it_is_to_begin_with_the_words_are_typed(self):
        self.engine.settings.states = {}
        self.hear("Yeah.")
        self.hear("That was a noise.")
        self.assertEqual([name for name, _ in self.program.asked], ["context", "insert", "context", "insert"])
        self.assertEqual(self.kept(), [])

    def hear(self, text, sound=None):
        import numpy as np
        self.engine._heard_sound = (np.zeros(8000, dtype=np.float32) if sound is None else sound,
                                    text, "a-model", {"seconds": 0.5, "clear": 0.2, "sure": 0.5})
        self.engine.handle_text(text, True)

    def kept(self):
        return sorted(os.listdir(self.folder)) if os.path.isdir(self.folder) else []

    def test_the_words_are_taken_back_and_the_sound_kept(self):
        self.hear("Yeah.")
        self.hear("That was a noise.")
        self.assertEqual([name for name, _ in self.program.asked], ["context", "insert", "scratch"])
        self.assertEqual(len([name for name in self.kept() if name.endswith(".wav")]), 1)
        with open(os.path.join(self.folder, "list.txt"), encoding="utf-8") as f:
            self.assertIn("\tYeah.\t", f.read())

    def test_words_already_taken_back_are_not_taken_back_twice(self):
        self.hear("Yeah.")
        self.hear("Scratch that.")
        self.hear("That was a noise.")
        self.assertEqual([name for name, _ in self.program.asked].count("scratch"), 1)
        self.assertEqual(len([name for name in self.kept() if name.endswith(".wav")]), 1)

    def test_said_again_or_with_nothing_written_it_does_nothing(self):
        self.hear("That was a noise.")
        self.assertEqual((self.program.asked, self.kept()), ([], []))
        self.assertIn("nothing was just written", self.engine.status.last_heard)
        self.hear("Yeah.")
        self.hear("That was a noise.")
        self.hear("That was a noise.")
        self.assertEqual([name for name, _ in self.program.asked].count("scratch"), 1)

    def test_long_after_it_is_about_nothing(self):
        self.hear("Yeah.")
        self.engine._typed_sound = (*self.engine._typed_sound[:4], -1e9, False)
        self.hear("That was a noise.")
        self.assertEqual(self.kept(), [])


if __name__ == "__main__":
    unittest.main()
