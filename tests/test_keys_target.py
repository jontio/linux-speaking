"""Typing into any text box on Windows: what is typed, with a pretend text box."""
import unittest

from dictation.formatting import LINE, PARAGRAPH
from dictation.keys_target import (READ, Box, KeysTarget, around, as_one_piece, box_kind, drawn_after,
                                   keystrokes, place_in, placed,
                                   program_name, takes_text_whole,
                                   right_to_left, says_empty, steps_for_insert,
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


class WholeTextTests(unittest.TestCase):
    """Windows' own edit boxes are handed the text whole, with no keys pressed."""

    def test_which_windows_take_it(self):
        for name in ("Edit", "RichEditD2DPT", "RICHEDIT50W", "RichEdit20W",
                     "WindowsForms10.EDIT.app.0.141b42a_r8_ad1", "WindowsForms10.RichEdit20W.app.0.1"):
            self.assertTrue(takes_text_whole(name), name)
        for name in ("Chrome_WidgetWin_1", "Scintilla", "_WwG", "ConsoleWindowClass", "Editor", ""):
            self.assertFalse(takes_text_whole(name), name)

    def test_line_breaks_as_an_edit_box_keeps_them(self):
        self.assertEqual(as_one_piece("one" + LINE + "two" + PARAGRAPH + "three"),
                         "one\r\ntwo\r\n\r\nthree")
        self.assertEqual(as_one_piece("a\nb\r\nc"), "a\r\nb\r\nc")
        self.assertEqual(as_one_piece(" this sucks"), " this sucks")


class EditBoxReadingTests(unittest.TestCase):
    """A box asked by message gives all its text and says where its selection is. What is
    before and after the cursor is worked out from that."""

    def read(self, text, first, last, kind):
        return around(*placed(text, first, last, kind))

    def test_which_windows_can_be_asked(self):
        self.assertEqual([box_kind(name) for name in ("Edit", "RichEditD2DPT", "RICHEDIT50W", "Scintilla",
                                                      "WindowsForms10.EDIT.app.0.1", "Chrome_WidgetWin_1", "")],
                         ["plain", "rich", "rich", "bytes", "plain", "", ""])

    def test_a_plain_box_counts_a_line_break_as_two(self):
        text = "First line.\r\nSecond line here"
        at = text.index("line here")
        self.assertEqual(self.read(text, at, at, "plain"), ("First line.\r\nSecond ", "line here", ""))

    def test_a_rich_box_counts_it_as_one_though_it_gives_back_two(self):
        text = "First line.\r\nSecond line here"     # as given back
        at = len("First line.\rSecond ")                # as the box counts
        self.assertEqual(self.read(text, at, at, "rich"), ("First line.\rSecond ", "line here", ""))
        self.assertEqual(self.read("One.\r\n\r\nTwo", 6, 6, "rich"), ("One.\r\r", "Two", ""))

    def test_one_that_counts_in_bytes(self):
        text = "Caf\u00e9 \u2014 na\u00efve words"       # the accented letters and the dash are 2 and 3 bytes
        at = len("Caf\u00e9 \u2014 na\u00efve ".encode("utf-8"))
        self.assertEqual(self.read(text, at, at, "bytes"), ("Caf\u00e9 \u2014 na\u00efve ", "words", ""))
        self.assertEqual(self.read("plain words", 6, 6, "bytes"), ("plain ", "words", ""))
        self.assertEqual(place_in(text, len("Caf\u00e9 \u2014 "), "bytes"), len("Caf\u00e9 \u2014 ".encode("utf-8")))
        self.assertEqual(place_in(text, 5, "rich"), 5)

    def test_a_selection(self):
        self.assertEqual(self.read("say hello now", 4, 9, "rich"), ("say ", " now", "hello"))

    def test_the_cursor_at_either_end_and_places_that_make_no_sense(self):
        self.assertEqual(self.read("abc", 0, 0, "plain"), ("", "abc", ""))
        self.assertEqual(self.read("abc", 3, 3, "plain"), ("abc", "", ""))
        self.assertEqual(self.read("abc", 9, 2, "plain"), ("abc", "", ""))
        self.assertEqual(self.read("", 0, 0, "rich"), ("", "", ""))

    def test_only_so_much_each_side(self):
        before, after, selected = self.read("x" * 5000, 2500, 2500, "plain")
        self.assertEqual((len(before), len(after), selected), (READ, READ, ""))


class KeystrokeTests(unittest.TestCase):
    """Text typed as presses of the keys that make it, as a keyboard would send it."""

    @staticmethod
    def lookup(c):
        # A keyboard with letters, a space, a comma, and "?" and capitals on Shift.
        if c.isascii() and c.isalpha():
            return ord(c.upper()), int(c.isupper())
        return {" ": (0x20, 0), ",": (0xBC, 0), "?": (0xBF, 1), "@": (0x32, 6)}.get(c)

    def test_letters_and_shift(self):
        self.assertEqual(keystrokes("Ok, a?", self.lookup),
                         [("key", ord("O"), True), ("key", ord("K"), False), ("key", 0xBC, False),
                          ("key", 0x20, False), ("key", ord("A"), False), ("key", 0xBF, True)])

    def test_a_character_the_keyboard_has_not_got_is_sent_as_itself(self):
        self.assertEqual(keystrokes("a\u2019b\u00e9", self.lookup),
                         [("key", ord("A"), False), ("char", "\u2019"), ("key", ord("B"), False),
                          ("char", "\u00e9")])

    def test_one_that_needs_ctrl_or_alt_is_sent_as_itself(self):
        self.assertEqual(keystrokes("@", self.lookup), [("char", "@")])

    def test_caps_lock_turns_shift_round_for_letters_only(self):
        self.assertEqual(keystrokes("Ok?", self.lookup, caps=True),
                         [("key", ord("O"), False), ("key", ord("K"), True), ("key", 0xBF, True)])

    def test_nothing(self):
        self.assertEqual(keystrokes("", self.lookup), [])


class EmptyBoxTests(unittest.TestCase):
    """A browser gives an empty box's hint, or its name, as if it were its text. The
    box's own account of what is in it settles whether anything has been typed."""

    def test_nothing_typed(self):
        self.assertTrue(says_empty(""))
        self.assertTrue(says_empty("\n"))
        self.assertTrue(says_empty("\ufeff\r\n"))

    def test_something_typed(self):
        self.assertFalse(says_empty("Hello"))
        self.assertFalse(says_empty(" "))      # a space is something typed
        self.assertFalse(says_empty("\nHello"))

    def test_a_box_that_gives_no_account_is_not_called_empty(self):
        self.assertFalse(says_empty(None))


class HintTests(unittest.TestCase):
    """A hint in an empty box is read as text before the cursor, but it is drawn after
    it. The numbers are (left, top, width, height) on the screen."""

    CURSOR = (805, 974, 1, 20)

    def test_a_hint_starts_at_the_cursor_and_runs_on(self):
        # As a chat box gave it: the hint, and a speck on the line below.
        self.assertTrue(drawn_after(self.CURSOR, [(805, 974, 94, 20), (805, 1007, 1, 1)]))

    def test_typed_text_ends_at_the_cursor(self):
        self.assertFalse(drawn_after((899, 974, 1, 20), [(805, 974, 94, 20)]))
        self.assertFalse(drawn_after((899, 974, 1, 20), [(805, 974, 96, 20)]))  # near enough

    def test_lines_above_the_cursor_reach_further_right_and_are_still_before_it(self):
        above = [(805, 950, 600, 20), (805, 974, 40, 20)]
        self.assertFalse(drawn_after((845, 974, 1, 20), above))
        self.assertFalse(drawn_after((805, 994, 1, 20), above))    # at the start of a new line

    def test_anything_left_of_the_cursor_on_its_line_means_typed_text(self):
        # Whatever else is reported, text to the left of the cursor was typed.
        self.assertFalse(drawn_after((850, 974, 1, 20), [(805, 974, 94, 20)]))
        self.assertFalse(drawn_after((850, 974, 1, 20), [(805, 974, 45, 20), (850, 974, 60, 20)]))

    def test_a_hint_set_in_from_the_cursor(self):
        self.assertTrue(drawn_after(self.CURSOR, [(812, 975, 150, 18)]))

    def test_nothing_to_go_on(self):
        self.assertFalse(drawn_after(self.CURSOR, []))
        self.assertFalse(drawn_after(self.CURSOR, [(0, 0, 1, 0)]))  # a place that isn't one
        self.assertFalse(drawn_after((805, 974, 0, 0), [(805, 974, 94, 20)]))

    def test_right_to_left_writing_is_left_alone(self):
        self.assertTrue(right_to_left("\u05e9\u05dc\u05d5\u05dd"))
        self.assertTrue(right_to_left("abc \u0645\u0631\u062d\u0628\u0627"))
        self.assertFalse(right_to_left("Type a message"))


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

    def test_characters_nobody_sees_are_not_text_before_the_cursor(self):
        # An empty line in some chat boxes holds one: it must not earn a space.
        self.box = Box("\ufeff", "\u200b", "", "x.exe")
        self.assertEqual(self.target.request({"op": "context"}),
                         {"ok": True, "before": "", "after": ""})
        self.box = Box("Hello\u200b", "", "", "x.exe")
        self.assertEqual(self.target.request({"op": "context"})["before"], "Hello")

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
