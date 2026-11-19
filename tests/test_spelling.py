import unittest

from dictation.spelling import apply, parse


def spell(*phrases):
    spelled, outcome = "", ""
    for phrase in phrases:
        spelled, outcome = apply(spelled, parse(phrase)[0])
        if outcome:
            break
    return spelled, outcome


class Letters(unittest.TestCase):
    def test_one_at_a_time(self):
        self.assertEqual(spell("J.", "O.", "N.", "T.", "I."), ("jonti", ""))

    def test_several_in_one_breath(self):
        self.assertEqual(spell("J-O-N-T-I."), ("jonti", ""))
        self.assertEqual(spell("J, O, N, T, I"), ("jonti", ""))
        self.assertEqual(spell("JONTI"), ("jonti", ""))

    def test_letter_names_and_radio_alphabet(self):
        self.assertEqual(spell("Bee.", "Why?", "Tea.", "You.")[0], "bytu")
        self.assertEqual(spell("Alpha, bravo, Charlie.")[0], "abc")
        self.assertEqual(spell("Zed.", "Double you.", "Okay.")[0], "zwk")

    def test_capitals(self):
        self.assertEqual(spell("Capital J-O-N-T-I.")[0], "Jonti")
        self.assertEqual(spell("cap a", "b", "uppercase c")[0], "AbC")

    def test_doubles_digits_and_symbols(self):
        self.assertEqual(spell("double L")[0], "ll")
        self.assertEqual(spell("A.", "Two.", "Hyphen.", "B.", "Space.", "C.")[0], "a2-b c")
        self.assertEqual(spell("x", "at sign", "y", "dot", "z")[0], "x@y.z")


class Editing(unittest.TestCase):
    def test_backspace_and_clear(self):
        self.assertEqual(spell("A.", "B.", "Backspace.")[0], "a")
        self.assertEqual(spell("A.", "B.", "Back space.", "C.")[0], "ac")
        self.assertEqual(spell("A.", "B.", "Scratch that.")[0], "a")
        self.assertEqual(spell("A.", "B.", "Start again.", "C.")[0], "c")

    def test_done_and_cancel(self):
        self.assertEqual(spell("A.", "B.", "Done."), ("ab", "done"))
        self.assertEqual(spell("A.", "That's it."), ("a", "done"))
        self.assertEqual(spell("A.", "Cancel.", "B."), ("a", "cancel"))
        self.assertEqual(spell("A.", "Never mind."), ("a", "cancel"))

    def test_words_it_does_not_understand_are_reported(self):
        steps, unknown = parse("A banana B")
        self.assertEqual((steps, unknown), (["a", "b"], ["banana"]))


class MakingALetterClear(unittest.TestCase):
    def test_the_word_that_says_which_letter_is_not_spelled(self):
        self.assertEqual(spell("B for bravo")[0], "b")
        self.assertEqual(spell("B as in boy, A like apple, T for tango.")[0], "bat")
        self.assertEqual(parse("four for five"), (["4", "5"], ["for"]))   # not after a figure

    def test_all_caps(self):
        self.assertEqual(spell("N A S A")[0], "nasa")
        self.assertEqual(spell("NASA")[0], "nasa")
        self.assertEqual(spell("All caps N A S A")[0], "NASA")
        self.assertEqual(spell("all caps NASA")[0], "NASA")
        self.assertEqual(spell("all caps a b", "c")[0], "ABc")   # for the one phrase

    def test_letters_with_marks_on_them(self):
        self.assertEqual(parse("é"), (["é"], []))
        self.assertEqual(spell("C A F É")[0], "café")
        self.assertEqual(spell("capital M, a macron, o, r, i")[0], "Māori")
        self.assertEqual(spell("e acute")[0], "é")

    def test_double_u_is_the_letter_w_however_it_is_written(self):
        self.assertEqual(spell("double-u", "Double you", "W", "Double U.")[0], "wwww")
        self.assertEqual(spell("T O double U N")[0], "town")
        self.assertEqual(spell("capital double U")[0], "W")
        # Two of the letter u are said one by one, as the other doubled letters can be.
        self.assertEqual(spell("V A C U U M")[0], "vacuum")
        self.assertEqual(spell("double L")[0], "ll")
        self.assertEqual(spell("B for bravo")[0], "b")

    def test_more_signs(self):
        self.assertEqual(spell("a comma b slash c colon d ampersand e plus f hash g")[0], "a,b/c:d&e+f#g")
        self.assertEqual(spell("x forward slash y back slash z")[0], "x/y\\z")
        self.assertEqual(spell("open bracket a close bracket question mark")[0], "(a)?")



