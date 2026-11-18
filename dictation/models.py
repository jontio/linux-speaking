"""Speech models: the ones that can be fetched, fetching one, and removing one.

Models come from Hugging Face, in the form faster-whisper reads. One is fetched into
"<name>.part" beside the others and renamed when every file is there and checked. So a
half-fetched model is never offered for dictation, and a download that was interrupted
carries on from where it stopped.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import struct
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

SITE = "https://huggingface.co"
PART = ".part"
SKIPPED = frozenset({".gitattributes", "README.md"})
BLOCK = 256 * 1024
SPARE = 200 * 1000 * 1000  # disk space that is left alone
TIMEOUT = 30


WHISPER = "model.bin"               # the file that marks a folder as a Whisper model
TRANSDUCER = "encoder.int8.onnx"    # and as a transducer, such as Parakeet: see engine.py
FULL = "encoder.onnx"               # a transducer at full precision: its numbers as they were
                                    # trained, not rounded to eight bits each. Four times the size.
TRANSDUCERS = (TRANSDUCER, FULL)


@dataclass(frozen=True)
class Known:
    name: str       # the folder it is kept in, and faster-whisper's own name for it
    source: str     # where on Hugging Face
    megabytes: int  # the size of the download
    marker: str = WHISPER  # the file that has to be there for it to count as installed


KNOWN = (
    Known("tiny.en", "Systran/faster-whisper-tiny.en", 78),
    Known("base.en", "Systran/faster-whisper-base.en", 148),
    Known("distil-small.en", "Systran/faster-distil-whisper-small.en", 336),
    Known("small.en", "Systran/faster-whisper-small.en", 486),
    Known("distil-medium.en", "Systran/faster-distil-whisper-medium.en", 792),
    Known("medium.en", "Systran/faster-whisper-medium.en", 1531),
    Known("distil-large-v3", "Systran/faster-distil-whisper-large-v3", 1517),
    Known("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1622),
    Known("large-v3", "Systran/faster-whisper-large-v3", 3091),
    # NVIDIA's Parakeet, as converted for sherpa-onnx by that project: TDT 0.6b v2
    # (CC BY 4.0) and the newer Unified 0.6b (NVIDIA Open Model License). "-full" is the
    # same recogniser at full precision.
    Known("parakeet-tdt-0.6b-v2", "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8", 661,
          TRANSDUCER),
    Known("parakeet-tdt-0.6b-v2-full", "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2", 2513,
          FULL),
    Known("parakeet-unified-en-0.6b",
          "csukuangfj2/sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming", 663,
          TRANSDUCER),
    Known("parakeet-unified-en-0.6b-full",
          "csukuangfj2/sherpa-onnx-nemo-parakeet-unified-en-0.6b-non-streaming", 2515, FULL),
)
BY_NAME = {known.name: known for known in KNOWN}


_FETCHING, _FETCHING_LOCK = set(), threading.Lock()  # the models being fetched just now


def fetching(name: str) -> bool:
    """Whether this model is being fetched at the moment, by any window."""
    with _FETCHING_LOCK:
        return name in _FETCHING


class Cancelled(Exception):
    """The download was stopped on purpose."""


class Failed(Exception):
    """The download could not be finished. The message is for the person to read."""


def size_text(nbytes: float) -> str:
    megabytes = nbytes / 1e6
    return f"{megabytes / 1000:.1f} GB" if megabytes >= 1000 else f"{round(megabytes)} MB"


def kind(model_dir: str, name: str) -> str:
    """"whisper", "transducer", or "" if the folder holds no model."""
    folder = os.path.join(model_dir, name)
    if os.path.exists(os.path.join(folder, WHISPER)):
        return "whisper"
    if transducer_files(model_dir, name):
        return "transducer"
    return ""


def transducer_files(model_dir: str, name: str) -> dict:
    """The files of the transducer kept as `name`, by what each is for: those of the
    8-bit build if it is there, else of the full one. Empty if there is no transducer."""
    folder = os.path.join(model_dir, name)
    if os.path.exists(os.path.join(folder, "tokens.txt")):
        for marker in TRANSDUCERS:
            if os.path.exists(os.path.join(folder, marker)):
                ending = marker[len("encoder"):]
                return {"tokens": os.path.join(folder, "tokens.txt"),
                        **{part: os.path.join(folder, part + ending)
                           for part in ("encoder", "decoder", "joiner")}}
    return {}


def whisper_layers(model_dir: str, name: str):
    """How many decoder layers the Whisper model kept as `name` has, read from the names
    of the numbers in its model file. None if that can't be told."""
    try:
        with open(os.path.join(model_dir, name, WHISPER), "rb") as f:
            def number(kind: str) -> int:
                return struct.unpack("<" + kind, f.read(struct.calcsize("<" + kind)))[0]

            def string() -> str:
                return f.read(number("H"))[:-1].decode("utf-8")

            if not 4 <= number("I") <= 6:  # the layouts this was written for
                return None
            string()      # what kind of model
            number("I")   # and its revision
            count = number("I")
            if count > 100_000:
                return None
            layers = set()
            for _ in range(count):
                named = re.match(r"decoder/layer_(\d+)/", string())
                f.seek(4 * number("B") + 1, os.SEEK_CUR)  # its shape and its type
                f.seek(number("I"), os.SEEK_CUR)          # the numbers themselves
                if named:
                    layers.add(int(named.group(1)))
            return max(layers) + 1 if layers else None
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return None


