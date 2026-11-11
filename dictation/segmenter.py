"""Cutting the microphone stream into phrases at each pause.

Works on loudness values, one per 20 ms frame, so it can be tested without
audio. The engine keeps the audio itself.
"""
from __future__ import annotations

from dataclasses import dataclass

START = "start"
END = "end"


@dataclass
class SegmenterConfig:
    frame_ms: int = 20
    start_ms: int = 60          # this much speech in a row starts a phrase
    end_silence_ms: int = 650   # this much silence ends it
    max_phrase_ms: int = 20000  # force a cut after this long
    min_level: float = 150.0    # never treat anything quieter as speech
    ratio: float = 3.0          # speech is this many times louder than the room
    warmup_ms: int = 500        # at the start, just measure the room


class Segmenter:
    """Feed it one loudness value per frame; it says when a phrase starts and ends."""

    def __init__(self, config: SegmenterConfig | None = None):
        self.c = config or SegmenterConfig()
        self.noise = self.c.min_level / self.c.ratio
        self.in_phrase = False
        self._loud = 0
        self._quiet = 0
        self._length = 0
        self._levels = []  # loudness of each frame in the current phrase
        self._warmup = []  # loudness of the first frames, to measure the room

    @property
    def threshold(self) -> float:
        return max(self.c.min_level, self.noise * self.c.ratio)

    def feed(self, level: float) -> str | None:
        c = self.c
        if self._warmup is not None:
            # Measure the room before listening, or a hissy microphone's noise
            # would be taken for one long phrase.
            self._warmup.append(level)
            if len(self._warmup) * c.frame_ms >= c.warmup_ms:
                self.noise = max(self.noise, _median(self._warmup))
                self._warmup = None
            return None
        speech = level > self.threshold
        if not self.in_phrase:
            # Follow the room's typical noise, a little faster down than up, so a
            # hissy microphone's ups and downs don't count as speech. Sounds loud
            # enough to be speech are left out, or every phrase's first syllable
            # would push the room level up.
            if not speech:
                rate = 0.05 if level < self.noise else 0.02
                self.noise += (level - self.noise) * rate
            self._loud = self._loud + 1 if speech else 0
            if self._loud * c.frame_ms >= c.start_ms:
                self.in_phrase = True
                self._quiet = 0
                self._length = self._loud
                self._loud = 0
                self._levels = [level]
                return START
            return None
        self._length += 1
        self._levels.append(level)
        self._quiet = 0 if speech else self._quiet + 1
        too_long = self._length * c.frame_ms >= c.max_phrase_ms
        if self._quiet * c.frame_ms >= c.end_silence_ms or too_long:
            self.in_phrase = False
            self._loud = 0
            if too_long and _steady(self._levels):
                # It never paused and never dipped, so it's a steady noise, not
                # someone talking at length: treat its loudness as the new room level.
                self.noise = max(self.noise, _median(self._levels))
            else:
                self.noise = max(self.noise, min(self._levels))
            self._levels = []
            return END
        return None

    def reset(self) -> None:
        self.in_phrase = False
        self._loud = self._quiet = self._length = 0


def _steady(levels) -> bool:
    """True for hiss or hum, False for speech.

    Speech keeps dropping between syllables and words, so its quiet moments are far
    below its typical loudness. A steady noise stays close to it throughout.
    """
    ordered = sorted(levels)
    if not ordered:
        return False
    quiet = ordered[len(ordered) // 10]
    return quiet >= 0.5 * ordered[len(ordered) // 2]


def _median(values) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0
