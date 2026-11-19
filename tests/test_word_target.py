"""The parts of the Word and Outlook link that need no Word to test."""
import unittest
from types import SimpleNamespace
from unittest import mock

from dictation.formatting import LINE, PARAGRAPH
from dictation.word_target import (BUSY, WordTarget, first_line, for_word, last_line, nearest,
                                   units)


class TextTests(unittest.TestCase):
    def test_before_the_cursor_is_cut_at_the_last_break(self):
        self.assertEqual(last_line("First one.\rSecond"), "Second")
        self.assertEqual(last_line("a\x0bb"), "b")            # a line break
        self.assertEqual(last_line("cell one\x07cell two"), "cell two")
        self.assertEqual(last_line("page one\x0cpage two"), "page two")
        self.assertEqual(last_line("ends here\r"), "")
        self.assertEqual(last_line("no breaks"), "no breaks")

    def test_after_the_cursor_is_cut_at_the_first_break(self):
        self.assertEqual(first_line(" rest of it.\rNext paragraph"), " rest of it.")
        self.assertEqual(first_line("\rNext"), "")
        self.assertEqual(first_line("one\x0btwo\rthree"), "one")

    def test_break_marks_become_words_own(self):
        self.assertEqual(for_word("a" + PARAGRAPH + "b" + LINE + "c"), "a\rb\x0bc")
        self.assertEqual(for_word("plain"), "plain")

    def test_length_as_word_counts_it(self):
        self.assertEqual(units("abc"), 3)
        self.assertEqual(units("café"), 4)
        self.assertEqual(units("a\U0001F600b"), 4)  # an emoji takes two places


class NearestTests(unittest.TestCase):
    def test_keeps_reading_order(self):
        matches = [(0, 3), (10, 13), (20, 23), (30, 33)]
        self.assertEqual(nearest(matches, 21, 4), matches)

    def test_drops_the_furthest_when_there_are_too_many(self):
        matches = [(0, 3), (10, 13), (20, 23), (30, 33)]
        self.assertEqual(nearest(matches, 22, 2), [(20, 23), (30, 33)])
        self.assertEqual(nearest(matches, 0, 2), [(0, 3), (10, 13)])

    def test_cursor_inside_a_match_counts_as_nearest(self):
        self.assertEqual(nearest([(0, 3), (10, 13)], 11, 1), [(10, 13)])


class _Document:
    """Stands in for a Word document: its text, and the ranges that keep their place in
    it as it changes."""

    def __init__(self, text, at):
        self.text, self.ranges = text, []
        self.selection = _Selection(self, at, at)

    def replace(self, start, end, new, by):
        self.text = self.text[:start] + new + self.text[end:]
        for piece in self.ranges + [self.selection]:
            if piece is by:
                continue
            for edge in ("Start", "End"):
                place = getattr(piece, edge)
                if place >= end:
                    setattr(piece, edge, place + len(new) - (end - start))
                elif place > start:
                    setattr(piece, edge, start)


class _Range:
    def __init__(self, document, start, end):
        self.document, self.Start, self.End = document, start, end
        document.ranges.append(self)

    @property
    def Text(self):
        return self.document.text[self.Start:self.End]

    @Text.setter
    def Text(self, new):
        self.document.replace(self.Start, self.End, new, self)
        self.End = self.Start + len(new)

    @property
    def StoryLength(self):
        return len(self.document.text) + 1    # with the mark that ends the last paragraph

    @property
    def Duplicate(self):
        return _Range(self.document, self.Start, self.End)

    def SetRange(self, start, end):
        most = len(self.document.text)
        self.Start, self.End = min(start, most), min(end, most)

    def Collapse(self, to_start=0):
        self.Start = self.End = self.Start if to_start else self.End

    def InsertAfter(self, new):
        self.document.replace(self.End, self.End, new, self)
        self.End += len(new)

    def InStory(self, other):
        return other.document is self.document

    def Select(self):
        self.document.selection.Start, self.document.selection.End = self.Start, self.End


class _Selection(_Range):
    def __init__(self, document, start, end):
        self.document, self.Start, self.End = document, start, end

    @property
    def Range(self):
        return _Range(self.document, self.Start, self.End)

    def EndKey(self, unit, extend):
        self.Start = self.End = len(self.document.text)


