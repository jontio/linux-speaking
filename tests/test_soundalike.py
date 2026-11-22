import os
import unittest
import unittest.mock

from dictation import soundalike
from dictation.soundalike import BREAK, END, NUMBER, Change, apply, decide, pieces, places, suggest


def counts(words, totals, **met):
    """A set's counts made by hand: `met` is place -> how often each word stood there,
    with _ for the space in a place's name ("R_the", "B_going_far")."""
    made = soundalike._Counts(tuple(words), tuple(totals))
    made.met = {key.replace("_", " "): tuple(row) for key, row in met.items()}
    return made


def fixed(before, phrase, **kw):
    return apply(before + phrase, suggest(before, phrase, **kw))


class CuttingTextIntoWords(unittest.TestCase):
    def names(self, text):
        return [part[0] for part in pieces(text)]

    def test_words_are_in_small_letters_and_marks_are_neighbours_too(self):
        self.assertEqual(self.names("Take the cat, too. Then go!"),
                         ["take", "the", "cat", BREAK, "too", END, "then", "go", END])

    def test_figures_are_all_one_to_their_neighbours(self):
        self.assertEqual(self.names("It cost 2.50 and took 3 days"),
                         ["it", "cost", NUMBER, "and", "took", NUMBER, "days"])

    def test_a_word_keeps_the_mark_of_a_letter_left_out(self):
        self.assertEqual(self.names("They’re sure it's the dogs' bowl"),
                         ["they're", "sure", "it's", "the", "dogs", "bowl"])

    def test_a_title_ends_no_sentence(self):
        self.assertEqual(self.names("Ask Mr. Smith. He knows."),
                         ["ask", "mr", "smith", END, "he", "knows", END])

    def test_a_new_line_ends_a_sentence(self):
        self.assertEqual(self.names("Dear Bob\nthanks"), ["dear", "bob", END, "thanks"])

    def test_it_says_which_words_are_inside_quotation_marks(self):
        inside = {part[4] for part in pieces("He said \"too late\" and ‘two’ and 'to go' then left") if part[3]}
        self.assertEqual(inside, {"too", "late", "two", "to", "go"})

    def test_where_each_word_is(self):
        text = "Go too far"
        self.assertEqual([text[part[1]:part[2]] for part in pieces(text)], ["Go", "too", "far"])


class ThePlacesAWordIsKnownBy(unittest.TestCase):
    def test_in_the_middle_of_a_sentence(self):
        self.assertEqual(places([END, "take", "the", "cat", "too", "the", "vet"], 4),
                         [("L", "cat"), ("LL", "the cat"), ("R", "the"), ("RR", "the vet"), ("B", "cat the")])

    def test_what_is_not_known_is_not_told(self):
        self.assertEqual(places(["the", "cat", "too"], 2), [("L", "cat"), ("LL", "the cat")])
        self.assertEqual(places(["too", "the"], 0), [("R", "the")])

    def test_nothing_is_told_across_the_end_of_a_sentence(self):
        told = dict(places(["gone", END, "too", END, "then"], 2))
        self.assertEqual(told, {"L": END, "R": END, "B": END + " " + END})


