""""Click OK": pressing what the window in front shows, by its name."""
import unittest
from types import SimpleNamespace
from unittest import mock

from dictation import clicking
from dictation.commands import Command, Dictation, interpret
from dictation.settings import ITEMS, OPTIONS, Settings
from dictation.status import State

from tests.test_engine_telling import Quiet, bare

NAMES = ["&File", "Save", "Save As...", "Save All", "Don\u2019t Save", "Cancel", "OK",
         "Close tab", "Close", "Open...\tCtrl+O", "", "Yes, replace it"]


class WhichOneWasMeant(unittest.TestCase):
    def named(self, said):
        at = clicking.best(said, NAMES)
        return None if at is None else NAMES[at]

    def test_the_whole_name_however_it_is_written(self):
        self.assertEqual(self.named("OK"), "OK")
        self.assertEqual(self.named("file"), "&File")                 # the mark under a letter is no part of it
        self.assertEqual(self.named("open"), "Open...\tCtrl+O")       # nor the dots, nor the key after it
        self.assertEqual(self.named("don't save"), "Don\u2019t Save")
        self.assertEqual(self.named("dont save"), "Don\u2019t Save")
        self.assertEqual(self.named("yes replace it"), "Yes, replace it")

    def test_the_whole_name_before_one_that_only_starts_so(self):
        self.assertEqual(self.named("save"), "Save")
        self.assertEqual(self.named("close"), "Close")
        self.assertEqual(self.named("save as"), "Save As...")

    def test_then_the_start_of_a_name_and_then_words_inside_one(self):
        self.assertEqual(clicking.best("save", ["Save All", "Save As...", "Cancel"]), 1)   # the shorter of the two
        self.assertEqual(self.named("all"), "Save All")
        self.assertEqual(self.named("tab"), "Close tab")

    def test_what_nothing_is_called_is_not_found(self):
        for said in ("print", "sav", "", "os", "clos"):
            self.assertIsNone(clicking.best(said, NAMES), said)       # never part of a word


class TheWordsForIt(unittest.TestCase):
    def test_click_and_a_name(self):
        for said, name in (("Click OK.", "ok"), ("click the save button", "save"),
                           ("Click on Cancel", "cancel"), ("click don't save", "don't save"),
                           ("Click file", "file")):
            self.assertEqual(interpret(said, True), Command("click", name), said)

    def test_a_sentence_that_begins_with_click_is_a_sentence(self):
        for said in ("Click here to see more of what we have on offer today.", "Click, and it opens.",
                     "click", "Clicking is easy."):
            self.assertIsInstance(interpret(said, True), Dictation, said)

    def test_it_is_off_until_it_is_ticked(self):
        self.assertIn("click", [item.key for item in ITEMS])
        self.assertNotIn("click", OPTIONS)                            # something to say, when it is on
        settings = Settings()
        self.assertFalse(settings.enabled("click"))
        self.assertIsInstance(interpret("Click OK.", True, settings.disabled_commands()), Dictation)
        self.assertIsNone(interpret("click ok", False))               # and never while asleep


class SaidAloud(Quiet):
    def engine(self, reply=None, error=None):
        engine = bare(click=True)
        engine._last_typed = None
        engine.pressed = []

        def press(name):
            engine.pressed.append(name)
            if error:
                raise error
            return reply
        engine._presser = press
        return engine

    def test_what_is_there_is_pressed_and_nothing_is_typed(self):
        engine = self.engine({"ok": True, "kind": "pressed"})
        engine.handle_text("Click OK.", True)
        self.assertEqual(engine.pressed, ["ok"])
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])
        self.assertEqual(engine.notices, [])                          # what it did shows itself
        self.assertIs(engine.status.state, State.AWAKE)

    def test_what_is_not_there_was_only_words_and_is_typed(self):
        engine = self.engine({"ok": False, "why": "can't find that", "looked_at": 12})
        engine.handle_text("Click here to continue", True)
        self.assertEqual(engine.pressed, ["here to continue"])
        self.assertIn("insert", [op for op, _ in engine.targets.asked])

    def test_with_commands_only_what_is_not_there_is_not_typed_either(self):
        engine = self.engine({"ok": False, "why": "can't find that"})
        engine.status.commands_only = True
        engine.handle_text("Click here to continue", True)
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])

    def test_what_is_there_and_cannot_be_pressed_is_said_and_not_typed(self):
        engine = self.engine(error=clicking.CantClick("That is there, but it can't be pressed."))
        engine.handle_text("Click OK.", True)
        self.assertEqual(engine.notices, [("problem", "That is there, but it can't be pressed.")])
        self.assertNotIn("insert", [op for op, _ in engine.targets.asked])

    def test_whatever_goes_wrong_the_listening_goes_on(self):
        engine = self.engine(error=RuntimeError("the desktop fell over"))
        engine.handle_text("Click OK.", True)
        self.assertIs(engine.status.state, State.AWAKE)

    def test_the_log_is_told_what_kind_of_thing_it_was_and_never_its_name(self):
        engine = self.engine({"ok": True, "kind": "ticked"})
        with mock.patch("dictation.engine.log") as logged, \
                mock.patch.object(clicking, "in_front", lambda: "Notepad.exe"):
            engine.handle_text("click remember my choice", True)
        self.assertEqual(logged.call_args[0][0], "command click: ticked, in Notepad.exe")

    def test_switched_off_the_words_are_typed_and_nothing_is_asked_of_any_window(self):
        engine = self.engine({"ok": True})
        engine.settings.states = {}                                   # as it is to begin with
        engine.handle_text("Click OK.", True)
        self.assertEqual(engine.pressed, [])
        self.assertIn("insert", [op for op, _ in engine.targets.asked])


class Thing:
    """Stands in for something in a window, as the Linux accessibility service shows it."""

    def __init__(self, role, name="", children=(), showing=True, usable=True, can_press=True):
        self.role, self.name, self.children = role, name, list(children)
        self.showing, self.usable, self.can_press, self.pressed = showing, usable, can_press, 0

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, i):
        return self.children[i]

    def get_role_name(self):
        return self.role

    def get_name(self):
        return self.name

    def get_state_set(self):
        have = ({"SHOWING"} if self.showing else set()) | ({"SENSITIVE"} if self.usable else set())
        return SimpleNamespace(contains=lambda state: state in have)


class OnLinux(unittest.TestCase):
    ATSPI = SimpleNamespace(StateType=SimpleNamespace(SHOWING="SHOWING", SENSITIVE="SENSITIVE"))

    def test_only_what_shows_is_usable_and_has_a_name_can_be_meant(self):
        ok, greyed, hidden = Thing("push button", "OK"), Thing("push button", "Apply", usable=False), \
            Thing("push button", "Help", showing=False)
        window = Thing("frame", "A window", [
            Thing("panel", "", [ok, greyed, hidden, Thing("label", "OK"), Thing("push button", ""),
                                Thing("button", "Cancel")]),       # as newer versions name a button
            Thing("menu bar", "", [Thing("menu", "File", [Thing("menu item", "Open...")])])])
        found = []
        clicking._gather(self.ATSPI, window, found, 0)
        self.assertEqual([thing.name for thing in found], ["OK", "Cancel", "File", "Open..."])


if __name__ == "__main__":
    unittest.main()
