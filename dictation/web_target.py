"""Linux: dictating into the text boxes of a web browser, and of programs built from one.

VS Code's panels (a chat box, the terminal), a browser's pages, and programs such as
Slack describe their text boxes through the accessibility interface: the text, where
the cursor is, what is selected. But they offer no way to change the text through it,
as Kate does. So what is around the cursor is read there, and the words are typed, as
key presses the desktop has allowed: see portal_keys.py.

Such a program only describes its boxes if it is asked to when it starts: VS Code with
"force-renderer-accessibility": true in its argv.json, a browser with
--force-renderer-accessibility on its command line.

Everything that decides what to type is shared with the Windows target that types:
keys_target.py.
"""
from __future__ import annotations

import os
import threading
import time

from . import config
from .keys_target import READ, Box, KeysTarget, presses
from .portal_keys import NotAllowed, shared, typable
from .selecting import find_nearest

OBJECT = "￼"        # stands in a box's text for something inside it that isn't text
MOST = 50000             # the longest text read whole
ASK_WAIT = 25.0          # how long a phrase waits for the desktop's question to be answered
ASK_AGAIN = 300.0        # after a refusal, how long before the question is put again


def without_decoration(text: str, first: int, last: int, positions) -> tuple:
    """(text, first, last) with the characters at `positions` taken out, and the two
    places moved to match.

    A web page can draw words in an empty box that nobody typed: a hint such as "Type a
    message". The page makes them out of decoration (a ::before or ::after), which the
    accessibility interface gives as a thing inside the box, not as its text.
    """
    for at in sorted(set(positions), reverse=True):
        if 0 <= at < len(text):
            text = text[:at] + text[at + 1:]
            first -= first > at
            last -= last > at
    first = max(0, min(first, len(text)))
    return text, first, max(first, min(last, len(text)))


