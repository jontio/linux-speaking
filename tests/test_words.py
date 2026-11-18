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


class NamesTheDictionaryKnows(unittest.TestCase):
    """A name is not an everyday word with an ending on it: "James" is not "jam" + "es"."""

    def setUp(self):
        self.lexicon = Lexicon(lower={"jam", "wale", "mark", "said"},
                               capitalised={"James", "Wales", "Mark"})

    def test_a_listed_name_keeps_its_capital(self):
        self.assertEqual(self.lexicon.decapitalise("James"), "James")
        self.assertEqual(self.lexicon.decapitalise("Wales,"), "Wales,")

    def test_unless_it_is_an_everyday_word_as_well(self):
        self.assertEqual(self.lexicon.decapitalise("Mark"), "mark")
        self.assertEqual(self.lexicon.decapitalise("Said"), "said")
        self.assertEqual(self.lexicon.decapitalise("Jams"), "jams")

    def test_or_an_everyday_form_that_somebody_is_also_called(self):
        # A real dictionary lists "States", "Fields", "Powers" and "Weeks" as names.
        lexicon = Lexicon(lower={"state", "field", "power", "week", "mile", "number", "rule", "act",
                                 "window", "jam", "wale", "holm"},
                          capitalised={"States", "Fields", "Powers", "Weeks", "Miles", "Numbers",
                                       "Rules", "Acts", "Windows", "James", "Wales", "Holmes"})
        for word in ("States", "Fields", "Powers", "Weeks", "Miles", "Numbers", "Rules", "Acts"):
            self.assertEqual(lexicon.decapitalise(word), word.lower(), word)
        self.assertEqual(lexicon.decapitalise("Fields,"), "fields,")
        # A name that is seldom anything else keeps its capital: and so does the system.
        for name in ("James", "Wales", "Holmes", "Windows"):
            self.assertEqual(lexicon.decapitalise(name), name)

    def test_a_british_spelling_that_an_american_dictionary_has_only_as_a_name(self):
        lexicon = Lexicon(lower={"gray", "armor", "tire"}, capitalised={"Grey", "Armour", "Tyre"})
        self.assertEqual(lexicon.decapitalise("Grey"), "grey")
        self.assertEqual(lexicon.decapitalise("Armour"), "armour")
        self.assertEqual(lexicon.decapitalise("Tyre"), "tyre")


class TwoSpellingsOfOneWord(unittest.TestCase):
    def test_folded_to_one(self):
        from dictation.words import fold
        for british, american in (("colour", "color"), ("favourite", "favorite"), ("realise", "realize"),
                                  ("organisation", "organization"), ("analyse", "analyze"),
                                  ("centre", "center"), ("grey", "gray")):
            self.assertEqual(fold(british), fold(american), british)
        for word in ("four", "hour", "your", "our", "this", "is"):
            self.assertEqual(fold(word), word)

    def test_the_other_spelling_is_offered_for_looking_up(self):
        from dictation.words import spellings
        self.assertIn("colour", spellings("color"))
        self.assertIn("color", spellings("colour"))
        self.assertIn("realise", spellings("realize"))
        self.assertIn("centre", spellings("center"))
        self.assertEqual(spellings("doctor"), frozenset())   # there is no "doctour"
        self.assertEqual(spellings("cat"), frozenset())

    def test_either_dictionary_knows_both(self):
        british, american = Lexicon(lower={"colour", "realise"}), Lexicon(lower={"color", "realize"})
        for lexicon in (british, american):
            for word in ("Color", "colour", "Colours", "realized", "Realise"):
                self.assertTrue(lexicon.ordinary(word), word)
            self.assertEqual(lexicon.decapitalise("Color"), "color")
            self.assertFalse(lexicon.ordinary("Taylor"))


class WordsThatLeadUpToAName(unittest.TestCase):
    def test_will_can_be_a_name_and_the_cannot(self):
        from dictation.words import LEAD_INS
        self.assertNotIn("will", LEAD_INS)
        self.assertNotIn("new", LEAD_INS)
        for word in ("the", "in", "ask", "maybe", "when"):
            self.assertIn(word, LEAD_INS)

    def test_verbs_that_a_dictionary_also_has_as_names_lead_up_to_one(self):
        # "I" and then "Hope Sarah is well": the capital is the recogniser's, not a name's.
        from dictation.words import LEAD_INS
        for word in ("hope", "help", "love", "left", "best"):
            self.assertIn(word, LEAD_INS)


if __name__ == "__main__":
    unittest.main()
