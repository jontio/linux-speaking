"""Tests dictation into KWrite through the accessibility interface.

Run by scripts/test-editor.sh, which opens a scratch KWrite window for it.
"""
import sys
import time

from dictation.editor_target import EditorTarget
from dictation.formatting import LINE, PARAGRAPH

target = EditorTarget()
failures = 0


def check(label, got, want):
    global failures
    same = got == want
    failures += not same
    print(("PASS " if same else "FAIL ") + label + ("" if same else f"\n     got  {got!r}\n     want {want!r}"), flush=True)


def r(**message):
    return target.request(message)


def text():
    return r(op="text")["text"]


def cmd(name, arg=""):
    return r(op="command", name=name, arg=arg)


def say(words, **extra):
    return r(op="insert", text=words, **extra)


for _ in range(40):
    if r(op="status").get("ready"):
        break
    time.sleep(0.5)
else:
    print("FAIL no focused KWrite text area found (is its window in front?)")
    sys.exit(1)

check("named", target.name, "KWrite")
check("starts empty", text(), "")
say("The cat sat")
check("insert", text(), "The cat sat")
check("context", r(op="context"), {"ok": True, "before": "The cat sat", "after": ""})
say(". It was happy")
cmd("scratch")
check("scratch that", text(), "The cat sat")
say(" and  ")
say(",", delete_before=2)
check("delete_before", text(), "The cat sat and,")
cmd("backspace", "5")
check("backspace 5", text(), "The cat sat")
say(PARAGRAPH + "Second paragraph here")
check("new paragraph leaves a blank line", text(), "The cat sat\n\nSecond paragraph here")
say(LINE + "next line")
check("new line", text(), "The cat sat\n\nSecond paragraph here\nnext line")
check("context is the current line", r(op="context")["before"], "next line")
check("select", (cmd("select", "cat").get("ok"), r(op="text")["selected"]), (True, "cat"))
check("context around a selection", r(op="context"), {"ok": True, "before": "The ", "after": " sat"})
say("dog")
check("select-and-say", text().split("\n")[0], "The dog sat")
cmd("line_end")
say(" down")
check("go to end of line", text().split("\n")[0], "The dog sat down")
cmd("line_start")
say("Well ")
check("go to start of line", text().split("\n")[0], "Well The dog sat down")
cmd("para_end")
cmd("para_end")
say(" end")
check("end of paragraph twice reaches the next", text().endswith("next line end"), True)
cmd("para_start")
cmd("para_start")
say("Top ")
check("start of paragraph twice reaches the one before", text().split("\n")[0], "Top Well The dog sat down")
cmd("doc_end")
say(" here and then")
cmd("select", "and")
say(".", delete_before=1, capitalise_next=True)
check("full stop capitalises the next word", text().endswith("end here. Then"), True)
cmd("select", "then")
cmd("all_caps")
check("all caps that", (text().endswith("here. THEN"), r(op="text")["selected"]), (True, "THEN"))
cmd("no_caps")
cmd("cap")
check("cap that", text().endswith("here. Then"), True)
cmd("unselect")
check("unselect", r(op="text")["selected"], "")
cmd("doc_top")
say("X")
check("go to top", text().startswith("XTop Well"), True)
before_undo = text()
cmd("doc_end")
say(" last words")
check("typed", text().endswith(" last words"), True)
undo = cmd("undo")
time.sleep(0.5)
check("undo that takes back the phrase", (undo.get("ok"), text()), (True, before_undo))
check("bold is refused", cmd("bold").get("why"), "plain text has no formatting")
check("can't find", cmd("select", "zebra").get("why"), "can't find that")
check("move falls through", r(op="move", steps=[]).get("why"), "unknown request")
print("failures:", failures, flush=True)
sys.exit(1 if failures else 0)
