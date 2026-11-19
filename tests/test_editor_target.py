import unittest
from types import SimpleNamespace

from dictation.editor_target import (
    EditorTarget, line_move, line_span, paragraph_end, paragraph_start, units, words_left,
    words_right,
)

DOC = "one\ntwo\n\nthree\nfour\n\n\nfive\n"
#      0123 4567 8 9...


class ParagraphEnd(unittest.TestCase):
    def go(self, caret):
        return caret + paragraph_end(DOC[caret:])

    def test_from_inside_a_paragraph(self):
        self.assertEqual(self.go(0), 7)   # end of "two"
        self.assertEqual(self.go(5), 7)
        self.assertEqual(self.go(9), 19)  # end of "four"

    def test_already_at_the_end_goes_to_the_next(self):
        self.assertEqual(self.go(7), 19)
        self.assertEqual(self.go(19), 26)  # end of "five", past two blank lines

    def test_last_paragraph_stays(self):
        self.assertEqual(self.go(26), 26)
        self.assertEqual(self.go(len(DOC)), len(DOC))

    def test_from_a_blank_line(self):
        self.assertEqual(self.go(8), 19)


class ParagraphStart(unittest.TestCase):
    def go(self, caret):
        return paragraph_start(DOC[:caret])

    def test_from_inside_a_paragraph(self):
        self.assertEqual(self.go(6), 0)
        self.assertEqual(self.go(17), 9)   # start of "three"
        self.assertEqual(self.go(25), 22)  # start of "five"

    def test_already_at_the_start_goes_to_the_one_before(self):
        self.assertEqual(self.go(22), 9)
        self.assertEqual(self.go(9), 0)

    def test_first_paragraph_stays(self):
        self.assertEqual(self.go(0), 0)


class Words(unittest.TestCase):
    TEXT = "The quick, brown fox.\nNext line"

    def left(self, caret, count):
        return caret - words_left(self.TEXT[:caret], count)

    def right(self, caret, count):
        return caret + words_right(self.TEXT[caret:], count)

    def test_left(self):
        end = len(self.TEXT)
        self.assertEqual(self.TEXT[self.left(end, 1):], "line")
        self.assertEqual(self.TEXT[self.left(end, 2):], "Next line")
        self.assertEqual(self.TEXT[self.left(end, 3):], "fox.\nNext line")
        self.assertEqual(self.left(end, 50), 0)
        self.assertEqual(self.left(7, 1), 4)  # from inside "quick" to its start

    def test_right(self):
        self.assertEqual(self.TEXT[self.right(0, 1):], "quick, brown fox.\nNext line")
        self.assertEqual(self.TEXT[self.right(0, 2):], "brown fox.\nNext line")
        self.assertEqual(self.TEXT[self.right(0, 4):], "Next line")
        self.assertEqual(self.right(0, 50), len(self.TEXT))


class Lines(unittest.TestCase):
    TEXT = "first\nsecond line\n\nfourth"

    def test_span(self):
        self.assertEqual(line_span(self.TEXT, 8), (6, 17))
        self.assertEqual(line_span(self.TEXT, 0), (0, 5))
        self.assertEqual(line_span(self.TEXT, len(self.TEXT)), (19, 25))
        self.assertEqual(line_span(self.TEXT, 18), (18, 18))

    def test_move_keeps_the_column_where_it_can(self):
        self.assertEqual(line_move(self.TEXT, 15, -1), 5)    # "first" is shorter: its end
        self.assertEqual(line_move(self.TEXT, 3, 1), 9)      # column 3 of "second line"
        self.assertEqual(line_move(self.TEXT, 9, 1), 18)     # the blank line
        self.assertEqual(line_move(self.TEXT, 9, 2), 22)
        self.assertEqual(line_move(self.TEXT, 2, -5), 2)     # already at the top
        self.assertEqual(line_move(self.TEXT, 20, 9), 20)    # already at the bottom
        self.assertEqual(line_move(self.TEXT, 0, 3), 19)     # as "go to line 4" does


