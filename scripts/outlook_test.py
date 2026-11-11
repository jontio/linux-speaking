"""Live test of dictation into a classic Outlook message. Windows only; Outlook must be open.

    venv\\Scripts\\python.exe app\\scripts\\outlook_test.py

It opens a new, empty message of its own, works on that alone, and closes it without
saving or sending. Nothing is addressed, so it couldn't be sent by accident.
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pythoncom  # noqa: E402
import win32com.client.dynamic  # noqa: E402

from dictation import winapi  # noqa: E402

DISCARD = 1
SUBJECT = "Linux Speaking test message"
failures = []


def check(what, got, want):
    ok = got == want
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))
    if not ok:
        failures.append(what)


def window_titled(start: str):
    """The top-level window whose title starts with `start`, or None."""
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(window, _):
        title = ctypes.create_unicode_buffer(512)
        winapi.user32.GetWindowTextW(window, title, 512)
        if title.value.startswith(start):
            found.append(window)
        return True

    winapi.user32.EnumWindows(callback_type(visit), 0)
    return found[0] if found else None


def main():
    pythoncom.CoInitialize()
    try:
        outlook = winapi.running("Outlook.Application")
    except pythoncom.com_error:
        print("Outlook isn't running. Open it and try again.")
        return 1
    item = outlook.CreateItem(0)   # a new mail message
    item.Subject = SUBJECT
    item.Display()
    try:
        run(outlook, item)
    finally:
        item.Close(DISCARD)
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


def run(outlook, item):
    inspector = item.GetInspector
    area = None
    for _ in range(50):
        top = window_titled(SUBJECT)
        area = winapi.child_of_class(top, "_WwG") if top else None
        if area:
            break
        time.sleep(0.1)
    assert area, "the message's editing area wasn't found"
    os.environ["LS_OFFICE_TEST_WINDOW"] = str(area)
    from dictation.formatting import PARAGRAPH
    from dictation.word_target import WordTarget

    target = WordTarget()
    shown = []
    target.show_numbers = shown.append
    doc = inspector.WordEditor
    # Asked for through the editing area itself, as the engine does: Outlook's editor
    # won't give a document's window any other way.
    selection = winapi.native_object(area).Selection

    def ask(**message):
        return target.request(message)

    def text():
        return (doc.Content.Text or "").rstrip("\r")

    def reset(content="", start=None):
        doc.Content.Text = content
        at = len(content) if start is None else start
        selection.SetRange(at, at)
        target.history.clear()

    check("the editing area answers", ask(op="status").get("ready"), True)
    check("Outlook says this message is being written", target._composing_now(), True)
    reset()
    check("context in an empty message", ask(op="context"), {"ok": True, "before": "", "after": ""})
    ask(op="insert", text="Hello there,")
    check("insert", text(), "Hello there,")
    ask(op="insert", text=PARAGRAPH + "Thanks for this.")
    check("a paragraph break", text(), "Hello there,\rThanks for this.")
    check("context", ask(op="context").get("before"), "Thanks for this.")
    ask(op="command", name="scratch")
    check("scratch that", text(), "Hello there,")
    ask(op="insert", text=" how are you?")
    ask(op="command", name="undo")
    check("undo takes back one phrase", text(), "Hello there,")
    reset("one two three two one")
    selection.SetRange(0, 0)
    reply = ask(op="command", name="select", arg="two")
    check("several matches are numbered", reply.get("choices"), 2)
    check("with places on screen", [len(p) for p in shown[-1]] if shown else None, [5, 5])
    ask(op="command", name="choose", arg="2")
    check("choose 2", (selection.Start, selection.Text), (14, "two"))
    ask(op="insert", text="2")
    check("dictating over the selection", text(), "one two three 2 one")
    ask(op="command", name="bold")
    check("bold that", doc.Range(14, 15).Font.Bold, -1)
    ask(op="command", name="doc_top")
    ask(op="command", name="word_right", arg="2")
    check("move right 2 words", selection.Start, 8)
    ask(op="command", name="select_line")
    ask(op="command", name="delete")
    check("select line, delete that", text(), "")


if __name__ == "__main__":
    sys.exit(main())
