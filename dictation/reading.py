"""Reading sentences aloud, to collect sound a recogniser could be retrained on.

One sentence is shown at a time, and the microphone stays open. At each pause a recogniser
hears the sentence so far, and when it has heard it to the end the sound is kept and the
next sentence is shown: nothing has to be pressed. Pressing Next does the same at once.
The sound is kept with the silence trimmed off, beside the text that was read: a folder
for each day, with 001.wav, 002.wav and so on, and a line "001<tab>the text" for each in
said.txt.

Nothing here retrains anything. These files are what a retraining would start from.
"""
from __future__ import annotations

import codecs
import collections
import locale
import math
import os
import re
import shutil
import time
import wave
from dataclasses import dataclass

from . import config
from .segmenter import START, Segmenter, SegmenterConfig

FOLDER = os.path.join(os.path.dirname(config.STATE_FILE), "training")
OWN_TEXT = "own-text.txt"   # in FOLDER: a text of the reader's own choosing
SAID = "said.txt"           # in each day's folder: what was read for each sound file

LONGEST_TEXT = 2_000_000  # characters of a chosen text that are looked at
LEAST_WORDS = 3     # shorter than this is a heading or a scrap, not a sentence
MOST_WORDS = 24     # longer than this is too much to read in one breath
TAIL_FRAMES = 32    # silence kept after the last word: dictation's phrases end the same way
PAUSE_FRAMES = 10   # after Next, the sentence's sound ends once it has been quiet this long
CHECK_FRAMES = 20   # a pause this long, and a recogniser is asked whether the sentence is done
WAIT_FRAMES = 150   # or after this long, if the reader never pauses
LEAST_FRAMES = 15   # less speech than this was a cough or a click
LEAD_FRAMES = 5     # with less quiet than this before it, a sentence's first sound was missed
LONGEST_FRAMES = 40 * config.RATE // config.FRAME  # the microphone was left open: not a sentence

NOTHING_HEARD = "nothing heard"
TOO_LONG = "too long"
MISSED_START = "start missed"


# ---- what there is to read ------------------------------------------------------------
# A recogniser can only be taught text it could have written. Figures, and marks that
# Parakeet has no way to write, would teach it something else than what was said.
_READABLE = re.compile(r"[A-Z][A-Za-z',.?! -]*[.?!]")
_ENDS = re.compile(r"(?<=[.?!])\s+(?=[A-Z])")


def sentences_from(text: str) -> tuple:
    """(the sentences of `text` that can be read for training, how many were left out).

    A blank line ends a paragraph, and a line break inside one is only a space. Left out:
    anything with figures or unusual marks in it, anything too short or too long, and
    anything that comes up twice.
    """
    text = (text.replace("’", "'").replace("‘", "'")
            .replace("“", "").replace("”", "").replace('"', "")
            .replace(" — ", ", ").replace(" – ", ", "))
    found, left_out = [], 0
    for paragraph in re.split(r"\n\s*\n", text):
        for sentence in _ENDS.split(" ".join(paragraph.split())):
            if not sentence:
                continue
            count = len(sentence.split())
            if (_READABLE.fullmatch(sentence) and LEAST_WORDS <= count <= MOST_WORDS
                    and sentence not in found):
                found.append(sentence)
            else:
                left_out += 1
    return found, left_out


def _text_of(path: str) -> str:
    """What the text file at `path` says, however it was saved. Raises OSError.

    A file need not be UTF-8. Word's "Plain Text" is in the Windows encoding, where a
    curly apostrophe is one byte that means nothing in UTF-8, and its "Unicode" is
    UTF-16. Read as UTF-8 the one loses every sentence with an apostrophe in it, and the
    other has no sentences at all. So: UTF-16 if the file starts with its mark, UTF-8 if
    the bytes are UTF-8, and otherwise this computer's own encoding, or Western Windows
    where that is UTF-8 as well.
    """
    with open(path, "rb") as f:
        data = f.read(4 * LONGEST_TEXT)
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")[:LONGEST_TEXT]
    try:
        # (Not finished off: a long file may have been cut in the middle of a letter.)
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(data)
    except UnicodeDecodeError:
        own = locale.getpreferredencoding(False)
        own = "cp1252" if codecs.lookup(own).name in ("utf-8", "ascii") else own
        text = data.decode(own, errors="replace")
    return text[:LONGEST_TEXT]


