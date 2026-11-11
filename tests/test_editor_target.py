import unittest

from dictation.editor_target import paragraph_end, paragraph_start, units

DOC = "one\ntwo\n\nthree\nfour\n\n\nfive\n"
#      0123 4567 8 9...


class ParagraphEnd(unittest.TestCase):
    def go(self, caret):
        return caret + paragraph_end(DOC[caret:])

    def test_from_inside_a_paragraph(self):
        self.assertEqual(self.go(0), 7)   # end of "two"
        self.assertEqual(self.go(5), 7)
        self.assertEqual(self.go(9), 19)  # end of "four"

    def test_already_at_the_end_goes_to_the_next(self):
        self.assertEqual(self.go(7), 19)
        self.assertEqual(self.go(19), 26)  # end of "five", past two blank lines

    def test_last_paragraph_stays(self):
        self.assertEqual(self.go(26), 26)
        self.assertEqual(self.go(len(DOC)), len(DOC))

    def test_from_a_blank_line(self):
        self.assertEqual(self.go(8), 19)


class ParagraphStart(unittest.TestCase):
    def go(self, caret):
        return paragraph_start(DOC[:caret])

    def test_from_inside_a_paragraph(self):
        self.assertEqual(self.go(6), 0)
        self.assertEqual(self.go(17), 9)   # start of "three"
        self.assertEqual(self.go(25), 22)  # start of "five"

    def test_already_at_the_start_goes_to_the_one_before(self):
        self.assertEqual(self.go(22), 9)
        self.assertEqual(self.go(9), 0)

    def test_first_paragraph_stays(self):
        self.assertEqual(self.go(0), 0)


class Units(unittest.TestCase):
    def test_counts_like_the_editor(self):
        self.assertEqual(units("abc"), 3)
        self.assertEqual(units("café"), 4)
        self.assertEqual(units("\U0001f600"), 2)


if __name__ == "__main__":
    unittest.main()
