"""Whether what was heard makes sense: a spoken command, or a sign-off, heard as another word.

A recogniser hears sounds and writes the words that sound like them. "Comma" said straight
after "Hi Joe" sounds like "common", and with nothing to tell it otherwise, that is what it
writes: "Hi Joe common". Anyone reading that knows at once that nobody writes it, and that
"Hi Joe," was meant. In the same way "Cheers" said by itself at the end of a letter comes
out as "Chairs". This is that check: would a person write this?

It only ever chooses between readings that sound the same: what was heard, and the spoken
command or the word it sounds like (HEARD_AS). Never a word that wasn't heard, or something
like it. Each reading is typed as it would be (the program's own fitting, after the text
before it), and a small language model says how likely each is as written English. The other
reading is taken only if it is far more likely (MARGIN): "a common mistake", "we have a lot
in common" and "he fell into a coma" stay as they are. So that nothing is held up, a check
is made only where one of those words was heard.

The model: SmolLM2-135M, the base model (Hugging Face, Apache-2.0), in the int8 ONNX build
published by onnx-community, run with onnxruntime: 138 MB, fetched once into the models
folder, from a fixed version of the page it is published on, and checked against the
SHA-256 published for it. About a tenth of a second for each check on a laptop.

Measured on readings made up for it (37, none of them anyone's own dictation): every
spoken comma heard as "common" or "coma" scored at least 9 (natural logarithm) above the
word, and every real "common" or "coma" at most 5.3. MARGIN sits between.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import urllib.request

from . import __version__

FOLDER = "sense-en"                 # in the models folder
SOURCE = ("https://huggingface.co/onnx-community/SmolLM2-135M-ONNX/resolve/"
          "d0ae6834f1df45e0e95b5fdae95e536f9ca7cd3f/")    # a fixed version of the page
FILES = {   # the name kept here: (where it is at SOURCE, its SHA-256, its size)
    "model_int8.onnx": ("onnx/model_int8.onnx",
                        "50ba80511ce74634d232a043b6c37775cca756b826b49d0a4a8eff958c4bbcc9", 135658354),
    "tokenizer.json": ("tokenizer.json",
                       "139d2f4b4919b90953bdd3c0c40c94c9b23074799a766508dc3bf5eb8ab73351", 2053526),
}
MEGABYTES = 138
MARGIN = 7.0          # how much more likely (natural log) the other reading must be
# ...but less for a sign-off said by itself at the start of a line, which is where they are
# said: there "Cheers" scored 4.2 to 9.6 above "Chairs", and anywhere else at most 0.6.
ALONE_MARGIN = 3.5
CONTEXT = 300         # how much of the text before is read with it, in characters
THREADS = 2
REFUSED_FOR = 300.0   # seconds a reading taken back with "scratch that" is not made again

# The spoken commands, and what each is heard as when there is nothing to tell the
# recogniser it was a command. And the sign-offs, by themselves at the end of a letter.
HEARD_AS = {
    "comma": ("common", "commons", "coma", "comer", "karma", "calmer", "commer"),
    "full stop": ("full stuff",),
    "Cheers": ("chairs", "chair's", "jeers", "cheer's"),
}
COMMANDS = ("comma", "full stop")   # (the others are words, which keep the case they had)

_HEARD = {heard: meant for meant, words in HEARD_AS.items() for heard in words}
_FIND = re.compile(r"(?i)(?<![\w'’])(" + "|".join(
    re.escape(h).replace(r"\ ", r"\s+") for h in sorted(_HEARD, key=len, reverse=True))
    + r")(?![\w'’])([.,!?]*)")


def folder(model_dir: str) -> str:
    return os.path.join(model_dir, FOLDER)


def installed(model_dir: str) -> bool:
    """Whether the files are there, each of the size published (a file cut short by a
    power cut is not)."""
    try:
        return all(os.path.getsize(os.path.join(folder(model_dir), name)) == size
                   for name, (_, _, size) in FILES.items())
    except OSError:
        return False


def check(model_dir: str) -> None:
    """Take away any file that isn't the one published, so that it is fetched again: for
    when the model won't load."""
    for name, (_, wanted, _) in FILES.items():
        path = os.path.join(folder(model_dir), name)
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256()
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != wanted:
                os.remove(path)
        except OSError:
            pass


