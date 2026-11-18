import unittest

from dictation.opinions import checked, others, same, settle

SAID = [["question", "mark"], ["full", "stop"], ["new", "line"], ["comma"], ["period"]]  # longest first


class Same(unittest.TestCase):
    def test_capitals_and_punctuation_do_not_count(self):
        self.assertTrue(same("Fill the pool, then pull the cover.", "fill the pool then pull the cover"))
        self.assertTrue(same("", "  "))

    def test_a_different_word_does(self):
        self.assertFalse(same("fill the pool", "fill the pole"))
        self.assertFalse(same("fill the pool", "fill the"))


class Settle(unittest.TestCase):
    def test_the_two_that_agree_win(self):
        self.assertEqual(settle("Fill the pole until it is full.", "fill the pool until it is full",
                                "Fill the pool until it is full."),
                         "Fill the pool until it is full.")
        self.assertEqual(settle("I left the pen on the desk.", "I left the pin on the desk.",
                                "I left the pen on the desk"),
                         "I left the pen on the desk.")

    def test_each_place_is_settled_by_itself(self):
        first = "Her salary went up, so she bought celery and fresh bread."
        second = "Her celery went up so she bought celery and fresh bred."
        third = "her salary went up so she bought salary and fresh bred"
        self.assertEqual(settle(first, second, third),
                         "Her salary went up, so she bought celery and fresh bred.")

    def test_the_first_stands_where_the_third_sides_with_neither(self):
        self.assertEqual(settle("send it for me", "send it from me", "send it to me"), "send it for me")
        self.assertEqual(settle("send it for me", "send it from me", ""), "send it for me")

    def test_words_left_out_or_put_in(self):
        self.assertEqual(settle("we walk the beach", "we walk along the beach", "We walk along the beach."),
                         "we walk along the beach")
        self.assertEqual(settle("we walk along the beach", "we walk the beach", "we walk the beach"),
                         "we walk the beach")

    def test_the_first_ones_punctuation_is_kept_where_they_agree(self):
        self.assertEqual(settle("Yes, the men sat on the bed.", "yes the man sat on the bed", "Yes the men sat on the bed"),
                         "Yes, the men sat on the bed.")

    def test_a_word_put_in_keeps_the_punctuation_and_capital_of_the_one_it_replaces(self):
        self.assertEqual(settle("Fill the pole.", "fill the pool", "fill the pool"), "Fill the pool.")
        self.assertEqual(settle("Pole, then pull it.", "pool then pull it", "pool then pull it"),
                         "Pool, then pull it.")
        self.assertEqual(settle("it was a long, wide beach", "it was along wide beach", "it was along wide beach"),
                         "it was along, wide beach")
        self.assertEqual(settle("so I said pole", "so I said Pool.", "so I said pool"), "so I said Pool.")

    def test_all_three_alike(self):
        self.assertEqual(settle("one phrase", "One phrase.", "one phrase"), "one phrase")


class SpokenPunctuation(unittest.TestCase):
    """One recogniser writes "question mark" and another "?". That is not a difference
    between what they heard, and the words that were said must never be voted away."""

    def test_it_is_not_a_difference(self):
        self.assertTrue(same("is this one better question mark", "Is this one better?", SAID))
        self.assertTrue(same("cheers comma new line Jonti", "Cheers, Jonti", SAID))
        self.assertFalse(same("is this one better question mark", "Is this one beta?", SAID))
        self.assertFalse(same("is this one better question mark", "Is this one better?"))  # not if unlisted

    def test_what_was_said_stays_whoever_wins(self):
        first = "is this one beater question mark"
        self.assertEqual(settle(first, "Is this one better?", "is this one better?", SAID),
                         "is this one better question mark")
        self.assertEqual(settle(first, "Is this one beta?", "is this one better?", SAID), first)
        self.assertEqual(settle("fill the pole comma then pull it", "Fill the pool, then pull it.",
                                "fill the pool then pull it", SAID),
                         "fill the pool comma then pull it")
        self.assertEqual(settle("new line fill the pole full stop", "Fill the pool.", "fill the pool", SAID),
                         "new line fill the pool full stop")

    def test_a_sign_only_the_second_wrote_is_not_put_in(self):
        self.assertEqual(settle("fill the pool then pull", "fill the pool comma then pull", "x", SAID),
                         "fill the pool then pull")

    def test_a_phrase_that_is_only_punctuation(self):
        self.assertTrue(same("question mark", "?", SAID))
        self.assertEqual(settle("question mark", "?", "?", SAID), "question mark")


