import os
import tempfile
import unittest

from dictation import vocabulary
from dictation.settings import Settings
from dictation.words import Lexicon

WORDS = ("Jonti", "Linux Speaking", "clangd")
DICTIONARY = Lexicon(lower={"jaunty", "tune", "little", "walked", "step", "notes", "clang"},
                     capitalised={"John"})
BARE = Lexicon()  # no dictionary found, as on Windows


def settle(hinted, plain, before="", lexicon=DICTIONARY):
    return vocabulary.settle(hinted, plain, before, WORDS, lexicon)


class Parse(unittest.TestCase):
    def test_lines_and_commas(self):
        self.assertEqual(vocabulary.parse("Jonti\n  Linux   Speaking ,clangd\n\n"), WORDS)

    def test_drops_repeats_and_punctuation_only(self):
        self.assertEqual(vocabulary.parse("Jonti\njonti\n--\n"), ("Jonti",))

    def test_limits(self):
        many = vocabulary.parse("\n".join(f"word{n}" for n in range(100)))
        self.assertEqual(len(many), vocabulary.MAX_WORDS)
        self.assertEqual(len(vocabulary.parse("x" * 100)[0]), vocabulary.MAX_WORD_CHARS)

    def test_a_saved_list(self):
        self.assertEqual(vocabulary.parse(["Jonti", "clangd"]), ("Jonti", "clangd"))


class Hint(unittest.TestCase):
    def test_none(self):
        self.assertEqual(vocabulary.hint(()), "")

    def test_list(self):
        self.assertEqual(vocabulary.hint(WORDS), "Jonti, Linux Speaking, clangd. ")

    def test_stays_short(self):
        words = tuple("w" * 30 + str(n) for n in range(40))
        self.assertLessEqual(len(vocabulary.hint(words)), vocabulary.MAX_HINT_CHARS + 2)


class Mentions(unittest.TestCase):
    def test_found_whatever_the_case_and_punctuation(self):
        self.assertTrue(vocabulary.mentions("Cheers, jonti!", WORDS))
        self.assertTrue(vocabulary.mentions("That is Jonti's.", WORDS))
        self.assertTrue(vocabulary.mentions("I use Linux speaking daily", WORDS))

    def test_not_found(self):
        self.assertFalse(vocabulary.mentions("Thanks for the notes.", WORDS))
        self.assertFalse(vocabulary.mentions("Linux is speaking", WORDS))
        self.assertFalse(vocabulary.mentions("", WORDS))


