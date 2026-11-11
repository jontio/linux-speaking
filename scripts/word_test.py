"""Live test of dictation into Microsoft Word. Windows only.

    venv\\Scripts\\python.exe app\\scripts\\word_test.py

It opens a blank document of its own in Word, works on that alone, and closes it without
saving. Word doesn't need to be in front.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pythoncom  # noqa: E402
import win32com.client.dynamic  # noqa: E402

from dictation import winapi  # noqa: E402

failures = []


def check(what, got, want):
    ok = got == want
    print(("ok    " if ok else "FAIL  ") + what + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))
    if not ok:
        failures.append(what)


def main():
    pythoncom.CoInitialize()
    started = False
    try:
        word = winapi.running("Word.Application")
    except pythoncom.com_error:
        word = win32com.client.dynamic.Dispatch("Word.Application")
        started = True
    word.Visible = True
    doc = word.Documents.Add()
    try:
        run(word, doc)
    finally:
        doc.Close(False)
        if started:
            word.Quit(False)
    print(f"\n{len(failures)} failed" if failures else "\nall passed")
    return 1 if failures else 0


def run(word, doc):
    window = doc.ActiveWindow
    area = None
    for _ in range(50):
        area = winapi.child_of_class(window.Hwnd, "_WwG")
        if area:
            break
        time.sleep(0.1)
    assert area, "Word's editing area wasn't found"
    os.environ["LS_OFFICE_TEST_WINDOW"] = str(area)
    os.environ["LS_MAIL"] = os.environ["LS_VSCODE"] = "0"
    os.environ["LS_SETTINGS_FILE"] = os.path.join(tempfile.mkdtemp(), "settings.json")
    from dictation.engine import Engine
    from dictation.formatting import PARAGRAPH
    from dictation.word_target import WordTarget

    target = WordTarget()
    shown = []
    target.show_numbers = shown.append
    selection = window.Selection

    def ask(**message):
        return target.request(message)

    def text():
        return (doc.Content.Text or "").rstrip("\r")

    def reset(content="", start=None, end=None):
        doc.Content.Text = content
        at = len(content) if start is None else start
        selection.SetRange(at, at if end is None else end)
        target.history.clear()

    # ---- the basics
    check("status", ask(op="status").get("ready"), True)
    reset()
    check("context in an empty document", ask(op="context"), {"ok": True, "before": "", "after": ""})
    ask(op="insert", text="Hello world.")
    check("insert", text(), "Hello world.")
    check("cursor after the insert", (selection.Start, selection.End), (12, 12))
    check("context after it", ask(op="context").get("before"), "Hello world.")
    reset("one two three", 4, 7)
    check("context with a selection", ask(op="context"),
          {"ok": True, "before": "one ", "after": " three", "selected": True})
    ask(op="insert", text="2")
    check("dictating over a selection", text(), "one 2 three")
    reset("abcdef", 3)
    ask(op="insert", text="-", delete_before=2, delete_after=1)
    check("delete before and after", text(), "a-ef")
    ask(op="command", name="undo")
    check("one undo takes back the whole phrase", text(), "abcdef")
    reset("hello", 0)
    ask(op="insert", text="Well. ", capitalise_next=True)
    check("capital for what follows", text(), "Well. Hello")
    reset("x")
    ask(op="insert", text="a" + PARAGRAPH + "b")
    check("a paragraph break", doc.Paragraphs.Count, 2)
    check("its text", text(), "xa\rb")
    check("context is only the cursor's own paragraph", ask(op="context").get("before"), "b")
    reset("say ")
    ask(op="insert", text='"hi" and it\'s')
    print("      quotes typed by Word as:", repr(text()))

    # ---- editing commands
    reset("one two three")
    ask(op="insert", text=" four")
    ask(op="command", name="scratch")
    check("scratch that", text(), "one two three")
    check("scratch with nothing left", ask(op="command", name="scratch").get("why"), "nothing to scratch")
    ask(op="command", name="backspace", arg="3")
    check("backspace 3", text(), "one two th")
    reset("one two three", 4, 7)
    ask(op="command", name="delete")
    check("delete that, on a selection", text(), "one  three")
    reset("first")
    ask(op="command", name="new_paragraph")
    ask(op="insert", text="Second")
    check("new paragraph", text(), "first\rSecond")
    ask(op="command", name="new_line")
    ask(op="insert", text="Third")
    check("new line", text(), "first\rSecond\x0bThird")

    # ---- moving
    reset("alpha beta gamma\rdelta epsilon\rzeta", 8)
    ask(op="command", name="line_end")
    check("go to end of line", selection.Start, 16)
    ask(op="command", name="line_start")
    check("go to start of line", selection.Start, 0)
    ask(op="command", name="para_end")
    check("go to end of paragraph", selection.Start, 16)
    ask(op="command", name="para_end")
    check("again goes on to the next", selection.Start, 30)
    ask(op="command", name="para_start")
    check("go to start of paragraph", selection.Start, 17)
    ask(op="command", name="para_start")
    check("again goes back to the one before", selection.Start, 0)
    ask(op="command", name="doc_end")
    check("go to bottom", selection.Start, 35)
    ask(op="command", name="word_left", arg="2")
    check("move left 2 words", selection.Start, 23)
    ask(op="command", name="doc_top")
    check("go to top", selection.Start, 0)
    ask(op="command", name="word_right", arg="1")
    check("move right a word", selection.Start, 6)
    ask(op="command", name="line_down", arg="2")
    check("down 2 lines", selection.Paragraphs(1).Range.Text, "zeta\r")
    ask(op="command", name="line_up", arg="1")
    check("up one line", selection.Paragraphs(1).Range.Text, "delta epsilon\r")
    ask(op="command", name="select_line")
    check("select line", selection.Text, "delta epsilon")
    ask(op="command", name="delete_line")
    check("delete line", text(), "alpha beta gamma\rzeta")
    ask(op="command", name="select_all")
    check("select all", (selection.Start, selection.End), (0, doc.Content.End))
    ask(op="command", name="unselect")
    check("unselect that", selection.Start, selection.End)

    # ---- selecting
    reset("the cat sat on the mat. The dog saw the cat.")
    check("select, one match", ask(op="command", name="select", arg="dog").get("ok"), True)
    check("it is selected", selection.Text, "dog")
    check("select, not there", ask(op="command", name="select", arg="zebra").get("why"), "can't find that")
    reply = ask(op="command", name="select", arg="cat", nearest=True)
    check("nearest match wins when numbers are off", (reply.get("ok"), selection.Start), (True, 40))
    selection.SetRange(0, 0)
    reply = ask(op="command", name="select", arg="the")
    check("several matches are numbered", reply.get("choices"), 4)
    check("a place on screen for each", [len(p) for p in shown[-1]] if shown else None, [5, 5, 5, 5])
    print("      first number at", shown[-1][0][1:3] if shown and shown[-1] else None)
    check("choose 3", ask(op="command", name="choose", arg="3").get("ok"), True)
    check("the third is selected", (selection.Start, selection.Text), (24, "The"))
    check("the numbers are taken away", shown[-1:], [[]])
    ask(op="command", name="select", arg="the")
    ask(op="command", name="cancel_choices")
    check("cancelling takes them away", shown[-1:], [[]])
    check("choose with nothing showing", ask(op="command", name="choose", arg="1").get("why"),
          "nothing to choose from")

    # ---- formatting
    reset("plain ")
    ask(op="insert", text="bold words")
    ask(op="command", name="bold")
    check("bold that", (doc.Range(6, 16).Font.Bold, doc.Range(0, 5).Font.Bold), (-1, 0))
    ask(op="command", name="all_caps")
    check("all caps that", text(), "plain BOLD WORDS")
    ask(op="command", name="no_caps")
    check("no caps that", text(), "plain bold words")
    ask(op="command", name="cap")
    check("cap that", text(), "plain Bold Words")
    ask(op="command", name="select_last")
    check("select that", selection.Text, "Bold Words")
    check("unknown command", ask(op="command", name="duplicate_line").get("why"), "unknown command")
    check("unknown request", ask(op="move", steps=[]).get("why"), "unknown request")

    # ---- through the engine: fitting to the text, and commands by voice
    engine = Engine(transcriber=object())
    engine.targets.office = target
    engine.status.state = __import__("dictation.status", fromlist=["State"]).State.AWAKE
    reset()
    engine.handle_text("hello there", True)
    check("engine: first words get a capital", text(), "Hello there")
    engine.handle_text("full stop", True)
    engine.handle_text("this is the second sentence", True)
    check("engine: spacing and capital after a full stop", text(),
          "Hello there. This is the second sentence")
    engine.handle_text("scratch that", True)
    check("engine: scratch that", text(), "Hello there.")
    engine.handle_text("new paragraph", True)
    engine.handle_text("next one", True)
    check("engine: new paragraph", text(), "Hello there.\rNext one")
    engine.handle_text("go to start of line", True)
    check("engine: go to start of line", selection.Start, 13)
    engine.handle_text("move right 1 word", True)
    check("engine: move right a word", selection.Start, 18)
    engine.handle_text("delete line", True)
    check("engine: delete line", text(), "Hello there.")
    engine.handle_text("tab", True)
    check("engine: tab", text(), "Hello there.\r\t")
    engine.handle_text("select hello", True)
    engine.handle_text("goodbye", True)
    check("engine: select and say", text(), "Goodbye there.\r\t")
    check("engine: says where it is typing", engine.status.target, "Word")


if __name__ == "__main__":
    sys.exit(main())
