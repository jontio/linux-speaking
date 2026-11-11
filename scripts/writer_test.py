"""Drives the Writer extension over its socket and checks the document.

Run by scripts/test-writer.sh against a hidden LibreOffice with an empty document.
"""
import sys
import time

from dictation import client

failures = 0


def send(**message):
    return client.request(message)


def doc():
    return send(op="text")["text"]


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


for _ in range(60):
    if send(op="status").get("ready"):
        break
    time.sleep(0.5)
else:
    sys.exit("extension never became ready: %r" % send(op="status"))

check("empty document", doc(), "")
send(op="dictate", text="The cat sat.")
check("first phrase capitalised, full stop dropped", doc(), "The cat sat")
send(op="dictate", text="Full stop.")
check("spoken full stop attaches", doc(), "The cat sat.")
send(op="dictate", text="It was happy.")
check("space and capital after full stop", doc(), "The cat sat. It was happy")
check("context", send(op="context")["before"], "The cat sat. It was happy")
send(op="command", name="scratch")
check("scratch that", doc(), "The cat sat.")
send(op="command", name="scratch")
check("scratch that again", doc(), "The cat sat")
send(op="command", name="undo")
check("undo that", doc(), "The cat sat.")
send(op="command", name="new_paragraph")
send(op="dictate", text="second paragraph here")
check("new paragraph", doc(), "The cat sat.\nSecond paragraph here")
r = send(op="command", name="select", arg="cat", nearest=True)
check("select finds a word in the previous paragraph", r.get("ok"), True)
send(op="dictate", text="Dog.")
check("select-and-say replaces the selection", doc(), "The dog sat.\nSecond paragraph here")
send(op="dictate", text="Black.")
check("insert mid-sentence", doc(), "The dog black sat.\nSecond paragraph here")
send(op="command", name="scratch")
check("scratch mid-sentence", doc(), "The dog sat.\nSecond paragraph here")
send(op="command", name="select", arg="second paragraph", nearest=True)
send(op="command", name="all_caps")
check("all caps that", doc(), "The dog sat.\nSECOND PARAGRAPH here")
send(op="command", name="no_caps")
check("no caps that", doc(), "The dog sat.\nsecond paragraph here")
send(op="command", name="cap")
check("cap that", doc(), "The dog sat.\nSecond Paragraph here")
check("bold that", send(op="command", name="bold").get("ok"), True)
check("italicize that", send(op="command", name="italic").get("ok"), True)
check("underline that", send(op="command", name="underline").get("ok"), True)
check("select something missing", send(op="command", name="select", arg="zebra").get("why"), "can't find that")
send(op="command", name="select", arg="here", nearest=True)
send(op="command", name="unselect")
send(op="dictate", text="comma and more new line last line")
check("comma, new line", doc(), "The dog sat.\nSecond Paragraph here, and more\nLast line")
send(op="command", name="select", arg="sat", nearest=True)
send(op="command", name="delete")
check("delete that", doc(), "The dog .\nSecond Paragraph here, and more\nLast line")

send(op="command", name="doc_top")
send(op="dictate", text="Start.")
check("go to top", doc().startswith("Start The dog"), True)
send(op="command", name="line_end")
send(op="dictate", text="End.")
check("go to end of line", doc().split("\n")[0], "Start The dog . End")
send(op="command", name="doc_end")
send(op="dictate", text="for a period of time period")
check("period is a word by default", doc().endswith("Last line for a period of time period"), True)
send(op="command", name="scratch")
send(op="dictate", text="it ended period", spoken_off=[])
check("period when switched on", doc().endswith("Last line it ended."), True)
send(op="dictate", text="then a full stop", spoken_off=["full stop"])
check("full stop switched off", doc().endswith("it ended. Then a full stop"), True)
send(op="command", name="line_start")
send(op="dictate", text="Well comma")
check("go to start of line", doc().split("\n")[-1].startswith("Well, Last line"), True)

send(op="command", name="doc_end")
r = send(op="insert", text=", inserted", delete_before=0, delete_after=0, capitalise_next=False)
check("insert op", (r.get("ok"), doc().endswith("full stop, inserted")), (True, True))
send(op="command", name="scratch")
check("scratch after insert op", doc().endswith("Then a full stop"), True)

send(op="command", name="doc_top")
send(op="command", name="para_end")
send(op="dictate", text="tail")
check("go to end of paragraph", doc().split("\n")[0].endswith("End tail"), True)
send(op="command", name="doc_end")
send(op="command", name="para_start")
send(op="dictate", text="Head")
# "Last line" follows a line break, so its paragraph starts at "Second Paragraph".
check("go to start of paragraph", "\nHead Second Paragraph here" in doc(), True)
send(op="command", name="doc_end")
r = send(op="move", steps=[["text", "gotoStartOfParagraph", False], ["text", "gotoEndOfParagraph", False]])
send(op="dictate", text="comma moved")
check("move op", (r.get("ok"), doc().endswith("full stop, moved")), (True, True))
check("move op refuses other methods", send(op="move", steps=[["view", "setString", "x"]]).get("ok"), False)

send(op="command", name="backspace", arg="1")
check("backspace", doc().endswith("full stop, move"), True)
send(op="command", name="backspace", arg="6")
check("backspace 6", doc().endswith("full stop"), True)
send(op="command", name="select", arg="full stop", nearest=True)
send(op="command", name="backspace", arg="1")
check("backspace removes a selection", doc().endswith("Then a "), True)
send(op="command", name="undo")
send(op="command", name="undo")
check("backspace can be undone", doc().endswith("full stop, move"), True)

# Numbered matches. Start a clean paragraph with the same word three times.
send(op="command", name="doc_end")
send(op="command", name="new_paragraph")
send(op="dictate", text="the fox saw a fox chase a third fox")
state = send(op="text")
before_text, was_modified = state["text"], state["modified"]
r = send(op="command", name="select", arg="fox")
check("several matches are numbered", r.get("choices"), 3)
state = send(op="text")
check("numbers shown above the words", state["rubies"], ["1", "2", "3"])
check("numbering leaves the text alone", state["text"], before_text)
check("numbering doesn't mark the document modified", state["modified"], was_modified)
r = send(op="command", name="choose", arg="2")
state = send(op="text")
check("choose 2 selects the second", (r.get("ok"), state["selected"], state["rubies"]), (True, "fox", []))
send(op="dictate", text="dog")
check("the chosen one is replaced", doc().endswith("The fox saw a dog chase a third fox"), True)
send(op="command", name="undo")
check("one undo restores it, with no numbering steps", doc().endswith("The fox saw a fox chase a third fox"), True)
send(op="command", name="select", arg="fox")
send(op="dictate", text="comma indeed")
check("dictating cancels the numbers", send(op="text")["rubies"], [])
send(op="command", name="scratch")
send(op="command", name="select", arg="fox")
send(op="command", name="cancel_choices")
check("cancel takes the numbers away", send(op="text")["rubies"], [])
check("one match is selected straight away",
      (send(op="command", name="select", arg="third").get("choices"), send(op="text")["selected"]),
      (None, "third"))
check("choose with nothing showing", send(op="command", name="choose", arg="1").get("why"), "nothing to choose from")

send(op="command", name="select", arg="fox")
check("numbers showing again", len(send(op="text")["rubies"]) > 1, True)
time.sleep(3.5)  # the test runs with a 2 second limit
check("numbers clear by themselves after the time limit", send(op="text")["rubies"], [])

print("failures:", failures)
sys.exit(1 if failures else 0)
