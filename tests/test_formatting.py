import os
import tempfile
import unittest

from dictation.formatting import LINE, PARAGRAPH, fit, preview, sentence_start, title
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


class GreetingComma(unittest.TestCase):
    """The recogniser writes "Hello, Bob". With the setting, the comma is left out."""

    def typed(self, raw, **kw):
        return fit(raw, "", "", LEX, spoken_off=(), greeting_comma=False, **kw).text

    def test_before_a_name(self):
        self.assertEqual(self.typed("Hello, Bob."), "Hello Bob")
        self.assertEqual(self.typed("Hi, Sam, thanks for the notes."), "Hi Sam, thanks for the notes")
        self.assertEqual(self.typed("Good morning, Bob!"), "Good morning Bob")
        self.assertEqual(self.typed("Thanks. Hey, Jonti, are you there?"), "Thanks. Hey Jonti, are you there")

    def test_before_a_word_that_stands_for_people(self):
        self.assertEqual(self.typed("Morning, everyone."), "Morning everyone")
        self.assertEqual(self.typed("Hi, there."), "Hi there")

    def test_a_comma_that_belongs_is_kept(self):
        self.assertEqual(self.typed("Hello, how are you?"), "Hello, how are you")
        self.assertEqual(self.typed("Hello, I am here."), "Hello, I am here")
        self.assertEqual(self.typed("Hello, I'm Bob."), "Hello, I'm Bob")
        self.assertEqual(self.typed("I saw her this morning, Bob."), "I saw her this morning, Bob")

    def test_other_words_of_greeting(self):
        from dictation.formatting import without_greeting_comma as plain
        for said, want in (("Greetings, Dave.", "Greetings Dave."),
                           ("Hello there, Dave.", "Hello there Dave."),
                           ("Hi there, Dave!", "Hi there Dave!"),
                           ("Hallo, Dave.", "Hallo Dave."),
                           ("Kia ora, Dave.", "Kia ora Dave."),
                           ("G'day, Dave.", "G'day Dave."),
                           ("Gday, Dave.", "Gday Dave."),
                           ("Yo, Dave.", "Yo Dave."),
                           ("Welcome, Dave.", "Welcome Dave."),
                           ("Welcome back, Dave.", "Welcome back Dave."),
                           ("Thanks. Greetings, everyone.", "Thanks. Greetings everyone."),
                           ("And then I said hey there, Jill.", "And then I said hey there Jill."),
                           ("So I wrote kia ora, Dave and sent it.", "So I wrote kia ora Dave and sent it.")):
            self.assertEqual(plain(said), want)
        self.assertEqual(self.typed("Greetings, Dave."), "Greetings Dave")

    def test_words_that_only_greet_at_the_start_keep_their_comma_further_on(self):
        for kept in ("He sends his greetings, Dave",
                     "Season's greetings, Dave",
                     "You're welcome, Dave",
                     "You are always welcome, Dave and Jill"):
            self.assertEqual(self.typed(kept + "."), kept)

    def test_further_on_in_a_sentence_too(self):
        self.assertEqual(self.typed("So if I say hello, Bob."), "So if I say hello Bob")
        self.assertEqual(self.typed("So if I say hello, Jill and I say hello, Peter."),
                         "So if I say hello Jill and I say hello Peter")
        self.assertEqual(self.typed("Oh, hello, Bob."), "Oh, hello Bob")
        self.assertEqual(self.typed("She said hi, Mary-Ann, and left."), "She said hi Mary-Ann, and left")
        self.assertEqual(self.typed("Then I said hey, Bob Smith!"), "Then I said hey Bob Smith")
        self.assertEqual(self.typed("I waved and said hello, everyone."), "I waved and said hello everyone")

    def test_further_on_a_comma_before_a_name_that_begins_something_new_is_kept(self):
        for kept in ("I said hello, Bob said goodbye",
                     "When you say hello, Jill will answer",
                     "I said hello, I think",
                     "We said hello, Monday was the day for it",
                     "They said hi, OK was the answer",
                     "She said hello, how are you"):
            self.assertEqual(self.typed(kept + "."), kept)

    def test_further_on_a_word_that_is_also_a_time_of_day_keeps_its_comma(self):
        for kept in ("I saw her this morning, Bob",
                     "We had a good evening, Bob",
                     "Have a good day, Jill",
                     "See you this afternoon, Peter and Sam"):
            self.assertEqual(self.typed(kept + "."), kept)

    def test_inside_quotes(self):
        from dictation.formatting import without_greeting_comma
        self.assertEqual(without_greeting_comma('She said, "Hello, Bob."'), 'She said, "Hello Bob."')
        self.assertEqual(without_greeting_comma("He wrote (hi, Sam) on it."), "He wrote (hi Sam) on it.")
        self.assertEqual(without_greeting_comma('She said, "Hello, Bob will be late."'),
                         'She said, "Hello, Bob will be late."')

    def test_sign_offs_keep_theirs(self):
        self.assertEqual(self.typed("Cheers, Jonti"), "Cheers, Jonti")
        self.assertEqual(self.typed("Thanks, Bob."), "Thanks, Bob")

    def test_a_comma_that_was_said_is_typed(self):
        self.assertEqual(self.typed("Hello Bob comma"), "Hello Bob,")
        self.assertEqual(self.typed("Hello comma Bob"), "Hello, Bob")

    def test_left_alone_unless_asked(self):
        self.assertEqual(fit("Hello, Bob.", "", "", LEX).text, "Hello, Bob")


