import unittest

from dictation.segmenter import END, FELL_AWAY, LIMIT, PAUSE, ROOM, START, Segmenter, SegmenterConfig


def talk(frames: int, loud: float = 2000) -> list:
    """Talking, as its loudness goes: syllables, and between them dips a fifth as loud.
    It ends on a syllable. (A loudness that never moves is no voice: see the last tests.)"""
    beat = [loud] * 7 + [loud * 0.2] * 3
    levels = (beat * (frames // len(beat) + 1))[:frames]
    levels[-1] = loud
    return levels


def run(levels, config=None):
    s = Segmenter(config or SegmenterConfig(warmup_ms=0))
    return [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]


class Phrases(unittest.TestCase):
    def test_quiet_room_never_starts(self):
        self.assertEqual(run([40] * 500), [])

    def test_one_phrase(self):
        levels = [40] * 50 + talk(50) + [40] * 60
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual(events[0][0], 52)   # after 60 ms of speech
        self.assertEqual(events[1][0], 132)  # 650 ms after the speech stops

    def test_short_pause_does_not_split(self):
        levels = [40] * 20 + [2000] * 30 + [40] * 20 + [2000] * 30 + [40] * 60
        self.assertEqual([e for _, e in run(levels)], [START, END])

    def test_click_is_ignored(self):
        levels = [40] * 20 + [5000] * 2 + [40] * 100
        self.assertEqual(run(levels), [])

    def test_long_speech_is_cut(self):
        events = run([40] * 10 + talk(1200))
        self.assertEqual([e for _, e in events][:2], [START, END])
        self.assertEqual(events[1][0] - events[0][0], 1000 - 3)   # at twenty seconds

    def test_hissy_microphone_does_not_start_phrases(self):
        import random
        rng = random.Random(1)
        levels = [rng.uniform(800, 1500) for _ in range(3000)]  # a minute of hiss
        events = run(levels)
        self.assertLessEqual(len(events), 2)  # at most one false start while it settles

    def test_hissy_microphone_with_warmup_never_starts(self):
        import random
        rng = random.Random(3)
        s = Segmenter()
        events = [e for _ in range(3000) if (e := s.feed(rng.uniform(800, 1500)))]
        self.assertEqual(events, [])

    def test_wake_up_right_after_switching_on(self):
        import random
        rng = random.Random(4)
        hiss = lambda n: [rng.uniform(800, 1500) for _ in range(n)]
        s = Segmenter()
        levels = hiss(50) + [9000] * 50 + hiss(60)  # speech one second after switch-on
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertLess(events[1][0] - events[0][0], 100)  # a short phrase, not 20 s

    def test_speech_over_hiss(self):
        import random
        rng = random.Random(2)
        hiss = lambda n: [rng.uniform(800, 1500) for _ in range(n)]
        events = run(hiss(1500) + [9000] * 60 + hiss(100))
        self.assertEqual([e for _, e in events][-2:], [START, END])

    def test_long_speech_does_not_deafen_it(self):
        # Half a minute of talking with only short gaps: loud syllables, brief dips.
        import random
        rng = random.Random(5)
        speech = []
        while len(speech) < 1500:
            speech += [rng.uniform(3000, 8000) for _ in range(rng.randint(6, 14))]
            speech += [rng.uniform(40, 120) for _ in range(rng.randint(2, 10))]
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate([40] * 20 + speech) if (e := s.feed(level))]
        kinds = [e for _, e in events]
        self.assertEqual(kinds[:3], [START, END, START])  # cut at 20 s, picked up again
        self.assertLess(events[2][0] - events[1][0], 40)  # within 0.8 s of the cut
        self.assertLess(s.threshold, 1000)  # speech still counts as speech

    def test_adapts_to_a_noisy_room(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        for _ in range(3000):
            s.feed(400)
        self.assertFalse(s.in_phrase)
        self.assertGreater(s.threshold, 400)



class ARoomThatGetsLouderAfterThePhraseHasStarted(unittest.TestCase):
    """A fan comes on, or the microphone turns itself up when the talking stops: what is
    left is above what the room was taken to be. The phrase used to run on to its limit,
    twenty seconds, before anything was done with what had been said."""

    def test_the_phrase_ends_when_the_sound_falls_far_below_the_voice(self):
        levels = [40] * 50 + talk(100) + [200] * 1200        # two seconds said, then a louder room
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])     # and no second phrase of the noise
        self.assertEqual(events[1][0], 50 + 100 + 32)              # 650 ms after the voice, not 20 s
        self.assertEqual(s.ended_by, FELL_AWAY)
        self.assertGreaterEqual(s.noise, 200)                      # that is the room now

    def test_it_keeps_what_the_log_is_told_of_a_phrase(self):
        levels = [40] * 50 + talk(100) + [200] * 1200
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        for level in levels:
            s.feed(level)
        self.assertEqual((s.voice_was, s.tail_was, s.tail_steady), (2000, 200, True))
        self.assertLess(s.room_was, 60)                               # what it had been taken to be

    def test_and_what_is_said_next_is_a_phrase_of_its_own(self):
        levels = [40] * 50 + talk(100) + [200] * 300 + talk(60) + [200] * 100
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END, START, END])
        self.assertEqual(events[3][0] - events[2][0], 60 - 3 + 33)  # as long as it was said, and the pause

    def test_before_this_it_ran_to_the_limit(self):
        levels = [40] * 50 + talk(100) + [200] * 1200
        s = Segmenter(SegmenterConfig(warmup_ms=0, fall_ratio=0.0, flat_ms=0))   # as it was
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual(events[1][0] - events[0][0], 1000 - 3)       # twenty seconds
        self.assertEqual(s.ended_by, LIMIT)

    def test_a_quiet_room_is_exactly_as_it_was(self):
        levels = [40] * 50 + talk(50) + [40] * 60
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual(events, [(52, START), (132, END)])
        self.assertEqual(s.ended_by, PAUSE)
        self.assertLess(s.noise, 60)                                  # the room is not thought louder

    def test_the_ups_and_downs_of_talking_do_not_end_it(self):
        # Loud syllables, soft ones a fifth as loud, and gaps between words of a fifth of
        # a second: one phrase, as it is one sentence.
        word = [1800] * 8 + [400] * 6 + [1200] * 6 + [300] * 4 + [45] * 10
        levels = [40] * 50 + word * 12 + [40] * 60
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END])
        self.assertGreater(events[1][0], 50 + len(word) * 12)

    def test_trailing_off_softly_is_still_heard_to_its_end(self):
        # The last words said at a quarter of the loudness: above the fall, and kept.
        levels = [40] * 50 + talk(60) + talk(60, 500) + [40] * 60
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual(events[1][0], 50 + 120 + 32)

    def test_a_bang_at_the_start_does_not_cut_off_what_is_said_after_it(self):
        # A door slams, far louder than the voice, and then the talking starts: syllables
        # and the gaps between them, all of it far below the bang.
        word = [1800] * 8 + [400] * 6 + [1200] * 6 + [300] * 4 + [45] * 10
        levels = [40] * 50 + [20000] * 10 + word * 6 + [40] * 60
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertGreater(events[1][0], 50 + 10 + len(word) * 6)     # all of it was heard
        self.assertEqual(s.ended_by, PAUSE)
        self.assertLess(s.noise, 60)                                  # and the room is not thought loud

    def test_talking_that_goes_on_far_more_softly_is_still_talking(self):
        loud = [6000] * 8 + [2400] * 6 + [4000] * 6 + [1800] * 4 + [45] * 10
        soft = [level * 0.12 if level > 100 else level for level in loud]  # an aside, an eighth as loud
        levels = [40] * 50 + loud * 4 + soft * 4 + loud * 2 + [40] * 60
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END])            # one phrase: none of it cut off
        self.assertGreater(events[1][0], 50 + len(loud) * 10)

    def test_a_hiss_that_wavers_a_little_is_still_the_room(self):
        import random
        random.seed(3)
        hiss = [200 * random.uniform(0.8, 1.25) for _ in range(1200)]
        levels = [40] * 50 + talk(100) + hiss
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual((events[1][0], s.ended_by), (50 + 100 + 32, FELL_AWAY))

    def test_a_steady_noise_that_starts_a_phrase_still_becomes_the_room(self):
        levels = [40] * 50 + [300] * 1100 + [300] * 200
        s = Segmenter(SegmenterConfig(warmup_ms=0, flat_ms=0))        # as it was: at the limit
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual(s.ended_by, LIMIT)