def own_text(folder: str = FOLDER) -> tuple:
    """The reader's own text, as sentences_from gives it. ([], 0) if none was chosen."""
    try:
        return sentences_from(_text_of(os.path.join(folder, OWN_TEXT)))
    except OSError:
        return [], 0


def choose_own_text(path: str, folder: str = FOLDER) -> tuple:
    """Take a copy of the text file at `path` as the reader's own text, if there is
    anything in it to read. Returns what sentences_from makes of it. Raises OSError."""
    found, left_out = sentences_from(_text_of(path))
    if found:
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(path, os.path.join(folder, OWN_TEXT))
    return found, left_out


# ---- has the sentence been read to its end? ----------------------------------------------
DONE = "done"        # heard to the end, near enough
NOT_YET = "not yet"  # so far it is the beginning of the sentence
ASTRAY = "astray"    # it isn't this sentence


def _words(text: str) -> list:
    text = text.lower().replace("\u2019", "'").replace("-", " ")
    return re.sub(r"[^a-z0-9' ]", " ", text).split()


def _allowed(count: int) -> int:
    """How many words of `count` may be heard wrong. A recogniser is being asked about the
    very voice it is to be taught, so it has to be let off a word in four: the words it
    gets wrong are the ones worth keeping."""
    return max(1, count // 4)


def verdict(text: str, heard: str) -> str:
    """What to make of `heard`, a recogniser's hearing of the sound so far, when `text`
    is the sentence being read: DONE, NOT_YET or ASTRAY."""
    said, got = _words(text), _words(heard)
    if not got:
        return NOT_YET
    # How far each beginning of the sentence is from what was heard, in words changed,
    # left out or put in. The beginning that fits best says how far the reader has got.
    row = list(range(len(got) + 1))
    apart = [row[-1]]
    for i, word in enumerate(said, 1):
        new = [i]
        for j, other in enumerate(got, 1):
            new.append(min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (word != other)))
        row = new
        apart.append(row[-1])
    reached = max(i for i, distance in enumerate(apart) if distance == min(apart))
    if reached == len(said):
        return DONE if apart[reached] <= _allowed(len(said)) else ASTRAY
    if len(got) < 3 or apart[reached] <= _allowed(max(reached, len(got))):
        return NOT_YET
    return ASTRAY