class OwnWords(unittest.TestCase):
    def test_a_word_that_is_to_be_kept_is_never_voted_away(self):
        keep = lambda words: any(word.strip(",.").lower() == "jonti" for word in words)
        self.assertEqual(settle("Cheers, Jonti", "Cheers, Jaunty.", "cheers jaunty", keep=keep), "Cheers, Jonti")
        self.assertEqual(settle("Cheers, Jonti and the pole", "Cheers, Jaunty and the pool", "cheers jaunty and the pool",
                                keep=keep), "Cheers, Jonti and the pool")


class TheSameWordWrittenTwoWays(unittest.TestCase):
    """How a word is written is not something recognisers differ on in what they heard."""

    def test_a_title_long_or_short(self):
        self.assertEqual(settle("Dr. Smith is here.", "Doctor Smith is here.", "Doctor Smith is here."),
                         "Dr. Smith is here.")
        self.assertTrue(same("Dr. Smith is here.", "doctor Smith is here"))

    def test_a_british_and_an_american_spelling(self):
        self.assertEqual(settle("The colour is red.", "The color is red.", "The color is red."),
                         "The colour is red.")
        self.assertTrue(same("I realise that", "I realize that."))
        self.assertFalse(same("the colour is red", "the collar is red"))

    def test_a_shortenings_stop_is_not_handed_to_the_word_that_replaces_it(self):
        self.assertEqual(settle("St. John is here.", "Saint John is here.", "Saint John is here."),
                         "Saint John is here.")
        self.assertEqual(settle("Fill the pole.", "fill the pool", "fill the pool"), "Fill the pool.")


class Checked(unittest.TestCase):
    def ask(self, hearings):
        self.asked = []

        def ask(model):
            self.asked.append(model)
            return hearings.get(model)
        return ask

    def test_who_is_asked(self):
        self.assertEqual(others("parakeet-tdt-0.6b-v2"), ("small.en", "medium.en"))
        self.assertEqual(others("small.en"), ("medium.en", "parakeet-tdt-0.6b-v2"))
        self.assertEqual(others("large-v3"), ("small.en", "medium.en"))

    def test_the_same_and_the_third_is_not_asked(self):
        ask = self.ask({"small.en": "Fill the pool."})
        self.assertEqual(checked("fill the pool", "parakeet-tdt-0.6b-v2", ask), ("fill the pool", "the same"))
        self.assertEqual(self.asked, ["small.en"])

    def test_they_differ_and_the_third_settles_it(self):
        ask = self.ask({"small.en": "fill the pool", "medium.en": "fill the pool"})
        self.assertEqual(checked("fill the pole", "parakeet-tdt-0.6b-v2", ask),
                         ("fill the pool", "differed, and changed"))
        self.assertEqual(self.asked, ["small.en", "medium.en"])
        ask = self.ask({"small.en": "I left the pin", "medium.en": "I left the pen"})
        self.assertEqual(checked("I left the pen", "parakeet-tdt-0.6b-v2", ask),
                         ("I left the pen", "differed, and stood"))

    def test_a_murmur_that_only_the_first_took_for_words_is_dropped(self):
        ask = self.ask({"small.en": "", "medium.en": ""})
        self.assertEqual(checked("Mm.", "parakeet-tdt-0.6b-v2", ask), ("", "differed, and changed"))
        self.assertEqual(checked("Uh, mm-hmm.", "parakeet-tdt-0.6b-v2", ask)[0], "")

    def test_real_words_are_never_dropped_because_the_others_heard_nothing(self):
        # Whisper says nothing to some short phrases that were said: its silence isn't a vote.
        ask = self.ask({"small.en": "", "medium.en": ""})
        self.assertEqual(checked("Pyramid.", "parakeet-tdt-0.6b-v2", ask),
                         ("Pyramid.", "the second heard nothing, and it stood"))
        self.assertEqual(self.asked, ["small.en"])       # and the third isn't troubled
        ask = self.ask({"small.en": "", "medium.en": "send it now"})
        self.assertEqual(checked("Send it now.", "parakeet-tdt-0.6b-v2", ask)[0], "Send it now.")
        ask = self.ask({"small.en": ".", "medium.en": ""})
        self.assertEqual(checked("Scratch that", "parakeet-tdt-0.6b-v2", ask)[0], "Scratch that")

    def test_some_words_can_still_be_voted_out_of_a_phrase(self):
        ask = self.ask({"small.en": "send it now", "medium.en": "Send it now."})
        self.assertEqual(checked("Send it uh now.", "parakeet-tdt-0.6b-v2", ask)[0], "Send it now.")

    def test_nobody_to_ask(self):
        self.assertEqual(checked("fill the pole", "parakeet-tdt-0.6b-v2", self.ask({})),
                         ("fill the pole", "nobody to ask"))
        self.assertEqual(checked("fill the pole", "parakeet-tdt-0.6b-v2", self.ask({"small.en": "fill the pool"})),
                         ("fill the pole", "differed, with nobody to settle it"))


if __name__ == "__main__":
    unittest.main()
