import os
import tempfile
import unittest

from dictation import vocabulary
from dictation.settings import Settings
from dictation.words import Lexicon

WORDS = ("Jonti", "Linux Speaking", "clangd")
DICTIONARY = Lexicon(lower={"jaunty", "tune", "little", "walked", "step", "notes", "clang"},
                     capitalised={"John"})
BARE = Lexicon()  # no dictionary found, as on Windows


def settle(hinted, plain, before="", lexicon=DICTIONARY):
    return vocabulary.settle(hinted, plain, before, WORDS, lexicon)


class Parse(unittest.TestCase):
    def test_lines_and_commas(self):
        self.assertEqual(vocabulary.parse("Jonti\n  Linux   Speaking ,clangd\n\n"), WORDS)

    def test_drops_repeats_and_punctuation_only(self):
        self.assertEqual(vocabulary.parse("Jonti\njonti\n--\n"), ("Jonti",))

    def test_limits(self):
        many = vocabulary.parse("\n".join(f"word{n}" for n in range(100)))
        self.assertEqual(len(many), vocabulary.MAX_WORDS)
        self.assertEqual(len(vocabulary.parse("x" * 100)[0]), vocabulary.MAX_WORD_CHARS)

    def test_a_saved_list(self):
        self.assertEqual(vocabulary.parse(["Jonti", "clangd"]), ("Jonti", "clangd"))


class Hint(unittest.TestCase):
    def test_none(self):
        self.assertEqual(vocabulary.hint(()), "")

    def test_list(self):
        self.assertEqual(vocabulary.hint(WORDS), "Jonti, Linux Speaking, clangd. ")

    def test_stays_short(self):
        words = tuple("w" * 30 + str(n) for n in range(40))
        self.assertLessEqual(len(vocabulary.hint(words)), vocabulary.MAX_HINT_CHARS + 2)


class Mentions(unittest.TestCase):
    def test_found_whatever_the_case_and_punctuation(self):
        self.assertTrue(vocabulary.mentions("Cheers, jonti!", WORDS))
        self.assertTrue(vocabulary.mentions("That is Jonti's.", WORDS))
        self.assertTrue(vocabulary.mentions("I use Linux speaking daily", WORDS))

    def test_not_found(self):
        self.assertFalse(vocabulary.mentions("Thanks for the notes.", WORDS))
        self.assertFalse(vocabulary.mentions("Linux is speaking", WORDS))
        self.assertFalse(vocabulary.mentions("", WORDS))


class Settle(unittest.TestCase):
    def test_both_hearings_agree(self):
        self.assertEqual(settle("Cheers, Jonti.", "Cheers, Jonti."), "Cheers, Jonti.")

    def test_a_name_written_as_one_stands(self):
        self.assertEqual(settle("Cheers, Jonti!", "Cheers, John T."), "Cheers, Jonti!")
        self.assertEqual(settle("My name is Jonti and I live here.",
                                "My name is John T. and I live here."),
                         "My name is Jonti and I live here.")

    def test_an_ordinary_word_in_a_sentence_comes_back(self):
        self.assertEqual(settle("It was a Jonti little tune.", "It was a jaunty little tune."),
                         "It was a jaunty little tune.")
        self.assertEqual(settle("He walked with a jonti step.", "He walked with a jaunty step."),
                         "He walked with a jaunty step.")

    def test_also_without_a_dictionary(self):
        self.assertEqual(settle("It was a Jonti little tune.", "It was a jaunty little tune.",
                                lexicon=BARE), "It was a jaunty little tune.")

    def test_after_a_greeting_or_sign_off(self):
        self.assertEqual(settle("Cheers, Jonti!", "Cheers, jaunty!"), "Cheers, Jonti!")
        self.assertEqual(settle("Hi jonti, how are you", "Hi jaunty, how are you"),
                         "Hi Jonti, how are you")

    def test_the_cue_can_be_in_the_document(self):
        self.assertEqual(settle("Jonti went home", "jaunty went home", before="Thanks,\n"),
                         "Jonti went home")
        self.assertEqual(settle("Jonti went home", "jaunty went home", before="It was a"),
                         "jaunty went home")

    def test_spoken_punctuation_between_the_cue_and_the_name(self):
        for lexicon in (DICTIONARY, BARE):
            self.assertEqual(settle("Cheers, new line, Jonti", "Cheers, new line, jaunty",
                                    lexicon=lexicon), "Cheers, new line, Jonti")
            self.assertEqual(settle("Cheers comma new line Jonti.", "Cheers comma new line jaunty.",
                                    lexicon=lexicon), "Cheers comma new line Jonti.")
            self.assertEqual(settle("Thanks, new-paragraph jonti", "Thanks, new-paragraph jaunty",
                                    lexicon=lexicon), "Thanks, new-paragraph Jonti")
        self.assertEqual(settle("It was new line Jonti", "It was new line jaunty"),
                         "It was new line jaunty")

    def test_said_by_itself(self):
        self.assertEqual(settle("Jonti.", "Jaunty."), "Jonti.")
        self.assertEqual(settle("Jonti.", "John Deere"), "Jonti.")

    def test_start_of_a_sentence_goes_by_the_dictionary(self):
        self.assertEqual(settle("Jonti tunes are fun.", "Jaunty tunes are fun."),
                         "Jaunty tunes are fun.")
        self.assertEqual(settle("Jonti is here.", "John T. is here."), "Jonti is here.")
        self.assertEqual(settle("Fine. Jonti tunes.", "Fine. Jaunty tunes."),
                         "Fine. Jaunty tunes.")

    def test_start_of_a_sentence_without_a_dictionary_takes_the_name(self):
        self.assertEqual(settle("Jonti tunes are fun.", "Jaunty tunes are fun.", lexicon=BARE),
                         "Jonti tunes are fun.")

    def test_an_unknown_word_is_taken_as_the_name(self):
        self.assertEqual(settle("I saw jonti there", "I saw jonty there"), "I saw Jonti there")

    def test_a_word_from_nowhere_is_dropped(self):
        self.assertEqual(settle("Thanks Jonti.", "Thanks."), "Thanks.")
        self.assertEqual(settle("Jonti.", ""), "")

    def test_other_differences_follow_the_hinted_hearing(self):
        self.assertEqual(settle("Cheers, Jonti, see you soon!", "Cheers, John T. see you son."),
                         "Cheers, Jonti, see you soon!")

    def test_two_word_and_lower_case_entries(self):
        self.assertEqual(settle("I use linux speaking daily.", "I use Linux Speaking daily."),
                         "I use Linux Speaking daily.")  # both agree: the plain hearing
        self.assertEqual(settle("Start clangd first.", "Start clang D first."),
                         "Start clangd first.")
        self.assertEqual(settle("I like linux speaking a lot", "I like Lennox speaking a lot"),
                         "I like Linux Speaking a lot")

    def test_i_is_not_a_name(self):
        self.assertEqual(settle("Then Jonti walked", "Then I walked"), "Then I walked")


class Saved(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            settings = Settings.load(path)
            self.assertEqual(settings.words, ())
            settings.set_words(("Jonti", "clangd"))
            self.assertEqual(Settings.load(path).words, ("Jonti", "clangd"))

    def test_a_damaged_list_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w") as f:
                f.write('{"states": {}, "words": "Jonti"}')
            self.assertEqual(Settings.load(path).words, ())


if __name__ == "__main__":
    unittest.main()
