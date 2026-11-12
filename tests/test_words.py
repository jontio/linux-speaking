import unittest

from dictation.commands import is_cancel
from dictation.words import Lexicon, repetitive


class Repetitive(unittest.TestCase):
    def test_one_word_over_and_over(self):
        self.assertTrue(repetitive("Say, " + " ".join(["say"] * 27)))
        self.assertTrue(repetitive("la di da la di da la di da la di da"))

    def test_ordinary_writing(self):
        self.assertFalse(repetitive(
            "It was a good day and we went to the park, and then the dog ran to the "
            "pond and back to the park, and the day was as good as the one before."))
        self.assertFalse(repetitive("It was a good day and we went to the park. say say say"))

    def test_too_short_to_tell(self):
        self.assertFalse(repetitive("no no no"))
        self.assertFalse(repetitive(""))


class Ordinary(unittest.TestCase):
    def test_common_words_need_no_dictionary(self):
        self.assertTrue(Lexicon().ordinary("the"))
        self.assertFalse(Lexicon().ordinary("jaunty"))
        self.assertFalse(Lexicon().has_dictionary)

    def test_dictionary_words_and_their_endings(self):
        lexicon = Lexicon(lower={"tune"})
        self.assertTrue(lexicon.ordinary("Tunes"))
        self.assertTrue(lexicon.has_dictionary)


class Cancel(unittest.TestCase):
    def test_said_alone(self):
        for phrase in ("Cancel.", "cancel that", "Never mind!", "Nevermind"):
            self.assertTrue(is_cancel(phrase), phrase)

    def test_not_in_a_sentence(self):
        self.assertFalse(is_cancel("cancel the meeting"))
        self.assertFalse(is_cancel("two"))


if __name__ == "__main__":
    unittest.main()
