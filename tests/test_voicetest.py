import os
import tempfile
import unittest

import numpy as np

from dictation import config, voicetest
from dictation.voicetest import Candidate, compare, words


class Words(unittest.TestCase):
    def test_case_and_punctuation_do_not_count(self):
        self.assertEqual(words("Hello, World! It’s well-known."), ["hello", "world", "it's", "well", "known"])

    def test_the_passage_has_nothing_that_can_be_written_two_ways(self):
        text = " ".join(voicetest.PASSAGE)
        self.assertFalse(any(c.isdigit() for c in text))
        self.assertGreater(len(words(text)), 200)
        self.assertLess(len(words(text)), 340)     # it all has to fit in the window
        for figure in "one two three four five six seven eight nine ten".split():
            self.assertNotIn(figure, words(text))  # may be written as a figure

    def test_the_passage_has_the_words_that_get_taken_for_others(self):
        said = words(" ".join(voicetest.PASSAGE))
        self.assertGreaterEqual(said.count("better"), 3)
        for word in "beta pen pin chair really ferry bed bad letter later salary celery".split():
            self.assertIn(word, said)


class Compare(unittest.TestCase):
    def check(self, said, heard, wrong, slips):
        self.assertEqual(compare(words(said), words(heard)), (wrong, slips))

    def test_all_right(self):
        self.check("the cat sat on the mat", "The cat sat on the mat.", 0, [])

    def test_a_changed_word(self):
        self.check("the cat sat on the mat", "the cat sat on the map", 1, [("mat", "map")])

    def test_a_word_left_out_and_one_put_in(self):
        self.check("the cat sat on the mat", "the cat on the mat", 1, [("sat", "")])
        self.check("the cat sat", "the big cat sat", 1, [("", "big")])

    def test_neighbouring_slips_are_shown_together(self):
        self.check("we walk along the beach today", "we walk a long the beach today", 2, [("along", "a long")])
        self.check("send the latest figures now", "send the late fingers now", 2, [("latest figures", "late fingers")])

    def test_nothing_heard_and_nothing_said(self):
        self.check("one two three", "", 3, [("one two three", "")])
        self.check("", "hello", 1, [("", "hello")])
        self.check("", "", 0, [])


class SpokenPunctuation(unittest.TestCase):
    strip = staticmethod(lambda text: voicetest.without_spoken_signs(words(text)))

    def test_said_as_words_or_left_out_it_is_the_same(self):
        said = words("Could you send me the latest figures when you get a chance?")
        for heard in ("Could you send me the latest figures when you get a chance question mark",
                      "could you send me the latest figures comma when you get a chance?",
                      "Could you send me the latest figures when you get a chance. Full stop. New line."):
            self.assertEqual(compare(said, self.strip(heard))[0], 0, heard)

    def test_the_passage_itself_loses_nothing(self):
        passage = words(" ".join(voicetest.PASSAGE))
        self.assertEqual(voicetest.without_spoken_signs(passage), passage)

    def test_a_misheard_sign_still_counts(self):
        self.assertEqual(compare(words("thanks for the notes"), self.strip("thanks for the notes coma")),
                         (1, [("", "coma")]))

    def test_one_word_or_two_is_not_a_mistake(self):
        said = words("the lazy dog near the river bank every other year")
        self.assertEqual(voicetest.score(said, words("the lazy dog near the riverbank everyother year")), (0, []))
        self.assertEqual(voicetest.score(said, words("the lazy dog near the river tank every other year")),
                         (1, [("bank", "tank")]))

    def test_slips_everyone_made_are_the_readers(self):
        R = voicetest.Result
        results = [R("a", "here", "a", True, 3, 266, 1.0, [["he", "we"], ["same", "aim"], ["from", "for"]]),
                   R("b", "here", "b", True, 2, 266, 1.0, [["he", "we"], ["from", "for"]]),
                   R("c", "here", "c", True, 4, 266, 1.0, [["the", "this"], ["he", "we"], ["from", "for"], ["a", ""]]),
                   R("bad", "here", "bad", True, 130, 266, 1.0, [["he", "she"]]),      # too poor to be asked
                   R("broken", "here", "x", True, 0, 266, 0.0, [], "no such model")]
        self.assertEqual(voicetest.shared_slips(results), [["he", "we"], ["from", "for"]])
        self.assertEqual(voicetest.shared_slips(results[:2]), [])  # too few to tell

    def test_old_results_are_counted_again(self):
        result = voicetest.Result("small", "here", "small.en", True, 9, 266, 1.0,
                                  [["", "comma"], ["chance", "chants question mark"], ["", "period period"],
                                   ["fence", "fens"], ["latest figures", "late fingers full stop"]])
        voicetest.rescore(result)
        self.assertEqual(result.wrong, 4)
        self.assertEqual(result.slips, [["chance", "chants"], ["fence", "fens"], ["latest figures", "late fingers"]])
        voicetest.rescore(result)  # doing it again changes nothing
        self.assertEqual(result.wrong, 4)

    def test_kept_results_are_counted_again_when_read(self):
        path = os.path.join(tempfile.mkdtemp(), "r.json")
        voicetest.save_results([voicetest.Result("small", "here", "small.en", True, 3, 266, 1.0,
                                                 [["", "comma"], ["", "period"], ["fence", "fens"]])], path)
        _, results = voicetest.load_results(path)
        self.assertEqual((results[0].wrong, results[0].slips), (1, [["fence", "fens"]]))