class Units(unittest.TestCase):
    def test_counts_like_the_editor(self):
        self.assertEqual(units("abc"), 3)
        self.assertEqual(units("café"), 4)
        self.assertEqual(units("\U0001f600"), 2)


class _Box:
    """Stands in for an editor's text area as the accessibility interface gives it."""

    def __init__(self, text, caret):
        self.text, self.caret, self.chosen = text, caret, None


class _Text:
    get_character_count = staticmethod(lambda o: len(o.text))
    get_caret_offset = staticmethod(lambda o: o.caret)
    get_text = staticmethod(lambda o, start, end: o.text[start:end])
    get_n_selections = staticmethod(lambda o: 1 if o.chosen else 0)
    get_selection = staticmethod(
        lambda o, n: SimpleNamespace(start_offset=o.chosen[0], end_offset=o.chosen[1]))

    @staticmethod
    def remove_selection(o, n):
        o.chosen = None

    @staticmethod
    def set_caret_offset(o, at):
        o.caret = at

    @staticmethod
    def add_selection(o, start, end):
        o.chosen, o.caret = (start, end), end


class _Edit:
    @staticmethod
    def insert_text(o, at, text, length):
        o.text = o.text[:at] + text + o.text[at:]

    @staticmethod
    def delete_text(o, start, end):
        o.text = o.text[:start] + o.text[end:]


