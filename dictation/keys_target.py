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

from .formatting import LINE, PARAGRAPH, fit
from .selecting import find_nearest
from .words import Lexicon

HISTORY = 20
READ = 1000        # how far around the cursor to read
WHOLE = 20000      # the most text looked through for "select ..."
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


def program_name(exe: str) -> str:
    stem = exe[:-4] if exe.lower().endswith(".exe") else exe
    return NAMES.get(stem.lower(), stem[:1].upper() + stem[1:]) or "another program"


class Box:
    """A text box that has the keyboard, as read through UI Automation."""

    def __init__(self, before: str, after: str, selected: str, program: str):
        self.before, self.after, self.selected, self.program = before, after, selected, program


class KeysTarget:
    """`everything` is called each time: the "other programs" tick box in Settings."""

    def __init__(self, everything=lambda: False, look=None, press=None):
        self.everything = everything
        self.name = "another program"
        self.lexicon = Lexicon.load_default()
        self.history = []                 # what was typed lately, newest last
        self.seen = ""                    # what last had the keyboard, for the log
        self._look = look                 # for tests: returns a Box or None
        self._press = press or _send      # for tests: receives the list of steps
        self._uia = None
        self._jobs: queue.Queue = queue.Queue()
        if look is None:
            threading.Thread(target=self._run, daemon=True).start()

    # ---- called from the engine's threads -------------------------------------------
    def request(self, message: dict, timeout: float = 6.0) -> dict:
        """Answer one request, in the same form as the Writer extension. Never raises."""
        if not self.everything():
            return {"ok": True, "ready": False} if message.get("op") == "status" else dict(NOT_FOCUSED)
        if self._look is not None:        # under test: no thread, no Windows
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
        program = winapi.focused()[0]
        element = self._uia.GetFocusedElement()
        self.seen = f"{program} control type {element.CurrentControlType}"
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
        before = here.Clone()
        before.MoveEndpointByRange(end, here, start)
        before.MoveEndpointByUnit(start, api.TextUnit_Character, -READ)
        after = here.Clone()
        after.MoveEndpointByRange(start, here, end)
        after.MoveEndpointByUnit(end, api.TextUnit_Character, READ)
        self._pattern, self._here = pattern, here
        return Box(before.GetText(-1) or "", after.GetText(-1) or "", here.GetText(-1) or "",
                   program)

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
        if op == "context":
            reply = {"ok": True, "before": before, "after": after}
            if box.selected:
                reply["selected"] = True
            return reply
        if op == "insert":
            return self._insert(box, m.get("text", ""), int(m.get("delete_before", 0)),
                                int(m.get("delete_after", 0)))
        if op == "command":
            return self._command(box, before, after, m.get("name", ""), m.get("arg", ""))
        return {"ok": False, "why": "unknown request"}

    def _insert(self, box, text: str, delete_before: int, delete_after: int) -> dict:
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
        api = self._api
        start, end = api.TextPatternRangeEndpoint_Start, api.TextPatternRangeEndpoint_End
        whole = self._pattern.DocumentRange
        text = whole.GetText(WHOLE) or ""
        lead = whole.Clone()
        lead.MoveEndpointByRange(end, self._here, start)
        found = find_nearest(text, len(lead.GetText(WHOLE) or ""), phrase)
        if found is None:
            return {"ok": False, "why": "can't find that"}
        match = whole.Clone()
        match.MoveEndpointByRange(end, whole, start)            # an empty range at the top
        match.MoveEndpointByUnit(end, api.TextUnit_Character, found[1])
        match.MoveEndpointByUnit(start, api.TextUnit_Character, found[0])
        if (match.GetText(-1) or "") != text[found[0]:found[1]]:
            return {"ok": False, "why": "can't select here"}    # it counts differently
        match.Select()
        return {"ok": True}


# ---- pressing keys ----------------------------------------------------------------------
def _send(steps: list) -> None:
    """Type the steps into whatever has the keyboard."""
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

    up, unicode_flag, extended = 0x0002, 0x0004, 0x0001

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
            ctypes.windll.user32.SendInput(len(batch), array, ctypes.sizeof(Input))
            time.sleep(0.005)

    for step in steps:
        if step[0] == "type":
            data = step[1].encode("utf-16-le")
            codes = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
            send([e for code in codes for e in (event(0, code, unicode_flag),
                                                event(0, code, unicode_flag | up))])
        else:
            send(press(step[1].split("+")) * step[2])