def might_need(raw: str) -> bool:
    """Whether `raw` has one of the words that are checked: if not, nothing is asked."""
    return bool(_FIND.search(raw))


# ---- fetching it -------------------------------------------------------------------------
_fetching = threading.Lock()


def fetch(model_dir: str, progress=lambda done, total: None) -> None:
    """Download the model into the models folder, each file checked against its published
    SHA-256 before it is kept. Raises OSError (or ValueError, if what came was not what
    was asked for) and leaves nothing behind but what was there before."""
    with _fetching:
        if installed(model_dir):
            return
        target = folder(model_dir)
        os.makedirs(target, exist_ok=True)
        total = sum(size for _, _, size in FILES.values())
        import shutil
        if shutil.disk_usage(target).free < total + 50 * 1024 * 1024:
            raise OSError(f"there isn't room for it ({total // (1024 * 1024)} MB) in {target}")
        done = 0
        for name, (path, wanted, size) in FILES.items():
            final = os.path.join(target, name)
            try:
                if os.path.getsize(final) == size:
                    done += size
                    continue                 # (one of another size, cut short, is fetched again)
            except OSError:
                pass
            part = final + ".part"
            digest = hashlib.sha256()
            request = urllib.request.Request(SOURCE + path,
                                             headers={"User-Agent": f"linux-speaking/{__version__}"})
            try:
                with urllib.request.urlopen(request, timeout=60) as reply, open(part, "wb") as out:
                    while True:
                        block = reply.read(256 * 1024)
                        if not block:
                            break
                        out.write(block)
                        digest.update(block)
                        done += len(block)
                        progress(done, total)
                    out.flush()
                    os.fsync(out.fileno())  # all on the disk before it takes the file's name
                if digest.hexdigest() != wanted:
                    raise ValueError(f"{name} as downloaded is not the one published")
                os.replace(part, final)
            finally:
                if os.path.exists(part):
                    os.remove(part)


# ---- the language model --------------------------------------------------------------------
class Scorer:
    """How likely a text is as written English: the sum of the log-probabilities of its
    pieces, each given the ones before it."""

    def __init__(self, model_dir: str, threads: int = THREADS):
        import onnxruntime
        from tokenizers import Tokenizer
        here = folder(model_dir)
        self.tokenizer = Tokenizer.from_file(os.path.join(here, "tokenizer.json"))
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(os.path.join(here, "model_int8.onnx"), options,
                                                    providers=["CPUExecutionProvider"])
        self.past = [(i.name, i.shape[1], i.shape[3]) for i in self.session.get_inputs()
                     if i.name.startswith("past_key_values")]
        self.start = self.tokenizer.token_to_id("<|endoftext|>")

    def logp(self, texts: list) -> list:
        import numpy as np
        ids = [[self.start] + self.tokenizer.encode(t, add_special_tokens=False).ids for t in texts]
        width, rows = max(len(i) for i in ids), len(ids)
        tokens = np.zeros((rows, width), dtype=np.int64)
        mask = np.zeros((rows, width), dtype=np.int64)
        for row, i in enumerate(ids):
            tokens[row, :len(i)] = i
            mask[row, :len(i)] = 1
        feed = {"input_ids": tokens, "attention_mask": mask,
                "position_ids": np.tile(np.arange(width, dtype=np.int64), (rows, 1))}
        for name, heads, size in self.past:          # nothing before: the whole text at once
            feed[name] = np.zeros((rows, heads, 0, size), dtype=np.float32)
        logits = self.session.run(["logits"], feed)[0]
        out = []
        for row, i in enumerate(ids):
            z = logits[row, :len(i) - 1].astype(np.float64)
            z -= z.max(axis=1, keepdims=True)
            z -= np.log(np.exp(z).sum(axis=1, keepdims=True))
            out.append(float(z[np.arange(len(i) - 1), i[1:]].sum()))
        return out


