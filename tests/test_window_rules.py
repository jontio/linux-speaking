"""Rules the windows go by that need no window to try: when a voice-test recording is
taken as finished, and which result its "Use it for dictation" button means."""
import unittest

from dictation import voicetest


class RecordingEndsByItself(unittest.TestCase):
    def test_the_passage_takes_a_minute_or_more_to_read(self):
        words = len(voicetest.words(" ".join(voicetest.PASSAGE)))
        self.assertAlmostEqual(voicetest.least_seconds(), words / voicetest.READ_WORDS_A_SECOND)
        self.assertGreater(voicetest.least_seconds(), 60)
        self.assertLess(voicetest.least_seconds(), voicetest.LONGEST_SECONDS / 2)

    def test_a_pause_while_reading_does_not_end_it(self):
        early = voicetest.least_seconds() - 1
        self.assertFalse(voicetest.read_out(early, voicetest.QUIET_END * 3))  # a drink of water

    def test_a_long_quiet_once_it_could_have_been_read_ends_it(self):
        late = voicetest.least_seconds() + 1
        self.assertFalse(voicetest.read_out(late, voicetest.QUIET_END - 0.1))  # still reading
        self.assertTrue(voicetest.read_out(late, voicetest.QUIET_END))


class WhichToUse(unittest.TestCase):
    def result(self, title, wrong, seconds, where="here", problem=""):
        return voicetest.Result(title, where, title.lower(), False, wrong=wrong, total=300,
                                seconds=seconds, problem=problem)

    def test_the_result_itself_is_handed_over_for_the_button(self):
        quick, slow = self.result("Small", 4, 0.5), self.result("Medium", 3, 2.0)
        self.assertIs(voicetest.suggested([slow, quick]), quick)  # as accurate, near enough
        self.assertEqual(voicetest.suggestion([slow, quick]), "Small")

    def test_nothing_tried_is_nothing_suggested(self):
        self.assertIsNone(voicetest.suggested([]))
        self.assertIsNone(voicetest.suggested([self.result("Small", 0, 0.5, problem="no")]))
        self.assertEqual(voicetest.suggestion([]), "")

    def test_several_working_together_are_not_a_model_to_choose(self):
        team = self.result("Parakeet checked by Small", 0, 3.0, where="team")
        one = self.result("Small", 5, 0.5)
        self.assertIs(voicetest.suggested([team, one]), one)


if __name__ == "__main__":
    unittest.main()
