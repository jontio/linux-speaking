import unittest

from dictation.status import State, Status


class Tooltip(unittest.TestCase):
    def test_off(self):
        s = Status()
        self.assertEqual(s.tooltip(), "Dictation: Off")
        self.assertEqual(s.menu_toggle_label(), "Turn on")

    def test_awake_without_writer(self):
        s = Status(State.AWAKE, last_heard="hello")
        self.assertEqual(s.tooltip(), "Dictation: Awake\nNo program to type into is in front\nHeard: hello")
        self.assertTrue(s.awake)
        self.assertEqual(s.menu_toggle_label(), "Turn off")

    def test_loading(self):
        s = Status(State.ASLEEP, ready=False)
        self.assertEqual(s.tooltip().splitlines()[0], "Dictation: Loading\u2026")
        s.ready = True
        self.assertEqual(s.tooltip().splitlines()[0], "Dictation: Asleep")

    def test_names_what_it_is_typing_into(self):
        s = Status(State.AWAKE, writer_ready=True, target="Thunderbird")
        self.assertEqual(s.tooltip(), "Dictation: Awake\nTyping into Thunderbird")

    def test_too_loud(self):
        s = Status(State.AWAKE, writer_ready=True, loud=True)
        self.assertIn("Microphone too loud: turn it down", s.tooltip().splitlines())
        self.assertNotIn("too loud", Status(State.OFF, loud=True).tooltip())

    def test_asleep_is_not_awake(self):
        self.assertFalse(Status(State.ASLEEP).awake)


if __name__ == "__main__":
    unittest.main()
