"""Deciding from the words whether a sentence ended at a pause (punctuation.py). The rule is
tried with made-up chances; the model itself, where it is installed."""
import os
import unittest

from dictation import config, punctuation
from dictation.punctuation import WordsDecider


class Chances:
    """Stands in for the model: gives the same chances at every word."""

    def __init__(self, none=0.0, comma=0.0, stop=0.0, question=0.0):
        self.row = [none, comma, stop, question]

    def pieces_of(self, word):
        return 1

    def probabilities(self, words):
        return [list(self.row) for _ in words]


def decide(held, **chances):
    return WordsDecider(Chances(**chances)).decide("it should be an option", " that the user can select", held)


class TheRule(unittest.TestCase):
    def test_the_recognisers_stop_goes_where_the_words_say_the_sentence_goes_on(self):
        self.assertEqual(decide(".", none=0.97, stop=0.03), "")
        self.assertEqual(decide(".", none=0.1, comma=0.87, stop=0.03), ",")

    def test_and_stays_where_they_dont_say_so_clearly(self):
        self.assertEqual(decide(".", none=0.8, stop=0.2), ".")
        self.assertEqual(decide(".", none=0.9, stop=0.1), ".")      # a sentence end is not taken away lightly
        self.assertEqual(decide("?", none=0.8, stop=0.1, question=0.1), "?")
        self.assertEqual(decide("!", none=0.8, stop=0.2), "!")

    def test_a_full_stop_becomes_a_question_mark_where_the_words_ask(self):
        self.assertEqual(decide(".", stop=0.3, question=0.6), "?")
        self.assertEqual(decide(".", stop=0.4, question=0.5), ".")       # not by enough

    def test_where_the_recogniser_wrote_none_one_goes_in_only_if_the_words_are_clear(self):
        self.assertEqual(decide("", none=0.4, stop=0.6), ".")
        self.assertEqual(decide("", none=0.4, question=0.6), "?")
        self.assertEqual(decide("", none=0.6, stop=0.4), "")
        self.assertEqual(decide("", none=0.4, comma=0.6), ",")

    def test_with_no_words_on_one_side_the_recogniser_has_it(self):
        decider = WordsDecider(Chances(stop=1.0))
        self.assertEqual(decider.decide("", " that the user", "."), ".")
        self.assertEqual(decider.decide("it works", "", ""), "")


class WhatTheModelIsShown(unittest.TestCase):
    def test_words(self):
        self.assertEqual(punctuation.model_words("Wi-Fi,"), ["wi", "fi"])
        self.assertEqual(punctuation.model_words("Don’t"), ["don't"])
        self.assertEqual(punctuation.model_words("“Hello”"), ["hello"])
        self.assertEqual(punctuation.model_words("&"), ["<unk>"])
        self.assertEqual(punctuation.model_words("3.5"), ["3", "5"])


HERE = os.environ.get("LS_PUNCTUATION_MODEL_DIR", config.HELPER_MODEL_DIR)


try:
    import onnxruntime  # noqa: F401  (what runs the model)
    RUNS = True
except ImportError:
    RUNS = False


@unittest.skipUnless(RUNS and punctuation.installed(HERE),
                     "the punctuation model, or onnxruntime to run it, is not installed here")
class TheModel(unittest.TestCase):
    """The real model, where it is installed (LS_PUNCTUATION_MODEL_DIR may say where)."""

    @classmethod
    def setUpClass(cls):
        cls.decider = WordsDecider(punctuation.Model(HERE))

    def test_a_pause_in_the_middle_of_a_sentence(self):
        for before, phrase in (("Also, it should be an option", " that the user can select"),
                               ("It needs to be able to look over the last few sentences to figure out",
                                " what the punctuation should be"),
                               ("I'm going past the chemist tomorrow so", " I can grab whatever you need"),
                               ("Parking is limited so take", " the bus if you can")):
            self.assertEqual(self.decider.decide(before, phrase, "."), "", (before, phrase))

    def test_a_sentence_that_ended(self):
        self.assertIn(self.decider.decide("Thanks for sending the report", " I will read it tonight", "."),
                      (".", "?"))
        self.assertEqual(self.decider.decide("Can you send me the report", " I need it by Friday", "?"), "?")

    def test_it_is_quick(self):
        import time
        began = time.perf_counter()
        for _ in range(20):
            self.decider.decide("It should be an option", " that the user can select", ".")
        self.assertLess((time.perf_counter() - began) / 20, 0.2)


if __name__ == "__main__":
    unittest.main()


class Fetching(unittest.TestCase):
    """The download is checked before anything is kept (no network: a made-up archive)."""

    def archive(self, files):
        import io
        import tarfile
        held = io.BytesIO()
        with tarfile.open(fileobj=held, mode="w:bz2") as tar:
            for name, content in files.items():
                info = tarfile.TarInfo(punctuation.IN_ARCHIVE + name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
        return held.getvalue()

    def fetched(self, data, files):
        import hashlib
        import io
        import tempfile
        from unittest import mock
        folder = tempfile.mkdtemp()
        reply = mock.MagicMock()
        reply.__enter__.return_value = reply
        stream = io.BytesIO(data)
        reply.read.side_effect = lambda n=-1: stream.read(n)
        reply.headers = {"Content-Length": str(len(data))}
        with mock.patch("urllib.request.urlopen", return_value=reply), \
                mock.patch.object(punctuation, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()), \
                mock.patch.object(punctuation, "FILES", {n: hashlib.sha256(c).hexdigest() for n, c in files.items()}):
            punctuation.fetch(folder)
            return folder, punctuation.installed(folder)

    def test_the_two_files_are_taken_out_and_checked(self):
        files = {"model.int8.onnx": b"model", "bpe.vocab": b"pieces"}
        folder, done = self.fetched(self.archive(dict(files, **{"model.onnx": b"not wanted"})), files)
        self.assertTrue(done)
        self.assertEqual(sorted(os.listdir(punctuation.folder(folder))), ["bpe.vocab", "model.int8.onnx"])

    def test_an_archive_that_is_not_the_published_one_is_refused(self):
        import hashlib
        import io
        import tempfile
        from unittest import mock
        folder = tempfile.mkdtemp()
        data = self.archive({"model.int8.onnx": b"model", "bpe.vocab": b"pieces"})
        reply = mock.MagicMock()
        reply.__enter__.return_value = reply
        stream = io.BytesIO(data)
        reply.read.side_effect = lambda n=-1: stream.read(n)
        reply.headers = {}
        with mock.patch("urllib.request.urlopen", return_value=reply), \
                mock.patch.object(punctuation, "ARCHIVE_SHA256", hashlib.sha256(b"another").hexdigest()):
            with self.assertRaises(ValueError):
                punctuation.fetch(folder)
        self.assertFalse(punctuation.installed(folder))
        self.assertFalse(os.path.exists(punctuation.folder(folder)))
