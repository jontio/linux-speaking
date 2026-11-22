"""Stand-ins for the programs dictated into, each keeping its record of what was typed the
way its real link does (each ported from the link's own code), with an undo stack of whole
steps as the program's own Undo has. Only the parts the engine's requests reach.

  Writer  - extension/pythonpath/ls_ops.py: Ops._apply / _scratch / _last / undo / redo
  Word    - dictation/word_target.py: WordTarget._insert / _scratch / _last / undo / redo
  VSCode  - vscode/extension.js: insert / lastRange / scratch / undo / redo

Each program's own "scratch" takes away its newest insertion and puts back nothing that the
insertion took out; "select_last" ("correct that") selects the newest insertion, and the
formatting commands act on it. That is why a full stop typed by itself, after a quiet spell,
has to be taken back before any of them (see Engine._scratch_the_mark).

The document is one line; the cursor is an index into it. Ranges are [start, end] that move
as the text changes. LibreOffice moves every index at the place text is put in, so in Writer
text put in at a range's end goes behind it (Doc.move_at_insert).
"""
from dictation.formatting import LINE, PARAGRAPH


class Range:
    def __init__(self, doc, start, end):
        self.doc, self.start, self.end = doc, start, end
        doc.ranges.append(self)

    @property
    def text(self):
        return self.doc.text[self.start:self.end]


class Doc:
    move_at_insert = False
    name = "a program"
    other = None

    def __init__(self, text=""):
        self.text, self.cursor, self.ranges = text, len(text), []
        self.selection = None               # (start, end), or None
        self.correcting = False             # after "correct ...": the cursor goes back to the end
        self.undos, self.redos = [], []     # each a list of (pos, removed, inserted)
        self.asked, self.formatted = [], []

    def describe(self):
        return self.name

    def pick(self):
        pass

    def inserts(self):
        return [(m["text"], m.get("delete_before", 0)) for m in self.asked if m["op"] == "insert"]

    # ---- the document
    def edit(self, pos, removed_len, new, record=None):
        removed = self.text[pos:pos + removed_len]
        self.text = self.text[:pos] + new + self.text[pos + removed_len:]
        n, r = len(new), removed_len
        for rg in self.ranges:
            collapsed = rg.start == rg.end
            for edge in ("start", "end"):
                x = getattr(rg, edge)
                if x > pos + r:
                    x += n - r
                elif x > pos:
                    x = pos
                elif x == pos and r == 0 and n and (self.move_at_insert or (edge == "start" and not collapsed)):
                    x += n                  # text put in at a range's start is not in it
                setattr(rg, edge, x)
        if self.cursor > pos + r:
            self.cursor += n - r
        elif self.cursor >= pos:
            self.cursor = pos + n
        if record is not None:
            record.append((pos, removed, new))

    def step(self, edits):
        self.undos.append(edits)
        self.redos.clear()

    def undo(self):
        if not self.undos:
            return False
        edits = self.undos.pop()
        for pos, removed, new in reversed(edits):
            self.edit(pos, len(new), removed)
            self.cursor = pos + len(removed)
        self.redos.append(edits)
        self.selection = None
        return True

    def redo(self):
        if not self.redos:
            return False
        edits = self.redos.pop()
        for pos, removed, new in edits:
            self.edit(pos, len(removed), new)
            self.cursor = pos + len(new)
        self.undos.append(edits)
        self.selection = None
        return True

    def context(self):
        if self.selection:
            start, end = self.selection
            return {"ok": True, "before": self.text[:start][-200:], "after": self.text[end:],
                    "selected": self.text[start:end]}
        return {"ok": True, "before": self.text[:self.cursor][-200:], "after": self.text[self.cursor:]}

    def put_in(self, text, delete_before):
        """The insertion, over the selection if there is one: (where it starts, the edits)."""
        record = []
        if self.selection:
            start, end = self.selection
            self.selection = None
            self.edit(start, end - start, "", record)
            self.cursor = start
        if delete_before:
            self.edit(self.cursor - delete_before, delete_before, "", record)
        start = self.cursor
        self.edit(start, 0, text, record)
        return start, record

    # ---- what the engine asks
    def request(self, m):
        self.asked.append(dict(m))
        op = m["op"]
        if op == "command" and m.get("name") in ("new_paragraph", "new_line"):
            # The programs answer these by inserting the break like any phrase.
            m = dict(op="insert", text=PARAGRAPH if m["name"] == "new_paragraph" else LINE,
                     delete_before=0)
            op = "insert"
        if op == "context":
            return self.context()
        if op == "insert":
            text = m.get("text", "")
            if not text and not m.get("delete_before") and not self.selection:
                return {"ok": True, "text": ""}
            start, record = self.put_in(text, int(m.get("delete_before", 0)))
            self.step(record)
            self.inserted(start, text)
            if self.correcting:               # "correct ...": back to where the cursor was
                self.correcting, self.cursor = False, len(self.text)
                return {"ok": True, "text": text, "back": True}
            return {"ok": True, "text": text}
        if op == "command":
            name = m["name"]
            if name == "undo":
                return self.undone()
            if name == "redo":
                return self.redone()
            if name == "delete" and self.selection:
                start, end = self.selection
                self.selection = None
                record = []
                self.edit(start, end - start, "", record)
                self.cursor = start
                self.step(record)
                return {"ok": True}
            if name in ("scratch", "delete"):
                found = self.last()
                if found is None:
                    return {"ok": False, "why": "nothing to scratch"}
                self.forget_last()
                start, end = found
                record = []
                self.edit(start, end - start, "", record)
                self.cursor = start
                self.step(record)
                return {"ok": True}
            if name == "select_last":
                found = self.last()
                if found is None:
                    return {"ok": False, "why": "nothing to select"}
                self.selection = found
                return {"ok": True}
            if name in ("select", "correct"):
                # The nearest match before the cursor, as the programs look for it.
                arg = str(m.get("arg", "")).strip()
                at = self.text[:self.cursor].lower().rfind(arg.lower()) if arg else -1
                if at < 0:
                    return {"ok": False, "why": "can't find that"}
                self.selection = (at, at + len(arg))
                self.correcting = name == "correct"
                return {"ok": True}
            if name == "unselect":
                if self.selection:
                    self.cursor, self.selection = self.selection[1], None
                return {"ok": True}
            if name in ("cap", "all_caps", "no_caps", "bold", "italic", "underline"):
                found = self.last()
                if found is None:
                    return {"ok": False, "why": "nothing to format"}
                start, end = found
                self.formatted.append((name, self.text[start:end]))
                if name in ("cap", "all_caps", "no_caps"):     # the letters change
                    old = self.text[start:end]
                    new = {"cap": old.title(), "all_caps": old.upper(), "no_caps": old.lower()}[name]
                    self.text = self.text[:start] + new + self.text[end:]
                return {"ok": True}
        return {"ok": False, "why": "unknown command"}

    # each program keeps its record its own way
    def inserted(self, start, text):
        raise NotImplementedError

    def last(self):
        raise NotImplementedError

    def forget_last(self):
        raise NotImplementedError

    def undone(self):
        return {"ok": True} if self.undo() else {"ok": False, "why": "nothing to undo"}

    def redone(self):
        return {"ok": True} if self.redo() else {"ok": False, "why": "nothing to redo"}


