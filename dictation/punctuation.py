"""Deciding, from the words, whether a sentence ended where a phrase ended.

What decides is a small punctuation model made for speech recognition: sherpa-onnx's English
online punctuation and casing model (a CNN-BiLSTM by frankyoujian, "Edge-Punct-Casing",
Apache-2.0; arXiv 2407.13142), trained on Wikipedia and on interview, podcast and TED talk
transcripts. It is 7.6 MB and gives, after each word of what it is shown, how likely a comma,
a full stop or a question mark is to follow. See joins.py for where it is used.

It is run here with onnxruntime directly, rather than through sherpa-onnx's own class, which
gives only its best guess and not how sure it is. The words are cut into pieces exactly as
sherpa-onnx 2.0.1 cuts them (SentencePiece: the best-scoring way through the bytes of each
word), and the model is given them as sherpa-onnx gives them; the two were compared on
5,006 texts, 251,610 words, and gave the same marks for every one. (sherpa-onnx 2.0.1 also
crashes on a single word of some 200 pieces; a word of more than 24 here is shown to the
model as one unknown piece.)

How its answer is used: the model is shown the 30 words before the join and the phrase after
it (12 words at most), in small letters and without marks, and only what it says at the
join is read. Then:

- where the recogniser wrote a full stop, a question mark or an exclamation mark, it stays
  unless the model gives a sentence end there less than 5 in 100; then a comma, if the model
  is sure of one (80 in 100), else nothing. A full stop becomes a question mark where the
  model is 20 in 100 surer of that.
- where the recogniser wrote none, a full stop (or a question mark) goes in if the model gives
  one 50 in 100 or more; else the recogniser's comma, colon or semicolon stays, or a comma
  goes in if the model gives one 50 in 100.

The numbers were first set on half of a set of dictation (the user's 300 recorded sentences
heard by his own recogniser, cut at his pauses and mid-clause; 196 dictation-style passages;
60 passages of book dialogue; 481 sessions in all) and checked on the other half: with the
recogniser's stop kept from 15 in 100, sentence ends at pauses were right 89.5 times in 100
against 48.8 with the recogniser's own stops kept, the stray full stops at pauses in the
middle of a clause fell from 82 in 100 to under 3, and mistakes in marks and capitals fell
from 15 to 5.4 in 100 words. But it took the stop away at one real sentence end in six, and
in natural dictation, with its long sentences, that made run-on sentences. From 5 in 100
(over 2,729 pauses where the recogniser wrote a stop) it takes it away at one real end in
eleven, and keeps 15 in 100 of the stops at pauses in mid-sentence, where it kept 10. A
decision takes a few thousandths of a second.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import tarfile
import threading
import urllib.request

from . import __version__, joins

FOLDER = "punctuation-en"          # in the models folder
FILES = {                          # what is needed, and what each must be
    "model.int8.onnx": "9d611f445fe4a46186080fe161be6059d87d72eb88d3a8cb00c1a06e83a6067e",
    "bpe.vocab": "e118b7ad88c54db562517df49e1cffd4836d166c34fb190fd311d7f34eb238f5",
}
ARCHIVE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/"
           "sherpa-onnx-online-punct-en-2024-08-06.tar.bz2")
ARCHIVE_SHA256 = "9f5e5a72c7d2829635bd074fce92b6bbd5b78da8a52e7ad8ed1be933f366b99d"
ARCHIVE_MEGABYTES = 31
IN_ARCHIVE = "./sherpa-onnx-online-punct-en-2024-08-06/"   # as the names stand in it

# The rule, as set on the dictation described above.
KEEP = 0.05          # keep the recogniser's sentence end if P(. or ?) is at least this
COMMA = 0.8          # where its end is taken away: a comma if P(,) is at least this
COMMA_ADDED = 0.5    # where it wrote none: a comma if P(,) is at least this
ADD = 0.5            # where it wrote none: a sentence end if P(. or ?) is at least this
QUESTION = 0.2       # a full stop kept becomes "?" if P(?) is this much more than P(.)
LEFT_WORDS, RIGHT_WORDS, MOST_TOKENS = 30, 12, 150
MOST_PIECES = 24     # a word of more pieces than this is shown as one unknown piece

_MAX_ROW = 200       # sherpa-onnx's longest row of pieces


def folder(model_dir: str) -> str:
    return os.path.join(model_dir, FOLDER)


def installed(model_dir: str) -> bool:
    return all(os.path.isfile(os.path.join(folder(model_dir), name)) for name in FILES)


def check(model_dir: str) -> None:
    """Take away any file that isn't the one published, so that it is fetched again: for
    when the model won't load (a file cut short by a power cut, say)."""
    for name, wanted in FILES.items():
        path = os.path.join(folder(model_dir), name)
        try:
            with open(path, "rb") as f:
                if hashlib.sha256(f.read()).hexdigest() != wanted:
                    os.remove(path)
        except OSError:
            pass


