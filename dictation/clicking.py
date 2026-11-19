""""Click OK": pressing a button, a link, a tick box, a tab or a menu of the program in
front, by the name it shows.

The desktop's accessibility service is asked what the window in front has that can be
pressed, and the one whose name was said is pressed through that same service: as a
screen reader presses it, with no mouse moved. On Windows that is UI Automation; on
Linux, AT-SPI.

What is said has to be the control's name, or the start of it: "click save" presses
"Save", and "Save As..." if there is no "Save". The mark that underlines a letter ("&"),
and dots at the end, are not part of a name. Where nothing has that name the words are
dictation, as "select" with words that aren't there is: "Click here to see more" can
still be dictated.

It is an option, off until it is ticked: a "click" at the start of a phrase is otherwise
only a word.
"""
from __future__ import annotations

import re

from . import config

MOST = 600        # controls looked at in one window, at most
DEEPEST = 25      # how far down a window's tree is gone (Linux)
# The kinds of control that are pressed: by the names AT-SPI gives them (Linux). A button
# is a "push button" to older versions of the service and a "button" to newer ones.
ROLES = frozenset((
    "button", "push button", "toggle button", "check box", "radio button", "switch",
    "menu item", "menu", "check menu item", "radio menu item", "link", "page tab",
    "list item", "tree item", "combo box", "table cell", "tool bar item",
    "button menu", "push button menu", "menu button"))


class CantClick(Exception):
    """It couldn't be pressed. Its text is for the person to read."""


def plain(name: str) -> str:
    """A control's name as it is said: small letters, no "&" under a letter, no dots or
    colon at its end, no key written after it ("Open...\\tCtrl+O")."""
    name = (name or "").split("\t")[0].replace("&", "")
    name = re.sub(r"[\u2026.:]+\s*$", "", name.strip())
    name = re.sub(r"['\u2019]", "", name.lower())      # "don't" is said, and may be written "dont"
    return " ".join(re.sub(r"[^\w]+", " ", name).split())


def best(said: str, names: list):
    """Which of `names` was meant by `said`: its place in the list, or None. The whole
    name first; then a name that starts with what was said; then one with those words
    in it, in that order. Of several as good, the shortest name: "Save" before "Save
    All", and the first of two alike."""
    wanted = plain(said)
    if not wanted:
        return None
    ranked = []
    for at, name in enumerate(names):
        have = plain(name)
        if not have:
            continue
        if have == wanted:
            rank = 0
        elif have.startswith(wanted + " "):
            rank = 1
        elif f" {wanted} " in f" {have} ":
            rank = 2
        else:
            continue
        ranked.append((rank, len(have), at))
    return min(ranked)[2] if ranked else None


# ---- Windows -------------------------------------------------------------------------------
def _click_windows(said: str) -> dict:
    import ctypes
    import comtypes
    import comtypes.client
    try:
        comtypes.CoInitialize()
    except OSError:
        pass                              # this thread is set up already
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as api
    uia = comtypes.client.CreateObject(api.CUIAutomation, interface=api.IUIAutomation)
    window = ctypes.WinDLL("user32").GetForegroundWindow()
    if not window:
        return {"ok": False, "why": "no window in front"}
    root = uia.ElementFromHandle(window)
    kinds = (api.UIA_ButtonControlTypeId, api.UIA_HyperlinkControlTypeId,
             api.UIA_CheckBoxControlTypeId, api.UIA_RadioButtonControlTypeId,
             api.UIA_MenuItemControlTypeId, api.UIA_TabItemControlTypeId,
             api.UIA_ListItemControlTypeId, api.UIA_TreeItemControlTypeId,
             api.UIA_SplitButtonControlTypeId, api.UIA_ComboBoxControlTypeId)
    wanted = uia.CreatePropertyCondition(api.UIA_ControlTypePropertyId, kinds[0])
    for kind in kinds[1:]:
        wanted = uia.CreateOrCondition(
            wanted, uia.CreatePropertyCondition(api.UIA_ControlTypePropertyId, kind))
    usable = uia.CreateAndCondition(
        uia.CreatePropertyCondition(api.UIA_IsEnabledPropertyId, True),
        uia.CreatePropertyCondition(api.UIA_IsOffscreenPropertyId, False))
    found = root.FindAll(api.TreeScope_Descendants, uia.CreateAndCondition(wanted, usable))
    controls = [found.GetElement(at) for at in range(min(found.Length, MOST))]
    names = []
    for control in controls:
        try:
            names.append(control.CurrentName or "")
        except Exception:
            names.append("")
    at = best(said, names)
    if at is None:
        return {"ok": False, "why": "can't find that", "looked_at": len(controls)}
    control = controls[at]
    kind = _press_windows(api, control)
    return {"ok": True, "kind": kind}


