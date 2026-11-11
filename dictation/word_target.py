"""Dictating into Microsoft Word, and into messages in classic Outlook, on Windows.

Both are reached through Word's automation interface: Outlook's message editor is Word
underneath. The editing area that has the keyboard hands over its own Word "Window"
object, which gives the text around the cursor and lets it be changed.

Everything that touches Word runs on one thread of its own. Word is spoken to through
COM, which wants its objects used from the thread that got them, and a busy Word (a
dialog open, say) must not be able to hold up the rest of the engine.
"""
from __future__ import annotations

import os
import queue
import threading
import time

from .formatting import LINE, PARAGRAPH, fit
from .editor_target import words_left, words_right
from .selecting import find_all
from .words import Lexicon

# Word's own numbers for things.
CHARACTER, LINE_UNIT, STORY = 1, 5, 6
MOVE, EXTEND = 0, 1
COLLAPSE_END = 0
GOTO_LINE, GOTO_ABSOLUTE = 3, 1
LOWER_CASE, UPPER_CASE, TITLE_WORD = 0, 1, 2
OUTLOOK_EXPLORER, OUTLOOK_INSPECTOR = 34, 35

EDITOR_CLASS = "_WwG"  # the window class of Word's editing area, in Word and in Outlook
PROGRAMS = {"winword.exe": "Word", "outlook.exe": "Outlook"}
# What ends a paragraph in Word's text: paragraph mark, table cell mark, page break.
PARAGRAPH_ENDS = "\r\x07\x0c"
LINE_BREAK = "\x0b"
WINDOW = 3000   # how far around the cursor to look for "select ..."
HISTORY = 20
MAX_CHOICES = 20
NOT_FOCUSED = {"ok": False, "why": "editor not focused"}
BUSY = (-2147418111, -2147417846)  # "call was rejected" and "retry later": Word is busy
# For tests: the handle of a Word editing area to use whether or not it has the keyboard.
TEST_WINDOW = int(os.environ.get("LS_OFFICE_TEST_WINDOW", "0"))


def units(text: str) -> int:
    """Length as Word counts positions (UTF-16 units)."""
    return len(text.encode("utf-16-le")) // 2


def last_line(text: str) -> str:
    """The part of `text` after its last paragraph or line break."""
    for mark in PARAGRAPH_ENDS + LINE_BREAK:
        text = text.rsplit(mark, 1)[-1]
    return text


def first_line(text: str) -> str:
    """The part of `text` before its first paragraph or line break."""
    for mark in PARAGRAPH_ENDS + LINE_BREAK:
        text = text.split(mark, 1)[0]
    return text


def for_word(text: str) -> str:
    """Dictated text with the engine's break marks turned into Word's."""
    return text.replace(PARAGRAPH, "\r").replace(LINE, LINE_BREAK)


def nearest(matches: list, caret: int, limit: int) -> list:
    """The `limit` matches closest to `caret`, back in reading order."""
    def distance(match):
        start, end = match
        return 0 if start <= caret <= end else min(abs(start - caret), abs(end - caret))
    return sorted(sorted(matches, key=distance)[:limit])


class Front:
    """The document that has the keyboard."""

    def __init__(self, name, window, handle):
        self.name = name
        self.window = window          # Word's Window object
        self.handle = handle
        self.application = window.Application
        try:
            self.selection = window.Selection
        except Exception:
            # Outlook's editor doesn't allow that one; it has a single window anyway.
            self.selection = self.application.Selection