class Settle(unittest.TestCase):
    def test_both_hearings_agree(self):
        self.assertEqual(settle("Cheers, Jonti.", "Cheers, Jonti."), "Cheers, Jonti.")

    def test_a_name_written_as_one_stands(self):
        self.assertEqual(settle("Cheers, Jonti!", "Cheers, John T."), "Cheers, Jonti!")
        self.assertEqual(settle("My name is Jonti and I live here.",
                                "My name is John T. and I live here."),
                         "My name is Jonti and I live here.")

    def test_an_ordinary_word_in_a_sentence_comes_back(self):
        self.assertEqual(settle("It was a Jonti little tune.", "It was a jaunty little tune."),
                         "It was a jaunty little tune.")
        self.assertEqual(settle("He walked with a jonti step.", "He walked with a jaunty step."),
                         "He walked with a jaunty step.")

    def test_also_without_a_dictionary(self):
        self.assertEqual(settle("It was a Jonti little tune.", "It was a jaunty little tune.",
                                lexicon=BARE), "It was a jaunty little tune.")

    def test_after_a_greeting_or_sign_off(self):
        self.assertEqual(settle("Cheers, Jonti!", "Cheers, jaunty!"), "Cheers, Jonti!")
        self.assertEqual(settle("Hi jonti, how are you", "Hi jaunty, how are you"),
                         "Hi Jonti, how are you")

    def test_the_cue_can_be_in_the_document(self):
        self.assertEqual(settle("Jonti went home", "jaunty went home", before="Thanks,\n"),
                         "Jonti went home")
        self.assertEqual(settle("Jonti went home", "jaunty went home", before="It was a"),
                         "jaunty went home")

    def test_spoken_punctuation_between_the_cue_and_the_name(self):
        for lexicon in (DICTIONARY, BARE):
            self.assertEqual(settle("Cheers, new line, Jonti", "Cheers, new line, jaunty",
                                    lexicon=lexicon), "Cheers, new line, Jonti")
            self.assertEqual(settle("Cheers comma new line Jonti.", "Cheers comma new line jaunty.",
                                    lexicon=lexicon), "Cheers comma new line Jonti.")
            self.assertEqual(settle("Thanks, new-paragraph jonti", "Thanks, new-paragraph jaunty",
                                    lexicon=lexicon), "Thanks, new-paragraph Jonti")
        self.assertEqual(settle("It was new line Jonti", "It was new line jaunty"),
                         "It was new line jaunty")

    def test_said_by_itself(self):
        self.assertEqual(settle("Jonti.", "Jaunty."), "Jonti.")
        self.assertEqual(settle("Jonti.", "John Deere"), "Jonti.")

    def test_start_of_a_sentence_goes_by_the_dictionary(self):
        self.assertEqual(settle("Jonti tunes are fun.", "Jaunty tunes are fun."),
                         "Jaunty tunes are fun.")
        self.assertEqual(settle("Jonti is here.", "John T. is here."), "Jonti is here.")
        self.assertEqual(settle("Fine. Jonti tunes.", "Fine. Jaunty tunes."),
                         "Fine. Jaunty tunes.")

    def test_start_of_a_sentence_without_a_dictionary_takes_the_name(self):
        self.assertEqual(settle("Jonti tunes are fun.", "Jaunty tunes are fun.", lexicon=BARE),
                         "Jonti tunes are fun.")

    def test_an_unknown_word_is_taken_as_the_name(self):
        self.assertEqual(settle("I saw jonti there", "I saw jonty there"), "I saw Jonti there")

    def test_a_word_from_nowhere_is_dropped(self):
        self.assertEqual(settle("Thanks Jonti.", "Thanks."), "Thanks.")
        self.assertEqual(settle("Jonti.", ""), "")

    def test_other_differences_follow_the_hinted_hearing(self):
        self.assertEqual(settle("Cheers, Jonti, see you soon!", "Cheers, John T. see you son."),
                         "Cheers, Jonti, see you soon!")

    def test_two_word_and_lower_case_entries(self):
        self.assertEqual(settle("I use linux speaking daily.", "I use Linux Speaking daily."),
                         "I use Linux Speaking daily.")  # both agree: the plain hearing
        self.assertEqual(settle("Start clangd first.", "Start clang D first."),
                         "Start clangd first.")
        self.assertEqual(settle("I like linux speaking a lot", "I like Lennox speaking a lot"),
                         "I like Linux Speaking a lot")

    def test_i_is_not_a_name(self):
        self.assertEqual(settle("Then Jonti walked", "Then I walked"), "Then I walked")