class ASignSaidAfterOneThatIsThere(unittest.TestCase):
    """A sign said at the start of a phrase where the text already ends with one: the
    recogniser's full stop kept at the end of the phrase before, or a sign said there."""

    def typed(self, before, raw, keep_final=True):
        ins = fit(raw, before, "", keep_final=keep_final)
        return before[:len(before) - ins.delete_before] + ins.text, ins.said_end

    def test_the_same_sign_twice_is_typed_once(self):
        for keep in (True, False):
            self.assertEqual(self.typed("I have something.", "Full stop.", keep), ("I have something.", True))
            self.assertEqual(self.typed("I have something.", "full stop", keep), ("I have something.", True))
            self.assertEqual(self.typed("Is it?", "Question mark.", keep), ("Is it?", True))
            self.assertEqual(self.typed("Hello,", "comma", keep), ("Hello,", False))
            self.assertEqual(self.typed("I have something. ", "Full stop.", keep), ("I have something. ", True))

    def test_another_sign_takes_the_place_of_the_one_there(self):
        self.assertEqual(self.typed("I have something.", "Question mark."), ("I have something?", True))
        self.assertEqual(self.typed("I have something?", "Full stop."), ("I have something.", True))
        self.assertEqual(self.typed("I have something.", "Exclamation mark!"), ("I have something!", True))
        self.assertEqual(self.typed("I have something.", "Comma how are you."),
                         ("I have something, how are you.", False))
        self.assertEqual(self.typed("I have something.", "Comma how are you.", keep_final=False),
                         ("I have something, how are you", False))

    def test_a_shortenings_own_stop_stays(self):
        self.assertEqual(self.typed("We met at 5 p.m.", "Full stop."), ("We met at 5 p.m.", True))
        self.assertEqual(self.typed("We met at 5 p.m.", "Question mark."), ("We met at 5 p.m.?", True))
        self.assertEqual(self.typed("We met at 5 p.m.", "Comma and then left.", keep_final=False),
                         ("We met at 5 p.m., and then left", False))

    def test_the_stop_of_an_initial_or_a_sometimes_shortening_stays(self):
        self.assertEqual(self.typed("Signed, John F.", "Comma the manager.", keep_final=False),
                         ("Signed, John F., the manager", False))
        self.assertEqual(self.typed("The meeting is on 3 Jan.", "Comma at noon.", keep_final=False),
                         ("The meeting is on 3 Jan., at noon", False))

    def test_dots_that_trail_off_stay(self):
        self.assertEqual(self.typed("Well...", "Full stop."), ("Well...", True))
        self.assertEqual(self.typed("Well…", "Full stop."), ("Well…", True))
        self.assertEqual(self.typed("Well...", "Question mark."), ("Well...?", True))

    def test_with_no_sign_there_the_said_one_is_typed(self):
        self.assertEqual(self.typed("I have something", "Full stop."), ("I have something.", True))
        self.assertEqual(self.typed("I have something.", "Full stop. And then more.", keep_final=False),
                         ("I have something. And then more", False))


class WhereTheSaidSignsAre(unittest.TestCase):
    """The signs that were said are the person's own: an insertion says where they are."""

    def marks(self, raw, before=""):
        ins = fit(raw, before, "")
        return [(ins.text[a:b], ins.text[:a]) for a, b in ins.said_marks]

    def test_said_signs_are_found_and_the_recognisers_are_not(self):
        self.assertEqual(self.marks("Hello Rick comma how are you question mark"),
                         [(",", "Hello Rick"), ("?", "Hello Rick, how are you")])
        self.assertEqual(self.marks("Hello Rick, how are you?"), [])

    def test_with_a_space_put_before_the_phrase(self):
        self.assertEqual(self.marks("yes comma I will", "Well"), [(",", " yes")])

    def test_a_stop_said_after_a_shortening_is_the_shortenings_own(self):
        ins = fit("at 5 p.m. full stop then left.", "We met", "")
        self.assertEqual([ins.text[a - 3:b] for a, b in ins.said_marks], ["p.m."])

    def test_line_breaks_and_quotes(self):
        self.assertEqual([m for m, _ in self.marks("open quote yes close quote", "He said")], ["“", "”"])
        self.assertEqual(len(self.marks("new paragraph thanks", "Dear Sam")), 1)


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


class InsideAPhrase(unittest.TestCase):
    LEXICON = Lexicon(lower={"government", "tomorrow", "apples", "see", "buy"})

    def fit(self, raw, before="We met "):
        return fit(raw, before, "", self.LEXICON).text

    def test_a_shortenings_full_stop_does_not_start_a_sentence(self):
        self.assertEqual(self.fit("the U.S. government said so"), "the U.S. government said so")
        self.assertEqual(self.fit("at 5 p.m. tomorrow"), "at 5 p.m. tomorrow")
        self.assertEqual(self.fit("e.g. apples"), "e.g. apples")
        self.assertEqual(self.fit("See Dr. Smith. Then go"), "see Dr. Smith. Then go")

    def test_a_sentences_full_stop_still_does(self):
        self.assertEqual(self.fit("it is late. tomorrow then"), "it is late. Tomorrow then")

    def test_after_the_mark_of_a_list_item_or_a_heading_comes_a_capital(self):
        for marker in ("- ", "* ", "# ", "## ", "> ", "1) ", "- [ ] ", "  - "):
            self.assertTrue(sentence_start(marker), marker)
            self.assertEqual(self.fit("Buy milk.", marker), "Buy milk")
        self.assertEqual(self.fit("Buy milk.", "First line\n- "), "Buy milk")

    def test_a_dash_in_the_middle_of_a_line_is_not_such_a_mark(self):
        self.assertFalse(sentence_start("well - "))
        self.assertFalse(sentence_start("x = 3 - "))

    def test_cap_that_leaves_the_letter_after_an_apostrophe_small(self):
        self.assertEqual(title("don't stop john's o\u2019clock 3rd"), "Don't Stop John's O\u2019clock 3rd")
        self.assertEqual(title("ALL THE WAY"), "All The Way")


