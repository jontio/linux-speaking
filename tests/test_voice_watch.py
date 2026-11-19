"""Seeing the voice stop where the room is too loud for a pause."""
import unittest

import numpy as np

from dictation import config
from dictation.segmenter import END, NO_VOICE, START, Segmenter, SegmenterConfig
from dictation.speech import BEGAN_LATE, GONE, VoiceWatch

RATE, FRAME = config.RATE, config.FRAME


def voice(seconds: float, loud: float = 3000.0, pitch: float = 140.0) -> np.ndarray:
    """Something with a pitch, as a voice has: a tone and its overtones, rising and
    falling by the syllable."""
    t = np.arange(int(seconds * RATE)) / RATE
    tone = sum(np.sin(2 * np.pi * pitch * n * t) / n for n in range(1, 8))
    syllables = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)
    return (tone * syllables * loud).astype(np.float32)


def room(seconds: float, loud: float = 1600.0, seed: int = 1) -> np.ndarray:
    """A noise with no pitch, whose loudness wanders: a fan that roars, a keyboard."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    steps = n // 1600 + 2
    wander = np.interp(np.arange(n), np.arange(steps) * 1600, np.exp(rng.normal(0, 0.5, steps)))
    return (rng.normal(0, 1, n) * wander * loud).astype(np.float32)


def frames(sound: np.ndarray):
    for at in range(0, len(sound) - FRAME + 1, FRAME):
        yield sound[at:at + FRAME].astype(np.int16)


def watched(sound: np.ndarray) -> list:
    """What the watch says of `sound`, and when: [(seconds in, what), ...]."""
    watch = VoiceWatch()
    said = []
    for count, frame in enumerate(frames(sound), 1):
        seen = watch.feed(frame)
        if seen:
            said.append((round(count * FRAME / RATE, 2), seen))
            if seen == GONE:
                break
    return said


class TheVoiceIsWatched(unittest.TestCase):
    def test_it_is_seen_to_have_gone_though_the_room_goes_on(self):
        sound = room(12.0)
        sound[:3 * RATE] += voice(3.0)                    # three seconds said, in a loud room
        said = watched(sound)
        self.assertEqual([what for _, what in said], [GONE])
        self.assertGreater(said[0][0], 3.0 + 1.0)        # not before it has really stopped
        self.assertLess(said[0][0], 3.0 + 2.6)           # and not twenty seconds after

    def test_a_room_with_no_voice_in_it_is_never_cut_for_want_of_one(self):
        self.assertEqual(watched(room(15.0, seed=2)), [])  # as a whisper would not be

    def test_talking_with_short_gaps_in_it_is_not_cut(self):
        sound = room(12.0, seed=3)
        for start in (0.0, 2.6, 5.2, 7.8):               # four stretches, 0.6 s apart
            sound[int(start * RATE):int((start + 2.0) * RATE)] += voice(2.0)
        said = watched(sound[:int(9.8 * RATE)])
        self.assertEqual(said, [])

    def test_a_voice_that_begins_well_into_the_rooms_noise_is_said_to_have_begun_late(self):
        sound = room(12.0, seed=4)
        sound[6 * RATE:9 * RATE] += voice(3.0)           # six seconds of the room, then a voice
        said = watched(sound)
        self.assertEqual([what for _, what in said], [BEGAN_LATE, GONE])
        self.assertTrue(6.0 < said[0][0] < 7.3)          # within a look or two of its start
        self.assertTrue(9.0 + 1.0 < said[1][0] < 9.0 + 2.6)

    def test_a_voice_that_begins_the_phrase_did_not_begin_late(self):
        sound = room(6.0, seed=5)
        sound[:2 * RATE] += voice(2.0)
        self.assertEqual([what for _, what in watched(sound)], [GONE])

    def test_in_a_quiet_room_too_the_voice_is_seen(self):
        sound = np.concatenate([voice(2.0), np.zeros(4 * RATE, np.float32)])
        self.assertEqual([what for _, what in watched(sound)], [GONE])

    def test_it_keeps_count_for_the_one_who_cuts_the_phrase(self):
        watch = VoiceWatch()
        self.assertEqual((watch.frames_for(1.0), watch.frames_for(watch.AFTER)), (50, 12))
        watch.start(15)                                   # the moment before the phrase is kept
        self.assertEqual((watch.frames, watch.heard, watch.frames_since_voice()), (15, False, 0))
        sound = room(5.0, seed=6)
        sound[:2 * RATE] += voice(2.0)
        for frame in frames(sound):
            if watch.feed(frame) == GONE:
                break
        self.assertGreaterEqual(watch.frames_since_voice(), watch.frames_for(watch.GONE_AFTER))
        watch.began_at(75)
        self.assertEqual((watch.frames, watch.frames_since_voice()), (75, 0))


class ThePhraseIsCutFromOutside(unittest.TestCase):
    def test_cut_ends_the_phrase_and_leaves_the_room_as_it_was_taken_to_be(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        unsteady = [900, 900, 900, 400, 900, 900, 500, 900, 900, 400] * 10   # no fan: it rises and falls
        events = [s.feed(level) for level in [40] * 50 + [2000, 2000, 2000, 400] * 12 + unsteady]
        self.assertEqual([e for e in events if e], [START])
        before = s.noise
        self.assertEqual(s.cut(), END)
        self.assertEqual((s.in_phrase, s.ended_by, s.noise), (False, NO_VOICE, before))
        self.assertEqual((s.voice_was > 0, s.tail_was), (True, 900))
        self.assertEqual(s.cut(), "")                     # there is nothing to cut twice

    def test_a_phrase_with_no_voice_in_it_that_ran_to_the_limit_was_the_room(self):
        import random
        random.seed(8)
        # A noise that rises and falls, louder than the room was taken to be: it starts a
        # phrase that runs to the limit, and then another, and another.
        noise = [180 * random.choice((0.5, 0.8, 1.0, 1.4, 1.9)) for _ in range(3000)]
        s = Segmenter(SegmenterConfig(warmup_ms=0, min_level=60, ratio=2.5))
        endings = 0
        for level in [40] * 100 + noise[:1100]:
            if s.feed(level) == END:
                endings += 1
        self.assertEqual((endings, s.ended_by), (1, "limit"))
        before = s.threshold
        s.was_the_room()                                   # the engine saw no voice in it
        self.assertGreater(s.threshold, before)
        started = sum(1 for level in noise[1100:] if s.feed(level) == START)
        self.assertLessEqual(started, 2)                   # it no longer starts one phrase after another
        for level in [40] * 200:                           # and when the room is quiet again
            s.feed(level)
        self.assertLess(s.threshold, before + 1)           # it is taken to be quiet again

    def test_a_phrase_cut_down_to_its_end_has_its_limit_counted_from_there(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        unsteady = [900, 900, 900, 400, 900, 900, 500, 900, 900, 400]
        for level in [40] * 50 + unsteady * 90:           # eighteen seconds of a room that rises and falls
            s.feed(level)
        self.assertTrue(s.in_phrase)
        s.began_again(75)                                  # a voice began: only the last 1.5 s is kept
        events = [s.feed(level) for level in unsteady * 50]  # ten seconds more
        self.assertEqual([e for e in events if e], [])     # which the old count would have cut at two


if __name__ == "__main__":
    unittest.main()