class Correct(unittest.TestCase):
    """ "Correct ..." chooses words as "select ..." does, and once something has been said
    in their place the cursor is back where it was."""

    def setUp(self):
        self.shown = []
        self.target = WordTarget.__new__(WordTarget)
        self.target.history, self.target.show_numbers = [], self.shown.append
        self.target._choices = self.target._choices_mark = self.target._correction = None
        self.target._place = lambda front, match: (match.Start, 0, 10, 10)
        self.target._front = lambda: self.front
        self.target._outlook = None
        self.open("the cat sat on the mat")

    def open(self, text, at=None, handle=1):
        self.document = _Document(text, len(text) if at is None else at)
        self.front = SimpleNamespace(handle=handle, selection=self.document.selection,
                                     application=SimpleNamespace(), window=None)

    def cmd(self, name, arg="", nearest=True):
        return self.target._handle({"op": "command", "name": name, "arg": arg, "nearest": nearest})

    def say(self, text, **extra):
        return self.target._handle({"op": "insert", "text": text, **extra})

    def at(self):
        return self.document.selection.Start, self.document.selection.End

    def test_the_cursor_goes_back_to_the_end(self):
        self.assertTrue(self.cmd("correct", "cat")["ok"])
        self.assertEqual(self.at(), (4, 7))
        self.assertTrue(self.say("lion").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the lion sat on the mat", (23, 23)))
        self.say(" today")
        self.assertEqual(self.document.text, "the lion sat on the mat today")

    def test_back_to_a_place_before_the_words(self):
        self.open("the cat sat on the mat", at=0)
        self.cmd("correct", "mat")
        self.say("carpet")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the carpet", (0, 0)))

    def test_the_word_the_cursor_is_right_after_or_right_before(self):
        self.cmd("correct", "mat")
        self.say("rug")
        self.say(" again")
        self.assertEqual(self.document.text, "the cat sat on the rug again")
        self.open("the cat sat on the mat", at=4)
        self.cmd("correct", "cat")
        self.say("lion")
        self.assertEqual(self.at(), (4, 4))

    def test_spaces_taken_out_beside_the_words(self):
        self.cmd("correct", "cat")
        self.say("lion,", delete_after=1)
        self.assertEqual((self.document.text, self.at()), ("the lion,sat on the mat", (23, 23)))

    def test_only_the_next_thing_said_goes_back(self):
        self.cmd("correct", "cat")
        self.say("lion")
        self.document.selection.SetRange(3, 3)
        self.assertFalse(self.say(" big").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the big lion sat on the mat", (7, 7)))

    def test_no_going_back_if_something_else_is_selected_by_then(self):
        self.cmd("correct", "cat")
        self.cmd("select", "sat")
        self.assertFalse(self.say("stood").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the cat stood on the mat", (13, 13)))
        self.cmd("correct", "cat")
        self.document.selection.SetRange(0, 3)        # chosen by hand meanwhile
        self.assertFalse(self.say("a").get("back"))
        self.assertEqual(self.at(), (1, 1))

    def test_not_in_another_document(self):
        self.cmd("correct", "cat")
        self.open("the cat sat on the mat", at=4, handle=2)
        self.document.selection.SetRange(4, 7)
        self.assertFalse(self.say("lion").get("back"))
        self.assertEqual(self.at(), (8, 8))

    def test_unselect_goes_back_too(self):
        self.cmd("correct", "cat")
        self.cmd("unselect")
        self.assertEqual(self.at(), (22, 22))
        self.cmd("select", "cat")
        self.cmd("unselect")
        self.assertEqual(self.at(), (7, 7))

    def test_with_numbers_to_choose_from(self):
        self.open("a fox and a fox and a fox")
        reply = self.cmd("correct", "fox", nearest=False)
        self.assertEqual((reply.get("choices"), len(self.shown[-1])), (3, 3))
        self.assertTrue(self.cmd("choose", "2")["ok"])
        self.assertEqual((self.at(), self.shown[-1]), ((12, 15), []))
        self.assertTrue(self.say("wolf").get("back"))
        self.assertEqual((self.document.text, self.at()), ("a fox and a wolf and a fox", (26, 26)))
        # Numbers for "select ..." leave the cursor with the words, as ever.
        self.cmd("select", "fox", nearest=False)
        self.cmd("choose", "1")
        self.assertFalse(self.say("cat").get("back"))
        self.assertEqual(self.at(), (5, 5))

    def test_any_other_command_ends_it(self):
        self.cmd("correct", "cat")
        self.cmd("line_end")
        self.document.selection.SetRange(4, 7)        # the same words, chosen by hand
        self.assertIsNone(self.say("lion").get("back"))
        self.assertEqual(self.at(), (8, 8))

    def test_a_busy_word_is_asked_again_and_the_cursor_still_goes_back(self):
        class Busy(Exception):
            hresult = BUSY[0]

        self.cmd("correct", "cat")
        selection, calls = self.document.selection, []

        class Slow:
            """The front document, whose selection Word won't give the first time."""
            handle, application, window = 1, SimpleNamespace(), None

            @property
            def selection(self):
                calls.append(1)
                if len(calls) == 1:
                    raise Busy()
                return selection

        self.target._front = Slow
        with mock.patch.dict("sys.modules", {"pythoncom": SimpleNamespace(com_error=Busy)}), \
                mock.patch("dictation.word_target.time.sleep"):
            reply = self.target._answer({"op": "insert", "text": "lion"})
        self.assertTrue(reply.get("back"))
        self.assertEqual((self.document.text, self.at()), ("the lion sat on the mat", (23, 23)))

    def test_not_there(self):
        self.assertEqual(self.cmd("correct", "zebra")["why"], "can't find that")
        self.assertFalse(self.say(" more").get("back"))


class ScratchPutsBack(Correct):
    """ "Scratch that" after words were said over a selection: the phrase goes and the
    words it took the place of are back, selected as they were."""

    def test_after_select(self):
        self.cmd("select", "cat")
        self.say("lion")
        self.assertEqual(self.document.text, "the lion sat on the mat")
        reply = self.cmd("scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, True))
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (4, 7)))
        self.say("tiger")                     # said again, it takes their place as before
        self.assertEqual((self.document.text, self.at()), ("the tiger sat on the mat", (9, 9)))

    def test_after_correct_they_can_be_said_again_and_the_cursor_still_goes_back(self):
        self.cmd("correct", "cat")
        self.assertTrue(self.say("lion").get("back"))
        self.assertEqual(self.at(), (23, 23))
        self.assertTrue(self.cmd("scratch").get("restored"))
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (4, 7)))
        self.assertTrue(self.say("leopard").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the leopard sat on the mat", (26, 26)))

    def test_after_correct_with_the_cursor_before_the_words(self):
        self.open("the cat sat on the mat", at=0)
        self.cmd("correct", "mat")
        self.say("carpet")
        self.cmd("scratch")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (19, 22)))
        self.assertTrue(self.say("rug").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the rug", (0, 0)))

    def test_after_correct_of_the_word_right_before_the_cursor(self):
        self.cmd("correct", "mat")
        self.say("rug")
        self.cmd("scratch")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (19, 22)))
        self.assertTrue(self.say("carpet").get("back"))
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the carpet", (25, 25)))

    def test_unselect_after_it_goes_back_to_where_the_cursor_was(self):
        self.cmd("correct", "cat")
        self.say("lion")
        self.cmd("scratch")
        self.cmd("unselect")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (22, 22)))

    def test_the_spaces_taken_out_beside_them_come_back_too(self):
        self.cmd("select", "cat")
        self.say("lion,", delete_after=1)
        self.assertEqual(self.document.text, "the lion,sat on the mat")
        self.cmd("scratch")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (4, 7)))
        self.cmd("select", "sat")
        self.say(",", delete_before=1)
        self.assertEqual(self.document.text, "the cat, on the mat")
        self.cmd("scratch")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (8, 11)))

    def test_words_selected_by_hand(self):
        self.document.selection.SetRange(8, 11)
        self.say("stood")
        self.cmd("scratch")
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (8, 11)))

    def test_a_phrase_that_took_nothings_place_only_goes(self):
        self.say(" today")
        reply = self.cmd("scratch")
        self.assertEqual((reply.get("ok"), reply.get("restored")), (True, None))
        self.assertEqual((self.document.text, self.at()), ("the cat sat on the mat", (22, 22)))

    def test_said_twice_takes_back_the_phrase_before_as_ever(self):
        self.say(" today")
        self.cmd("select", "cat")
        self.say("lion")
        self.cmd("scratch")
        self.assertEqual(self.document.text, "the cat sat on the mat today")
        self.cmd("scratch")
        self.assertEqual(self.document.text, "the cat sat on the mat")

    def test_select_that_and_format_that_still_find_the_last_phrase(self):
        self.say(" today")
        self.assertTrue(self.cmd("select_last")["ok"])
        self.assertEqual(self.at(), (23, 28))

    def test_words_with_a_table_cell_mark_among_them_are_not_kept(self):
        self.open("one\x07two")
        self.document.selection.SetRange(2, 5)
        self.say("x")
        self.assertIsNone(self.cmd("scratch").get("restored"))


class Redo(Correct):
    """ "Redo that" is Word's own Redo."""

    def test_it_is_asked_of_word_and_nothing_is_left_selected(self):
        asked = []
        self.document.selection.Document = SimpleNamespace(Redo=lambda times: asked.append(times) or True)
        self.document.selection.SetRange(4, 7)
        self.assertEqual(self.cmd("redo"), {"ok": True})
        self.assertEqual((asked, self.at()), ([1], (7, 7)))

    def test_nothing_to_redo(self):
        self.document.selection.Document = SimpleNamespace(Redo=lambda times: False)
        self.assertEqual(self.cmd("redo"), {"ok": False, "why": "nothing to redo"})


if __name__ == "__main__":
    unittest.main()
