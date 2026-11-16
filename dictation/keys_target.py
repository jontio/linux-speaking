"""Windows: dictating into any program's text box, by typing.

For programs with no link of their own, such as a chat box in a web page. What is around
the cursor is read through Windows' accessibility interface (UI Automation), so spacing
and capitals still fit. The words themselves go in as keystrokes, as if typed.

Because keystrokes go to whatever has the keyboard, nothing is typed unless Windows says
that is a text box that can be edited and isn't a password box.
"""
from __future__ import annotations

import os
import queue
import threading
import time
import unicodedata

from .formatting import LINE, PARAGRAPH, fit
from .selecting import find_nearest
from .words import Lexicon

HISTORY = 20
READ = 1000        # how far around the cursor to read
WHOLE = 20000      # the most text looked through for "select ..."
MOST = 400000      # the longest text an edit box is asked for whole, each time
UP = 12            # how far out from the cursor the text box is looked for
SLACK = 4          # screen pixels by which text before the cursor may seem to pass it
OBJID_CARET = 0xFFFFFFF8   # "give me this window's text cursor"
INVISIBLE = 0x8000         # its state when there is none to be seen
# Characters nobody sees, which some programs keep in a line with nothing on it.
UNSEEN = dict.fromkeys(map(ord, "\u200b\u2060\ufeff"))
NOT_FOCUSED = {"ok": False, "why": "editor not focused"}
NAMES = {"code": "VS Code", "msedge": "Edge", "chrome": "Chrome", "firefox": "Firefox",
         "notepad": "Notepad", "teams": "Teams", "ms-teams": "Teams", "slack": "Slack"}

# Keys by name, as Windows numbers them. Those in EXTENDED need a flag saying so.
KEYS = {"enter": 0x0D, "backspace": 0x08, "delete": 0x2E, "tab": 0x09, "home": 0x24,
        "end": 0x23, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "ctrl": 0x11, "shift": 0x10, "a": 0x41, "z": 0x5A}
EXTENDED = {"delete", "home", "end", "left", "up", "right", "down"}

# What each command is on the keyboard: (keys held together, how many times per count).
COMMAND_KEYS = {
    "press_enter": "enter", "undo": "ctrl+z", "select_all": "ctrl+a",
    "line_end": "end", "line_start": "home", "doc_top": "ctrl+home", "doc_end": "ctrl+end",
    "word_left": "ctrl+left", "word_right": "ctrl+right", "line_up": "up", "line_down": "down",
}
COUNTED = {"word_left", "word_right", "line_up", "line_down"}


def units(text: str) -> int:
    """Length in UTF-16 units, which is how keystrokes and Backspace count."""
    return len(text.encode("utf-16-le")) // 2


def steps_for_text(text: str) -> list:
    """The keystrokes that type `text`: [("type", words) or ("press", keys, times), ...].

    A line break is Shift+Enter, because plain Enter sends the message in a chat box. A
    paragraph break is two of them: a blank line.
    """
    steps, piece = [], ""
    for c in text + "\0":
        special = {"\t": ("tab", 1), LINE: ("shift+enter", 1), "\n": ("shift+enter", 1),
                   PARAGRAPH: ("shift+enter", 2)}.get(c)
        if special or c == "\0":
            if piece:
                steps.append(("type", piece))
                piece = ""
            if special:
                steps.append(("press",) + special)
        elif c != "\r":
            piece += c
    return steps


def typed_length(text: str) -> int:
    """How many Backspaces take `text` away again after it has been typed."""
    return sum(units(step[1]) if step[0] == "type" else step[2] for step in steps_for_text(text))


def steps_for_insert(text: str, delete_before: int, delete_after: int, selected: bool) -> list:
    steps = []
    if selected:
        steps.append(("press", "backspace", 1))   # what is said takes the selection's place
    if delete_before:
        steps.append(("press", "backspace", delete_before))
    if delete_after:
        steps.append(("press", "delete", delete_after))
    return steps + steps_for_text(text)


def box_kind(window_class: str) -> str:
    """How a window can be asked for its text by message: "rich" or "plain" for Windows'
    own edit boxes, "bytes" for the editing area of Notepad++ and its like (Scintilla),
    which says where things are in bytes, and "" for a window that can't be asked."""
    name = window_class.lower()
    if "richedit" in name:
        return "rich"
    if name == "edit" or ".edit." in name:
        return "plain"
    return "bytes" if name == "scintilla" else ""


