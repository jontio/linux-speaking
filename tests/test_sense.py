"""Whether what was heard makes sense (sense.py): the readings made of a phrase, the choice
between them, and the engine putting it right as the phrase goes in."""
import os
import unittest
from unittest import mock

from dictation import sense, tidy
from dictation.formatting import PARAGRAPH

from tests.test_engine_telling import bare
from tests.test_engine_tidy import Page

_LEXICON = []


def lexicon():
    """The program's own word list, loaded once: it knows "common" has no capital."""
    if not _LEXICON:
        from dictation.words import Lexicon
        _LEXICON.append(Lexicon.load_default())
    return _LEXICON[0]


class Scores:
    """Stands in for the language model: `rule(text)` is how likely each text is."""

    def __init__(self, rule):
        self.rule, self.asked = rule, []

    def logp(self, texts):
        self.asked.append(list(texts))
        return [self.rule(t) for t in texts]


def comma_after_a_greeting(text):
    return 0.0 if text.rstrip().endswith(("Hi Rick,", "Dear Sam,")) else -20.0


class Readings(unittest.TestCase):
    def test_a_spoken_command_heard_as_a_word(self):
        self.assertEqual(sense.readings("Hi rick, common new paragraph."),
                         [("Hi rick, comma new paragraph.", "common", "comma")])
        self.assertEqual(sense.readings("Common."), [("comma", "common", "comma")])
        self.assertEqual(sense.readings("coma"), [("comma", "coma", "comma")])
        self.assertEqual(sense.readings("that was the full stuff"),
                         [("that was the full stop", "full stuff", "full stop")])

    def test_a_sign_off_heard_as_another_word(self):
        self.assertEqual(sense.readings("Chairs"), [("Cheers", "chairs", "Cheers")])
        self.assertEqual(sense.readings("chairs,"), [("cheers,", "chairs", "Cheers")])

    def test_each_word_is_a_reading_of_its_own(self):
        self.assertEqual([r for r, _, _ in sense.readings("common sense, common")],
                         ["comma sense, common", "common sense, comma"])

    def test_only_whole_words(self):
        self.assertEqual(sense.readings("commonplace, uncommon, comatose"), [])
        self.assertFalse(sense.might_need("commonplace"))
        self.assertTrue(sense.might_need("Hi Rick common"))

    def test_never_a_mark_with_no_word_before_it_on_its_line(self):
        self.assertEqual(sense.readings("Common new paragraph.", before=""), [])
        self.assertEqual(sense.readings("Common", before="Hi Rick,\n\n"), [])
        self.assertEqual(sense.readings("Common", before="Hi Rick,"), [("comma", "common", "comma")])
        self.assertEqual(len(sense.readings("We share common ground", before="")), 1)
        self.assertEqual(sense.readings("Chairs", before=""), [("Cheers", "chairs", "Cheers")])

    def test_not_a_command_switched_off(self):
        self.assertEqual(sense.readings("Hi Rick common", spoken_off=("comma",)), [])


