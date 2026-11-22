"""Each phrase heard with the end of the one before in front of it (config.LEFT_CONTEXT): the
hearing cut at the join by the model's own times, what it wrote there, the engine's choice of
what to put in front, the join decided by it, and the same over the link to another computer."""
import time
import unittest
from unittest import mock

import numpy as np

from dictation import config, engine as engine_module, tidy
from dictation.engine import Transcriber, mark_at_join, split_at_lead

from tests.test_engine_telling import bare
from tests.test_engine_tidy import Page


class CutAtTheJoin(unittest.TestCase):
    def test_the_new_phrase_is_what_comes_after_the_join(self):
        tokens = [" Hi", " R", "ick", ".", " I", " am", " here", "."]
        times = [0.1, 0.4, 0.5, 0.7, 1.3, 1.5, 1.7, 1.9]
        before, after = split_at_lead(tokens, times, 1.2)
        self.assertEqual(before, [" Hi", " R", "ick", "."])
        self.assertEqual(after, [" I", " am", " here", "."])
        self.assertEqual(mark_at_join(before, after), (".", True))

    def test_a_word_begun_before_the_join_is_the_phrase_befores(self):
        tokens = [" see", " you", " to", "mor", "row", " then"]
        times = [0.2, 0.5, 0.95, 1.1, 1.18, 1.6]
        before, after = split_at_lead(tokens, times, 1.2)
        self.assertEqual("".join(after), " then")

    def test_a_mark_at_the_join_is_the_joins(self):
        tokens = [" well", ",", " thanks", " anyway"]
        times = [1.0, 1.25, 1.4, 1.7]
        before, after = split_at_lead(tokens, times, 1.2)
        self.assertEqual((before, after), ([" well", ","], [" thanks", " anyway"]))
        self.assertEqual(mark_at_join(before, after), (",", False))

    def test_no_mark_where_the_sentence_goes_on(self):
        before, after = split_at_lead([" today", " the", " sun"], [1.0, 1.3, 1.5], 1.2)
        self.assertEqual(mark_at_join(before, after), ("", False))

    def test_nothing_after_the_join(self):
        before, after = split_at_lead([" today", "."], [1.0, 1.1], 1.2)
        self.assertEqual(after, [])
        self.assertEqual(mark_at_join(before, after), (".", False))

    def test_a_word_written_across_the_pause_cant_be_cut(self):
        tokens = [" it", " is", " at", " ", "3", ":", "3", "0", " tomorrow"]
        times = [0.2, 0.5, 0.9, 1.0, 1.0, 2.7, 2.7, 2.8, 3.1]
        self.assertIsNone(split_at_lead(tokens, times, 2.5))
        self.assertIsNone(split_at_lead([" for", "give", " me"], [1.0, 2.6, 2.9], 2.5))

    def test_a_mark_said_by_itself_is_the_new_phrases(self):
        before, after = split_at_lead([" Hi", " Rick", ","], [0.2, 0.5, 1.3], 1.2)
        self.assertEqual((before, after), ([" Hi", " Rick"], [","]))

    def test_a_closing_quote_after_the_stop_is_looked_past(self):
        self.assertEqual(mark_at_join([" go", " away", ".", "”"], [" Then"]), (".", True))


class Result:
    def __init__(self, tokens, timestamps=None):
        self.tokens = tokens
        self.timestamps = timestamps
        self.ys_log_probs = None
        self.text = "".join(tokens).strip()


class Recogniser:
    """Hears whatever it is given as `script(seconds)` says: (tokens, times)."""

    def __init__(self, script):
        self.script, self.heard = script, []

    def create_stream(self):
        recogniser = self

        class Stream:
            def accept_waveform(self, rate, audio):
                self.audio = audio

        return Stream()

    def decode_stream(self, stream):
        seconds = len(stream.audio) / config.RATE
        self.heard.append(seconds)
        tokens, times = self.script(seconds)
        stream.result = Result(tokens, times)