# ---- fetching it -------------------------------------------------------------------------
_fetching = threading.Lock()


def fetch(model_dir: str, progress=lambda done, total: None) -> None:
    """Download the model into the models folder: the release archive from sherpa-onnx's
    own page, checked against its published SHA-256, and the two files needed taken out of
    it and checked again. Raises OSError (or ValueError, if what came was not what was
    asked for) and leaves nothing behind but what was there before."""
    with _fetching:
        if installed(model_dir):
            return
        target = folder(model_dir)
        made = not os.path.isdir(target)
        os.makedirs(target, exist_ok=True)   # (a folder that can't be written to is found
        try:                                 # out before the download, not after it)
            _fetch_into(target, progress)
        except BaseException:
            if made:
                shutil.rmtree(target, ignore_errors=True)
            raise


def _fetch_into(target: str, progress) -> None:
    request = urllib.request.Request(ARCHIVE, headers={"User-Agent": f"linux-speaking/{__version__}"})
    data, digest = io.BytesIO(), hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as reply:
        total = int(reply.headers.get("Content-Length") or 0)
        while True:
            block = reply.read(256 * 1024)
            if not block:
                break
            data.write(block)
            digest.update(block)
            progress(data.tell(), total)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("the punctuation model that was downloaded is not the one published")
    data.seek(0)
    with tarfile.open(fileobj=data, mode="r:bz2") as archive:
        for name, wanted in FILES.items():
            member = archive.getmember(IN_ARCHIVE + name)
            if not member.isfile():
                raise ValueError(f"{name} in the archive is not a plain file")
            content = archive.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != wanted:
                raise ValueError(f"{name} in the archive is not the one published")
            part = os.path.join(target, name + ".part")
            try:
                with open(part, "wb") as out:
                    out.write(content)
                    out.flush()
                    os.fsync(out.fileno())   # all on the disk before it takes the name
                os.replace(part, os.path.join(target, name))
            finally:
                if os.path.exists(part):
                    os.remove(part)