class Choosing(unittest.TestCase):
    def render(self, before):
        return lambda phrase: (before + " " + phrase).replace(" comma", ",")

    def test_far_more_likely_is_taken(self):
        reader = sense.Reader(Scores(comma_after_a_greeting))
        self.assertEqual(reader.reread("common", "Hi Rick", self.render("Hi Rick")),
                         ("comma", ("common", "comma")))

    def test_only_by_the_margin(self):
        reader = sense.Reader(Scores(lambda t: 0.0 if t.endswith(",") else -(sense.MARGIN - 0.5)))
        self.assertEqual(reader.reread("common", "It is quite", self.render("It is quite")),
                         ("common", None))

    def test_nothing_is_asked_without_such_a_word(self):
        scores = Scores(comma_after_a_greeting)
        reader = sense.Reader(scores)
        self.assertEqual(reader.reread("thanks for your help", "Hi Rick", self.render("Hi Rick")),
                         ("thanks for your help", None))
        self.assertEqual(scores.asked, [])

    def test_a_sign_off_by_itself_on_a_new_line_needs_less(self):
        reader = sense.Reader(Scores(lambda t: 0.0 if "Cheers" in t else -(sense.ALONE_MARGIN + 0.5)))
        render = lambda before: (lambda phrase: before + phrase)
        before = "All the best.\n\n"
        self.assertEqual(reader.reread("Chairs", before, render(before)), ("Cheers", ("chairs", "Cheers")))
        before = "All the best. "                      # not at the start of a line
        self.assertEqual(reader.reread("Chairs", before, render(before)), ("Chairs", None))
        before = "All the best.\n\n"                  # not by itself
        self.assertEqual(reader.reread("Chairs are here", before, render(before)), ("Chairs are here", None))

    def test_taken_back_it_is_not_made_again_for_a_while(self):
        reader = sense.Reader(Scores(comma_after_a_greeting))
        reader.refuse("common", now=100.0)
        self.assertEqual(reader.reread("common", "Hi Rick", self.render("Hi Rick"), now=200.0)[1], None)
        self.assertEqual(reader.reread("common", "Hi Rick", self.render("Hi Rick"),
                                       now=100.0 + sense.REFUSED_FOR + 1)[1], ("common", "comma"))

    def test_only_the_end_of_the_text_before_is_read(self):
        scores = Scores(comma_after_a_greeting)
        reader = sense.Reader(scores)
        before = "word " * 200 + "Hi Rick"
        reader.reread("common", before, self.render(before))
        for text in scores.asked[0]:
            self.assertLessEqual(len(text), sense.CONTEXT + 20)
            self.assertFalse(text.startswith(" "))


class AsThePhraseGoesIn(unittest.TestCase):
    def setUp(self):
        from dictation import config
        for patch in (mock.patch("dictation.engine.log"), mock.patch.object(config, "SENTENCE_QUIET", 0),
                      mock.patch("dictation.engine.Engine._save")):
            patch.start()
            self.addCleanup(patch.stop)

    def engine(self, page, rule=comma_after_a_greeting, ends="said"):
        engine = bare(page, tidy=True, hear_again=False)
        engine.lexicon = lexicon()
        engine.settings.sentence_ends = ends
        engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
        engine._sense = sense.Reader(Scores(rule))
        return engine

    def test_a_comma_said_by_itself_after_a_greeting(self):
        page = Page()
        engine = self.engine(page)
        engine.handle_text("Hi Rick", True)
        engine.handle_text("Common.", True)
        self.assertEqual(page.text, "Hi Rick,")

    def test_and_in_the_same_phrase_with_more(self):
        page = Page()
        engine = self.engine(page)
        engine.handle_text("Hi rick common new paragraph.", True)
        self.assertEqual(page.text, "Hi Rick," + PARAGRAPH)

    def test_where_the_word_makes_sense_it_stays(self):
        page = Page()
        engine = self.engine(page, rule=lambda t: -20.0 if t.endswith(",") else 0.0)
        engine.handle_text("We have a lot in", True)
        engine.handle_text("common.", True)
        self.assertEqual(page.text, "We have a lot in common")

    def test_in_words_mode_the_held_stop_does_not_get_in_the_way(self):
        page = Page()
        engine = self.engine(page, ends="words")
        engine._decider = None
        engine._deciding = True
        engine.handle_text("Hi Rick.", True)
        engine.handle_text("Common.", True)
        self.assertEqual(page.text, "Hi Rick,")

    # (A comma said after a greeting is the letters' own rule now, model or not: see letters.py.
    # These are of what only the model can tell: a list.)
    LIST = staticmethod(lambda t: 0.0 if t.rstrip().endswith("apples, pears and plums") else -20.0)

    def test_scratch_that_and_said_again_it_is_typed_as_heard(self):
        page = Page()
        engine = self.engine(page, rule=self.LIST)
        engine.handle_text("I like apples", True)
        engine.handle_text("common pears and plums.", True)
        self.assertEqual(page.text, "I like apples, pears and plums")
        engine.handle_text("scratch that", True)
        self.assertEqual(page.text, "I like apples")
        engine.handle_text("common pears and plums.", True)
        self.assertEqual(page.text, "I like apples common pears and plums")

    def test_without_the_model_it_is_typed_as_heard(self):
        page = Page()
        engine = self.engine(page, rule=self.LIST)
        engine._sense = None
        engine.handle_text("I like apples", True)
        engine.handle_text("common pears and plums.", True)
        self.assertEqual(page.text, "I like apples common pears and plums")

    def test_not_with_tidy_switched_off(self):
        page = Page()
        engine = self.engine(page, rule=self.LIST)
        engine.settings.states["tidy"] = False
        engine.handle_text("I like apples", True)
        engine.handle_text("common pears and plums.", True)
        self.assertEqual(page.text, "I like apples common pears and plums")