class Phrases(unittest.TestCase):
    def sound(self, *parts):
        """Speech and silence in turn, in seconds, as 16-bit samples with a little room noise."""
        rng = np.random.default_rng(3)
        pieces = [rng.normal(0, 6000 if at % 2 == 0 else 20, int(seconds * config.RATE))
                  for at, seconds in enumerate(parts)]
        return np.concatenate(pieces).astype(np.int16)

    def test_cut_at_the_pauses(self):
        quiet_start = np.concatenate([self.sound(0.0, 1.0), self.sound(1.5, 1.2, 2.0, 1.0, 1.0, 1.0)])
        found = voicetest.phrases(quiet_start)
        self.assertEqual(len(found), 3)
        self.assertEqual(found[0].dtype, np.float32)
        self.assertLessEqual(float(np.max(np.abs(found[0]))), 1.0)
        for phrase, seconds in zip(found, (1.5, 2.0, 1.0)):
            self.assertAlmostEqual(len(phrase) / config.RATE, seconds + 0.95, delta=0.3)  # with the pause

    def test_stopped_mid_phrase_the_last_one_is_kept(self):
        found = voicetest.phrases(np.concatenate([self.sound(0.0, 1.0), self.sound(1.5, 1.2, 0.8)]))
        self.assertEqual(len(found), 2)

    def test_silence_gives_nothing(self):
        self.assertEqual(voicetest.phrases(self.sound(0.0, 3.0)), [])


class Recording(unittest.TestCase):
    def test_saved_and_read_back(self):
        path = os.path.join(tempfile.mkdtemp(), "state", "voice.wav")
        samples = np.arange(-2000, 2000, dtype=np.int16)
        voicetest.save_recording(samples, path)
        np.testing.assert_array_equal(voicetest.load_recording(path), samples)

    def test_a_recording_of_another_text_is_not_used(self):
        path = os.path.join(tempfile.mkdtemp(), "voice.wav")
        voicetest.save_recording(np.arange(100, dtype=np.int16), path)
        self.assertFalse(voicetest.recording_is_old(path))
        with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as f:
            f.write("An older text.")
        self.assertTrue(voicetest.recording_is_old(path))
        self.assertIsNone(voicetest.load_recording(path))
        os.remove(os.path.splitext(path)[0] + ".txt")   # one from before the text was kept
        self.assertTrue(voicetest.recording_is_old(path))
        self.assertIsNone(voicetest.load_recording(path))
        self.assertFalse(voicetest.recording_is_old(os.path.join(tempfile.mkdtemp(), "none.wav")))

    def test_none_if_missing_or_not_ours(self):
        folder = tempfile.mkdtemp()
        self.assertIsNone(voicetest.load_recording(os.path.join(folder, "none.wav")))
        with open(os.path.join(folder, "junk.wav"), "wb") as f:
            f.write(b"not a recording")
        self.assertIsNone(voicetest.load_recording(os.path.join(folder, "junk.wav")))