class StraightQuotes(unittest.TestCase):
    LEXICON = Lexicon(lower={"come", "here", "hello", "world", "the", "word"})

    def fit(self, raw, before, after):
        return fit(raw, before, after, self.LEXICON).text

    def test_no_space_before_a_quote_mark_that_closes(self):
        self.assertEqual(self.fit("come here", 'She said "', '"'), "come here")
        self.assertEqual(self.fit("hello world", 'print("', '")'), "hello world")
        self.assertEqual(self.fit("hello", "it's '", "'"), "hello")

    def test_a_space_before_one_that_opens(self):
        self.assertEqual(self.fit("the word", "say ", '"quoted" next'), "the word ")
        self.assertEqual(self.fit("the word", 'he said "yes" and ', '"no"'), "the word ")
        self.assertEqual(self.fit("the word", "don't say ", "'quoted'"), "the word ")


class SpelledWithASmallFirstLetter(unittest.TestCase):
    """A word written with its first letter small and a capital later keeps it so, even
    at the start of a sentence."""

    LEXICON = Lexicon(lower={"is", "here", "works", "hello"})

    def test_at_the_start_of_a_sentence(self):
        self.assertEqual(fit("vLR5340 is here.", "", "", self.LEXICON).text, "vLR5340 is here")
        self.assertEqual(fit("iPhone works.", "Done. ", "", self.LEXICON).text, "iPhone works")
        self.assertEqual(fit("is here. eBay works", "x ", "", self.LEXICON).text, "is here. eBay works")

    def test_an_ordinary_word_still_gets_its_capital(self):
        self.assertEqual(fit("hello there", "", "", self.LEXICON).text, "Hello there")
        self.assertEqual(fit("is here. works", "x ", "", self.LEXICON).text, "is here. Works")


# A dictionary in which names are everyday words as well, as they are in a real one.
WORDS = Lexicon(
    lower={"new", "mark", "may", "march", "will", "rose", "ask", "old", "car", "maybe", "knows",
           "apples", "pears", "list", "how", "works", "color", "issue", "manager", "line",
           "hired", "fruit", "physics", "hiring", "key", "name", "put", "pressed", "cancer"},
    capitalised={"Mark", "May", "March", "Will", "Rose", "Tom", "Zealand", "Jones"})


def typed(before, raw, after="", lexicon=WORDS, **kw):
    return preview(before, after, fit(raw, before, after, lexicon, **kw))


class NamesThatAreEverydayWordsToo(unittest.TestCase):
    """The first word of a phrase that goes on with a sentence loses the recogniser's
    capital. Not if the capital belongs to a name."""

    def test_another_capital_straight_after_it(self):
        self.assertEqual(typed("I live in", "New Zealand."), "I live in New Zealand")
        self.assertEqual(typed("ask", "Mark Jones about it."), "ask Mark Jones about it")
        self.assertEqual(typed("I spoke to", "Will Smith yesterday.", lexicon=Lexicon()),
                         "I spoke to Will Smith yesterday")

    def test_but_not_a_word_that_only_leads_up_to_a_name(self):
        self.assertEqual(typed("and then", "The London bus came"), "and then the London bus came")
        self.assertEqual(typed("and", "Maybe Tom knows"), "and maybe Tom knows")
        self.assertEqual(typed("so", "Ask Tom"), "so ask Tom")
        self.assertEqual(typed("and then", "When I left"), "and then when I left")
        self.assertEqual(typed("we", "Will NASA help"), "we will NASA help")
        self.assertEqual(typed("and", "Well, Tom said so"), "and well, Tom said so")

    def test_a_month_where_a_date_fits(self):
        self.assertEqual(typed("see you in", "May."), "see you in May")
        self.assertEqual(typed("on", "March 5th"), "on March 5th")
        self.assertEqual(typed("you", "May go now"), "you may go now")
        self.assertEqual(typed("we will", "March on"), "we will march on")

    def test_one_of_the_persons_own_words(self):
        self.assertEqual(typed("I spoke to", "Rose."), "I spoke to rose")       # not told of her
        self.assertEqual(typed("I spoke to", "Rose.", names=("Rose",)), "I spoke to Rose")
        self.assertEqual(typed("that is", "Rose's.", names=("Rose",)), "that is Rose's")
        self.assertEqual(typed("it uses", "Clangd now", names=("clangd",)), "it uses clangd now")
        # An entry of two words is theirs only when both are said.
        self.assertEqual(typed("in", "New Plymouth today", names=("New Plymouth",)),
                         "in New Plymouth today")
        self.assertEqual(typed("and a", "New car", names=("New Plymouth",)), "and a new car")

    def test_a_name_the_dictionary_knows_after_a_greeting(self):
        self.assertEqual(typed("Hello", "Mark."), "Hello Mark")
        self.assertEqual(typed("and then", "Mark."), "and then mark")

    def test_an_american_spelling_with_a_british_dictionary_and_the_other_way(self):
        british = Lexicon(lower={"colour", "realise", "centre", "issue"})
        american = Lexicon(lower={"color", "realize", "center", "issue"})
        for lexicon in (british, american):
            self.assertEqual(typed("and the", "Color is the issue.", lexicon=lexicon),
                             "and the color is the issue")
            self.assertEqual(typed("and the", "Colours matter", lexicon=lexicon), "and the colours matter")
            self.assertEqual(typed("you will", "Realise it", lexicon=lexicon), "you will realise it")
            self.assertEqual(typed("in the", "Center of it", lexicon=lexicon), "in the center of it")


