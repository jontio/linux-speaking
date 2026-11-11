"""The parts of the Word and Outlook link that need no Word to test."""
import unittest

from dictation.formatting import LINE, PARAGRAPH
from dictation.word_target import first_line, for_word, last_line, nearest, units


class TextTests(unittest.TestCase):
    def test_before_the_cursor_is_cut_at_the_last_break(self):
        self.assertEqual(last_line("First one.\rSecond"), "Second")
        self.assertEqual(last_line("a\x0bb"), "b")            # a line break
        self.assertEqual(last_line("cell one\x07cell two"), "cell two")
        self.assertEqual(last_line("page one\x0cpage two"), "page two")
        self.assertEqual(last_line("ends here\r"), "")
        self.assertEqual(last_line("no breaks"), "no breaks")

    def test_after_the_cursor_is_cut_at_the_first_break(self):
        self.assertEqual(first_line(" rest of it.\rNext paragraph"), " rest of it.")
        self.assertEqual(first_line("\rNext"), "")
        self.assertEqual(first_line("one\x0btwo\rthree"), "one")

    def test_break_marks_become_words_own(self):
        self.assertEqual(for_word("a" + PARAGRAPH + "b" + LINE + "c"), "a\rb\x0bc")
        self.assertEqual(for_word("plain"), "plain")

    def test_length_as_word_counts_it(self):
        self.assertEqual(units("abc"), 3)
        self.assertEqual(units("café"), 4)
        self.assertEqual(units("a\U0001F600b"), 4)  # an emoji takes two places


class NearestTests(unittest.TestCase):
    def test_keeps_reading_order(self):
        matches = [(0, 3), (10, 13), (20, 23), (30, 33)]
        self.assertEqual(nearest(matches, 21, 4), matches)

    def test_drops_the_furthest_when_there_are_too_many(self):
        matches = [(0, 3), (10, 13), (20, 23), (30, 33)]
        self.assertEqual(nearest(matches, 22, 2), [(20, 23), (30, 33)])
        self.assertEqual(nearest(matches, 0, 2), [(0, 3), (10, 13)])

    def test_cursor_inside_a_match_counts_as_nearest(self):
        self.assertEqual(nearest([(0, 3), (10, 13)], 11, 1), [(10, 13)])


if __name__ == "__main__":
    unittest.main()
