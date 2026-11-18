"""The key that switches dictation on Windows, with a stand-in for Windows itself: no key
is taken or pressed on the computer the tests run on."""
import queue
import threading
import unittest

from dictation import hotkey


class Windows:
    """Stands in for the calls to Windows. `refuse` is the set of keys another program has."""

    refuse = frozenset()
    made = []

    def __init__(self):
        self.taken = None
        self.given_back = False
        self.presses = queue.Queue()
        Windows.made.append(self)

    def take(self, modifiers, key):
        if key in self.refuse:
            return False
        self.taken = (modifiers, key)
        return True

    def wait(self):
        return self.presses.get()  # True for a press, False to stop

    def give_back(self):
        self.given_back = True

    def wake(self):
        self.presses.put(False)


class Keys(unittest.TestCase):
    def test_the_number_pads_plus_is_among_them_as_the_settings_expect(self):
        self.assertIn("Number pad +", hotkey.KEYS)
        self.assertEqual(hotkey.KEYS["Number pad +"], (0, 0x6B))
        self.assertEqual(hotkey.NUMPAD_PLUS, "Number pad +")

    def test_each_is_a_name_with_what_windows_asks_for(self):
        self.assertGreaterEqual(len(hotkey.KEYS), 4)
        for name, (modifiers, key) in hotkey.KEYS.items():
            self.assertTrue(name.strip() and name == name.strip())
            self.assertIsInstance(modifiers, int)
            self.assertTrue(0 < key < 256, name)
        self.assertEqual(len(set(hotkey.KEYS.values())), len(hotkey.KEYS))

    def test_there_is_one_for_a_keyboard_with_no_number_pad(self):
        self.assertTrue(any("+" in name and name != "Number pad +" for name in hotkey.KEYS))

    def test_no_key_and_keys_it_does_not_know_count_as_none(self):
        self.assertEqual(hotkey.chosen("Pause"), "Pause")
        for name in ("", None, "None", "Caps Lock", 7):
            self.assertEqual(hotkey.chosen(name), "")

    def test_what_a_key_costs_is_said_only_of_keys_there_are(self):
        self.assertTrue(set(hotkey.COSTS) <= set(hotkey.KEYS))


class Taking(unittest.TestCase):
    def setUp(self):
        Windows.made, Windows.refuse = [], frozenset()
        self.pressed = threading.Semaphore(0)
        self.key = hotkey.Hotkey(self.pressed.release, windows=Windows)
        self.addCleanup(self.key.stop)

    def test_it_takes_the_key_by_name_and_tells_of_each_press(self):
        self.assertTrue(self.key.start("Pause"))
        self.assertEqual(self.key.name, "Pause")
        at = Windows.made[-1]
        self.assertEqual(at.taken, (hotkey.MOD_NOREPEAT, 0x13))
        at.presses.put(True)
        at.presses.put(True)
        self.assertTrue(self.pressed.acquire(timeout=2))
        self.assertTrue(self.pressed.acquire(timeout=2))

    def test_a_key_with_ctrl_and_alt_is_asked_for_with_them(self):
        self.assertTrue(self.key.start("Ctrl+Alt+D"))
        self.assertEqual(Windows.made[-1].taken,
                         (hotkey.MOD_CONTROL | hotkey.MOD_ALT | hotkey.MOD_NOREPEAT, 0x44))

    def test_a_key_another_program_has_is_refused_and_nothing_is_held(self):
        Windows.refuse = frozenset({0x6B})
        self.assertFalse(self.key.start("Number pad +"))
        self.assertEqual(self.key.name, "")
        self.assertTrue(self.key.start("F9"))  # another can still be taken
        self.assertEqual(self.key.name, "F9")

    def test_a_name_it_does_not_know_takes_nothing(self):
        self.assertFalse(self.key.start("Caps Lock"))
        self.assertEqual(Windows.made, [])

    def test_choosing_another_gives_the_first_back(self):
        self.assertTrue(self.key.start("Pause"))
        first = Windows.made[-1]
        self.assertTrue(self.key.start("Scroll Lock"))
        self.assertTrue(first.given_back)
        self.assertEqual(self.key.name, "Scroll Lock")
        self.assertEqual(len(Windows.made), 2)

    def test_the_same_again_is_not_taken_twice(self):
        self.assertTrue(self.key.start("Pause"))
        self.assertTrue(self.key.start("Pause"))
        self.assertEqual(len(Windows.made), 1)

    def test_stopping_gives_it_back(self):
        self.assertTrue(self.key.start("Pause"))
        self.key.stop()
        self.assertTrue(Windows.made[-1].given_back)
        self.assertEqual(self.key.name, "")
        self.key.stop()  # and twice is fine

    def test_a_press_that_goes_wrong_does_not_end_the_listening(self):
        def broken():
            self.pressed.release()
            raise RuntimeError("as a test")
        key = hotkey.Hotkey(broken, windows=Windows)
        self.addCleanup(key.stop)
        self.assertTrue(key.start("Pause"))
        Windows.made[-1].presses.put(True)
        Windows.made[-1].presses.put(True)
        self.assertTrue(self.pressed.acquire(timeout=2))
        self.assertTrue(self.pressed.acquire(timeout=2))


if __name__ == "__main__":
    unittest.main()
