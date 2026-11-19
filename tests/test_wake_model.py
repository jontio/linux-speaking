"""Which model does the listening: the one that was chosen, for everything it can do."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from dictation import config
from dictation.engine import Transcriber


class OneModelDoesTheListening(unittest.TestCase):
    def ears(self, chosen: str, installed=("small.en", "medium.en")):
        ears = Transcriber.__new__(Transcriber)
        ears.lock, ears._guests = threading.RLock(), []
        ears._loaded = {}
        ears.helper_name, ears.dictation_name = "small.en", chosen
        ears._extras = {}
        ears._letter_times, ears._letter_speeds = {}, None
        folder = tempfile.mkdtemp()      # what is found of this computer's speed is kept here
        self.addCleanup(shutil.rmtree, folder, True)
        speeds = mock.patch.object(config, "SPELL_SPEEDS", os.path.join(folder, "spelling-speed.json"))
        speeds.start()
        self.addCleanup(speeds.stop)
        ears.quick, ears.speech_only = False, True
        ears.not_speech, ears.ignored, ears.left_out = 0.3, "before", ""
        ears._is_transducer = lambda name: name.startswith("parakeet")
        ears._model = lambda name: ears._loaded.setdefault(name, "whisper")
        ears._transducer = lambda name: ears._loaded.setdefault(name, "parakeet")
        self.asked = []

        def by_transducer(name, audio, sure=False, speech_only=None):
            self.asked.append(("parakeet", name))
            return "Wake up."

        def by_whisper(audio, awake, prompt, model, quickly):
            ears._model(model)
            self.asked.append(("whisper", model, awake))
            return "Wake up."

        ears._by_transducer, ears._transcribe = by_transducer, by_whisper
        kinds = mock.patch("dictation.engine.models.kind",
                           lambda folder, name: "whisper" if name in installed else "")
        kinds.start()
        self.addCleanup(kinds.stop)
        return ears

    def test_a_parakeet_listens_for_wake_up_itself(self):
        ears = self.ears("parakeet-mine")
        self.assertEqual(ears.transcribe([0.0] * 16000, False), "Wake up.")
        self.assertEqual(self.asked, [("parakeet", "parakeet-mine")])
        self.assertEqual((ears.not_speech, ears.ignored), (0.0, ""))   # nothing left of the phrase before

    def test_so_does_a_whisper_model_whichever_one_was_chosen(self):
        for chosen in ("small.en", "medium.en", "base.en"):
            ears = self.ears(chosen)
            ears.transcribe([0.0] * 16000, False)
            self.assertEqual(self.asked, [("whisper", chosen, False)], chosen)

    def test_there_is_no_switch_for_it(self):
        ears = self.ears("parakeet-mine")
        self.assertFalse(hasattr(ears, "wake_same"))
        with self.assertRaises(TypeError):
            ears.transcribe([0.0] * 16000, False, wake_same=False)

    def test_sound_too_long_to_be_wake_up_is_not_listened_to(self):
        ears = self.ears("parakeet-mine")
        long = [0.0] * int((config.WAKE_MAX_SECONDS + 1) * config.RATE)
        self.assertEqual(ears.transcribe(long, False), "")
        self.assertEqual(self.asked, [])

    def test_a_sound_left_out_as_a_noise_is_kept_for_the_log(self):
        ears = self.ears("parakeet-mine")

        def noise(name, audio, sure=False, speech_only=None):
            ears.left_out = "Yeah."
            return ""

        ears._by_transducer = noise
        self.assertEqual(ears.transcribe([0.0] * 16000, False), "")
        self.assertEqual((ears.not_speech, ears.ignored), (1.0, "Yeah."))

    def test_what_leans_on_a_hint_goes_to_the_helper_of_a_parakeet(self):
        ears = self.ears("parakeet-mine")
        ears.transcribe([0.0] * 16000, True)                          # dictation: itself
        ears.transcribe([0.0] * 16000, True, "letters", exact=True)   # the spelling box
        ears._hear_short = lambda model, audio: self.asked.append(("alone", model)) or "comma"
        ears._short_window = True
        ears.hear_alone([0.0] * 8000)                                 # the short second listen
        self.assertEqual(self.asked, [("parakeet", "parakeet-mine"), ("whisper", "small.en", True),
                                      ("alone", "whisper")])
        self.assertEqual(sorted(ears._loaded), ["small.en"])          # and only the helper was needed

    def test_with_a_whisper_model_chosen_it_does_those_too_and_no_helper_is_loaded(self):
        ears = self.ears("medium.en")
        ears.use("medium.en")
        ears.transcribe([0.0] * 16000, True, "letters", exact=True)
        ears.transcribe([0.0] * 16000, True, "names", exact=True, code=True)
        self.assertEqual(self.asked, [("whisper", "medium.en", True)] * 2)
        self.assertEqual(sorted(ears._loaded), ["medium.en"])         # one model, and that is all


class TheWhisperForSourceCode(unittest.TestCase):
    ears = OneModelDoesTheListening.ears

    def test_it_is_a_bigger_one_where_that_is_installed_and_loaded_only_when_code_is_dictated(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        self.assertEqual(sorted(ears._loaded), ["parakeet-mine", "small.en"])    # no Medium yet
        with mock.patch.object(config, "CODE_MODELS", ("medium.en",)):
            ears.transcribe([0.0] * 16000, True, "names", exact=True, code=True)
        self.assertEqual(self.asked, [("whisper", "medium.en", True)])
        self.assertIn("medium.en", ears._loaded)
        ears.transcribe([0.0] * 16000, True, "letters", exact=True)              # spelling: still the helper
        self.assertEqual(self.asked[-1], ("whisper", "small.en", True))

    def test_without_one_installed_the_helper_does_it(self):
        ears = self.ears("parakeet-mine", installed=("small.en",))
        with mock.patch.object(config, "CODE_MODELS", ("medium.en",)):
            ears.transcribe([0.0] * 16000, True, "names", exact=True, code=True)
        self.assertEqual(self.asked, [("whisper", "small.en", True)])

    def test_it_is_let_go_when_no_code_has_been_dictated_for_a_while(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        with mock.patch.object(config, "CODE_MODELS", ("medium.en",)):
            ears.transcribe([0.0] * 16000, True, "names", exact=True, code=True)
            ears.transcribe([0.0] * 16000, True)                      # soon after: kept
            self.assertIn("medium.en", ears._loaded)
            ears._extras["medium.en"] = time.monotonic() - config.CODE_MODEL_IDLE - 1
            ears.transcribe([0.0] * 16000, True)                      # much later: let go
        self.assertEqual(sorted(ears._loaded), ["parakeet-mine", "small.en"])

    def test_changing_the_model_lets_go_of_what_the_last_one_needed(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        with mock.patch.object(config, "CODE_MODELS", ("medium.en",)):
            ears.transcribe([0.0] * 16000, True, "names", exact=True, code=True)
        ears.use("base.en")                                           # a Whisper model now
        self.assertEqual(sorted(ears._loaded), ["base.en"])
        ears.use("parakeet-other")
        self.assertEqual(sorted(ears._loaded), ["parakeet-other", "small.en"])



class TheSpellingBox(unittest.TestCase):
    """Heard by the model that tells letters apart best, whichever is chosen for dictation."""

    ears = OneModelDoesTheListening.ears

    def spelled(self, ears):
        heard = []
        ears._short_window = True
        ears._hear_short = lambda model, audio, hint="", beam=0: \
            heard.append(("short", model, hint)) or "B."
        return heard

    def test_medium_hears_it_where_it_is_installed_through_the_short_window_with_the_hint(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        heard = self.spelled(ears)
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en", "small.en")):
            self.assertEqual(ears.transcribe([0.0] * 16000, True, "Spelling: J, O.", exact=True, letters=True), "B.")
        self.assertEqual(heard, [("short", "whisper", "Spelling: J, O.")])
        self.assertIn("medium.en", ears._loaded)                # loaded for it, now
        self.assertEqual(self.asked, [("parakeet", "parakeet-mine")])   # and the chosen model heard it too

    def test_the_chosen_model_settles_a_word_of_command_and_medium_the_letters(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        ears._short_window = True
        said = {"medium": "Dumb.", "chosen": "Done."}
        ears._hear_short = lambda model, audio, hint="", beam=0: said["medium"]
        ears._by_transducer = lambda name, audio, sure=False, speech_only=None: said["chosen"]
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en",)):
            hear = lambda: ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True)
            self.assertEqual(hear(), "Done.")                    # "done", which Medium took for "dumb"
            said.update(medium="N.", chosen="And.")
            self.assertEqual(hear(), "N.")                       # a letter goes by Medium
            said.update(medium="", chosen="J.")
            self.assertEqual(hear(), "J.")                       # unless Medium wrote nothing

    def test_a_chosen_model_that_cannot_be_asked_leaves_it_to_medium(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        ears._short_window = True
        ears._hear_short = lambda model, audio, hint="", beam=0: "B."

        def broken(name, audio, sure=False, speech_only=None):
            raise RuntimeError("it fell over")
        ears._by_transducer = broken
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en",)), mock.patch("dictation.engine.log"):
            self.assertEqual(ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True), "B.")

    def test_without_medium_small_does_it(self):
        ears = self.ears("parakeet-mine", installed=("small.en",))
        ears.use("parakeet-mine")
        self.spelled(ears)
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en", "small.en")):
            ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True)
        self.assertEqual(sorted(ears._loaded), ["parakeet-mine", "small.en"])

    def test_with_a_whisper_model_chosen_medium_still_hears_the_letters(self):
        ears = self.ears("small.en")
        ears.use("small.en")
        self.spelled(ears)
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en", "small.en")):
            ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True)
        self.assertEqual(sorted(ears._loaded), ["medium.en", "small.en"])

    def test_it_is_let_go_when_the_box_has_not_been_used_for_a_while(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        self.spelled(ears)
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en", "small.en")):
            ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True)
            ears._extras["medium.en"] = time.monotonic() - config.CODE_MODEL_IDLE - 1
            ears.transcribe([0.0] * 16000, True)
        self.assertEqual(sorted(ears._loaded), ["parakeet-mine", "small.en"])

    def test_where_the_short_window_cannot_be_had_it_is_heard_the_usual_way(self):
        ears = self.ears("parakeet-mine")
        ears.use("parakeet-mine")
        ears._short_window = True

        def refuses(model, audio, hint="", beam=0):
            raise RuntimeError("this library insists on the half minute")
        ears._hear_short = refuses
        with mock.patch.object(config, "SPELL_MODELS", ("medium.en",)), mock.patch("dictation.engine.log"):
            self.assertEqual(ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True), "Wake up.")
        self.assertEqual(self.asked[0], ("whisper", "medium.en", True))
        self.assertFalse(ears._short_window)


class AComputerThatIsSlowOverALetter(unittest.TestCase):
    """The best model for letters is no use if each one is waited for: how long it takes
    here is measured as the box is used, and one that is too slow gives way to the next."""

    def ears(self, chosen="parakeet-mine", takes=None, installed=("small.en", "medium.en")):
        ears = OneModelDoesTheListening.ears(self, chosen, installed)
        ears._model = lambda name: ears._loaded.setdefault(name, name)   # known by its name
        ears.use(chosen)
        ears._short_window = True
        self.takes = dict(takes or {})     # seconds over a letter: one number, or one for each time
        self.now, self.heard = 1000.0, []

        def hear_short(model, audio, hint="", beam=0):
            self.heard.append((model, beam))
            took = self.takes.get(model, 0.1)
            self.now += took.pop(0) if isinstance(took, list) else took
            return "B."
        ears._hear_short = hear_short
        for patch in (mock.patch("dictation.engine.time.monotonic", lambda: self.now),
                      mock.patch.object(config, "SPELL_MODELS", ("medium.en", "small.en")),
                      mock.patch.object(config, "SPELL_SLOW", 1.2),
                      mock.patch("dictation.engine.log")):
            patch.start()
            self.addCleanup(patch.stop)
        self.letter = lambda: ears.transcribe([0.0] * 16000, True, "hint", exact=True, letters=True)
        return ears

    def kept(self):
        with open(config.SPELL_SPEEDS, encoding="utf-8") as f:
            return json.load(f)

    def test_a_model_that_is_too_slow_here_gives_way_to_the_next(self):
        ears = self.ears(takes={"medium.en": 2.5, "small.en": 0.4})
        for _ in range(4):               # the one that loaded it isn't counted: then three
            self.letter()
        self.assertEqual([model for model, _ in self.heard], ["medium.en"] * 4)
        self.assertNotIn("medium.en", ears._loaded)       # let go: it is the biggest thing in memory
        self.letter()
        self.assertEqual(self.heard[-1][0], "small.en")
        self.assertEqual(self.kept(), {"medium.en": 2.5})

    def test_a_quick_one_stays(self):
        ears = self.ears(takes={"medium.en": 0.8})
        for _ in range(6):
            self.letter()
        self.assertEqual([model for model, _ in self.heard], ["medium.en"] * 6)
        self.assertEqual(self.kept(), {"medium.en": 0.8})
        self.assertIn("medium.en", ears._loaded)

    def test_a_computer_that_was_busy_for_one_letter_is_not_a_slow_computer(self):
        self.ears(takes={"medium.en": [0.1, 3.0, 0.9, 2.8, 0.9, 0.9]})
        for _ in range(6):
            self.letter()
        self.assertEqual([model for model, _ in self.heard], ["medium.en"] * 6)
        self.assertEqual(self.kept(), {"medium.en": 0.9})

    def test_the_hearing_that_loaded_the_model_is_no_measure_of_it(self):
        self.ears(takes={"medium.en": [9.0, 0.8, 0.8, 0.8, 0.8]})
        for _ in range(5):
            self.letter()
        self.assertEqual(self.kept(), {"medium.en": 0.8})

    def test_what_was_found_is_kept_for_the_next_time_the_program_is_started(self):
        ears = self.ears(takes={"medium.en": 2.5})
        with open(config.SPELL_SPEEDS, "w", encoding="utf-8") as f:
            json.dump({"medium.en": 2.5}, f)
        self.letter()
        self.assertEqual(self.heard, [("small.en", 1)])
        self.assertNotIn("medium.en", ears._loaded)       # never loaded at all

    def test_where_all_of_them_are_slow_the_smallest_hears_it(self):
        self.ears()
        with open(config.SPELL_SPEEDS, "w", encoding="utf-8") as f:
            json.dump({"medium.en": 4.0, "small.en": 1.5}, f)
        self.letter()
        self.assertEqual(self.heard, [("small.en", 1)])

    def test_a_file_that_cannot_be_read_is_as_if_nothing_had_been_found(self):
        self.ears()
        with open(config.SPELL_SPEEDS, "w", encoding="utf-8") as f:
            f.write("{not what was written")
        self.letter()
        self.assertEqual(self.heard, [("medium.en", 1)])

    def test_a_chosen_whisper_that_is_too_slow_is_not_asked_as_well(self):
        ears = self.ears(chosen="medium.en")
        with open(config.SPELL_SPEEDS, "w", encoding="utf-8") as f:
            json.dump({"medium.en": 3.0}, f)
        self.letter()
        self.assertEqual(self.heard, [("small.en", 1)])   # and not Medium after it
        self.assertIn("medium.en", ears._loaded)          # which is still what dictation is heard by

    def test_a_chosen_whisper_is_timed_as_it_hears_the_box_beside_medium(self):
        self.ears(chosen="small.en", takes={"medium.en": 0.8, "small.en": 0.3})
        for _ in range(4):
            self.letter()
        self.assertEqual(self.kept(), {"small.en": 0.3, "medium.en": 0.8})

    def test_a_letter_is_one_piece_so_one_way_of_writing_it_is_followed(self):
        self.ears()
        self.letter()
        self.assertEqual(self.heard, [("medium.en", 1)])

    def test_the_model_is_loaded_as_the_box_is_opened(self):
        ears = self.ears()
        ears.ready_for_letters()
        self.assertIn("medium.en", ears._loaded)
        self.assertEqual(self.heard, [])
        for _ in range(3):               # and so the first letter is a measure already
            self.letter()
        self.assertEqual(self.kept(), {"medium.en": 0.1})

    def test_a_model_that_cannot_be_loaded_then_is_only_noted(self):
        ears = self.ears()

        def falls_over(name):
            raise OSError("no room")
        ears._model = falls_over
        ears.ready_for_letters()         # nothing raised: the letter will say so itself


class TheBoxIsOpened(unittest.TestCase):
    """The engine has the model for letters loaded while the box is opening."""

    def engine(self, ears, offload=None):
        from dictation.engine import Engine
        engine = Engine.__new__(Engine)
        engine._transcriber, engine._offload = ears, offload
        return engine

    def test_it_is_asked_for_to_one_side(self):
        asked = threading.Event()
        ears = mock.Mock()
        ears.ready_for_letters = asked.set
        self.engine(ears)._letters_ahead()
        self.assertTrue(asked.wait(5))

    def test_not_where_another_computer_does_the_listening(self):
        ears = mock.Mock()
        self.engine(ears, offload=object())._letters_ahead()
        time.sleep(0.05)
        ears.ready_for_letters.assert_not_called()

    def test_a_recogniser_that_has_no_such_thing_is_left_alone(self):
        self.engine(object())._letters_ahead()
        self.engine(None)._letters_ahead()


if __name__ == "__main__":
    unittest.main()