class WebBoxTarget(KeysTarget):
    """Any program's focused text box that can be read but not written through the
    accessibility interface. `everything` is the "other programs" tick box in Settings."""

    OWN_THREAD = False   # the accessibility library can be called from any thread

    def __init__(self, everything=lambda: False, keys=None):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        super().__init__(everything)
        self.A, self.T = Atspi, Atspi.Text
        self.keys = keys or shared()
        self._object = None
        self._program = ""
        self._asking = None      # the thread putting the desktop's question, while it is open
        self._refused = 0.0      # when the question was last refused
        self.problem = ""        # why keys can't be pressed, for the person to read: "" if they can
        self.log = lambda message: print(message, flush=True)

    # ---- finding the text box ---------------------------------------------------------
    def _is_box(self, o) -> bool:
        states, S = o.get_state_set(), self.A.StateType
        if not (states.contains(S.FOCUSED) and states.contains(S.EDITABLE)):
            return False
        if o.get_role() == self.A.Role.PASSWORD_TEXT:
            return False                     # never dictate into a password box
        # One that can be written through the interface is the other target's: Kate, Qt, GTK.
        return o.get_text_iface() is not None and o.get_editable_text_iface() is None

    def _search(self, window):
        stack, seen = [window], 0
        while stack and seen < 30000:
            o = stack.pop()
            seen += 1
            try:
                if self._is_box(o):
                    return o
                for i in range(min(o.get_child_count(), 400) - 1, -1, -1):
                    child = o.get_child_at_index(i)
                    if child is not None:
                        stack.append(child)
            except Exception:
                continue                     # a part of the window that went away meanwhile
        return None

    def _focused(self):
        try:
            if self._object is not None and self._is_box(self._object):
                return self._object
        except Exception:
            pass
        self._object = None
        S = self.A.StateType
        desktop = self.A.get_desktop(0)
        for i in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(i)
                if app is None or app.get_process_id() == os.getpid():
                    continue
                for w in range(min(app.get_child_count(), 50)):
                    window = app.get_child_at_index(w)
                    if window is None or not window.get_state_set().contains(S.ACTIVE):
                        continue
                    found = self._search(window)
                    if found is not None:
                        self._object, self._program = found, app.get_name() or ""
                        self.history = []
                        return found
            except Exception:
                continue
        return None

    # ---- reading it -------------------------------------------------------------------
    def _decoration(self, o, text: str) -> list:
        """Where in `text` the things are that the page drew and nobody typed."""
        if OBJECT not in text:
            return []
        found = []
        try:
            H = self.A.Hypertext
            for k in range(H.get_n_links(o)):
                link = H.get_link(o, k)
                inside = link.get_object(0)
                tag = (inside.get_attributes() or {}).get("tag", "") if inside is not None else ""
                if tag.startswith("::"):
                    found.append(link.get_start_index())
        except Exception:
            pass
        return found

    def _read(self, o) -> tuple:
        """(all the text, where the selection starts, where it ends)."""
        T = self.T
        count = T.get_character_count(o)
        first = last = T.get_caret_offset(o)
        if T.get_n_selections(o) > 0:
            chosen = T.get_selection(o, 0)
            if chosen.start_offset != chosen.end_offset:
                first, last = sorted((chosen.start_offset, chosen.end_offset))
        if count > MOST:                     # too long to read whole: only around the cursor
            start = max(0, first - READ)
            text = T.get_text(o, start, min(count, last + READ))
            return text, first - start, last - start
        text = T.get_text(o, 0, count)
        return without_decoration(text, first, last, self._decoration(o, text))

    def _box(self):
        o = self._focused()
        if o is None:
            self.seen = "no text box that is only read through the accessibility interface"
            return None
        self.seen = f"{self._program} text box"
        if not self._may_press_keys():
            self.seen += ", but the desktop hasn't allowed key presses"
            return None
        text, first, last = self._read(o)
        self._text, self._cursor, self._chosen = text, first, last > first
        return Box(text[max(0, first - READ):first], text[last:last + READ], text[first:last],
                   self._program)

    # ---- the desktop's leave to press keys ------------------------------------------------
    def _may_press_keys(self) -> bool:
        """Whether keys can be pressed. The first time, the desktop asks the person at
        the computer, and this waits a while for the answer."""
        if self.keys.ready():
            return True
        if self._asking is None or not self._asking.is_alive():
            if time.monotonic() - self._refused < ASK_AGAIN and self._refused:
                return False
            self._asking = threading.Thread(target=self._ask, daemon=True)
            self._asking.start()
        self._asking.join(ASK_WAIT)
        return self.keys.ready()

    def _ask(self) -> None:
        self.log("asking the desktop to let dictation press keys: answer its question on the screen")
        try:
            self.keys.allow()
            self.problem = ""
            self.log("the desktop allows key presses")
        except NotAllowed as e:
            self._refused = time.monotonic()
            self.problem = ("The desktop didn't let this program press keys, so nothing can "
                            "be typed into other programs' text boxes. It asks again the "
                            "next time you dictate into one, a few minutes from now.")
            self.log(f"key presses not allowed: {e}")

    # ---- writing ----------------------------------------------------------------------------
    def _paced(self) -> bool:
        return False                         # the desktop takes key presses as fast as they come

    def _type(self, steps: list) -> None:
        for step in steps:
            if step[0] == "type":
                self.keys.type(step[1])
            else:
                self.keys.press(step[1], step[2])

    def _insert(self, box, text: str, delete_before: int, delete_after: int) -> dict:
        # What can't be typed is made plain first, so that what is remembered as typed,
        # for "scratch that", is what really went in.
        return super()._insert(box, typable(text), delete_before, delete_after)

    def _select(self, box, phrase: str, correcting: bool = False) -> dict:
        """Select the nearest match for `phrase`, by moving the cursor there with the
        arrow keys and holding Shift across it. `correcting` is for "correct ...": where
        the cursor was is remembered, to go back to."""
        found = find_nearest(self._text, self._cursor, phrase)
        if found is None:
            return {"ok": False, "why": "can't find that", "sounds_tried": True}
        steps = [("press", "left", 1)] if self._chosen else []   # that puts the cursor at its start
        # Counted as an arrow key moves: one press for a face with its skin tone, say.
        if found[0] > self._cursor:
            steps.append(("press", "right", presses(self._text[self._cursor:found[0]])))
        elif found[0] < self._cursor:
            steps.append(("press", "left", presses(self._text[found[0]:self._cursor])))
        steps.append(("press", "shift+right", presses(self._text[found[0]:found[1]])))
        self._press(steps)
        if correcting:
            self._chose(self._text, self._cursor, found)
        return {"ok": True}