def transcriber(recogniser):
    ears = Transcriber.__new__(Transcriber)
    ears._loaded = {"parakeet-x": recogniser}
    ears.lock = __import__("threading").RLock()
    ears.speech_only = False
    ears.dictation_name = "parakeet-x"
    ears._is_transducer = lambda name: True
    ears._transducer = lambda name: recogniser
    return ears


class TheHearing(unittest.TestCase):
    def test_only_the_new_words_come_back_and_the_join_is_kept(self):
        def script(seconds):
            if seconds > 2.5:                 # heard with the end of the one before
                return ([" for", " the", " report", ".", " Thanks", " a", " lot", "."],
                        [0.2, 0.5, 0.8, 1.1, 2.1, 2.4, 2.6, 2.8])
            return [" thanks", " a", " lot", "."], [0.1, 0.4, 0.6, 0.8]
        recogniser = Recogniser(script)
        ears = transcriber(recogniser)
        lead = np.zeros(2 * config.RATE, dtype=np.float32)
        phrase = np.zeros(1 * config.RATE, dtype=np.float32)
        with mock.patch.object(engine_module, "log"):
            text = ears.transcribe(np.concatenate([lead, phrase]), True, lead=len(lead))
        self.assertEqual(text, "Thanks a lot.")
        self.assertEqual(text.at_join, (".", True))

    def test_a_number_said_across_the_pause_is_heard_by_itself(self):
        def script(seconds):
            if seconds > 2.5:
                return [" it", " costs", " 2", "5", " dollars"], [0.2, 0.5, 1.9, 2.1, 2.4]
            return [" five", " dollars"], [0.1, 0.4]
        recogniser = Recogniser(script)
        ears = transcriber(recogniser)
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        with mock.patch.object(engine_module, "log"):
            self.assertEqual(ears.transcribe(audio, True, lead=2 * config.RATE), "five dollars")

    def test_the_join_goes_back_with_the_words_not_on_the_recogniser(self):
        def script(seconds):
            return ([" one", ".", " Two"], [0.3, 0.6, 2.2]) if seconds > 2.5 else ([" two"], [0.1])
        ears = transcriber(Recogniser(script))
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        with mock.patch.object(engine_module, "log"):
            first = ears.transcribe(audio, True, lead=2 * config.RATE)
            ears.transcribe(audio[:config.RATE], True)       # (another phrase heard meanwhile)
        self.assertEqual(first.at_join, (".", True))

    def test_without_the_models_times_the_phrase_is_heard_by_itself(self):
        recogniser = Recogniser(lambda seconds: ([" all", " of", " it"] if seconds > 1.5 else [" it"], None))
        ears = transcriber(recogniser)
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        with mock.patch.object(engine_module, "log"):
            text = ears.transcribe(audio, True, lead=2 * config.RATE)
        self.assertEqual(text, "it")
        self.assertEqual(recogniser.heard, [3.0, 1.0])
        self.assertIsNone(getattr(text, "at_join", None))

    def test_whisper_and_what_leans_on_the_prompt_hear_the_phrase_alone(self):
        ears = transcriber(Recogniser(lambda s: ([], [])))
        ears._is_transducer = lambda name: False
        seen = []
        ears._transcribe = lambda audio, awake, prompt, model, quick: seen.append(len(audio)) or "words"
        ears._let_go_of_code_model = lambda: None
        ears.quick = False
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        self.assertEqual(ears.transcribe(audio, True, lead=2 * config.RATE), "words")
        self.assertEqual(seen, [config.RATE])

    def test_a_guest_asks_with_the_phrase_before_and_is_told_it_was_taken_so(self):
        ears = transcriber(Recogniser(lambda s: ([" before", ".", " Now"], [0.3, 0.6, 2.2])))
        ears._guests, ears.not_speech, ears.ignored = [], 0.0, ""
        ears._guest_model = lambda header: "parakeet-x"
        ears._let_go_of_code_model = lambda: None
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        with mock.patch.object(engine_module, "log"):
            reply = ears.answer({"kind": "phrase", "awake": True, "lead": 2 * config.RATE}, audio)
        self.assertEqual((reply["text"], reply["lead"], reply["join"]), ("Now", 2 * config.RATE, [".", True]))
        reply = ears.answer({"kind": "phrase", "awake": True}, audio)
        self.assertEqual(reply["lead"], 0)
        self.assertNotIn("join", reply)


