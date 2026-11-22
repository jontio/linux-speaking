"""Typing into any text box on Windows: what is typed, with a pretend text box."""
import unittest
from unittest import mock

from dictation.formatting import LINE, PARAGRAPH
from dictation.keys_target import (READ, Box, KeysTarget, around, as_one_piece, box_kind, drawn_after,
                                   keystrokes, left_between, place_in, placed,
                                   program_name, takes_text_whole,
                                   right_to_left, says_empty, steps_for_insert,
                                   arrow_length, presses, steps_back, steps_for_text, typed_length)


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


class StepsBackTests(unittest.TestCase):
    """The arrow keys after "correct ...". The words chosen ran from 4 to 7, and four
    characters were typed in their place."""

    def test_right_for_a_cursor_that_was_after_the_words(self):
        self.assertEqual(steps_back(22, 4, 7, 4), [("press", "right", 15)])
        self.assertEqual(steps_back(8, 4, 7, 4), [("press", "right", 1)])

    def test_left_for_one_that_was_before_them(self):
        self.assertEqual(steps_back(0, 4, 7, 4), [("press", "left", 8)])
        self.assertEqual(steps_back(4, 4, 7, 4), [("press", "left", 4)])

    def test_nothing_for_one_that_was_among_them_or_right_after(self):
        self.assertEqual(steps_back(7, 4, 7, 4), [])
        self.assertEqual(steps_back(5, 4, 7, 4), [])

    def test_what_was_deleted_beside_the_words(self):
        self.assertEqual(steps_back(22, 4, 7, 4, delete_after=1), [("press", "right", 14)])
        self.assertEqual(steps_back(8, 4, 7, 4, delete_after=1), [])
        self.assertEqual(steps_back(0, 4, 7, 4, delete_before=1), [("press", "left", 7)])
        self.assertEqual(steps_back(4, 4, 7, 4, delete_before=1), [("press", "left", 4)])

    def test_presses(self):
        self.assertEqual(presses("one\r\ntwo\nthree"), 13)
        self.assertEqual(presses(""), 0)
        self.assertEqual(presses("\U0001f600"), 1)                       # a face
        self.assertEqual(presses("\U0001f44d\U0001f3fd"), 1)             # a thumb with a skin tone
        self.assertEqual(presses("e\u0301"), 1)                          # a letter and its accent
        self.assertEqual(presses("\U0001f468\u200d\U0001f469\u200d\U0001f467"), 1)  # a family
        self.assertEqual(presses("\U0001f1f3\U0001f1ff\U0001f1eb\U0001f1f7"), 2)     # two flags
        self.assertEqual(presses("\u2764\ufe0f ok"), 4)                  # a heart, drawn in colour

    def test_how_far_back_across_what_was_typed(self):
        self.assertEqual(arrow_length("lion"), 4)
        self.assertEqual(arrow_length("\U0001f600 ok"), 4)
        self.assertEqual(arrow_length("one" + LINE + "two" + PARAGRAPH + "x"), 10)


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

    def test_a_phrase_taken_out_whole_by_the_next_is_no_longer_scratched(self):
        self.box = Box("Hello world", "", "", "Code.exe")
        self.ask(op="insert", text=".")                         # a stop typed for the time being
        self.box = Box("Hello world.", "", "", "Code.exe")
        self.ask(op="insert", text=" and more", delete_before=1)   # the next phrase takes it out
        self.box = Box("Hello world and more", "", "", "Code.exe")
        self.assertTrue(self.ask(op="command", name="scratch")["ok"])
        self.assertEqual(self.typed[-1], [("press", "backspace", 9)])
        self.assertEqual(self.target.history, [])

    def test_the_web_boxes_keep_the_programs_own_line_breaks(self):
        from dictation.formatting import LINE, PARAGRAPH
        from dictation.portal_keys import typable
        self.assertEqual(typable("One" + PARAGRAPH + "two" + LINE + "three"), "One" + PARAGRAPH + "two" + LINE + "three")

    def test_a_phrase_ending_in_a_line_break_is_only_scratched_where_it_is(self):
        from dictation.formatting import PARAGRAPH
        self.box = Box("Dear Sam,\nThe meeting moved to Thursday. ", "", "", "Code.exe")
        self.ask(op="insert", text="I will send it" + PARAGRAPH)
        self.box = Box("Dear Sam,\nThe meeting moved to Thursday", " at the usual place.", "", "Code.exe")
        self.assertEqual(self.ask(op="command", name="scratch")["why"], "nothing to scratch")
        self.ask(op="insert", text="I will send it" + PARAGRAPH)
        self.box = Box("Dear Sam,\nThe meeting moved to Thursday. I will send it\r\n\r\n", "", "", "Code.exe")
        self.assertTrue(self.ask(op="command", name="scratch")["ok"])

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

    def test_redo_is_the_key_this_system_uses_for_it(self):
        import os
        self.assertTrue(self.ask(op="command", name="redo")["ok"])
        self.assertEqual(self.typed, [[("press", "ctrl+y" if os.name == "nt" else "ctrl+shift+z", 1)]])
        self.typed.clear()
        self.ask(op="command", name="undo")
        self.assertEqual(self.typed, [[("press", "ctrl+z", 1)]])

    def test_delete_several_lines(self):
        self.ask(op="command", name="delete_line", arg="3")
        self.assertEqual(self.typed, [[("press", "home", 1), ("press", "shift+down", 2),
                                       ("press", "shift+end", 1), ("press", "backspace", 1)]])
        self.typed.clear()
        self.ask(op="command", name="select_line", arg="3")       # one line only, whatever is said
        self.assertEqual(self.typed, [[("press", "home", 1), ("press", "shift+end", 1)]])

    def test_new_line_is_fitted_and_typed(self):
        self.ask(op="command", name="new_line")
        self.assertIn(("press", "shift+enter", 1), self.typed[-1])

    def test_caps_on_a_selection(self):
        self.box = Box("say ", " now", "hello", "x.exe")
        self.ask(op="command", name="all_caps")
        self.assertEqual(self.typed, [[("type", "HELLO")]])

    # "Correct ...": the program's text can't be selected through the stand-in, so the
    # words are said to have been chosen, as selecting them would.
    TEXT = "the cat sat on the mat"

    def chosen(self, mark, found=(4, 7), text=TEXT):
        self.target._chose(text, mark, found)
        self.box = Box(text[:found[0]], text[found[1]:], text[found[0]:found[1]], "x.exe")

    def test_after_correct_the_cursor_goes_back_to_the_end(self):
        self.chosen(mark=22)
        reply = self.ask(op="insert", text="lion")
        self.assertTrue(reply["back"])
        self.assertEqual(self.typed, [[("press", "backspace", 1), ("type", "lion")],
                                      [("press", "right", 15)]])

    def test_after_correct_the_cursor_goes_back_to_before_the_words(self):
        self.chosen(mark=0)
        self.ask(op="insert", text="lion")
        self.assertEqual(self.typed[-1], [("press", "left", 8)])

    def test_correcting_the_word_the_cursor_is_right_after_leaves_it_after_the_new_one(self):
        self.chosen(mark=22, found=(19, 22))
        self.assertTrue(self.ask(op="insert", text="rug").get("back"))
        self.assertEqual(self.typed, [[("press", "backspace", 1), ("type", "rug")]])

    def test_only_the_next_thing_said_goes_back(self):
        self.chosen(mark=22)
        self.ask(op="insert", text="lion")
        self.box = Box("the lion sat on the mat", "", "", "x.exe")
        self.assertFalse(self.ask(op="insert", text=" again").get("back"))
        self.assertEqual(self.typed[-1], [("type", " again")])

    def test_no_going_back_if_other_words_are_selected_by_then(self):
        self.chosen(mark=22)
        self.box = Box("the cat sat on the ", "", "mat", "x.exe")
        self.assertFalse(self.ask(op="insert", text="rug").get("back"))
        self.assertEqual(len(self.typed), 1)
        # The same word somewhere else in the text is not the one that was chosen.
        self.chosen(mark=22)
        self.box = Box("a different ", " here", "cat", "x.exe")
        self.assertFalse(self.ask(op="insert", text="dog").get("back"))

    def test_unselect_after_correct_goes_back_too(self):
        self.chosen(mark=22)
        self.ask(op="command", name="unselect")
        self.assertEqual(self.typed, [[("press", "right", 1)], [("press", "right", 15)]])
        self.typed.clear()
        self.chosen(mark=0)
        self.ask(op="command", name="unselect")
        self.assertEqual(self.typed, [[("press", "right", 1)], [("press", "left", 7)]])
        self.typed.clear()
        self.box = Box("a ", " c", "b", "x.exe")      # selected some other way
        self.ask(op="command", name="unselect")
        self.assertEqual(self.typed, [[("press", "right", 1)]])

    def test_a_line_break_is_one_press_however_it_is_written(self):
        text = "the cat sat\r\non the mat\r\nand more"
        self.chosen(mark=len(text), text=text)
        self.ask(op="insert", text="lion")
        self.assertEqual(self.typed[-1], [("press", "right", len("sat\non the mat\nand more") + 1)])

    def test_too_far_to_go_back_one_key_at_a_time(self):
        text = "the cat sat " + "and sat " * 50
        self.chosen(mark=len(text), text=text)
        reply = self.ask(op="insert", text="lion")
        self.assertEqual((reply.get("back"), reply.get("too_far")), (None, True))
        self.assertEqual(len(self.typed), 1)          # the words, and no arrow keys

    def test_further_where_keys_go_in_a_burst_but_not_without_end(self):
        self.target._paced = lambda: False
        text = "the cat sat " + "and sat " * 50
        self.chosen(mark=len(text), text=text)
        self.assertTrue(self.ask(op="insert", text="lion").get("back"))
        self.assertEqual(self.typed[-1], [("press", "right", len(text) - 7)])
        text = "the cat sat " + "and sat " * 500
        self.chosen(mark=len(text), text=text)
        self.assertTrue(self.ask(op="insert", text="lion").get("too_far"))

    def test_any_other_command_ends_it(self):
        self.chosen(mark=22)
        self.ask(op="command", name="all_caps")
        self.assertIsNone(self.ask(op="insert", text="lion").get("back"))
        self.chosen(mark=22)
        self.ask(op="command", name="cancel_choices")   # sent to every program at once
        self.assertTrue(self.ask(op="insert", text="lion").get("back"))

    def test_an_arrow_key_crosses_a_character_as_it_is_seen(self):
        text = "the cat sat \U0001f44d\U0001f3fd ok cafe\u0301 \U0001f1f3\U0001f1ff"
        self.chosen(mark=len(text), text=text)
        self.ask(op="insert", text="\U0001f600")
        self.assertEqual(self.typed[-1], [("press", "right", len(" sat X ok cafe F"))])
        self.chosen(mark=0, text=text)
        self.ask(op="insert", text="\U0001f600")
        self.assertEqual(self.typed[-1], [("press", "left", 5)])

    def test_unknown_things(self):
        self.assertEqual(self.ask(op="command", name="go_to_line", arg="3")["why"], "unknown command")
        self.assertEqual(self.ask(op="move", steps=[])["why"], "unknown request")
        self.assertEqual(self.ask(op="command", name="bold")["why"], "plain text has no formatting")


