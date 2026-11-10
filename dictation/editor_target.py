"""Dictating into Kate and KWrite, through the desktop's accessibility interface.

Kate has no add-on that could talk to the engine, but like a screen reader the engine
can read its text and cursor and make edits. Everything here runs in the engine.
Kate must be started with QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 for this to work.
"""
from __future__ import annotations

import re

from .formatting import LINE, PARAGRAPH
from .selecting import find_nearest

APPS = ("kate", "kwrite")
NAMES = {"kate": "Kate", "kwrite": "KWrite"}
WINDOW = 4000  # how far around the cursor to read
HISTORY = 20
BLANK_LINE = re.compile(r"\n[ \t]*(?=\n)")  # the end of a line that a blank line follows
AFTER_BLANK = re.compile(r"\n(?:[ \t]*\n)+")  # ends where the line after blank lines starts


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
    def __init__(self):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        self.A = Atspi
        self.T = Atspi.Text
        self.E = Atspi.EditableText
        self.name = ""
        self._object = None
        self._app = None
        self.history = []  # {"start", "text", "edits"} for recent phrases, newest last

    # ---- finding the editor ---------------------------------------------------
    def _is_focused_editor(self, o) -> bool:
        states = o.get_state_set()
        S = self.A.StateType
        return (states.contains(S.FOCUSED) and states.contains(S.EDITABLE)
                and states.contains(S.MULTI_LINE) and o.get_editable_text_iface() is not None)

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

    def focused(self):
        """The text area with the keyboard focus in Kate or KWrite, or None."""
        try:
            if self._object is not None and self._is_focused_editor(self._object):
                return self._object
        except Exception:
            pass
        self._object = None
        desktop = self.A.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            try:
                if app is None or app.get_name() not in APPS:
                    continue
                found = self._search(app)
            except Exception:
                continue
            if found is not None:
                if self._app is None or app.get_process_id() != self._app.get_process_id():
                    self.history = []
                self._object, self._app = found, app
                self.name = NAMES.get(app.get_name(), app.get_name())
                return found
        return None

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
            before, after, _, _ = self._around(o)
            return {"ok": True, "before": before, "after": after}
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
            self.E.insert_text(o, position, text, units(text))
            edits += 1
        after = position + units(text)
        if capitalise_next:
            rest = self.T.get_text(o, after, min(self.T.get_character_count(o), after + 200))
            rest = rest.split("\n", 1)[0]
            for i, c in enumerate(rest):
                if c.isalpha():
                    if c != c.upper() and units(c.upper()) == 1:
                        self.E.delete_text(o, after + i, after + i + 1)
                        self.E.insert_text(o, after + i, c.upper(), 1)
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
        size = units(phrase["text"])
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
        if name == "new_line":
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
            if units(new) == units(old) and new != old:
                self._place(o, start)
                self.E.delete_text(o, start, end)
                self.E.insert_text(o, start, new, units(new))
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
