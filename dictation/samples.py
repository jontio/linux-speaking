"""Samples of dictation as it is really done, for working out where its punctuation goes.

Sentences read aloud (reading.py) are read in one breath, and a pause in them falls where
the text has a comma. Real dictation is not like that: people stop to think in the middle
of a sentence, and the recogniser, which hears each phrase by itself, puts a full stop
there. To find out what is right at such a pause, the program needs to hear the person
dictate as they do, and to be told what they meant.

So: in the window for it (tray.SamplesWindow), the person dictates something, an email or
a message, as they naturally would, into a box; then puts the text in the box right, to
what they meant; then keeps it. Each phrase's sound is kept, with what the recogniser
wrote for it, when it ended and how long it was; and the text as it was put right. All on
this computer, in a folder of its own (FOLDER): nothing is sent anywhere, and the folder
can be deleted at any time. scripts/check_punctuation.py then plays the samples through
the program's own typing, each way it can put full stops (joins.py), and says how often
each was right.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import wave

from . import config

FOLDER = os.path.join(os.path.dirname(config.STATE_FILE), "samples")
SAMPLE = "sample.json"


class Recording:
    """The phrases dictated into the samples box since it was last kept or cleared."""

    def __init__(self, folder: str = FOLDER):
        self.folder = folder
        self.phrases = []          # [(sound, what was written, when it ended, how long it was)]

    def add(self, sound, written: str, ended: float, seconds: float) -> None:
        """One phrase: its sound (numbers from -1 to 1 at config.RATE), what the recogniser
        wrote for it, when (time.monotonic) it was taken to be over, and its length."""
        self.phrases.append((sound, written, float(ended), float(seconds)))

    def clear(self) -> None:
        self.phrases = []

    def keep(self, meant: str, details: dict | None = None) -> str:
        """Keep the phrases with `meant`, the text as the person put it right. Returns the
        folder they are kept in. Each phrase is a sound file, and sample.json says what was
        written for each, how long the pause before it was, and what was meant. Only the
        person's own account can read them. Raises OSError, keeping nothing, if it can't."""
        day = time.strftime("%Y-%m-%d")
        for place in (self.folder, os.path.join(self.folder, day)):
            os.makedirs(place, mode=0o700, exist_ok=True)
            _for_its_owner(place)
        taken = {name for name in os.listdir(os.path.join(self.folder, day))}
        number = 1
        while f"{number:03d}" in taken:
            number += 1
        here = os.path.join(self.folder, day, f"{number:03d}")
        # Written into a folder of its own and put in place when it is whole, so that a
        # sample that can't be kept (a full disk) leaves nothing of the person's voice behind.
        part = here + ".part"
        shutil.rmtree(part, ignore_errors=True)
        os.makedirs(part, mode=0o700)
        try:
            self._write(part, meant, details)
            os.replace(part, here)
        except BaseException:
            shutil.rmtree(part, ignore_errors=True)
            raise
        self.clear()
        return here

    def _write(self, here: str, meant: str, details) -> None:
        import numpy as np
        phrases, previous_end = [], None
        for i, (sound, written, ended, seconds) in enumerate(self.phrases, 1):
            name = f"phrase-{i:02d}.wav"
            samples = (np.clip(np.asarray(sound, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
            with os.fdopen(_private(os.path.join(here, name)), "wb") as raw, wave.open(raw, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.RATE)
                w.writeframes(samples.tobytes())
            # The pause before a phrase: from the end of the one before to this one's start.
            # (Each phrase's sound runs on a moment past its last word, as dictation cuts it.)
            started = ended - seconds
            pause = None if previous_end is None else round(max(0.0, started - previous_end), 2)
            phrases.append({"sound": name, "written": written, "seconds": round(seconds, 2),
                            "pause_before": pause})
            previous_end = ended
        record = {"meant": meant, "phrases": phrases, "kept": time.strftime("%Y-%m-%d %H:%M:%S"),
                  **(details or {})}
        with os.fdopen(_private(os.path.join(here, SAMPLE)), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)


def _private(path: str) -> int:
    """A new file only its owner can read: the person's voice, and what they wrote."""
    return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)


