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
check("context around a selection", r(op="context"),
      {"ok": True, "before": "The ", "after": " sat", "selected": True,
       "selected_edges": ["c", "t"]})
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
cmd("doc_end")
say(" one two three")
cmd("word_left", "2")
say("X")
check("move left 2 words", text().endswith(" one Xtwo three"), True)
cmd("word_right", "1")
say("Y")
check("move right a word", text().endswith(" one Xtwo Ythree"), True)
cmd("doc_end")
say(PARAGRAPH + "line a" + LINE + "line b" + LINE + "line c")
cmd("line_up", "1")
say("X")
check("up one line", text().split("\n")[-2:], ["line bX", "line c"])
cmd("line_down", "1")
cmd("select_line")
check("select line", r(op="text")["selected"], "line c")
cmd("unselect")
cmd("line_up", "2")
cmd("delete_line", "1")
check("delete line", text().split("\n")[-2:], ["line bX", "line c"])
check("go to line 1", (cmd("go_to_line", "1").get("ok"), r(op="text")["caret"]), (True, 0))
cmd("doc_end")
cmd("select_all")
check("select all", r(op="text")["selected"], text())
cmd("unselect")
check("bold is refused", cmd("bold").get("why"), "plain text has no formatting")
check("can't find", cmd("select", "zebra").get("why"), "can't find that")
check("move falls through", r(op="move", steps=[]).get("why"), "unknown request")

# "Correct ...": the words are chosen as for "select", and once something has been said in
# their place the cursor is back where it was.
cmd("doc_end")
say(PARAGRAPH + "the quick brown cat jumps")
check("correct chooses the words", (cmd("correct", "cat").get("ok"), r(op="text")["selected"]), (True, "cat"))
check("and says the cursor went back", say("dog").get("back"), True)
say(" high")
check("correct: the cursor is back at the end", text().split("\n")[-1], "the quick brown dog jumps high")
cmd("correct", "high")
say("higher")
say(" still")
check("correcting the word the cursor is right after", text().split("\n")[-1], "the quick brown dog jumps higher still")
cmd("line_start")
cmd("correct", "dog")
say("wolf")
say("See ")
check("back to a place before the words", text().split("\n")[-1], "See the quick brown wolf jumps higher still")
cmd("line_start")
cmd("correct", "see")
say("Look")
say("X")
check("correcting the word the cursor is right before", text().split("\n")[-1], "XLook the quick brown wolf jumps higher still")
cmd("doc_end")
cmd("correct", "quick")
cmd("unselect")
check("unselect after correct goes back too", (bool(say("!").get("back")), text().split("\n")[-1]),
      (False, "XLook the quick brown wolf jumps higher still!"))
say(PARAGRAPH + "second line")
cmd("correct", "wolf")
say("fox")
say(" end")
check("back from another paragraph", text().split("\n")[-3:],
      ["XLook the quick brown fox jumps higher still!", "", "second line end"])
cmd("correct", "second")
cmd("select", "line")
check("no going back if other words are selected by then", (bool(say("row").get("back")), text().split("\n")[-1]),
      (False, "second row end"))
say("s")
check("the cursor stays with them", text().split("\n")[-1], "second rows end")
cmd("doc_end")
cmd("correct", "second")
say("third")
say(" again")
check("only the next thing said goes back", (bool(say(" twice").get("back")), text().split("\n")[-1]),
      (False, "third rows end again twice"))
cmd("doc_end")
cmd("correct", "third")
cmd("all_caps")
check("another command in between ends it", (bool(say("fourth").get("back")), text().split("\n")[-1]),
      (False, "fourth rows end again twice"))
check("correct, not there", cmd("correct", "zebra").get("why"), "can't find that")
print("failures:", failures, flush=True)
sys.exit(1 if failures else 0)
