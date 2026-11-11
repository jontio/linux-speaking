"""Dictating through the desktop's accessibility interface: Kate, KWrite, and optionally
any other program's text boxes.

Kate has no add-on that could talk to the engine, but like a screen reader the engine
can read a text box's text and cursor and make edits. Everything here runs in the engine.

A program only offers this interface when accessibility is on for it. Kate and KWrite are
started with QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1. For everything else the desktop's
accessibility switch has to be on, which the "other programs" setting does.
"""
from __future__ import annotations

import os
import re

from .formatting import LINE, PARAGRAPH
from .selecting import find_nearest

APPS = ("kate", "kwrite")
# Programs reached a better way, through their own add-on or extension.
HAVE_THEIR_OWN = ("soffice", "soffice.bin", "libreoffice", "thunderbird", "code", "code-oss",
                  "codium", "vscodium")
NAMES = {"kate": "Kate", "kwrite": "KWrite"}
WINDOW = 4000  # how far around the cursor to read
HISTORY = 20
BLANK_LINE = re.compile(r"\n[ \t]*(?=\n)")  # the end of a line that a blank line follows
AFTER_BLANK = re.compile(r"\n(?:[ \t]*\n)+")  # ends where the line after blank lines starts


def _in_word(c: str) -> bool:
    return c.isalnum() or c in "'\u2019"


def words_left(before: str, count: int) -> int:
    """How far to move left to reach the start of the word `count` words back."""
    at = len(before)
    for _ in range(count):
        while at > 0 and not _in_word(before[at - 1]):
            at -= 1
        while at > 0 and _in_word(before[at - 1]):
            at -= 1
    return len(before) - at


def words_right(after: str, count: int) -> int:
    """How far to move right to reach the start of the word `count` words on."""
    at = 0
    for _ in range(count):
        while at < len(after) and _in_word(after[at]):
            at += 1
        while at < len(after) and not _in_word(after[at]):
            at += 1
    return at


def line_span(text: str, caret: int) -> tuple:
    """Start and end of the line the cursor is on, the end not counting its line break."""
    start = text.rfind("\n", 0, caret) + 1
    end = text.find("\n", caret)
    return start, len(text) if end < 0 else end


def line_move(text: str, caret: int, lines: int) -> int:
    """Where the cursor lands `lines` down (or up, if negative), keeping its column
    where the line is long enough."""
    start, _ = line_span(text, caret)
    column = caret - start
    for _ in range(abs(lines)):
        if lines < 0:
            if start == 0:
                break
            start = text.rfind("\n", 0, start - 1) + 1
        else:
            following = text.find("\n", start)
            if following < 0:
                break
            start = following + 1
    _, end = line_span(text, start)
    return min(start + column, end)


def paragraph_end(after: str) -> int:
    """How far to move forward for "go to end of paragraph", given the text after the cursor.

    In plain text a paragraph is a run of lines with no blank line in it. Already at
    its end, carry on to the end of the next paragraph.
    """
    edge = BLANK_LINE.search(after)
    here = after[: edge.start()] if edge else after
    if here.strip() == "":  # already at the end
        body = after.lstrip(" \t\n")
        if not body:
            return 0
        edge = BLANK_LINE.search(body)
        length = edge.start() if edge else len(body.rstrip(" \t\n"))
        return len(after) - len(body) + length
    return edge.start() if edge else len(after.rstrip("\n"))


def paragraph_start(before: str) -> int:
    """Where in `before`, the text up to the cursor, "go to start of paragraph" lands.

    Already at the start, go back to the start of the paragraph before.
    """
    def last_start(text: str) -> int:
        ends = [m.end() for m in AFTER_BLANK.finditer(text)]
        return ends[-1] if ends else 0

    start = last_start(before)
    if before[start:].strip() == "":  # already at the start
        return last_start(before[:start].rstrip(" \t\n"))
    return start


def units(text: str) -> int:
    """Length as the editor counts it (UTF-16 units)."""
    return len(text.encode("utf-16-le")) // 2