# ---- following the microphone, for a level display ---------------------------------------
class Ear:
    """Follows the microphone's sound without keeping any of it: how loud the room is by
    itself, and whether somebody is speaking. For a display of the level."""

    def __init__(self, boost: float = 1.0):
        made = SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO, flat_ms=0)
        self._segmenter = Segmenter(made)
        self._boost = boost
        self._warmup = -(-made.warmup_ms // made.frame_ms)  # frames still to hear of the room

    def feed(self, frame) -> float:
        """One frame of 16-bit sound. Returns how loud it is, in the same measure as `room`."""
        import numpy as np
        level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * self._boost
        self._segmenter.feed(level)
        self._warmup = max(0, self._warmup - 1)
        return level

    @property
    def ready(self) -> bool:
        """Whether the room has been measured: until then there is no level to show."""
        return self._warmup <= 0

    @property
    def room(self) -> float:
        """How loud the room is by itself."""
        return self._segmenter.noise

    @property
    def speaking(self) -> bool:
        return self._segmenter.in_phrase


# ---- cutting the microphone's sound into sentences -------------------------------------
@dataclass
class Take:
    """The sound of one sentence, or why there isn't any."""
    samples: object = None   # 16-bit sound at config.RATE, trimmed; None if it can't be kept
    problem: str = ""

    @property
    def seconds(self) -> float:
        return 0.0 if self.samples is None else len(self.samples) / config.RATE


class Cutter:
    """Give it the microphone's sound a frame at a time, and say when the reader moves on.
    feed() hands back each sentence's sound once it is complete.

    Pressing Next a little early loses nothing: the sound runs on to the next pause.
    Nothing said before the microphone was listening can be kept, though, so a sentence
    already under way when it opens is handed back as MISSED_START, not as half of itself.
    """

    def __init__(self, boost: float = 1.0):
        made = SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO, flat_ms=0)
        self._segmenter = Segmenter(made)
        self._warmup = made.warmup_ms // made.frame_ms    # frames spent measuring the room
        self._onset = made.start_ms // made.frame_ms      # frames of speech before it counts
        # How much quiet is kept in front of a sentence not yet begun: a rest before
        # reading is no part of the sentence, and doesn't count towards its being too long.
        self._lead_most = LEAD_FRAMES + config.PREROLL_FRAMES + self._onset + 8
        self._boost = boost
        self._quiet = 0   # frames in a row without speech, up to now
        self._recent = collections.deque(maxlen=config.PREROLL_FRAMES)  # the latest frames
        self._done = []
        self._fresh()

    def _fresh(self) -> None:
        """Begin a sentence's sound, with the quiet just before now as its lead-in."""
        lead = min(self._quiet, len(self._recent))
        self._frames = list(self._recent)[len(self._recent) - lead:]
        self._first = None      # where in it speech began
        self._last = None       # and the last frame of speech so far
        self._closing = None    # after Next: how many more frames to wait for a pause
        self._skipping = False  # passing over speech that belongs to nothing, up to a pause
        self._marks = {}        # checkpoint() results: how long it was, and its last speech
        self._checked = None    # the last speech a recogniser has been asked about
        self._too_long = False
        self._segmenter.reset()

    @property
    def ready(self) -> bool:
        """Whether the room has been measured, so that reading can begin."""
        return self._warmup <= 0

    @property
    def room(self) -> float:
        """How loud the room is by itself, in the pause detector's own measure."""
        return self._segmenter.noise

    @property
    def speaking(self) -> bool:
        """Whether the reader is taken to be speaking just now."""
        return self._segmenter.in_phrase

    def loudness(self, frame) -> float:
        """How loud a frame is, in the same measure as `room`."""
        import numpy as np
        return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * self._boost

    def reopened(self) -> None:
        """The microphone was closed for a rest and is open again. The room is not
        measured afresh: the reader may start the moment the sentence is back."""
        self._quiet = 0
        self._recent.clear()
        self._fresh()

    def feed(self, frame) -> list:
        """One frame of 16-bit sound. Returns the Takes it completes: mostly none."""
        import numpy as np
        level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * self._boost
        loud = level > self._segmenter.threshold
        event = self._segmenter.feed(level)
        if not self.ready:
            self._warmup -= 1
            return []
        self._quiet = 0 if loud else self._quiet + 1
        self._recent.append(frame)
        if self._skipping:
            if self._quiet >= PAUSE_FRAMES:
                self._fresh()  # the pause has come: the sentence starts from here
        elif len(self._frames) >= LONGEST_FRAMES:
            self._too_long = True
        elif not self._too_long:
            self._frames.append(frame)
            if self._first is None and len(self._frames) > self._lead_most:
                del self._frames[:len(self._frames) - self._lead_most]
            if event == START and self._first is None:
                self._first = max(0, len(self._frames) - self._onset)
            if self._first is not None and loud and self._segmenter.in_phrase:
                self._last = len(self._frames) - 1
        if self._closing is not None:
            self._closing -= 1
            if self._quiet >= PAUSE_FRAMES:
                self._cut()
            elif self._closing <= 0:
                self._cut()
                self._skipping = True  # still talking: what follows belongs to no sentence
        done, self._done = self._done, []
        return done

    @property
    def due(self) -> bool:
        """Whether the reader has paused after saying something new, so that it is worth
        asking a recogniser if the sentence is done."""
        return (self._last is not None and self._last != self._checked
                and self._quiet >= CHECK_FRAMES and self._closing is None
                and not self._skipping and not self._too_long
                and self._last - self._first >= LEAST_FRAMES)

    def checkpoint(self) -> tuple:
        """(a mark, the sentence's sound so far) for a recogniser to hear. accept(mark)
        then ends the sentence's sound where it stood at this moment."""
        import numpy as np
        mark = len(self._frames)
        self._marks[mark] = self._checked = self._last
        start = max(0, self._first - config.PREROLL_FRAMES)
        return mark, np.concatenate(self._frames[start:mark])

    def accept(self, mark: int) -> bool:
        """The sentence was heard to its end at checkpoint `mark`: its sound ends there.
        False if that checkpoint was of a sentence since started afresh."""
        last = self._marks.get(mark)
        if last is None:
            return False
        more = self._last > last  # something was said after it: that belongs to nothing
        self._cut(mark if more else len(self._frames), last)
        self._skipping = more and self._quiet < PAUSE_FRAMES
        return True

    def next(self) -> None:
        """The reader has finished the sentence: its sound ends here, or at the pause
        that follows if they are still speaking."""
        if self._closing is not None:
            self._cut()  # pressed again before the pause came
        if self._quiet >= PAUSE_FRAMES or self._first is None:
            self._cut()
        else:
            self._closing = WAIT_FRAMES

    def again(self) -> None:
        """Forget what has been heard of this sentence: it is being read afresh. If the
        reader is still speaking, the rest of that is passed over too."""
        still_speaking = self._quiet < PAUSE_FRAMES
        self._fresh()
        self._skipping = still_speaking

    def _cut(self, end: int | None = None, last: int | None = None) -> None:
        """Hand over the sentence's sound: all of it, or up to frame `end`, where the
        last speech was at `last`."""
        import numpy as np
        end = len(self._frames) if end is None else end
        last = self._last if last is None else last
        if self._too_long:
            take = Take(problem=TOO_LONG)
        elif self._first is None or last is None or last - self._first < LEAST_FRAMES:
            take = Take(problem=NOTHING_HEARD)
        elif self._first < LEAD_FRAMES:
            take = Take(problem=MISSED_START)  # no quiet before it: its beginning wasn't heard
        else:
            start = max(0, self._first - config.PREROLL_FRAMES)
            take = Take(np.concatenate(self._frames[start:min(end, last + 1 + TAIL_FRAMES)]))
        self._done.append(take)
        self._fresh()


