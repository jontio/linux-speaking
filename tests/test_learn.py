"""Words learned from the samples of real dictation (learn.py)."""
import json
import os
import tempfile
import unittest

from dictation import learn


def sample(typed, meant, written=None):
    """A kept sample as samples.kept gives it. `written` is what the recogniser wrote; it
    is kept in the sample but it is not what learning looks at."""
    record = {"meant": meant, "typed": typed,
              "phrases": [{"written": line} for line in (written or [typed])]}
    return ("somewhere", record)


class Pairs(unittest.TestCase):
    def test_a_word_put_right_for_another_is_learned(self):
        table = learn.pairs([sample("I spoke to Junty.", "I spoke to Jonti.")])
        self.assertEqual(table, {"junty": "Jonti"})

    def test_what_the_program_itself_put_right_is_not_learned(self):
        # (Sums of money in figures, the sound-alike tidy-up: the person changed nothing.)
        table = learn.pairs([sample("$20 or $30", "$20 or $30",
                                    written=["twenty or thirty dollars"])])
        self.assertEqual(table, {})

    def test_a_word_mostly_left_as_typed_is_not_this_voice_slip(self):
        table = learn.pairs([sample("A jaunty tune. Jaunty went home. Jaunty",
                                    "A jaunty tune. Jonti went home. Jaunty")])
        self.assertEqual(table, {})

    def test_two_meanings_for_one_form_are_left(self):
        self.assertEqual(learn.pairs([sample("Jim", "Jon"), sample("Jim", "Jane")]), {})

    def test_words_of_one_letter_and_two_for_one_are_left(self):
        self.assertEqual(learn.pairs([sample("a", "I")]), {})
        self.assertEqual(learn.pairs([sample("John T", "Jonti")]), {})

    def test_the_form_is_kept_as_it_was_meant(self):
        self.assertEqual(learn.pairs([sample("junty", "Jonti")]), {"junty": "Jonti"})

    def test_a_sample_from_before_the_program_typing_was_kept_teaches_nothing(self):
        record = ("somewhere", {"meant": "I spoke to Jonti.",
                                "phrases": [{"written": "I spoke to Junty."}]})
        self.assertEqual(learn.pairs([record]), {})


class Saved(unittest.TestCase):
    def test_nothing_is_put_in_place_of_what_was_said(self):
        # (The pairs are evidence only: the engine knows nothing of them, and there is no
        # function here that rewrites text.)
        from dictation import engine
        self.assertFalse(hasattr(learn, "apply"))
        self.assertNotIn("learn", dir(engine))
    def test_round_trip_and_only_its_owner_can_read_it(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "learned-words.json")
        learn.save({"junty": "Jonti"}, path)
        self.assertEqual(learn.load(path), {"junty": "Jonti"})
        if os.name == "posix":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_what_cannot_be_read_is_nothing(self):
        folder = tempfile.mkdtemp()
        self.assertEqual(learn.load(os.path.join(folder, "none.json")), {})
        path = os.path.join(folder, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pairs": "junty"}, f)
        self.assertEqual(learn.load(path), {})

    def test_worked_out_again_from_the_samples_kept(self):
        import numpy as np
        from dictation import samples
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "learned.json")
        recording = samples.Recording(folder)
        recording.add(np.zeros(160, dtype=np.float32), "Cheers, Junty.", 1.0, 0.01)
        recording.keep("Cheers, Jonti.", {"typed": "Cheers, Junty."})
        self.assertEqual(learn.from_samples(folder, path), {"junty": "Jonti"})
        samples.forget(folder)
        self.assertEqual(learn.from_samples(folder, path), {})
