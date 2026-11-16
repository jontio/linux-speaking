import hashlib
import io
import json
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

    def test_a_transducer_download_needs_its_own_file_in_the_list(self):
        known = models.Known("parakeet", "Someone/parakeet", 1, models.TRANSDUCER)
        folder = tempfile.mkdtemp()
        with self.assertRaises(models.Failed):  # a Whisper listing won't do
            models.Download(known, folder, opener=Site(), free=lambda _: 10 ** 12).run()
        site = Site(files={"encoder.int8.onnx": b"e" * 100, "decoder.int8.onnx": b"d", "joiner.int8.onnx": b"j",
                           "tokens.txt": b"a 0\n"})
        models.Download(known, folder, opener=site, free=lambda _: 10 ** 12).run()
        self.assertEqual(models.kind(folder, "parakeet"), "transducer")


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


if __name__ == "__main__":
    unittest.main()