class PunctuationWordsThatAreOnlyWords(unittest.TestCase):
    def test_after_an_article(self):
        self.assertEqual(typed("", "We hired a new line manager."), "We hired a new line manager")
        self.assertEqual(typed("", "I pressed the question mark key."), "I pressed the question mark key")
        self.assertEqual(typed("", "Put a comma after the name."), "Put a comma after the name")
        self.assertEqual(typed("", "The word colon is here"), "The word colon is here")
        self.assertEqual(typed("Put a", "comma after the name"), "Put a comma after the name")

    def test_in_a_phrase_of_its_own_kind(self):
        self.assertEqual(typed("", "He was diagnosed with colon cancer."),
                         "He was diagnosed with colon cancer")
        self.assertEqual(typed("", "The comma key is stuck."), "The comma key is stuck")
        self.assertEqual(typed("", "The trial period ends on Friday period", spoken_off=()),
                         "The trial period ends on Friday.")

    def test_elsewhere_they_are_signs_as_before(self):
        self.assertEqual(typed("", "Dear Sir comma new line thanks"), "Dear Sir," + LINE + "Thanks")
        self.assertEqual(typed("", "read this colon it works"), "Read this: it works")
        self.assertEqual(typed("the end", "full stop"), "the end.")
        self.assertEqual(typed("I saw a", "comma"), "I saw a,")   # said by itself: the sign
        self.assertEqual(typed("", "in other words comma I think so"), "In other words, I think so")

    def test_a_capital_a_is_the_letter_unless_it_starts_the_sentence(self):
        self.assertEqual(typed("", "from point A comma go to point B full stop"),
                         "From point A, go to point B.")
        self.assertEqual(typed("from point A", "comma go on"), "from point A, go on")
        self.assertEqual(typed("", "A comma is needed here"), "A comma is needed here")
        self.assertEqual(typed("It works. A", "comma is needed"), "It works. A comma is needed")


class Shortenings(unittest.TestCase):
    def test_the_recognisers_capital_stands_after_one(self):
        self.assertEqual(typed("", "Apples, pears, etc. are fruit."), "Apples, pears, etc. are fruit")
        self.assertEqual(typed("", "He has a Ph.D. in physics."), "He has a Ph.D. in physics")
        self.assertEqual(typed("", "Acme Inc. is hiring."), "Acme Inc. is hiring")
        self.assertEqual(typed("", "It was in the U.S. Then we left"), "It was in the U.S. Then we left")

    def test_its_stop_is_kept_at_the_end_of_a_phrase(self):
        self.assertEqual(typed("We met ", "at 5 p.m."), "We met at 5 p.m.")
        self.assertEqual(typed("", "I live in the U.S."), "I live in the U.S.")
        self.assertEqual(typed("", "Apples, pears, etc."), "Apples, pears, etc.")
        self.assertEqual(typed("We met ", "at 5 p.m.", " yesterday"), "We met at 5 p.m. yesterday")
        self.assertFalse(fit("at 5 p.m.", "We met ", " yesterday", WORDS).capitalise_next)

    def test_an_ordinary_last_word_still_loses_the_recognisers_stop(self):
        self.assertEqual(typed("", "I said no."), "I said no")
        self.assertEqual(typed("", "It works."), "It works")
        self.assertEqual(typed("", "Is it 5 p.m.?"), "Is it 5 p.m.")

    def test_spoken_punctuation_leaves_its_stop(self):
        self.assertEqual(typed("", "Is it 5 p.m. question mark"), "Is it 5 p.m.?")
        self.assertEqual(typed("", "apples, pears, etc. comma and so on"), "Apples, pears, etc., and so on")
        # A full stop that is said is the same stop: one, not two.
        self.assertEqual(typed("", "it works etc. full stop then we left"), "It works etc. Then we left")

    def test_what_follows_one_in_the_document(self):
        self.assertEqual(typed("We met at 5 p.m.", "Then we left."), "We met at 5 p.m. Then we left")
        self.assertEqual(typed("We met at 5 p.m.", "And went home."), "We met at 5 p.m. and went home")


class SaidInPieces(unittest.TestCase):
    """The recogniser may write each piece as a sentence: "Hello. Comma. How are you?" """

    def test_the_capital_after_a_comma_that_was_said_goes(self):
        self.assertEqual(typed("", "Hello. Comma. How are you? Question mark."), "Hello, how are you?")
        self.assertEqual(typed("", "The list. Colon. Apples. Comma. Pears."), "The list: apples, pears")

    def test_a_name_keeps_it(self):
        self.assertEqual(typed("", "Thanks. Comma. Tom. Full stop."), "Thanks, Tom.")
        self.assertEqual(typed("", "Hello comma Mark"), "Hello, Mark")

    def test_after_a_full_stop_that_was_said_it_stays(self):
        self.assertEqual(typed("", "It works. Full stop. How are you"), "It works. How are you")