def takes_text_whole(window_class: str) -> bool:
    """Whether a window of this class is one of Windows' own edit boxes, plain or rich,
    which can be handed text whole. Notepad's is one."""
    return box_kind(window_class) in ("rich", "plain")


def placed(text: str, first: int, last: int, kind: str) -> tuple:
    """(the text, where the selection starts, where it ends), counted in characters, for a
    box of this `kind` that gave all its `text` and said where its selection is.

    A rich edit box counts each line break as one character but gives it back as two, so
    its text is put the way it counts. A "bytes" box counts in bytes of UTF-8.
    """
    if kind == "rich":
        text = text.replace("\r\n", "\r")
    elif kind == "bytes":
        raw = text.encode("utf-8")
        first, last = (len(raw[:place].decode("utf-8", "ignore")) for place in (first, last))
    first = max(0, min(first, len(text)))
    return text, first, max(first, min(last, len(text)))


def place_in(text: str, at: int, kind: str) -> int:
    """Where character `at` of `text` is, as a box of this `kind` counts."""
    return len(text[:at].encode("utf-8")) if kind == "bytes" else at


def around(text: str, first: int, last: int) -> tuple:
    """(before, after, selected), at most READ characters each side."""
    return text[max(0, first - READ):first], text[last:last + READ], text[first:last]