# ---- what has been kept ------------------------------------------------------------------
class Kept:
    """The sentences recorded so far, on disk: see the top of this file."""

    def __init__(self, folder: str = FOLDER, day: str = ""):
        self.folder = folder
        self.day = day or time.strftime("%Y-%m-%d")
        self._mine = []  # the numbers kept in this sitting, latest last

    def _days(self) -> list:
        try:
            return sorted(name for name in os.listdir(self.folder)
                          if os.path.isfile(os.path.join(self.folder, name, SAID)))
        except OSError:
            return []

    def _lines(self, day: str) -> list:
        """[(number, text)] for the sound files of a day that are still there. Where a
        number is listed twice, the later line is the one its sound goes with."""
        found = {}
        try:
            with open(os.path.join(self.folder, day, SAID), encoding="utf-8",
                      errors="replace") as f:
                for line in f:
                    number, tab, text = line.rstrip("\n").partition("\t")
                    if tab and os.path.exists(os.path.join(self.folder, day, number + ".wav")):
                        found.pop(number, None)
                        found[number] = text
        except (OSError, ValueError):
            pass
        return list(found.items())

    def texts(self) -> set:
        """Every text that has been read and kept, on any day."""
        return {text for day in self._days() for _, text in self._lines(day)}

    def times(self) -> dict:
        """How many times each text has been read and kept, over all the days."""
        return collections.Counter(text for day in self._days() for _, text in self._lines(day))

    # A text is read through once. It can be gone through again, for more of the voice or
    # the voice in another room: how many times each text is to be read is kept here.
    ROUNDS = "rounds.json"

    def rounds(self, name: str) -> int:
        """How many times the text called `name` is to be read through: once, unless
        it has been asked for again."""
        import json
        try:
            with open(os.path.join(self.folder, self.ROUNDS), encoding="utf-8") as f:
                return max(1, int(json.load(f).get(name, 1)))
        except (OSError, ValueError, AttributeError, TypeError):
            return 1

    def set_rounds(self, name: str, rounds: int) -> None:
        import json
        path = os.path.join(self.folder, self.ROUNDS)
        try:
            with open(path, encoding="utf-8") as f:
                said = json.load(f)
        except (OSError, ValueError):
            said = {}
        said = said if isinstance(said, dict) else {}
        said[name] = max(1, int(rounds))
        try:
            os.makedirs(self.folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(said, f)
        except OSError:
            pass  # a folder that can't be written: the sentences are simply not offered again

    def totals(self) -> tuple:
        """(how many sentences are kept, how many seconds of sound they come to)."""
        count, nbytes = 0, 0
        for day in self._days():
            for number, _ in self._lines(day):
                count += 1
                try:
                    nbytes += max(0, os.path.getsize(
                        os.path.join(self.folder, day, number + ".wav")) - 44)
                except OSError:
                    pass
        return count, nbytes / (2 * config.RATE)

    def keep(self, samples, text: str) -> str:
        """Save one sentence's sound and its text. Returns the sound file. Raises OSError."""
        folder = os.path.join(self.folder, self.day)
        os.makedirs(folder, exist_ok=True)
        taken = [int(name[:-4]) for name in os.listdir(folder)
                 if name.endswith(".wav") and name[:-4].isdigit()]
        # A number is never used twice, even one whose sound was deleted by hand: its
        # line in the list would pair the new sound with the old words.
        try:
            with open(os.path.join(folder, SAID), encoding="utf-8", errors="replace") as f:
                taken += [int(line.split("\t", 1)[0]) for line in f
                          if line.split("\t", 1)[0].isdigit()]
        except (OSError, ValueError):
            pass
        number = f"{max(taken, default=0) + 1:03d}"
        path = os.path.join(folder, number + ".wav")
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(config.RATE)
            f.writeframes(samples.astype("<i2").tobytes())
        with open(os.path.join(folder, SAID), "a", encoding="utf-8") as f:
            f.write(f"{number}\t{' '.join(text.split())}\n")
        self._mine.append(number)
        return path

    def take_back(self) -> str:
        """Remove the last sentence kept in this sitting. Returns its text, or ""."""
        if not self._mine:
            return ""
        number = self._mine.pop()
        folder = os.path.join(self.folder, self.day)
        lines = self._lines(self.day)
        text = next((said for kept, said in lines if kept == number), "")
        try:
            os.remove(os.path.join(folder, number + ".wav"))
            with open(os.path.join(folder, SAID), "w", encoding="utf-8") as f:
                f.writelines(f"{kept}\t{said}\n" for kept, said in lines if kept != number)
        except OSError:
            pass
        return text


def unread(sentences, kept: Kept, rounds: int = 1) -> list:
    """Those of `sentences` still to be read, in their order: any not yet read and kept
    `rounds` times. Once through, unless the text is being gone through again."""
    times = kept.times()
    return [sentence for sentence in sentences if times.get(sentence, 0) < rounds]


def read_through(sentences, kept: Kept) -> int:
    """How many times the whole of `sentences` has been read: as often as its least
    read sentence."""
    times = kept.times()
    return min((times.get(sentence, 0) for sentence in sentences), default=0)


# ---- is the voice at a good level? ------------------------------------------------------
# Two things can be wrong with a level, and they are measured differently. Too quiet is
# the voice not standing far enough above the room: `above` is how far, on the scale of
# the app's own meter (engine.meter_value), 0 to 100 where 100 is 40 dB. Too loud is the
# microphone running out of room: `peak` is the highest the sound went, where 1.0 is the
# most it can carry and what is past CLIP_LEVEL comes out distorted.
QUIET = 37.5      # under this, 15 dB above the room, the voice is too quiet
GOOD = 62.5       # from this, 25 dB above the room, it is at a good level
BLEND = 6.0       # the colours run into one another over this much either side of those
ROOMY = 0.5       # a peak up to here leaves plenty in hand
WARM = 0.6        # past here it is getting loud
LOUD = 0.7        # from here there is little in hand: one loud word would distort
LOWEST_DB = -48.0  # a peak this far under the most there can be is the bar's empty end

# Cool colours for too little, warm for too much, green between: each means one thing.
GREY, BLUE, GREEN = (138, 138, 138), (66, 133, 188), (46, 157, 79)
YELLOW, ORANGE, RED = (236, 196, 40), (239, 108, 0), (229, 57, 53)


def level_place(peak: float) -> float:
    """How far along a bar, 0 to 100, a peak comes: by ear, so that each doubling of the
    sound moves it on by the same amount."""
    if peak <= 0:
        return 0.0
    return min(100.0, max(0.0, 100.0 * (1.0 - 20.0 * math.log10(min(peak, 1.0)) / LOWEST_DB)))


def _between(a: tuple, b: tuple, share: float) -> tuple:
    share = min(1.0, max(0.0, share))
    return tuple(round(x + (y - x) * share) for x, y in zip(a, b))


def level_colour(above: float, peak: float) -> tuple:
    """(red, green, blue) for a level: grey for too quiet, through blue, to green for
    good, then through yellow and orange to red as the microphone runs out of room.
    No steps."""
    if peak >= config.CLIP_LEVEL:
        return RED
    if above < QUIET + BLEND:
        colour = _between(GREY, BLUE, (above - (QUIET - BLEND)) / (2 * BLEND))
    else:
        colour = _between(BLUE, GREEN, (above - (GOOD - BLEND)) / (2 * BLEND))
    if peak > LOUD:
        return _between(ORANGE, RED, (peak - LOUD) / (config.CLIP_LEVEL - LOUD))
    if peak > WARM:
        return _between(YELLOW, ORANGE, (peak - WARM) / (LOUD - WARM))
    if peak > ROOMY:
        return _between(colour, YELLOW, (peak - ROOMY) / (WARM - ROOMY))
    return colour


def level_verdict(above: float, peak: float) -> tuple:
    """(what to tell the reader, its colour) for a sentence: `above` and `peak` are the
    most each came to while it was spoken."""
    if peak >= config.CLIP_LEVEL:
        return "Too loud", RED
    if peak >= LOUD:
        return "Nearly too loud", ORANGE
    if above >= GOOD:
        return "Good level", GREEN
    if above >= QUIET:
        return "A little quiet", BLUE
    return "Too quiet", GREY


# What to do about each verdict, for a window that is only there to try the level.
ADVICE = {
    "Too quiet": "Speak up, move closer to the microphone, or turn the microphone up.",
    "A little quiet": "It can be heard, but a little louder or closer would be heard better.",
    "Good level": "Nothing to change.",
    "Nearly too loud": "Move back a little, or turn the microphone down a little: a loud "
                       "word would be distorted.",
    "Too loud": "Turn the microphone down, or move it further away: the sound is distorted.",
}


def long_enough(text: str) -> float:
    """Seconds by which anyone would have read `text` aloud and been heard out: after
    that, a sentence still on the screen is waiting for something."""
    return 4.0 + 0.6 * len(text.split())


def time_text(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s"
