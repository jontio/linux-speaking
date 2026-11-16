import unittest

from dictation.selecting import alike, find_all, find_exact, find_nearest, variants

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


def words(text, places):
    return [text[a:b] for a, b in places]


class SoundAlikes(unittest.TestCase):
    MIXED = "I have 2 cats, two dogs, and I went to the shop too."
    ONE = "I went to the shop to buy two apples to eat."

    def test_a_number_is_the_same_in_words_and_figures(self):
        self.assertEqual(words(self.ONE, find_exact(self.ONE, "2")), ["two"])
        self.assertEqual(words("the 2nd time", find_all("the 2nd time", "second")), ["2nd"])
        self.assertEqual(words("It was 20 to 4", find_exact("It was 20 to 4", "twenty")), ["20"])

    def test_everything_that_sounds_the_same_is_offered(self):
        self.assertEqual(words(self.MIXED, find_all(self.MIXED, "two")), ["2", "two", "to", "too"])
        for heard in ("two", "to", "too", "2"):
            self.assertEqual(words(self.ONE, find_all(self.ONE, heard)), ["to", "to", "two", "to"])

    def test_as_heard_leaves_the_others_out(self):
        self.assertEqual(words(self.ONE, find_exact(self.ONE, "two")), ["two"])
        self.assertEqual(words(self.MIXED, find_exact(self.MIXED, "two")), ["2", "two"])

    def test_not_there_as_heard_falls_back_to_what_sounds_the_same(self):
        text = "They went there and left their coats."
        self.assertEqual(words(text, find_all(text, "they're")), ["there", "their"])
        self.assertEqual(words(text, find_all(text, "they're coats")), ["their coats"])
        self.assertEqual(find_all(text, "dog"), [])

    def test_nearest_prefers_the_word_as_heard(self):
        text = "to to to two to to"
        self.assertEqual(text[slice(*find_nearest(text, 0, "two"))], "two")
        self.assertEqual(find_nearest(text, 0, "to"), (0, 2))

    def test_nearest_falls_back_to_what_sounds_the_same(self):
        text = "We need 2 more, not three."
        self.assertEqual(text[slice(*find_nearest(text, 0, "too"))], "2")
        self.assertIsNone(find_nearest(text, 0, "for"))

    def test_ordinary_words_are_as_before(self):
        self.assertEqual(alike("cat"), frozenset({"cat"}))
        self.assertEqual(alike("two"), frozenset({"two", "2", "to", "too"}))
        self.assertEqual(alike("2"), alike("too"))
        self.assertEqual(alike("it's"), frozenset({"it's", "its"}))

    def test_curly_apostrophes_match(self):
        text = "It\u2019s here"
        self.assertEqual(words(text, find_all(text, "its")), ["It\u2019s"])


class Variants(unittest.TestCase):
    def test_the_other_way_of_writing_a_number_comes_first(self):
        self.assertEqual(variants("two"), ["2", "to", "too"])
        self.assertEqual(variants("Select-me 2!")[:1], ["select me two"])

    def test_none_for_ordinary_words(self):
        self.assertEqual(variants("the cat sat"), [])
        self.assertEqual(variants(""), [])

    def test_one_changed_word_before_two_and_never_too_many(self):
        found = variants("for two")
        self.assertEqual(found[0].count(" "), 1)
        self.assertLessEqual(len(found), 12)
        changed = [sum(a != b for a, b in zip(v.split(), ["for", "two"])) for v in found]
        self.assertEqual(changed, sorted(changed))
        self.assertNotIn("for two", found)


if __name__ == "__main__":
    unittest.main()