class MoreSigns(unittest.TestCase):
    ON = {"spoken_off": ()}  # with the ones that are off to begin with switched on

    def test_american_names_for_brackets(self):
        self.assertEqual(typed("see", "open paren page four close paren"), "see (page four)")
        self.assertEqual(typed("see", "open parenthesis page four close parenthesis"), "see (page four)")
        self.assertEqual(typed("x", "open square bracket one close square bracket"), "x [one]")
        self.assertEqual(typed("x", "open brace one close brace"), "x {one}")
        self.assertEqual(typed("x", "open curly bracket one close curly bracket"), "x {one}")

    def test_dashes_and_slashes(self):
        self.assertEqual(typed("", "wait dash what", **self.ON), "Wait – what")
        self.assertEqual(typed("", "this em dash that"), "This—that")
        self.assertEqual(typed("pages 5", "en dash 10"), "pages 5–10")
        self.assertEqual(typed("", "and slash or", **self.ON), "And/or")
        self.assertEqual(typed("", "one forward slash two"), "One/two")
        self.assertEqual(typed("", "C colon backslash users"), "C:\\users")
        self.assertEqual(typed("wait –", "what"), "wait – what")    # the spaced kind, in the document
        self.assertEqual(typed("5–", "10"), "5–10")                 # and the kind with none

    def test_the_everyday_ones_are_words_until_switched_on(self):
        self.assertEqual(typed("", "dash to the shops and slash prices"), "Dash to the shops and slash prices")
        self.assertEqual(typed("", "quote me a price"), "Quote me a price")
        self.assertEqual(typed("", "a dash of salt", **self.ON), "A dash of salt")

    def test_quotes(self):
        self.assertEqual(typed("", "he said quote hello unquote and left", **self.ON),
                         "He said “hello” and left")
        self.assertEqual(typed("", "he said quote hello end quote and left", **self.ON),
                         "He said “hello” and left")
        self.assertEqual(typed("", "he said quote hello quote and left", **self.ON),
                         "He said “hello” and left")
        self.assertEqual(typed("He said “hi", "quote", " and left", **self.ON), "He said “hi” and left")
        self.assertEqual(typed("", "open single quote hi close single quote"), "‘Hi’")

    def test_signs_in_names_and_sums(self):
        self.assertEqual(typed("mail", "bob at sign example"), "mail bob@example")
        self.assertEqual(typed("cc", "at sign jonti"), "cc @jonti")
        self.assertEqual(typed("", "Smith ampersand Jones"), "Smith & Jones")
        self.assertEqual(typed("", "fifty percent sign of them"), "Fifty% of them")
        self.assertEqual(typed("item", "hash sign five"), "item #five")
        self.assertEqual(typed("item", "number sign five"), "item #five")
        self.assertEqual(typed("costs", "dollar sign five or euro sign six"), "costs $five or €six")

    def test_apostrophe(self):
        self.assertEqual(typed("", "the dogs apostrophe bone"), "The dogs' bone")
        self.assertEqual(typed("", "the dog apostrophe s bone"), "The dog's bone")

    def test_newline_written_as_one_word_is_the_word(self):
        # Inside a sentence it is the name of the character. ("Newline." said by itself
        # is still the command: see test_commands.)
        self.assertEqual(typed("", "Strip the trailing newline."), "Strip the trailing newline")
        self.assertEqual(typed("", "No newline at end of file."), "No newline at end of file")
        self.assertEqual(typed("", "It is terminated by newline or end of file."),
                         "It is terminated by newline or end of file")
        self.assertEqual(typed("", "first new line second"), "First" + LINE + "Second")

    def test_each_can_be_said_as_a_word(self):
        self.assertEqual(typed("", "the literal ampersand"), "The ampersand")


class CapThat(unittest.TestCase):
    def test_capitals_that_are_there_stay(self):
        self.assertEqual(title("the NASA report"), "The NASA Report")
        self.assertEqual(title("my iPhone"), "My iPhone")

    def test_all_in_capitals_is_brought_down_first(self):
        self.assertEqual(title("THE NASA REPORT"), "The Nasa Report")


class MarkdownTypedByHand(unittest.TestCase):
    def test_no_space_after_a_mark_that_opens(self):
        self.assertEqual(typed("**", "bold words"), "**Bold words")
        self.assertEqual(typed("some **", "bold words"), "some **bold words")
        self.assertEqual(typed("run `", "code"), "run `code")
        self.assertEqual(typed("say _", "this"), "say _this")

    def test_a_space_after_one_that_closes(self):
        self.assertEqual(typed("some **bold words**", "and more"), "some **bold words** and more")
        self.assertEqual(typed("run `code`", "now"), "run `code` now")

    def test_one_star_at_the_start_of_a_line_is_a_list_item(self):
        self.assertEqual(typed("*", "apples"), "* apples")

    def test_the_start_of_a_line_is_still_the_start_of_a_sentence(self):
        self.assertTrue(sentence_start("**"))
        self.assertTrue(sentence_start("Done. **"))
        self.assertFalse(sentence_start("some **"))
        self.assertFalse(sentence_start("some **bold words**"))


# Nearer a real dictionary: it lists everyday words with capitals too, for what they
# are short for ("It", "In", "So") or for somebody called that ("Will", "Hope", "States").
REAL = Lexicon(
    lower={"next", "last", "using", "especially", "either", "unfortunately", "meeting", "three",
           "around", "control", "will", "hope", "state", "power", "field", "week", "mile", "new",
           "old", "mark", "may", "it", "in", "so", "can", "is", "do", "advance", "lot", "be",
           "problem", "work", "depend", "agree", "have", "go", "come", "back", "june", "key",
           "character", "low", "affair", "point", "people", "date", "level", "math", "art",
           "lifetime", "shelf", "temporary", "fix", "revised", "plan", "password", "sign",
           "newline", "trail", "file", "email", "board", "risk", "uncle", "lake", "air", "twenty",
           "dollar", "server", "share"},
    capitalised={"Monday", "Tuesday", "Friday", "John", "Sarah", "Python", "Christmas", "English",
                 "Mark", "Will", "Hope", "May", "New", "It", "In", "So", "Can", "Is", "A", "States",
                 "Powers", "Fields", "Weeks", "Miles", "Jones", "Zealand", "Tom", "Bob", "Taupo",
                 "James", "June"})


def real(before, raw, after="", **kw):
    return preview(before, after, fit(raw, before, after, REAL, **kw))