class BySound(unittest.TestCase):
    """For a recogniser that can't be given the words as a hint."""

    def fix(self, text, before="", lexicon=DICTIONARY):
        return vocabulary.by_sound(text, before, WORDS, lexicon)

    def test_sounds_alike(self):
        key = vocabulary.sound_key
        self.assertEqual({key(w) for w in ("Jonti", "jaunty", "John T", "Johnty", "Jonty")}, {key("Jonti")})
        self.assertEqual(key("thunder bird"), key("Thunderbird"))
        self.assertNotEqual(key("giant"), key("Jonti"))
        self.assertNotEqual(key("hunting"), key("Jonti"))

    def test_put_in_where_a_name_fits(self):
        self.assertEqual(self.fix("Cheers, Jaunty."), "Cheers, Jonti.")
        self.assertEqual(self.fix("Cheers comma new line John T."), "Cheers comma new line Jonti.")
        self.assertEqual(self.fix("Hi Jonty, how are you?"), "Hi Jonti, how are you?")
        self.assertEqual(self.fix("I spoke to Johnty about it."), "I spoke to Jonti about it.")
        self.assertEqual(self.fix("Jaunty", before="Cheers,\n"), "Jonti")

    def test_an_ordinary_word_in_a_sentence_is_left(self):
        self.assertEqual(self.fix("It was a jaunty little tune."), "It was a jaunty little tune.")
        knows_jaunt = Lexicon(lower={"jaunt", "went", "today"})
        self.assertEqual(self.fix("We went for a jaunt today", lexicon=knows_jaunt),
                         "We went for a jaunt today")

    def test_already_right_or_nothing_like_it(self):
        self.assertEqual(self.fix("Jonti is here"), "Jonti is here")
        self.assertEqual(self.fix("Thanks for the notes."), "Thanks for the notes.")
        self.assertEqual(self.fix(""), "")
        self.assertEqual(vocabulary.by_sound("Cheers, Jaunty.", "", (), DICTIONARY), "Cheers, Jaunty.")

    def test_very_short_words_are_not_matched_by_sound(self):
        self.assertEqual(vocabulary.by_sound("Go to the bay", "", ("Bo",), DICTIONARY), "Go to the bay")

    def test_enter_said_between_the_sign_off_and_the_name(self):
        # "cheers comma enter jonti": as "new line" does, "enter" leaves the name straight
        # after the sign-off, however the recogniser wrote the pauses.
        for heard in ("Cheers, comma, enter, jaunty.", "Cheers, comma, enter. Jaunty.",
                      "Cheers. Comma. Enter. Jaunty.", "Cheers, press enter, jaunty.",
                      "Thanks, enter, jaunty"):
            self.assertEqual(self.fix(heard), heard.replace("jaunty", "Jonti").replace("Jaunty", "Jonti"))
        self.assertEqual(self.fix("Please press enter, jaunty."), "Please press enter, jaunty.")

    def test_a_made_up_word_may_be_a_little_further_off(self):
        # A short "u" for the short "o" of the name, in a word in no dictionary.
        self.assertEqual(self.fix("Cheers, comma, enter, Junty."), "Cheers, comma, enter, Jonti.")
        self.assertEqual(self.fix("I spoke to Junty about it."), "I spoke to Jonti about it.")
        self.assertEqual(self.fix("Junty", before="Cheers,\n"), "Jonti")
        # Not without a dictionary to say that it is made up, nor for a real word or name.
        self.assertEqual(self.fix("I spoke to Junty about it.", lexicon=BARE), "I spoke to Junty about it.")
        known = Lexicon(lower={"is", "here", "we", "hunt", "today"}, capitalised={"Russ"})
        self.assertEqual(vocabulary.by_sound("Russ is here.", "", ("Ross",), known), "Russ is here.")
        self.assertEqual(vocabulary.by_sound("We hunt today.", "", ("Hont",), known), "We hunt today.")


class Saved(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            settings = Settings.load(path)
            self.assertEqual(settings.words, ())
            settings.set_words(("Jonti", "clangd"))
            self.assertEqual(Settings.load(path).words, ("Jonti", "clangd"))

    def test_a_damaged_list_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "settings.json")
            with open(path, "w") as f:
                f.write('{"states": {}, "words": "Jonti"}')
            self.assertEqual(Settings.load(path).words, ())


class BySoundAlone(unittest.TestCase):
    """Sound is thin evidence: an everyday word is not swapped for a listed name."""

    WORDS = Lexicon(lower={"done", "time", "quite", "sure", "jaunty", "how", "you", "am"})

    def fix(self, text, words, before=""):
        return vocabulary.by_sound(text, before, words, self.WORDS)

    def test_everyday_words_stay_whatever_comes_before(self):
        self.assertEqual(self.fix("I'm done.", ("Dan",)), "I'm done.")
        self.assertEqual(self.fix("from time to time", ("Tom",)), "from time to time")
        self.assertEqual(self.fix("I am quite sure", ("Kate",)), "I am quite sure")
        self.assertEqual(self.fix("Done.", ("Dan",)), "Done.")

    def test_a_name_still_goes_in_after_a_greeting_or_a_sign_off(self):
        self.assertEqual(self.fix("Jaunty", ("Jonti",), before="Cheers,\n"), "Jonti")
        self.assertEqual(self.fix("Hi jaunty, how are you?", ("Jonti",)), "Hi Jonti, how are you?")

    def test_and_where_a_name_was_written(self):
        self.assertEqual(self.fix("I'm Jonty.", ("Jonti",)), "I'm Jonti.")
        self.assertEqual(self.fix("Jonty.", ("Jonti",)), "Jonti.")


