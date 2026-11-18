import io
import os
import tempfile
import unittest
from unittest import mock

from dictation import config, control


class Asking(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "state", "show")

    def test_nothing_asked_is_nothing_taken(self):
        self.assertEqual(control.taken(self.path), [])

    def test_what_is_asked_is_taken_once_in_order(self):
        control.ask("toggle", self.path)
        control.ask("settings", self.path)
        self.assertEqual(control.taken(self.path), ["toggle", "settings"])
        self.assertEqual(control.taken(self.path), [])
        self.assertFalse(os.path.exists(self.path))

    def test_an_empty_file_as_the_menu_entry_leaves_asks_to_be_shown(self):
        os.makedirs(os.path.dirname(self.path))
        open(self.path, "w").close()
        self.assertEqual(control.taken(self.path), [control.SHOW])

    def test_words_are_tidied_and_a_runaway_file_is_cut_short(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as f:
            f.write("  Toggle \n\n" + "wake\n" * 100)
        words = control.taken(self.path)
        self.assertEqual(words[:2], ["toggle", "wake"])
        self.assertLessEqual(len(words), 20)


class AskedWhole(unittest.TestCase):
    def test_a_request_is_never_seen_half_written_and_two_are_both_kept(self):
        import tempfile
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "show")
        control.ask("toggle", path)
        self.assertEqual(os.listdir(folder), ["show"])        # nothing left beside it
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "toggle\n")
        control.ask("sleep", path)
        self.assertEqual(control.taken(path), ["toggle", "sleep"])
        self.assertEqual(control.taken(path), [])


@unittest.skipIf(config.WINDOWS, "the lock is a file on Linux")
class OnlyOne(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "state", "running")
        self.addCleanup(self.let_go)

    def let_go(self):
        if control._held is not None:
            control._held.close()
            control._held = None

    def test_not_running_until_one_has_claimed_it(self):
        self.assertFalse(control.running(self.path))
        self.assertFalse(os.path.exists(self.path))  # asking leaves nothing behind

    def test_the_first_claims_it_and_a_second_is_refused(self):
        self.assertTrue(control.only_one(self.path))
        self.assertTrue(control.running(self.path))
        first, control._held = control._held, None
        try:
            self.assertFalse(control.only_one(self.path))  # a second start
            self.assertIsNone(control._held)
        finally:
            control._held = first

    def test_it_is_free_again_when_the_first_has_gone(self):
        self.assertTrue(control.only_one(self.path))
        self.let_go()  # as the system does when the program ends, however it ends
        self.assertFalse(control.running(self.path))
        self.assertTrue(control.only_one(self.path))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "show")
        self.said = []

    def run_it(self, *words, running=True):
        with mock.patch.object(control, "running", lambda: running), \
                mock.patch.object(control, "request_file", lambda: self.path):
            return control.main(list(words), out=self.said.append)

    def test_each_word_is_left_for_the_app_and_one_line_is_said(self):
        for word in control.COMMANDS:
            self.said.clear()
            self.assertEqual(self.run_it(word), 0)
            self.assertEqual(len(self.said), 1)
            self.assertEqual(control.taken(self.path), [word])

    def test_toggle_is_among_them_with_the_others_the_contract_names(self):
        self.assertEqual(set(control.COMMANDS), {"toggle", "wake", "sleep", "off", "settings"})

    def test_with_the_app_not_running_it_says_so_and_ends_with_1(self):
        self.assertEqual(self.run_it("toggle", running=False), 1)
        self.assertEqual(len(self.said), 1)
        self.assertIn("isn't running", self.said[0])
        self.assertEqual(control.taken(self.path), [])  # nothing is left for a later start

    def test_a_word_it_does_not_know_asks_nothing(self):
        self.assertEqual(self.run_it("dance"), 2)
        self.assertEqual(self.run_it(), 2)
        self.assertEqual(control.taken(self.path), [])
        self.assertTrue(all("toggle" in line for line in self.said))

    def test_it_prints_by_default(self):
        with mock.patch.object(control, "running", lambda: False), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(control.main(["wake"]), 1)
        self.assertEqual(out.getvalue().count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