class Deciding(unittest.TestCase):
    """With counts made by hand: "to" met 30,000 times and "too" 1,000. The other word has
    to be 20 times as likely at a pause, and 400 times anywhere else."""

    SET = counts(("to", "too"), (30000, 1000),
                 R_the=(4000, 2), L_cat=(30, 3), L_going=(900, 2), R_far=(20, 60),
                 B_going_far=(0, 40), L_very=(3, 120), R_much=(15, 300))

    def said(self, names, at, where="", **kw):
        kw.setdefault("threshold", 20.0)
        kw.setdefault("elsewhere", 400.0)
        chosen = decide(self.SET, names, at, where, **kw)
        return None if chosen is None else self.SET.words[chosen[0]]

    def test_before_a_pause_the_words_after_it_decide(self):
        self.assertEqual(self.said(["take", "the", "cat", "too", "the", "vet"], 3, "before"), "to")
        self.assertIsNone(self.said(["take", "the", "cat", "to", "the", "vet"], 3, "before"))

    def test_before_a_pause_nothing_is_changed_on_the_words_before_it_alone(self):
        # "going to" is far the commoner, but what comes after is not a place either
        # word has been met in: it says nothing, so nothing is done.
        self.assertIsNone(self.said(["going", "too", "zebras"], 1, "before"))
        self.assertIsNone(self.said(["going", "too"], 1, "before"))        # nor with nothing after it yet

    def test_after_a_pause_the_words_before_it_decide(self):
        self.assertEqual(self.said(["going", "too", "zebras"], 1, "after"), "to")
        self.assertIsNone(self.said(["zebras", "too", "the"], 1, "after"))

    def test_the_two_it_stands_between_say_more_than_each_side(self):
        # "going to" and then "far": between those two it is "too", whatever each says alone.
        self.assertIsNone(self.said(["going", "too", "far"], 1, "before"))
        self.assertEqual(self.said(["going", "to", "far"], 1, "before"), "too")

    def test_away_from_a_pause_it_takes_much_more(self):
        names = ["take", "the", "cat", "too", "the", "vet"]
        self.assertIsNone(self.said(names, 3, ""))                           # the recogniser saw both sides
        self.assertEqual(self.said(names, 3, "", elsewhere=10.0), "to")     # unless asked for less

    def test_the_threshold_is_the_callers_to_set(self):
        self.assertIsNone(self.said(["very", "too", "much"], 1, "before"))
        self.assertEqual(self.said(["very", "to", "much"], 1, "before"), "too")
        self.assertIsNone(self.said(["very", "to", "much"], 1, "before", threshold=100000.0))

    def test_a_set_can_be_held_to_more_than_the_others(self):
        names = ["take", "the", "cat", "too", "the", "vet"]
        with unittest.mock.patch.dict(soundalike.HARDER, {"to": 50.0}):
            self.assertIsNone(self.said(names, 3, "before"))
        self.assertEqual(self.said(names, 3, "before"), "to")

    def test_a_few_meetings_count_for_less_than_they_look(self):
        how, met = soundalike.ratio(self.SET, "L cat", 1, 0)                # 3 of 1,000 against 30 of 30,000
        self.assertTrue(met)
        self.assertLess(how, 3.0 / 1000 / (30.0 / 30000))                   # less than taking it at its word
        self.assertEqual(soundalike.ratio(self.SET, "L dog", 1, 0), (1.0, False))    # never met: nothing said


class WhatIsSaidOfAText(unittest.TestCase):
    """With the counts as they are shipped."""

    def test_the_word_before_a_pause_is_put_right_once_the_rest_is_there(self):
        changes = suggest("Take the cat too", " the vet")
        self.assertEqual([(c.start, c.end, c.new, c.old) for c in changes], [(13, 16, "to", "too")])
        self.assertGreaterEqual(changes[0].sure, soundalike.THRESHOLD)
        self.assertLessEqual(changes[0].sure, soundalike.CERTAIN)
        self.assertEqual(fixed("Take the cat too", " the vet"), "Take the cat to the vet")

    def test_the_right_word_is_left_alone(self):
        for before, phrase in (("Take the cat to", " the vet"), ("I want to go", " too"),
                               ("It is bigger than", " mine"), ("We ate and then", " we left"),
                               ("I guessed", " the answer"), ("The cupboard was", " bare"),
                               ("I know", " what to do"), ("They went there", " by train")):
            self.assertEqual(suggest(before, phrase), [], before + phrase)

    def test_the_named_mix_ups(self):
        for before, phrase, want in (
                ("It is bigger then", " mine", "It is bigger than mine"),
                ("It is bigger", " then mine", "It is bigger than mine"),
                ("I guest", " the answer", "I guessed the answer"),
                ("I", " guest the answer", "I guessed the answer"),
                ("I don't no", " what to do", "I don't know what to do"),
                ("Is that you're", " coat", "Is that your coat"),
                ("I think there", " going home", "I think they're going home"),
                ("Did you here", " that noise", "Did you hear that noise"),
                ("The dog wagged it's", " tail", "The dog wagged its tail"),
                ("I new", " it was wrong", "I knew it was wrong")):
            self.assertEqual(fixed(before, phrase), want)

    def test_what_is_likely_but_not_likely_enough_is_left(self):
        # "Was bare" is some twenty times as common as "was bear" in the books: likely,
        # and not sure enough to change what somebody may have meant.
        self.assertEqual(suggest("The cupboard was", " bear"), [])
        self.assertEqual(fixed("The cupboard was", " bear", threshold=10.0), "The cupboard was bare")

    def test_with_nothing_after_it_yet_nothing_is_said(self):
        self.assertEqual(suggest("Take the cat", " too"), [])

    def test_it_keeps_the_capitals_of_what_was_written(self):
        self.assertEqual(fixed("Then they went Too", " the shops"), "Then they went To the shops")
        self.assertEqual(fixed("THEN THEY WENT TOO", " THE SHOPS"), "THEN THEY WENT TO THE SHOPS")

    def test_a_word_inside_quotation_marks_is_left_alone(self):
        self.assertEqual(suggest('She wrote "take the cat too', ' the vet" on the card'), [])
        self.assertEqual(suggest("She wrote ‘take the cat too", " the vet’ on the card"), [])

    def test_one_of_the_persons_own_words_is_left_alone(self):
        self.assertEqual(suggest("Take the cat too", " the vet", protected=["Too"]), [])
        self.assertEqual(len(suggest("Take the cat too", " the vet", protected=["vet"])), 1)

    def test_what_the_program_did_not_type_is_left_alone(self):
        before = "Take the cat too"
        self.assertEqual(suggest(before, " the vet", changeable_from=len(before)), [])
        self.assertEqual(len(suggest(before, " the vet", changeable_from=13)), 1)

    def test_the_text_after_the_cursor_is_read_but_never_changed(self):
        self.assertEqual(fixed("We went", " too", after=" the shops and came back"), "We went to")
        self.assertEqual(suggest("We went to", " see", after=" too the shops"), [])

    def test_a_threshold_nothing_reaches_says_nothing(self):
        self.assertEqual(suggest("Take the cat too", " the vet", threshold=soundalike.CERTAIN * 1000), [])

    def test_no_text_and_text_with_no_such_words(self):
        self.assertEqual(suggest("", ""), [])
        self.assertEqual(suggest("The quick brown fox", " jumps over the lazy dog"), [])

    def test_apply_makes_the_changes_whatever_their_order_and_length(self):
        text = "go too the shop and by milk"
        self.assertEqual(apply(text, [Change(20, 22, "buy", "by", 50.0), Change(3, 6, "to", "too", 50.0)]),
                         "go to the shop and buy milk")


