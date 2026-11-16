import unittest
from types import SimpleNamespace as Segment

from dictation import quick

RATE = 16000


class Window(unittest.TestCase):
    def test_a_short_phrase_gets_ten_seconds(self):
        for seconds in (0.5, 2, 4.9):
            self.assertEqual(quick.window_frames(int(seconds * RATE), RATE), 1000)

    def test_five_seconds_of_room_after_the_phrase(self):
        self.assertEqual(quick.window_frames(int(5.1 * RATE), RATE), 1500)
        self.assertEqual(quick.window_frames(int(9.9 * RATE), RATE), 1500)
        self.assertEqual(quick.window_frames(int(12 * RATE), RATE), 2000)

    def test_never_more_than_the_usual_half_minute(self):
        self.assertEqual(quick.window_frames(int(20 * RATE), RATE), 2500)
        self.assertEqual(quick.window_frames(int(26 * RATE), RATE), quick.FULL)
        self.assertEqual(quick.window_frames(int(40 * RATE), RATE), quick.FULL)

    def test_the_setting_goes_back_afterwards(self):
        with quick.window(1500):
            self.assertEqual(quick._window[0], 1500)
        self.assertEqual(quick._window[0], quick.FULL)
        with self.assertRaises(RuntimeError):
            with quick.window(1000):
                raise RuntimeError("whatever happens inside")
        self.assertEqual(quick._window[0], quick.FULL)


class Limits(unittest.TestCase):
    def test_grows_with_the_phrase_and_stops(self):
        self.assertEqual(quick.token_limit(1), 24)
        self.assertEqual(quick.token_limit(10), 96)
        self.assertEqual(quick.token_limit(60), 200)


class Runaway(unittest.TestCase):
    SAID = "you ought to know John, if I teach them I'll scarcely see much of people in my own class."

    def test_what_was_said_is_fine(self):
        self.assertEqual(quick.runaway(self.SAID, 7.5), "")
        self.assertEqual(quick.runaway("", 1.0), "")
        self.assertEqual(quick.runaway("Yes.", 0.4), "")

    def test_the_sentence_twice_over(self):
        self.assertIn("twice", quick.runaway(self.SAID + " " + self.SAID, 12.0))

    def test_more_than_there_was_time_for(self):
        self.assertIn("time", quick.runaway(" ".join(f"word{n}" for n in range(40)), 7.5))

    def test_one_thing_many_times(self):
        self.assertTrue(quick.runaway("la la la la la la la la la la la la la la la la la la la la la la", 30.0))

    def test_a_short_phrase_gone_round_once(self):
        self.assertIn("twice", quick.runaway("comma comma", 0.6))
        self.assertIn("twice", quick.runaway("Period. Period.", 0.8))
        self.assertEqual(quick.runaway("comma", 0.6), "")

    def test_real_repeats_that_people_say_are_let_through(self):
        self.assertEqual(quick.runaway("No, no, no, I said no.", 2.5), "")
        self.assertEqual(quick.runaway("It is what it is, and that is that.", 3.0), "")


class Unsure(unittest.TestCase):
    def test_a_good_hearing(self):
        self.assertFalse(quick.unsure([Segment(avg_logprob=-0.3, compression_ratio=1.4)]))
        self.assertFalse(quick.unsure([]))

    def test_a_poor_one_or_one_that_repeats(self):
        self.assertTrue(quick.unsure([Segment(avg_logprob=-1.4, compression_ratio=1.4)]))
        self.assertTrue(quick.unsure([Segment(avg_logprob=-0.3, compression_ratio=3.1)]))


if __name__ == "__main__":
    unittest.main()