def _for_its_owner(folder: str) -> None:
    """A samples folder closed to other accounts, as the noises kept are (see speech.py)."""
    try:
        if os.name == "posix" and os.stat(folder).st_mode & 0o077:
            os.chmod(folder, 0o700)
    except OSError:
        pass


def kept(folder: str = FOLDER) -> list:
    """The samples kept, oldest first: [(their folder, what sample.json says), ...]."""
    found = []
    if not os.path.isdir(folder):
        return found
    for day in sorted(os.listdir(folder)):
        here = os.path.join(folder, day)
        if not os.path.isdir(here):
            continue
        for number in sorted(os.listdir(here)):
            path = os.path.join(here, number, SAMPLE)
            try:
                with open(path, encoding="utf-8") as f:
                    found.append((os.path.dirname(path), json.load(f)))
            except (OSError, ValueError):
                continue
    return found


def forget(folder: str = FOLDER, only: str = "") -> None:
    """Delete every sample, or with `only`, just the sample kept in that folder (and the
    day's folder with it, if that leaves it empty)."""
    if only:
        shutil.rmtree(only, ignore_errors=True)
        day = os.path.dirname(only)
        try:
            if os.path.isdir(day) and not os.listdir(day):
                os.rmdir(day)
        except OSError:
            pass
        return
    shutil.rmtree(folder, ignore_errors=True)


# ---- playing samples back through the program's typing --------------------------------------
class Page:
    """A page that is typed into, in memory: it answers what the programs dictation goes
    into answer (see targets.py), for as much as typing a sample needs."""

    name = "a sample"
    other = None

    def __init__(self):
        self.text, self.steps = "", []

    def describe(self):
        return self.name

    def pick(self):
        pass

    def request(self, message: dict) -> dict:
        op, name = message.get("op"), message.get("name", "")
        if op == "context":
            return {"ok": True, "before": self.text[-2000:], "after": ""}
        if op == "insert":
            cut = len(self.text) - int(message.get("delete_before", 0))
            self.steps.append(self.text[:cut])
            self.text = self.text[:cut] + message.get("text", "")
            return {"ok": True}
        if op == "command" and name in ("scratch", "undo"):
            if not self.steps:
                return {"ok": False, "why": "nothing to take back"}
            self.text = self.steps.pop()
            return {"ok": True}
        if op == "command" and name in ("new_line", "new_paragraph", "press_enter"):
            self.steps.append(self.text)
            self.text += "\n" if name == "new_line" else "\n\n"
            return {"ok": True}
        return {"ok": False, "why": "unknown command"}


def replay(written: list, sentence_ends: str, decider=None, words=(), lexicon=None,
           reader=None) -> str:
    """The text the program would type for phrases written as `written`, one after another,
    with full stops put as `sentence_ends` says (see joins.py), and the end of the last
    sentence finished as going to sleep would. `decider` decides joins for "words";
    `reader` (sense.Reader) checks what was heard makes sense."""
    import queue
    import threading
    from .engine import Engine
    from .settings import Settings
    from .status import State, Status
    from . import tidy
    page = Page()
    engine = Engine.__new__(Engine)
    engine.status = Status()
    engine.status.state = State.AWAKE
    engine.settings = Settings()
    engine.settings.sentence_ends = sentence_ends
    engine.settings.words = tuple(words)
    engine.settings.states["hear_again"] = False      # no sound is heard again in a replay
    engine.targets = page
    engine._selected_that, engine._explained_at, engine._choice_timer = False, -60.0, None
    engine.on_change = engine.on_level = lambda: None
    engine.on_event = lambda name: None
    engine.on_notice = lambda text, kind="info": None
    engine._told, engine._standing = {}, {}
    engine._mail, engine.share_problem = None, ""
    engine.lexicon, engine.keep_final = lexicon, False
    engine._typed_sound = engine._heard_sound = None
    engine._holds, engine._running, engine._recorder = 0, True, None
    engine._lock = threading.Lock()
    engine._phrases = queue.Queue()
    engine._load_tried, engine._transcriber, engine._offload = 0.0, None, None
    engine._run, engine._runs, engine._last_tidy, engine._refused = None, [], None, tidy.Refused()
    engine._decider = decider
    engine._deciding = engine._decider_failed = True   # never fetch or load a model in a replay
    engine._sense, engine._sense_loading = reader, True
    if reader is not None:
        reader.refused.clear()                       # each sample starts afresh
    engine._save = lambda: None                      # nor write down whether dictation is on
    import unittest.mock as mock
    with mock.patch("dictation.engine.log"), mock.patch("dictation.engine.config.SENTENCE_QUIET", 0):
        for text in written:
            engine.handle_text(text, True)
        engine._finish_sentence("the end of the sample", for_now=True)
    return page.text


