import os
import tempfile
import unittest

from dictation.formatting import LINE, PARAGRAPH, fit, preview, sentence_start
from dictation.words import Lexicon


def make_lexicon():
    words = ["6", "black/S", "page/S", "four", "dog/S", "bark/SD", "list/S", "London/M", "may", "May"]
    with tempfile.NamedTemporaryFile("w", suffix=".dic", delete=False) as f:
        f.write("\n".join(words) + "\n")
    try:
        return Lexicon.from_hunspell(f.name)
    finally:
        os.unlink(f.name)


LEX = make_lexicon()


def run(before, raw, after="", **kw):
    return preview(before, after, fit(raw, before, after, LEX, **kw))


class ExamplesFromTheChat(unittest.TestCase):
    def test_new_sentence_after_full_stop(self):
        self.assertEqual(run("The cat sat.", "it was happy"), "The cat sat. It was happy")

    def test_word_into_the_middle(self):
        self.assertEqual(run("The ", "Black.", after="cat"), "The black cat")

    def test_spoken_comma(self):
        self.assertEqual(run("Hello", "Comma."), "Hello,")


class Capitals(unittest.TestCase):
    def test_start_of_paragraph(self):
        self.assertEqual(run("", "hello there"), "Hello there")

    def test_mid_sentence_common_word(self):
        self.assertEqual(run("and then", "The dog barked."), "and then the dog barked")

    def test_mid_sentence_dictionary_word(self):
        self.assertEqual(run("see (", "Page four."), "see (page four")

    def test_names_keep_capitals(self):
        self.assertEqual(run("I went to", "London."), "I went to London")

    def test_unknown_words_keep_capitals(self):
        self.assertEqual(run("I met", "Jonti today."), "I met Jonti today")

    def test_i_keeps_capital(self):
        self.assertEqual(run("and then", "I left."), "and then I left")

    def test_acronyms_keep_capitals(self):
        self.assertEqual(run("we used", "NASA data"), "we used NASA data")

    def test_after_abbreviation(self):
        self.assertEqual(run("See e.g.", "The list."), "See e.g. the list")

    def test_after_closing_quote_with_question(self):
        self.assertEqual(run('He asked "Why?"', "then left"), 'He asked "Why?" Then left')

    def test_sentence_start_rules(self):
        self.assertTrue(sentence_start(""))
        self.assertTrue(sentence_start("Done. "))
        self.assertTrue(sentence_start("(Done.)"))
        self.assertTrue(sentence_start("line" + LINE))
        self.assertFalse(sentence_start("see above"))
        self.assertFalse(sentence_start("Ask Dr."))


class Spaces(unittest.TestCase):
    def test_space_after_when_next_is_a_word(self):
        self.assertEqual(run("The ", "big black", after="cat"), "The big black cat")

    def test_no_space_before_following_punctuation(self):
        self.assertEqual(run("The cat", "sat", after="."), "The cat sat.")

    def test_removes_space_before_punctuation(self):
        self.assertEqual(run("Hello ", "comma"), "Hello,")

    def test_no_space_after_opening_quote(self):
        self.assertEqual(run('He said "', "hello"), 'He said "hello')

    def test_space_after_closing_quote(self):
        self.assertEqual(run('He said "hi"', "and left"), 'He said "hi" and left')


class SpokenPunctuation(unittest.TestCase):
    def test_question(self):
        self.assertEqual(
            run("", "Hello comma how are you question mark"), "Hello, how are you?"
        )

    def test_whisper_punctuation_around_spoken_words(self):
        self.assertEqual(run("", "Hello, comma, how are you?"), "Hello, how are you")

    def test_full_stop_capitalises_next(self):
        self.assertEqual(run("", "the end full stop next one"), "The end. Next one")

    def test_new_paragraph_inline(self):
        self.assertEqual(
            run("", "first part new paragraph second part"),
            "First part" + PARAGRAPH + "Second part",
        )

    def test_new_line_removes_following_space(self):
        self.assertEqual(run("Dear Sir", "comma new line", after=" Thanks"),
                         "Dear Sir," + LINE + "Thanks")

    def test_hyphen(self):
        self.assertEqual(run("a", "well hyphen known fact"), "a well-known fact")

    def test_brackets(self):
        self.assertEqual(
            run("It", "works open bracket mostly close bracket"), "It works (mostly)"
        )

    def test_literal(self):
        self.assertEqual(
            run("", "the word literal comma is here"), "The word comma is here"
        )

    def test_full_stop_before_existing_words_capitalises_them(self):
        self.assertEqual(run("The end", "full stop", after=" and then"),
                         "The end. And then")


class WhisperFullStops(unittest.TestCase):
    def test_dropped_by_default(self):
        self.assertEqual(run("", "It works."), "It works")

    def test_kept_when_asked_at_end_of_paragraph(self):
        self.assertEqual(run("", "It works.", keep_final=True), "It works.")

    def test_dropped_mid_sentence_even_when_kept(self):
        self.assertEqual(run("The ", "Black.", after="cat", keep_final=True), "The black cat")

    def test_empty_phrase(self):
        self.assertEqual(fit("  ", "x", "").text, "")


if __name__ == "__main__":
    unittest.main()
