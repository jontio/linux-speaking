"""What dictation does to a Writer document."""
import os
import re
import threading

import uno
import unohelper
from com.sun.star.awt import XCallback

from dictation.formatting import LINE, PARAGRAPH, Insertion, fit
from dictation.selecting import find_all, find_nearest
from dictation.words import Lexicon

PARAGRAPH_BREAK = 0  # com.sun.star.text.ControlCharacter
LINE_BREAK = 1
HISTORY = 20
NEARBY_PARAGRAPHS = 8
MAX_CHOICES = 20
# Numbers above matches are taken away after this long, whatever else happens.
CHOICE_SECONDS = float(os.environ.get("LINUX_SPEAKING_CHOICE_SECONDS", "25"))
BOLD = 150.0  # com.sun.star.awt.FontWeight
SINGLE_UNDERLINE = 1


def _upper_first(s):
    for i, c in enumerate(s):
        if c.isalpha():
            return i, c.upper()
    return -1, ""


class _ClearChoices(unohelper.Base, XCallback):
    """Runs on the main thread when numbered matches have been showing too long."""

    def __init__(self, ops, serial):
        self.ops = ops
        self.serial = serial

    def notify(self, data):
        if self.ops.choices and self.ops.choice_serial == self.serial:
            self.ops._clear_choices()


