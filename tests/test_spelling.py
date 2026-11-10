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


if __name__ == "__main__":
    unittest.main()