class Decides:
    def __init__(self, answer=""):
        self.answer, self.asked = answer, []

    def decide(self, before, phrase, held):
        self.asked.append((before, phrase, held))
        return self.answer


class WhatGoesInFront(unittest.TestCase):
    def setUp(self):
        for patch in (mock.patch("dictation.engine.log"), mock.patch.object(config, "SENTENCE_QUIET", 0),
                      mock.patch("dictation.engine.Engine._save")):
            patch.start()
            self.addCleanup(patch.stop)

    def engine(self, page, **states):
        states.setdefault("left_context", True)
        engine = bare(page, tidy=False, hear_again=False, **states)
        engine.settings.sentence_ends = "words"
        engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
        engine._decider = self.decider = Decides("")
        return engine

    def unit(self, engine, seconds=2.0, ago=1.0, program="Writer"):
        sound = np.zeros(int(seconds * config.RATE), dtype=np.float32)
        sound[:int(seconds * config.RATE * 0.8)] = 0.3       # voice, then quiet
        engine._heard_units = [{"program": program, "sound": sound, "ended": time.monotonic() - ago}]

    def test_the_phrase_before_as_it_was(self):
        engine = self.engine(Page())
        self.unit(engine, seconds=2.0)
        self.assertEqual(len(engine._lead_for(True)), 2 * config.RATE)

    def test_only_so_much_of_it(self):
        engine = self.engine(Page())
        self.unit(engine, seconds=10.0)
        self.assertEqual(len(engine._lead_for(True)), int(config.LEFT_CONTEXT * config.RATE))

    def test_none_with_no_seconds_of_it(self):
        engine = self.engine(Page())
        self.unit(engine)
        with mock.patch.object(config, "LEFT_CONTEXT", 0):
            self.assertIsNone(engine._lead_for(True))

    def test_none_when_switched_off_or_nothing_to_go_on_with(self):
        engine = self.engine(Page(), left_context=False)
        self.unit(engine)
        self.assertIsNone(engine._lead_for(True))
        engine = self.engine(Page())
        self.assertIsNone(engine._lead_for(True))             # nothing typed before
        self.unit(engine, ago=config.LEFT_CONTEXT_GAP + 5)
        self.assertIsNone(engine._lead_for(True))             # too long ago
        self.unit(engine, program="Word")
        self.assertIsNone(engine._lead_for(True))             # another program
        self.unit(engine)
        self.assertIsNone(engine._lead_for(False))            # not ordinary dictation

    def kept(self, engine, *heard):
        """Phrases heard one after another: what is kept for the next to be heard with."""
        for text, typed in heard:
            sound = np.full(config.RATE, 0.1 * (len(getattr(engine, "_heard_units", []) or []) + 1),
                            dtype=np.float32)
            engine._just_typed = (0, text, False) if typed else None
            engine._keep_for_context(sound, text, time.monotonic(), True)
        return [round(float(u["sound"][0]), 1) for u in engine._heard_units]

    def test_what_is_kept_to_go_on_with(self):
        engine = self.engine(Page())
        self.assertEqual(self.kept(engine, ("It works.", True), ("new paragraph", False)), [0.1, 0.2])
        self.assertEqual(self.kept(engine, ("", False)), [0.1, 0.2])            # a cough: nothing changes
        engine._took_back = True
        self.assertEqual(self.kept(engine, ("scratch that", False)), [0.1])      # the one taken back goes
        engine._took_back = False
        self.assertEqual(self.kept(engine, ("scratch that", False)), [0.1])      # nothing taken: kept
        self.assertEqual(self.kept(engine, ("bold that", False)), [])            # another command: all of it

    def test_only_the_last_three(self):
        engine = self.engine(Page())
        self.assertEqual(len(self.kept(engine, *[("It works.", True)] * 5)), 3)

    def test_sleep_forgets(self):
        engine = self.engine(Page())
        self.kept(engine, ("It works.", True))
        engine.sleep()
        self.assertEqual(engine._heard_units, [])

    def test_the_join_heard_decides_the_full_stop(self):
        page = Page()
        engine = self.engine(page)
        engine.handle_text("I will send the report tomorrow.", True)
        engine._heard_join = (".", True)                       # as handle_audio leaves it
        engine.handle_text("thanks for your help.", True)
        self.assertEqual(page.text, "I will send the report tomorrow. Thanks for your help")
        self.assertEqual(self.decider.asked, [])               # the words were not asked

    def test_and_that_it_goes_on(self):
        page = Page()
        engine = self.engine(page)
        self.decider.answer = "."
        engine.handle_text("I will send the report.", True)
        engine._heard_join = ("", False)
        engine.handle_text("tomorrow morning.", True)
        self.assertEqual(page.text, "I will send the report tomorrow morning")

    def test_only_for_the_phrase_it_was_heard_with(self):
        page = Page()
        engine = self.engine(page)
        self.decider.answer = ","
        engine.handle_text("It works.", True)
        engine._heard_join = (".", True)
        engine.handle_text("scratch that", True)              # a command in between: not used
        engine.handle_text("It works.", True)
        engine.handle_text("then we left.", True)
        self.assertEqual(page.text, "It works, then we left")