class TheFirstWordOfAPhraseInMidSentence(unittest.TestCase):
    """The recogniser gives every phrase a capital. In the middle of a sentence it goes,
    unless it is a name's: and a name coming next does not make the first word one."""

    def test_an_everyday_word_before_a_name_is_not_part_of_it(self):
        for before, said, typed_as in (
                ("I will see you", "Next Monday.", "I will see you next Monday"),
                ("We met", "Last Friday at the cafe.", "We met last Friday at the cafe"),
                ("Everyone was late,", "Especially John.", "Everyone was late, especially John"),
                ("I wrote it", "Using Python and a bit of C.", "I wrote it using Python and a bit of C"),
                ("We can do it on", "Either Monday or Tuesday.", "We can do it on either Monday or Tuesday"),
                ("I wanted to ask him but", "Unfortunately John is away.",
                 "I wanted to ask him but unfortunately John is away"),
                ("I am", "Meeting Sarah at noon.", "I am meeting Sarah at noon"),
                ("I spoke to", "Three English teachers.", "I spoke to three English teachers"),
                ("It should arrive", "Around Christmas.", "It should arrive around Christmas"),
                ("then press", "Control C.", "then press control C"),
                ("I", "Hope Sarah is well.", "I hope Sarah is well")):
            self.assertEqual(real(before, said), typed_as, said)

    def test_a_word_that_names_begin_with_still_keeps_its_capital(self):
        for before, said, typed_as in (
                ("the", "New Zealand dollar fell.", "the New Zealand dollar fell"),
                ("I spoke to", "Mark Jones about it.", "I spoke to Mark Jones about it"),
                ("I spoke to", "Old Tom about it.", "I spoke to Old Tom about it"),
                ("I spoke to", "Uncle Bob about it.", "I spoke to Uncle Bob about it"),
                ("They live near", "Lake Taupo.", "They live near Lake Taupo"),
                ("We flew", "Air New Zealand to Sydney.", "We flew Air New Zealand to Sydney")):
            self.assertEqual(real(before, said), typed_as, said)

    def test_after_a_greeting_a_word_that_runs_on_is_no_name(self):
        for before, said, typed_as in (
                ("Thanks", "Will do.", "Thanks will do"), ("Thanks", "In advance.", "Thanks in advance"),
                ("Thanks", "So much for coming.", "Thanks so much for coming"),
                ("Hi", "Can you send me the file?", "Hi can you send me the file"),
                ("Hello", "It is me again.", "Hello it is me again"),
                ("Hello", "It.", "Hello it")):
            self.assertEqual(real(before, said), typed_as, said)
        self.assertEqual(real("Hi", "Mark"), "Hi Mark")
        self.assertEqual(real("Hi", "Mark, how are you?"), "Hi Mark, how are you")
        self.assertEqual(real("Hi", "Will"), "Hi Will")

    def test_everyday_forms_that_a_dictionary_also_has_as_names(self):
        for before, said, typed_as in (
                ("the report", "States that the risk is low.", "the report states that the risk is low"),
                ("the battery", "Powers the board for a week.", "the battery powers the board for a week"),
                ("the struct has three", "Fields that matter.", "the struct has three fields that matter"),
                ("it happened", "Weeks later.", "it happened weeks later"),
                ("the nearest shop is", "Miles away.", "the nearest shop is miles away")):
            self.assertEqual(real(before, said), typed_as, said)
        self.assertEqual(real("that is what", "James said."), "that is what James said")

    def test_may_the_verb_after_a_word_that_also_comes_before_a_date(self):
        for before, said, typed_as in (
                ("I think this", "May be a problem.", "I think this may be a problem"),
                ("the people we heard from", "May not agree.", "the people we heard from may not agree"),
                ("the one before", "May have been better.", "the one before may have been better"),
                ("what comes after", "May depend on the weather.", "what comes after may depend on the weather")):
            self.assertEqual(real(before, said), typed_as, said)
        for before, said, typed_as in (
                ("we fly out this", "May and come back in June.", "we fly out this May and come back in June"),
                ("we will know by", "May I hope.", "we will know by May I hope"),
                ("we will know by", "May.", "we will know by May"),
                ("it runs from", "May to June.", "it runs from May to June"),
                ("see you in", "May we hope.", "see you in May we hope"),
                ("by", "May 5 we should know.", "by May 5 we should know")):
            self.assertEqual(real(before, said), typed_as, said)