def as_one_piece(text: str) -> str:
    """`text` as an edit box is handed it: its line breaks as that box keeps them."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace(PARAGRAPH, "\n\n").replace(LINE, "\n").replace("\n", "\r\n")


def keystrokes(text: str, lookup, caps: bool = False) -> list:
    """How `text` is typed on the keyboard: ("key", which key, whether with Shift) for a
    character the keyboard has, and ("char", the character) for one it hasn't.

    `lookup(character)` gives (key, modifiers) for a character that has a key, where
    modifiers is 0 for none and 1 for Shift, and None for one that hasn't. A character
    that needs Ctrl or Alt held is sent as itself. `caps` is whether Caps Lock is on,
    which turns Shift round for letters.
    """
    found = []
    for c in text:
        key = lookup(c)
        if key is None or key[1] not in (0, 1):
            found.append(("char", c))
        else:
            found.append(("key", key[0], bool(key[1]) != (caps and c.isalpha())))
    return found


def says_empty(value) -> bool:
    """Whether a text box's own account of what is in it says nothing has been typed.
    `value` is None for a box that gives no account."""
    return value is not None and not value.translate(UNSEEN).strip("\r\n")


def drawn_after(caret: tuple, rects: list) -> bool:
    """Whether text read as being before the cursor is drawn after it, on the cursor's
    own line. `caret` and each of `rects` are (left, top, width, height) on the screen.

    Text that was typed ends where the cursor is. A hint shown in an empty box ("Type a
    message") starts there and runs on to the right. So it is a hint only if nothing on
    the cursor's line is to the left of the cursor and something is to the right.
    """
    left, top, _, height = caret
    if height <= 0:
        return False
    after = False
    for r_left, r_top, r_width, r_height in rects:
        if r_width <= 1 or r_height <= 1:
            continue                      # nothing is drawn there
        shared = min(top + height, r_top + r_height) - max(top, r_top)
        if shared * 2 <= min(height, r_height):
            continue                      # another line
        if r_left < left - SLACK:
            return False                  # text to the left of the cursor: it was typed
        after = after or r_left + r_width > left + SLACK
    return after


def right_to_left(text: str) -> bool:
    """Whether `text` has writing that runs right to left, where "before" is to the right."""
    return any(unicodedata.bidirectional(c) in ("R", "AL") for c in text)


def program_name(exe: str) -> str:
    stem = exe[:-4] if exe.lower().endswith(".exe") else exe
    return NAMES.get(stem.lower(), stem[:1].upper() + stem[1:]) or "another program"


class Box:
    """A text box that has the keyboard, as read through UI Automation."""

    def __init__(self, before: str, after: str, selected: str, program: str):
        self.before, self.after, self.selected, self.program = before, after, selected, program


class KeysTarget:
    """`everything` is called each time: the "other programs" tick box in Settings."""

    OWN_THREAD = True   # requests are answered on a thread of the target's own (for COM)

    def __init__(self, everything=lambda: False, look=None, press=None):
        self.everything = everything
        self.name = "another program"
        self.lexicon = Lexicon.load_default()
        self.history = []                 # what was typed lately, newest last
        self.seen = ""                    # what last had the keyboard, for the log
        self._look = look                 # for tests: returns a Box or None
        self._press = press or self._type  # for tests: receives the list of steps
        self._as_keys = True              # how text is typed into the program in front
        self._edit = None                 # its window, if that can be handed text whole
        self._edit_text = None            # for a box asked by message: its text, cursor, window, kind
        self._uia = None
        self._acc = None                  # the older accessibility interface, for the cursor
        self._jobs: queue.Queue = queue.Queue()
        if look is None and self.OWN_THREAD:
            threading.Thread(target=self._run, daemon=True).start()

    # ---- called from the engine's threads -------------------------------------------
    def request(self, message: dict, timeout: float = 6.0) -> dict:
        """Answer one request, in the same form as the Writer extension. Never raises."""
        if not self.everything():
            return {"ok": True, "ready": False} if message.get("op") == "status" else dict(NOT_FOCUSED)
        if self._look is not None or not self.OWN_THREAD:   # under test, or no thread needed
            return self._answer(message)
        done, box = threading.Event(), {}
        self._jobs.put((message, box, done, time.monotonic() + timeout))
        if not done.wait(timeout):
            return {"ok": False, "why": "the program isn't answering"}
        return box["reply"]

    def _run(self) -> None:
        import comtypes  # the first import sets this thread up for COM by itself
        try:
            comtypes.CoInitialize()
        except OSError:
            pass                          # already done
        while True:
            message, box, done, deadline = self._jobs.get()
            if time.monotonic() > deadline:
                continue
            box["reply"] = self._answer(message)
            done.set()

    def _answer(self, message: dict) -> dict:
        try:
            return self._handle(message)
        except Exception as e:
            return {"ok": False, "why": "error", "error": str(e)[:200]}

    # ---- reading the text box that has the keyboard -------------------------------------
    def _box(self):
        if self._look is not None:
            return self._look()
        import comtypes.client
        if self._uia is None:
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient
            self._api = UIAutomationClient
            self._uia = comtypes.client.CreateObject(
                UIAutomationClient.CUIAutomation, interface=UIAutomationClient.IUIAutomation)
        api = self._api
        from . import winapi
        program, window_class, window = winapi.focused()
        self._edit_text = None
        if window and box_kind(window_class):
            done, box = self._edit_box(program, window_class, window)
            if done:
                return box
        element = self._uia.GetFocusedElement()
        self.seen = f"{program} control type {element.CurrentControlType}"
        # A browser, or a program built from one, takes characters sent as themselves, in
        # a burst. Windows 11's Notepad doesn't: it writes the last character of a burst
        # for each of them, and drops some key presses sent as fast. One of Windows' own
        # edit boxes, as Notepad's is, is handed the text whole instead, and anything else
        # gets key presses at a pace it can follow.
        self._as_keys = (element.CurrentFrameworkId or "") != "Chrome"
        self._edit = window if self._as_keys and takes_text_whole(window_class) else None
        if element.CurrentProcessId == os.getpid() or element.CurrentIsPassword:
            return None                   # our own windows, and never a password box
        raw = element.GetCurrentPattern(api.UIA_TextPatternId)
        pattern = raw.QueryInterface(api.IUIAutomationTextPattern) if raw else None
        if pattern is None:
            self.seen += ", no text to read"
            return None
        chosen = pattern.GetSelection()
        if chosen.Length < 1:
            self.seen += ", no cursor"
            return None
        here = chosen.GetElement(0)
        if here.GetAttributeValue(api.UIA_IsReadOnlyAttributeId) is True:
            self.seen += ", read only"
            return None
        start, end = api.TextPatternRangeEndpoint_Start, api.TextPatternRangeEndpoint_End
        field = self._field(element, here)
        own = self._own(pattern, element, field)
        self._pattern, self._here = pattern, here
        if field is not None and says_empty(self._value(field)):
            # Nothing has been typed. What can be read is the box's hint ("Type a
            # message"), or its name: a browser gives those as if they were its text.
            self._whole = None
            return Box("", "", "", program)
        self._whole = own if own is not None else pattern.DocumentRange
        before = here.Clone()
        before.MoveEndpointByRange(end, here, start)
        before.MoveEndpointByUnit(start, api.TextUnit_Character, -READ)
        after = here.Clone()
        after.MoveEndpointByRange(start, here, end)
        after.MoveEndpointByUnit(end, api.TextUnit_Character, READ)
        at_start = at_end = False
        if own is not None:
            # No further than the box's own text: in a web page, reading on from the box
            # runs into the page around it, such as a label on the same line. A cursor at
            # the box's end can count as beyond it, and then cutting the range back
            # doesn't work, so that case is settled by asking where the cursor is.
            try:
                at_start = here.CompareEndpoints(start, own, start) <= 0
                at_end = here.CompareEndpoints(end, own, end) >= 0
                if not at_start and before.CompareEndpoints(start, own, start) < 0:
                    before.MoveEndpointByRange(start, own, start)
                if not at_end and after.CompareEndpoints(end, own, end) > 0:
                    after.MoveEndpointByRange(end, own, end)
            except Exception:
                at_start = at_end = False
        before_text = "" if at_start else before.GetText(-1) or ""
        after_text = "" if at_end else after.GetText(-1) or ""
        selected = here.GetText(-1) or ""
        if own is not None and not selected and self._hint(here, before, before_text, after_text):
            self._whole = None
            return Box("", "", "", program)
        return Box(before_text, after_text, selected, program)

    def _edit_box(self, program: str, window_class: str, window) -> tuple:
        """(whether that settles it, the Box or None) for a box that can be asked for its
        text by message: one of Windows' own edit boxes, as Notepad's text area is, or
        the editing area of Notepad++.

        The accessibility interface is kept out of it. Read that way, Windows 11's
        Notepad takes its text cursor off the screen until a key is pressed, and
        Notepad++ offers nothing to read at all.
        """
        from . import winapi
        kind = box_kind(window_class)
        self.seen = f"{program} edit box {window_class}"
        self._as_keys, self._edit = True, None
        if winapi.window_process(window) == os.getpid():
            return True, None             # our own windows
        refused = winapi.edit_refuses(window, scintilla=kind == "bytes")
        if refused:
            self.seen += ", " + refused
            return True, None             # never a password box, or one that can't be changed
        read = winapi.edit_text(window, MOST)
        if read is None:
            return kind == "bytes", None  # too long to ask for whole, or no answer
        text, first, last = placed(*read, kind)
        if kind != "bytes":
            self._edit = window           # and it can be handed text whole
        self._edit_text = (text, first, window, kind)
        return True, Box(*around(text, first, last), program)

    def _hint(self, here, before, text: str, rest: str) -> bool:
        """Whether what reads as the text before the cursor is a hint shown in an empty
        box. Some programs give the hint as the box's text, and even as what the box
        says is in it, so it is told by where it is drawn: see drawn_after().

        `text` and `rest` are the box's own text before and after the cursor.
        """
        line = text.replace("\r", "\n").strip("\n")
        if not line.strip() or "\n" in line or rest.translate(UNSEEN).strip("\r\n"):
            return False                  # nothing there, or more than a hint would be
        typed = self.history[-1].replace(PARAGRAPH, "\n").replace(LINE, "\n").rsplit("\n", 1)[-1] \
            if self.history else ""
        if right_to_left(line) or (typed.strip() and line.endswith(typed)):
            return False                  # or it ends with what was typed here last
        try:
            # Where the cursor is drawn is asked of the window. What the text reader says
            # can be the far end of the hint, which is where typed text would put it.
            said = _rects(here)
            caret = self._caret() or (said[0] if len(said) == 1 else None)
            return caret is not None and drawn_after(caret, _rects(before))
        except Exception:
            return False

    def _caret(self):
        """Where the cursor is drawn on the screen, as (left, top, width, height), or
        None if the program in front doesn't say."""
        import ctypes
        import comtypes.client
        from . import winapi
        try:
            window = winapi.focused()[2]
            if not window:
                return None
            if self._acc is None:
                comtypes.client.GetModule("oleacc.dll")
                from comtypes.gen import Accessibility
                self._acc = Accessibility
            found = ctypes.POINTER(self._acc.IAccessible)()
            ctypes.oledll.oleacc.AccessibleObjectFromWindow(
                window, OBJID_CARET, ctypes.byref(self._acc.IAccessible._iid_),
                ctypes.byref(found))
            if int(found.accState(0) or 0) & INVISIBLE:
                return None
            left, top, width, height = found.accLocation(0)
            return (left, top, width, height) if height > 0 else None
        except Exception:
            return None

    def _field(self, focused, here):
        """The text box the cursor is in, or None if it isn't in one.

        Often that is what has the keyboard. But a web page can say the whole page has
        it, with the box somewhere inside, so the box is looked for from the cursor out.
        """
        api = self._api
        boxes = (api.UIA_EditControlTypeId, api.UIA_ComboBoxControlTypeId)
        try:
            node, walker = here.GetEnclosingElement(), self._uia.RawViewWalker
            for _ in range(UP):
                if node.CurrentControlType in boxes:
                    return node
                if self._uia.CompareElements(node, focused):
                    break
                node = walker.GetParentElement(node)
        except Exception:  # nothing further out, or a program that doesn't say
            pass
        try:
            return focused if focused.CurrentControlType in boxes else None
        except Exception:
            return None

    def _value(self, field):
        """What a text box says is in it, or None if it doesn't say."""
        try:
            raw = field.GetCurrentPattern(self._api.UIA_ValuePatternId)
            if not raw:
                return None
            return raw.QueryInterface(self._api.IUIAutomationValuePattern).CurrentValue or ""
        except Exception:
            return None

    def _own(self, pattern, focused, field):
        """Where a text box's own text starts and ends, or None if that can't be had."""
        if field is None:
            return None
        try:
            return pattern.RangeFromChild(field)
        except Exception:
            pass
        try:
            return pattern.DocumentRange if self._uia.CompareElements(field, focused) else None
        except Exception:
            return None

    # ---- requests -------------------------------------------------------------------------
    def _handle(self, m: dict) -> dict:
        op = m.get("op")
        if op == "command" and m.get("name") == "cancel_choices":
            return {"ok": True}
        box = self._box()
        if op == "status":
            if box is not None:
                self.name = program_name(box.program)
            return {"ok": True, "ready": box is not None, "seen": self.seen}
        if box is None:
            return dict(NOT_FOCUSED)
        before = box.before.replace("\r\n", "\n").replace("\r", "\n").rsplit("\n", 1)[-1]
        after = box.after.replace("\r\n", "\n").replace("\r", "\n").split("\n", 1)[0]
        before, after = before.translate(UNSEEN), after.translate(UNSEEN)
        if op == "context":
            reply = {"ok": True, "before": before, "after": after}
            if box.selected:
                reply["selected"] = True
                reply["selected_edges"] = [box.selected[:1], box.selected[-1:]]
            return reply
        if op == "insert":
            return self._insert(box, m.get("text", ""), int(m.get("delete_before", 0)),
                                int(m.get("delete_after", 0)))
        if op == "command":
            return self._command(box, before, after, m.get("name", ""), m.get("arg", ""))
        return {"ok": False, "why": "unknown request"}

    def _type(self, steps: list) -> None:
        _send(steps, self._as_keys)

    def _hand_over(self, text: str) -> bool:
        """Give the text to an edit box whole, in place of anything selected there.
        False if the box in front isn't one that takes it, or didn't."""
        if self._edit is None or self._look is not None:
            return False
        from . import winapi
        if not winapi.replace_selection(self._edit, as_one_piece(text)):
            return False
        winapi.tap_shift(self._edit)      # or Notepad's cursor goes from the screen
        return True

    def _insert(self, box, text: str, delete_before: int, delete_after: int) -> dict:
        if not (text and not delete_before and not delete_after and self._hand_over(text)):
            steps = steps_for_insert(text, delete_before, delete_after, bool(box.selected))
            if steps:
                self._press(steps)
        if text:
            self.history.append(text)
            del self.history[:-HISTORY]
        return {"ok": True, "text": text}

    def _last(self, before: str):
        """The last phrase typed, if it is still what is just before the cursor."""
        if not self.history:
            return None
        tail = self.history[-1].replace(PARAGRAPH, "\n").replace(LINE, "\n").rsplit("\n", 1)[-1]
        return self.history[-1] if before.endswith(tail) else None

    def _command(self, box, before: str, after: str, name: str, arg: str) -> dict:
        count = max(1, min(99, int(arg))) if str(arg).isdigit() else 1
        if name in ("new_paragraph", "new_line"):
            ins = fit(name.replace("_", " "), before, after, self.lexicon, spoken_off=())
            return self._insert(box, ins.text, ins.delete_before, ins.delete_after)
        if name in COMMAND_KEYS:
            self._press([("press", COMMAND_KEYS[name], count if name in COUNTED else 1)])
            if name == "press_enter":
                self.history.clear()      # in a chat box, that sent it
            return {"ok": True}
        if name == "backspace":
            self._press([("press", "backspace", 1 if box.selected else count)])
            return {"ok": True}
        if name in ("scratch", "delete"):
            if name == "delete" and box.selected:
                self._press([("press", "backspace", 1)])
                return {"ok": True}
            last = self._last(before)
            if last is None or box.selected:
                self.history.clear()
                return {"ok": False, "why": "nothing to scratch"}
            self.history.pop()
            self._press([("press", "backspace", typed_length(last))])
            return {"ok": True}
        if name == "select_last":
            last = self._last(before)
            if last is None:
                return {"ok": False, "why": "nothing to select"}
            self._press([("press", "shift+left", typed_length(last))])
            return {"ok": True}
        if name == "unselect":
            if box.selected:
                self._press([("press", "right", 1)])
            return {"ok": True}
        if name in ("select_line", "delete_line"):
            self._press([("press", "home", 1), ("press", "shift+end", 1)]
                        + ([("press", "backspace", 1)] if name == "delete_line" else []))
            return {"ok": True}
        if name == "select":
            return self._select(box, arg)
        if name in ("cap", "all_caps", "no_caps"):
            old = box.selected or self._last(before)
            if not old or PARAGRAPH in old or LINE in old:
                return {"ok": False, "why": "nothing to format"}
            new = {"cap": old.title(), "all_caps": old.upper(), "no_caps": old.lower()}[name]
            if not box.selected:
                self._press([("press", "backspace", typed_length(old))])
                self.history[-1] = new
            self._press(steps_for_text(new))
            return {"ok": True}
        if name in ("bold", "italic", "underline"):
            return {"ok": False, "why": "plain text has no formatting"}
        if name == "choose":
            return {"ok": False, "why": "nothing to choose from"}
        return {"ok": False, "why": "unknown command"}

    def _select(self, box, phrase: str) -> dict:
        """Select the nearest match for `phrase`, where the program lets its text be
        selected from outside."""
        if self._look is not None:
            return {"ok": False, "why": "can't select here"}
        if self._edit_text is not None:   # an edit box, asked by message
            from . import winapi
            text, cursor, window, kind = self._edit_text
            found = find_nearest(text, cursor, phrase)
            if found is None:
                return {"ok": False, "why": "can't find that", "sounds_tried": True}
            if not winapi.select_in_edit(window, place_in(text, found[0], kind),
                                         place_in(text, found[1], kind)):
                return {"ok": False, "why": "can't select here"}
            winapi.tap_shift(window)
            return {"ok": True}
        whole = self._whole               # the box's own text, not the page around it
        if whole is None:                 # an empty box: only its hint is there
            return {"ok": False, "why": "can't find that", "sounds_tried": True}
        api = self._api
        start, end = api.TextPatternRangeEndpoint_Start, api.TextPatternRangeEndpoint_End
        text = whole.GetText(WHOLE) or ""
        lead = whole.Clone()
        lead.MoveEndpointByRange(end, self._here, start)
        found = find_nearest(text, len(lead.GetText(WHOLE) or ""), phrase)
        if found is None:
            return {"ok": False, "why": "can't find that", "sounds_tried": True}
        match = whole.Clone()
        match.MoveEndpointByRange(end, whole, start)            # an empty range at the top
        match.MoveEndpointByUnit(end, api.TextUnit_Character, found[1])
        match.MoveEndpointByUnit(start, api.TextUnit_Character, found[0])
        if (match.GetText(-1) or "") != text[found[0]:found[1]]:
            return {"ok": False, "why": "can't select here"}    # it counts differently
        match.Select()
        return {"ok": True}


def _rects(text_range) -> list:
    """Where a piece of text is on the screen: [(left, top, width, height), ...]."""
    numbers = list(text_range.GetBoundingRectangles() or ())
    return [tuple(numbers[at:at + 4]) for at in range(0, len(numbers) - 3, 4)]


# ---- pressing keys ----------------------------------------------------------------------
def _send(steps: list, as_keys: bool = False) -> None:
    """Type the steps into whatever has the keyboard.

    Text goes as characters sent as themselves, in a burst, or with `as_keys` as presses
    of the keys that make them, with Shift where a key needs it, one character at a time
    at about a hundred a second. A character the keyboard hasn't got is then sent as
    itself, alone, with a moment for the program to take it in.
    """
    import ctypes
    from ctypes import wintypes

    class KeyboardInput(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MouseInput(ctypes.Structure):  # only here to give the union its full size
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    class Either(ctypes.Union):
        _fields_ = [("ki", KeyboardInput), ("mi", MouseInput)]

    class Input(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", Either)]

    user32 = ctypes.windll.user32
    up, unicode_flag, extended, shift_key = 0x0002, 0x0004, 0x0001, 0x10

    def event(key=0, scan=0, flags=0):
        item = Input(type=1)  # a keyboard event
        item.ki = KeyboardInput(key, scan, flags, 0, 0)
        return item

    def press(names: list) -> list:
        """Hold the keys down in order, then let them go in reverse."""
        flags = [extended if n in EXTENDED else 0 for n in names]
        down = [event(KEYS[n], 0, f) for n, f in zip(names, flags)]
        return down + [event(KEYS[n], 0, f | up) for n, f in reversed(list(zip(names, flags)))]

    def send(events: list) -> None:
        for at in range(0, len(events), 60):   # in handfuls, so nothing is dropped
            batch = events[at:at + 60]
            array = (Input * len(batch))(*batch)
            user32.SendInput(len(batch), array, ctypes.sizeof(Input))
            time.sleep(0.005)

    def as_itself(text: str) -> list:
        data = text.encode("utf-16-le")
        codes = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
        return [e for code in codes for e in (event(0, code, unicode_flag),
                                              event(0, code, unicode_flag | up))]

    def by_key(text: str) -> None:
        user32.GetKeyboardLayout.restype = ctypes.c_void_p
        user32.VkKeyScanExW.argtypes = [wintypes.WCHAR, ctypes.c_void_p]
        user32.VkKeyScanExW.restype = ctypes.c_short
        user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        user32.MapVirtualKeyExW.restype = wintypes.UINT
        # The keyboard of the program in front, which may not be this one's.
        layout = user32.GetKeyboardLayout(
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None))

        def lookup(c: str):
            if len(c.encode("utf-16-le")) != 2:
                return None
            found = user32.VkKeyScanExW(c, layout)
            if found == -1:
                return None
            key, modifiers = found & 0xFF, (found >> 8) & 0xFF
            if user32.MapVirtualKeyExW(key, 2, layout) & 0x80000000:
                return None               # a key that waits for the next one, to put an accent on it
            return key, modifiers

        caps = bool(user32.GetKeyState(0x14) & 1)
        for stroke in keystrokes(text, lookup, caps):
            if stroke[0] == "char":
                send(as_itself(stroke[1]))
                time.sleep(0.02)
                continue
            _, key, shifted = stroke
            scan = user32.MapVirtualKeyExW(key, 0, layout)
            strike = [event(key, scan, 0), event(key, scan, up)]
            if shifted:
                strike = [event(shift_key, 0, 0)] + strike + [event(shift_key, 0, up)]
            send(strike)   # one character at a time, with a moment between: see send()
            time.sleep(0.005)

    for step in steps:
        if step[0] == "type":
            if as_keys:
                by_key(step[1])
            else:
                send(as_itself(step[1]))
        elif as_keys:
            for _ in range(step[2]):       # at a pace, as the characters are
                send(press(step[1].split("+")))
                time.sleep(0.005)
        else:
            send(press(step[1].split("+")) * step[2])
