"""Putting right what was typed a moment ago: which words may be touched, how a change
is fitted into the next insertion, the join rules, and what was taken back."""
import unittest

from dictation import tidy
from dictation.tidy import Change, Refused, amend, last_sentences, ours


def swap(old, new, kind="word"):
    """A check that changes each whole word `old` to `new`, wherever it stands."""
    import re

    def check(whole, starts):
        return [Change(m.start(), m.end(), new, kind) for m in re.finditer(rf"\b{old}\b", whole)]
    return check


class WhatIsOurs(unittest.TestCase):
    """Only what this program typed, and only while it is as it typed it."""

    def test_all_of_it_while_nothing_has_changed(self):
        self.assertEqual(ours("Dear Sam, take the cat too", "take the cat too"), "take the cat too")
        self.assertEqual(ours("take the cat too", "take the cat too"), "take the cat too")

    def test_from_the_cursor_back_to_where_the_person_changed_something(self):
        # "cat" was changed to "dog" by hand: from there back is theirs now.
        self.assertEqual(ours("take the dog too", "take the cat too"), "too")
        self.assertEqual(ours("take the cat too far", "take the cat too"), "")

    def test_none_of_it_when_the_cursor_is_somewhere_else(self):
        self.assertEqual(ours("Something else entirely", "take the cat too"), "")
        self.assertEqual(ours("", "take the cat too"), "")
        self.assertEqual(ours("take the cat too", ""), "")

    def test_a_word_is_not_the_end_of_a_longer_word(self):
        # "to" was typed; the text now ends "tomato": that is not it.
        self.assertEqual(ours("a ripe tomato", "going to"), "")
        self.assertEqual(ours("going to", "going to"), "going to")

    def test_it_starts_at_the_start_of_a_word(self):
        self.assertEqual(ours("He said the cat too", "I saw the cat too"), "the cat too")

    def test_only_so_much_is_remembered(self):
        run = "word " * 200
        self.assertLessEqual(len(ours("x " + run, run)), tidy.RUN_LENGTH)


class HowFarBack(unittest.TestCase):
    def test_the_sentence_being_gone_on_with_and_one_more(self):
        text = "One is here. Two is here. Three is here. And four"
        self.assertEqual(last_sentences(text), "Three is here. And four")
        self.assertEqual(last_sentences(text, 1), "And four")
        self.assertEqual(last_sentences("No end yet"), "No end yet")

    def test_a_dot_inside_a_sentence_is_no_end(self):
        self.assertEqual(last_sentences("It costs 3.50 at the shop. We met at 3 p.m. and left"),
                         "It costs 3.50 at the shop. We met at 3 p.m. and left")

    def test_a_new_line_starts_one(self):
        self.assertEqual(last_sentences("Dear Sam\nThanks for that\nI will come", 2),
                         "Thanks for that\nI will come")


class FittingAChangeIn(unittest.TestCase):
    """The change goes in with the new words: the end of what was typed is taken out and
    typed again, put right."""

    def test_with_nothing_to_change_the_insertion_is_as_it_was(self):
        self.assertEqual(amend(" the vet", 0, "take the cat to", "take the cat to", [swap("too", "to")])[:3],
                         (" the vet", 0, []))

    def test_a_word_before_is_put_right_as_the_new_words_go_in(self):
        text, delete, changes, whole = amend(" the vet", 0, "Take the cat too", "Take the cat too",
                                             [swap("too", "to")])
        self.assertEqual((text, delete), ("to the vet", 3))        # "too" goes, "to the vet" comes
        self.assertEqual(whole, "Take the cat too the vet")
        self.assertEqual([(c.start, c.end, c.new) for c in changes], [(13, 16, "to")])

    def test_everything_before_the_first_change_stays_untouched(self):
        text, delete, _, _ = amend(" was", 0, "I think the bare in the wood", "I think the bare in the wood",
                                   [swap("bare", "bear")])
        self.assertEqual((text, delete), ("bear in the wood was", len("bare in the wood")))

    def test_a_change_in_the_new_words_alone_takes_nothing_out(self):
        self.assertEqual(amend(" too the vet", 0, "Take the cat", "Take the cat", [swap("too", "to")])[:2],
                         (" to the vet", 0))

    def test_what_the_insertion_already_takes_out_is_counted_in(self):
        # The fitting takes a space out first; the change reaches back past it.
        text, delete, _, _ = amend(", I think", 1, "the cat too ", "the cat too ", [swap("too", "to")])
        self.assertEqual((text, delete), ("to, I think", 4))

    def test_what_the_person_changed_is_out_of_reach(self):
        # They put "too" back by hand, further up: only "far" is this program's now.
        self.assertEqual(amend(" away", 0, "the cat too far", "the cat to far", [swap("too", "to")])[:3],
                         (" away", 0, []))

    def test_what_another_program_typed_or_an_earlier_paragraph_is_out_of_reach(self):
        self.assertEqual(amend(" the vet", 0, "Take the cat too", "", [swap("too", "to")])[:3],
                         (" the vet", 0, []))
        before = "Me too. That is one. That is two. Take the cat"
        text, delete, changes, _ = amend(" the vet", 0, before, before, [swap("too", "to")])
        self.assertEqual((text, delete, changes), (" the vet", 0, []))    # three sentences back

    def test_two_changes_to_the_same_words_are_one(self):
        text, delete, changes, _ = amend(" the vet", 0, "the cat too", "the cat too",
                                         [swap("too", "to"), swap("too", "two")])
        self.assertEqual((text, len(changes)), ("to the vet", 1))

    def test_a_change_that_changes_nothing_is_none(self):
        self.assertEqual(amend(" x", 0, "to", "to", [swap("to", "to")])[2], [])