class Correct(unittest.TestCase):
    """ "Correct ..." chooses words as "select ..." does, and once something has been said
    in their place the cursor is back where it was."""

    def setUp(self):
        self.box = _Box("the cat sat on the mat", 22)
        self.target = EditorTarget.__new__(EditorTarget)
        self.target.T, self.target.E = _Text, _Edit
        self.target._utf16, self.target._one_line = True, False
        self.target.history, self.target.correction = [], None
        self.target.focused = lambda: self.box

    def cmd(self, name, arg=""):
        return self.target.request({"op": "command", "name": name, "arg": arg})

    def say(self, text, **extra):
        return self.target.request({"op": "insert", "text": text, **extra})

    def test_the_cursor_goes_back_to_the_end(self):
        self.assertTrue(self.cmd("correct", "cat")["ok"])
        self.assertEqual(self.box.chosen, (4, 7))
        self.assertTrue(self.say("lion").get("back"))
        self.assertEqual((self.box.text, self.box.caret, self.box.chosen),
                         ("the lion sat on the mat", 23, None))
        self.say(" today")
        self.assertEqual(self.box.text, "the lion sat on the mat today")

    def test_back_to_a_place_before_the_words(self):
        self.box.caret = 0
        self.cmd("correct", "mat")
        self.say("carpet")
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the carpet", 0))

    def test_the_word_the_cursor_is_right_after(self):
        self.cmd("correct", "mat")
        self.say("rug")
        self.say(" again")
        self.assertEqual(self.box.text, "the cat sat on the rug again")

    def test_the_word_the_cursor_is_right_before(self):
        self.box.caret = 4
        self.cmd("correct", "cat")
        self.say("lion")
        self.assertEqual(self.box.caret, 4)

    def test_spaces_taken_out_beside_the_words(self):
        self.cmd("correct", "cat")
        self.say("lion,", delete_after=1)
        self.assertEqual((self.box.text, self.box.caret), ("the lion,sat on the mat", 23))

    def test_only_the_next_thing_said_goes_back(self):
        self.cmd("correct", "cat")
        self.say("lion")
        self.box.caret = 3
        self.assertFalse(self.say(" big").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the big lion sat on the mat", 7))

    def test_no_going_back_if_something_else_is_selected_by_then(self):
        self.cmd("correct", "cat")
        self.cmd("select", "sat")
        self.assertFalse(self.say("stood").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the cat stood on the mat", 13))
        self.cmd("correct", "cat")
        _Text.add_selection(self.box, 0, 3)           # chosen by hand meanwhile
        self.assertFalse(self.say("a").get("back"))
        self.assertEqual(self.box.caret, 1)

    def test_unselect_goes_back_too(self):
        self.cmd("correct", "cat")
        self.cmd("unselect")
        self.assertEqual((self.box.caret, self.box.chosen), (22, None))
        self.cmd("select", "cat")
        self.cmd("unselect")
        self.assertEqual(self.box.caret, 7)

    def test_any_other_command_ends_it(self):
        self.cmd("correct", "cat")
        self.cmd("all_caps")
        self.assertEqual(self.box.chosen, (4, 7))
        self.assertIsNone(self.say("lion").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the lion sat on the mat", 8))
        self.cmd("correct", "lion")
        self.cmd("cancel_choices")                    # sent to every program at once
        self.assertTrue(self.say("cat").get("back"))

    def test_not_there(self):
        self.assertEqual(self.cmd("correct", "zebra")["why"], "can't find that")
        self.assertFalse(self.say(" more").get("back"))


class ScratchPutsBack(Correct):
    """ "Scratch that" after words were said over a selection: the phrase goes and the
    words it took the place of are back, selected as they were."""

    def at(self):
        return self.box.text, self.box.chosen

    def test_after_select(self):
        self.cmd("select", "cat")
        self.say("lion")
        reply = self.cmd("scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, True))
        self.assertEqual(self.at(), ("the cat sat on the mat", (4, 7)))
        self.say("tiger")
        self.assertEqual((self.box.text, self.box.caret), ("the tiger sat on the mat", 9))

    def test_after_correct_they_can_be_said_again_and_the_cursor_still_goes_back(self):
        self.cmd("correct", "cat")
        self.say("lion")
        self.assertTrue(self.cmd("scratch").get("restored"))
        self.assertEqual(self.at(), ("the cat sat on the mat", (4, 7)))
        self.assertTrue(self.say("leopard").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the leopard sat on the mat", 26))

    def test_after_correct_with_the_cursor_before_the_words(self):
        self.box.caret = 0
        self.cmd("correct", "mat")
        self.say("carpet")
        self.cmd("scratch")
        self.assertEqual(self.at(), ("the cat sat on the mat", (19, 22)))
        self.assertTrue(self.say("rug").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the rug", 0))

    def test_after_correct_of_the_word_right_before_the_cursor(self):
        self.cmd("correct", "mat")
        self.say("rug")
        self.cmd("scratch")
        self.assertEqual(self.at(), ("the cat sat on the mat", (19, 22)))
        self.assertTrue(self.say("carpet").get("back"))
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the carpet", 25))

    def test_unselect_after_it_goes_back_to_where_the_cursor_was(self):
        self.cmd("correct", "cat")
        self.say("lion")
        self.cmd("scratch")
        self.cmd("unselect")
        self.assertEqual((self.box.text, self.box.caret, self.box.chosen),
                         ("the cat sat on the mat", 22, None))

    def test_the_spaces_taken_out_beside_them_come_back_too(self):
        self.cmd("select", "cat")
        self.say("lion,", delete_after=1)
        self.assertEqual(self.box.text, "the lion,sat on the mat")
        self.cmd("scratch")
        self.assertEqual(self.at(), ("the cat sat on the mat", (4, 7)))
        self.cmd("select", "sat")
        self.say(",", delete_before=1)
        self.assertEqual(self.box.text, "the cat, on the mat")
        self.cmd("scratch")
        self.assertEqual(self.at(), ("the cat sat on the mat", (8, 11)))

    def test_the_capital_given_to_the_next_letter_goes_again(self):
        self.cmd("select", "cat")
        self.say("lion.", capitalise_next=True)
        self.assertEqual(self.box.text, "the lion. Sat on the mat")
        self.cmd("scratch")
        self.assertEqual(self.at(), ("the cat sat on the mat", (4, 7)))

    def test_a_phrase_that_took_nothings_place_only_goes(self):
        self.say(" today")
        reply = self.cmd("scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, None))
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the mat", 22))

    def test_said_twice_takes_back_the_phrase_before_as_ever(self):
        self.say(" today")
        self.cmd("select", "cat")
        self.say("lion")
        self.cmd("scratch")
        self.assertEqual(self.box.text, "the cat sat on the mat today")
        self.cmd("scratch")
        self.assertEqual(self.box.text, "the cat sat on the mat")


class UndoAndRedo(Correct):
    """ "Undo that" and "redo that" press the editor's own menu: as many times as the
    phrase was edits, so that it goes and comes back whole."""

    def setUp(self):
        super().setUp()
        self.pressed = []
        item = lambda name: SimpleNamespace(name=name, get_action_iface=lambda: object())
        self.menu = {"undo": item("undo"), "redo": item("redo")}
        self.target._app = object()
        self.target._menu_item = lambda app, wanted: self.menu.get(wanted)
        self.target.A = SimpleNamespace(Action=SimpleNamespace(
            do_action=lambda item, n: self.pressed.append(item.name)))

    def test_redo_is_as_many_steps_as_the_undo_was(self):
        self.say(" today,", delete_before=1)          # two edits: a space out, the words in
        self.assertTrue(self.cmd("undo")["ok"])
        self.assertEqual(self.pressed, ["undo", "undo"])
        self.assertTrue(self.cmd("redo")["ok"])
        self.assertEqual(self.pressed[2:], ["redo", "redo"])
        # The phrase is known again, so "scratch that" can still take it back.
        self.assertTrue(self.cmd("scratch")["ok"])

    def test_once_where_no_phrase_was_undone(self):
        self.cmd("redo")
        self.assertEqual(self.pressed, ["redo"])
        self.cmd("redo")
        self.assertEqual(self.pressed, ["redo", "redo"])

    def test_something_said_in_between_leaves_one_step(self):
        self.say(" today,", delete_before=1)
        self.cmd("undo")
        self.box.text, self.box.caret = "the cat sat on the mat", 22   # as the editor's Undo leaves it
        self.say(" now")
        self.pressed.clear()
        self.cmd("redo")
        self.assertEqual(self.pressed, ["redo"])

    def test_an_editor_with_no_menus_to_press_takes_the_phrase_back_and_puts_it_back(self):
        # Kate is one: "undo that" there is the last phrase taken back, as "scratch that".
        self.menu.clear()
        self.say(" today")
        self.assertTrue(self.cmd("undo")["ok"])
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the mat", 22))
        self.assertEqual(self.cmd("redo"), {"ok": True})
        self.assertEqual((self.box.text, self.box.caret), ("the cat sat on the mat today", 28))
        self.assertEqual(self.pressed, [])
        # It is known again, so it can be taken back again: and redone only the once.
        self.assertTrue(self.cmd("scratch")["ok"])
        self.assertEqual(self.box.text, "the cat sat on the mat")
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})

    def test_not_if_the_cursor_has_moved_or_something_was_said_since(self):
        self.menu.clear()
        self.say(" today")
        self.cmd("undo")
        self.box.caret = 3
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})
        self.box.caret = 22
        self.say(" today")
        self.cmd("undo")
        self.say(" now")
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})
        self.assertEqual(self.box.text, "the cat sat on the mat now")

    def test_nothing_to_redo_with_no_menu_and_nothing_undone(self):
        self.menu.clear()
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})

    def test_words_put_back_by_undo_are_not_redone(self):
        self.menu.clear()
        self.cmd("select", "cat")
        self.say("lion")
        self.assertTrue(self.cmd("undo").get("restored"))
        self.cmd("unselect")
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})
        self.assertEqual(self.box.text, "the cat sat on the mat")


if __name__ == "__main__":
    unittest.main()