class Codes(unittest.TestCase):
    """Part numbers and the like: found by their letters and figures, not their sound."""

    WORDS = ("Jonti", "vLR54H20", "vLR5340")

    def spelled(self, text):
        return vocabulary.spell_codes(text, self.WORDS)

    def test_which_words_are_codes(self):
        self.assertEqual([vocabulary.is_code(word) for word in ("vLR5340", "vLR54H20", "Jonti", "MP3", "A1",
                                                                "Win11", "2024")],
                         [True, True, False, True, False, True, False])
        self.assertEqual([vocabulary.is_code(word) for word in ("CO2", "B12", "10th", "3rd party")],
                         [True, True, False, False])
        self.assertEqual(vocabulary.names(self.WORDS), ("Jonti",))

    def test_however_parakeet_wrote_them(self):
        # As Parakeet wrote them for synthesized speech, in three voices and two models.
        for heard, typed in (("The VLR54H20 is the new one.", "The vLR54H20 is the new one."),
                             ("I flashed the VLR 5340 board.", "I flashed the vLR5340 board."),
                             ("I flashed the VLR-5340 board.", "I flashed the vLR5340 board."),
                             ("The VLR 5340, and the VLR 54H20.", "The vLR5340, and the vLR54H20."),
                             ("Use the VLR5340, not the VLR54H20.", "Use the vLR5340, not the vLR54H20."),
                             ("VLR5340.", "vLR5340.")):
            self.assertEqual(self.spelled(heard), typed, heard)

    def test_letters_said_one_by_one_and_figures_said_as_words(self):
        self.assertEqual(self.spelled("the V L R 54 H 20"), "the vLR54H20")
        self.assertEqual(self.spelled("vee el ar fifty three forty"), "vLR5340")
        self.assertEqual(self.spelled("the VLR fifty four H twenty board"), "the vLR54H20 board")
        self.assertEqual(self.spelled("VLR five three four zero"), "vLR5340")
        self.assertEqual(self.spelled("VLR fifty-three forty"), "vLR5340")

    def test_what_stands_around_it_stays(self):
        self.assertEqual(self.spelled("(VLR5340's pins)"), "(vLR5340's pins)")
        self.assertEqual(self.spelled('"VLR 5340",'), '"vLR5340",')

    def test_only_the_same_letters_and_figures(self):
        for heard in ("VLR on its own", "VLR 5341 is not one", "5340 alone", "the VLR 53 board", ""):
            self.assertEqual(self.spelled(heard), heard)

    def test_they_are_not_put_in_by_sound(self):
        # Their sound has no figures, so every code would sound like every other.
        self.assertEqual(vocabulary.by_sound("The VLR board.", "", self.WORDS, DICTIONARY), "The VLR board.")
        self.assertEqual(vocabulary.by_sound("Hi Jonty, the VLR 5340.", "", self.WORDS, DICTIONARY),
                         "Hi Jonti, the VLR 5340.")


class CodesAndEverydayWords(unittest.TestCase):
    """Everyday words can have a code's letters and figures. They are not the code."""

    def test_everyday_words_are_left(self):
        for listed, heard in (
                ("A380", "I saw a 380 pound gorilla."), ("Win11", "we win 11 games"),
                ("TO-220", "from 180 to 220 volts"), ("TO-92", "up to ninety two people"),
                ("UR10", "you are 10 minutes late"), ("A100", "about a 100 people came"),
                ("A380", "it was a 380 mile drive"), ("R100", "there are 100 reasons"),
                ("C130", "I see 130 people"), ("Cat6", "my cat six months ago"),
                ("Win10", "I win ten pounds"), ("OR1200", "1100 or 1200 of them"),
                ("US915", "it cost us 915 dollars"), ("AT90", "turn at 90 degrees"),
                ("IS31", "she is 31 today"), ("Type 2", "I type 2 words"),
                ("ATmega328P", "look at mega 328 P"), ("東京2020", "in 2020 we moved"),
                ("µA741", "it has a 741"), ("A380", "A 380 pound gorilla escaped."),
                ("Win11", "Win 11 games and you are through.")):
            self.assertEqual(vocabulary.spell_codes(heard, (listed,)), heard, listed)

    def test_written_as_a_code_it_is_still_found(self):
        for listed, heard, typed in (
                ("A380", "We flew on an A 380.", "We flew on an A380."),
                ("Win11", "It runs Win 11 now.", "It runs Win11 now."),
                ("TO-220", "a TO 220 package", "a TO-220 package"),
                ("TO-220", "a T O 220 package", "a TO-220 package"),
                ("ATmega328P", "the AT mega 328 P board", "the ATmega328P board"),
                ("Type 2", "It is Type two diabetes.", "It is Type 2 diabetes."),
                ("Über 2000", "the Uber 2000 model", "the Über 2000 model"),
                ("B12", "vitamin b12 and B twelve", "vitamin B12 and B12")):
            self.assertEqual(vocabulary.spell_codes(heard, (listed,)), typed, listed)

    def test_codes_of_three(self):
        self.assertEqual(vocabulary.spell_codes("the MP 3 file and CO 2", ("MP3", "CO2")),
                         "the MP3 file and CO2")
        self.assertEqual(vocabulary.spell_codes("em pee three and see oh two", ("MP3", "CO2")),
                         "MP3 and see oh two")   # "see" is a word first: not the C of CO2

    def test_what_stands_beside_a_code_is_left_alone(self):
        words = ("vLR5340",)
        for heard in ("vLR5340 - a chip", "— vLR5340 is here", "vLR5340 & vLR52", "vLR5340 日本 good",
                      "the VLR. 5340 units were sold", "the VLR, 5340 of them"):
            self.assertEqual(vocabulary.spell_codes(heard, words), heard, heard)
        self.assertEqual(vocabulary.spell_codes("VLR 5340’s price", words), "vLR5340’s price")
        self.assertEqual(vocabulary.spell_codes("VLR 5340's price", words), "vLR5340's price")
        self.assertEqual(vocabulary.spell_codes("the VLR 5340 - a chip", words), "the vLR5340 - a chip")


