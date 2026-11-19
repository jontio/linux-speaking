"""Cutting the microphone stream into phrases at each pause.

Works on loudness values, one per 20 ms frame, so it can be tested without
audio. The engine keeps the audio itself.
"""
from __future__ import annotations

from dataclasses import dataclass

START = "start"
END = "end"
# How a phrase ended (Segmenter.ended_by): the room went quiet, as it nearly always does;
# or the sound fell far below the voice but not below what the room was thought to be;
# or it never fell at all, and was cut at the longest a phrase may be.
PAUSE, FELL_AWAY, LIMIT = "pause", "fell away", "limit"
# ... or it was ended from outside, because the voice in it was seen to have stopped though
# the sound went on: see speech.VoiceWatch.
NO_VOICE = "no voice"
# ... or it was no phrase at all: sound as flat as a fan's or a hum's from its start, which
# is the room, grown louder. There is nothing in it to be taken down.
ROOM = "the room"


@dataclass
class SegmenterConfig:
    frame_ms: int = 20
    start_ms: int = 60          # this much speech in a row starts a phrase
    end_silence_ms: int = 650   # this much silence ends it
    max_phrase_ms: int = 20000  # force a cut after this long
    min_level: float = 150.0    # never treat anything quieter as speech
    ratio: float = 3.0          # speech is this many times louder than the room
    warmup_ms: int = 500        # at the start, just measure the room
    # A room can get louder after a phrase has started: a fan comes on, or the
    # microphone turns itself up when the talking stops. What is left is then above
    # what the room was taken to be, and the pause never came: the phrase ran on to its
    # limit, twenty seconds, before anything was done with it. So sound this far below
    # the voice of the phrase itself counts as quiet too, once there has been this much
    # of the voice to go by: if it stays level, as a fan or a hiss does. What rises and
    # falls as talking does is taken for talking, however soft.
    fall_ratio: float = 0.15
    fall_after_ms: int = 300
    # And however loud it is beside the voice, sound that stays flat is not talking: a
    # fan, a hum. Talking rises and falls with every syllable: of ten thousand
    # one-second stretches of one person's recorded sentences, not one was flat by this
    # measure (the quietest tenth of it over `flat_low` of its middle loudness, the
    # loudest tenth under `flat_high`).
    #
    # A second of it (`flat_ms`) after something clearly louder ends the phrase: the
    # voice has stopped and that is what is left. The room is not yet taken to be any
    # louder for it, though: a long "ummm" is flat as well, and the rest of the sentence
    # comes after it. Only a phrase that is flat from its start for `room_ms` is the
    # room itself. There is nothing in it to take down, and from then on a voice need
    # only be `flat_ratio` times as loud as it to be heard, where it has to be `ratio`
    # times as loud as a room that rises and falls: what is flat seldom goes far above
    # itself.
    flat_ms: int = 1000
    room_ms: int = 2000
    flat_low: float = 0.6
    flat_high: float = 1.6
    flat_under: float = 0.7   # how far under what came before, to be what is left after a voice
    flat_ratio: float = 1.6


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
        self._voice = []   # loudness of the frames of this phrase that were the voice
        self._typical = 0.0  # how loud the voice of this phrase usually is
        self.ended_by = ""   # how the last phrase ended: PAUSE, FELL_AWAY or LIMIT
        self.room_was = 0.0  # what the room was taken to be when it ended, and before
        # Of the last phrase, for the log: how loud its voice was, how loud its last
        # second was, and whether that second stayed level as a fan or a hiss does.
        self.voice_was, self.tail_was, self.tail_steady = 0.0, 0.0, False
        self.usual_was = 0.0  # and how loud it usually was, all through
        self.flat_room = 0.0  # how loud the room was when it was last found to be flat: 0 if it isn't
        self.tail_spread = (0.0, 0.0)  # the last second's quietest and loudest tenths, over its middle

    @property
    def threshold(self) -> float:
        ratio = self.c.flat_ratio if self.flat_room else self.c.ratio
        return max(self.c.min_level, self.noise * ratio)

    def _is_flat(self, levels) -> bool:
        ordered = sorted(levels)
        if not ordered:
            return False
        middle = ordered[len(ordered) // 2]
        return (middle > 0 and ordered[len(ordered) // 10] >= self.c.flat_low * middle
                and ordered[(9 * len(ordered)) // 10] <= self.c.flat_high * middle)

    def _over(self, by: str) -> str:
        """The phrase is over: keep what the log is told of it, and say so."""
        self.in_phrase = False
        self._loud = self._quiet = 0
        last_second = self._levels[-1000 // self.c.frame_ms:]
        self.voice_was, self.tail_was = self._typical, _median(last_second)
        self.tail_steady = _steady(last_second)
        self.tail_spread = _spread(last_second)
        self.usual_was = _median(self._levels)
        self.ended_by = by
        self._levels = []
        return END

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
                if self.flat_room and self.noise < 0.7 * self.flat_room:
                    self.flat_room = 0.0   # the fan has stopped: an ordinary room again
            self._loud = self._loud + 1 if speech else 0
            if self._loud * c.frame_ms >= c.start_ms:
                self.in_phrase = True
                self._quiet = 0
                self._length = self._loud
                self._loud = 0
                self._levels = [level]
                self._voice, self._typical = [level], level
                return START
            return None
        self._length += 1
        self._levels.append(level)
        # Quiet is what is below the room's threshold: or, once the voice of this phrase
        # is known, what is far below the voice. (See SegmenterConfig.fall_ratio.)
        quiet_below = self.threshold
        if len(self._voice) * c.frame_ms >= c.fall_after_ms:
            quiet_below = max(quiet_below, self._typical * c.fall_ratio)
        if level > quiet_below:
            self._quiet = 0
            self._voice.append(level)
            if len(self._voice) % 5 == 0:   # the upper quarter: loud enough to be the voice itself
                self._typical = sorted(self._voice)[(3 * len(self._voice)) // 4]
        else:
            self._quiet += 1
        flat_frames, room_frames = c.flat_ms // c.frame_ms, c.room_ms // c.frame_ms
        if c.flat_ms and len(self._levels) >= flat_frames and self._length % 5 == 0:
            recent = self._levels[-flat_frames:]
            middle = _median(recent)
            if middle > self.threshold and self._is_flat(recent):
                before = sorted(self._levels[:-flat_frames])
                if len(self._levels) >= room_frames and self._is_flat(self._levels):
                    # Flat from its start, for two seconds: no phrase, but the room.
                    self.room_was = self.noise
                    self.noise = max(self.noise, middle)
                    self.flat_room = self.noise
                    return self._over(ROOM)
                if len(before) >= 10 and middle < c.flat_under * before[(9 * len(before)) // 10]:
                    # A second of flat sound after something clearly louder: the voice
                    # has stopped. (If it is a fan, it starts a phrase of its own at
                    # once, and is found to be the room a moment later.)
                    self.room_was = self.noise
                    return self._over(FELL_AWAY)
        too_long = self._length * c.frame_ms >= c.max_phrase_ms
        if self._quiet * c.frame_ms >= c.end_silence_ms and not too_long:
            recent = self._levels[-self._quiet:]
            if _median(recent) > self.threshold and not _steady(recent):
                # Far below what came before, and yet it rises and falls as talking does:
                # a voice gone soft, or one that began after a bang. That is the voice
                # now. Only what stays level, as a fan or a hiss does, is the room.
                self._voice = [each for each in recent if each > self.threshold]
                self._typical = sorted(self._voice)[(3 * len(self._voice)) // 4]
                self._quiet = 0
                return None
        if self._quiet * c.frame_ms >= c.end_silence_ms or too_long:
            self.in_phrase = False
            self._loud = 0
            self.room_was = self.noise
            last_second = self._levels[-1000 // c.frame_ms:]
            self.voice_was, self.tail_was = self._typical, _median(last_second)
            self.tail_steady = _steady(last_second)
            self.tail_spread = _spread(last_second)
            self.usual_was = _median(self._levels)
            tail = _median(self._levels[-self._quiet:]) if self._quiet else 0.0
            if too_long and _steady(self._levels):
                # It never paused and never dipped, so it's a steady noise, not
                # someone talking at length: treat its loudness as the new room level.
                self.ended_by = LIMIT
                self.noise = max(self.noise, _median(self._levels))
            elif too_long:
                self.ended_by = LIMIT
                self.noise = max(self.noise, min(self._levels))
            elif tail > self.threshold:
                # The voice stopped and what was left was louder than the room was taken
                # to be: that is the room now. Or it would start a phrase of its own at
                # once, and swallow whatever is said next.
                self.ended_by = FELL_AWAY
                self.noise = max(self.noise, tail)
            else:
                self.ended_by = PAUSE
                self.noise = max(self.noise, min(self._levels))
            self._levels = []
            return END
        return None

    def cut(self) -> str:
        """End the phrase now, from outside: the voice in it has stopped, though the room
        is too loud for a pause to show. The room is not taken to be any louder for it:
        where its noise is nearly as loud as the voice, that would shut the voice out."""
        if not self.in_phrase:
            return ""
        self.in_phrase = False
        self._loud = self._quiet = 0
        self.room_was = self.noise
        last_second = self._levels[-1000 // self.c.frame_ms:]
        self.voice_was, self.tail_was = self._typical, _median(last_second)
        self.tail_steady = _steady(last_second)
        self.tail_spread = _spread(last_second)
        self.ended_by = NO_VOICE
        self._levels = []
        return END

    def was_the_room(self) -> None:
        """The phrase that just ran to its limit had no voice in it at all: it was the
        room, grown louder since it was last measured. A noise that rises and falls keeps
        starting phrases, and while a phrase is on the room isn't measured: so it was
        never learnt, and every phrase after it ran to the limit as well. How loud that
        one usually was is the room now. (It is followed down again as soon as it falls.)"""
        self.noise = max(self.noise, self.usual_was)

    def began_again(self, frames: int) -> None:
        """The phrase has been cut down to its last `frames`: what came before was only
        the room. Its length, and its limit, count from there."""
        if self.in_phrase:
            self._length = frames
            self._levels = self._levels[-frames:]

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


def _spread(levels) -> tuple:
    """How far the quietest and the loudest tenths of `levels` are from the middle one, as
    shares of it: (0.9, 1.1) for a fan, (0.1, 2.5) for talking."""
    ordered = sorted(levels)
    if not ordered or not ordered[len(ordered) // 2]:
        return (0.0, 0.0)
    middle = ordered[len(ordered) // 2]
    return (round(ordered[len(ordered) // 10] / middle, 2), round(ordered[(9 * len(ordered)) // 10] / middle, 2))


def _median(values) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2] if ordered else 0.0
