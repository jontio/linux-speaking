import unittest

import numpy as np

from dictation import config, speech
from dictation.speech import not_speech, only_noise_words

SOUND = np.zeros(config.RATE, dtype=np.float32)  # a stand-in: the detectors below don't listen


def detector(some: float, clear: float):
    """A voice detector that finds `some` seconds of speech on its easy reading and
    `clear` on its usual one, and remembers what it was asked."""
    asked = []

    def spoken(audio, threshold):
        asked.append(threshold)
        return some if threshold == speech.SOME else clear
    spoken.asked = asked
    return spoken


class NoiseWords(unittest.TestCase):
    def test_what_parakeet_writes_for_a_noise(self):
        for text in ("Yeah.", "yeah", "Uh,", "Okay.", "Mm-hmm.", "Uh-huh", "Ha ha ha.", "Yeah, okay.", "OK", "Hmm"):
            self.assertTrue(only_noise_words(text), text)

    def test_anything_else_is_not(self):
        for text in ("Yes.", "No", "Yeah, I think so.", "Scratch that", "Comma", "New line", "Okay then",
                     "The", "I", "Thank you.", "", " . "):
            self.assertFalse(only_noise_words(text), text)


class SpeechOrNoise(unittest.TestCase):
    def test_a_sound_with_nothing_like_speech_in_it_is_a_noise_whatever_was_written(self):
        self.assertEqual(not_speech("Brilliant.", SOUND, detector(0.0, 0.0)), "nothing like speech in it")
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.0, 0.0)), "nothing like speech in it")

    def test_real_words_need_only_something_like_speech(self):
        spoken = detector(0.04, 0.0)
        self.assertEqual(not_speech("Scratch that", SOUND, spoken), "")
        self.assertEqual(spoken.asked, [speech.SOME])  # the usual reading isn't taken at all
        self.assertEqual(not_speech("Yes.", SOUND, detector(0.04, 0.0)), "")

    def test_a_noise_word_needs_clear_speech_behind_it(self):
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.3, 0.0)),
                         "a noise word, with no clear speech behind it")
        self.assertEqual(not_speech("Uh", SOUND, detector(0.3, speech.CLEAR_SECONDS)),
                         "a noise word, with no clear speech behind it")
        self.assertEqual(not_speech("Yeah.", SOUND, detector(0.4, 0.31)), "")  # really said
        self.assertEqual(not_speech("Okay.", SOUND, detector(0.4, 0.2)), "")

    def test_nothing_written_is_not_asked_about(self):
        spoken = detector(0.0, 0.0)
        self.assertEqual(not_speech("", SOUND, spoken), "")
        self.assertEqual(not_speech("  ", SOUND, spoken), "")
        self.assertEqual(spoken.asked, [])

    def test_without_a_detector_everything_stands(self):
        self.assertEqual(not_speech("Yeah.", SOUND, lambda audio, threshold: None), "")

    def test_a_detector_that_breaks_is_given_up_on_and_everything_stands(self):
        import sys
        import types
        was, kept = speech._unusable, sys.modules.get("faster_whisper")
        broken = types.ModuleType("faster_whisper")
        broken.vad = types.SimpleNamespace(
            VadOptions=lambda **options: options,
            get_speech_timestamps=lambda audio, options: (_ for _ in ()).throw(RuntimeError("no model")))
        sys.modules["faster_whisper"] = broken
        speech._unusable = False
        try:
            self.assertIsNone(speech.spoken(SOUND, speech.SOME))
            self.assertTrue(speech._unusable)
            self.assertEqual(not_speech("Yeah.", SOUND), "")
        finally:
            speech._unusable = was
            if kept is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = kept

    def test_the_detector_s_spans_are_added_up_in_seconds(self):
        import sys
        import types
        was, kept = speech._unusable, sys.modules.get("faster_whisper")
        asked = {}

        def get_speech_timestamps(audio, options):
            asked.update(options)
            return [{"start": 1600, "end": 4800}, {"start": 8000, "end": 9600}]

        stand_in = types.ModuleType("faster_whisper")
        stand_in.vad = types.SimpleNamespace(VadOptions=lambda **options: options,
                                             get_speech_timestamps=get_speech_timestamps)
        sys.modules["faster_whisper"] = stand_in
        speech._unusable = False
        try:
            self.assertAlmostEqual(speech.spoken(SOUND, 0.5), 0.3)
            self.assertEqual(asked["threshold"], 0.5)
            self.assertEqual(asked["speech_pad_ms"], 0)
        finally:
            speech._unusable = was
            if kept is None:
                del sys.modules["faster_whisper"]
            else:
                sys.modules["faster_whisper"] = kept


if __name__ == "__main__":
    unittest.main()