SMALL = Lexicon(lower={"saw", "spoke", "moved", "ask", "met", "came", "was", "nice", "said", "hello",
                       "yesterday", "it", "new", "to", "and", "the", "in"},
                capitalised={"Amy", "Emma", "Tim", "Plymouth", "Don", "Diane", "Dean", "Donna",
                             "Danny", "June", "Maria", "Mario", "Murray", "John"})


# Nearer a real dictionary: it knows other people's names, has "john" and "rose" as
# everyday words as well, and lists the letter "T" with a capital.
PEOPLE = Lexicon(
    lower={"saw", "spoke", "to", "yesterday", "thanks", "and", "said", "so", "we", "use", "on",
           "the", "board", "model", "is", "rollback", "rang", "john", "rose", "i", "hi", "every",
           "day", "push", "it", "strike", "office", "git", "hub", "kiwi", "rail", "tail", "scale",
           "jaunty", "best", "wishes", "love", "all", "from", "here", "done", "regards", "my",
           "name", "this", "speaking", "cheers", "asked", "call", "went", "by", "connect", "over",
           "am", "a", "little", "tune", "will", "was", "at", "shop"},
    capitalised={"John", "Jon", "Sara", "Sarah", "Catherine", "Phillip", "Allan", "Shaun", "Jeff",
                 "Don", "Dean", "Diane", "Donna", "Danny", "Tim", "June", "Joan", "Maria", "Mario",
                 "Murray", "Amy", "Emma", "Michelle", "Simone", "Rose", "T", "Dan", "Tom", "Mary",
                 "Sam", "Will"})