def whisper_can_be_scored(model_dir: str, name: str) -> bool:
    """Whether a Whisper model can safely be asked to score words against sound, which is
    how it says how sure it was of each (see the voice test).

    The scoring reads particular decoder layers, named in the model's config.json. Some
    converted models name layers they don't have: a Distil model with the list of the
    model it was distilled from. The library doesn't notice, and the program dies. So
    the answer is yes only when every layer named is known to be there.
    """
    try:
        with open(os.path.join(model_dir, name, "config.json"), encoding="utf-8") as f:
            heads = json.load(f).get("alignment_heads")
        named = [int(layer) for layer, _ in heads]
    except (OSError, ValueError, TypeError):
        return False
    layers = whisper_layers(model_dir, name)
    return bool(named) and layers is not None and 0 <= min(named) and max(named) < layers


def is_installed(model_dir: str, name: str) -> bool:
    return bool(kind(model_dir, name))


def transducers_usable() -> bool:
    """Whether the library that runs Parakeet is installed."""
    import importlib.util
    return importlib.util.find_spec("sherpa_onnx") is not None


def part_size(model_dir: str, name: str) -> int:
    """How much of a model has been fetched so far, in bytes. 0 if none."""
    return folder_size(os.path.join(model_dir, name + PART))


def folder_size(path: str) -> int:
    try:
        return sum(_size(os.path.join(path, name)) for name in os.listdir(path))
    except OSError:
        return 0


def free_space(model_dir: str) -> int:
    """Bytes free on the disk the models are kept on."""
    path = model_dir
    while path and not os.path.exists(path):
        path = os.path.dirname(path)
    try:
        return shutil.disk_usage(path or ".").free
    except OSError:
        return 0


def room_problem(model_dir: str, known: Known, free=None) -> str:
    """Why a model can't be downloaded for want of disk space, or "" if there is room.
    Asked before a download is started, so that the answer comes at once and not after
    the download site has been asked what there is; the download checks again, exactly."""
    needed = known.megabytes * 1e6 - part_size(model_dir, known.name)
    free = free_space(model_dir) if free is None else free
    if needed > 0 and free < needed + SPARE:
        return ("There isn't enough free disk space: this model needs about "
                f"{size_text(needed)} more, and {size_text(free)} is free.")
    return ""


def remove(model_dir: str, name: str) -> None:
    """Remove a model, and anything half-fetched of it. Raises OSError if it can't be.

    A model that is only a link to one kept elsewhere loses the link, not the model.
    """
    if not _plain_name(name):
        raise OSError(f"not a model's name: {name!r}")
    _delete(os.path.join(model_dir, name))
    discard_part(model_dir, name)


def discard_part(model_dir: str, name: str) -> None:
    """Throw away what has been fetched of a model that isn't finished."""
    if not _plain_name(name):
        raise OSError(f"not a model's name: {name!r}")
    _delete(os.path.join(model_dir, name + PART))


