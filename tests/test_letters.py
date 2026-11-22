"""The opening and the end of a letter as they are said (letters.py)."""
import unittest

from dictation import letters, tidy
from dictation.formatting import LINE, fit


class Opening(unittest.TestCase):
    def test_common_after_a_greeting_and_a_name_is_the_comma_said(self):
        # (The comma said takes the place of the recogniser's mark for the pause before it.)
        self.assertEqual(letters.said("Hi rick, common new paragraph."), "Hi Rick comma new paragraph.")
        self.assertEqual(letters.said("Hello Sam common"), "Hello Sam comma")
        self.assertEqual(fit("Hi rick, common new paragraph.", "", "").text, "Hi Rick, ")

    def test_however_the_recogniser_marked_the_pauses(self):
        from dictation.formatting import PARAGRAPH
        for heard, meant in (
                ("Hi, Rick, common new paragraph.", "Hi, Rick comma new paragraph."),   # as reported
                ("Hi, rick, common new paragraph.", "Hi, Rick comma new paragraph."),
                ("Hi, Rick. Common new paragraph.", "Hi, Rick comma new paragraph."),
                ("Hi, Rick, common, new paragraph.", "Hi, Rick comma, new paragraph."),
                ("Hi Rick, coma, new paragraph.", "Hi Rick comma, new paragraph."),
                ("Hello, Sam, common new line.", "Hello, Sam comma new line."),
                ("Dear Dr Smith, common new paragraph.", "Dear Dr Smith comma new paragraph."),
                ("Cheers. Common.", "Cheers comma.")):
            self.assertEqual(letters.said(heard), meant, heard)
        for raw in ("Hi, Rick, common new paragraph.", "Hi, Rick. Common new paragraph.",
                    "Hi, Rick, common, new paragraph."):
            self.assertEqual(fit(raw, "", "", greeting_comma=False).text, "Hi Rick," + PARAGRAPH, raw)
            self.assertEqual(fit(raw, "", "").text, "Hi, Rick," + PARAGRAPH, raw)

    def test_after_all_or_everyone_or_hi_by_itself_before_a_break(self):
        for heard, meant in (("Hi all, common new paragraph.", "Hi all comma new paragraph."),
                             ("Hello everyone common new paragraph.", "Hello everyone comma new paragraph."),
                             ("Hi there, common", "Hi there comma"),
                             ("Hi, common new paragraph.", "Hi comma new paragraph.")):
            self.assertEqual(letters.said(heard), meant, heard)

    def test_and_after_a_sign_off(self):
        self.assertEqual(letters.said("Cheers, common"), "Cheers comma")
        self.assertEqual(letters.said("Kind regards common"), "Kind regards comma")

    def test_the_name_after_a_greeting_gets_its_capital(self):
        self.assertEqual(letters.said("Hi rick,"), "Hi Rick,")
        self.assertEqual(letters.said("Dear sam"), "Dear Sam")
        self.assertEqual(letters.said("Hi, rick,"), "Hi, Rick,")

    def test_nowhere_else(self):
        for left in ("It is a common mistake.", "Hello there, common ground", "hi rick how are you",
                     "We have a lot in common", "Hi there,", "Hi Rick. Common sense is rare.",
                     "Hi how common is that?", "Hello, common ground matters.",
                     "Cheers. Common sense says no.", "Hi everyone, common questions are below."):
            self.assertEqual(letters.said(left), left, left)


class SignOff(unittest.TestCase):
    def fixed(self, before, phrase, names=()):
        text, delete, changes, whole = tidy.amend(phrase, 0, before, before, [letters.signoff(names)])
        return before[:len(before) - delete] + text

    def test_a_misheard_sign_off_enter_and_a_name(self):
        self.assertEqual(self.fixed("All the best.\n\nChairs", ", enter, Jonti", ("Jonti",)),
                         "All the best.\n\nCheers," + LINE + "Jonti")

    def test_a_sign_off_heard_rightly(self):
        self.assertEqual(self.fixed("See you soon.\n\nRegards", " new line Sam"), "See you soon.\n\nRegards," + LINE + "Sam")

    def test_left_alone_elsewhere(self):
        for before, phrase in (("We bought four", " chairs, enter, the room"),
                               ("Please", " enter your name"),
                               ("The chairs", " enter, John")):
            self.assertEqual(self.fixed(before, phrase), before + phrase, (before, phrase))



class CommaSaidAfterAPause(unittest.TestCase):
    """ "Hi Rick", a pause, and "comma new paragraph": the comma heard as "common" in a phrase of
    its own, with the greeting on the line before it."""

    def test_after_a_greeting_and_a_name_or_a_sign_off(self):
        from dictation.letters import said
        for before, heard, meant in (("Hi Rick", "Common new paragraph.", "comma new paragraph."),
                                     ("Hi Rick,", "Common.", "comma."),
                                     ("Dear Sam", "Coma.", "comma."),
                                     ("Cheers", "Common.", "comma."),
                                     ("Hi Rick", "Common, how are you?", "comma, how are you?"),
                                     ("Hi, Rick", "Common new paragraph.", "comma new paragraph."),
                                     ("Dear Dr Smith.", "Common new paragraph.", "comma new paragraph."),
                                     ("Hi all", "Common new paragraph.", "comma new paragraph."),
                                     ("Hi there", "Common.", "comma."),
                                     ("Hi", "Common new paragraph.", "comma new paragraph.")):
            self.assertEqual(said(heard, before), meant, (before, heard))

    def test_not_where_it_is_a_word(self):
        from dictation.letters import said
        for before, heard in (("Hi Rick", "Common sense is rare."),
                              ("We have a lot in", "common new paragraph."),
                              ("Hi how", "Common."),
                              ("Hi all", "Common sense says no."),
                              ("", "Common new paragraph.")):
            self.assertEqual(said(heard, before), heard, (before, heard))

if __name__ == "__main__":
    unittest.main()
