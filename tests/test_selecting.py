import unittest

from dictation.selecting import find_all, find_nearest

TEXT = "the cat sat on the cat mat"


class FindNearest(unittest.TestCase):
    def test_nearest_before_cursor(self):
        self.assertEqual(find_nearest(TEXT, len(TEXT), "cat"), (19, 22))

    def test_nearest_after_cursor(self):
        self.assertEqual(find_nearest(TEXT, 0, "cat"), (4, 7))

    def test_cursor_inside_match(self):
        self.assertEqual(find_nearest(TEXT, 5, "cat"), (4, 7))

    def test_ignores_case_and_punctuation(self):
        text = "The Cat, sat."
        start, end = find_nearest(text, 0, "cat sat")
        self.assertEqual(text[start:end], "Cat, sat")

    def test_whole_words_only(self):
        self.assertIsNone(find_nearest("concatenate", 0, "cat"))

    def test_not_found(self):
        self.assertIsNone(find_nearest(TEXT, 0, "dog"))

    def test_apostrophes(self):
        text = "I don’t know"
        start, end = find_nearest(text, 0, "don't")
        self.assertEqual(text[start:end], "don’t")


class FindAll(unittest.TestCase):
    def test_every_match_in_order(self):
        self.assertEqual(find_all(TEXT, "cat"), [(4, 7), (19, 22)])

    def test_none(self):
        self.assertEqual(find_all(TEXT, "dog"), [])
        self.assertEqual(find_all(TEXT, "..."), [])


if __name__ == "__main__":
    unittest.main()
