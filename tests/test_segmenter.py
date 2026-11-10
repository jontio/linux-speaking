import unittest

from dictation.segmenter import END, START, Segmenter, SegmenterConfig


def run(levels, config=None):
    s = Segmenter(config or SegmenterConfig(warmup_ms=0))
    return [(i, e) for i, level in enumerate(levels) if (e := s.feed(level))]


class Phrases(unittest.TestCase):
    def test_quiet_room_never_starts(self):
        self.assertEqual(run([40] * 500), [])

    def test_one_phrase(self):
        levels = [40] * 50 + [2000] * 50 + [40] * 60
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
        events = run([40] * 10 + [2000] * 1200)
        self.assertEqual([e for _, e in events][:2], [START, END])

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
            speech += [rng.uniform(3000, 8000) for _ in range(rng.randint(8, 25))]
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


if __name__ == "__main__":
    unittest.main()