# ---- how right it was --------------------------------------------------------------------
_WORD = __import__("re").compile(r"[^\W_]+(?:['’.\-][^\W_]+)*\.?|[^\w\s]")


def _pieces(text: str) -> list:
    """[(word, the mark after it)] of a text: the mark is "", "," , "." (any sentence end)
    or "other", and a line break counts as a sentence end. It is one mark to a word, so a
    comma before a break stays the comma: a missed comma there must still be able to show."""
    import re
    out = []
    text = text.replace("\u2029", "\n").replace("\u2028", "\n")   # the program's own breaks
    for token in re.findall(r"\n|[^\W_]+(?:['’][^\W_]+)*|[^\w\s]", text):
        if re.match(r"[^\W_]", token):
            out.append([token, ""])
        elif out:
            mark = ("." if token in ".?!\n" else "," if token == "," else
                    out[-1][1] or "other" if token not in "\"“”'‘’()" else out[-1][1])
            if (out[-1][1] in ("", "other") or mark == ".") and not (
                    mark == "." and out[-1][1] == ","):
                out[-1][1] = mark if mark else out[-1][1]
    return [(w, m) for w, m in out]


def score(typed: str, meant: str) -> dict:
    """How far `typed` is from `meant`: the words lined up, and then for each gap between
    them whether the mark is right (none, comma, sentence end), and for each word whether
    its capital is. Words that were misheard are counted apart and their gaps left out."""
    a, b = _pieces(typed), _pieces(meant)
    x, y = [w.lower() for w, _ in a], [w.lower() for w, _ in b]
    n, m = len(x), len(y)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (x[i - 1] != y[j - 1]))
    pairs, i, j = [], n, m
    while i and j:
        if cost[i][j] == cost[i - 1][j - 1] + (x[i - 1] != y[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif cost[i][j] == cost[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    found = {"words": m, "misheard": cost[n][m], "ends_right": 0, "ends_missed": 0,
             "ends_wrong": 0, "commas_right": 0, "commas_missed": 0, "commas_wrong": 0,
             "capitals_wrong": 0}
    for (ia, jb) in pairs:
        if x[ia] != y[jb]:
            continue
        if a[ia][0][:1].isupper() != b[jb][0][:1].isupper():
            found["capitals_wrong"] += 1
        got, want = a[ia][1], b[jb][1]
        if jb == m - 1:
            continue                      # the very end: whether it has a stop is the sample's end
        if want == ".":
            found["ends_right" if got == "." else "ends_missed"] += 1
        elif got == "." and want != ",":
            # (A stop where a comma was meant is one wrong mark, counted as the comma missed,
            # not twice: the comma typed where a stop was meant is counted once as well.)
            found["ends_wrong"] += 1
        if want == ",":
            found["commas_right" if got == "," else "commas_missed"] += 1
        elif got == "," and want != ".":
            found["commas_wrong"] += 1
    return found
