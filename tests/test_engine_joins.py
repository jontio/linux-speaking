"""Where the words decide where sentences end (joins.py): the recogniser's mark held back at
the end of a phrase, the join decided when the next phrase comes, and the held mark typed
when nothing more is coming."""
import unittest
from unittest import mock

from dictation import joins, tidy
from dictation.settings import Settings

from tests.test_engine_telling import bare
from tests.test_engine_tidy import Page


class Decides:
    """Stands in for what decides: says `answer` (or the held mark, given None) and keeps
    what it was asked."""

    def __init__(self, answer=None):
        self.answer, self.asked = answer, []

    def decide(self, before, phrase, held):
        self.asked.append((before, phrase, held))
        if callable(self.answer):
            return self.answer(before, phrase, held)
        return held if self.answer is None else self.answer


class HeldBackAndDecided(unittest.TestCase):
    def setUp(self):
        from dictation import config
        for patch in (mock.patch("dictation.engine.log"), mock.patch.object(config, "SENTENCE_QUIET", 0),
                      mock.patch("dictation.engine.Engine._save")):
            started = patch.start()
            self.addCleanup(patch.stop)
            if isinstance(started, mock.MagicMock):
                self.log = started

    def engine(self, page, ends="words", answer=None, **states):
        engine = bare(page, tidy=False, hear_again=False, **states)
        engine.settings.sentence_ends = ends
        engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
        engine._decider = self.decider = Decides(answer)
        return engine

    def said(self, engine, *phrases):
        for phrase in phrases:
            engine.handle_text(phrase, True)
        return engine.targets.text

    def run_waiting(self, engine):
        """Do what was left for the worker to do."""
        while not engine._phrases.empty():
            kind, item = engine._phrases.get()
            if kind == "call":
                item()

    def test_the_recognisers_stop_is_held_back(self):
        page = Page()
        engine = self.engine(page)
        self.assertEqual(self.said(engine, "It should be an option."), "It should be an option")
        self.assertEqual(engine._held_mark, ("Writer", "It should be an option", ".", False))

    def test_mid_sentence_it_goes_on_in_small_letters(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.assertEqual(self.said(engine, "It should be an option.", "That the user can select."),
                         "It should be an option that the user can select")
        before, phrase, held = self.decider.asked[0]
        self.assertEqual((before, phrase, held), ("It should be an option", " that the user can select", "."))

    def test_a_sentence_end_goes_in_with_the_next_phrase_and_a_capital(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.assertEqual(self.said(engine, "It works.", "then we left."), "It works. Then we left")
        self.assertEqual(page.inserts()[-1], (". Then we left", 0))      # nothing taken out

    def test_a_question_mark_held_is_put_where_the_words_end_a_sentence(self):
        page = Page()
        engine = self.engine(page)                                      # keeps the held mark
        self.assertEqual(self.said(engine, "Can you come?", "We start at nine."),
                         "Can you come? We start at nine")

    def test_a_comma_goes_in_and_the_next_word_stays_small(self):
        page = Page()
        engine = self.engine(page, answer=",")
        self.assertEqual(self.said(engine, "When it rains.", "We stay in."), "When it rains, we stay in")

    def test_a_name_keeps_its_capital_where_the_sentence_goes_on(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.assertEqual(self.said(engine, "I sent it to.", "Rick yesterday."), "I sent it to Rick yesterday")

    def test_a_stop_that_was_said_is_not_decided(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.assertEqual(self.said(engine, "It works full stop", "then we left."), "It works. Then we left")
        self.assertEqual(self.decider.asked, [])
        self.assertEqual(engine._held_mark[2], ".")                     # the second phrase's own, held

    def test_a_phrase_that_ended_with_a_line_break_said_holds_no_stop(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "Hi Rick, comma new paragraph.", "I am writing to you.")
        self.assertNotIn("\u2029.", page.text)
        self.assertEqual(self.decider.asked, [])

    def test_a_sign_said_at_the_start_of_the_next_phrase_is_the_persons(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.assertEqual(self.said(engine, "When it rains.", "comma we stay in."), "When it rains, we stay in")
        self.assertEqual(self.decider.asked, [])

    def test_text_changed_by_hand_meanwhile_is_left_alone(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "It works.")
        page.text = "It works well"                              # typed on by hand
        self.assertEqual(self.said(engine, "then we left."), "It works well then we left")
        self.assertEqual(self.decider.asked, [])

    def test_in_another_program_nothing_carries_over(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "It works.")
        other = Page("It works")
        other.name = "Word"
        engine.targets = other
        self.assertEqual(self.said(engine, "then we left."), "It works then we left")

    def test_scratch_that_takes_the_join_back_with_the_phrase_and_it_is_decided_again(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "It works.", "then we left.")
        self.assertEqual(self.said(engine, "scratch that"), "It works")
        self.assertEqual(engine._held_mark, ("Writer", "It works", ".", False))
        self.decider.answer = ""
        self.assertEqual(self.said(engine, "and then we left."), "It works and then we left")

    def test_what_decides_failing_keeps_the_recognisers_mark(self):
        page = Page()
        engine = self.engine(page)

        class Broken:
            def decide(self, before, phrase, held):
                raise RuntimeError("no model")
        engine._decider = Broken()
        self.assertEqual(self.said(engine, "It works.", "then we left."), "It works. Then we left")

    def test_the_other_choices_are_as_they_were(self):
        page = Page()
        engine = self.engine(page, ends="pause", answer="")
        self.assertEqual(self.said(engine, "It works.", "Then we left."), "It works. Then we left.")
        page = Page()
        engine = self.engine(page, ends="said", answer=".")
        self.assertEqual(self.said(engine, "It works.", "Then we left."), "It works then we left")
        self.assertEqual(self.decider.asked, [])


class TheHeldMarkWhenNothingMoreIsComing(HeldBackAndDecided):
    def test_new_paragraph_types_it_first(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow.", "new paragraph")
        self.assertTrue(page.text.startswith("I will send the report tomorrow."), page.text)
        self.assertIsNone(engine._held_mark)

    def test_a_short_line_gets_none(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "Dear Sam.", "new line")
        self.assertFalse(page.text.startswith("Dear Sam."), page.text)

    def test_going_to_sleep_types_it(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow.")
        engine.sleep()
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")
        engine.sleep()                                           # and not twice
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")

    def test_with_no_mark_from_the_recogniser_a_full_stop_ends_a_sentence(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow")
        engine.sleep()
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")

    def test_not_where_the_cursor_has_moved(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow.")
        page.text += " and more by hand"
        engine.sleep()
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow and more by hand")

    def test_a_question_held_stays_a_question(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "Can you send me the report?")
        engine.turn_off()
        self.run_waiting(engine)
        self.assertEqual(page.text, "Can you send me the report?")


class ForTheTimeBeing(HeldBackAndDecided):
    """A mark typed after a quiet spell, or as dictation slept, is decided again if the
    sentence goes on."""

    def asleep_and_back(self, engine):
        engine.sleep()
        self.run_waiting(engine)
        engine.status.state = engine.status.state.__class__.AWAKE

    def test_the_sentence_goes_on_and_the_stop_goes(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.said(engine, "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")
        self.assertEqual(self.said(engine, "and the invoice."), "I will send the report tomorrow and the invoice")
        # The stop taken out with the phrase, in the one step the phrase is for Undo.
        self.assertEqual(page.inserts()[-1], (" and the invoice", 1))

    def test_the_sentence_had_ended_and_the_stop_stays(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.assertEqual(self.said(engine, "thanks for your help."),
                         "I will send the report tomorrow. Thanks for your help")

    def test_scratch_that_takes_away_the_phrase_not_only_the_stop(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "It works.", "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.assertEqual(page.text, "It works. I will send the report tomorrow.")
        self.assertEqual(self.said(engine, "scratch that"), "It works")
        self.assertEqual(engine._held_mark, ("Writer", "It works", ".", False))

    def test_after_a_quiet_spell_it_is_typed_for_the_time_being(self):
        from dictation import config
        import time
        page = Page()
        engine = self.engine(page)
        engine.status.state = engine.status.state.__class__.AWAKE
        with mock.patch.object(config, "SENTENCE_QUIET", 0.05):
            self.said(engine, "I will send the report tomorrow.")
            time.sleep(0.3)
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")
        self.assertTrue(engine._held_mark[3])

    def test_not_while_something_is_being_said(self):
        from dictation import config
        import time
        page = Page()
        engine = self.engine(page)
        with mock.patch.object(config, "SENTENCE_QUIET", 0.05):
            self.said(engine, "I will send the report tomorrow.")
            engine._speaking = True
            time.sleep(0.3)
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow")

    def test_a_new_paragraph_makes_it_for_good(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.said(engine, "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.said(engine, "new paragraph")
        self.assertIsNone(engine._held_mark)


class AsReviewed(HeldBackAndDecided):
    """What a review of the held marks found, each put right."""

    def asleep_and_back(self, engine):
        engine.sleep()
        self.run_waiting(engine)
        engine.status.state = engine.status.state.__class__.AWAKE

    def test_a_recording_window_brings_dictation_back_as_it_was(self):
        from dictation.status import State
        page = Page()
        engine = self.engine(page, answer="")
        engine._held = ""
        self.said(engine, "I will send the report tomorrow.")
        calls = []
        engine.turn_off = lambda remember=True: setattr(engine.status, "state", State.OFF)
        engine.turn_on = lambda awake=False, quietly=False: calls.append(awake) or True
        engine.hold()                                    # awake: listening stops for it
        self.said(engine, "and the invoice.")            # a phrase that was still being heard
        engine.unhold()
        self.assertEqual(calls, [True])                  # back on, and awake
        self.assertEqual(engine._held_mark[1], " and the invoice")   # what was held is still held

    def test_a_recording_window_never_switches_dictation_on(self):
        page = Page()
        engine = self.engine(page)
        engine._held = ""
        self.said(engine, "I will send the report tomorrow.")
        engine._finish_later("off")
        self.run_waiting(engine)                         # the mark typed for the time being
        engine.status.state = engine.status.state.__class__.OFF
        calls = []
        engine.turn_on = lambda awake=False, quietly=False: calls.append(awake) or True
        engine.hold()
        engine.unhold()
        self.assertEqual(calls, [])

    def test_a_sign_said_at_the_end_gets_no_second_mark(self):
        for said, then, typed in (
                ("When it rains comma.", "we stay in.", "When it rains, we stay in"),
                ("The options are colon.", "red and blue.", "The options are: red and blue"),
                ('He said, "Go away."', "then he left.", 'He said, "Go away." Then he left'),
                ("Is it 'ready?'", "we need to know.", "Is it 'ready?' We need to know")):
            page = Page()
            engine = self.engine(page, answer=".")
            self.assertEqual(self.said(engine, said, then), typed, said)
            self.assertIsNone(engine._held_mark if engine._held_mark and engine._held_mark[1] == said else None)

    def test_and_none_when_the_line_is_finished(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "When it rains really hard comma.", "new line")
        self.assertNotIn(",.", page.text)
        page = Page()
        engine = self.engine(page)
        self.said(engine, "When it rains really hard comma.")
        engine.sleep()
        self.run_waiting(engine)
        self.assertEqual(page.text, "When it rains really hard,")

    def test_switched_off_while_the_last_phrase_is_heard_it_still_gets_its_stop(self):
        page = Page()
        engine = self.engine(page)
        engine.turn_off()                                # clicked while the phrase is being heard
        self.said(engine, "I will send the report tomorrow.")   # which is typed after that
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")

    def test_a_short_line_keeps_its_mark_held_through_a_quiet_spell(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "Can you come?")
        engine._finish_later("after a quiet spell")
        self.run_waiting(engine)
        self.assertEqual(page.text, "Can you come")      # too short to tell: not typed
        self.assertEqual(self.said(engine, "we start at nine."), "Can you come? We start at nine")

    def test_and_while_another_program_is_in_front(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "I will send the report tomorrow.")
        other = Page("Somewhere else")
        other.name = "Word"
        engine.targets = other
        engine._finish_later("after a quiet spell")
        self.run_waiting(engine)
        engine.targets = page
        self.assertEqual(self.said(engine, "then we can talk."),
                         "I will send the report tomorrow. Then we can talk")

    def test_a_quiet_spell_waits_for_a_newer_phrase_to_have_its_own(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.said(engine, "I will send the report tomorrow.")
        old = engine._held_mark
        self.said(engine, "and the invoice as well.")    # came before the quiet timer's call ran
        engine._finish_later("after a quiet spell", only=old)
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow and the invoice as well")

    def test_a_spelled_word_goes_on_where_the_phrase_ended(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I sent the parcel to.")
        self.asleep_and_back(engine)
        self.assertEqual(page.text, "I sent the parcel to.")
        engine._dictate("Smith", exact=True)
        self.assertEqual(page.text, "I sent the parcel to Smith")
        # The stop it had went with the spelled word: the sentence waits for its new end,
        # and gets it when dictation stops, rather than never getting it at all.
        self.assertIsNotNone(engine._held_mark)
        engine._finish_sentence("dictation turned off", for_now=True)
        self.assertEqual(page.text, "I sent the parcel to Smith.")

    def test_a_spelled_word_after_a_stop_still_held_keeps_it_held(self):
        # The phrase before ended and its stop is only held back (no quiet spell yet): a
        # word spelled on from it must not lose that, either.
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I sent the parcel to the vet.")
        self.assertIsNotNone(engine._held_mark)
        engine._dictate("Smith", exact=True)
        self.assertEqual(page.text, "I sent the parcel to the vet Smith")
        self.assertIsNotNone(engine._held_mark)
        engine._finish_sentence("dictation turned off", for_now=True)
        self.assertEqual(page.text, "I sent the parcel to the vet Smith.")

    def test_a_break_that_cannot_be_typed_keeps_the_held_stop(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I sent the parcel to the vet.")
        held = engine._held_mark
        self.assertIsNotNone(held)
        real = page.request
        page.request = lambda message: ({"ok": False, "why": "busy"}
                                        if message.get("op") == "insert" else real(message))
        engine.handle_text("new paragraph", True)
        self.assertEqual(page.text, "I sent the parcel to the vet")   # nothing was typed
        self.assertEqual(engine._held_mark, held)                     # and nothing was lost

    def test_no_quiet_spell_stop_while_spelling(self):
        from dictation import config
        import time
        page = Page()
        engine = self.engine(page)
        with mock.patch.object(config, "SENTENCE_QUIET", 0.05):
            self.said(engine, "I sent the parcel to.")
            engine.status.spelling = True
            time.sleep(0.3)
            self.run_waiting(engine)
            self.assertEqual(page.text, "I sent the parcel to")
            engine.status.spelling = False                   # cancelled: then it comes
            time.sleep(0.3)
        self.run_waiting(engine)
        self.assertEqual(page.text, "I sent the parcel to.")

    def test_undo_that_after_a_stop_for_the_time_being_takes_away_the_phrase(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "It works well for me.", "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.assertEqual(page.text, "It works well for me. I will send the report tomorrow.")
        self.assertEqual(self.said(engine, "undo that"), "It works well for me")
        self.decider.answer = ""
        self.assertEqual(self.said(engine, "and more."), "It works well for me and more")

    def test_scratch_that_twice_after_a_stop_for_the_time_being(self):
        page = Page()
        engine = self.engine(page, answer="")
        self.said(engine, "It works well for me.", "I will send the report tomorrow.")
        self.asleep_and_back(engine)
        self.said(engine, "and the invoice.")            # takes the stop out with it
        self.assertEqual(self.said(engine, "scratch that"),            # as it was before the phrase
                         "It works well for me I will send the report tomorrow.")
        # A program whose record keeps what a later phrase took out (as this page does) needs
        # one "scratch that" more to reach the phrase before; nothing else is ever taken.
        for _ in range(2):
            self.said(engine, "scratch that")
            self.assertTrue(page.text.startswith("It works well for me"), page.text)
        self.assertEqual(page.text, "It works well for me")

    def test_after_scratch_that_the_quiet_spell_stop_comes_again(self):
        from dictation import config
        import time
        page = Page()
        engine = self.engine(page, answer="")
        with mock.patch.object(config, "SENTENCE_QUIET", 0.05):
            self.said(engine, "It works well for me.", "I will send the report tomorrow.")
            self.said(engine, "scratch that")
            time.sleep(0.3)
        self.run_waiting(engine)
        self.assertEqual(page.text, "It works well for me.")

    def test_a_new_paragraph_said_at_the_start_ends_the_sentence_before_it(self):
        from dictation.formatting import PARAGRAPH
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow.", "New paragraph, thanks for your help.")
        self.assertTrue(page.text.startswith("I will send the report tomorrow." + PARAGRAPH), repr(page.text))

    def test_and_said_at_the_end(self):
        from dictation.formatting import PARAGRAPH
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow new paragraph.")
        self.assertEqual(page.text, "I will send the report tomorrow." + PARAGRAPH)
        page = Page()
        engine = self.engine(page)
        self.said(engine, "Dear Sam new paragraph.")
        self.assertEqual(page.text, "Dear Sam" + PARAGRAPH)

    def test_not_with_text_after_the_cursor(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "I will send the report.")
        request = page.request

        def with_text_after(message):
            reply = request(message)
            if message["op"] == "context":
                reply["after"] = " and the invoice."
            return reply
        page.request = with_text_after
        self.said(engine, "tomorrow.")
        self.assertEqual(self.decider.asked, [])
        self.assertNotIn(". Tomorrow", page.text)

    def test_a_word_at_a_join_nothing_decided_is_left_as_it_is(self):
        page = Page()
        engine = self.engine(page, answer="")
        engine.settings.states["tidy"] = True
        request = page.request

        def with_text_after(message):
            reply = request(message)
            if message["op"] == "context":
                reply["after"] = " and so on."
            return reply
        page.request = with_text_after
        self.said(engine, "It works too.", "let me know.")
        self.assertIn("works too", page.text)

    def test_a_select_said_as_a_sentence_keeps_the_held_mark(self):
        page = Page()
        engine = self.engine(page, answer=".")
        request = page.request

        def cant_find(message):
            if message["op"] == "command" and message["name"] == "select":
                return {"ok": False, "why": "can't find that"}
            return request(message)
        page.request = cant_find
        self.said(engine, "I will send the report tomorrow.", "Select the colour you like.")
        self.assertEqual(page.text, "I will send the report tomorrow. Select the colour you like")

    def test_when_the_model_cant_be_had_it_is_not_fetched_for_every_phrase(self):
        from dictation import punctuation
        page = Page()
        engine = self.engine(page)
        engine._decider, engine._deciding = None, False
        fetched = []

        class AtOnce:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()
        with mock.patch.object(punctuation, "installed", return_value=False), \
                mock.patch.object(punctuation, "fetch", side_effect=lambda folder: fetched.append(1) or 1 / 0), \
                mock.patch("dictation.engine.threading.Thread", AtOnce):
            self.said(engine, "It works.", "then we left.", "and came back.", "and left again.")
        self.assertEqual(len(fetched), 1)
        self.assertEqual(len([n for n in engine.notices if "being downloaded" in n[1]]), 1)


class EachProgramsRecord(HeldBackAndDecided):
    """A stop typed by itself after a quiet spell is the newest thing in each program's
    record of what was typed (see tests/programs.py): every command about "the last phrase"
    must take it back first, or act on it alone. As the second review found them."""

    def quiet(self, engine):
        engine._finish_later("after a quiet spell", only=engine._held_mark)
        self.run_waiting(engine)

    def test_correct_that_after_a_quiet_spell_selects_the_phrase(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page)
            self.said(engine, "I will send the report tomorrow.")
            self.quiet(engine)
            self.assertEqual(page.text, "I will send the report tomorrow.", Program.name)
            self.said(engine, "correct that", "I will send the invoice tomorrow.")
            self.assertEqual(page.text, "I will send the invoice tomorrow", Program.name)

    def test_bold_that_after_a_quiet_spell_formats_the_phrase_and_the_stop_comes_back(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page)
            self.said(engine, "I will send the report tomorrow.")
            self.quiet(engine)
            self.said(engine, "bold that")
            self.assertEqual(page.formatted, [("bold", "I will send the report tomorrow")], Program.name)
            self.quiet(engine)
            self.assertEqual(page.text, "I will send the report tomorrow.", Program.name)

    def test_undo_that_after_a_stop_taken_back_first_loses_no_other_phrase(self):
        from tests.programs import PROGRAMS
        rule = lambda before, phrase, held: "" if phrase.strip().startswith("and") else "."
        for Program in PROGRAMS:
            page = Program("Hello there.")
            engine = self.engine(page, answer=rule)
            self.said(engine, "We met yesterday.", "It works well for me.")
            self.quiet(engine)
            self.said(engine, "and the invoice.", "undo that")
            # As it was before the phrase: the stop typed for the time being is back.
            self.assertEqual(page.text, "Hello there. We met yesterday. It works well for me.", Program.name)
            self.said(engine, "and more.")
            self.assertEqual(page.text, "Hello there. We met yesterday. It works well for me and more",
                             Program.name)
            self.said(engine, "scratch that")
            self.assertEqual(page.text, "Hello there. We met yesterday. It works well for me.", Program.name)

    def test_undo_that_twice_after_a_quiet_spell_takes_the_phrases_back_and_no_more(self):
        from tests.programs import PROGRAMS
        rule = lambda before, phrase, held: "" if phrase.strip().startswith("and") else "."
        for Program in PROGRAMS:
            for third in ("and the invoice.", "Then we left."):
                page = Program("Hello there.")
                engine = self.engine(page, answer=rule)
                self.said(engine, "We met yesterday.", "It works well for me.")
                self.quiet(engine)
                self.said(engine, third, "undo that", "undo that")
                self.assertEqual(page.text, "Hello there. We met yesterday", (Program.name, third))
                # Writer's link answers "scratch that" after "undo that" with what Undo emptied,
                # and takes nothing (it was so before): more of them reach the phrase. Nothing
                # else is ever taken, and the engine keeps in step.
                for _ in range(4 if Program.name == "Writer" else 1):
                    if page.text == "Hello there.":
                        break
                    self.said(engine, "scratch that")
                    self.assertTrue(page.text.startswith("Hello there."), (Program.name, third, page.text))
                self.assertEqual(page.text, "Hello there.", (Program.name, third))
                self.said(engine, "Then we left.")
                self.assertEqual(page.text, "Hello there. Then we left", (Program.name, third))

    def test_press_enter_scratched_takes_the_key_then_the_stop_then_the_phrase(self):
        from tests.programs import Word, VSCode
        for Program in (Word, VSCode):
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "It works well for me.", "I will send the report tomorrow.", "press enter")
            self.assertEqual(page.text, "It works well for me. I will send the report tomorrow.\u2029"
                             if Program is Word else page.text, Program.name)
            steps = []
            for _ in range(3):
                self.said(engine, "scratch that")
                steps.append(page.text)
            self.assertEqual(steps[-1], "It works well for me", (Program.name, steps))
            self.assertIn("It works well for me. I will send the report tomorrow", steps[0], Program.name)

    def test_delete_that_takes_back_as_scratch_that_does(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "It works well for me.", "I will send the report tomorrow.", "delete that")
            self.assertEqual(page.text, "It works well for me", Program.name)
            self.said(engine, "Then we left.")
            self.assertEqual(page.text, "It works well for me. Then we left", Program.name)

    def test_delete_that_puts_back_what_the_phrase_took_out(self):
        from tests.programs import Word
        page = Word()
        engine = self.engine(page, ends="said")
        engine.settings.states["tidy"] = True
        self.said(engine, "Hi Rick.", ", how are you?")
        self.said(engine, "delete that")
        self.assertEqual(page.text, "Hi Rick")       # as before the phrase (the said-mode stop was never typed)
        page = Word()
        engine = self.engine(page, ends="pause")
        engine.settings.states["tidy"] = True
        self.said(engine, "Hi Rick.", ", how are you?")
        self.said(engine, "delete that")
        self.assertEqual(page.text, "Hi Rick.")      # the stop the phrase took out is back

    def test_that_was_a_noise_after_a_quiet_spell_takes_the_noise(self):
        import numpy as np
        from tests.programs import PROGRAMS
        rule = lambda before, phrase, held: "." if phrase.strip().lower().startswith(("thank", "then")) else ""
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=rule, noise=True)
            self.said(engine, "I will send the report tomorrow.")
            engine._heard_sound = (np.zeros(3200, dtype=np.float32), "Thank you.", "model", None)
            self.said(engine, "Thank you.")          # a cough, heard as words
            self.quiet(engine)
            with mock.patch("dictation.engine.speech.keep_noise"):
                self.said(engine, "that was a noise")
            self.assertEqual(page.text, "I will send the report tomorrow", Program.name)
            self.said(engine, "Then we left.")
            self.assertEqual(page.text, "I will send the report tomorrow. Then we left", Program.name)

    def test_new_paragraph_and_its_stop_go_in_together_and_go_together(self):
        from dictation.formatting import PARAGRAPH
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            for quiet_first in (False, True):
                page = Program()
                engine = self.engine(page, answer=".")
                self.said(engine, "It works well for me.", "I will send the report tomorrow.")
                if quiet_first:
                    self.quiet(engine)
                self.said(engine, "new paragraph")
                self.assertEqual(page.text, "It works well for me. I will send the report tomorrow." + PARAGRAPH,
                                 (Program.name, quiet_first))
                self.said(engine, "scratch that")
                self.assertEqual(page.text, "It works well for me. I will send the report tomorrow",
                                 (Program.name, quiet_first))
                self.assertEqual(engine._held_mark[2], ".")
                self.said(engine, "scratch that")
                self.assertEqual(page.text, "It works well for me", (Program.name, quiet_first))

    def test_cap_that_or_unselecting_after_a_quiet_spell_keeps_the_stop_coming(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            for commands in (("cap that",), ("select that", "unselect that")):
                page = Program()
                engine = self.engine(page)
                self.said(engine, "I will send the report tomorrow.")
                self.quiet(engine)
                self.said(engine, *commands)
                self.quiet(engine)
                self.assertTrue(page.text.endswith("."), (Program.name, commands, page.text))

    def test_a_plain_break_after_the_stop_and_break_is_a_step_of_its_own(self):
        from dictation.formatting import PARAGRAPH
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "It works well for me.", "I will send the report tomorrow.", "new paragraph",
                      "new line", "scratch that")
            self.assertEqual(page.text, "It works well for me. I will send the report tomorrow." + PARAGRAPH,
                             Program.name)
            self.said(engine, "scratch that", "Then we left.")
            self.assertEqual(page.text, "It works well for me. I will send the report tomorrow. Then we left",
                             Program.name)

    def test_no_stop_put_in_front_of_a_closing_quote_an_apostrophe_or_a_dash(self):
        for phrase in ("close quote and then we left.", "'cause it rained.", "- and more besides."):
            page = Page()
            engine = self.engine(page, answer=".")
            self.said(engine, "We went shopping in town today.", phrase)
            for bad in (". ”", ". '", ". -", ". \""):
                self.assertNotIn(bad, page.text, (phrase, page.text))

    def test_correct_that_keeps_the_mark_at_the_join_and_holds_one_for_the_new_words(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "It works well for me.", "Then we left.", "correct that", "Then we went home.")
            self.assertEqual(page.text, "It works well for me. Then we went home", Program.name)
            self.quiet(engine)
            self.assertEqual(page.text, "It works well for me. Then we went home.", Program.name)

    def test_a_held_stop_typed_for_the_time_being_is_decided_as_the_recogniser_wrote_it(self):
        page = Page()
        engine = self.engine(page)
        self.said(engine, "I sent the parcel to my brother")          # no mark from the recogniser
        self.quiet(engine)                                            # a stop typed for the time being
        self.decider.asked.clear()
        self.said(engine, "and his wife yesterday.")
        self.assertEqual(self.decider.asked[-1][2], "")               # decided as no mark held

    def test_the_held_stop_is_not_dropped_while_something_is_selected_or_another_program_is_in_front(self):
        from tests.programs import Word
        page = Word()
        engine = self.engine(page)
        self.said(engine, "I will send the report tomorrow.")
        self.quiet(engine)
        self.said(engine, "select that", "bold that", "unselect that")
        self.quiet(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")

    def test_a_straight_opening_quote_starts_a_sentence(self):
        page = Page()
        engine = self.engine(page, answer=".")
        self.said(engine, "We went shopping in town today.", '"Thanks for your help," she said.')
        self.assertIn('today. "', page.text)

    def test_a_word_corrected_at_the_end_keeps_the_full_stop_coming(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "I'm planning on taking the cat to the Vat.", "correct vat", "vet")
            self.assertEqual(page.text, "I'm planning on taking the cat to the vet", Program.name)
            self.said(engine, "I'm hoping that this works correctly.")
            self.assertEqual(page.text, "I'm planning on taking the cat to the vet. I'm hoping that this "
                                        "works correctly", Program.name)

    def test_correct_finds_the_persons_own_word_heard_as_another(self):
        from tests.programs import Word
        from dictation.words import Lexicon
        page = Word()
        engine = self.engine(page, ends="said")
        engine.settings.words = ("Jonti",)
        engine.lexicon = Lexicon.load_default()
        self.said(engine, "Anywho, good to see you again.")
        engine.handle_text("Cheers, Jonti.", True)       # (as the own word put it in)
        # Heard again as before, with the pause after "Correct" written as a comma.
        self.said(engine, "Correct, John T.")
        self.assertEqual(page.context().get("selected"), "Jonti")
        self.assertNotIn("Correct", page.text)

    def test_hi_rick_then_comma_new_paragraph_said_after_a_pause(self):
        from dictation.formatting import PARAGRAPH
        from dictation.words import Lexicon
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            for ends in ("words", "said", "pause"):
                page = Program()
                engine = self.engine(page, ends=ends, answer=",")
                engine.lexicon = Lexicon.load_default()
                self.said(engine, "Hi Rick.")
                engine._heard_join = (",", False)              # as hearing the join gave it
                self.said(engine, "Common new paragraph.")
                self.assertEqual(page.text, "Hi Rick," + PARAGRAPH, (Program.name, ends))

    def test_hi_rick_comma_new_paragraph_however_the_recogniser_wrote_it(self):
        # "hi rick comma new paragraph", in one breath or with pauses, as a recogniser may
        # write it: a comma after "Hi" (taken out by "No comma after Hello or Hi", which is
        # on unless unticked), a stop after the name, "comma" heard as "common" or "coma".
        # Each item: the phrases, and the mark heard at the join before the second, if any.
        from dictation.formatting import PARAGRAPH
        from dictation.words import Lexicon
        from tests.programs import PROGRAMS
        heard = [
            (["Hi, Rick, common new paragraph."], None),           # as reported
            (["Hi Rick, common new paragraph."], None),
            (["Hi, Rick. Common new paragraph."], None),
            (["Hi Rick common new paragraph."], None),
            (["Hi, Rick, common, new paragraph."], None),
            (["Hi, rick, common new paragraph."], None),
            (["Hi Rick, coma, new paragraph."], None),
            (["Hi, Rick.", "Common new paragraph."], (",", False)),
            (["Hi, Rick.", "Common new paragraph."], (".", True)),
            (["Hi Rick.", "Common new paragraph."], None),
            (["Hi, Rick,", "common new paragraph."], None),
            (["Hi, Rick, common.", "New paragraph."], (".", True)),
        ]
        for phrases, join in heard:
            for no_greeting_comma in (True, False):
                comma_after_hi = phrases[0].startswith("Hi,") and not no_greeting_comma
                want = ("Hi, Rick," if comma_after_hi else "Hi Rick,") + PARAGRAPH
                for Program in PROGRAMS:
                    for ends in ("words", "said", "pause"):
                        page = Program()
                        engine = self.engine(page, ends=ends, answer=",",
                                             no_greeting_comma=no_greeting_comma)
                        engine.lexicon = Lexicon.load_default()
                        for n, phrase in enumerate(phrases):
                            if n and join:
                                engine._heard_join = join          # as hearing the join gave it
                            self.said(engine, phrase)
                        self.assertEqual(page.text, want, (phrases, join, no_greeting_comma,
                                                           Program.name, ends))

    def test_cheers_comma_enter_and_the_persons_own_name_heard_as_another(self):
        # Said as reported: "cheers comma enter jonti", by a recogniser that can't be given
        # the words as a hint, which wrote the name as an everyday word, or made one up.
        import numpy as np
        from dictation.formatting import LINE
        from dictation.words import Lexicon
        from tests.programs import PROGRAMS
        for heard in ("Cheers, comma, enter, jaunty.", "Cheers, comma, enter. Jaunty.",
                      "Cheers, comma, enter, Junty."):
            for Program in PROGRAMS:
                for ends in ("words", "said", "pause"):
                    page = Program("Hi Peter," + LINE + "Good to see you again." + LINE)
                    engine = self.engine(page, ends=ends)
                    engine.settings.states["tidy"] = True    # what lays the sign-off out
                    engine.settings.words = ("Jonti",)
                    engine.lexicon = Lexicon.load_default()
                    engine._offload = mock.Mock()
                    engine._offload.transcribe.return_value = heard
                    engine._offload.measured = None
                    engine._only_breath = lambda audio: False
                    engine.handle_audio(np.ones(16000, dtype=np.float32) * 0.1)
                    self.assertTrue(page.text.endswith(LINE + "Cheers," + LINE + "Jonti"),
                                    (heard, Program.name, ends, page.text))

    def test_correct_with_a_pause_after_it_is_a_sentence_unless_the_words_were_just_typed(self):
        from tests.programs import Word
        page = Word()
        engine = self.engine(page, ends="said")
        self.said(engine, "Is the meeting at three?")
        self.said(engine, "Correct, yes.")                        # "yes" wasn't typed: a sentence
        self.assertIn("Correct, yes", page.text)

    def test_a_short_correction_not_found_is_not_typed(self):
        from tests.programs import Word
        page = Word("Anywho, good to see you again. Cheers,")
        engine = self.engine(page, ends="said")
        self.said(engine, "Correct Fred Bloggs.")
        self.assertEqual(page.text, "Anywho, good to see you again. Cheers,")
        self.assertTrue(any("isn\u2019t there" in text or "isn't there" in text for _, text in engine.notices))
        self.said(engine, "Select the best option.")                  # a sentence: typed
        self.assertIn("Select the best option", page.text)

    def test_redo_that_brings_back_the_held_mark(self):
        from tests.programs import PROGRAMS
        for Program in PROGRAMS:
            page = Program()
            engine = self.engine(page, answer=".")
            self.said(engine, "It works well for me.", "I will send the report tomorrow.", "undo that",
                      "redo that", "Then we left.")
            self.assertEqual(page.text, "It works well for me. I will send the report tomorrow. Then we left",
                             Program.name)

    def test_a_sentence_starting_with_a_quote_a_bracket_or_money_is_decided(self):
        for phrase, wanted in (("$20 was spent on food.", "today. $20 was spent"),
                               ("Open quote thanks for your help close quote, she said.", "today. “Thanks"),
                               ("Open bracket see page five close bracket.", "today. (See")):
            page = Page()
            engine = self.engine(page, answer=".")
            self.said(engine, "We went shopping in town today.", phrase)
            self.assertIn(wanted, page.text, phrase)

    def test_a_quiet_spell_while_a_phrase_is_heard_waits(self):
        from dictation import config
        from dictation.status import State
        import time
        page = Page()
        engine = self.engine(page)
        with mock.patch.object(config, "SENTENCE_QUIET", 0.05):
            self.said(engine, "I will send the report tomorrow.")
            engine.status.state = State.THINKING      # a cough being heard
            time.sleep(0.2)
            engine.status.state = State.AWAKE         # it came to nothing
            time.sleep(0.3)
        self.run_waiting(engine)
        self.assertEqual(page.text, "I will send the report tomorrow.")

    def test_the_phrase_after_a_quiet_spell_is_tidied_with_the_one_before(self):
        from dictation.words import Lexicon
        page = Page()
        engine = self.engine(page, answer="")
        engine.settings.states["tidy"] = True
        engine.lexicon = Lexicon.load_default()
        self.said(engine, "Take the cat too.")
        self.quiet(engine)
        self.said(engine, "the vet.")
        self.assertEqual(page.text, "Take the cat to the vet")


class SavedChoice(unittest.TestCase):
    def test_the_engine_passes_the_choice_on_and_forgets_what_was_held(self):
        engine = bare(Page())
        engine.settings = Settings()
        engine._held_mark = ("Writer", "x", ".")
        with mock.patch("dictation.engine.log"):
            engine.set_sentence_ends("words")
        self.assertEqual((engine.settings.sentence_ends, engine._held_mark), ("words", None))


class Pieces(unittest.TestCase):
    def test_held_mark(self):
        self.assertEqual(joins.held_mark("It works."), ".")
        self.assertEqual(joins.held_mark("Can you?"), "?")
        self.assertEqual(joins.held_mark('He said "go!"'), "!")
        self.assertEqual(joins.held_mark("It works"), "")
        self.assertEqual(joins.held_mark("It works,"), "")

    def test_joined(self):
        cap = str.capitalize
        self.assertEqual(joins.joined("It works", " then we left", ".", cap), (". Then we left", 0))
        self.assertEqual(joins.joined("It works ", "then we left", ".", cap), (". Then we left", 1))
        self.assertEqual(joins.joined("It works", " then we left", ",", cap), (", then we left", 0))
        self.assertEqual(joins.joined("It works", " then we left", "", cap), (" then we left", 0))
        self.assertEqual(joins.joined("It works", ' "then" we left', "?", cap), ('? "Then" we left', 0))

    def test_ends_marked(self):
        for text in ("When it rains,", "It works.", 'He said, "Go away."', "Is it 'ready?'",
                     "He said “", "See (", "The options are: ", "Wait…"):
            self.assertTrue(joins.ends_marked(text), text)
        for text in ("It works", 'He said "go away"', "(see page five)", ""):
            self.assertFalse(joins.ends_marked(text), text)

    def test_looks_like_a_sentence(self):
        self.assertTrue(joins.looks_like_a_sentence("I will send it tomorrow"))
        self.assertFalse(joins.looks_like_a_sentence("Dear Sam"))
        self.assertFalse(joins.looks_like_a_sentence("Best regards"))


if __name__ == "__main__":
    unittest.main()
