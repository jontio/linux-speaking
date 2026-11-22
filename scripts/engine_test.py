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
os.environ["LS_VSCODE"] = "0"
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
rng = np.random.default_rng(7)
for label, seconds in (("hiss", 1.3), ("longer hiss", 2.4)):
    noise = rng.normal(0, 0.02, int(16000 * seconds)).astype(np.float32)
    hear(engine, noise)
    check(f"{label} does not wake it", engine.status.state, State.ASLEEP)
bumps = rng.normal(0, 0.003, 32000).astype(np.float32)
for at in (5000, 12000, 20000, 27000):
    bumps[at:at + 300] += rng.normal(0, 0.2, 300).astype(np.float32) * np.hanning(300).astype(np.float32)
hear(engine, bumps)
check("bumps and clicks do not wake it", engine.status.state, State.ASLEEP)
quiet = say("wake up")
quiet = quiet * 0.05 + rng.normal(0, 0.05 * float(np.sqrt((quiet ** 2).mean())) / 4, len(quiet)).astype(np.float32)
hear(engine, quiet)
check("a quiet, noisy wake up still wakes it", engine.status.state, State.AWAKE)
engine.status.state = State.ASLEEP
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
engine.handle_text("one two three four five", awake=True)
engine.handle_text("Move left two words.", awake=True)
engine.handle_text("and", awake=True)
check("move left two words", doc(), "One two three and four five")
engine.handle_text("Move right a word.", awake=True)
engine.handle_text("then", awake=True)
check("move right a word", doc(), "One two three and four then five")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
for line in ("top line", "New paragraph.", "middle line", "New paragraph.", "bottom line"):
    engine.handle_text(line, awake=True)
engine.handle_text("Up one line.", awake=True)
engine.handle_text("Delete line.", awake=True)
check("up one line, then delete line", doc(), "Top line\n\nBottom line")
engine.handle_text("Down a line.", awake=True)
engine.handle_text("Select line.", awake=True)
check("down a line, then select line", client.request({"op": "text"})["selected"], "Bottom line")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
engine.handle_text("some words here", awake=True)
engine.handle_text("New paragraph.", awake=True)
engine.handle_text("and more below", awake=True)
engine.handle_text("Select all.", awake=True)
check("select all", client.request({"op": "text"})["selected"].split(), "Some words here And more below".split())
engine.handle_text("Delete that.", awake=True)
check("select all, then delete that, empties the document", doc(), "")
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
# Speaking over a selection adds no spaces of its own.
engine.handle_text("the price is 5 dollars", awake=True)
client.request({"op": "command", "name": "select", "arg": "5", "nearest": True})
engine.handle_text("six", awake=True)
check("select-and-say keeps the spacing that was there", doc(), "The price is $6")
client.request({"op": "command", "name": "select", "arg": "price is", "nearest": True})
engine.handle_text("cost was", awake=True)
check("and for several words", doc(), "The cost was $6")
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
before = doc()
engine.handle_text("tree", awake=True)
check("one word that is no number is not typed, and the numbers stay",
      (engine.status.choosing, client.request({"op": "text"})["rubies"], doc()), (2, ["1", "2"], before))
engine.handle_text("carry on", awake=True)
check("other speech cancels the numbers", (engine.status.choosing, client.request({"op": "text"})["rubies"]), (0, []))
for _ in range(6):
    engine.handle_text("Scratch that.", awake=True)
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
# "Correct ...": what is said next takes the words' place, and the cursor goes back.
engine.settings.states = {"choose_numbers": False}
engine.handle_text("the price is 5 dollars", awake=True)
engine.handle_text("Correct price.", awake=True)
engine.handle_text("cost", awake=True)
engine.handle_text("for each one", awake=True)
check("correct, and the cursor goes back to the end", doc(), "The cost is $5 for each one")
engine.handle_text("Correct five.", awake=True)
engine.handle_text("six", awake=True)
engine.handle_text("full stop", awake=True)
check("words that sound the same, and figures", doc(), "The cost is $6 for each one.")
engine.handle_text("Correct me if I'm wrong.", awake=True)
check("words that aren't there make it a sentence, and it is typed", doc(),
      "The cost is $6 for each one. Correct me if I'm wrong")
engine.handle_text("Select the best one.", awake=True)
check("and the same for select", doc(),
      "The cost is $6 for each one. Correct me if I'm wrong select the best one")