class OverTheLink(unittest.TestCase):
    """The lead goes to the other computer with the phrase; one of an earlier version is
    asked again without it, and not sent it again."""

    class There:
        host = "elsewhere"
        sound = ""

        def __init__(self, understands=True):
            self.understands, self.calls = understands, []

        def hear(self, kind, audio, awake, prompt="", model="", otherwise=(), quick=False,
                 exact=False, speech_only=True, wake_same=True, code=False, letters=False,
                 sound="pcm", lead=0):
            self.calls.append((len(audio), lead))
            reply = {"ok": True, "text": "the words", "model": "parakeet-x"}
            if self.understands:
                reply["lead"] = lead
                if lead:
                    reply["join"] = [",", False]
            return reply

    def offload(self, there, local=None):
        from dictation import remote
        return remote.Offload(lambda: local, there, "parakeet-x", (), clock=lambda: 100.0)

    def test_sent_with_the_phrase_and_the_join_comes_back(self):
        there = self.There()
        offload = self.offload(there)
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        self.assertEqual(offload.transcribe(audio, True, lead=2 * config.RATE), "the words")
        self.assertEqual(there.calls, [(3 * config.RATE, 2 * config.RATE)])
        self.assertEqual(offload.join_heard, (",", False))

    def test_an_earlier_version_is_asked_again_without_it(self):
        there = self.There(understands=False)
        offload = self.offload(there)
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        self.assertEqual(offload.transcribe(audio, True, lead=2 * config.RATE), "the words")
        self.assertEqual(there.calls, [(3 * config.RATE, 2 * config.RATE), (config.RATE, 0)])
        self.assertIsNone(offload.join_heard)
        offload.transcribe(audio, True, lead=2 * config.RATE)
        self.assertEqual(there.calls[-1], (config.RATE, 0))   # and not sent it again

    def test_heard_here_when_the_other_computer_cant_be_asked(self):
        class Down(self.There):
            def hear(self, *a, **k):
                raise OSError("no answer")

        class Local:
            def __init__(self):
                self.asked = []

            def transcribe(self, audio, awake, prompt="", **more):
                from dictation import joins
                self.asked.append((len(audio), more.get("lead", 0)))
                return joins.heard("heard here", (".", True))

        local = Local()
        offload = self.offload(Down(), local)
        audio = np.zeros(3 * config.RATE, dtype=np.float32)
        with mock.patch("dictation.remote.log", create=True):
            self.assertEqual(offload.transcribe(audio, True, lead=2 * config.RATE), "heard here")
        self.assertEqual(local.asked, [(3 * config.RATE, 2 * config.RATE)])
        self.assertEqual(offload.join_heard, (".", True))


if __name__ == "__main__":
    unittest.main()
