import unittest

from dictation.editor_target import (
    line_move, line_span, paragraph_end, paragraph_start, units, words_left, words_right,
)

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


class Words(unittest.TestCase):
    TEXT = "The quick, brown fox.\nNext line"

    def left(self, caret, count):
        return caret - words_left(self.TEXT[:caret], count)

    def right(self, caret, count):
        return caret + words_right(self.TEXT[caret:], count)

    def test_left(self):
        end = len(self.TEXT)
        self.assertEqual(self.TEXT[self.left(end, 1):], "line")
        self.assertEqual(self.TEXT[self.left(end, 2):], "Next line")
        self.assertEqual(self.TEXT[self.left(end, 3):], "fox.\nNext line")
        self.assertEqual(self.left(end, 50), 0)
        self.assertEqual(self.left(7, 1), 4)  # from inside "quick" to its start

    def test_right(self):
        self.assertEqual(self.TEXT[self.right(0, 1):], "quick, brown fox.\nNext line")
        self.assertEqual(self.TEXT[self.right(0, 2):], "brown fox.\nNext line")
        self.assertEqual(self.TEXT[self.right(0, 4):], "Next line")
        self.assertEqual(self.right(0, 50), len(self.TEXT))


class Lines(unittest.TestCase):
    TEXT = "first\nsecond line\n\nfourth"

    def test_span(self):
        self.assertEqual(line_span(self.TEXT, 8), (6, 17))
        self.assertEqual(line_span(self.TEXT, 0), (0, 5))
        self.assertEqual(line_span(self.TEXT, len(self.TEXT)), (19, 25))
        self.assertEqual(line_span(self.TEXT, 18), (18, 18))

    def test_move_keeps_the_column_where_it_can(self):
        self.assertEqual(line_move(self.TEXT, 15, -1), 5)    # "first" is shorter: its end
        self.assertEqual(line_move(self.TEXT, 3, 1), 9)      # column 3 of "second line"
        self.assertEqual(line_move(self.TEXT, 9, 1), 18)     # the blank line
        self.assertEqual(line_move(self.TEXT, 9, 2), 22)
        self.assertEqual(line_move(self.TEXT, 2, -5), 2)     # already at the top
        self.assertEqual(line_move(self.TEXT, 20, 9), 20)    # already at the bottom
        self.assertEqual(line_move(self.TEXT, 0, 3), 19)     # as "go to line 4" does


class Units(unittest.TestCase):
    def test_counts_like_the_editor(self):
        self.assertEqual(units("abc"), 3)
        self.assertEqual(units("café"), 4)
        self.assertEqual(units("\U0001f600"), 2)


if __name__ == "__main__":
    unittest.main()