class WithADictionaryThatKnowsNames(unittest.TestCase):
    """By sound, with a dictionary as full as a real one."""

    def fix(self, text, listed=("Jonti", "Olds"), before=""):
        return vocabulary.by_sound(text, before, listed, PEOPLE)

    def test_john_t_is_jonti_though_the_dictionary_knows_john_and_t(self):
        for heard, typed in (("John T said so.", "Jonti said so."),
                             ("Regards, John T.", "Regards, Jonti."),
                             ("Hi John T,", "Hi Jonti,"),
                             ("My name is John T.", "My name is Jonti."),
                             ("This is John T speaking.", "This is Jonti speaking."),
                             ("I spoke to John T. yesterday.", "I spoke to Jonti yesterday."),
                             ("John T Olds", "Jonti Olds")):
            self.assertEqual(self.fix(heard), typed, heard)
        self.assertEqual(self.fix("I asked John to call."), "I asked John to call.")

    def test_his_own_name_said_by_itself(self):
        # On a line of its own, as when signing a letter: nothing before it in the paragraph.
        self.assertEqual(self.fix("Jaunty."), "Jonti.")
        self.assertEqual(self.fix("Jaunty"), "Jonti")
        # One of the commonest words, said by itself, is that word.
        self.assertEqual(vocabulary.by_sound("Will.", "", ("Wil",), PEOPLE), "Will.")
        self.assertEqual(vocabulary.by_sound("Done.", "", ("Dan",), PEOPLE), "Done.")
        # And inside a sentence an everyday word stays, as before.
        self.assertEqual(self.fix("It was a jaunty little tune."), "It was a jaunty little tune.")

    def test_after_best_wishes_and_love(self):
        for heard, typed in (("Best wishes, jaunty.", "Best wishes, Jonti."),
                             ("All the best, jaunty.", "All the best, Jonti."),
                             ("Love, jaunty.", "Love, Jonti."),
                             ("Cheers, jaunty.", "Cheers, Jonti.")):
            self.assertEqual(self.fix(heard), typed, heard)
        self.assertEqual(self.fix("Jaunty.", before="Best wishes, "), "Jonti.")

    def test_two_capitalised_words_are_one_of_their_words(self):
        listed = ("LibreOffice", "GitHub", "PayPal", "WordPress")
        for heard, typed in (("I use Libre Office every day.", "I use LibreOffice every day."),
                             ("Push it to Git Hub.", "Push it to GitHub."),
                             ("We paid by Pay Pal.", "We paid by PayPal."),
                             ("Publish it with Word Press.", "Publish it with WordPress.")):
            self.assertEqual(self.fix(heard, listed), typed, heard)
        # Written small they are words, and so is the first word of a sentence.
        for heard in ("Publish it with word press.", "Push it to git hub."):
            self.assertEqual(self.fix(heard, listed), heard)
        self.assertEqual(self.fix("I saw Amy at the shop.", ("Sam",)), "I saw Amy at the shop.")
        self.assertEqual(self.fix("Saw Amy at the shop.", ("Sam",)), "Saw Amy at the shop.")

    def test_two_hearings_after_dear_or_hello(self):
        def settle(hinted, plain, words):
            return vocabulary.settle(hinted, plain, "", words, PEOPLE)
        # A common word that is all that follows the greeting is the name it sounds like.
        self.assertEqual(settle("Dear Dan,", "Dear done,", ("Dan",)), "Dear Dan,")
        self.assertEqual(settle("Hello Sam, how are you?", "Hello some, how are you?", ("Sam",)),
                         "Hello Sam, how are you?")
        self.assertEqual(settle("Morning, Tom", "Morning, time", ("Tom",)), "Morning, Tom")
        self.assertEqual(settle("Best, Jonti", "Best, jaunty", ("Jonti",)), "Best, Jonti")
        # Not where the sentence runs on, nor after thanks, nor a word for those written to.
        self.assertEqual(settle("Hi Tom you send it?", "Hi, time you send it?", ("Tom",)),
                         "Hi, time you send it?")
        self.assertEqual(settle("Thanks, Dan.", "Thanks, done.", ("Dan",)), "Thanks, done.")
        self.assertEqual(settle("Hi Tom,", "Hi team,", ("Tom",)), "Hi team,")
        self.assertEqual(settle("Dear Al,", "Dear all,", ("Al",)), "Dear all,")


