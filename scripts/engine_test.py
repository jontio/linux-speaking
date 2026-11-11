"""Runs synthesized speech through the real engine into a hidden Writer.

Needs faster-whisper and libespeak-ng. Run with:
  PYTHON=venv/bin/python scripts/test-writer.sh scripts/engine_test.py
"""
import ctypes
import os
import sys
import tempfile
import time
import wave

import numpy as np

os.environ["LS_MAIL"] = "0"  # the running engine owns the Thunderbird port
os.environ["LS_EDITOR"] = "0"  # test Writer only, whatever window is in front
os.environ.setdefault("LS_STATE_FILE", os.path.join(tempfile.mkdtemp(), "state"))

from dictation import client  # noqa: E402
from dictation.engine import Engine  # noqa: E402
from dictation.status import State  # noqa: E402

failures = 0
_lib = ctypes.CDLL("libespeak-ng.so.1")
_rate = _lib.espeak_Initialize(1, 0, None, 0)
_samples = []
_CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)


@_CB
def _collect(wav, n, events):
    if wav and n > 0:
        _samples.extend(wav[:n])
    return 0


_lib.espeak_SetSynthCallback(_collect)


def say(text):
    """Synthesized speech as 16 kHz audio, with silence either side."""
    _samples.clear()
    data = text.encode("utf-8")
    _lib.espeak_Synth(data, len(data) + 1, 0, 0, 0, 1, None, None)
    _lib.espeak_Synchronize()
    audio = np.array(_samples, dtype=np.float32) / 32768.0
    n = int(len(audio) * 16000 / _rate)
    audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    pad = np.zeros(4800, dtype=np.float32)
    return np.concatenate([pad, audio.astype(np.float32), pad])


def check(label, got, want):
    global failures
    ok = got == want
    failures += not ok
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


def doc():
    return client.request({"op": "text"})["text"]


def hear(engine, audio):
    t = time.time()
    engine.handle_audio(audio)
    print(f"     heard {engine.status.last_heard!r} in {time.time() - t:.2f}s")


for _ in range(60):
    if client.request({"op": "status"}).get("ready"):
        break
    time.sleep(0.5)
else:
    sys.exit("extension never became ready")

engine = Engine()
engine.status.state = State.ASLEEP  # as if switched on, but without the microphone

hear(engine, say("this should be ignored"))
check("asleep ignores speech", (engine.status.state, doc()), (State.ASLEEP, ""))
hear(engine, say("wake up"))
check("wake up", engine.status.state, State.AWAKE)
hear(engine, say("the weather is nice today"))
typed = doc()
check("dictation typed a capitalised phrase", typed[:1].isupper() and len(typed) > 10, True)
# The robot voice garbles short commands, so the command itself goes in as text.
engine.handle_text("Scratch that.", awake=True)
check("scratch that", doc(), "")
# Settings are applied by the engine, with no change to the extension.
engine.settings.states = {"say:period": True, "say:full stop": False}
engine.handle_text("The end period", awake=True)
check("period switched on", doc(), "The end.")
engine.handle_text("came to a full stop", awake=True)
check("full stop switched off", doc(), "The end. Came to a full stop")
engine.settings.states = {}
engine.handle_text("Scratch that.", awake=True)
engine.handle_text("Scratch that.", awake=True)
check("back to empty", doc(), "")
engine.handle_text("one two three four", awake=True)
engine.handle_text("Delete last word.", awake=True)
check("delete last word", doc(), "One two three")
engine.handle_text("Delete last two words.", awake=True)
check("delete last two words", doc(), "One")
engine.handle_text("Delete last word.", awake=True)
check("delete the only word", doc(), "")
# Paragraph moves carry on into the next or previous paragraph when already at the edge.
for line in ("first", "New paragraph.", "second", "New paragraph.", "third"):
    engine.handle_text(line, awake=True)
client.request({"op": "command", "name": "doc_top"})
engine.handle_text("Go to end of paragraph.", awake=True)
engine.handle_text("Go to end of paragraph.", awake=True)
engine.handle_text("comma two", awake=True)
check("end of paragraph twice reaches the next one", doc(), "First\nSecond, two\nThird")
engine.handle_text("Go to start of paragraph.", awake=True)
engine.handle_text("Go to start of paragraph.", awake=True)
engine.handle_text("One.", awake=True)
check("start of paragraph twice reaches the one before", doc(), "One First\nSecond, two\nThird")
engine.handle_text("Undo that.", awake=True)
check("undo that removes what was just said", doc(), "First\nSecond, two\nThird")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
engine.settings.states = {}
# Spelling a word letter by letter.
engine.handle_text("my name is", awake=True)
engine.handle_text("Spell that.", awake=True)
check("spell that opens spelling", (engine.status.spelling, doc()), (True, "My name is"))
engine.handle_text("Capital J-O-N.", awake=True)
engine.handle_text("Tea.", awake=True)
engine.handle_text("Why?", awake=True)
engine.handle_text("Backspace.", awake=True)
engine.handle_text("I.", awake=True)
check("letters collect in the box, not the document", (engine.status.spelled, doc()), ("Jonti", "My name is"))
engine.handle_text("Done.", awake=True)
check("done puts the word in", (engine.status.spelling, doc()), (False, "My name is Jonti"))
engine.handle_text("Spell that.", awake=True)
engine.handle_text("X, Y, Z.", awake=True)
engine.handle_text("Cancel.", awake=True)
check("cancel leaves the document alone", (engine.status.spelling, doc()), (False, "My name is Jonti"))
engine.handle_text("Spell that.", awake=True)
engine.handle_text("C-O-M-M-A", awake=True)
engine.handle_text("That's it.", awake=True)
check("a spelled word is never turned into punctuation", doc(), "My name is Jonti comma")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
# Numbered matches: select a word that appears twice, then say a number.
engine.handle_text("the fox saw a fox", awake=True)
engine.handle_text("Select fox.", awake=True)
state = client.request({"op": "text"})
check("select shows numbers", (engine.status.choosing, state["rubies"]), (2, ["1", "2"]))
engine.handle_text("Two.", awake=True)
state = client.request({"op": "text"})
check("saying a number picks it", (engine.status.choosing, state["rubies"], state["selected"]), (0, [], "fox"))
engine.handle_text("dog", awake=True)
check("the second one was replaced", doc(), "The fox saw a dog")
engine.handle_text("Select fox.", awake=True)
engine.handle_text("Select the.", awake=True)
engine.handle_text("and more", awake=True)
check("one match needs no number", doc(), "And more fox saw a dog")
engine.handle_text("the fox", awake=True)
engine.handle_text("Select fox.", awake=True)
engine.handle_text("carry on", awake=True)
check("other speech cancels the numbers", (engine.status.choosing, client.request({"op": "text"})["rubies"]), (0, []))
for _ in range(6):
    engine.handle_text("Scratch that.", awake=True)
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
check("cleared", doc(), "")
if len(sys.argv) > 1:
    w = wave.open(sys.argv[1])
    hear(engine, np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0)
    print("     document:", repr(doc()))
    check("real recording typed something", len(doc()) > 50, True)
hear(engine, say("go to sleep"))
check("go to sleep", engine.status.state, State.ASLEEP)
before = doc()
hear(engine, say("this should also be ignored"))
check("asleep again ignores speech", doc(), before)

print("failures:", failures)
sys.stdout.flush()
os._exit(1 if failures else 0)
