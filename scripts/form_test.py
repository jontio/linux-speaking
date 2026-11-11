"""Tests dictation into an ordinary program's text boxes, through accessibility.

Run by scripts/test-form.sh, which opens a small form window for it.
"""
import sys
import time

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

from dictation.editor_target import EditorTarget  # noqa: E402
from dictation.formatting import LINE  # noqa: E402

everything = [True]
target = EditorTarget(lambda: everything[0])
failures = 0


def check(label, got, want):
    global failures
    same = got == want
    failures += not same
    print(("PASS " if same else "FAIL ") + label + ("" if same else f"\n     got  {got!r}\n     want {want!r}"), flush=True)


def r(**message):
    return target.request(message)


def find(o, name, depth=0):
    if o.get_name() == name and o.get_text_iface() is not None:
        return o
    if depth < 12:
        for i in range(min(o.get_child_count(), 100)):
            child = o.get_child_at_index(i)
            found = find(child, name, depth + 1) if child is not None else None
            if found is not None:
                return found
    return None


def form():
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is not None and app.get_name() == "ls-test-form":
            return app
    return None


for _ in range(40):
    if form() is not None and find(form(), "line") is not None:
        break
    time.sleep(0.5)
else:
    print("FAIL the test form never appeared")
    sys.exit(1)


def focus(name):
    Atspi.Component.grab_focus(find(form(), name))
    time.sleep(0.4)


focus("line")
for _ in range(20):
    if r(op="status").get("ready"):
        break
    time.sleep(0.3)
check("a one-line box in an ordinary program is found", r(op="status").get("ready"), True)
check("the program is named", target.name, "Ls-test-form")
r(op="insert", text="hello world")
check("typed into the one-line box", r(op="text")["text"], "hello world")
check("context", r(op="context"), {"ok": True, "before": "hello world", "after": ""})
r(op="insert", text=" and" + LINE + "more")
check("a line break becomes a space there", r(op="text")["text"], "hello world and more")
check("scratch that", (r(op="command", name="scratch").get("ok"), r(op="text")["text"]), (True, "hello world"))
r(op="command", name="select", arg="hello")
check("select", r(op="text")["selected"], "hello")
r(op="insert", text="goodbye")
check("select-and-say", r(op="text")["text"], "goodbye world")
r(op="insert", text=" café → done")
check("accented letters and symbols keep their place", r(op="text")["text"], "goodbye café → done world")

focus("editor")
check("a several-line box is found", r(op="status").get("ready"), True)
r(op="insert", text="first line" + LINE + "second line")
check("line breaks work there", r(op="text")["text"], "first line\nsecond line")
r(op="command", name="line_up", arg="1")
r(op="insert", text="X")
check("line commands work there", r(op="text")["text"], "first lineX\nsecond line")

focus("secret")
check("a password box is refused", r(op="status").get("ready"), False)
check("and nothing can be typed into it", r(op="insert", text="hunter2").get("why"), "editor not focused")
check("it stays empty", Atspi.Text.get_character_count(find(form(), "secret")), 0)

focus("line")
everything[0] = False
target._object = None
check("with the setting off, other programs are left alone", r(op="status").get("ready"), False)
print("failures:", failures, flush=True)
sys.exit(1 if failures else 0)