class OtherPeoplesNames(unittest.TestCase):
    """By sound, a listed name must not take the place of somebody else's, nor swallow
    the word beside it."""

    def fix(self, text, listed, lexicon=SMALL):
        return vocabulary.by_sound(text, "", (listed,), lexicon)

    def test_two_words_are_one_name_only_if_both_look_like_it(self):
        for listed, heard in (("Sam", "I saw Amy."), ("Tom", "I spoke to Emma."),
                              ("Tane", "We moved to New Plymouth."), ("Māori", "Ask Van der Merwe.")):
            self.assertEqual(self.fix(heard, listed), heard, listed)

    def test_another_vowel_is_another_name(self):
        for listed, heard in (("Tom", "I saw Tim."), ("Dan", "I saw Don."), ("Dan", "I saw Diane."),
                              ("Dan", "I spoke to Dean yesterday."), ("Dan", "Donna and Danny came."),
                              ("Jon", "It was in June."), ("Kate", "The Kit Kat was nice."),
                              ("Mary", "Maria and Mario met Murray.")):
            self.assertEqual(self.fix(heard, listed), heard, listed)
            self.assertEqual(self.fix(heard, listed, BARE), heard, listed)   # with no dictionary too

    def test_without_a_dictionary_an_everyday_word_is_not_a_name(self):
        self.assertEqual(self.fix("Done.", "Dan", BARE), "Done.")
        self.assertEqual(self.fix("Time flies.", "Tom", BARE), "Time flies.")

    def test_the_same_name_spelled_the_usual_way_is_put_right(self):
        # What the list is for: the recogniser writes the commoner spelling, which the
        # dictionary knows, and the person's is the other one.
        for listed, heard, typed in (
                ("Jon", "I saw John yesterday.", "I saw Jon yesterday."),
                ("Jon", "I saw Jonn yesterday.", "I saw Jon yesterday."),
                ("Sarah", "Hi Sara,", "Hi Sarah,"),
                ("John", "Thanks, Jon.", "Thanks, John."),
                ("Katherine", "I spoke to Catherine yesterday.", "I spoke to Katherine yesterday."),
                ("Philip", "Thanks, Phillip.", "Thanks, Philip."),
                ("Alan", "Thanks, Allan.", "Thanks, Alan."),
                ("Sean", "I spoke to Jeff and Shaun.", "I spoke to Jeff and Sean."),
                ("Jonti", "Jonte said so.", "Jonti said so."),
                ("Zephyr", "We use Zeffer on the board.", "We use Zephyr on the board."),
                ("Ornith", "The Ornath model is the rollback.", "The Ornith model is the rollback.")):
            for lexicon in (PEOPLE, BARE):
                self.assertEqual(self.fix(heard, listed, lexicon), typed, heard)

    def test_a_name_that_sounds_different_is_left_though_the_dictionary_knows_it(self):
        for listed, heard in (("Dan", "Thanks, Don."), ("Dan", "Thanks, Dean."), ("Dan", "Thanks, Diane."),
                              ("Dan", "Thanks, Donna."), ("Dan", "Thanks, Danny."), ("Tom", "Thanks, Tim."),
                              ("Jon", "June rang."), ("Jon", "Thanks, Joan."), ("Mary", "Thanks, Maria."),
                              ("Mary", "Thanks, Mario."), ("Mary", "Thanks, Murray."), ("Sam", "Thanks, Amy."),
                              ("Tom", "Thanks, Emma."), ("Michael", "Thanks, Michelle."),
                              ("Simon", "Thanks, Simone."), ("Ross", "Thanks, Rose.")):
            for lexicon in (PEOPLE, BARE):
                self.assertEqual(self.fix(heard, listed, lexicon), heard, listed)

    def test_how_names_sound(self):
        key = vocabulary.sound_key
        self.assertEqual(len({key(w) for w in ("Dan", "Don", "Dean", "Diane", "Donna", "Danny")}), 6)
        self.assertEqual(len({key(w) for w in ("Kate", "Kit", "Kat")}), 3)
        self.assertEqual(len({key(w) for w in ("Tom", "Tim", "time", "team")}), 4)
        self.assertEqual(key("Sarah"), key("Sara"))
        self.assertEqual(key("Katie"), key("Katy"))
        self.assertEqual(key("Māori"), key("Maori"))

    def test_the_first_vowel_and_the_number_of_syllables_tell_names_apart(self):
        key = vocabulary.sound_key
        # The same name: the vowels after the first are where its spellings differ.
        for same in (("Jon", "John"), ("Catherine", "Katherine", "Katharine"), ("Phillip", "Philip"),
                     ("Allan", "Alan", "Allen"), ("Shaun", "Sean", "Shawn"), ("Stephen", "Steven"),
                     ("Zeffer", "Zephyr", "Zepher"), ("Ornath", "Ornith"), ("Ann", "Anne"),
                     ("Jonti", "Jonte", "Johnty", "jaunty", "John T"), ("Rachel", "Rachael"),
                     ("Libre Office", "LibreOffice"), ("Git Hub", "GitHub"), ("Pay Pal", "PayPal")):
            self.assertEqual(len({key(w) for w in same}), 1, same)
        # Another name: another first vowel, or more syllables, or fewer.
        for listed, others in (("Dan", ("Don", "Dean", "Diane", "Donna", "Danny", "Dane")),
                               ("Tom", ("Tim", "Tam", "Emma")), ("Jon", ("June", "Joan", "Jan", "Jean", "Johnny")),
                               ("Mary", ("Maria", "Mario", "Murray")), ("Sam", ("Amy", "Same", "Sum")),
                               ("Rose", ("Ross",)), ("Andrew", ("Andrea",)), ("Julie", ("Julia",))):
            for other in others:
                self.assertNotEqual(key(listed), key(other), (listed, other))
        # And one that a silent "e" at the end gives a different last syllable.
        for one, other in (("Michael", "Michelle"), ("Daniel", "Danielle"), ("Simon", "Simone"),
                           ("Dennis", "Denise")):
            self.assertNotEqual(key(one), key(other), (one, other))

    def test_a_letter_that_makes_another_name_is_not_passed_over(self):
        # The dictionary no longer stands guard over other people's names, so the sound has to.
        key = vocabulary.sound_key
        for one, other in (("Ellen", "Helen"), ("Anna", "Hannah"), ("Hemi", "Emma"), ("Mark", "March"),
                           ("Carly", "Charlie"), ("Rick", "Rich"), ("Brook", "Bruce"), ("Maria", "Mario"),
                           ("Paula", "Paulo"), ("Andrew", "Andrea"), ("Olds", "Holds")):
            self.assertNotEqual(key(one), key(other), (one, other))
        # Where the letter makes no difference to the sound the names are still one.
        for same in (("Chris", "Kris"), ("Christine", "Kristine"), ("Chloe", "Khloe"), ("Cindy", "Sindy"),
                     ("Marc", "Mark"), ("Thomas", "Tomas"), ("Lindsay", "Lindsey"), ("Katie", "Katy")):
            self.assertEqual(len({key(w) for w in same}), 1, same)

    def test_a_month_is_not_renamed(self):
        for heard in ("On the 14th of March we fly to Sydney.", "Year 9 camp is in March.",
                      "Next March will be ten years."):
            self.assertEqual(self.fix(heard, "Mark", PEOPLE), heard)
        self.assertEqual(self.fix("Emma and Tom are getting married.", "Hemi", PEOPLE),
                         "Emma and Tom are getting married.")

    def test_the_marks_around_the_word_stay(self):
        self.assertEqual(self.fix('"Johnty said hello"', "Jonti"), '"Jonti said hello"')
        self.assertEqual(self.fix("(Johnty) said", "Jonti"), "(Jonti) said")
        self.assertEqual(self.fix("It was Johnty's.", "Jonti"), "It was Jonti's.")

    def test_the_stop_of_an_initial_goes_with_it(self):
        self.assertEqual(self.fix("I spoke to John T. yesterday.", "Jonti"), "I spoke to Jonti yesterday.")
        self.assertEqual(self.fix("I spoke to John T.", "Jonti"), "I spoke to Jonti.")  # the sentence's

    def test_an_entry_with_a_mark_of_its_own_is_not_given_it_twice(self):
        self.assertEqual(self.fix("We met Nate.", ".NET"), "We met Nate.")
        self.assertEqual(vocabulary.settle("We use .net here.", "We use Nett here.", "", (".NET",), SMALL),
                         "We use .NET here.")


