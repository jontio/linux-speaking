"""The engine putting right what it typed a moment ago, as the next phrase goes in."""
import unittest
from unittest import mock

from dictation import tidy
from dictation.tidy import Change

from tests.test_engine_telling import bare


class Page:
    """Stands in for a program that is typed into, and keeps its text as one would: what
    is before the cursor, each insertion as one step that can be taken back."""

    name = "Writer"
    other = None

    def __init__(self, text="", restores=False):
        # `restores` is whether taking a phrase back also puts back what it took out
        # before it. The programs' own "scratch that" does not: it takes away what was
        # typed, and that is all.
        self.text, self.steps, self.asked, self.restores = text, [], [], restores

    def describe(self):
        return "a page"

    def pick(self):
        pass

    def request(self, message):
        self.asked.append(dict(message))
        op = message["op"]
        if op == "context":
            return {"ok": True, "before": self.text[-200:], "after": ""}
        if op == "insert":
            cut = len(self.text) - int(message.get("delete_before", 0))
            self.steps.append((self.text, self.text[:cut]))
            self.text = self.text[:cut] + message["text"]
            return {"ok": True}
        if op == "command" and message["name"] in ("scratch", "undo"):
            if not self.steps:
                return {"ok": False, "why": "nothing to take back"}
            self.text = self.steps.pop()[0 if self.restores else 1]
            return {"ok": True}
        return {"ok": False, "why": "unknown command"}

    def inserts(self):
        return [(m["text"], m.get("delete_before", 0)) for m in self.asked if m["op"] == "insert"]