class HiAndHigh(unittest.TestCase):
    def test_high_before_a_name_at_the_start_is_a_greeting(self):
        self.assertEqual(fixed("", "High Rick, how are you"), "Hi Rick, how are you")
        self.assertEqual(fixed("High Rick", ", how are you"), "Hi Rick, how are you")
        self.assertEqual(fixed("Thanks. High Jill", ", see you at ten"), "Thanks. Hi Jill, see you at ten")

    def test_and_before_a_name_that_lost_its_capital(self):
        self.assertEqual(fixed("High rick", ", how are you?"), "Hi rick, how are you?")
        self.assertEqual(fixed("", "high rick, how are you?"), "hi rick, how are you?")

    def test_and_before_a_word_that_stands_for_people_or_a_comma(self):
        self.assertEqual(fixed("", "High everyone,"), "Hi everyone,")
        self.assertEqual(fixed("", "High there."), "Hi there.")
        self.assertEqual(fixed("", "High, how are you"), "Hi, how are you")

    def test_high_that_is_high_stays(self):
        for text in ("High Street is closed today", "High Court judges, he said", "High tide is at noon",
                     "High prices, low wages", "The fence is too high for me", "High above the town",
                     "It was high time, I think", "High"):
            self.assertEqual(suggest("", text), [], text)

    def test_hi_that_was_high(self):
        self.assertEqual(fixed("", "The fence is too hi for me"), "The fence is too high for me")
        self.assertEqual(fixed("", "They sell at a very hi price"), "They sell at a very high price")

    def test_hi_that_is_hi_stays(self):
        for text in ("Hi Rick, how are you", "She said hi to everyone", "Say hi for me", "Hi there"):
            self.assertEqual(suggest("", text), [], text)


class TheCountsThatAreShipped(unittest.TestCase):
    def test_the_file_is_small_and_names_its_books(self):
        self.assertLess(os.path.getsize(soundalike.DATA), 700 * 1000)
        with open(soundalike.DATA, encoding="utf-8") as f:
            head = [next(f) for _ in range(4)]
        self.assertIn("Project Gutenberg", "".join(head))

    def test_every_set_has_counts_and_no_word_is_in_two(self):
        known = soundalike.tables()
        seen = set()
        for words in soundalike.SETS:
            for word in words:
                self.assertNotIn(word.lower(), seen)
                seen.add(word.lower())
                self.assertIn(word.lower(), known, word)
                self.assertEqual(known[word.lower()].words, words)
        self.assertEqual(set(known), seen)

    def test_each_place_has_a_figure_for_each_word_of_its_set(self):
        for table in {id(t): t for t in soundalike.tables().values()}.values():
            self.assertEqual(len(table.totals), len(table.words))
            self.assertTrue(table.met)
            for key, row in table.met.items():
                self.assertEqual(len(row), len(table.words), key)
                self.assertIn(key.split(" ")[0], ("L", "R", "LL", "RR", "B"))

    def test_a_set_taken_out_of_the_list_is_not_looked_at(self):
        with unittest.mock.patch.object(soundalike, "SETS", soundalike.SETS[1:]):
            known = soundalike.tables(soundalike.DATA)
        self.assertNotIn("too", known)
        self.assertIn("their", known)

    def test_a_file_that_is_not_there_says_nothing(self):
        self.assertEqual(soundalike.tables(os.path.join(os.path.dirname(soundalike.DATA), "no-such-file.txt")), {})


if __name__ == "__main__":
    unittest.main()
