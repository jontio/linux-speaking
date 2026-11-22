"""Samples of dictation as it is really done (samples.py): kept, read back, and forgotten."""
import json
import os
import tempfile
import unittest
import wave

import numpy as np

from dictation import samples


class Keeping(unittest.TestCase):
    def test_kept_with_their_sound_and_what_was_meant(self):
        folder = tempfile.mkdtemp()
        recording = samples.Recording(folder)
        recording.add(np.full(1600, 0.5, dtype=np.float32), "It works.", 100.0, 1.6)
        recording.add(np.zeros(3200, dtype=np.float32), "Then we left.", 103.0, 0.8)
        here = recording.keep("It works, then we left.", {"sentence_ends": "words"})
        self.assertEqual(recording.phrases, [])
        with open(os.path.join(here, samples.SAMPLE), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["meant"], "It works, then we left.")
        self.assertEqual(record["sentence_ends"], "words")
        self.assertEqual([(p["written"], p["pause_before"], p["seconds"]) for p in record["phrases"]],
                         [("It works.", None, 1.6), ("Then we left.", 2.2, 0.8)])
        with wave.open(os.path.join(here, "phrase-01.wav")) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getnframes()), (16000, 1, 1600))
        self.assertEqual([path for path, _ in samples.kept(folder)], [here])

    def test_each_sample_gets_a_folder_of_its_own(self):
        folder = tempfile.mkdtemp()
        recording = samples.Recording(folder)
        for _ in range(3):
            recording.add(np.zeros(160, dtype=np.float32), "Yes.", 1.0, 0.01)
            recording.keep("Yes.")
        self.assertEqual(len({path for path, _ in samples.kept(folder)}), 3)

    def test_forgotten(self):
        folder = tempfile.mkdtemp()
        recording = samples.Recording(folder)
        recording.add(np.zeros(160, dtype=np.float32), "Yes.", 1.0, 0.01)
        recording.keep("Yes.")
        samples.forget(folder)
        self.assertEqual(samples.kept(folder), [])

    def test_one_forgotten_and_the_rest_kept(self):
        folder = tempfile.mkdtemp()
        recording = samples.Recording(folder)
        for _ in range(2):
            recording.add(np.zeros(160, dtype=np.float32), "Yes.", 1.0, 0.01)
            recording.keep("Yes.")
        first, second = [path for path, _ in samples.kept(folder)]
        samples.forget(folder, only=second)
        self.assertEqual([path for path, _ in samples.kept(folder)], [first])
        samples.forget(folder, only=first)
        self.assertEqual(samples.kept(folder), [])
        self.assertEqual(os.listdir(folder), [])      # the day's folder went with the last one

    def test_nothing_there_is_nothing_kept(self):
        self.assertEqual(samples.kept(os.path.join(tempfile.mkdtemp(), "none")), [])

    @unittest.skipUnless(os.name == "posix", "the modes are Linux's")
    def test_only_the_person_can_read_them(self):
        folder = os.path.join(tempfile.mkdtemp(), "samples")
        recording = samples.Recording(folder)
        recording.add(np.zeros(160, dtype=np.float32), "Yes.", 1.0, 0.01)
        here = recording.keep("Yes.")
        for path in (folder, os.path.dirname(here), here):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700, path)
        for name in os.listdir(here):
            self.assertEqual(os.stat(os.path.join(here, name)).st_mode & 0o777, 0o600, name)

    def test_one_that_cant_be_kept_leaves_nothing_behind_and_can_be_kept_again(self):
        from unittest import mock
        folder = tempfile.mkdtemp()
        recording = samples.Recording(folder)
        recording.add(np.zeros(160, dtype=np.float32), "Yes.", 1.0, 0.01)
        with mock.patch("dictation.samples.json.dump", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                recording.keep("Yes.")
        day = os.listdir(folder)[0]
        self.assertEqual(os.listdir(os.path.join(folder, day)), [])
        self.assertEqual(len(recording.phrases), 1)        # still there, to keep again
        recording.keep("Yes.")
        self.assertEqual(len(samples.kept(folder)), 1)


if __name__ == "__main__":
    unittest.main()


class PlayedBack(unittest.TestCase):
    """A sample typed again as the program would type it, each way, and scored."""

    WRITTEN = ["Also, it should be an option.", "That the user can select."]
    MEANT = "Also, it should be an option that the user can select."

    def test_at_every_pause_a_stop_and_a_capital_mid_sentence(self):
        typed = samples.replay(self.WRITTEN, "pause")
        self.assertEqual(typed, "Also, it should be an option. That the user can select.")
        found = samples.score(typed, self.MEANT)
        self.assertEqual((found["ends_wrong"], found["capitals_wrong"]), (1, 1))

    def test_only_where_said_none(self):
        typed = samples.replay(self.WRITTEN, "said")
        self.assertEqual(typed, "Also, it should be an option that the user can select")
        found = samples.score(typed, self.MEANT)
        self.assertEqual((found["ends_wrong"], found["ends_missed"], found["capitals_wrong"]), (0, 0, 0))

    def test_where_the_words_decide_with_what_decides_given(self):
        class Never:
            def decide(self, before, phrase, held):
                return ""
        typed = samples.replay(self.WRITTEN, "words", Never())
        self.assertEqual(typed, "Also, it should be an option that the user can select.")

    def test_a_replay_never_writes_down_whether_dictation_is_on(self):
        from unittest import mock
        from dictation.engine import Engine
        with mock.patch.object(Engine, "_save", side_effect=AssertionError("saved")):
            samples.replay(["Hi Sam,", "the report is attached.", "Go to sleep."], "said")
            samples.replay(["It works."], "words", decider=None)

    def test_commands_said_are_carried_out(self):
        typed = samples.replay(["Hi Rick,", "new line", "Thanks for that.", "Scratch that.", "Thanks."], "pause")
        self.assertEqual(typed, "Hi Rick,\nThanks.")

    def test_score_counts_what_is_wrong_and_leaves_out_misheard_words(self):
        found = samples.score("Hier, I will come. Tomorrow and Bring it", "Hi Rick, I will come tomorrow and bring it.")
        self.assertEqual(found["words"], 9)
        self.assertGreaterEqual(found["misheard"], 2)
        self.assertEqual((found["ends_wrong"], found["capitals_wrong"]), (1, 2))

    def test_a_comma_missed_at_a_line_break_is_counted(self):
        # (The break's full stop used to take the comma's place on both sides, which hid it.)
        found = samples.score("Hi Sam\n\nHow are you?", "Hi Sam,\n\nHow are you?")
        self.assertEqual(found["commas_missed"], 1)
        self.assertEqual(found["ends_missed"], 0)

    def test_a_stop_where_a_comma_was_meant_is_counted_once(self):
        found = samples.score("Hi Sam. How are you?", "Hi Sam, how are you?")
        self.assertEqual((found["commas_missed"], found["ends_wrong"]), (1, 0))
