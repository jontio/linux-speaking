"""Giving Whisper only as much sound as the phrase needs.

Whisper takes in half a minute of sound however short the phrase is, and working through
that half minute is most of the time it takes. Handed ten seconds for a three second
phrase, it writes the same words in a quarter of the time.

It was not taught that way, though, and now and then it loses its place and writes the
phrase over and over. So the quick way is a first try with a safety net: the phrase gets
five seconds of room after it, the answer may not be longer than could have been said in
the time, and an answer that repeats itself, or that Whisper itself was unsure of, is
thrown away and the phrase is done again the usual way.
"""
from __future__ import annotations

import zlib

FRAMES_A_SECOND = 100
FULL = 3000       # Whisper's usual half minute, in frames
LEAST = 1000      # less than ten seconds and it starts to repeat itself
HEADROOM = 500    # silence after the phrase, so it can tell where the phrase ends
STEP = 500

WORDS_A_SECOND = 4.0   # nobody dictates faster
REPEAT = 6             # this many words in a row, said twice, is Whisper going round
UNSURE = -1.0          # Whisper's own measure of a poor hearing (average log probability)
SQUASHED = 2.4         # text that compresses this well is the same thing many times

_window = [FULL]       # what Whisper is being given just now
_installed = None      # whether this library lets the window be changed; None until tried


def window_frames(samples: int, rate: int) -> int:
    """How much sound to give Whisper for a phrase of `samples`, in frames."""
    frames = samples * FRAMES_A_SECOND // rate + HEADROOM
    return min(FULL, max(LEAST, -(-frames // STEP) * STEP))


def token_limit(seconds: float) -> int:
    """The most word pieces a phrase this long could come to, with room to spare."""
    return min(200, int(8 * seconds) + 16)


def runaway(text: str, seconds: float) -> str:
    """Why `text` can't be what was said in `seconds`, or "" if it could be."""
    words = [word.strip(".,!?;:\"'()").lower() for word in text.split()]
    words = [word for word in words if word]
    if len(words) > WORDS_A_SECOND * seconds + 4:
        return "more words than there was time for"
    half = len(words) // 2
    if half and len(words) % 2 == 0 and words[:half] == words[half:]:
        return "the same words twice over"  # "comma comma": a short phrase gone round once
    seen = set()
    for at in range(len(words) - REPEAT + 1):
        run = tuple(words[at:at + REPEAT])
        if run in seen:
            return "the same words twice over"
        seen.add(run)
    raw = text.encode("utf-8")
    if len(raw) > 60 and len(raw) / len(zlib.compress(raw)) > SQUASHED:
        return "the same thing many times"
    return ""


def unsure(segments) -> bool:
    """Whether Whisper would itself have tried again: a poor hearing, or one that repeats."""
    return any(getattr(s, "avg_logprob", 0.0) < UNSURE
               or getattr(s, "compression_ratio", 0.0) > SQUASHED for s in segments)


def install() -> bool:
    """Make the window changeable. False if this version of the library won't allow it."""
    global _installed
    if _installed is None:
        try:
            import faster_whisper.transcribe as inner
            original = inner.pad_or_trim

            def pad_or_trim(array, length: int = FULL, *, axis: int = -1):
                # Only the half minute is changed; anything asked for by length is left.
                return original(array, _window[0] if length == FULL else length, axis=axis)

            inner.pad_or_trim = pad_or_trim
            _installed = True
        except Exception:
            _installed = False
    return _installed


class window:
    """`with window(frames):` gives Whisper that much sound for what is heard inside.

    One piece of listening at a time: the caller holds the recogniser's lock.
    """

    def __init__(self, frames: int):
        self.frames = frames

    def __enter__(self):
        _window[0] = self.frames
        return self

    def __exit__(self, *_):
        _window[0] = FULL