engine.settings.states = {}
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
# Part numbers on the person's own list come out as they spelled them (only in memory:
# the settings file is not touched).
engine.settings.words = ("vLR54H20", "vLR5340")
hear(engine, say("I flashed the V L R fifty three forty board"))
check("a part number said in words is written as it is spelled", "the vLR5340" in doc(), True)
hear(engine, say("V L R fifty four H twenty is the new one"))
check("and at the start of a sentence it keeps its small letter", "vLR54H20 is the new one" in doc(), True)
engine.settings.words = ()
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
# "Delete line": several at once, and an empty one, which must not take the last phrase
# said along with it.
for line in ("one", "New paragraph.", "two", "New paragraph.", "three", "New paragraph.", "four"):
    engine.handle_text(line, awake=True)
client.request({"op": "command", "name": "doc_top"})
engine.handle_text("Delete 2 lines.", awake=True)
check("delete 2 lines takes both", doc(), "\nThree\nFour")
engine.handle_text("Delete line.", awake=True)
check("delete line on an empty line leaves what was said last alone", doc(), "\nThree\nFour")
engine.handle_text("Down one line.", awake=True)
engine.handle_text("Delete line.", awake=True)
check("delete line empties the line", doc(), "\n\nFour")
engine.handle_text("Delete line.", awake=True)
check("and said again takes the empty line away", doc(), "\nFour")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
check("cleared", doc(), "")
# Commands of the person's own, and commands only. A real program is really started (one
# that only makes an empty file); no keys are pressed and nothing is opened on the screen.
made = os.path.join(tempfile.mkdtemp(), "made by a command")
engine.settings.shortcuts = {"make the file": f"run: touch \"{made}\"",
                             "ask and make": f"ask first\nrun: touch \"{made} too\"",
                             "sign off": "Kind regards,"}


def wait_for(path, seconds=5.0):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not os.path.exists(path):
        time.sleep(0.1)
    return os.path.exists(path)


engine.settings.states = {"run_programs": False}
engine.handle_text("Make the file.", awake=True)
check("a command that runs a program does nothing until that is switched on",
      (wait_for(made, 1.0), doc()), (False, ""))
engine.settings.states = {"run_programs": True}
engine.handle_text("Make the file.", awake=True)
check("switched on, the program is run, and nothing is typed", (wait_for(made), doc()), (True, ""))
engine.handle_text("Ask and make.", awake=True)
engine.handle_text("Yeah.", awake=True)
check("a command that asks first is left by anything but yes", wait_for(made + " too", 1.0), False)
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
engine.handle_text("Ask and make.", awake=True)
engine.handle_text("Yes.", awake=True)
check("and done on yes, which is not typed", (wait_for(made + " too"), doc()), (True, ""))
hear(engine, say("command mode"))
check("nothing that is said switches typing off", engine.status.commands_only, False)
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
engine.settings.states = {"run_programs": True, "commands_only": True}
engine.setting_changed("commands_only")
check("commands only, ticked in Settings", engine.status.commands_only, True)
engine.handle_text("This is only somebody talking.", awake=True)
check("with commands only what is no command is not typed", doc(), "")
engine.handle_text("Sign off.", awake=True)
check("but a shortcut of the person's own still is", doc(), "Kind regards,")
engine.handle_text("Select all.", awake=True)
engine.handle_text("Delete that.", awake=True)
check("and the program's commands are acted on", doc(), "")
hear(engine, say("normal mode"))
check("and nothing that is said switches it back on", (engine.status.commands_only, doc()), (True, ""))
engine.settings.states = {"run_programs": True}
engine.setting_changed("commands_only")
check("unticked in Settings", engine.status.commands_only, False)
engine.handle_text("typed again", awake=True)
check("and dictation is typed again", doc(), "Typed again")
client.request({"op": "command", "name": "doc_top"})
client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
client.request({"op": "command", "name": "delete"})
engine.settings.shortcuts, engine.settings.states = {}, {}


def empty():
    client.request({"op": "command", "name": "doc_top"})
    client.request({"op": "move", "steps": [["view", "gotoEnd", True]]})
    client.request({"op": "command", "name": "delete"})


# What was typed a moment ago is put right as the next phrase goes in (tidy.py): here the
# stop the recogniser put at the end of a phrase, when the next one starts with a comma.
engine.settings.states = {"keep_final": True}
engine.settings.sentence_ends = "pause"        # the recogniser's stop kept: what the tick box did
engine.handle_text("Hi Rick.", awake=True)
engine.handle_text(", how are you?", awake=True)
check("the stop before a comma goes as the next phrase goes in", doc(), "Hi Rick, how are you?")
engine.handle_text("Scratch that.", awake=True)
check("scratch that takes the phrase and the change back together", doc(), "Hi Rick.")
engine.handle_text(", how are you?", awake=True)
check("said again, it is put right again", doc(), "Hi Rick, how are you?")
engine.handle_text("Undo that.", awake=True)
check("undo that takes them back too", doc(), "Hi Rick.")
engine.handle_text(", how are you?", awake=True)
check("and after it the change is not made again there", doc(), "Hi Rick., how are you?")
engine.settings.states = {}
engine.settings.sentence_ends = "said"
empty()