class TheJoin(unittest.TestCase):
    def joined(self, typed, new, not_said=True):
        text, delete, changes, _ = amend(new, 0, typed, typed, [tidy.stop_before_comma(not_said)])
        return typed[:len(typed) - delete] + text, [c.kind for c in changes]

    def test_the_recognisers_stop_goes_when_the_next_phrase_starts_with_a_comma(self):
        self.assertEqual(self.joined("Hi Rick.", ", how are you?"), ("Hi Rick, how are you?", ["join"]))
        self.assertEqual(self.joined("We left.", "; they stayed"), ("We left; they stayed", ["join"]))
        self.assertEqual(self.joined("There are three.", ": one"), ("There are three: one", ["join"]))

    def test_a_stop_that_was_said_stays(self):
        self.assertEqual(self.joined("Hi Rick.", ", how are you?", not_said=False),
                         ("Hi Rick., how are you?", []))

    def test_the_dot_of_a_short_form_stays(self):
        for typed in ("We met at 3 p.m.", "Apples, pears etc.", "In the U.S.", "Ask Dr.",
                      "It weighs approx.", "See Fig.", "On 3 Jan."):
            self.assertEqual(self.joined(typed, ", and then"), (typed + ", and then", []), typed)

    def test_dots_that_trail_off_stay(self):
        self.assertEqual(self.joined("Well...", ", maybe"), ("Well..., maybe", []))

    def test_without_a_comma_next_nothing_is_done(self):
        self.assertEqual(self.joined("Hi Rick.", " How are you?"), ("Hi Rick. How are you?", []))


class ANameAfterAGreetingThatWasMade(unittest.TestCase):
    def fixed(self, typed, new):
        check = tidy.chained(lambda found: swap("[Hh]igh", "Hi"), tidy.name_after_greeting)
        text, delete, changes, _ = amend(new, 0, typed, typed, [check])
        return typed[:len(typed) - delete] + text, [c.kind for c in changes]

    def test_it_gets_its_capital(self):
        self.assertEqual(self.fixed("High rick", ", how are you?"),
                         ("Hi Rick, how are you?", ["word", "capital"]))
        self.assertEqual(self.fixed("Thanks for that. High rick", ""),
                         ("Thanks for that. Hi Rick", ["word", "capital"]))

    def test_a_word_that_is_no_name_is_left(self):
        for typed in ("High there", "High everyone", "High again"):
            self.assertEqual(self.fixed(typed, ", how are you?")[1], ["word"], typed)

    def test_more_than_one_word_is_left(self):
        self.assertEqual(self.fixed("High rick and jill", ", how are you?")[0],
                         "Hi rick and jill, how are you?")

    def test_a_name_that_has_its_capital_is_left(self):
        self.assertEqual(self.fixed("High Rick", ", how are you?"), ("Hi Rick, how are you?", ["word"]))