class WordTarget:
    def __init__(self):
        self.name = "Word"            # or "Outlook", whichever was last in front
        # Set by the tray. Called with [(number, left, top, width, height), ...] in
        # screen pixels to show numbers over matches, and with [] to take them away.
        self.show_numbers = None
        self.lexicon = Lexicon.load_default()
        self.history = []             # Word ranges of recent phrases, newest last
        self._choices = None          # (window handle, [ranges]) while numbers are showing
        self._outlook = None
        self._jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    # ---- called from the engine's threads ---------------------------------------
    def request(self, message: dict, timeout: float = 6.0) -> dict:
        """Answer one request, in the same form as the Writer extension. Never raises."""
        done, box = threading.Event(), {}
        self._jobs.put((message, box, done, time.monotonic() + timeout))
        if not done.wait(timeout):
            return {"ok": False, "why": "word not answering"}
        return box["reply"]

    def broadcast(self, message: dict) -> None:
        self.request(message, timeout=1.5)

    # ---- the thread that talks to Word --------------------------------------------
    def _run(self) -> None:
        import pythoncom
        pythoncom.CoInitialize()
        while True:
            try:
                job = self._jobs.get(timeout=0.4 if self._choices else None)
            except queue.Empty:
                self._refresh_numbers()   # they follow the text as it scrolls
                continue
            message, box, done, deadline = job
            if time.monotonic() > deadline:
                continue                  # nobody is waiting for this any more
            box["reply"] = self._answer(message)
            done.set()

    def _answer(self, message: dict) -> dict:
        import pythoncom
        for attempt in range(8):
            try:
                return self._handle(message)
            except pythoncom.com_error as e:
                if e.hresult in BUSY and attempt < 7:
                    time.sleep(0.2)       # Word is in the middle of something: try again
                    continue
                self._outlook = None
                return {"ok": False, "why": "error", "error": _describe(e)}
            except Exception as e:
                return {"ok": False, "why": "error", "error": str(e)}
        return {"ok": False, "why": "word not answering"}

    # ---- finding the document -------------------------------------------------------
    def _front(self):
        """The Word or Outlook document that has the keyboard, or None."""
        from . import winapi
        if TEST_WINDOW:
            program, kind, handle = "winword.exe", EDITOR_CLASS, TEST_WINDOW
        else:
            program, kind, handle = winapi.focused()
        name = PROGRAMS.get(program)
        if name is None or kind != EDITOR_CLASS:
            return None
        try:
            window = winapi.native_object(handle)
            front = Front(name, window, handle)
        except OSError:
            return None
        if front.selection is None:
            return None                   # a document opened for reading only
        if name == "Outlook" and not self._composing():
            return None
        self.name = name
        return front

    def _composing(self) -> bool:
        """True if the Outlook window in front is a message being written, not read."""
        import pythoncom
        from . import winapi
        try:
            if self._outlook is None:
                self._outlook = winapi.running("Outlook.Application")
            window = self._outlook.ActiveWindow()
            if window is None:
                return False
            if window.Class == OUTLOOK_EXPLORER:
                return window.ActiveInlineResponse is not None   # a reply in the reading pane
            if window.Class == OUTLOOK_INSPECTOR:
                item = window.CurrentItem
                try:
                    return not item.Sent
                except AttributeError:
                    return True           # an appointment or a contact: always editable
            return False
        except pythoncom.com_error:
            self._outlook = None
            # Outlook wouldn't say. Its editor refuses changes to a message being read,
            # so the worst that happens is an error when something is dictated.
            return True

    def _composing_now(self) -> bool:
        """For tests: what Outlook says about the window it has in front."""
        done, box = threading.Event(), {}
        self._jobs.put(({"op": "composing"}, box, done, time.monotonic() + 6))
        done.wait(6)
        return bool(box.get("reply", {}).get("composing"))

    # ---- requests -----------------------------------------------------------------------
    def _handle(self, m: dict) -> dict:
        op = m.get("op")
        if op == "composing":
            return {"ok": True, "composing": self._composing()}
        if op == "command" and m.get("name") == "cancel_choices":
            self._clear_choices()         # even when Word isn't in front
            return {"ok": True}
        front = self._front()
        if op == "status":
            return {"ok": True, "ready": front is not None}
        if front is None:
            return dict(NOT_FOCUSED)
        if self._choices and (op in ("insert", "move") or (
                op == "command" and m.get("name") != "choose")):
            self._clear_choices()         # doing anything else takes the numbers away
        if op == "context":
            before, after, selected = self._around(front)
            reply = {"ok": True, "before": before, "after": after}
            if selected:
                reply["selected"] = True  # what is dictated will replace the selection
            return reply
        if op == "insert":
            return self._insert(front, m.get("text", ""), int(m.get("delete_before", 0)),
                                int(m.get("delete_after", 0)), bool(m.get("capitalise_next")))
        if op == "command":
            return self._command(front, m.get("name", ""), m.get("arg", ""),
                                 bool(m.get("nearest")))
        if op == "text":  # for tests
            selection = front.selection
            return {"ok": True, "text": selection.Document.Content.Text or "",
                    "selected": selection.Text or "" if selection.Start != selection.End else "",
                    "start": selection.Start, "end": selection.End}
        return {"ok": False, "why": "unknown request"}

    # ---- reading ----------------------------------------------------------------------
    def _text(self, front, start: int, end: int) -> str:
        """The text between two positions in the part of the document the cursor is in."""
        piece = front.selection.Range
        piece.SetRange(max(0, start), max(0, end))
        return piece.Text or ""

    def _around(self, front) -> tuple:
        """Text before and after the cursor (or selection) on its line, and whether
        anything is selected."""
        start, end = front.selection.Start, front.selection.End
        before = last_line(self._text(front, start - 1000, start))
        after = first_line(self._text(front, end, end + 1000))
        return before, after, start != end

    # ---- changing -----------------------------------------------------------------------
    def _record(self, front, title: str, action):
        """Run `action` as one step for Word's Undo."""
        record = None
        try:
            record = front.application.UndoRecord
            record.StartCustomRecord(title)
        except Exception:
            record = None                 # an old Word: each change is undone separately
        try:
            return action()
        finally:
            if record is not None:
                try:
                    record.EndCustomRecord()
                except Exception:
                    pass

    def _insert(self, front, text, delete_before, delete_after, capitalise_next) -> dict:
        if not text and not delete_before and not delete_after:
            return {"ok": True, "text": ""}

        def change():
            at = front.selection.Range
            if at.Start != at.End:
                at.Text = ""              # dictating over a selection replaces it
            if delete_before:
                at.SetRange(max(0, at.Start - delete_before), at.Start)
                at.Text = ""
            if delete_after:
                at.SetRange(at.Start, at.Start + delete_after)
                at.Text = ""
            at.InsertAfter(for_word(text))
            spoken = at.Duplicate
            at.Collapse(COLLAPSE_END)
            if capitalise_next:
                rest = first_line(self._text(front, at.End, at.End + 200))
                for i, c in enumerate(rest):
                    if c.isalpha():
                        if c != c.upper():
                            letter = at.Duplicate
                            letter.SetRange(at.End + units(rest[:i]), at.End + units(rest[:i + 1]))
                            letter.Case = UPPER_CASE
                        break
            at.Select()
            if text:
                self.history.append(spoken)
                del self.history[:-HISTORY]

        self._record(front, "Dictation", change)
        return {"ok": True, "text": text}

    def _last(self, front):
        """The newest remembered phrase that is still in this document, or None."""
        here = front.selection.Range
        while self.history:
            phrase = self.history[-1]
            try:
                if phrase.InStory(here) and phrase.Start != phrase.End:
                    return phrase
                if phrase.InStory(here):
                    self.history.pop()    # its text has gone
                    continue
                return None               # it belongs to another document
            except Exception:
                self.history.pop()        # its document has been closed
        return None

    def _scratch(self, front) -> dict:
        phrase = self._last(front)
        if phrase is None:
            return {"ok": False, "why": "nothing to scratch"}
        self.history.pop()

        def remove():
            phrase.Text = ""
            phrase.Select()

        self._record(front, "Scratch that", remove)
        return {"ok": True}

    # ---- commands -----------------------------------------------------------------------
    def _command(self, front, name: str, arg: str, take_nearest: bool = False) -> dict:
        selection = front.selection
        count = max(1, min(99, int(arg))) if str(arg).isdigit() else 1
        if name in ("new_paragraph", "new_line"):
            before, after, _ = self._around(front)
            ins = fit(name.replace("_", " "), before, after, self.lexicon, spoken_off=())
            return self._insert(front, ins.text, ins.delete_before, ins.delete_after,
                                ins.capitalise_next)
        if name == "undo":
            if not selection.Document.Undo(1):
                return {"ok": False, "why": "nothing to undo"}
            # Undo can leave the restored text selected; the next phrase would replace it.
            front.selection.Collapse(COLLAPSE_END)
            return {"ok": True}
        if name == "scratch":
            return self._scratch(front)
        if name == "delete":
            if selection.Start == selection.End:
                return self._scratch(front)
            self._record(front, "Delete", lambda: setattr(selection.Range, "Text", ""))
            return {"ok": True}
        if name == "backspace":
            def erase():
                at = selection.Range
                if at.Start == at.End:
                    at.SetRange(max(0, at.Start - count), at.Start)
                at.Text = ""
            self._record(front, "Backspace", erase)
            return {"ok": True}
        if name == "select":
            return self._select(front, arg, take_nearest or self.show_numbers is None)
        if name == "choose":
            return self._choose(arg)
        if name == "select_last":
            phrase = self._last(front)
            if phrase is None:
                return {"ok": False, "why": "nothing to select"}
            phrase.Select()
            return {"ok": True}
        if name == "select_all":
            selection.WholeStory()
            return {"ok": True}
        if name == "unselect":
            selection.Collapse(COLLAPSE_END)
            return {"ok": True}
        if name == "line_end":
            selection.EndKey(LINE_UNIT, MOVE)
            return {"ok": True}
        if name == "line_start":
            selection.HomeKey(LINE_UNIT, MOVE)
            return {"ok": True}
        if name == "doc_top":
            selection.HomeKey(STORY, MOVE)
            return {"ok": True}
        if name == "doc_end":
            selection.EndKey(STORY, MOVE)
            return {"ok": True}
        if name in ("para_end", "para_start"):
            return self._paragraph_edge(front, name == "para_end")
        if name in ("word_left", "word_right"):
            # Counted the same way as everywhere else: Word's own idea of a word takes in
            # every comma and paragraph mark.
            if name == "word_left":
                before = self._text(front, selection.Start - WINDOW, selection.Start)
                moved = words_left(before, count)
                to = selection.Start - units(before[len(before) - moved:])
            else:
                after = self._text(front, selection.End, selection.End + WINDOW)
                to = selection.End + units(after[:words_right(after, count)])
            selection.SetRange(to, to)
            return {"ok": True}
        if name == "line_up":
            selection.MoveUp(LINE_UNIT, count, MOVE)
            return {"ok": True}
        if name == "line_down":
            selection.MoveDown(LINE_UNIT, count, MOVE)
            return {"ok": True}
        if name == "go_to_line":
            selection.GoTo(GOTO_LINE, GOTO_ABSOLUTE, max(1, int(arg or 1)))
            return {"ok": True}
        if name in ("select_line", "delete_line"):
            selection.HomeKey(LINE_UNIT, MOVE)
            if name == "delete_line" and count > 1:
                selection.MoveDown(LINE_UNIT, count - 1, EXTEND)
            selection.EndKey(LINE_UNIT, EXTEND)
            if name == "select_line" and (selection.Text or "")[-1:] in tuple(PARAGRAPH_ENDS):
                # Not the paragraph mark: saying something over the line would join it
                # to the next paragraph.
                selection.MoveEnd(CHARACTER, -1)
            if name == "delete_line":
                self._record(front, "Delete line", lambda: setattr(selection.Range, "Text", ""))
            return {"ok": True}
        if name in ("indent", "outdent"):
            paragraphs = selection.Paragraphs
            self._record(front, name.capitalize(),
                         paragraphs.Indent if name == "indent" else paragraphs.Outdent)
            return {"ok": True}
        if name in ("bold", "italic", "underline", "cap", "all_caps", "no_caps"):
            return self._format(front, name)
        return {"ok": False, "why": "unknown command"}

    def _paragraph_edge(self, front, to_end: bool) -> dict:
        """To the end or start of the paragraph. Already there, on to the next or the
        one before, so repeating the command walks through the document."""
        selection = front.selection
        paragraph = selection.Paragraphs(1)
        at = selection.Start
        if to_end:
            edge = paragraph.Range.End - 1          # just before its paragraph mark
            if at >= edge and paragraph.Next() is not None:
                edge = paragraph.Next().Range.End - 1
        else:
            edge = paragraph.Range.Start
            if at <= edge and paragraph.Previous() is not None:
                edge = paragraph.Previous().Range.Start
        selection.SetRange(edge, edge)
        return {"ok": True}

    def _format(self, front, name: str) -> dict:
        selection = front.selection
        target = selection.Range if selection.Start != selection.End else self._last(front)
        if target is None:
            return {"ok": False, "why": "nothing to format"}

        def apply():
            if name == "bold":
                target.Font.Bold = True
            elif name == "italic":
                target.Font.Italic = True
            elif name == "underline":
                target.Font.Underline = 1  # a single line
            else:
                target.Case = {"cap": TITLE_WORD, "all_caps": UPPER_CASE,
                               "no_caps": LOWER_CASE}[name]

        self._record(front, "Format that", apply)
        return {"ok": True}

    # ---- "select ...", with numbers to choose from --------------------------------------
    def _matches(self, front, phrase: str) -> tuple:
        """A Word range for each place `phrase` is found near the cursor, in reading
        order, and the index of the one nearest the cursor."""
        selection = front.selection
        caret = selection.Start
        low = max(0, caret - WINDOW)
        text = self._text(front, low, selection.End + WINDOW)
        offset = units(self._text(front, low, caret))  # the cursor's place in `text`, roughly
        places = [(units(text[:a]), units(text[:b]), text[a:b]) for a, b in find_all(text, phrase)]
        chosen = nearest([(a, b) for a, b, _ in places], offset, MAX_CHOICES)
        wanted = {(a, b): words for a, b, words in places}
        found, best, best_distance = [], 0, None
        for a, b in chosen:
            match = selection.Range
            match.SetRange(low + a, low + b)
            if (match.Text or "") != wanted[(a, b)]:
                continue  # something that isn't text (a field, say) threw the count off
            distance = 0 if a <= offset <= b else min(abs(a - offset), abs(b - offset))
            if best_distance is None or distance < best_distance:
                best, best_distance = len(found), distance
            found.append(match)
        return found, best

    def _place(self, front, match):
        """Where a range is on screen: (left, top, width, height), or None if it isn't."""
        import pythoncom
        try:
            # The four numbers are handed back; the zeros only hold their places.
            place = front.window.GetPoint(0, 0, 0, 0, match)
        except pythoncom.com_error:
            return None                   # scrolled out of view
        return tuple(place) if isinstance(place, tuple) and len(place) == 4 else None

    def _select(self, front, phrase: str, take_nearest: bool) -> dict:
        matches, best = self._matches(front, phrase)
        if not matches:
            return {"ok": False, "why": "can't find that"}
        if len(matches) == 1 or take_nearest:
            matches[best].Select()
            return {"ok": True}
        # Numbers go over the matches that can be seen. Any others are left out.
        seen = [(match, place) for match in matches
                for place in [self._place(front, match)] if place is not None]
        if len(seen) < 2:
            (seen[0][0] if seen else matches[best]).Select()
            return {"ok": True}
        self._choices = (front, [match for match, _ in seen])
        self.show_numbers([(n, *place) for n, (_, place) in enumerate(seen, start=1)])
        return {"ok": True, "choices": len(seen)}

    def _choose(self, arg: str) -> dict:
        if not self._choices:
            return {"ok": False, "why": "nothing to choose from"}
        matches = self._choices[1]
        n = int(arg or 0)
        if not 1 <= n <= len(matches):
            return {"ok": False, "why": "no such number"}
        self._clear_choices()
        matches[n - 1].Select()
        return {"ok": True}

    def _clear_choices(self) -> None:
        if self._choices:
            self._choices = None
            if self.show_numbers is not None:
                self.show_numbers([])

    def _refresh_numbers(self) -> None:
        """Keep the numbers over their words while the document scrolls, and take them
        away if another window comes to the front."""
        if not self._choices or self.show_numbers is None:
            return
        from . import winapi
        front, matches = self._choices
        try:
            if not TEST_WINDOW and winapi.focused()[2] != front.handle:
                self._clear_choices()
                return
            places = [(n, self._place(front, match)) for n, match in enumerate(matches, start=1)]
            self.show_numbers([(n, *place) for n, place in places if place is not None])
        except Exception:
            self._clear_choices()


def _describe(error) -> str:
    """A COM error in a few words."""
    try:
        return str(error.excepinfo[2] or error.strerror).strip()
    except Exception:
        return str(error)