def _press_windows(api, control) -> str:
    """Press it the way it is made to be pressed: the first of these that it has."""
    def pattern(number, interface):
        raw = control.GetCurrentPattern(number)
        return raw.QueryInterface(interface) if raw else None

    for number, interface, act, kind in (
            (api.UIA_InvokePatternId, api.IUIAutomationInvokePattern, "Invoke", "pressed"),
            (api.UIA_TogglePatternId, api.IUIAutomationTogglePattern, "Toggle", "ticked"),
            (api.UIA_SelectionItemPatternId, api.IUIAutomationSelectionItemPattern, "Select", "chosen"),
            (api.UIA_ExpandCollapsePatternId, api.IUIAutomationExpandCollapsePattern, "Expand", "opened"),
            (api.UIA_LegacyIAccessiblePatternId, api.IUIAutomationLegacyIAccessiblePattern,
             "DoDefaultAction", "pressed")):
        try:
            found = pattern(number, interface)
            if found is not None:
                getattr(found, act)()
                return kind
        except Exception:
            continue
    raise CantClick("That is there, but it gives no way of being pressed by another program.")


# ---- Linux ---------------------------------------------------------------------------------
def _click_linux(said: str) -> dict:
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    Atspi.init()
    active = Atspi.StateType.ACTIVE
    desktop = Atspi.get_desktop(0)
    window = None
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
            for w in range(min(app.get_child_count(), 50)) if app is not None else ():
                one = app.get_child_at_index(w)
                if one is not None and one.get_state_set().contains(active):
                    window = one
                    break
        except Exception:
            continue
        if window is not None:
            break
    if window is None:
        return {"ok": False, "why": "no window in front"}
    controls = []
    _gather(Atspi, window, controls, 0)
    at = best(said, [control.get_name() or "" for control in controls])
    if at is None:
        return {"ok": False, "why": "can't find that", "looked_at": len(controls)}
    control = controls[at]
    if control.get_action_iface() is None or control.get_n_actions() < 1:
        raise CantClick("That is there, but it gives no way of being pressed by another program.")
    Atspi.Action.do_action(control, 0)
    return {"ok": True, "kind": "pressed"}


def _gather(Atspi, node, controls: list, depth: int) -> None:
    """The controls under `node` that can be pressed, are showing and are not greyed."""
    if len(controls) >= MOST or depth > DEEPEST:
        return
    try:
        count = min(node.get_child_count(), 300)
    except Exception:
        return
    for i in range(count):
        try:
            child = node.get_child_at_index(i)
            if child is None:
                continue
            states = child.get_state_set()
            if not states.contains(Atspi.StateType.SHOWING):
                continue
            if child.get_role_name() in ROLES and states.contains(Atspi.StateType.SENSITIVE) \
                    and (child.get_name() or "").strip():
                controls.append(child)
        except Exception:
            continue
        _gather(Atspi, child, controls, depth + 1)


def click(said: str) -> dict:
    """Press the control of the window in front whose name was said. {"ok": True, "kind":
    "pressed"} or {"ok": False, "why": "can't find that"}. Raises CantClick, with words
    for the person, where it is there and can't be pressed, or nothing can be asked."""
    try:
        return _click_windows(said) if config.WINDOWS else _click_linux(said)
    except CantClick:
        raise
    except ImportError:
        raise CantClick("The part that asks a window what is in it isn't installed here."
                        if config.WINDOWS else
                        "The desktop's accessibility service can't be asked: its Python part "
                        "(python3-gi with Atspi) isn't installed.") from None
    except Exception as e:
        raise CantClick("The window in front couldn't be asked what is in it "
                        f"({type(e).__name__}).") from None


def in_front() -> str:
    """The program in front, by name, for the log: "" if it can't be told."""
    if not config.WINDOWS:
        return ""
    try:
        from . import keys_target
        return keys_target.program_in_front()
    except Exception:
        return ""