class Candidates(unittest.TestCase):
    HERE = [("small.en", "Small"), ("parakeet-x", "Parakeet")]
    THERE = [("medium.en", "Medium")]
    whisper = staticmethod(lambda where, name: "parakeet" not in name)

    def test_whisper_both_ways_parakeet_once(self):
        found = voicetest.candidates(self.HERE, self.THERE, (True, False), self.whisper)
        self.assertEqual([(c.where, c.name, c.quick) for c in found],
                         [("here", "small.en", True), ("here", "small.en", False), ("here", "parakeet-x", False),
                          ("there", "medium.en", True), ("there", "medium.en", False)])

    def test_one_way_only(self):
        found = voicetest.candidates(self.HERE, [], (True,), self.whisper)
        self.assertEqual([(c.name, c.quick) for c in found], [("small.en", True), ("parakeet-x", False)])
        found = voicetest.candidates(self.HERE, [], (False,), self.whisper)
        self.assertEqual([(c.name, c.quick) for c in found], [("small.en", False), ("parakeet-x", False)])

    def test_shown_by_their_short_names(self):
        listed = [("small.en", "Small: recommended  (small.en)"), ("en_small", "Small: recommended  (en_small)"),
                  ("medium.en", "Medium: accurate, slow  (medium.en)"), ("odd", "odd")]
        found = voicetest.candidates(listed, [], (True,))
        self.assertEqual([c.label for c in found], ["Small (small.en)", "Small (en_small)", "Medium", "odd"])

    def test_titles_say_which_is_which(self):
        self.assertEqual(Candidate("here", "small.en", "Small", True).title(), "Small, quicker recognition")
        self.assertEqual(Candidate("there", "medium.en", "Medium", False).title(),
                         "Medium, usual way on the other computer")
        self.assertEqual(Candidate("here", "p", "Parakeet", False, whisper=False).title(), "Parakeet")


