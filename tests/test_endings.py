import unittest

import numpy as np

from dictation import endings
from dictation.formatting import fit

RATE = 16000
ON = endings.end_phrases(())            # everything switched on
DEFAULT = endings.end_phrases(("period",))


def sound(*parts):
    """Speech and silence in turn: sound(1.0, 0.4, 0.5) is a second of speech, a pause of
    0.4 s, then half a second of speech. A little room noise runs all through."""
    rng = np.random.default_rng(1)
    pieces = []
    for at, seconds in enumerate(parts):
        level = 0.3 if at % 2 == 0 else 0.004
        pieces.append(rng.normal(0, level, int(seconds * RATE)).astype(np.float32))
    return np.concatenate(pieces)


class Phrases(unittest.TestCase):
    def test_only_the_ones_that_end_a_sentence(self):
        self.assertEqual(set(ON), {"full stop", "period", "question mark", "exclamation mark",
                                   "exclamation point"})

    def test_switched_off_ones_are_left_out(self):
        self.assertNotIn("period", DEFAULT)
        self.assertIn("full stop", DEFAULT)


class WorthChecking(unittest.TestCase):
    def test_a_sign_of_whispers_own_at_the_end(self):
        self.assertTrue(endings.worth_checking("Is that right?", ON))
        self.assertTrue(endings.worth_checking("This is a test.", ON))
        self.assertTrue(endings.worth_checking('He said "go."', ON))

    def test_not_when_the_words_came_out(self):
        self.assertFalse(endings.worth_checking("This is a test. Period.", ON))
        self.assertFalse(endings.worth_checking("Is that right, question mark?", ON))
        self.assertFalse(endings.worth_checking("Full stop.", ON))

    def test_a_switched_off_phrase_does_not_count_as_said(self):
        self.assertTrue(endings.worth_checking("It was a long period.", DEFAULT))

    def test_not_without_a_sign_or_without_phrases(self):
        self.assertFalse(endings.worth_checking("This is a test", ON))
        self.assertFalse(endings.worth_checking("This is a test,", ON))
        self.assertFalse(endings.worth_checking("This is a test.", ()))
        self.assertFalse(endings.worth_checking("", ON))


class WithPhrase(unittest.TestCase):
    def test_the_words_go_back_in_place_of_the_sign(self):
        self.assertEqual(endings.with_phrase("Is that right?", "Question mark.", ON),
                         "Is that right question mark")
        self.assertEqual(endings.with_phrase("This is a test.", "period", ON), "This is a test period")
        self.assertEqual(endings.with_phrase("Great news!", "Exclamation-mark!", ON),
                         "Great news exclamation mark")

    def test_what_was_said_wins_over_the_sign_whisper_chose(self):
        fixed = endings.with_phrase("Is that right?", "Period.", ON)
        self.assertEqual(fit(fixed, "", "", spoken_off=()).text, "Is that right.")

    def test_ordinary_words_change_nothing(self):
        self.assertEqual(endings.with_phrase("Put it over there.", "There.", ON), "")
        self.assertEqual(endings.with_phrase("He left a question.", "Question.", ON), "")
        self.assertEqual(endings.with_phrase("This is a test.", "", ON), "")

    def test_a_switched_off_phrase_changes_nothing(self):
        self.assertEqual(endings.with_phrase("This is a test.", "Period.", DEFAULT), "")

    def test_fitted_it_types_the_sign(self):
        fixed = endings.with_phrase("Is that right?", "Question mark.", ON)
        self.assertEqual(fit(fixed, "", "", spoken_off=()).text, "Is that right?")
        self.assertEqual(fit("Is that right?", "", "", spoken_off=()).text, "Is that right")


class LoneSign(unittest.TestCase):
    """ "Question mark" said by itself, written down as "?" and nothing else."""
    SPOKEN = [("question mark", "?"), ("period", "."), ("comma", ","), ("exclamation mark", "!")]

    def test_only_signs(self):
        for text in ("?", " ? ", "?.", "...", ","):
            self.assertTrue(endings.only_signs(text), text)
        for text in ("", "  ", "Yes?", "a", "3."):
            self.assertFalse(endings.only_signs(text), text)

    def test_the_words_heard_alone_decide(self):
        self.assertEqual(endings.said_alone("?", "Question mark.", self.SPOKEN), "question mark")
        self.assertEqual(endings.said_alone(".", "Period", self.SPOKEN), "period")
        self.assertEqual(endings.said_alone("?", "Comma.", self.SPOKEN), "comma")  # what was said wins

    def test_a_question_mark_is_taken_at_its_word(self):
        self.assertEqual(endings.said_alone("?", "Question.", self.SPOKEN), "question mark")
        self.assertEqual(endings.said_alone("!", "", self.SPOKEN), "exclamation mark")

    def test_a_noise_written_as_a_full_stop_is_left_out(self):
        self.assertEqual(endings.said_alone(".", "", self.SPOKEN), "")
        self.assertEqual(endings.said_alone(".", "Hmm.", self.SPOKEN), "")
        self.assertEqual(endings.said_alone(",", "the", self.SPOKEN), "")

    def test_switched_off_phrases_are_not_put_in(self):
        self.assertEqual(endings.said_alone("?", "Question mark", [("period", ".")]), "")


class TrailingBurst(unittest.TestCase):
    def test_a_short_burst_after_a_pause(self):
        start, end = endings.trailing_burst(sound(1.2, 0.4, 0.5, 0.3), RATE)
        self.assertAlmostEqual(start, 1.6, delta=0.05)
        self.assertAlmostEqual(end, 2.1, delta=0.05)

    def test_silence_after_it_does_not_matter(self):
        self.assertIsNotNone(endings.trailing_burst(sound(1.2, 0.4, 0.5, 0.65), RATE))
        self.assertIsNotNone(endings.trailing_burst(sound(1.2, 0.4, 0.5), RATE))

    def test_no_pause_no_burst(self):
        self.assertIsNone(endings.trailing_burst(sound(2.0, 0.3), RATE))
        self.assertIsNone(endings.trailing_burst(sound(1.2, 0.1, 0.5), RATE))  # a gap inside a word

    def test_a_gap_inside_the_last_words_keeps_them_together(self):
        start, end = endings.trailing_burst(sound(1.2, 0.4, 0.3, 0.08, 0.3), RATE)  # "question mark"
        self.assertAlmostEqual(start, 1.6, delta=0.05)
        self.assertAlmostEqual(end, 2.28, delta=0.05)

    def test_too_long_or_too_short_to_be_punctuation(self):
        self.assertIsNone(endings.trailing_burst(sound(1.2, 0.4, 2.0), RATE))
        self.assertIsNone(endings.trailing_burst(sound(1.2, 0.4, 0.1), RATE))

    def test_nothing_before_the_pause(self):
        self.assertIsNone(endings.trailing_burst(sound(0.5), RATE))
        self.assertIsNone(endings.trailing_burst(np.zeros(RATE, dtype=np.float32), RATE))
        self.assertIsNone(endings.trailing_burst(np.zeros(100, dtype=np.float32), RATE))

    def test_cut_keeps_a_little_either_side(self):
        audio = sound(1.2, 0.4, 0.5, 0.3)
        piece = endings.cut(audio, (1.6, 2.1), RATE)
        self.assertAlmostEqual(len(piece) / RATE, 0.5 + 2 * endings.PAD, delta=0.01)
        self.assertEqual(len(endings.cut(audio, (0.05, 0.4), RATE)), int((0.4 + endings.PAD) * RATE))


if __name__ == "__main__":
    unittest.main()