class Ops:
    def __init__(self, ctx):
        self.ctx = ctx
        self.smgr = ctx.ServiceManager
        self.desktop = self.smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        self.toolkit = self.smgr.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        self.lexicon = Lexicon.load_default()
        self.history = []  # (document, text range) of recent phrases, newest last
        self.choices = None  # (document, [text ranges]) while numbered matches are showing
        self.choice_serial = 0
        self.poster = self.smgr.createInstanceWithContext("com.sun.star.awt.AsyncCallback", ctx)
        self.check_focus = os.environ.get("LINUX_SPEAKING_NO_FOCUS_CHECK") != "1"
        self.keep_final = os.environ.get("LINUX_SPEAKING_KEEP_FINAL") == "1"

    # ---- finding the document -------------------------------------------
    def _document(self):
        doc = self.desktop.getCurrentComponent()
        if doc is None or not hasattr(doc, "supportsService") \
                or not doc.supportsService("com.sun.star.text.TextDocument"):
            return None, "no writer document"
        if self.check_focus and self.toolkit.getActiveTopWindow() is None:
            return None, "writer not focused"
        return doc, ""

    def handle(self, message):
        op = message.get("op")
        if op == "ping":
            return {"ok": True}
        if self.choices and op == "command" and message.get("name") == "cancel_choices":
            # Works even when Writer isn't in front: the numbers must never be left behind.
            self._clear_choices()
            return {"ok": True}
        doc, why = self._document()
        if op == "status":
            return {"ok": True, "ready": doc is not None, "why": why}
        if doc is None:
            return {"ok": False, "why": why}
        if self.choices and (op in ("insert", "dictate", "move") or (
                op == "command" and message.get("name") != "choose")):
            self._clear_choices()  # doing anything else takes the numbers away
        if op == "context":
            before, after, view, _ = self._around(doc)
            reply = {"ok": True, "before": before, "after": after}
            if not view.isCollapsed():
                reply["selected"] = True  # what is dictated will replace the selection
            return reply
        if op == "text":  # the whole document, for tests
            return {"ok": True, "text": doc.getText().getString(),
                    "rubies": self._rubies(doc), "modified": doc.isModified(),
                    "selected": doc.getCurrentController().getViewCursor().getString()}
        if op == "move":  # cursor movement described by the engine
            return self._move(doc, message.get("steps", []))
        if op == "insert":  # the engine has already fitted the text to its surroundings
            return self._apply(doc, Insertion(
                message.get("text", ""), int(message.get("delete_before", 0)),
                int(message.get("delete_after", 0)), bool(message.get("capitalise_next")),
            ))
        if op == "dictate":
            return self._dictate(doc, message.get("text", ""), message.get("spoken_off"))
        if op == "command":
            return self._command(doc, message.get("name", ""), message.get("arg", ""),
                                 bool(message.get("nearest")))
        return {"ok": False, "why": "unknown request"}

    # ---- reading around the cursor ---------------------------------------
    def _around(self, doc):
        """Text before and after the cursor (or selection) in its paragraph."""
        view = doc.getCurrentController().getViewCursor()
        text = view.getText()
        left = text.createTextCursorByRange(view.getStart())
        left.gotoStartOfParagraph(True)
        right = text.createTextCursorByRange(view.getEnd())
        right.gotoEndOfParagraph(True)
        return left.getString(), right.getString(), view, text

    def _last(self, doc):
        """The newest remembered phrase in this document, or None."""
        while self.history:
            owner, rng = self.history[-1]
            if owner == doc:  # a fresh proxy each time, so compare by value
                try:
                    rng.getString()
                    return rng
                except Exception:
                    pass
            self.history.pop()
        return None

    # ---- dictation ---------------------------------------------------------
    def _dictate(self, doc, raw, spoken_off=None):
        before, after, view, text = self._around(doc)
        ins = fit(raw, before, after, self.lexicon, keep_final=self.keep_final,
                  spoken_off=spoken_off)
        return self._apply(doc, ins)

    def _apply(self, doc, ins):
        """Put one fitted phrase into the document at the cursor or over the selection."""
        if not ins.text:
            return {"ok": True, "text": ""}
        view = doc.getCurrentController().getViewCursor()
        text = view.getText()
        undo = doc.getUndoManager()
        undo.enterUndoContext("Dictation")
        try:
            cursor = text.createTextCursorByRange(view.getStart())
            cursor.gotoRange(view.getEnd(), True)
            cursor.setString("")  # dictating over a selection replaces it
            if ins.delete_before:
                cursor.goLeft(ins.delete_before, True)
                cursor.setString("")
            if ins.delete_after:
                cursor.goRight(ins.delete_after, True)
                cursor.setString("")
            piece = ""
            for ch in ins.text + "\0":
                if ch in (PARAGRAPH, LINE, "\0"):
                    if piece:
                        text.insertString(cursor, piece, False)
                        piece = ""
                    if ch == PARAGRAPH:
                        text.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
                    elif ch == LINE:
                        text.insertControlCharacter(cursor, LINE_BREAK, False)
                else:
                    piece += ch
            if ins.capitalise_next:
                rest = text.createTextCursorByRange(cursor.getEnd())
                rest.gotoEndOfParagraph(True)
                i, upper = _upper_first(rest.getString())
                if i >= 0:
                    rest.collapseToStart()
                    rest.goRight(i, False)
                    rest.goRight(1, True)
                    rest.setString(upper)
            spoken = text.createTextCursorByRange(cursor.getEnd())
            spoken.goLeft(len(ins.text), True)
            self.history.append((doc, spoken))
            del self.history[:-HISTORY]
            view.gotoRange(cursor.getEnd(), False)
        finally:
            undo.leaveUndoContext()
        return {"ok": True, "text": ins.text}

    # ---- moving the cursor --------------------------------------------------
    def _move(self, doc, steps):
        """Run cursor-movement steps: ["view" or "text", method name, arguments...].

        "view" is the cursor on screen, which knows about lines. "text" is a text
        cursor starting from it, which knows about words, sentences and paragraphs.
        Only movement methods are allowed.
        """
        view = doc.getCurrentController().getViewCursor()
        cursor = None
        for step in steps:
            target, method, args = step[0], step[1], step[2:]
            if not re.fullmatch(r"(goto|go|collapse)[A-Za-z]*", method):
                return {"ok": False, "why": "not a movement"}
            if target == "text":
                if cursor is None:
                    cursor = view.getText().createTextCursorByRange(view.getStart())
                getattr(cursor, method)(*args)
            else:
                if cursor is not None:
                    view.gotoRange(cursor, False)
                    cursor = None
                getattr(view, method)(*args)
        if cursor is not None:
            view.gotoRange(cursor, False)
        return {"ok": True}

    # ---- commands ----------------------------------------------------------
    def _command(self, doc, name, arg, nearest=False):
        view = doc.getCurrentController().getViewCursor()
        if name == "new_paragraph":
            return self._dictate(doc, "new paragraph", ())
        if name == "new_line":
            return self._dictate(doc, "new line", ())
        if name in ("line_end", "line_start", "doc_top", "doc_end"):
            {"line_end": view.gotoEndOfLine, "line_start": view.gotoStartOfLine,
             "doc_top": view.gotoStart, "doc_end": view.gotoEnd}[name](False)
            return {"ok": True}
        if name in ("para_end", "para_start"):
            cursor = view.getText().createTextCursorByRange(view.getStart())
            if name == "para_end":
                cursor.gotoEndOfParagraph(False)
            else:
                cursor.gotoStartOfParagraph(False)
            view.gotoRange(cursor, False)
            return {"ok": True}
        if name == "undo":
            undo = doc.getUndoManager()
            if not undo.isUndoPossible():
                return {"ok": False, "why": "nothing to undo"}
            undo.undo()
            # Undo can leave the restored text selected; the next phrase would replace it.
            doc.getCurrentController().getViewCursor().collapseToEnd()
            return {"ok": True}
        if name == "scratch":
            return self._scratch(doc, view)
        if name == "backspace":
            def erase():
                if not view.isCollapsed():  # like the key, it removes a selection
                    view.setString("")
                    return
                cursor = view.getText().createTextCursorByRange(view.getStart())
                cursor.goLeft(max(1, min(99, int(arg or 1))), True)
                cursor.setString("")
            self._edit(doc, "Backspace", erase)
            return {"ok": True}
        if name == "delete":
            if view.isCollapsed():
                return self._scratch(doc, view)
            self._edit(doc, "Delete", lambda: view.setString(""))
            return {"ok": True}
        if name == "select":
            if nearest:
                return self._select(doc, view, arg)
            return self._select_or_number(doc, view, arg)
        if name == "cancel_choices":
            return {"ok": True}  # already cleared in handle()
        if name == "choose":
            if not self.choices:
                return {"ok": False, "why": "nothing to choose from"}
            matches = self.choices[1]
            n = int(arg or 0)
            if not 1 <= n <= len(matches):
                return {"ok": False, "why": "no such number"}
            self._clear_choices()
            doc.getCurrentController().select(matches[n - 1])
            return {"ok": True}
        if name == "select_last":
            rng = self._last(doc)
            if rng is None:
                return {"ok": False, "why": "nothing to select"}
            doc.getCurrentController().select(rng)
            return {"ok": True}
        if name == "unselect":
            view.collapseToEnd()
            return {"ok": True}
        if name in ("bold", "italic", "underline", "cap", "all_caps", "no_caps"):
            return self._format(doc, view, name)
        return {"ok": False, "why": "unknown command"}

    def _edit(self, doc, title, action):
        undo = doc.getUndoManager()
        undo.enterUndoContext(title)
        try:
            action()
        finally:
            undo.leaveUndoContext()

    def _scratch(self, doc, view):
        rng = self._last(doc)
        if rng is None:
            return {"ok": False, "why": "nothing to scratch"}
        self.history.pop()

        def remove():
            rng.setString("")
            view.gotoRange(rng.getStart(), False)

        self._edit(doc, "Scratch that", remove)
        return {"ok": True}

    def _format(self, doc, view, name):
        selected = not view.isCollapsed()
        if selected:
            target = view.getText().createTextCursorByRange(view.getStart())
            target.gotoRange(view.getEnd(), True)
        else:
            target = self._last(doc)
        if target is None:
            return {"ok": False, "why": "nothing to format"}

        def apply():
            if name == "bold":
                target.setPropertyValue("CharWeight", BOLD)
            elif name == "italic":
                target.setPropertyValue(
                    "CharPosture", uno.Enum("com.sun.star.awt.FontSlant", "ITALIC")
                )
            elif name == "underline":
                target.setPropertyValue("CharUnderline", SINGLE_UNDERLINE)
            else:
                old = target.getString()
                new = {"cap": old.title(), "all_caps": old.upper(),
                       "no_caps": old.lower()}[name]
                # Change one character at a time so the formatting survives.
                text = target.getText()
                walker = text.createTextCursorByRange(target.getStart())
                for a, b in zip(old, new):
                    walker.goRight(1, True)
                    if a != b:
                        walker.setString(b)
                    walker.collapseToEnd()
                # Editing can shift the edges of a range, so rebuild it.
                again = text.createTextCursorByRange(walker.getEnd())
                again.goLeft(len(new), True)
                if selected:
                    doc.getCurrentController().select(again)
                else:
                    self.history[-1] = (doc, again)

        self._edit(doc, "Format that", apply)
        return {"ok": True}

    def _rubies(self, doc):
        """The ruby texts in the document, in order. For tests."""
        found = []
        paragraphs = doc.getText().createEnumeration()
        while paragraphs.hasMoreElements():
            paragraph = paragraphs.nextElement()
            if not hasattr(paragraph, "createEnumeration"):
                continue
            portions = paragraph.createEnumeration()
            while portions.hasMoreElements():
                portion = portions.nextElement()
                if portion.TextPortionType == "Ruby" and portion.IsStart:
                    found.append(portion.RubyText)
        return found

    # ---- numbered matches, like Dragon's --------------------------------------
    def _quietly(self, doc, action):
        """Change the document without adding an undo step or marking it modified."""
        undo = doc.getUndoManager()
        modified = doc.isModified()
        undo.lock()
        try:
            action()
        finally:
            undo.unlock()
            doc.setModified(modified)

    def _matches(self, view, phrase):
        """A text range for every match in the paragraphs around the cursor, in order."""
        text = view.getText()
        found = []
        for steps in range(-NEARBY_PARAGRAPHS, NEARBY_PARAGRAPHS + 1):
            c = text.createTextCursorByRange(view.getStart())
            moved = True
            for _ in range(abs(steps)):
                moved = c.gotoNextParagraph(False) if steps > 0 else c.gotoPreviousParagraph(False)
                if not moved:
                    break
            if not moved:
                continue
            c.gotoStartOfParagraph(False)
            c.gotoEndOfParagraph(True)
            for start, end in find_all(c.getString(), phrase):
                m = text.createTextCursorByRange(c.getStart())
                while start > 30000:  # goRight takes a short
                    m.goRight(30000, False)
                    start -= 30000
                    end -= 30000
                m.goRight(start, False)
                m.goRight(end - start, True)
                found.append(m)
        return found[:MAX_CHOICES]

    def _select_or_number(self, doc, view, phrase):
        matches = self._matches(view, phrase)
        if not matches:
            return {"ok": False, "why": "can't find that"}
        if len(matches) == 1:
            doc.getCurrentController().select(matches[0])
            return {"ok": True}

        def number():
            for i, m in enumerate(matches, start=1):
                m.setPropertyValue("RubyText", str(i))  # small text above the words

        self._quietly(doc, number)
        self.choices = (doc, matches)
        # A safety net in case the engine quits or can't reach us to cancel.
        self.choice_serial += 1
        timer = threading.Timer(
            CHOICE_SECONDS, self.poster.addCallback,
            (_ClearChoices(self, self.choice_serial), None),
        )
        timer.daemon = True
        timer.start()
        return {"ok": True, "choices": len(matches)}

    def _clear_choices(self):
        if not self.choices:
            return
        doc, matches = self.choices
        self.choices = None

        def clear():
            for m in matches:
                try:
                    m.setPropertyToDefault("RubyText")
                except Exception:
                    pass

        try:
            self._quietly(doc, clear)
        except Exception:
            pass  # the document may have been closed

    def _select(self, doc, view, phrase):
        text = view.getText()
        here = text.createTextCursorByRange(view.getStart())
        here.gotoStartOfParagraph(True)
        caret = len(here.getString())

        def paragraph_at(steps):
            """A cursor at the start of the paragraph `steps` away, with its text."""
            c = text.createTextCursorByRange(view.getStart())
            for _ in range(abs(steps)):
                moved = c.gotoNextParagraph(False) if steps > 0 else c.gotoPreviousParagraph(False)
                if not moved:
                    return None, None
            c.gotoStartOfParagraph(False)
            c.gotoEndOfParagraph(True)
            return c, c.getString()

        order = [0]
        for n in range(1, NEARBY_PARAGRAPHS + 1):
            order += [-n, n]
        for steps in order:
            c, content = paragraph_at(steps)
            if c is None:
                continue
            where = caret if steps == 0 else (len(content) if steps < 0 else 0)
            found = find_nearest(content, where, phrase)
            if found:
                start, end = found
                c.collapseToStart()
                while start > 0:  # goRight takes a short
                    step = min(start, 30000)
                    c.goRight(step, False)
                    start -= step
                    end -= step
                c.goRight(end - start, True)
                doc.getCurrentController().select(c)
                return {"ok": True}
        return {"ok": False, "why": "can't find that"}