class TakenBack(unittest.TestCase):
    def setUp(self):
        self.whole = "Take the cat too the vet"
        self.change = Change(13, 16, "to")

    def test_undone_once_it_is_not_made_again_in_the_same_words(self):
        refused = Refused()
        self.assertFalse(refused.has(self.whole, self.change))
        refused.add(self.whole, self.change)
        self.assertTrue(refused.has(self.whole, self.change))
        self.assertTrue(refused.has("Please take the cat too my mother", Change(20, 23, "to")))
        self.assertFalse(refused.has("I want too go", Change(7, 10, "to")))       # other words before it
        self.assertEqual(amend(" the vet", 0, "Take the cat too", "Take the cat too",
                               [swap("too", "to")], refused)[:3], (" the vet", 0, []))

    def test_scratched_it_takes_twice(self):
        refused = Refused()
        refused.add(self.whole, self.change, sure=False)
        self.assertFalse(refused.has(self.whole, self.change))
        refused.add(self.whole, self.change, sure=False)
        self.assertTrue(refused.has(self.whole, self.change))

    def test_the_same_swap_undone_in_two_places_is_not_made_anywhere(self):
        refused = Refused()
        refused.add(self.whole, self.change)
        self.assertFalse(refused.has("I want too go", Change(7, 10, "to")))
        refused.add("He went too school", Change(8, 11, "to"))
        self.assertTrue(refused.has("I want too go", Change(7, 10, "to")))
        self.assertFalse(refused.has("me to", Change(3, 5, "too")))                # the other way is another swap


class HeardAgain(unittest.TestCase):
    """A sentence said in two phrases, heard again as one."""

    def test_how_many_words_changed(self):
        self.assertEqual(tidy.words_changed("Take the cat too the vet", "Take the cat to the vet"), 1)
        self.assertEqual(tidy.words_changed("Take the cat. To the vet", "take the cat to the vet"), 0)
        self.assertEqual(tidy.words_changed("a walk in the part", "a walk in the park today"), 2)
        self.assertEqual(tidy.words_changed("", "two words"), 2)

    def test_it_is_typed_when_a_word_or_two_is_put_right(self):
        self.assertTrue(tidy.worth_typing("Take the cat too the vet", "Take the cat to the vet"))
        self.assertTrue(tidy.worth_typing("Hi Rick. How are you", "Hi Rick, how are you"))   # marks alone
        self.assertTrue(tidy.worth_typing("we went a part", "we went apart again"))

    def test_it_is_not_typed_when_it_is_the_same_or_something_else_altogether(self):
        self.assertFalse(tidy.worth_typing("Take the cat to the vet", "Take the cat to the vet"))
        self.assertFalse(tidy.worth_typing("Take the cat to the vet", ""))
        self.assertFalse(tidy.worth_typing("Take the cat to the vet tomorrow morning please",
                                           "Thank you for watching and see you all next time"))
        self.assertFalse(tidy.worth_typing("one two three four five six seven eight",
                                           "one two nine ten eleven six seven eight"))     # 3 of 8

    def test_it_is_cut_where_the_two_phrases_met(self):
        cut = tidy.split_like
        self.assertEqual(cut("Take the cat to the vet", "Take the cat too", " the vet"),
                         ("Take the cat to", " the vet"))
        self.assertEqual(cut("Hi Rick, how are you", "Hi Rick.", " How are you"),
                         ("Hi Rick", ", how are you"))
        self.assertEqual(cut("Hi Rick, how are you", "High rick", ", how are you"),
                         ("Hi Rick", ", how are you"))
        # A word put right at the very join goes with the phrase it was in.
        self.assertEqual(cut("a walk in the park with the dog", "a walk in the part", " with the dog"),
                         ("a walk in the park", " with the dog"))
        self.assertEqual(cut("we saw bears and wolves", "we saw", " bares and wolves"),
                         ("we saw", " bears and wolves"))

    def test_a_word_that_was_lost_at_the_join_comes_back_in_one_of_them(self):
        first, second = tidy.split_like("a cup of tea with milk", "a cup", " tea with milk")
        self.assertEqual(first + second, "a cup of tea with milk")
        self.assertIn(first, ("a cup", "a cup of"))

    def test_with_nothing_to_go_by_there_is_no_cut(self):
        self.assertIsNone(tidy.split_like("word", "one", " two"))
        self.assertIsNone(tidy.split_like("one two", "", " two"))
        self.assertIsNone(tidy.split_like("quite other words here", "one two", " three four"))


class ForTheLog(unittest.TestCase):
    def test_it_says_how_many_of_what_and_never_the_words(self):
        said = tidy.kinds([Change(0, 3, "to"), Change(5, 8, "then"), Change(9, 10, "", "join"),
                           Change(11, 15, "Rick", "capital")])
        self.assertEqual(said, "2 x a word that sounds like another, a full stop before a comma, "
                               "a capital for a name")
        self.assertNotIn("then", said.replace("then", "", 0) if False else said.split(",")[1])


if __name__ == "__main__":
    unittest.main()