class AsThePhraseGoesIn(unittest.TestCase):
    def setUp(self):
        patch = mock.patch("dictation.engine.log")
        self.log = patch.start()
        self.addCleanup(patch.stop)

    def engine(self, page, **states):
        engine = bare(page, **states)
        engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
        return engine

    def said(self, engine, *phrases):
        for phrase in phrases:
            engine.handle_text(phrase, True)
        return engine.targets.text

    def test_the_recognisers_stop_goes_when_the_next_phrase_starts_with_a_comma(self):
        page = Page()
        engine = self.engine(page, keep_final=True)
        self.assertEqual(self.said(engine, "Hi Rick."), "Hi Rick.")
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Rick, how are you?")
        # In one step: the stop is taken out and the new words typed.
        self.assertEqual(page.inserts(), [("Hi Rick.", 0), (", how are you?", 1)])
        self.assertIn("put right as the phrase went in: a full stop before a comma",
                      [call[0][0] for call in self.log.call_args_list])

    def test_scratch_that_takes_the_phrase_and_the_change_back_together(self):
        page = Page()
        engine = self.engine(page, keep_final=True)
        self.said(engine, "Hi Rick.", ", how are you?")
        self.assertEqual(self.said(engine, "scratch that"), "Hi Rick.")
        # And said again, it is put right again: once taken back that way may only mean
        # the new words were misheard.
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Rick, how are you?")
        # Twice says it was the change that was not wanted.
        self.assertEqual(self.said(engine, "scratch that", ", how are you?"), "Hi Rick., how are you?")

    def test_undo_that_says_it_was_not_wanted_and_it_is_not_done_again_there(self):
        page = Page()
        engine = self.engine(page, keep_final=True)
        self.said(engine, "Hi Rick.", ", how are you?")
        self.assertEqual(self.said(engine, "undo that"), "Hi Rick.")
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Rick., how are you?")
        self.assertIn("what was put right with the last phrase was taken back: it won't be done again there",
                      [call[0][0] for call in self.log.call_args_list])

    def test_it_is_the_same_where_the_program_puts_back_what_was_taken_out_itself(self):
        page = Page(restores=True)
        engine = self.engine(page, keep_final=True)
        self.said(engine, "Hi Rick.", ", how are you?")
        self.assertEqual(self.said(engine, "scratch that"), "Hi Rick.")
        ops = [m["op"] for m in page.asked]
        self.assertNotIn("insert", ops[len(ops) - 1 - ops[::-1].index("command"):])   # nothing more typed

    def test_a_space_that_was_taken_out_is_not_typed_back(self):
        # As it always was: a comma closes up to the word before it, and scratching it
        # leaves the page as the program leaves it.
        page = Page("Well ")
        engine = self.engine(page)
        self.said(engine, ", how are you")
        before = len(page.asked)
        self.said(engine, "scratch that")
        self.assertEqual([m["op"] for m in page.asked[before:] if m["op"] != "context"], ["command"])

    def test_a_stop_that_was_said_stays(self):
        page = Page()
        engine = self.engine(page)
        self.assertEqual(self.said(engine, "Hi Rick full stop", ", how are you?"), "Hi Rick., how are you")

    def test_what_the_person_typed_or_changed_is_left_alone(self):
        page = Page("Hi Rick.")                            # typed by hand: not this program's
        engine = self.engine(page, keep_final=True)
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Rick., how are you?")
        page = Page()
        engine = self.engine(page, keep_final=True)
        self.said(engine, "Hi Rick.")
        page.text = "Hi Dick."                             # changed by hand since
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Dick., how are you?")

    def test_in_another_program_it_is_left_alone(self):
        page = Page()
        engine = self.engine(page, keep_final=True)
        self.said(engine, "Hi Rick.")
        other = Page("Hi Rick.")
        other.name = "Word"
        engine.targets = other
        self.assertEqual(self.said(engine, ", how are you?"), "Hi Rick., how are you?")

    def test_unticked_nothing_is_put_right(self):
        page = Page()
        engine = self.engine(page, keep_final=True, tidy=False)
        self.assertEqual(self.said(engine, "Hi Rick.", ", how are you?"), "Hi Rick., how are you?")

    def test_a_word_that_sounds_like_another_is_put_right_when_the_next_words_show_it(self):
        # Where the words decide where sentences end, the join is known by then.
        page = Page()
        engine = self.engine(page)
        engine.settings.sentence_ends = "words"
        self.assertEqual(self.said(engine, "Take the cat too", "the vet"), "Take the cat to the vet")
        self.assertEqual(page.inserts()[-1], ("to the vet", 3))
        self.assertEqual(self.said(engine, "scratch that"), "Take the cat too")

    def test_where_it_isnt_known_whether_a_sentence_ended_the_words_at_the_join_are_left(self):
        # "It works too" and then "let me know" reads, with the stop left off, as "take
        # the cat too" and then "the vet" does: either may be right.
        for first, second, typed in (("It works too.", "Let me know.", "It works too let me know"),
                                     ("Take the cat too", "the vet", "Take the cat too the vet"),
                                     ("Who told you?", "no, I did.", "Who told you no, I did")):
            page = Page()
            engine = self.engine(page)
            from dictation.words import Lexicon
            engine.lexicon = Lexicon.load_default()          # for "Let" to be known as a word
            self.assertEqual(self.said(engine, first, second), typed)
        # A word away from the join is put right all the same.
        page = Page()
        engine = self.engine(page)
        self.assertEqual(self.said(engine, "I want to buy a new car and", "sell the old one too the dealer"),
                         "I want to buy a new car and sell the old one to the dealer")

    def test_after_a_long_pause_a_word_at_the_join_has_to_be_plainly_wrong(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I want that too")
        engine._typed_at -= 30                              # half a minute later
        self.assertEqual(self.said(engine, "the vet said no"), "I want that too the vet said no")

    def test_the_persons_own_words_are_left_alone(self):
        page = Page()
        engine = self.engine(page)
        engine.settings.words = ("too",)
        self.assertEqual(self.said(engine, "Take the cat too", "the vet"), "Take the cat too the vet")

    def test_greeting_and_name(self):
        page = Page()
        engine = self.engine(page)
        self.assertEqual(self.said(engine, "High rick", ", how are you?"), "Hi Rick, how are you")
        self.assertEqual(self.said(engine, "scratch that"), "High rick")

    def test_the_run_of_its_own_text_grows_phrase_by_phrase_and_only_so_far(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "Take the cat", "to the vet", "and come back")
        self.assertEqual(engine._run, ("Writer", "Take the cat to the vet and come back"))
        for n in range(60):
            self.said(engine, "and then some more words follow")
        self.assertLessEqual(len(engine._run[1]), tidy.RUN_LENGTH)
        self.assertTrue(page.text.endswith(engine._run[1]))

    def test_a_check_that_swaps_a_word_reaches_back_into_the_phrase_before(self):
        # (The check that knows which words sound alike is given here by hand.)
        page = Page()
        engine = self.engine(page)
        import re
        swap = lambda found: (lambda whole, starts: [
            Change(m.start(), m.end(), "to") for m in re.finditer(r"\btoo(?= the vet)", whole)])
        real = tidy.chained
        with mock.patch.object(tidy, "chained", lambda *checks: real(swap, *checks)):
            self.assertEqual(self.said(engine, "Take the cat too", "the vet"), "Take the cat to the vet")
        self.assertEqual(page.inserts(), [("Take the cat too", 0), ("to the vet", 3)])
        self.assertEqual(self.said(engine, "scratch that"), "Take the cat too")


class HeardAgainInOnePiece(unittest.TestCase):
    """Two phrases of one sentence, heard once more with their sounds put together."""

    def setUp(self):
        patch = mock.patch("dictation.engine.log")
        self.log = patch.start()
        self.addCleanup(patch.stop)
        self.page = Page()
        # (The tidy-up as each phrase goes in is left out here: it would put right the
        # very words these tests leave for the second hearing.)
        self.engine = bare(self.page, tidy=False)
        engine = self.engine
        engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
        engine._unit = engine._just_typed = None
        self.heard, self.joined = "", []
        engine._ears = lambda: self
        self.at = 100.0

    def transcribe(self, sound, awake, prompt=""):            # stands in for the recogniser
        self.joined.append(len(sound))
        return self.heard

    def say(self, text, gap=2.0, took=0.1, seconds=1.0):
        """One phrase: typed, and then looked at for hearing again, as handle_audio does."""
        import numpy as np
        from dictation import config
        self.engine._just_typed = None
        self.engine.handle_text(text, True)
        self.at += gap + seconds
        self.engine._hear_again(np.zeros(int(seconds * config.RATE), dtype=np.float32), self.at,
                                took, True, "")
        return self.page.text

    def logged(self):
        return [call[0][0] for call in self.log.call_args_list if "heard again" in call[0][0]]

    def test_a_word_that_the_pause_cost_is_put_right(self):
        self.say("Take the cat too")
        self.assertEqual(self.joined, [])                      # one phrase: nothing to join
        self.heard = "Take the cat to the vet."
        self.assertEqual(self.say("the vet"), "Take the cat to the vet")
        self.assertEqual(self.joined, [32000])                 # the two sounds, as one
        # The two phrases were taken back and typed again, as two phrases still.
        self.assertEqual([m.get("name") or m["op"] for m in self.page.asked if m["op"] != "context"][-4:],
                         ["scratch", "scratch", "insert", "insert"])
        self.assertEqual(self.page.inserts()[-2:], [("Take the cat to", 0), (" the vet", 0)])
        self.assertIn("1 word put right", self.logged()[-1])
        self.assertEqual(self.engine._run, ("Writer", "Take the cat to the vet"))

    def test_the_persons_own_word_stays_when_heard_again(self):
        import numpy as np
        from dictation import config
        from dictation.words import Lexicon
        self.engine.settings.words = ("Jonti",)
        self.engine.lexicon = Lexicon.load_default()
        self.say("Anywho, good to see you again.")
        self.page.text = "Anywho, good to see you again. Cheers, Jonti"   # as the own word put it
        self.engine._just_typed = (0, " Cheers, Jonti", False)
        self.engine._run = ("Writer", self.page.text)
        self.heard = "Anywho, good to see you again. Cheers, John T."
        self.at += 1.0
        self.engine._hear_again(np.zeros(config.RATE, dtype=np.float32), self.at, 0.1, True, "Jonti. ")
        self.assertNotIn("John T", self.page.text)

    def test_scratch_that_still_takes_away_the_last_phrase_only(self):
        self.say("Take the cat too")
        self.heard = "Take the cat to the vet."
        self.say("the vet")
        self.engine.handle_text("scratch that", True)
        self.assertEqual(self.page.text, "Take the cat to")
        self.assertEqual(self.engine._run, ("Writer", "Take the cat to"))

    def test_heard_the_same_nothing_is_typed_again(self):
        self.say("Take the cat")
        self.heard = "Take the cat to the vet."
        before = len(self.page.asked)
        self.assertEqual(self.say("to the vet"), "Take the cat to the vet")
        self.assertEqual([m["op"] for m in self.page.asked[before:]], ["context", "insert", "context"])
        self.assertIn("the same", self.logged()[-1])

    def test_something_else_altogether_is_left_as_it_was(self):
        self.say("Take the cat too")
        self.heard = "Thank you for watching, see you next time."
        self.assertEqual(self.say("the vet"), "Take the cat too the vet")
        self.assertIn("left as it was", self.logged()[-1])

    def test_it_is_not_heard_again_when_it_should_not_be(self):
        for why, change in (
                ("the pause was long: another sentence", lambda: self.say("the vet", gap=9.0)),
                ("too slow a recogniser for it", lambda: self.say("the vet", took=2.0)),
                ("too much sound", lambda: self.say("the vet", seconds=20.0)),
                ("a phrase is being said", lambda: (setattr(self.engine, "_speaking", True), self.say("the vet"))),
                ("another phrase is waiting", lambda: (self.engine._phrases.put(("audio", None)), self.say("the vet"))),
                ("unticked", lambda: (self.engine.settings.states.update(hear_again=False), self.say("the vet"))),
                ("a box typed into key by key", lambda: (setattr(self.page, "typed", lambda: True), self.say("the vet")))):
            self.setUp()
            self.say("Take the cat too")
            self.heard = "Take the cat to the vet."
            change()
            self.assertEqual((why, self.joined, self.page.text), (why, [], "Take the cat too the vet"))

    def test_after_a_full_stop_that_was_said_the_sentence_is_over(self):
        self.say("Take the cat too full stop")
        self.heard = "Take the cat to. The vet."
        self.say("the vet")
        self.assertEqual(self.joined, [])

    def test_a_command_in_between_breaks_the_run(self):
        self.say("Take the cat too")
        self.say("new line")
        self.heard = "Take the cat to the vet."
        self.say("the vet")
        self.assertEqual(self.joined, [])

    def test_changed_by_hand_meanwhile_it_is_left(self):
        self.say("Take the cat too")
        self.heard = "Take the cat to the vet."
        self.engine._just_typed = None
        self.engine.handle_text("the vet", True)
        self.page.text = "Take the dog too the vet"            # the person has been at it
        import numpy as np
        self.engine._hear_again(np.zeros(16000, dtype=np.float32), 103.0, 0.1, True, "")
        self.assertEqual(self.page.text, "Take the dog too the vet")

    def test_if_the_second_taking_back_fails_the_phrase_is_put_back(self):
        self.say("Take the cat too")
        self.heard = "Take the cat to the vet."
        self.page.steps = self.page.steps[:0]                  # the program has lost its first step
        self.engine._just_typed = None
        self.engine.handle_text("the vet", True)
        import numpy as np
        self.engine._hear_again(np.zeros(16000, dtype=np.float32), 103.0, 0.1, True, "")
        self.assertEqual(self.page.text, "Take the cat too the vet")

    def test_the_mark_the_first_phrase_went_in_with_stays(self):
        # Where the words decided that a sentence ended before the first of the two phrases,
        # that stop went in with it: heard again, the two say nothing of it, and it stays.
        self.engine.settings.sentence_ends = "words"

        class Decides:
            def decide(self, before, phrase, held):
                return "." if "sun" in phrase else ""
        self.engine._decider = Decides()
        self.say("We have lovely weather here today.")
        self.say("The sun is shining, and")
        self.heard = "the sun is shining, and the birds are singing."
        self.assertEqual(self.say("the birds are singing."),
                         "We have lovely weather here today. The sun is shining, and the birds are singing")

    def test_each_join_is_heard_with_the_phrase_before_it_only(self):
        self.say("Take the cat too")
        self.heard = "Take the cat to the vet."
        self.say("the vet")
        self.heard = "The vet and come back."
        self.assertEqual(self.say("and come back"), "Take the cat to the vet and come back")
        self.assertEqual(self.joined, [32000, 32000])          # the last two each time, not all three


if __name__ == "__main__":
    unittest.main()