class ScratchPutsBackTests(unittest.TestCase):
    """ "Scratch that" after a phrase was said over selected words: the phrase goes, and
    the words are typed again in its place and selected as they were."""

    TEXT = "the cat sat on the mat"

    def setUp(self):
        self.box = Box("the ", " sat on the mat", "cat", "x.exe")
        self.typed = []
        self.target = KeysTarget(lambda: True, look=lambda: self.box, press=self.typed.append)

    def ask(self, **message):
        return self.target.request(message)

    def chosen(self, mark, found=(4, 7), text=TEXT):
        self.target._chose(text, mark, found)
        self.box = Box(text[:found[0]], text[found[1]:], text[found[0]:found[1]], "x.exe")

    def test_after_words_were_selected(self):
        self.ask(op="insert", text="lion")
        self.box = Box("the lion", " sat on the mat", "", "x.exe")
        reply = self.ask(op="command", name="scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, True))
        self.assertEqual(self.typed[-1], [("press", "backspace", 4), ("type", "cat"),
                                          ("press", "shift+left", 3)])
        self.assertIsNone(self.target._correction)

    def test_the_space_taken_out_beside_them_comes_back_and_is_not_selected(self):
        self.ask(op="insert", text="lion,", delete_after=1)
        self.box = Box("the lion,", "sat on the mat", "", "x.exe")
        self.ask(op="command", name="scratch")
        self.assertEqual(self.typed[-1], [("press", "backspace", 5), ("type", "cat "),
                                          ("press", "left", 1), ("press", "shift+left", 3)])
        self.box = Box("the cat ", " on the mat", "sat", "x.exe")
        self.ask(op="insert", text=",", delete_before=1)
        self.box = Box("the cat,", " on the mat", "", "x.exe")
        self.ask(op="command", name="scratch")
        self.assertEqual(self.typed[-1], [("press", "backspace", 1), ("type", " sat"),
                                          ("press", "shift+left", 3)])

    def test_after_correct_the_cursor_is_taken_to_the_phrase_first(self):
        self.chosen(mark=22)
        self.ask(op="insert", text="lion")
        self.assertEqual(self.typed[-1], [("press", "right", 15)])
        self.box = Box("the lion sat on the mat", "", "", "x.exe")
        self.assertTrue(self.ask(op="command", name="scratch").get("restored"))
        self.assertEqual(self.typed[-1], [("press", "left", 15), ("press", "backspace", 4),
                                          ("type", "cat"), ("press", "shift+left", 3)])
        # The words are chosen as "correct ..." left them: said again, the cursor goes back.
        self.box = Box("the ", " sat on the mat", "cat", "x.exe")
        self.assertTrue(self.ask(op="insert", text="tiger").get("back"))
        self.assertEqual(self.typed[-1], [("press", "right", 15)])

    def test_after_correct_with_the_cursor_before_the_words(self):
        self.chosen(mark=0)
        self.ask(op="insert", text="lion")
        self.box = Box("", "the lion sat on the mat", "", "x.exe")
        self.assertTrue(self.ask(op="command", name="scratch").get("restored"))
        self.assertEqual(self.typed[-1], [("press", "right", 8), ("press", "backspace", 4),
                                          ("type", "cat"), ("press", "shift+left", 3)])
        self.box = Box("the ", " sat on the mat", "cat", "x.exe")
        self.assertTrue(self.ask(op="insert", text="tiger").get("back"))
        self.assertEqual(self.typed[-1], [("press", "left", 9)])

    def test_after_correct_of_the_word_right_before_the_cursor(self):
        self.chosen(mark=22, found=(19, 22))
        self.ask(op="insert", text="rug")
        self.box = Box("the cat sat on the rug", "", "", "x.exe")
        self.assertTrue(self.ask(op="command", name="scratch").get("restored"))
        self.assertEqual(self.typed[-1], [("press", "backspace", 3), ("type", "mat"),
                                          ("press", "shift+left", 3)])
        self.box = Box("the cat sat on the ", "", "mat", "x.exe")
        self.assertTrue(self.ask(op="insert", text="carpet").get("back"))

    def test_not_if_the_cursor_or_the_text_has_moved_since(self):
        self.chosen(mark=22)
        self.ask(op="insert", text="lion")
        keys = len(self.typed)
        self.box = Box("the lion sat on the mat and more", "", "", "x.exe")
        self.assertEqual(self.ask(op="command", name="scratch")["why"], "nothing to scratch")
        self.assertEqual(len(self.typed), keys)       # and no key was pressed

    def test_the_phrase_is_the_one_that_was_said_not_the_same_word_before_the_cursor(self):
        # "the" (the second one) is said again as "mat": the text now ends "mat mat", and
        # the one to take back is the first of those.
        self.chosen(mark=22, found=(15, 18))
        self.ask(op="insert", text="mat")
        self.box = Box("the cat sat on mat mat", "", "", "x.exe")
        self.ask(op="command", name="scratch")
        self.assertEqual(self.typed[-1], [("press", "left", 4), ("press", "backspace", 3),
                                          ("type", "the"), ("press", "shift+left", 3)])

    def test_too_far_to_go_back_leaves_the_cursor_after_the_phrase_and_it_is_put_back_there(self):
        text = "the cat sat " + "and sat " * 50
        self.chosen(mark=len(text), text=text)
        self.assertTrue(self.ask(op="insert", text="lion").get("too_far"))
        self.box = Box("the lion", text[7:], "", "x.exe")
        self.assertTrue(self.ask(op="command", name="scratch").get("restored"))
        self.assertEqual(self.typed[-1], [("press", "backspace", 4), ("type", "cat"),
                                          ("press", "shift+left", 3)])

    def test_words_that_would_not_be_the_same_typed_again_are_not_kept(self):
        for selected in ("one\ttwo", "one\r\ntwo", "see \ufffc here", "x" * 301):
            self.target.history.clear()
            self.box = Box("a ", " c", selected, "x.exe")
            self.ask(op="insert", text="b")
            self.box = Box("a b", " c", "", "x.exe")
            reply = self.ask(op="command", name="scratch")
            self.assertEqual((reply.get("ok"), reply.get("restored")), (True, None), selected[:8])
            self.assertEqual(self.typed[-1], [("press", "backspace", 1)])

    def test_a_long_selection_is_kept_where_keys_go_in_a_burst(self):
        self.target._paced = lambda: False
        self.box = Box("a ", " c", "x" * 301, "x.exe")
        self.ask(op="insert", text="b")
        self.box = Box("a b", " c", "", "x.exe")
        self.assertTrue(self.ask(op="command", name="scratch").get("restored"))

    def test_a_phrase_that_took_nothings_place_only_goes(self):
        self.box = Box("Hello ", "", "", "x.exe")
        self.ask(op="insert", text="world.")
        self.box = Box("Hello world.", "", "", "x.exe")
        reply = self.ask(op="command", name="scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, None))
        self.assertEqual(self.typed[-1], [("press", "backspace", 6)])

    def test_caps_on_the_last_phrase_still_works_and_then_it_only_goes(self):
        self.ask(op="insert", text="lion")
        self.box = Box("the lion", " sat on the mat", "", "x.exe")
        self.ask(op="command", name="all_caps")
        self.box = Box("the LION", " sat on the mat", "", "x.exe")
        self.assertIsNone(self.ask(op="command", name="scratch").get("restored"))
        self.assertEqual(self.typed[-1], [("press", "backspace", 4)])


class LeftBetweenTests(unittest.TestCase):
    TEXT = "the cat sat on the mat"

    def test_a_cursor_that_was_after_the_words(self):
        self.assertEqual(left_between((self.TEXT, 22, 4, 7)), ("after", " sat on the mat"))
        self.assertEqual(left_between((self.TEXT, 22, 4, 7), delete_after=1), ("after", "sat on the mat"))

    def test_one_that_was_before_them(self):
        self.assertEqual(left_between((self.TEXT, 0, 4, 7)), ("before", "the "))
        self.assertEqual(left_between((self.TEXT, 0, 4, 7), delete_before=1), ("before", "the"))
        self.assertEqual(left_between((self.TEXT, 4, 4, 7), delete_before=1), ("before", ""))

    def test_one_that_is_left_right_at_their_end(self):
        self.assertIsNone(left_between((self.TEXT, 7, 4, 7)))
        self.assertIsNone(left_between((self.TEXT, 5, 4, 7)))
        self.assertIsNone(left_between((self.TEXT, 8, 4, 7), delete_after=1))


class _EditBox:
    """Stands in for one of Windows' own edit boxes, and for the messages it answers."""

    def __init__(self, text, first, last=None):
        self.text, self.first, self.last = text, first, first if last is None else last
        self.asked, self.reads, self.late = [], 0, None

    # What dictation.winapi offers.
    def edit_text(self, window, most):
        self.reads += 1
        if self.late and self.reads <= self.late[0]:
            return self.late[1]               # the keys haven't all been taken in yet
        return self.text, self.first, self.last

    def select_in_edit(self, window, first, last):
        self.asked.append((first, last))
        self.first, self.last = first, last
        return True

    def tap_shift(self, window):
        pass

    # The keys that reach it.
    def press(self, steps):
        for step in steps:
            if step[0] == "type":
                self.put(step[1])
            elif step[1] == "backspace":
                if self.first == self.last:
                    self.first = max(0, self.first - step[2])
                self.put("")
            elif step[1] == "delete":
                self.last = self.first + step[2]
                self.put("")
            elif step[1] == "shift+enter":
                self.put("\r\n" * step[2])
            else:
                raise AssertionError(f"an arrow key was pressed: {step}")

    def put(self, new):
        self.text = self.text[:self.first] + new + self.text[self.last:]
        self.first = self.last = self.first + len(new)


class EditBoxCorrectTests(unittest.TestCase):
    """In a box that is asked by message the cursor is put straight back, however far."""

    TEXT = "the cat sat on the mat\r\n" + "and more\r\n" * 500 + "the end"

    def setUp(self):
        self.edit = _EditBox(self.TEXT, len(self.TEXT))
        self.target = KeysTarget(lambda: True, look=self.look, press=self.edit.press)
        import dictation
        for patch in (mock.patch.dict("sys.modules", {"dictation.winapi": self.edit}),
                      mock.patch.object(dictation, "winapi", self.edit, create=True),
                      mock.patch("dictation.keys_target.SETTLE", 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def look(self):
        e = self.edit
        return Box(e.text[:e.first], e.text[e.last:], e.text[e.first:e.last], "notepad.exe")

    def correct(self, start, end):
        """As "correct ..." leaves things once it has selected the words from start to end."""
        self.target._chose(self.edit.text, self.edit.first, (start, end), (7, "plain"))
        self.edit.first, self.edit.last = start, end

    def test_back_to_the_end_of_a_long_text(self):
        self.correct(4, 7)
        reply = self.target.request({"op": "insert", "text": "lion", "delete_before": 0, "delete_after": 1})
        self.assertTrue(reply["back"])
        self.assertTrue(self.edit.text.startswith("the lionsat on the mat\r\nand more"))
        self.assertEqual((self.edit.first, self.edit.last), (len(self.edit.text),) * 2)
        self.assertEqual(len(self.edit.text), len(self.TEXT))

    def test_back_to_a_place_before_the_words(self):
        self.edit.first = self.edit.last = 2
        at = self.TEXT.rindex("end")
        self.correct(at, at + 3)
        self.assertTrue(self.target.request({"op": "insert", "text": "finish"}).get("back"))
        self.assertTrue(self.edit.text.endswith("the finish"))
        self.assertEqual((self.edit.first, self.edit.last), (2, 2))

    def test_the_word_the_cursor_is_right_after(self):
        at = self.TEXT.rindex("end")
        self.correct(at, at + 3)
        self.target.request({"op": "insert", "text": "finish"})
        self.assertEqual(self.edit.first, len(self.edit.text))
        self.assertTrue(self.edit.text.endswith("the finish"))

    def test_it_waits_until_the_words_have_all_gone_in(self):
        self.correct(4, 7)
        half = self.TEXT[:4] + "li" + self.TEXT[7:]     # as the box is with typing under way
        self.edit.late = (3, (half, 6, 6))
        self.assertTrue(self.target.request({"op": "insert", "text": "lion"}).get("back"))
        self.assertEqual((self.edit.reads, self.edit.first), (4, len(self.edit.text)))
        self.assertEqual(self.edit.asked, [(len(self.edit.text),) * 2])

    def test_not_if_the_box_never_holds_what_it_should(self):
        self.correct(4, 7)
        self.edit.late = (10 ** 6, (self.TEXT[:4] + "liXon" + self.TEXT[7:], 9, 9))
        reply = self.target.request({"op": "insert", "text": "lion"})
        self.assertEqual((reply.get("back"), reply.get("too_far"), self.edit.asked), (None, True, []))

    def test_a_line_break_in_the_new_words(self):
        self.correct(4, 7)
        self.assertTrue(self.target.request({"op": "insert", "text": "big" + LINE + "lion"}).get("back"))
        self.assertTrue(self.edit.text.startswith("the big\r\nlion sat on"))
        self.assertEqual(self.edit.first, len(self.edit.text))

    def test_unselect_goes_straight_back(self):
        self.correct(4, 7)
        self.target.request({"op": "command", "name": "unselect"})
        self.assertEqual((self.edit.first, self.edit.last), (len(self.TEXT),) * 2)

    def test_not_if_other_words_are_selected_by_then(self):
        self.correct(4, 7)
        self.edit.first, self.edit.last = 8, 11
        self.assertFalse(self.target.request({"op": "insert", "text": "stood"}).get("back"))
        self.assertEqual(self.edit.first, 13)


class EditBoxCountingTests(unittest.TestCase):
    """Windows' own edit boxes count a face, or any character from beyond the first
    65,536, as two. Here it is one."""

    TEXT = "\U0001f44d Hello world"

    def test_where_the_cursor_is(self):
        text, first, last = placed(self.TEXT, 9, 9, "plain")       # before "world", as Windows counts
        self.assertEqual((text[:first], text[first:]), ("\U0001f44d Hello ", "world"))
        self.assertEqual(placed(self.TEXT, 9, 14, "rich")[1:], (8, 13))

    def test_and_back_again(self):
        self.assertEqual(place_in(self.TEXT, 8, "plain"), 9)
        self.assertEqual(place_in(self.TEXT, 13, "rich"), 14)
        self.assertEqual(place_in("plain words", 6, "plain"), 6)

    def test_text_without_such_characters_is_as_before(self):
        self.assertEqual(placed("one\r\ntwo", 5, 8, "plain"), ("one\r\ntwo", 5, 8))
        self.assertEqual(placed("one\r\ntwo", 4, 7, "rich"), ("one\rtwo", 4, 7))


if __name__ == "__main__":
    unittest.main()