# A word that sounds like another is put right once the next words show which it was: where
# the words decide where sentences end, the join is known, and "too" becomes "to". Where
# they don't, the words at the join are left: "it works too" and then "let me know" reads
# just the same with the stop left off.
engine.handle_text("take the cat too", awake=True)
engine.handle_text("the vet", awake=True)
check("with sentence ends not decided, the words at the join are left", doc(), "Take the cat too the vet")
engine.handle_text("Scratch that.", awake=True)
engine.handle_text("Scratch that.", awake=True)
empty()
engine.settings.sentence_ends = "words"
engine._held_mark = None
engine.handle_text("take the cat too", awake=True)
engine.handle_text("the vet", awake=True)
check("too becomes to once the vet follows", doc(), "Take the cat to the vet")
engine.handle_text("Scratch that.", awake=True)
check("and scratch that takes it back with the phrase", doc(), "Take the cat too")
engine.handle_text("Scratch that.", awake=True)
engine.settings.sentence_ends = "said"
engine._held_mark = None
empty()

# Where the words decide where sentences end (joins.py, punctuation.py), with the real model
# where it is installed: the recogniser's stop is held back, and the next phrase decides it.
from dictation import config as _config, punctuation as _punctuation  # noqa: E402
if _punctuation.installed(_config.HELPER_MODEL_DIR):
    engine.settings.sentence_ends = "words"
    engine._held_mark = None
    engine._decider = _punctuation.WordsDecider(_punctuation.Model(_config.HELPER_MODEL_DIR))
    engine.handle_text("Also, it should be an option.", awake=True)
    check("the recogniser's stop is held back", doc(), "Also, it should be an option")
    engine.handle_text("That the user can select.", awake=True)
    check("a pause in mid-sentence gets no stop", doc(), "Also, it should be an option that the user can select")
    engine.handle_text("Thanks for sending the report.", awake=True)
    check("a sentence that ended gets its stop with the next phrase",
          doc(), "Also, it should be an option that the user can select. Thanks for sending the report")
    engine.handle_text("Scratch that.", awake=True)
    check("scratch that takes the phrase and its stop back", doc(),
          "Also, it should be an option that the user can select")
    engine.handle_text("Thanks for sending the report.", awake=True)
    engine.sleep()
    # The engine's own worker types it, a moment later: wait for it, a few seconds at most.
    want = "Also, it should be an option that the user can select. Thanks for sending the report."
    for _ in range(50):
        if doc() == want:
            break
        time.sleep(0.1)
    check("going to sleep types the last stop", doc(), want)
    engine.status.state = State.AWAKE
    engine.handle_text("And the invoice.", awake=True)
    check("and it is decided again when the sentence goes on", doc(),
          "Also, it should be an option that the user can select. Thanks for sending the report and the invoice")
    engine.settings.sentence_ends = "said"
    engine._held_mark = None
    empty()
else:
    print("SKIP the punctuation model is not installed here")

# A sentence said in two phrases is heard again in one piece, and the two are typed again
# if a word comes out differently. (The second hearing is given here: the robot voice
# can't be relied on to be misheard on cue.)
class HeardTogether:
    def transcribe(self, sound, awake, prompt=""):
        return "Take the cat to the vet."


second = np.zeros(16000, dtype=np.float32)
real_ears = engine._ears
engine.settings.states = {"tidy": False}   # it would put "too" right itself: see above
engine._just_typed = None
engine.handle_text("take the cat too", awake=True)
engine._hear_again(second, time.monotonic(), 0.05, True, "")
engine._ears = lambda: HeardTogether()
engine._just_typed = None
engine.handle_text("the vet", awake=True)
check("two phrases as they were first heard", doc(), "Take the cat too the vet")
engine._hear_again(second, time.monotonic() + 1.5, 0.05, True, "")
engine._ears = real_ears
check("heard again in one piece, they are typed again", doc(), "Take the cat to the vet")
engine.handle_text("Scratch that.", awake=True)
check("and scratch that still takes away the last of them", doc(), "Take the cat to")
engine.handle_text("Scratch that.", awake=True)
check("and then the first", doc(), "")
engine.settings.states = {}
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
