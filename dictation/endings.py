"""Punctuation said after a pause at the end of a phrase.

"Is that right ... question mark", with a short pause before the last two words, is
sometimes written down by Whisper as "Is that right?": it takes the words as an
instruction and writes the sign. But its own sign at the end of a phrase is always
dropped, because it puts one after every phrase whether asked to or not. So the question
mark that was asked for goes as well.

The text can't tell the two apart, so the sound is looked at. If the phrase ends with a
short burst of speech after a pause, and no punctuation word came out at the end, that
burst is heard again by itself. Heard alone, "question mark" comes out as words.
"""
from __future__ import annotations

import re

from .commands import normalise
from .formatting import SPOKEN

FRAME = 0.02      # seconds of sound measured at a time
JOIN = 0.16       # a silence shorter than this is inside a word: the "k" of "mark"
PAUSE = 0.2       # the least silence that counts as a pause before the last words
SHORTEST = 0.25   # "period", said quickly
LONGEST = 1.4     # "exclamation point", said slowly
PAD = 0.15        # sound kept either side of the burst when it is cut out
QUIET = 0.1       # under this share of the phrase's loud parts is silence

_OWN_ENDING = re.compile(r"[.!?]+[\"')\]”’]*$")
_TRAILING = re.compile(r"[\s,.;:!?]+$")


def end_phrases(spoken_off=()) -> tuple:
    """The spoken phrases that end a sentence and are switched on: "full stop" and so on."""
    off = set(spoken_off)
    return tuple(phrase for phrase, sign in SPOKEN if sign in (".", "!", "?") and phrase not in off)


def worth_checking(text: str, phrases) -> bool:
    """Whether `text` could be hiding punctuation that was said: it ends with a sign of
    Whisper's own, which will be dropped, and not with one of the phrases."""
    if not phrases or not _OWN_ENDING.search(text.strip()):
        return False
    said = normalise(text)
    return not any(said == phrase or said.endswith(" " + phrase) for phrase in phrases)


def with_phrase(text: str, heard_alone: str, phrases) -> str:
    """`text` with the punctuation phrase put back in words, if that is what the last
    burst of sound was when heard by itself. Otherwise "" ."""
    heard = normalise(heard_alone)
    if heard not in phrases:
        return ""
    return (_TRAILING.sub("", text.strip()) + " " + heard).strip()


def only_signs(text: str) -> bool:
    """Whether `text` is punctuation and nothing else: "?" for the words "question mark"."""
    return bool(text.strip()) and not re.search(r"\w", text)


def said_alone(text: str, heard_alone: str, spoken) -> str:
    """The punctuation phrase that was said, when all that came out was a sign.

    With an unfinished question before the cursor, Whisper hears "question mark" and
    finishes the question: it writes "?" and no words. Heard again with nothing before it,
    the same sound comes out as words. `spoken` is the [(phrase, sign), ...] switched on.
    Returns "" if it wasn't one of them: a cough can come out as a full stop.
    """
    heard = normalise(heard_alone)
    for phrase, _ in spoken:
        if heard == phrase:
            return phrase
    sign = text.strip()[:1]
    if sign in ("?", "!"):  # not the kind of thing a noise is written down as
        for phrase, symbol in spoken:
            if symbol == sign:
                return phrase
    return ""


def trailing_burst(audio, rate: int):
    """(start, end) in seconds of a short burst of speech that ends `audio` after a pause,
    or None if it doesn't end that way."""
    import numpy as np
    size = int(rate * FRAME)
    count = len(audio) // size
    if count < 10:
        return None
    frames = np.asarray(audio[:count * size], dtype=np.float32).reshape(count, size)
    level = np.sqrt(np.mean(frames ** 2, axis=1))
    loud = level > QUIET * np.percentile(level, 95)
    runs = []  # (first frame, frame after the last) of each stretch of speech
    at = 0
    while at < count:
        if not loud[at]:
            at += 1
            continue
        end = at
        while end < count and loud[end]:
            end += 1
        if runs and (at - runs[-1][1]) * FRAME < JOIN:
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((at, end))
        at = end
    if len(runs) < 2:
        return None
    (start, end), earlier = runs[-1], runs[-2]
    if (start - earlier[1]) * FRAME < PAUSE or not SHORTEST <= (end - start) * FRAME <= LONGEST:
        return None
    return start * FRAME, end * FRAME


def cut(audio, burst, rate: int):
    """The burst's sound, with a little either side."""
    return audio[max(0, int((burst[0] - PAD) * rate)): int((burst[1] + PAD) * rate)]
