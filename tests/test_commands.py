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
        self.assertEqual(interpret("Correct that.", awake=True), Command("select_last"))
        self.assertIsInstance(interpret("Correct that mistake", awake=True), Dictation)
        self.assertIsInstance(interpret("correct that", True, frozenset({"select_last"})), Dictation)

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


class Enter(unittest.TestCase):
    OFF = frozenset({"enter"})  # how it starts: the setting is not ticked

    def test_press_enter_always_was_a_command(self):
        self.assertEqual(interpret("Press enter.", True, self.OFF), Command("press_enter"))

    def test_the_one_word_is_typed_until_it_is_switched_on(self):
        self.assertIsInstance(interpret("Enter.", True, self.OFF), Dictation)
        self.assertEqual(interpret("Enter.", True), Command("enter"))

    def test_in_a_sentence_it_is_a_word(self):
        self.assertIsInstance(interpret("Enter the building", True), Dictation)

    def test_it_can_be_on_with_press_enter_off(self):
        self.assertEqual(interpret("enter", True, frozenset({"press_enter"})), Command("enter"))
        self.assertIsInstance(interpret("press enter", True, frozenset({"press_enter"})), Dictation)


class Space(unittest.TestCase):
    def test_said_by_itself(self):
        for said in ("Space.", "space bar", "Spacebar", "Press space"):
            self.assertEqual(interpret(said, True), Command("space", "1"), said)

    def test_with_a_count(self):
        self.assertEqual(interpret("space 3", True), Command("space", "3"))
        self.assertEqual(interpret("Space three times.", True), Command("space", "3"))
        self.assertEqual(interpret("space 99", True), Command("space", "20"))  # no more than that

    def test_in_a_sentence_it_is_a_word(self):
        for said in ("Space station", "We need more space", "Space for everyone", "space to", "space bar bar"):
            self.assertIsInstance(interpret(said, True), Dictation, said)

    def test_switched_off_it_is_typed(self):
        self.assertIsInstance(interpret("space", True, frozenset({"space"})), Dictation)

    def test_backspace_is_still_backspace(self):
        self.assertEqual(interpret("Backspace", True), Command("backspace", "1"))
        self.assertEqual(interpret("back space 2", True), Command("backspace", "2"))


if __name__ == "__main__":
    unittest.main()