class Writer(Doc):
    """Ops.history: ranges, newest last. Ops._last takes the newest whose range still
    answers, an emptied one included."""
    name = "Writer"
    move_at_insert = True

    def __init__(self, text=""):
        super().__init__(text)
        self.history = []

    def inserted(self, start, text):
        if text:
            self.history.append(Range(self, start, start + len(text)))

    def last(self):
        return (self.history[-1].start, self.history[-1].end) if self.history else None

    def forget_last(self):
        self.history.pop()


class Word(Writer):
    """WordTarget: as Writer's, but an emptied range is dropped and the one before looked at."""
    name = "Word"
    move_at_insert = False

    def last(self):
        while self.history:
            rng = self.history[-1]
            if rng.start != rng.end:
                return rng.start, rng.end
            self.history.pop()
        return None


class VSCode(Doc):
    """extension.js: {start, text}, start a fixed place; the phrase must still be there."""
    name = "VS Code"

    def __init__(self, text=""):
        super().__init__(text)
        self.history, self.taken = [], None

    def inserted(self, start, text):
        self.taken = None
        if text:
            self.history.append({"start": start, "text": text})

    def last(self):
        if not self.history:
            return None
        phrase = self.history[-1]
        tries = [phrase["start"]]
        if self.cursor >= len(phrase["text"]):
            tries.append(self.cursor - len(phrase["text"]))
        for start in tries:
            if self.text[start:start + len(phrase["text"])] == phrase["text"]:
                return start, start + len(phrase["text"])
        return None

    def forget_last(self):
        self.history.pop()

    def undone(self):
        found = self.last()
        self.undo()
        self.taken = self.history.pop() if found and self.history else None
        return {"ok": True}

    def redone(self):
        self.redo()
        if self.taken:
            self.history.append(self.taken)
        self.taken = None
        return {"ok": True}


PROGRAMS = (Writer, Word, VSCode)
