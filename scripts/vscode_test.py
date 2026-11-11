"""Tests dictation into Visual Studio Code through its extension.

Run by scripts/test-vscode.sh, which opens a separate VS Code window with a scratch
Markdown file for it. Argument: the test window's socket.
"""
import sys
import time

import os

from dictation import client
from dictation.coding import fit_code, where
from dictation.formatting import LINE, PARAGRAPH, fit

SOCKET = sys.argv[1]
failures = 0


def check(label, got, want):
    global failures
    same = got == want
    failures += not same
    print(("PASS " if same else "FAIL ") + label + ("" if same else f"\n     got  {got!r}\n     want {want!r}"), flush=True)


def r(**message):
    try:
        return client.send(SOCKET, message, 8)
    except (OSError, ValueError) as e:
        return {"ok": False, "why": "not answering", "error": str(e)}


def text():
    return r(op="text")["text"]


def last():
    return text().split("\n")[-1]


def cmd(name, arg="", **extra):
    return r(op="command", name=name, arg=arg, **extra)


def say(words, **extra):
    return r(op="insert", text=words, **extra)


for _ in range(120):
    if r(op="status").get("ready"):
        break
    time.sleep(0.5)
else:
    print("FAIL the extension never answered:", r(op="status"))
    sys.exit(1)

check("a Markdown file", r(op="text").get("language"), "markdown")
check("starts empty", text(), "")
say("The cat sat")
check("insert", text(), "The cat sat")
check("context", r(op="context"),
      {"ok": True, "before": "The cat sat", "after": "", "language": "markdown"})
say(". It was happy")
cmd("scratch")
check("scratch that", text(), "The cat sat")
say(" and  ")
say(",", delete_before=2)
check("delete_before", text(), "The cat sat and,")
cmd("backspace", "5")
check("backspace 5", text(), "The cat sat")
before_phrase = text()
say(" on the mat")
cmd("undo")
time.sleep(0.3)
check("undo that takes back one phrase", text(), before_phrase)

say(PARAGRAPH + "## ")
check("new paragraph leaves a blank line", text(), "The cat sat\n\n## ")
check("after a heading marker a sentence is starting", r(op="context")["before"], "")
say("A heading")

say(PARAGRAPH + "- first item")
check("after a list marker too", (cmd("new_line").get("ok"), last(), r(op="context")["before"]), (True, "- ", ""))
say("Second item")
check("new line carries the list on", text().split("\n")[-2:], ["- first item", "- Second item"])
cmd("new_line")
cmd("new_line")
check("new line on an empty item ends the list", last(), "")
say("1. one")
cmd("new_line")
check("numbered lists count up", last(), "2. ")
say("two" + LINE + "three")
check("a line break inside a phrase carries on too", text().split("\n")[-3:], ["1. one", "2. two", "3. three"])
say(PARAGRAPH + "- [x] done")
cmd("new_line")
check("check boxes start unticked", last(), "- [ ] ")
cmd("backspace", "6")

say(PARAGRAPH + "the fox saw a fox chase a third fox")
picked = cmd("select", "fox")
check("several matches are numbered", (picked.get("choices"), r(op="text")["numbers"]), (3, 3))
check("the numbers leave the text alone", last(), "the fox saw a fox chase a third fox")
check("choose 2", (cmd("choose", "2").get("ok"), r(op="text")["selected"], r(op="text")["numbers"]), (True, "fox", 0))
say("dog")
check("the second one is replaced", last(), "the fox saw a dog chase a third fox")
cmd("select", "fox")
say("x")
check("typing cancels the numbers", r(op="text")["numbers"], 0)
cmd("backspace", "1")
check("nearest match", (cmd("select", "fox", nearest=True).get("ok"), r(op="text")["selected"], r(op="text")["numbers"]), (True, "fox", 0))
check("can't find", cmd("select", "zebra").get("why"), "can't find that")
check("choose with nothing showing", cmd("choose", "1").get("why"), "nothing to choose from")

cmd("select", "third")
cmd("all_caps")
check("all caps that", (last(), r(op="text")["selected"]), ("the fox saw a dog chase a THIRD fox", "THIRD"))
cmd("no_caps")
cmd("cap")
check("cap that", last(), "the fox saw a dog chase a Third fox")
cmd("bold")
check("bold that wraps in asterisks", (last(), r(op="text")["selected"]), ("the fox saw a dog chase a **Third** fox", "**Third**"))
cmd("unselect")
check("unselect", r(op="text")["selected"], "")
cmd("doc_end")
say(" and more")
cmd("italic")
check("italicize that, on the last phrase", last(), "the fox saw a dog chase a **Third** fox *and more*")
check("it can still be scratched", (cmd("scratch").get("ok"), last()), (True, "the fox saw a dog chase a **Third** fox"))
check("underline is refused", cmd("underline").get("why"), "markdown has no underline")