class Teams(unittest.TestCase):
    """Several recognisers together: a transducer, one Whisper to check it and another to
    settle the two where they differ."""

    whisper = staticmethod(lambda where, name: "parakeet" not in name)
    ALL = [("small.en", "Small"), ("medium.en", "Medium"), ("parakeet-x", "Parakeet"), ("base.en", "Base")]

    def made(self, here, there, ways=(True,)):
        return voicetest.teams(voicetest.candidates(here, there, ways, self.whisper))

    def test_on_this_computer(self):
        (team,) = self.made(self.ALL, [])
        self.assertEqual(team.title(), "Parakeet, checked by Small and Medium")
        self.assertEqual([(m.where, m.name, m.quick) for m in team.team],
                         [("here", "parakeet-x", False), ("here", "small.en", True), ("here", "medium.en", True)])
        self.assertEqual(team.where, "team")

    def test_on_the_other_computer_and_across_the_two(self):
        made = self.made(self.ALL, self.ALL)
        self.assertEqual([team.title() for team in made],
                         ["Parakeet, checked by Small and Medium",
                          "Parakeet, checked by Small and Medium on the other computer",
                          "Parakeet, checked by Small and Medium, all on the other computer"])
        self.assertEqual([m.where for m in made[1].team], ["here", "there", "there"])
        self.assertEqual([m.where for m in made[2].team], ["there", "there", "there"])

    def test_none_without_all_three_kinds(self):
        self.assertEqual(self.made([("small.en", "Small"), ("medium.en", "Medium")], []), [])
        self.assertEqual(self.made([("parakeet-x", "Parakeet"), ("small.en", "Small")], []), [])
        self.assertEqual(self.made([("parakeet-x", "Parakeet")], [("small.en", "Small")]), [])

    def test_the_quick_way_is_used_when_both_are_tried(self):
        (team,) = self.made(self.ALL, [], ways=(True, False))
        self.assertEqual([m.quick for m in team.team], [False, True, True])
        (team,) = self.made(self.ALL, [], ways=(False,))
        self.assertEqual([m.quick for m in team.team], [False, False, False])

    def hearing(self, texts):
        calls = []

        def hear(member, sound, written):
            calls.append(member.name)
            return texts[member.name][sound]
        return hear, calls

    def test_the_third_is_asked_only_where_the_two_differ(self):
        (team,) = self.made(self.ALL, [])
        hear, calls = self.hearing({"parakeet-x": {"a": "Fill the pole.", "b": "It is full."},
                                    "small.en": {"a": "fill the pool", "b": "it is full"},
                                    "medium.en": {"a": "Fill the pool.", "b": "never asked"}})
        self.assertEqual(voicetest.hear_together(team.team, "b", "", hear), ("It is full.", False))
        self.assertEqual(calls, ["parakeet-x", "small.en"])
        self.assertEqual(voicetest.hear_together(team.team, "a", "", hear), ("Fill the pool.", True))
        self.assertEqual(calls[2:], ["parakeet-x", "small.en", "medium.en"])

    def test_across_two_computers_the_first_two_listen_together(self):
        import threading
        team = self.made(self.ALL, self.ALL)[1]
        both = threading.Barrier(2, timeout=5)   # passes only if two are listening at once

        def hear(member, sound, written):
            if member.name != "medium.en":
                both.wait()
            return "the same words"
        self.assertEqual(voicetest.hear_together(team.team, "a", "", hear), ("the same words", False))

    def test_a_team_is_tried_like_any_recogniser(self):
        (team,) = self.made(self.ALL, [])
        hear, calls = self.hearing({"parakeet-x": {"one": "fill the pole", "two": "until it is full"},
                                    "small.en": {"one": "fill the pool", "two": "until it is fall"},
                                    "medium.en": {"one": "fill the pool", "two": "until it is full"}})
        result = voicetest.try_one(team, ["one", "two"], words("fill the pool until it is full"), hear)
        self.assertEqual((result.wrong, result.slips, result.where), (0, [], "team"))
        self.assertEqual(calls[:3], ["parakeet-x", "small.en", "medium.en"])   # each is loaded first
        self.assertIn("differed in 2 of 2 phrases", result.note)
        self.assertIn("Medium was asked", result.note)

    def test_a_team_is_not_suggested(self):
        results = [voicetest.Result("team", "team", "a+b+c", True, 0, 300, 0.5),
                   voicetest.Result("small", "here", "small.en", True, 1, 300, 0.7)]
        self.assertEqual(voicetest.suggestion(results), "small")


class Trying(unittest.TestCase):
    SAID = words("the cat sat on the mat and the dog ran away")
    SOUNDS = ["phrase one", "phrase two"]  # stand-ins: the recogniser below goes by these

    def setUp(self):
        self.now, self.calls = [0.0], []

    def hear(self, texts, seconds=2.0):
        def recogniser(candidate, sound, written):
            self.calls.append((sound, written))
            self.now[0] += seconds
            return texts[sound]
        return recogniser

    def test_counts_and_times(self):
        hear = self.hear({"phrase one": "The cat sat on the map", "phrase two": "and the dog ran away."})
        seen = []
        result = voicetest.try_one(Candidate("here", "small.en", "Small", True), self.SOUNDS, self.SAID, hear,
                                   progress=seen.append, clock=lambda: self.now[0])
        self.assertEqual((result.wrong, result.total, result.slips), (1, 11, [["mat", "map"]]))
        self.assertEqual(result.seconds, 2.0)       # the first, untimed call loads the model
        self.assertEqual(seen, [1, 2])
        self.assertAlmostEqual(result.percent(), 100 / 11)

    def test_each_phrase_is_shown_what_was_written_before_it(self):
        voicetest.try_one(Candidate("here", "s", "S", True), self.SOUNDS, self.SAID,
                          self.hear({"phrase one": "the cat sat", "phrase two": "on the mat"}))
        self.assertEqual(self.calls, [("phrase one", ""), ("phrase one", ""), ("phrase two", "the cat sat")])

    def test_a_recogniser_that_fails_is_reported_not_fatal(self):
        def broken(candidate, sound, written):
            raise RuntimeError("no such model")
        result = voicetest.try_one(Candidate("here", "s", "S", True), self.SOUNDS, self.SAID, broken)
        self.assertEqual(result.problem, "no such model")

    def test_cancelled(self):
        self.assertIsNone(voicetest.try_one(Candidate("here", "s", "S", True), self.SOUNDS, self.SAID,
                                            self.hear({"phrase one": "", "phrase two": ""}),
                                            cancelled=lambda: True))