class ASentenceEndThatWasSaid(unittest.TestCase):
    """After "p.m." or "etc." the text can't say whether a sentence ended. The phrase
    that typed it can: its Insertion's `said_end`, handed back as `after_said_end`."""

    def said(self, raw, before=""):
        return fit(raw, before, "", REAL).said_end

    def test_what_a_phrase_says_of_its_own_ending(self):
        self.assertTrue(self.said("The meeting is at 5 p.m. full stop"))
        self.assertTrue(self.said("That is all full stop"))
        self.assertTrue(self.said("Is it at 5 p.m. question mark"))
        self.assertTrue(self.said("What a day exclamation mark"))
        self.assertTrue(self.said("he said open quote go away full stop close quote"))
        self.assertFalse(self.said("The meeting is at 5 p.m."))       # the shortening's own
        self.assertFalse(self.said("That is all."))                   # the recogniser's
        self.assertFalse(self.said("That is all.", "x"))
        self.assertFalse(self.said("Dear Sir comma"))
        self.assertFalse(self.said("the end full stop and then"))
        self.assertFalse(self.said("the end full stop new line"))     # a break: a capital anyway

    def test_full_stop_said_by_itself_after_a_shortening_is_the_same_stop(self):
        ins = fit("Full stop.", "The meeting starts at 3 p.m.", "", REAL)
        self.assertEqual((ins.text, ins.said_end), ("", True))
        self.assertEqual(real("The meeting starts at 3 p.m.", "Full stop."), "The meeting starts at 3 p.m.")
        self.assertEqual(real("Bring pens, paper, etc.", "full stop then we can start"),
                         "Bring pens, paper, etc. Then we can start")
        self.assertEqual(real("Bring pens, paper, etc.", "full stop new paragraph"),
                         "Bring pens, paper, etc." + PARAGRAPH)
        self.assertEqual(real("at 5 p.m.", "full stop", " and then left"), "at 5 p.m. And then left")
        # After any other word it is typed, as it always was.
        self.assertEqual(real("The end", "Full stop."), "The end.")
        self.assertEqual(real("Is it 5 p.m.", "Question mark."), "Is it 5 p.m.?")

    def test_after_a_stop_that_was_said_the_phrase_starts_a_sentence(self):
        for before, raw, typed_as in (
                ("Bring pens, paper, etc.", "To register, email me.", "Bring pens, paper, etc. To register, email me"),
                ("The meeting starts at 3 p.m.", "From there we will go to dinner.",
                 "The meeting starts at 3 p.m. From there we will go to dinner"),
                ("He works in the U.S.", "And comes home twice a year.", "He works in the U.S. And comes home twice a year"),
                ("We live on Queen St.", "The house is the green one.", "We live on Queen St. The house is the green one")):
            self.assertEqual(real(before, raw, after_said_end=True), typed_as, raw)

    def test_after_one_that_was_not_the_phrase_carries_on(self):
        for before, raw, typed_as in (
                ("The meeting starts at 3 p.m.", "On Tuesday.", "The meeting starts at 3 p.m. on Tuesday"),
                ("The meeting starts at 3 p.m.", "Tomorrow afternoon.", "The meeting starts at 3 p.m. tomorrow afternoon"),
                ("It costs approx.", "Twenty dollars.", "It costs approx. twenty dollars"),
                ("Bring pens, paper, etc.", "To the hall by nine.", "Bring pens, paper, etc. to the hall by nine"),
                ("The meeting starts at 3 p.m.", "I will be there.", "The meeting starts at 3 p.m. I will be there"),
                ("The meeting starts at 3 p.m.", "John will be there.", "The meeting starts at 3 p.m. John will be there")):
            self.assertEqual(real(before, raw, after_said_end=False), typed_as, raw)

    def test_after_any_other_sentence_end_a_capital_comes_whatever_is_passed(self):
        for known in (None, True, False):
            self.assertEqual(real("That is done.", "and then we left", after_said_end=known),
                             "That is done. And then we left", known)
            self.assertEqual(real("Is that right?", "to be honest, no", after_said_end=known),
                             "Is that right? To be honest, no", known)
            self.assertEqual(real("The end." + LINE, "and more", after_said_end=known),
                             "The end." + LINE + "And more", known)
            self.assertEqual(real("and then", "The dog barked.", after_said_end=known),
                             "and then the dog barked", known)

    def test_where_it_is_not_known_it_is_as_it_was(self):
        self.assertEqual(real("We met at 5 p.m.", "Then we left."), "We met at 5 p.m. Then we left")
        self.assertEqual(real("We met at 5 p.m.", "And went home."), "We met at 5 p.m. and went home")


class SignWordsAfterAnArticle(unittest.TestCase):
    """After "a" or "the" a punctuation word is a word. Not always."""

    def test_a_hyphen_inside_a_word_that_has_an_article_in_it(self):
        self.assertEqual(real("", "It is a state hyphen of hyphen the hyphen art system."),
                         "It is a state-of-the-art system")
        self.assertEqual(real("", "A once hyphen in hyphen a hyphen lifetime chance."),
                         "A once-in-a-lifetime chance")
        self.assertEqual(real("", "An off hyphen the hyphen shelf part."), "An off-the-shelf part")
        self.assertEqual(real("", "There is a hyphen in my surname."), "There is a hyphen in my surname")
        self.assertEqual(real("", "The hyphen key."), "The hyphen key")

    def test_an_opening_quote_or_bracket_that_is_closed_later(self):
        self.assertEqual(real("", "It was a open quote temporary close quote fix."),
                         "It was a “temporary” fix")
        self.assertEqual(real("", "This is the open bracket revised close bracket plan."),
                         "This is the (revised) plan")
        self.assertEqual(real("the", "open bracket old close bracket town hall"), "the (old) town hall")
        self.assertEqual(real("", "Type an open bracket first."), "Type an open bracket first")
        self.assertEqual(real("", "An open quote is missing."), "An open quote is missing")

    def test_the_letter_a_at_the_start_of_a_sentence(self):
        self.assertEqual(real("", "A hyphen level maths was hard."), "A-level maths was hard")
        self.assertEqual(real("", "A hyphen Z listing."), "A-Z listing")
        self.assertEqual(real("", "A comma B comma and C are done."), "A, B, and C are done")
        self.assertEqual(real("", "A hyphen is missing."), "A hyphen is missing")
        self.assertEqual(real("", "A hyphen joins the two words."), "A hyphen joins the two words")
        self.assertEqual(real("", "A comma goes here."), "A comma goes here")

    def test_key_and_character_after_a_sign_are_words_like_any_others(self):
        self.assertEqual(real("", "New paragraph key points are as follows."),
                         PARAGRAPH + "Key points are as follows")
        self.assertEqual(real("", "That is all full stop Key points to note are below."),
                         "That is all. Key points to note are below")
        self.assertEqual(real("", "The meeting ran late comma key people had already left."),
                         "The meeting ran late, key people had already left")
        self.assertEqual(real("", "It was a low hyphen key affair."), "It was a low-key affair")
        self.assertEqual(real("", "Use a 32 hyphen character password."), "Use a 32-character password")
        self.assertEqual(real("", "Press the full stop key."), "Press the full stop key")

    def test_a_shorter_sign_is_not_found_inside_words_that_were_left(self):
        self.assertEqual(real("", "Add a semi colon at the end."), "Add a semi colon at the end")
        self.assertEqual(real("", "The semi-colon is missing."), "The semi-colon is missing")
        self.assertEqual(real("", "one semi colon two"), "One; two")