class EditorTarget:
    """Kate and KWrite always. With `everything`, any program's focused text box."""

    def __init__(self, everything=lambda: False):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        self.A = Atspi
        self.T = Atspi.Text
        self.E = Atspi.EditableText
        self.everything = everything   # called each time: the Settings tick box
        self.name = ""
        self._object = None
        self._app = None
        self._utf16 = True     # Qt counts in UTF-16 units; GTK counts characters
        self._one_line = False
        self.history = []  # {"start", "text", "edits"} for recent phrases, newest last

    # ---- finding the text box ---------------------------------------------------
    def _wanted(self, app) -> bool:
        """Whether to look in this program at all."""
        name = (app.get_name() or "").lower()
        if name in APPS:
            return True
        if not self.everything() or name in HAVE_THEIR_OWN:
            return False
        return app.get_process_id() != os.getpid()

    def _is_focused_editor(self, o) -> bool:
        states = o.get_state_set()
        S = self.A.StateType
        if not (states.contains(S.FOCUSED) and states.contains(S.EDITABLE)
                and o.get_editable_text_iface() is not None):
            return False
        if o.get_role() == self.A.Role.PASSWORD_TEXT:
            return False       # never dictate into a password box
        return states.contains(S.MULTI_LINE) or self.everything()

    def _search(self, o, depth=0):
        if self._is_focused_editor(o):
            return o
        if depth < 25:
            for i in range(min(o.get_child_count(), 300)):
                child = o.get_child_at_index(i)
                found = self._search(child, depth + 1) if child is not None else None
                if found is not None:
                    return found
        return None

    def _in_front(self, app):
        """The program's windows that are in front. Only those are searched."""
        S = self.A.StateType
        for i in range(min(app.get_child_count(), 50)):
            window = app.get_child_at_index(i)
            if window is not None and window.get_state_set().contains(S.ACTIVE):
                yield window

    def focused(self):
        """The text box with the keyboard, in a program we may dictate into, or None."""
        try:
            if self._object is not None and self._is_focused_editor(self._object):
                return self._object
        except Exception:
            pass
        self._object = None
        desktop = self.A.get_desktop(0)
        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None or not self._wanted(app):
                    continue
                found = next((f for f in (self._search(w) for w in self._in_front(app))
                              if f is not None), None)
            except Exception:
                continue
            if found is not None:
                if self._app is None or app.get_process_id() != self._app.get_process_id():
                    self.history = []
                self._object, self._app = found, app
                name = app.get_name() or "another program"
                self.name = NAMES.get(name.lower(), name[:1].upper() + name[1:])
                self._utf16 = (app.get_toolkit_name() or "").lower().startswith("qt")
                self._one_line = not found.get_state_set().contains(self.A.StateType.MULTI_LINE)
                return found
        return None

    def _count(self, text: str) -> int:
        """The length of `text` as this program counts positions."""
        return units(text) if self._utf16 else len(text)

    def _put(self, o, position: int, text: str) -> None:
        # Qt wants the length in its own units; GTK wants it in bytes.
        self.E.insert_text(o, position, text,
                           units(text) if self._utf16 else len(text.encode("utf-8")))

    # ---- reading ----------------------------------------------------------------
    def _span(self, o):
        """Start and end of the selection, or the cursor twice."""
        if self.T.get_n_selections(o) > 0:
            s = self.T.get_selection(o, 0)
            if s.start_offset != s.end_offset:
                return min(s.start_offset, s.end_offset), max(s.start_offset, s.end_offset)
        caret = self.T.get_caret_offset(o)
        return caret, caret

    def _around(self, o):
        start, end = self._span(o)
        count = self.T.get_character_count(o)
        before = self.T.get_text(o, max(0, start - WINDOW), start).rsplit("\n", 1)[-1]
        after = self.T.get_text(o, end, min(count, end + WINDOW)).split("\n", 1)[0]
        return before, after, start, end

    def _place(self, o, offset) -> None:
        if self.T.get_n_selections(o) > 0:
            self.T.remove_selection(o, 0)
        self.T.set_caret_offset(o, offset)

    def _select(self, o, start, end) -> None:
        if self.T.get_n_selections(o) > 0:
            self.T.remove_selection(o, 0)
        self.T.add_selection(o, start, end)

    # ---- requests ---------------------------------------------------------------
    def request(self, message: dict) -> dict:
        """Answer one request, in the same form as the Writer extension. Never raises."""
        try:
            return self._handle(message)
        except Exception as e:
            self._object = None
            return {"ok": False, "why": "error", "error": str(e)}

    def _handle(self, m: dict) -> dict:
        op = m.get("op")
        if op == "command" and m.get("name") == "cancel_choices":
            return {"ok": True}
        o = self.focused()
        if op == "status":
            return {"ok": True, "ready": o is not None}
        if o is None:
            return {"ok": False, "why": "editor not focused"}
        if op == "context":
            before, after, start, end = self._around(o)
            reply = {"ok": True, "before": before, "after": after}
            if start != end:
                reply["selected"] = True  # what is dictated will replace the selection
            return reply
        if op == "insert":
            return self._insert(o, m.get("text", ""), int(m.get("delete_before", 0)),
                                int(m.get("delete_after", 0)), bool(m.get("capitalise_next")))
        if op == "command":
            return self._command(o, m.get("name", ""), m.get("arg", ""))
        if op == "text":  # for tests
            start, end = self._span(o)
            return {"ok": True, "text": self.T.get_text(o, 0, self.T.get_character_count(o)),
                    "selected": self.T.get_text(o, start, end), "caret": self.T.get_caret_offset(o)}
        return {"ok": False, "why": "unknown request"}

    # ---- inserting ----------------------------------------------------------------
    def _insert(self, o, text, delete_before, delete_after, capitalise_next) -> dict:
        if self._one_line:
            # A one-line box can't hold a line break: a space is the nearest thing.
            text = text.replace(PARAGRAPH, " ").replace(LINE, " ")
        # In plain text a paragraph is set off by a blank line.
        text = text.replace(PARAGRAPH, "\n\n").replace(LINE, "\n")
        if not text and not delete_before and not delete_after:
            return {"ok": True, "text": ""}
        start, end = self._span(o)
        edits = 0
        if start != end:  # dictating over a selection replaces it
            self._place(o, start)
            self.E.delete_text(o, start, end)
            edits += 1
        position = start
        if delete_before:
            delete_before = min(delete_before, position)
            self.E.delete_text(o, position - delete_before, position)
            position -= delete_before
            edits += 1
        if delete_after:
            self.E.delete_text(o, position, position + delete_after)
            edits += 1
        if text:
            self._put(o, position, text)
            edits += 1
        after = position + self._count(text)
        if capitalise_next:
            rest = self.T.get_text(o, after, min(self.T.get_character_count(o), after + 200))
            rest = rest.split("\n", 1)[0]
            for i, c in enumerate(rest):
                if c.isalpha():
                    if c != c.upper() and units(c.upper()) == 1:
                        self.E.delete_text(o, after + i, after + i + 1)
                        self._put(o, after + i, c.upper())
                        edits += 2
                    break
        self._place(o, after)
        if text:
            self.history.append({"start": position, "text": text, "edits": edits})
            del self.history[:-HISTORY]
        return {"ok": True, "text": text}

    # ---- the last phrase ------------------------------------------------------------
    def _last(self, o):
        """Start and end of the last phrase, if it is still where it was put."""
        if not self.history:
            return None
        phrase = self.history[-1]
        size = self._count(phrase["text"])
        caret = self.T.get_caret_offset(o)
        for start in (phrase["start"], caret - size):  # where it went in, or just before the cursor
            if start >= 0 and self.T.get_text(o, start, start + size) == phrase["text"]:
                return start, start + size
        return None

    def _scratch(self, o) -> dict:
        found = self._last(o)
        if found is None:
            if self.history:
                self.history.pop()
            return {"ok": False, "why": "nothing to scratch"}
        self.history.pop()
        self._place(o, found[0])
        self.E.delete_text(o, found[0], found[1])
        self._place(o, found[0])
        return {"ok": True}

    # ---- undo, through the editor's own menu ---------------------------------------
    def _menu_item(self, o, wanted: str, depth=0):
        role = o.get_role_name()
        if role == "menu item" and o.get_name().replace("&", "").strip().lower() == wanted:
            return o
        if depth < 8 and role in ("application", "frame", "menu bar", "menu", "filler",
                                  "panel", "popup menu", "window"):
            for i in range(min(o.get_child_count(), 80)):
                child = o.get_child_at_index(i)
                found = self._menu_item(child, wanted, depth + 1) if child is not None else None
                if found is not None:
                    return found
        return None

    def _undo(self, o) -> dict:
        item = self._menu_item(self._app, "undo") if self._app is not None else None
        if item is None or item.get_action_iface() is None:
            # No menu to press: taking back the last phrase is the next best thing.
            return self._scratch(o)
        # One spoken phrase can be several edits to the editor. Undo them together.
        times = self.history.pop()["edits"] if self._last(o) is not None else 1
        for _ in range(times):
            self.A.Action.do_action(item, 0)
        return {"ok": True}

    # ---- moving -----------------------------------------------------------------------
    def _paragraph_edge(self, o, to_end: bool) -> int:
        caret = self.T.get_caret_offset(o)
        if to_end:
            count = self.T.get_character_count(o)
            return caret + paragraph_end(self.T.get_text(o, caret, min(count, caret + 4 * WINDOW)))
        lo = max(0, caret - 4 * WINDOW)
        return lo + paragraph_start(self.T.get_text(o, lo, caret))

    # ---- commands -----------------------------------------------------------------------
    def _command(self, o, name: str, arg: str) -> dict:
        T = self.T
        start, end = self._span(o)
        caret = T.get_caret_offset(o)
        count = T.get_character_count(o)
        if name == "new_paragraph":
            return self._insert(o, PARAGRAPH, 0, 0, False)
        if name in ("new_line", "press_enter"):  # the Enter key is one line break here
            return self._insert(o, LINE, 0, 0, False)
        if name == "undo":
            return self._undo(o)
        if name == "scratch":
            return self._scratch(o)
        if name == "delete":
            if start == end:
                return self._scratch(o)
            self._place(o, start)
            self.E.delete_text(o, start, end)
            return {"ok": True}
        if name == "backspace":
            if start == end:
                start = max(0, end - max(1, min(99, int(arg or 1))))
            self._place(o, start)
            self.E.delete_text(o, start, end)
            self._place(o, start)
            return {"ok": True}
        if name == "select":
            # There is nowhere to draw choice numbers here, so take the nearest match.
            lo = max(0, caret - WINDOW)
            found = find_nearest(T.get_text(o, lo, min(count, caret + WINDOW)), caret - lo, arg)
            if found is None:
                return {"ok": False, "why": "can't find that"}
            self._select(o, lo + found[0], lo + found[1])
            return {"ok": True}
        if name == "select_last":
            found = self._last(o)
            if found is None:
                return {"ok": False, "why": "nothing to select"}
            self._select(o, *found)
            return {"ok": True}
        if name == "select_all":
            self._select(o, 0, count)
            return {"ok": True}
        if name == "unselect":
            self._place(o, end)
            return {"ok": True}
        if name == "line_end":
            self._place(o, caret + len(T.get_text(o, caret, min(count, caret + WINDOW)).split("\n", 1)[0]))
            return {"ok": True}
        if name == "line_start":
            self._place(o, caret - len(T.get_text(o, max(0, caret - WINDOW), caret).rsplit("\n", 1)[-1]))
            return {"ok": True}
        if name in ("para_end", "para_start"):
            self._place(o, self._paragraph_edge(o, name == "para_end"))
            return {"ok": True}
        if name in ("line_up", "line_down", "go_to_line", "select_line", "delete_line"):
            text = T.get_text(o, 0, count)
            number = max(1, int(arg or 1))
            if name in ("line_up", "line_down"):
                self._place(o, line_move(text, caret, number if name == "line_down" else -number))
            elif name == "go_to_line":
                self._place(o, line_move(text, 0, number - 1))
            elif name == "select_line":
                self._select(o, *line_span(text, caret))
            else:
                first, last = line_span(text, caret)
                for _ in range(min(number, 99) - 1):
                    last = line_span(text, min(last + 1, len(text)))[1]
                if last < len(text):
                    last += 1                      # with its line break, so lines below move up
                elif first > 0:
                    first -= 1                     # the last line: take the break before it
                self._place(o, first)
                self.E.delete_text(o, first, last)
                self._place(o, min(first, len(text) - (last - first)))
            return {"ok": True}
        if name in ("word_left", "word_right"):
            words = max(1, min(99, int(arg or 1)))
            if name == "word_left":
                self._place(o, caret - words_left(T.get_text(o, max(0, caret - WINDOW), caret), words))
            else:
                self._place(o, caret + words_right(T.get_text(o, caret, min(count, caret + WINDOW)), words))
            return {"ok": True}
        if name == "doc_top":
            self._place(o, 0)
            return {"ok": True}
        if name == "doc_end":
            self._place(o, count)
            return {"ok": True}
        if name in ("cap", "all_caps", "no_caps"):
            last = start == end
            if last:
                found = self._last(o)
                if found is None:
                    return {"ok": False, "why": "nothing to format"}
                start, end = found
            old = T.get_text(o, start, end)
            new = {"cap": old.title(), "all_caps": old.upper(), "no_caps": old.lower()}[name]
            if self._count(new) == self._count(old) and new != old:
                self._place(o, start)
                self.E.delete_text(o, start, end)
                self._put(o, start, new)
                if last:
                    self.history[-1]["text"] = new
                    self.history[-1]["start"] = start
                    self._place(o, end)
                else:
                    self._select(o, start, end)
            return {"ok": True}
        if name in ("bold", "italic", "underline"):
            return {"ok": False, "why": "plain text has no formatting"}
        if name == "choose":
            return {"ok": False, "why": "nothing to choose from"}
        return {"ok": False, "why": "unknown command"}