# ---- cutting words into the model's pieces, as sherpa-onnx does ---------------------------
class Pieces:
    """SentencePiece as sherpa-onnx 2.0.1 does it (simple-sentencepiece v0.7): the best-scoring
    way through the bytes of "▁" + the word, the scores added in single precision, a tie going
    to the shorter piece, and one unknown piece for each byte no piece covers."""

    def __init__(self, path: str):
        import numpy as np
        self.np = np
        tokens, scores, unknown = [], [], 0
        with open(path, "rb") as f:
            for line in f.read().split(b"\n"):
                parts = line.split()
                if not parts:
                    continue
                if len(parts) < 2:
                    raise ValueError("the punctuation model's word pieces could not be read")
                if parts[0] == b"<unk>":
                    unknown = len(tokens)
                tokens.append(parts[0])
                scores.append(np.float32(float(parts[1])))
        self.index = {}
        for i, piece in enumerate(tokens):
            self.index.setdefault(piece, i)
        self.scores, self.unknown = scores, unknown
        self.longest = max(len(piece) for piece in tokens)
        self.known = {}

    def of(self, word: bytes) -> tuple:
        found = self.known.get(word)
        if found is not None:
            return found
        np = self.np
        s = "▁".encode() + word
        n = len(s)
        nothing, zero = np.float32(-np.inf), np.float32(0.0)
        score, end, which = [zero] * (n + 1), [0] * (n + 1), [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            best, best_end, best_id = nothing, -1, 0
            for length in range(1, min(self.longest, n - i) + 1):
                piece = self.index.get(s[i:i + length])
                if piece is None:
                    continue
                total = self.scores[piece] + score[i + length]
                if total > best:
                    best, best_end, best_id = total, i + length, piece
                elif total == best and best_end >= i + length:
                    best_end, best_id = i + length, piece
            score[i] = zero if best == nothing else best
            end[i], which[i] = best_end, best_id
        ids, i = [], 0
        while i < n:
            if end[i] == -1:
                ids.append(self.unknown)
                i += 1
            else:
                ids.append(which[i])
                i = end[i]
        found = tuple(ids)
        if len(self.known) > 100000:
            self.known.clear()
        self.known[word] = found
        return found


class Model:
    """The punctuation model: how likely none, a comma, a full stop and a question mark are
    after each word."""

    def __init__(self, model_dir: str, threads: int = 1):
        import numpy as np
        import onnxruntime
        self.np = np
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = threads
        options.log_severity_level = 3
        here = folder(model_dir)
        self.session = onnxruntime.InferenceSession(os.path.join(here, "model.int8.onnx"), options,
                                                    providers=["CPUExecutionProvider"])
        self.pieces = Pieces(os.path.join(here, "bpe.vocab"))

    def pieces_of(self, word: str) -> int:
        return len(self.pieces.of(word.encode("utf-8")))

    def probabilities(self, words: list) -> list:
        """For each word (no spaces in any), [P(none), P(comma), P(full stop), P(question)]
        after it. As sherpa-onnx makes the rows: <s> ... </s>, a new row before a word
        would take one past 199 pieces; the rows are padded only as far as the longest (the
        model looks no more than three pieces either way, so the answers are the same)."""
        np = self.np
        rows, tokens, valid = [], [1], [1]
        for word in words:
            ids = self.pieces.of(word.encode("utf-8"))
            if len(tokens) + len(ids) > _MAX_ROW - 1:
                rows.append((tokens + [2], valid + [1]))
                tokens, valid = [1], [1]
            tokens.extend(ids)
            valid.extend([1] + [0] * (len(ids) - 1))
        rows.append((tokens + [2], valid + [1]))
        width = min(_MAX_ROW, max(len(t) for t, _ in rows) + 3)
        token_ids = np.zeros((len(rows), width), dtype=np.int32)
        valid_ids = np.zeros((len(rows), width), dtype=np.int32)
        lengths = np.zeros((len(rows),), dtype=np.int32)
        for i, (t, v) in enumerate(rows):
            token_ids[i, :len(t)] = t
            valid_ids[i, :len(v)] = v
            lengths[i] = sum(v)
        _, punct, _ = self.session.run(None, {"token_ids": token_ids, "valid_ids": valid_ids,
                                             "label_lens": lengths})
        punct = punct - punct.max(axis=1, keepdims=True)
        chances = np.exp(punct)
        chances /= chances.sum(axis=1, keepdims=True)
        return [list(map(float, row)) for row in chances]


# ---- the words the model is shown ----------------------------------------------------------
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'"})
_WORD = re.compile(r"\S+")


def model_words(word: str) -> list:
    """What the model is shown for one typed word: small letters, apostrophes inside words
    kept, other marks and signs taken out; "Wi-Fi" is two words, "wi fi". A word of signs
    alone is one unknown piece."""
    parts = re.split(r"[^a-z0-9']+", word.lower().translate(_APOSTROPHES))
    return [part.strip("'") for part in parts if part.strip("'")] or ["<unk>"]


class WordsDecider(joins.Decider):
    """Decides each join from the words around it, with the model above."""

    name = "the punctuation model"

    def __init__(self, model: Model):
        self.model = model

    def _guarded(self, words: list) -> list:
        return [w if self.model.pieces_of(w) <= MOST_PIECES else "<unk>" for w in words]

    def chances(self, before: str, phrase: str) -> list:
        """[P(none), P(comma), P(full stop), P(question)] at the join between `before` and
        `phrase`; None if there are no words on one side."""
        # The last 30 words typed before the join, and the first 12 of the phrase, each as
        # the model is to see it; the oldest typed words go first if it is too long.
        left = [self._guarded(model_words(w)) for w in _WORD.findall(before)[-LEFT_WORDS:]]
        right = [w for typed in _WORD.findall(phrase)[:RIGHT_WORDS]
                 for w in self._guarded(model_words(typed))]
        if not left or not right:
            return None
        budget = MOST_TOKENS - 2 - sum(self.model.pieces_of(w) for w in right)
        total = sum(self.model.pieces_of(w) for words in left for w in words)
        while len(left) > 1 and total > budget:
            total -= sum(self.model.pieces_of(w) for w in left.pop(0))
        flat = [w for words in left for w in words]
        return self.model.probabilities(flat + right)[len(flat) - 1]

    def decide(self, before: str, phrase: str, held: str) -> str:
        found = self.chances(before, phrase)
        if found is None:
            return held
        _, comma, stop, question = found
        ending = stop + question
        if held in joins.ENDS:
            if ending >= KEEP:
                return "?" if held == "." and question - stop >= QUESTION else held
            return "," if comma >= COMMA else ""
        if ending >= ADD:
            return "?" if question > stop else "."
        if held in (",", ":", ";"):
            return held
        return "," if comma >= COMMA_ADDED else ""