class AtSign(unittest.TestCase):
    def test_at_sign_in_and_at_sign_up_are_words(self):
        self.assertEqual(real("", "You will be asked for your password at sign in."),
                         "You will be asked for your password at sign in")
        self.assertEqual(real("", "Enter your details at sign up."), "Enter your details at sign up")
        self.assertEqual(real("", "Check your email at sign-in."), "Check your email at sign-in")
        self.assertEqual(real("", "You get a discount at sign-up."), "You get a discount at sign-up")

    def test_in_an_address_it_is_the_sign(self):
        self.assertEqual(real("mail", "bob at sign example"), "mail bob@example")
        self.assertEqual(real("", "Send it to info at sign example dot com."),
                         "Send it to info@example dot com")
        self.assertEqual(real("cc", "at sign jonti"), "cc @jonti")


class Backslash(unittest.TestCase):
    def test_a_space_before_it_where_it_starts_something(self):
        self.assertEqual(real("", "Use printf with backslash n for a new line."),
                         "Use printf with \\n for a new line")
        self.assertEqual(real("it ends with", "backslash n"), "it ends with \\n")
        self.assertEqual(real("", "Note colon backslash n means a line break"),
                         "Note: \\n means a line break")

    def test_none_inside_a_path(self):
        self.assertEqual(real("", "C colon backslash users backslash jo"), "C:\\users\\jo")
        self.assertEqual(real("C:", "backslash users"), "C:\\users")
        self.assertEqual(real("C:\\users", "backslash jo backslash documents"), "C:\\users\\jo\\documents")
        self.assertEqual(real("the share is", "backslash backslash server backslash share"),
                         "the share is \\\\server\\share")
        self.assertEqual(real("the path is", "C colon backslash users"), "the path is C:\\users")


class GreetingBeforeACapitalThatIsNoName(unittest.TestCase):
    def typed(self, raw):
        return fit(raw, "", "", LEX, spoken_off=(), greeting_comma=False).text

    def test_days_and_words_all_in_capitals(self):
        self.assertEqual(self.typed("Hello, Monday works for me."), "Hello, Monday works for me")
        self.assertEqual(self.typed("Hi, OK, I'll do that."), "Hi, OK, I'll do that")
        self.assertEqual(self.typed("Hi, January is fine."), "Hi, January is fine")

    def test_a_name_still_loses_the_comma(self):
        self.assertEqual(self.typed("Hello, Bob."), "Hello Bob")


class AfterATitle(unittest.TestCase):
    def test_the_name_keeps_its_capital_whatever_else_the_word_means(self):
        lex = Lexicon(lower=("see", "smith", "is", "in", "ask", "baker", "about", "it", "hill", "the"))
        for before, raw, want in (("See Dr.", "Smith is in.", " Smith is in"),
                                  ("Ask Mr.", "Baker about it.", " Baker about it"),
                                  ("See Dr", "Smith is in.", " Smith is in"),
                                  ("See the", "Smith is in.", " smith is in")):
            for carried in (None, False):
                self.assertEqual(fit(raw, before, "", lex, after_said_end=carried).text, want,
                                 (before, raw, carried))



class NamesThatEndInTwoPlusSigns(unittest.TestCase):
    def typed(self, raw, before=""):
        return fit(raw, before, "").text

    def test_parakeet_unified_writes_two_question_marks_for_them(self):
        # Its pieces for "C plus plus" are " C", " ", "?", "?": taken for the end of a
        # question, they were dropped, and only "C" was typed.
        self.assertEqual(self.typed("C ??."), "C++")
        self.assertEqual(self.typed("C??."), "C++")
        self.assertEqual(self.typed("I write C ?? code."), "I write C++ code")   # and no capital on "code"
        self.assertEqual(self.typed("It is written in C ??."), "It is written in C++")

    def test_a_phrase_that_starts_with_one_keeps_its_capital_mid_sentence(self):
        for raw in ("C++.", "C ??.", "C plus plus", "C++ is fast.", "C# too.", "Notepad++."):
            typed = fit(raw, "I like", "").text
            self.assertTrue(typed.startswith((" C++", " C#", " Notepad++")), (raw, typed))
        self.assertEqual(fit("G++.", "I compile with", "").text, " g++")
        self.assertEqual(self.typed("Open it in Notepad ??."), "Open it in Notepad++")

    def test_and_parakeet_v2_writes_the_words(self):
        self.assertEqual(self.typed("C plus plus."), "C++")
        self.assertEqual(self.typed("c plus plus", "I like "), "C++")
        self.assertEqual(self.typed("I use g plus plus and clang plus plus."), "I use g++ and clang++")

    def test_what_whisper_writes_is_left(self):
        self.assertEqual(self.typed("C++ and C#."), "C++ and C#")

    def test_nothing_else_is_given_plus_signs(self):
        self.assertEqual(self.typed("What??"), "What")
        self.assertEqual(self.typed("Is it C?"), "Is it C")
        self.assertEqual(self.typed("two plus two"), "Two plus two")
        self.assertEqual(self.typed("A plus plus"), "A plus plus")
        self.assertEqual(self.typed("Mac ??"), "Mac")
        self.assertEqual(self.typed("C ???"), "C")

if __name__ == "__main__":
    unittest.main()
