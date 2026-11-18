import hashlib
import io
import json
import struct
import os
import tempfile
import unittest
import urllib.error

from dictation import models
from dictation.settings import available_models, model_label

KNOWN = models.Known("tiny.en", "Someone/tiny", 1)
FILES = {"config.json": b"{}", "model.bin": bytes(range(256)) * 4000, "vocabulary.txt": b"a\nb\n"}


class Reply(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Site:
    """Stands in for the download site."""

    def __init__(self, files=None, ranges=True, digest=None, extra=()):
        self.files = dict(FILES if files is None else files)
        self.ranges = ranges
        self.digest = digest
        self.extra = list(extra)
        self.asked = []      # (url, Range header or None)
        self.agents = set()
        self.stop_after = None  # bytes of model.bin to give before the line drops

    def __call__(self, request, timeout=None):
        url, wanted = request.full_url, request.get_header("Range")
        self.asked.append((url, wanted))
        self.agents.add(request.get_header("User-agent"))
        if url.endswith("/tree/main"):
            entries = [{"type": "file", "path": ".gitattributes", "size": 3},
                       {"type": "directory", "path": "extras", "size": 0}] + self.extra
            for name, data in self.files.items():
                entry = {"type": "file", "path": name, "size": len(data)}
                if name == "model.bin":
                    entry["lfs"] = {"oid": self.digest or hashlib.sha256(data).hexdigest()}
                entries.append(entry)
            return Reply(json.dumps(entries).encode())
        data = self.files[url.rsplit("/", 1)[1]]
        if url.endswith("model.bin") and self.stop_after is not None:
            data = data[:self.stop_after]
        if wanted and self.ranges:
            return Reply(data[int(wanted[len("bytes="):-1]):], 206)
        return Reply(data)


class Fetching(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.final = os.path.join(self.folder, "tiny.en")

    def download(self, site, **more):
        more.setdefault("free", lambda _: 10 ** 12)
        return models.Download(KNOWN, self.folder, opener=site, **more)

    def test_fetches_checks_and_puts_in_place(self):
        site, seen = Site(), []
        folder = self.download(site, progress=lambda done, total: seen.append((done, total))).run()
        self.assertEqual(folder, self.final)
        self.assertEqual(sorted(os.listdir(self.final)), sorted(FILES))
        with open(os.path.join(self.final, "model.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["model.bin"])
        self.assertFalse(os.path.exists(self.final + models.PART))
        total = sum(map(len, FILES.values()))
        self.assertEqual(seen[-1], (total, total))
        self.assertEqual(seen, sorted(seen))
        self.assertTrue(models.is_installed(self.folder, "tiny.en"))
        self.assertEqual(len(site.agents), 1)  # says what program is asking, and no more
        self.assertRegex(site.agents.pop(), r"^linux-speaking/[\d.]+$")

    def test_already_there_asks_nothing(self):
        site = Site()
        self.download(site).run()
        site.asked.clear()
        self.download(site).run()
        self.assertEqual(site.asked, [])

    def test_a_damaged_download_is_thrown_away(self):
        with self.assertRaises(models.Failed):
            self.download(Site(digest="0" * 64)).run()
        self.assertFalse(models.is_installed(self.folder, "tiny.en"))
        self.assertFalse(os.path.exists(os.path.join(self.final + models.PART, "model.bin")))

    def test_a_dropped_line_carries_on_next_time(self):
        site = Site()
        site.stop_after = 5000
        with self.assertRaises(models.Failed):
            self.download(site).run()
        self.assertEqual(models.part_size(self.folder, "tiny.en"), 5000 + len(FILES["config.json"]))
        self.assertEqual(available_models(self.folder), [])  # not offered half-fetched
        site.stop_after = None
        site.asked.clear()
        self.download(site).run()
        self.assertIn(("https://huggingface.co/Someone/tiny/resolve/main/model.bin", "bytes=5000-"),
                      site.asked)
        with open(os.path.join(self.final, "model.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["model.bin"])

    def test_a_site_that_will_not_carry_on_starts_the_file_again(self):
        site = Site(ranges=False)
        site.stop_after = 5000
        with self.assertRaises(models.Failed):
            self.download(site).run()
        site.stop_after = None
        self.download(site).run()
        with open(os.path.join(self.final, "model.bin"), "rb") as f:
            self.assertEqual(f.read(), FILES["model.bin"])

    def test_cancel_stops_and_keeps_what_came(self):
        site = Site()
        download = self.download(site, progress=lambda done, total: download.cancel())
        with self.assertRaises(models.Cancelled):
            download.run()
        self.assertFalse(models.is_installed(self.folder, "tiny.en"))
        self.assertGreater(models.part_size(self.folder, "tiny.en"), 0)
        models.discard_part(self.folder, "tiny.en")
        self.assertEqual(models.part_size(self.folder, "tiny.en"), 0)

    def test_not_enough_room(self):
        with self.assertRaises(models.Failed) as raised:
            self.download(Site(), free=lambda _: 1000).run()
        self.assertIn("disk space", str(raised.exception))

    def test_no_connection(self):
        def opener(request, timeout=None):
            raise urllib.error.URLError("no route")
        with self.assertRaises(models.Failed) as raised:
            self.download(opener).run()
        self.assertIn("internet", str(raised.exception))

    def test_an_error_from_the_site(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        with self.assertRaises(models.Failed) as raised:
            self.download(opener).run()
        self.assertIn("503", str(raised.exception))

    def test_nonsense_from_the_site(self):
        with self.assertRaises(models.Failed):
            self.download(lambda request, timeout=None: Reply(b"<html>")).run()
        with self.assertRaises(models.Failed):
            self.download(Site(files={"config.json": b"{}"})).run()  # no model in the list

    def test_file_names_that_would_land_elsewhere_are_left_out(self):
        site = Site(extra=[{"type": "file", "path": "../outside.txt", "size": 1},
                           {"type": "file", "path": "sub/inside.txt", "size": 1}])
        self.download(site).run()
        self.assertEqual(sorted(os.listdir(self.final)), sorted(FILES))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "outside.txt")))


class Removing(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def make(self, name, where=None):
        path = os.path.join(where or self.folder, name)
        os.makedirs(path)
        with open(os.path.join(path, "model.bin"), "wb") as f:
            f.write(b"x" * 10)
        return path

    def test_removes_the_folder_and_anything_half_fetched(self):
        self.make("medium.en")
        self.make("medium.en" + models.PART)
        models.remove(self.folder, "medium.en")
        self.assertEqual(os.listdir(self.folder), [])

    def test_a_link_loses_the_link_only(self):
        elsewhere = tempfile.mkdtemp()
        kept = self.make("big", elsewhere)
        os.symlink(kept, os.path.join(self.folder, "big"))
        self.assertTrue(models.is_installed(self.folder, "big"))
        models.remove(self.folder, "big")
        self.assertFalse(os.path.lexists(os.path.join(self.folder, "big")))
        self.assertTrue(os.path.exists(os.path.join(kept, "model.bin")))

    def test_only_a_plain_name(self):
        self.make("keep")
        for name in ("", ".", "..", "../keep", "a/b", "a\\b", "c:keep"):
            with self.assertRaises(OSError):
                models.remove(self.folder, name)
        self.assertTrue(models.is_installed(self.folder, "keep"))

    def test_removing_what_is_not_there_is_fine(self):
        models.remove(self.folder, "never-was")


class Kinds(unittest.TestCase):
    def test_told_apart_by_their_files(self):
        folder = tempfile.mkdtemp()
        for name, files in (("small.en", ["model.bin"]), ("parakeet", ["encoder.int8.onnx", "tokens.txt"]),
                            ("half", ["encoder.int8.onnx"]), ("empty", [])):
            os.makedirs(os.path.join(folder, name))
            for file in files:
                open(os.path.join(folder, name, file), "w").close()
        self.assertEqual([models.kind(folder, n) for n in ("small.en", "parakeet", "half", "empty", "gone")],
                         ["whisper", "transducer", "", "", ""])
        self.assertTrue(models.is_installed(folder, "parakeet"))
        self.assertFalse(models.is_installed(folder, "half"))
        self.assertEqual([n for n, _ in available_models(folder)], ["small.en", "parakeet"])

    def test_a_transducer_at_either_precision(self):
        folder = tempfile.mkdtemp()
        for name, files in (("packed", ["encoder.int8.onnx", "tokens.txt"]),
                            ("full", ["encoder.onnx", "encoder.weights", "tokens.txt"]),
                            ("both", ["encoder.int8.onnx", "encoder.onnx", "tokens.txt"]),
                            ("no-tokens", ["encoder.onnx"])):
            os.makedirs(os.path.join(folder, name))
            for file in files:
                open(os.path.join(folder, name, file), "w").close()
        self.assertEqual([models.kind(folder, n) for n in ("packed", "full", "both", "no-tokens")],
                         ["transducer", "transducer", "transducer", ""])

        def names(name):
            return {part: os.path.relpath(path, os.path.join(folder, name))
                    for part, path in models.transducer_files(folder, name).items()}

        self.assertEqual(names("packed"), {"encoder": "encoder.int8.onnx", "decoder": "decoder.int8.onnx",
                                           "joiner": "joiner.int8.onnx", "tokens": "tokens.txt"})
        self.assertEqual(names("full"), {"encoder": "encoder.onnx", "decoder": "decoder.onnx",
                                         "joiner": "joiner.onnx", "tokens": "tokens.txt"})
        self.assertEqual(names("both")["encoder"], "encoder.int8.onnx")
        self.assertEqual(models.transducer_files(folder, "no-tokens"), {})
        self.assertEqual(models.transducer_files(folder, "gone"), {})
        self.assertEqual([n for n, _ in available_models(folder)], ["both", "full", "packed"])

    def test_a_transducer_download_needs_its_own_file_in_the_list(self):
        known = models.Known("parakeet", "Someone/parakeet", 1, models.TRANSDUCER)
        folder = tempfile.mkdtemp()
        with self.assertRaises(models.Failed):  # a Whisper listing won't do
            models.Download(known, folder, opener=Site(), free=lambda _: 10 ** 12).run()
        site = Site(files={"encoder.int8.onnx": b"e" * 100, "decoder.int8.onnx": b"d", "joiner.int8.onnx": b"j",
                           "tokens.txt": b"a 0\n"})
        models.Download(known, folder, opener=site, free=lambda _: 10 ** 12).run()
        self.assertEqual(models.kind(folder, "parakeet"), "transducer")

    def test_a_full_precision_download_brings_its_weights_file(self):
        known = models.Known("parakeet-full", "Someone/parakeet-full", 1, models.FULL)
        folder = tempfile.mkdtemp()
        packed = Site(files={"encoder.int8.onnx": b"e", "decoder.int8.onnx": b"d", "joiner.int8.onnx": b"j",
                             "tokens.txt": b"a 0\n"})
        with self.assertRaises(models.Failed):  # the 8-bit build's listing won't do
            models.Download(known, folder, opener=packed, free=lambda _: 10 ** 12).run()
        site = Site(files={"encoder.onnx": b"e" * 10, "encoder.weights": b"w" * 1000, "decoder.onnx": b"d",
                           "joiner.onnx": b"j", "tokens.txt": b"a 0\n"})
        models.Download(known, folder, opener=site, free=lambda _: 10 ** 12).run()
        self.assertEqual(models.kind(folder, "parakeet-full"), "transducer")
        self.assertEqual(os.path.getsize(os.path.join(folder, "parakeet-full", "encoder.weights")), 1000)


class Catalogue(unittest.TestCase):
    def test_names_are_unique_plain_and_described(self):
        names = [known.name for known in models.KNOWN]
        self.assertEqual(len(set(names)), len(names))
        for known in models.KNOWN:
            self.assertTrue(models._plain_name(known.name))
            self.assertNotEqual(model_label(known.name)[1], known.name, known.name)
        orders = [model_label(name)[0] for name in names]
        self.assertEqual(orders, sorted(orders))  # listed smallest first

    def test_sizes_in_words(self):
        self.assertEqual(models.size_text(78e6), "78 MB")
        self.assertEqual(models.size_text(1531e6), "1.5 GB")

    def test_free_space_of_a_folder_not_made_yet(self):
        self.assertGreater(models.free_space(os.path.join(tempfile.mkdtemp(), "not", "yet")), 0)

    def test_room_is_asked_about_before_a_download_is_started(self):
        with tempfile.TemporaryDirectory() as folder:
            known = models.Known("medium.en", "Someone/medium", 1500)
            plenty, little = 1500e6 + models.SPARE + 1, 1500e6 + models.SPARE - 1
            self.assertEqual(models.room_problem(folder, known, free=plenty), "")
            problem = models.room_problem(folder, known, free=little)
            self.assertIn("enough free disk space", problem)
            self.assertIn("1.5 GB", problem)
            # What has arrived already doesn't have to fit a second time.
            os.makedirs(os.path.join(folder, "medium.en" + models.PART))
            with open(os.path.join(folder, "medium.en" + models.PART, "model.bin"), "wb") as f:
                f.truncate(1_000_000_000)
            self.assertEqual(models.room_problem(folder, known, free=600e6 + models.SPARE), "")
            self.assertTrue(models.room_problem(folder, known, free=400e6 + models.SPARE))


class ScoringWhisper(unittest.TestCase):
    """A Whisper model is asked how sure it was only if it has the layers its own
    configuration names: asked otherwise, the library takes the program down."""

    def model(self, folder, layers, heads, version=6):
        os.makedirs(os.path.join(folder, "m"))
        with open(os.path.join(folder, "m", "model.bin"), "wb") as f:
            def string(text):
                f.write(struct.pack("<H", len(text) + 1) + text.encode("utf-8") + b"\0")

            names = ["encoder/layer_0/ffn/weight", "decoder/embeddings/weight"]
            names += [f"decoder/layer_{n}/{part}/weight" for n in range(layers) for part in ("attention", "ffn")]
            f.write(struct.pack("<I", version))
            string("WhisperSpec")
            f.write(struct.pack("<II", 3, len(names)))
            for name in names:
                string(name)
                f.write(struct.pack("<BII", 2, 2, 3))            # two dimensions: 2 by 3
                f.write(struct.pack("<BI", 0, 24) + bytes(24))   # its type, its size, itself
            f.write(struct.pack("<I", 0))
        if heads is not None:
            with open(os.path.join(folder, "m", "config.json"), "w", encoding="utf-8") as f:
                json.dump({"alignment_heads": heads, "lang_ids": []}, f)

    def test_the_layers_are_counted_from_the_model_file(self):
        with tempfile.TemporaryDirectory() as folder:
            self.model(folder, 12, [[6, 1], [11, 3]])
            self.assertEqual(models.whisper_layers(folder, "m"), 12)
            self.assertTrue(models.whisper_can_be_scored(folder, "m"))

    def test_a_model_that_names_layers_it_has_not_got_is_not_asked(self):
        with tempfile.TemporaryDirectory() as folder:
            self.model(folder, 4, [[6, 1], [11, 3]])  # the list of the model it was distilled from
            self.assertEqual(models.whisper_layers(folder, "m"), 4)
            self.assertFalse(models.whisper_can_be_scored(folder, "m"))

    def test_nor_is_one_that_cannot_be_made_out(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(models.whisper_can_be_scored(folder, "m"))       # no such model
            self.model(folder, 12, None)
            self.assertFalse(models.whisper_can_be_scored(folder, "m"))       # it names no layers
        with tempfile.TemporaryDirectory() as folder:
            self.model(folder, 12, [[6, 1]], version=9)
            self.assertIsNone(models.whisper_layers(folder, "m"))             # a layout not known
            self.assertFalse(models.whisper_can_be_scored(folder, "m"))
        with tempfile.TemporaryDirectory() as folder:
            self.model(folder, 12, [[6, 1]])
            with open(os.path.join(folder, "m", "model.bin"), "r+b") as f:
                f.truncate(40)
            self.assertIsNone(models.whisper_layers(folder, "m"))             # cut short


class TwoAtOnce(unittest.TestCase):
    def test_a_model_being_fetched_is_not_fetched_a_second_time_beside_it(self):
        folder = tempfile.mkdtemp()
        first = models.Download(KNOWN, folder, opener=Site(), free=lambda _: 10 ** 12)
        seen = []
        first._run = lambda: seen.append(models.fetching(KNOWN.name)) or "there"
        with models._FETCHING_LOCK:
            models._FETCHING.add(KNOWN.name)
        try:
            with self.assertRaises(models.Failed):
                first.run()
        finally:
            with models._FETCHING_LOCK:
                models._FETCHING.discard(KNOWN.name)
        self.assertEqual((first.run(), seen, models.fetching(KNOWN.name)), ("there", [True], False))


if __name__ == "__main__":
    unittest.main()