class SoundThatStaysFlatIsTheRoom(unittest.TestCase):
    """A fan, or a hum: as loud as half the voice, and with a pitch of its own, so that
    neither its loudness beside the voice nor the want of a voice gives it away. But it
    is flat, and talking never is: of ten thousand one-second stretches of one person's
    recorded sentences not one was flat by this measure."""

    def hum(self, frames, loud=300, seed=1):
        import random
        rng = random.Random(seed)
        return [loud * rng.uniform(0.9, 1.1) for _ in range(frames)]

    def test_a_phrase_ends_a_second_after_the_voice_though_the_hum_is_half_as_loud(self):
        levels = [40] * 50 + talk(100, 600) + self.hum(1200)        # the voice 600, the hum 300
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events, how = [], []
        for i, level in enumerate(levels):
            e = s.feed(level)
            if e:
                events.append((i, e))
                how += [s.ended_by] if e == END else []
        # What was said is handed over about a second after it, not twenty. Then the hum
        # starts a phrase of its own, is found to be the room, and starts no more.
        self.assertEqual([e for _, e in events], [START, END, START, END])
        self.assertLessEqual(events[1][0], 50 + 100 + 55)
        self.assertEqual(how, [FELL_AWAY, ROOM])
        self.assertLessEqual(events[3][0] - events[2][0], 105)     # two seconds
        self.assertGreater(s.noise, 250)                           # the hum is the room now
        self.assertTrue(s.flat_room)

    def test_a_hum_with_nothing_said_in_it_is_no_phrase_at_all(self):
        levels = [40] * 50 + self.hum(600)
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertLessEqual(events[1][0] - events[0][0], 105)     # found out within two seconds
        self.assertEqual(s.ended_by, ROOM)

    def test_over_the_hum_a_voice_twice_as_loud_is_still_heard_and_ends_at_its_pause(self):
        hum = self.hum(2000)
        said = talk(80, 700)
        speech = [max(a, b) for a, b in zip(said, hum[300:380])]   # the voice over the hum
        levels = [40] * 50 + hum[:300] + speech + hum[380:600]
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END, START, END])
        start, end = events[2][0], events[3][0]
        self.assertLessEqual(abs(start - (50 + 300)), 6)           # it began where the voice did
        self.assertLessEqual(end - (50 + 300 + 80), 40)            # and ended within a second of it
        self.assertEqual(s.ended_by, PAUSE)

    def test_a_long_um_is_not_the_room_and_the_sentence_after_it_is_heard(self):
        # "Ummmm" for a second and a half, flat, and then the sentence: at the same loudness.
        levels = [40] * 50 + [1500] * 75 + talk(150, 1500) + [40] * 60
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])     # one phrase, all of it
        self.assertEqual((events[1][0], s.ended_by), (50 + 225 + 32, PAUSE))
        self.assertFalse(s.flat_room)

    def test_when_the_hum_stops_the_room_is_an_ordinary_one_again(self):
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        for level in [40] * 50 + self.hum(300):
            s.feed(level)
        self.assertTrue(s.flat_room)
        for level in [40] * 200:
            s.feed(level)
        self.assertFalse(s.flat_room)
        self.assertEqual(s.threshold, max(s.c.min_level, s.noise * s.c.ratio))

    def test_talking_is_never_taken_for_it(self):
        levels = [40] * 50 + talk(900, 3000) + [40] * 60           # eighteen seconds of talking
        s = Segmenter(SegmenterConfig(warmup_ms=0))
        events = [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual((events[1][0], s.ended_by), (50 + 900 + 32, PAUSE))

    def test_a_long_vowel_is_not_a_fan(self):
        # "Sooo" held for most of a second, in the middle of talking: still one phrase.
        levels = [40] * 50 + talk(40) + [2000] * 40 + talk(40) + [40] * 60
        events = run(levels)
        self.assertEqual([e for _, e in events], [START, END])
        self.assertEqual(events[1][0], 50 + 120 + 32)


if __name__ == "__main__":
    unittest.main()
