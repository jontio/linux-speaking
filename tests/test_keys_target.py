"""Typing into any text box on Windows: what is typed, with a pretend text box."""
import unittest

from dictation.formatting import LINE, PARAGRAPH
from dictation.keys_target import (Box, KeysTarget, program_name, steps_for_insert,
                                   steps_for_text, typed_length)


class StepsTests(unittest.TestCase):
    def test_plain_words_are_typed(self):
        self.assertEqual(steps_for_text("hello there"), [("type", "hello there")])

    def test_breaks_are_shift_enter_so_a_chat_box_doesnt_send(self):
        self.assertEqual(steps_for_text("a" + LINE + "b" + PARAGRAPH + "c"), [
            ("type", "a"), ("press", "shift+enter", 1), ("type", "b"),
            ("press", "shift+enter", 2), ("type", "c")])

    def test_a_tab_is_the_tab_key(self):
        self.assertEqual(steps_for_text("\t"), [("press", "tab", 1)])

    def test_deleting_comes_first(self):
        self.assertEqual(steps_for_insert(" Hi", 2, 1, selected=True), [
            ("press", "backspace", 1), ("press", "backspace", 2), ("press", "delete", 1),
            ("type", " Hi")])

    def test_how_many_backspaces_take_it_away(self):
        self.assertEqual(typed_length("abc"), 3)
        self.assertEqual(typed_length("a" + PARAGRAPH + "b"), 4)
        self.assertEqual(typed_length("\U0001F600"), 2)

    def test_program_names(self):
        self.assertEqual(program_name("Code.exe"), "VS Code")
        self.assertEqual(program_name("notepad.exe"), "Notepad")
        self.assertEqual(program_name("someapp.exe"), "Someapp")


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.box = Box("Hello ", "", "", "Code.exe")
        self.typed = []
        self.on = True
        self.target = KeysTarget(lambda: self.on, look=lambda: self.box, press=self.typed.append)

    def ask(self, **message):
        return self.target.request(message)

    def test_off_unless_the_setting_is_on(self):
        self.on = False
        self.assertEqual(self.ask(op="status"), {"ok": True, "ready": False})
        self.assertEqual(self.ask(op="insert", text="x")["why"], "editor not focused")
        self.assertEqual(self.typed, [])

    def test_not_ready_without_a_text_box(self):
        self.box = None
        self.assertFalse(self.ask(op="status")["ready"])
        self.assertEqual(self.ask(op="context")["why"], "editor not focused")

    def test_status_names_the_program(self):
        self.assertTrue(self.ask(op="status")["ready"])
        self.assertEqual(self.target.name, "VS Code")

    def test_context_is_the_cursors_own_line(self):
        self.box = Box("First line\r\nsecond ", " rest\nmore", "", "x.exe")
        self.assertEqual(self.ask(op="context"), {"ok": True, "before": "second ", "after": " rest"})
        self.box = Box("a ", " c", "b", "x.exe")
        self.assertTrue(self.ask(op="context")["selected"])

    def test_insert_types(self):
        self.ask(op="insert", text="world", delete_before=1)
        self.assertEqual(self.typed, [[("press", "backspace", 1), ("type", "world")]])

    def test_scratch_takes_back_the_last_phrase(self):
        self.ask(op="insert", text="world.")
        self.box = Box("Hello world.", "", "", "Code.exe")
        self.assertTrue(self.ask(op="command", name="scratch")["ok"])
        self.assertEqual(self.typed[-1], [("press", "backspace", 6)])
        self.assertEqual(self.ask(op="command", name="scratch")["why"], "nothing to scratch")

    def test_scratch_refuses_if_the_cursor_has_moved(self):
        self.ask(op="insert", text="world.")
        self.box = Box("Somewhere else", "", "", "Code.exe")
        self.assertEqual(self.ask(op="command", name="scratch")["why"], "nothing to scratch")

    def test_commands_are_keys(self):
        self.ask(op="command", name="press_enter")
        self.ask(op="command", name="word_left", arg="3")
        self.ask(op="command", name="select_all")
        self.ask(op="command", name="delete_line")
        self.assertEqual(self.typed, [
            [("press", "enter", 1)], [("press", "ctrl+left", 3)], [("press", "ctrl+a", 1)],
            [("press", "home", 1), ("press", "shift+end", 1), ("press", "backspace", 1)]])

    def test_new_line_is_fitted_and_typed(self):
        self.ask(op="command", name="new_line")
        self.assertIn(("press", "shift+enter", 1), self.typed[-1])

    def test_caps_on_a_selection(self):
        self.box = Box("say ", " now", "hello", "x.exe")
        self.ask(op="command", name="all_caps")
        self.assertEqual(self.typed, [[("type", "HELLO")]])

    def test_unknown_things(self):
        self.assertEqual(self.ask(op="command", name="go_to_line", arg="3")["why"], "unknown command")
        self.assertEqual(self.ask(op="move", steps=[])["why"], "unknown request")
        self.assertEqual(self.ask(op="command", name="bold")["why"], "plain text has no formatting")


if __name__ == "__main__":
    unittest.main()
