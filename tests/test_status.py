import unittest

from dictation.status import State, Status


class Tooltip(unittest.TestCase):
    def test_off(self):
        s = Status()
        self.assertEqual(s.tooltip(), "Dictation: Off")
        self.assertEqual(s.menu_toggle_label(), "Turn the microphone on")

    def test_awake_with_nothing_in_front(self):
        s = Status(State.AWAKE, last_heard="hello", target_known=True)
        self.assertEqual(s.tooltip(), "Dictation: Awake\nNothing to type into is in front\nHeard: hello")
        self.assertTrue(s.awake)
        self.assertEqual(s.menu_toggle_label(), "Turn the microphone off")

    def test_where_the_words_will_go_is_not_said_before_it_has_been_looked_for(self):
        self.assertEqual(Status(State.AWAKE).tooltip(), "Dictation: Awake")
        # Nor asleep or off, when nobody is looking: it was stale then, and often wrong.
        asleep = Status(State.ASLEEP, writer_ready=True, target="Writer", target_known=True)
        self.assertNotIn("Writer", asleep.tooltip())
        self.assertNotIn("in front", Status(State.ASLEEP, target_known=True).tooltip())

    def test_asleep_says_how_to_wake_it(self):
        self.assertEqual(Status(State.ASLEEP).tooltip(), 'Dictation: Asleep. Say "wake up" to dictate.')

    def test_loading(self):
        s = Status(State.ASLEEP, ready=False)
        self.assertEqual(s.tooltip().splitlines()[0], "Dictation: Loading\u2026")
        s.ready = True
        self.assertTrue(s.tooltip().splitlines()[0].startswith("Dictation: Asleep"))

    def test_no_speech_model_says_so_and_why(self):
        s = Status(State.ASLEEP, ready=False, failed="No speech model is installed. Open Settings.")
        self.assertEqual(s.label(), "No speech model")
        self.assertEqual(s.tooltip(), "Dictation: No speech model\nNo speech model is installed. Open Settings.")

    def test_names_what_it_is_typing_into(self):
        s = Status(State.AWAKE, writer_ready=True, target="Thunderbird", target_known=True)
        self.assertEqual(s.tooltip(), "Dictation: Awake\nTyping into Thunderbird")

    def test_too_loud(self):
        s = Status(State.AWAKE, writer_ready=True, loud=True)
        self.assertIn("Microphone too loud: turn it down", s.tooltip().splitlines())
        self.assertNotIn("too loud", Status(State.OFF, loud=True).tooltip())

    def test_standing_problems_are_listed_whatever_the_state(self):
        s = Status(State.OFF, problems=["The microphone can't be opened."])
        self.assertEqual(s.tooltip(), "Dictation: Off\nThe microphone can't be opened.")
        self.assertEqual(Status().problems, [])
        self.assertIsNot(Status().problems, Status().problems)

    def test_asleep_is_not_awake(self):
        self.assertFalse(Status(State.ASLEEP).awake)


if __name__ == "__main__":
    unittest.main()
