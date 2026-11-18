"""Starting at sign-in, with stand-ins for systemctl and for Windows' folders: nothing on
the computer the tests run on is asked or switched."""
import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from dictation import autostart, config


class Systemctl:
    """Stands in for systemctl: answers as told, and keeps what it was asked."""

    def __init__(self, said="enabled", code=0, error="", missing=False):
        self.said, self.code, self.error, self.missing = said, code, error, missing
        self.asked = []

    def __call__(self, command, **how):
        self.asked.append(command)
        if self.missing:
            raise FileNotFoundError("systemctl")
        return SimpleNamespace(returncode=self.code, stdout=self.said + "\n", stderr=self.error)


class Linux(unittest.TestCase):
    def test_enabled_and_disabled_are_told(self):
        run = Systemctl("enabled")
        self.assertIs(autostart._linux_state(run), True)
        self.assertEqual(run.asked, [["systemctl", "--user", "is-enabled", autostart.SERVICE]])
        self.assertIs(autostart._linux_state(Systemctl("disabled", code=1)), False)

    def test_anything_else_cannot_be_told(self):
        for said in ("static", "masked", "not-found", ""):
            self.assertIsNone(autostart._linux_state(Systemctl(said, code=1)), said)

    def test_no_systemd_cannot_be_told(self):
        self.assertIsNone(autostart._linux_state(Systemctl(missing=True)))

    def test_a_systemctl_that_never_answers_cannot_be_told(self):
        def stuck(command, **how):
            raise subprocess.TimeoutExpired(command, 4)
        self.assertIsNone(autostart._linux_state(stuck))

    def test_switching_enables_and_disables_the_service(self):
        run = Systemctl()
        self.assertEqual(autostart._linux_switch(True, run), "")
        self.assertEqual(autostart._linux_switch(False, run), "")
        self.assertEqual([command[2] for command in run.asked], ["enable", "disable"])
        self.assertTrue(all(command[-1] == autostart.SERVICE for command in run.asked))

    def test_a_refusal_is_said_with_its_reason(self):
        problem = autostart._linux_switch(
            True, Systemctl("", code=1, error="Failed to enable unit: Unit file does not exist."))
        self.assertIn("switch that on", problem)
        self.assertIn("Unit file does not exist", problem)

    def test_switching_without_systemd_says_it_cannot_be_told(self):
        self.assertEqual(autostart._linux_switch(True, Systemctl(missing=True)), autostart.CANT_TELL)

    @unittest.skipIf(config.WINDOWS, "asks systemctl only on Linux")
    def test_the_windows_ask_through_the_stand_in(self):
        self.assertIs(autostart.state(run=Systemctl("disabled", code=1)), False)
        run = Systemctl("")
        self.assertEqual(autostart.switch(True, run=run), "")
        self.assertEqual(run.asked, [["systemctl", "--user", "enable", autostart.SERVICE]])
        self.assertEqual(autostart.switch(False, run=Systemctl("", code=1)),
                         "The desktop wouldn't switch that off.")


class Windows(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.startup = os.path.join(self.folder.name, "Startup", autostart.SHORTCUT)
        self.menu = os.path.join(self.folder.name, "Programs", autostart.SHORTCUT)
        self.made = []

    def make(self, place):
        self.made.append(place)
        with open(place, "w") as f:
            f.write("made")

    def switch(self, on):
        return autostart._windows_switch(on, self.startup, self.menu, self.make)

    def test_the_shortcut_is_named_as_the_installer_names_it(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "install.ps1"), encoding="utf-8") as f:
            installer = f.read()
        self.assertIn('"$startup\\' + autostart.SHORTCUT + '"', installer)

    def test_it_starts_at_sign_in_when_the_shortcut_is_there(self):
        self.assertFalse(autostart._windows_state(self.startup))
        os.makedirs(os.path.dirname(self.startup))
        open(self.startup, "w").close()
        self.assertTrue(autostart._windows_state(self.startup))

    def test_switching_on_copies_the_start_menus_shortcut(self):
        os.makedirs(os.path.dirname(self.menu))
        with open(self.menu, "w") as f:
            f.write("the installer's")
        self.assertEqual(self.switch(True), "")
        with open(self.startup) as f:
            self.assertEqual(f.read(), "the installer's")
        self.assertEqual(self.made, [])

    def test_with_no_start_menu_shortcut_one_is_made(self):
        self.assertEqual(self.switch(True), "")
        self.assertEqual(self.made, [self.startup])

    def test_switching_off_removes_it_and_twice_is_fine(self):
        self.switch(True)
        self.assertEqual(self.switch(False), "")
        self.assertFalse(os.path.exists(self.startup))
        self.assertEqual(self.switch(False), "")

    def test_a_shortcut_that_cannot_be_made_is_said_not_raised(self):
        def refuse(place):
            raise OSError(13, "Access is denied")
        problem = autostart._windows_switch(True, self.startup, self.menu, refuse)
        self.assertIn("Startup folder", problem)
        self.assertIn("Access is denied", problem)

    def test_the_shortcut_is_made_as_the_installer_makes_it(self):
        written = SimpleNamespace(Save=lambda: self.made.append("saved"))
        shell = SimpleNamespace(CreateShortcut=lambda place: written)
        client = SimpleNamespace(Dispatch=lambda name: shell)
        with mock.patch.dict("sys.modules", {"win32com": SimpleNamespace(client=client),
                                             "win32com.client": client}), \
                mock.patch.object(config, "INSTALL_DIR", os.path.join("C:", "ls")):
            autostart.make_shortcut(self.startup)
        self.assertEqual(written.TargetPath,
                         os.path.join("C:", "ls", "venv", "Scripts", "pythonw.exe"))
        self.assertEqual(written.Arguments, "-m dictation.tray")
        self.assertEqual(written.WorkingDirectory, os.path.join("C:", "ls", "app"))
        self.assertEqual(written.IconLocation, os.path.join("C:", "ls", "linux-speaking.ico"))
        self.assertEqual(self.made, ["saved"])


if __name__ == "__main__":
    unittest.main()
