"""Which model does the listening: the one that was chosen, for everything it can do."""
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
        ears._code_name, ears._code_used = "", 0.0
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
            ears._code_used = time.monotonic() - config.CODE_MODEL_IDLE - 1
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


if __name__ == "__main__":
    unittest.main()
