import unittest

from dictation.selecting import alike, back_to, find_all, find_exact, find_nearest, variants

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


class BackTo(unittest.TestCase):
    """Where the cursor goes back to after "correct ...". In each test the words
    "cat" (4 to 7) of "the cat sat on the mat" are replaced."""

    def go(self, mark, new="lion", delete_before=0, delete_after=0):
        start, end = 4, 7
        new_start = start - delete_before
        new_end = new_start + len(new)
        return back_to(mark, start, end, new_start, new_end, new_end - end - delete_after)

    def test_a_cursor_after_the_words_moves_along_with_the_text(self):
        self.assertEqual(self.go(22), 23)             # the end of the line is still its end
        self.assertEqual(self.go(8), 9)               # before "sat" still
        self.assertEqual(self.go(22, new="ox"), 21)   # shorter words

    def test_a_cursor_before_the_words_stays(self):
        self.assertEqual(self.go(0), 0)
        self.assertEqual(self.go(3), 3)

    def test_a_cursor_right_after_the_words_ends_right_after_the_new_ones(self):
        self.assertEqual(self.go(7), 8)

    def test_a_cursor_right_before_the_words_stays_before_the_new_ones(self):
        self.assertEqual(self.go(4), 4)

    def test_a_cursor_among_the_words_is_left_after_the_new_ones(self):
        self.assertEqual(self.go(5), 8)
        self.assertEqual(self.go(6, new="a"), 5)

    def test_what_was_deleted_beside_the_words_is_not_gone_back_into(self):
        # A space taken out before the words, where the cursor was just before them.
        self.assertEqual(self.go(4, delete_before=1), 3)
        self.assertEqual(self.go(3, delete_before=1), 3)
        # A space taken out after the words, where the cursor was just after it.
        self.assertEqual(self.go(8, delete_after=1), 8)
        self.assertEqual(self.go(22, delete_after=1), 22)


class QuoteMarks(unittest.TestCase):
    """A quote mark beside a word is not part of the word; one inside it is."""

    TEXT = "He said 'hello' to the boys\u2019 toys, \u2018Hello,\u2019 he said"

    def found(self, phrase, caret=0):
        return self.TEXT[slice(*find_nearest(self.TEXT, caret, phrase))]

    def test_a_word_in_quotes_is_found_without_them(self):
        self.assertEqual(self.found("hello"), "hello")
        self.assertEqual(self.found("hello he"), "Hello,\u2019 he")

    def test_a_possessive_with_its_mark_at_the_end(self):
        self.assertEqual(self.found("boys"), "boys")
        self.assertEqual(self.found("boys toys"), "boys\u2019 toys")

    def test_an_apostrophe_inside_a_word_stays(self):
        self.assertEqual(find_all("don't stop", "don't"), [(0, 5)])
        self.assertEqual(find_all("don't stop", "don"), [])

    def test_quote_marks_alone_are_no_word(self):
        self.assertEqual(find_all("a ' b '' c", "b c"), [(4, 10)])


class WrittenAnotherWay(unittest.TestCase):
    """The command comes without punctuation and as the recogniser spells: the words in
    the document are found all the same."""

    TEXT = ("There are 1,250 people in the U.S. at 3:30 p.m. with Dr. Smith's dog's bone, "
            "the café, 21 colours and 305 more. I realise that I am here.")

    def found(self, phrase):
        place = find_nearest(self.TEXT, 0, phrase)
        return self.TEXT[slice(*place)] if place else None

    def test_a_number_with_a_comma_in_it(self):
        self.assertEqual(self.found("1250"), "1,250")
        self.assertEqual(self.found("1,250"), "1,250")
        self.assertEqual(words(self.TEXT, find_exact(self.TEXT, "1250 people")), ["1,250 people"])

    def test_a_number_said_in_words(self):
        self.assertEqual(self.found("twenty one"), "21")
        self.assertEqual(self.found("twenty-one colours"), "21 colours")
        self.assertEqual(self.found("three hundred and five"), "305")
        self.assertEqual(words("twenty-one days", find_exact("twenty-one days", "21")), ["twenty-one"])
        self.assertEqual(words("in 1984 then", find_exact("in 1984 then", "nineteen eighty four")), ["1984"])

    def test_initials_and_titles_with_their_stops(self):
        self.assertEqual(self.found("us"), "U.S.")
        self.assertEqual(self.found("pm"), "p.m.")
        self.assertEqual(self.found("in the us at"), "in the U.S. at")
        self.assertEqual(self.found("dr smith's"), "Dr. Smith's")
        self.assertEqual(self.found("doctor"), "Dr.")
        self.assertEqual(self.found("doctor smith's dog's"), "Dr. Smith's dog's")
        self.assertEqual(self.found("am"), "am")   # not "p.m.": that is "pm"

    def test_the_other_spelling(self):
        self.assertEqual(self.found("colors"), "colours")
        self.assertEqual(self.found("realize"), "realise")
        self.assertEqual(words("the color gray", find_all("the color gray", "colour grey")), ["color gray"])

    def test_without_its_apostrophe_or_its_accent(self):
        self.assertEqual(self.found("dogs bone"), "dog's bone")
        self.assertEqual(self.found("cafe"), "café")
        self.assertEqual(words("Māori words", find_all("Māori words", "maori")), ["Māori"])

    def test_as_heard_is_still_taken_first(self):
        text = "the dogs and the dog's bone"
        self.assertEqual(words(text, find_exact(text, "dogs")), ["dogs"])
        self.assertEqual(words(text, find_all(text, "dogs")), ["dogs", "dog's"])
        self.assertEqual(text[slice(*find_nearest(text, len(text), "dogs"))], "dogs")

    def test_variants_for_programs_that_look_for_exactly_the_words(self):
        self.assertEqual(variants("twenty one")[0], "21")
        self.assertEqual(variants("1250"), ["1,250"])
        self.assertEqual(variants("color"), ["colour"])
        self.assertEqual(variants("the colour"), ["the color"])
        self.assertEqual(variants("realize it"), ["realise it"])
        self.assertIn("dr smith", variants("doctor smith"))


if __name__ == "__main__":
    unittest.main()