class WordsSaidInPlaceOfAName(unittest.TestCase):
    """After a greeting a name is likely. Not so likely that "team" is Tom."""

    def test_by_sound(self):
        self.assertEqual(vocabulary.by_sound("Hi team,", "", ("Tom",), SMALL), "Hi team,")
        self.assertEqual(vocabulary.by_sound("Thanks, done.", "", ("Dan",), SMALL), "Thanks, done.")
        self.assertEqual(vocabulary.by_sound("Hi all,", "", ("Al", "Aul"), SMALL), "Hi all,")

    def test_with_a_hint(self):
        for lexicon in (SMALL, BARE, None):
            self.assertEqual(vocabulary.settle("I'm Dan.", "I'm done.", "", ("Dan",), lexicon), "I'm done.")
            self.assertEqual(vocabulary.settle("Hi Tom,", "Hi team,", "", ("Tom",), lexicon), "Hi team,")
            self.assertEqual(vocabulary.settle("Thanks, Dan.", "Thanks, done.", "", ("Dan",), lexicon),
                             "Thanks, done.")

    def test_after_im_an_everyday_word_stays_and_a_name_goes_in(self):
        self.assertEqual(settle("I'm Jonti today", "I'm jaunty today"), "I'm jaunty today")
        self.assertEqual(settle("I'm Jonti.", "I'm Johnty."), "I'm Jonti.")
        self.assertEqual(settle("Cheers, Jonti!", "Cheers, jaunty!"), "Cheers, Jonti!")  # a greeting


if __name__ == "__main__":
    unittest.main()