class TheFiles(unittest.TestCase):
    def test_a_file_cut_short_is_not_installed_and_a_wrong_one_is_taken_away(self):
        import tempfile
        models = tempfile.mkdtemp()
        os.makedirs(sense.folder(models))
        for name, (_, _, size) in sense.FILES.items():
            with open(os.path.join(sense.folder(models), name), "wb") as f:
                f.write(b"x" * (size if name == "tokenizer.json" else 10))
        self.assertFalse(sense.installed(models))
        sense.check(models)
        self.assertEqual(os.listdir(sense.folder(models)), [])   # neither is the one published


MODELS = os.environ.get("LS_TEST_SENSE_MODELS", "")


@unittest.skipUnless(MODELS and sense.installed(MODELS), "the language model is not here "
                     "(set LS_TEST_SENSE_MODELS to a models folder that has it)")
class TheRealModel(unittest.TestCase):
    """Readings made up for it, none of them anyone's own: the model must take every spoken
    comma, and leave every word."""

    CASES = [
        ("Hi Rick", " common", ",", True), ("Dear Sam", " common", ",", True),
        ("Cheers", " common", ",", True), ("Kind regards", " common", ",", True),
        ("Hi Rick", " coma", ",", True), ("Hi Rick", ". Common", ",", True),
        ("I like apples", " common pears and plums", ", pears and plums", True),
        ("If it rains tomorrow", " common we will stay inside", ", we will stay inside", True),
        ("To be honest", " common I forgot", ", I forgot", True),
        ("All the best.\n\n", "Chairs", "Cheers", "alone"),
        ("Thanks for your help.\n\n", "Chairs", "Cheers", "alone"),
        ("Let me know what you think.\n", "Chairs", "Cheers", "alone"),
        ("We have a lot in", " common", ",", False), ("It is a", " common mistake", ", mistake", False),
        ("He fell into a", " coma", ",", False), ("That is quite", " common", ",", False),
        ("The village", " common is a lovely place", ", is a lovely place", False),
        ("We walked across the", " common to the pub", ", to the pub", False),
        ("Use your", " common sense", ", sense", False),
        ("", "Chairs are expensive", "Cheers are expensive", False),
        ("Let me know what you think. ", "Chairs", "Cheers", False),
        ("Please bring two", " chairs.", " cheers.", False),
    ]

    @classmethod
    def setUpClass(cls):
        cls.scorer = sense.Scorer(MODELS)

    def test_the_cases(self):
        for before, heard, other, taken in self.CASES:
            h, o = self.scorer.logp([before + heard, before + other])
            need = sense.ALONE_MARGIN if taken == "alone" else sense.MARGIN
            self.assertEqual(o - h >= need, bool(taken), (before, heard, round(o - h, 2)))

    def test_through_the_engine(self):
        from dictation import config
        page = Page()
        with mock.patch("dictation.engine.log"), mock.patch.object(config, "SENTENCE_QUIET", 0):
            engine = bare(page, tidy=True, hear_again=False)
            engine.settings.sentence_ends = "said"
            engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
            engine._sense = sense.Reader(self.scorer)
            for phrase in ("Hi rick", "Common.", "new paragraph", "I hope you are well."):
                engine.handle_text(phrase, True)
        self.assertTrue(page.text.startswith("Hi Rick,"), repr(page.text))


if __name__ == "__main__":
    unittest.main()