cmd("doc_top")
say("X")
check("go to top", text().startswith("XThe cat sat"), True)
cmd("line_end")
say(" down")
check("go to end of line", text().split("\n")[0], "XThe cat sat down")
cmd("line_start")
say("Well ")
check("go to start of line", text().split("\n")[0], "Well XThe cat sat down")
cmd("para_end")
cmd("para_end")
say(" end")
check("end of paragraph twice reaches the next", text().split("\n")[2], "## A heading end")
cmd("para_start")
cmd("para_start")
say("Top ")
check("start of paragraph twice reaches the one before", text().split("\n")[0], "Top Well XThe cat sat down")
cmd("doc_end")
say(" here and then")
cmd("select", "and", nearest=True)
say(".", delete_before=1, capitalise_next=True)
check("full stop capitalises the next word", last().endswith("fox here. Then"), True)
cmd("doc_end")
lines = len(text().split("\n"))
cmd("press_enter")
time.sleep(0.3)
check("press enter is the Enter key", len(text().split("\n")), lines + 1)
cmd("doc_end")
say("one two three")
cmd("word_left", "2")
say("X")
check("move left 2 words", last(), "one Xtwo three")
cmd("word_right", "1")
say("Y")
check("move right a word", last(), "one Xtwo Ythree")
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
cmd("duplicate_line")
check("duplicate line", text().split("\n")[-3:], ["line bX", "line bX", "line c"])
cmd("delete_line", "2")
check("delete 2 lines takes the copy and the line after it", last(), "line bX")
cmd("doc_end")
say(PARAGRAPH)
cmd("tab")
time.sleep(0.2)
check("tab indents", last() in ("    ", "\t"), True)
cmd("go_to_line", "1")
say("Z")
check("go to line 1", text().startswith("ZTop Well"), True)
cmd("doc_end")
cmd("select_all")
time.sleep(0.2)
check("select all", r(op="text")["selected"], text())
cmd("unselect")
check("move falls through", r(op="move", steps=[]).get("why"), "unknown request")
check("unknown command", cmd("fly").get("why"), "unknown command")
# ---- C++: the engine's code rules, typed into a real .cpp file -------------------------
def code(phrase):
    """What the engine does with a phrase in a C or C++ file."""
    context = r(op="context")
    reply = r(op="symbols")
    names = reply.get("names", [])
    scope = {item["name"]: item["kind"] for item in reply.get("scope", [])}
    place, comment = where(context["before"])
    if place == "comment":
        ins = fit(phrase, comment, context["after"])
    else:
        ins = fit_code(phrase, context["before"], context["after"], names, scope)
    return say(ins.text, delete_before=ins.delete_before, delete_after=ins.delete_after)


r(op="open", path=os.path.join(os.path.dirname(SOCKET), "test.cpp"))
for _ in range(40):
    if r(op="context").get("language") == "cpp":
        break
    time.sleep(0.25)
check("a C++ file", r(op="context").get("language"), "cpp")
code("Hash include open angle stdio dot h close angle.")
cmd("new_paragraph")
code("int main open bracket close bracket open brace")
cmd("new_line")
code("int line count equals zero semicolon")
cmd("new_line")
code("comment say hello")
cmd("new_line")
code("print f open bracket quote hello comma world backslash n quote close bracket semicolon")
cmd("new_line")
code("for open bracket int i equals zero semicolon i less than ten semicolon i plus plus close bracket open brace new line line count plus equals i semicolon new line close brace")
cmd("new_line")
code("return line count semicolon")
cmd("new_line")
code("close brace")
check("a small program, indented", text().split("\n"), [
    "#include <stdio.h>",
    "",
    "int main() {",
    "    int line_count = 0;",
    "    // Say hello",
    '    printf("hello, world\\n");',
    "    for (int i = 0; i < 10; i++) {",
    "        line_count += i;",
    "    }",
    "    return line_count;",
    "}",
])
check("the file's names are reported", {"line_count", "main", "printf"} <= set(r(op="symbols")["names"]), True)
check("select finds a name by its spoken words",
      (cmd("select", "line count", nearest=True).get("ok"), r(op="text")["selected"]),
      (True, "line_count"))
cmd("doc_end")
cmd("scratch")
check("scratch that works in code", text().split("\n")[-1], "")

# Speaking over a selection puts the words in its place, with no spaces added.
cmd("doc_end")
say(LINE + 'printf("the number is = %i\\n", i);')
picked = cmd("select", "i")
for n in range(1, picked.get("choices", 1) + 1):
    if n > 1:
        cmd("select", "i")              # show the numbers again
    cmd("choose", str(n))
    if r(op="context")["before"].endswith("= %"):
        break                           # this is the i in "%i"
check("the i after the percent is selected", r(op="context")["before"].endswith("= %"), True)
check("the engine is told a selection will be replaced", r(op="context").get("selected"), True)
ctx = r(op="context")
ins = fit_code("D.", ctx["before"], ctx["after"], [])
say(ins.text.strip(" ") if ctx.get("selected") else ins.text)
check("select, choose, then say the right letter", last().strip(), 'printf("the number is = %d\\n", i);')

# ---- with a C/C++ language server (clangd), if the editor has one ------------------------
def kinds():
    return {item["kind"] for item in r(op="symbols").get("scope", [])}


cmd("select", "return line count", nearest=True)
cmd("line_start")
for _ in range(20):                       # give the language server time to read the file
    if "variable" in kinds():
        break
    time.sleep(1)
if "variable" not in kinds():
    print("SKIP no C/C++ language server in this VS Code: its checks were not run")
else:
    in_scope = {i["name"]: i["kind"] for i in r(op="symbols")["scope"]}
    check("the language server reports what is in scope",
          (in_scope.get("line_count"), in_scope.get("main")), ("variable", "function"))
    code("line counts plus equals won semicolon new line")
    code("four open bracket int j equals zero semicolon j less than line count semicolon j plus plus close bracket open brace new line")
    code("line count equals line counts times to semicolon new line close brace new line")
    lines = text().split("\n")
    at = lines.index("    line_count += 1;")
    check("misheard names, keywords and numbers are put right", lines[at:at + 5], [
        "    line_count += 1;",
        "    for (int j = 0; j < line_count; j++) {",
        "        line_count = line_count * 2;",
        "    }",
        "    return line_count;",
    ])
    code("int line counter equals zero semicolon new line")
    check("a new name being declared is left alone",
          [line for line in text().split("\n") if "counter" in line or "int line" in line][-1:],
          ["    int line_counter = 0;"])

print("failures:", failures, flush=True)
sys.exit(1 if failures else 0)
