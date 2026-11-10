import unittest

from dictation.commands import Command, Dictation, choice, interpret, normalise


class Asleep(unittest.TestCase):
    def test_wakes_on_wake_up(self):
        self.assertEqual(interpret("Wake up.", awake=False), Command("wake"))
        self.assertEqual(interpret("Wake-up!", awake=False), Command("wake"))

    def test_wakes_on_near_misses(self):
        for heard in ("Wake cup.", "Wakeup", "Wake up, wake up.", "Wake up up", "Awake up."):
            self.assertEqual(interpret(heard, awake=False), Command("wake"), heard)

    def test_ignores_everything_else(self):
        for heard in ("We go up", "Thank you.", "Wake", "Up", "What's up?", "Wake up the kids now"):
            self.assertIsNone(interpret(heard, awake=False), heard)
        self.assertIsNone(interpret("Hello there", awake=False))
        self.assertIsNone(interpret("Go to sleep.", awake=False))
        self.assertIsNone(interpret("Wake up the kids", awake=False))


class Awake(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(interpret("Go to sleep.", awake=True), Command("sleep"))
        self.assertEqual(interpret("Scratch that!", awake=True), Command("scratch"))
        self.assertEqual(interpret("New paragraph.", awake=True), Command("new_paragraph"))
        self.assertEqual(interpret("Bold that.", awake=True), Command("bold"))

    def test_select(self):
        self.assertEqual(
            interpret("Select the black cat.", awake=True), Command("select", "the black cat")
        )
        self.assertEqual(interpret("Select that.", awake=True), Command("select_last"))

    def test_dictation(self):
        self.assertEqual(interpret("The cat sat.", awake=True), Dictation("The cat sat."))
        self.assertEqual(interpret("Select.", awake=True), Dictation("Select."))

    def test_silence(self):
        self.assertIsNone(interpret(" ... ", awake=True))

    def test_normalise(self):
        self.assertEqual(normalise("  Don’t   stop-now! "), "don't stop now")


class Choosing(unittest.TestCase):
    def test_numbers(self):
        for heard, n in (("2.", 2), ("Two.", 2), ("Choose 3", 3), ("Number one.", 1),
                         ("Too.", 2), ("Pick four", 4)):
            self.assertEqual(choice(heard, 5), n, heard)

    def test_out_of_range_or_not_a_number(self):
        self.assertIsNone(choice("Six.", 5))
        self.assertIsNone(choice("The cat sat.", 5))
        self.assertIsNone(choice("Choose wisely", 5))


if __name__ == "__main__":
    unittest.main()
