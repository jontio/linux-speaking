"""How the three ways of putting full stops do on the person's samples (bench.py)."""
import tempfile
import unittest

import numpy as np

from dictation import bench, samples


def kept(folder, written, meant):
    recording = samples.Recording(folder)
    for i, line in enumerate(written):
        recording.add(np.zeros(160, dtype=np.float32), line, 1.0 + i, 0.01)
    recording.keep(meant)


class Checking(unittest.TestCase):
    def test_each_way_is_scored_and_the_best_named(self):
        folder = tempfile.mkdtemp()
        kept(folder, ["Also, it should be an option.", "That the user can select."],
             "Also, it should be an option that the user can select.")
        found = bench.check(folder, decider=None, reader=None, build=False)
        self.assertEqual(found["samples"], 1)
        self.assertEqual(found["phrases"], 2)
        self.assertEqual(found["ways"]["said"]["errors"], 0)     # typed as meant, stop held back
        self.assertGreater(found["ways"]["pause"]["errors"], 0)  # a stop where a comma was meant
        self.assertEqual(found["best"], "said")
        self.assertFalse(found["model"])                         # none was built

    def test_nothing_kept_is_nothing_scored(self):
        found = bench.check(tempfile.mkdtemp(), decider=None, build=False)
        self.assertEqual((found["samples"], found["words"], found["best"]), (0, 0, ""))

    def test_a_way_that_typed_nothing_is_no_winner(self):
        folder = tempfile.mkdtemp()
        kept(folder, ["Hello there.", "Scratch that."], "Hello, there.")
        found = bench.check(folder, decider=None, build=False)
        self.assertEqual(found["best"], "")

    def test_the_typing_can_be_given_for_showing(self):
        folder = tempfile.mkdtemp()
        kept(folder, ["Hello."], "Hello.")
        found = bench.check(folder, decider=None, with_texts=True, build=False)
        self.assertEqual(len(found["texts"]), 1)
        here, meant, typed = found["texts"][0]
        self.assertEqual(meant, "Hello.")
        self.assertEqual(set(typed), set(bench.SHORT))
