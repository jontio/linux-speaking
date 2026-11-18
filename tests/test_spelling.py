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


if __name__ == "__main__":
    unittest.main()