class Suggesting(unittest.TestCase):
    def result(self, title, wrong, seconds, problem=""):
        return voicetest.Result(title, "here", title, True, wrong, 240, seconds, [], problem)

    def test_the_quickest_of_those_nearly_as_good_as_the_best(self):
        results = [self.result("small", 14, 0.8), self.result("medium", 5, 2.5),
                   self.result("parakeet", 5, 0.5), self.result("large", 4, 6.0)]
        self.assertEqual(voicetest.suggestion(results), "parakeet")

    def test_a_few_words_worse_is_not_nearly_as_good(self):
        results = [self.result("base", 7, 0.3), self.result("small", 4, 0.8)]
        self.assertEqual(voicetest.suggestion(results), "small")

    def test_failed_ones_are_left_out(self):
        self.assertEqual(voicetest.suggestion([self.result("a", 0, 0.1, "broke"), self.result("b", 9, 1.0)]), "b")
        self.assertEqual(voicetest.suggestion([]), "")

    def test_results_are_kept(self):
        path = os.path.join(tempfile.mkdtemp(), "state", "results.json")
        results = [self.result("small", 1, 0.8)]
        results[0].slips = [["mat", "map"]]
        voicetest.save_results(results, path)
        when, again = voicetest.load_results(path)
        self.assertTrue(when)
        self.assertEqual(again, results)
        self.assertEqual(voicetest.load_results(os.path.join(tempfile.mkdtemp(), "none.json")), ("", []))

    def test_results_for_another_text_are_not_shown(self):
        import json
        path = os.path.join(tempfile.mkdtemp(), "results.json")
        voicetest.save_results([self.result("small", 1, 0.8)], path)
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        for passage in ("0123456789abcdef", None):   # another text, and from before it was kept
            saved["passage"] = passage
            with open(path, "w", encoding="utf-8") as f:
                json.dump({k: v for k, v in saved.items() if v is not None}, f)
            self.assertEqual(voicetest.load_results(path), ("", []))


class ReadingSlips(unittest.TestCase):
    """A word read differently from the page is "wrong" for every recogniser alike. It
    is the reader's slip, and is left out of each one's count."""

    def result(self, title, wrong, slips):
        return voicetest.Result(title, "here", title, True, wrong, 300, 1.0, slips)

    def test_shared_slips_are_taken_off(self):
        read = [["", "this"], ["at the", "this"], ["the", ""]]      # four words
        results = [self.result("a", 4, read), self.result("b", 5, read + [["better", "beta"]]),
                   self.result("c", 6, [["pen", "pin"]] + read + [["bed", "bad"]])]
        shared = voicetest.shared_slips(results)
        self.assertEqual(shared, read)
        self.assertEqual([voicetest.own_wrong(r, shared) for r in results], [0, 1, 2])

    def test_only_the_slips_it_made_are_taken_off(self):
        # One that did badly isn't asked about shared slips, and may not have made them.
        shared = [["at the", "this"]]
        self.assertEqual(voicetest.own_wrong(self.result("bad", 90, [["a", "b"]]), shared), 90)
        self.assertEqual(voicetest.own_wrong(self.result("ok", 3, [["at the", "this"], ["x", "y"]]), []), 3)


if __name__ == "__main__":
    unittest.main()