# ---- the readings, and which makes sense ---------------------------------------------------
def readings(raw: str, spoken_off=(), before: str | None = None) -> list:
    """The other readings of `raw`: one for each word in it that sounds like a spoken
    command or a sign-off (HEARD_AS), with that put in its place. [(the reading, what was
    heard there, what it was taken as)]. A command switched off in Settings is not one, nor
    a mark with no word before it on its line, where `before` (the text before the phrase)
    is given: a comma never starts a page or a line. (There the model, with next to nothing
    to read, liked ",": "Common" and a new paragraph at the top of a page was meant.)"""
    from .formatting import BREAKS
    line = re.split("[\n\r" + BREAKS + "]", before)[-1] if before is not None else "x"
    out = []
    for found in _FIND.finditer(raw):
        heard = re.sub(r"\s+", " ", found.group(1).lower())
        meant = _HEARD[heard]
        if meant in spoken_off:
            continue
        if (meant in COMMANDS and not re.search(r"\w", line)
                and not re.search(r"\w", raw[:found.start()])):
            continue
        if meant in COMMANDS:
            # The command, without the recogniser's mark after the word: the command says
            # what the mark is. ("Hi Joe, common." is "Hi Joe, comma".)
            new = meant
            tail = raw[found.end():]
            if tail[:1] not in ("", " "):
                new += " "
        else:
            word = found.group(1)
            new = (meant if word[:1].isupper() else meant.lower()) + found.group(2)
        out.append((raw[:found.start()] + new + raw[found.end():], heard, meant))
    return out


def _plain(text: str) -> str:
    from .formatting import LINE, PARAGRAPH
    return text.replace(PARAGRAPH, "\n\n").replace(LINE, "\n")


class Reader:
    """Rereads a phrase as heard, and gives back the reading that makes sense."""

    def __init__(self, scorer, margin: float = MARGIN):
        self.scorer, self.margin = scorer, margin
        self.refused = {}         # what was heard: until when it is left as it is

    def refuse(self, heard: str, now: float) -> None:
        """A reading taken back straight after it was made: not made again for a while."""
        self.refused[heard] = now + REFUSED_FOR

    def reread(self, raw: str, before: str, render, spoken_off=(), now: float = 0.0) -> tuple:
        """`raw` as heard, or the reading of it that makes far more sense after `before`:
        (the phrase, what was heard and what it was taken as, or None). `render(phrase)` is
        the text as it would stand after the phrase was typed (the text before it with the
        phrase fitted on), from which the end is read."""
        choices = [(r, h, m) for r, h, m in readings(raw, spoken_off, before)
                   if self.refused.get(h, 0.0) <= now]
        if not choices:
            return raw, None
        start = max(0, len(before) - CONTEXT)
        if start:
            space = before.find(" ", start)
            start = space + 1 if 0 <= space < len(before) - 1 else start
        texts = [_plain(render(raw)[start:])] + [_plain(render(r)[start:]) for r, _, _ in choices]
        scores = self.scorer.logp(texts)
        from .formatting import LINE, PARAGRAPH
        line_start = bool(before.strip()) and before.rstrip(" \t")[-1:] in ("\n", "\r", LINE, PARAGRAPH)
        taken = []
        for i, (reading, heard, meant) in enumerate(choices, 1):
            need = self.margin
            if (meant not in COMMANDS and line_start
                    and re.fullmatch(r"(?i)\W*" + re.escape(heard) + r"\W*", raw.strip())):
                need = min(need, ALONE_MARGIN)
            if scores[i] - scores[0] >= need:
                taken.append((scores[i], reading, heard, meant))
        if not taken:
            return raw, None
        _, reading, heard, meant = max(taken)
        return reading, (heard, meant)