class AsInBravo(unittest.TestCase):
    """The word is said so that the letter can't be mistaken: it is the word that settles it."""

    def spelled(self, said):
        steps, _ = parse(said)
        return apply("", steps)[0]

    def test_the_word_settles_the_letter_whatever_the_letter_was_heard_as(self):
        for said, want in (("B as in Bravo.", "b"), ("E as in bravo", "b"), ("D for delta", "d"),
                           ("B for delta", "d"), ("P like papa", "p"), ("capital D as in delta", "D"),
                           ("B for boy", "b"), ("V for boy", "b")):
            self.assertEqual(self.spelled(said), want, said)

    def test_and_where_the_letter_was_heard_as_words_altogether(self):
        # How a recogniser once wrote "B as in bravo" and "S as in sierra".
        self.assertEqual(self.spelled("We are in Bravo."), "b")
        self.assertEqual(self.spelled("S, I'm in Sierra."), "s")
        self.assertEqual(self.spelled("Capital, we are in Bravo"), "B")

    def test_letters_said_one_after_another_are_as_they_were(self):
        self.assertEqual(self.spelled("J, O, N."), "jon")
        self.assertEqual(self.spelled("T as in tango, I"), "ti")
        self.assertEqual(self.spelled("bravo echo"), "be")
        self.assertEqual(self.spelled("B E"), "be")



class HeardByTwoModels(unittest.TestCase):
    """The model best at letters, told to expect them, and the one chosen for dictation."""

    def goes_by(self, by_letters, by_words):
        from dictation.spelling import choose
        steps, _ = parse(choose(by_letters, by_words))
        return steps

    def test_a_word_of_command_goes_by_the_chosen_model(self):
        self.assertEqual(self.goes_by("Dumb.", "Done."), ["done"])
        self.assertEqual(self.goes_by("D.", "Done."), ["done"])
        self.assertEqual(self.goes_by("Console.", "Cancel."), ["cancel"])
        self.assertEqual(self.goes_by("B.", "Backspace."), ["backspace"])

    def test_letters_go_by_the_model_that_is_best_at_them(self):
        self.assertEqual(self.goes_by("N.", "And."), ["n"])
        self.assertEqual(self.goes_by("B.", "Be."), ["b"])
        self.assertEqual(self.goes_by("J, O, N.", "John"), ["j", "o", "n"])
        self.assertEqual(self.goes_by("Z.", ""), ["z"])

    def test_where_it_wrote_nothing_the_box_knows_the_other_is_taken_if_it_did(self):
        self.assertEqual(self.goes_by("", "N."), ["n"])
        self.assertEqual(self.goes_by("Yay.", "J."), ["j"])
        self.assertEqual(self.goes_by("Yay.", "Hooray."), [])      # neither: nothing is added


class WaysTheyAreMisheard(unittest.TestCase):
    def spelled(self, said):
        steps, _ = parse(said)
        return steps

    def test_n_written_as_a_word(self):
        self.assertEqual(self.spelled("In."), ["n"])
        self.assertEqual(self.spelled("An."), ["n"])
        self.assertEqual(self.spelled("J, O, in"), ["j", "o", "n"])
        self.assertEqual(self.spelled("I N"), ["i", "n"])           # two letters are two letters
        self.assertEqual(self.spelled("B as in bravo"), ["b"])      # and "as in" is as it was

    def test_done_and_cancel_as_a_recogniser_expecting_letters_wrote_them(self):
        for said in ("Dumb.", "dun", "Done."):
            self.assertEqual(self.spelled(said), ["done"], said)
        for said in ("Council.", "Console.", "Cancel."):
            self.assertEqual(self.spelled(said), ["cancel"], said)
        self.assertEqual(self.spelled("Markspace."), ["backspace"])


if __name__ == "__main__":
    unittest.main()