class Download:
    """Fetches one model. run() does the work, on whichever thread calls it."""

    def __init__(self, known: Known, model_dir: str, progress=None, opener=None, free=None):
        self.known = known
        self.model_dir = model_dir
        self._progress = progress or (lambda done, total: None)
        self._opener = opener or urllib.request.urlopen
        self._free = free or free_space
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Stop soon. run() then raises Cancelled. What was fetched is kept."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> str:
        """Fetch the model and return its folder. Raises Cancelled or Failed."""
        with _FETCHING_LOCK:
            if self.known.name in _FETCHING:
                # Two at once would write into the same half-fetched folder.
                raise Failed("This model is already being fetched, from another window.")
            _FETCHING.add(self.known.name)
        try:
            return self._run()
        finally:
            with _FETCHING_LOCK:
                _FETCHING.discard(self.known.name)

    def _run(self) -> str:
        final = os.path.join(self.model_dir, self.known.name)
        if is_installed(self.model_dir, self.known.name):
            return final
        part = final + PART
        try:
            files = self._list()
            self._check()                 # paused while the list was being asked for
            total = sum(size for _, size, _ in files)
            os.makedirs(part, exist_ok=True)
            have = sum(min(_size(os.path.join(part, path)), size) for path, size, _ in files)
            if self._free(self.model_dir) < total - have + SPARE:
                raise Failed("There isn't enough free disk space: this model needs "
                             f"{size_text(total - have)} more.")
            done = 0
            for path, size, digest in files:
                self._fetch(path, size, digest, os.path.join(part, path), done, total)
                done += size
            _delete(final)  # an empty or broken folder of the same name
            os.replace(part, final)
            return final
        except (Cancelled, Failed):
            raise
        except urllib.error.HTTPError as e:
            raise Failed(f"The download site answered with an error ({e.code}). "
                         "Try again later.") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.HTTPException) as e:
            raise Failed("The download site could not be reached, or the connection was "
                         "lost. Check the internet connection and try again: it carries "
                         "on from where it stopped.") from e
        except ValueError as e:
            raise Failed("The download site's answer could not be understood.") from e
        except OSError as e:
            raise Failed(f"The model could not be saved: {e.strerror or e}") from e

    def _list(self) -> list:
        """(file name, size, SHA-256 or "") for each file of the model."""
        with self._open(f"{SITE}/api/models/{self.known.source}/tree/main") as reply:
            entries = json.loads(reply.read().decode("utf-8"))
        files = []
        for entry in entries:
            path = str(entry.get("path", ""))
            if entry.get("type") != "file" or path in SKIPPED or not _plain_name(path):
                continue  # only plain files, and never one that would land outside the folder
            files.append((path, int(entry.get("size", 0)), (entry.get("lfs") or {}).get("oid", "")))
        if not any(path == self.known.marker for path, _, _ in files):
            raise Failed("The download site did not list this model's files.")
        return files

    def _fetch(self, path: str, size: int, digest: str, dest: str, done: int, total: int) -> None:
        self._check()                     # before each file is asked for, too
        have = _size(dest)
        if have > size:
            os.remove(dest)
            have = 0
        if have < size:
            headers = {"Range": f"bytes={have}-"} if have else {}
            url = f"{SITE}/{self.known.source}/resolve/main/{path}"
            with self._open(url, headers) as reply:
                carried_on = bool(have) and getattr(reply, "status", 200) == 206
                if not carried_on:
                    have = 0  # the whole file is coming, from the start
                with open(dest, "ab" if carried_on else "wb") as out:
                    while True:
                        self._check()
                        block = reply.read(BLOCK)
                        if not block:
                            break
                        out.write(block)
                        have += len(block)
                        self._progress(done + min(have, size), total)
            if have != size:
                raise Failed("The download stopped early. Try again: it carries on from "
                             "where it stopped.")
        self._progress(done + size, total)
        if digest and _sha256(dest, self._check) != digest:
            os.remove(dest)
            raise Failed("The download was damaged on the way. Try again.")

    def _open(self, url: str, headers: dict | None = None):
        request = urllib.request.Request(
            url, headers={"User-Agent": f"linux-speaking/{__version__}", **(headers or {})})
        return self._opener(request, timeout=TIMEOUT)

    def _check(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()


def _plain_name(name: str) -> bool:
    """Whether `name` is one file or folder name, with no path in it."""
    return bool(name) and name not in (".", "..") and not any(c in name for c in '/\\:')


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _delete(path: str) -> None:
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _sha256(path: str, check=lambda: None) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            check()
            block = f.read(4 * 1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)
