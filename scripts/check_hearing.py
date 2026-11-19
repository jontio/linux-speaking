"""Which model hears your letters, your punctuation and your "wake up" best: a check with
your own voice.

It shows something to say, records you saying it, and gives that one recording to each
model in turn. So every model hears exactly the same sound, and the count at the end is a
fair one. About six minutes. Nothing leaves this computer. What is kept, in the program's
state folder, is the table of results and, in a folder called "hearing-check", the
recordings themselves (your voice saying these letters and phrases), so that another way
of hearing can be tried on them later without your saying it all again:

    ... check_hearing.py --again      goes through the kept recordings once more

Delete that folder when you no longer want them kept.

Run it with the Python that Linux Speaking runs on, with the microphone turned off in
Linux Speaking itself, or it would hear you as well:

    Linux:    ~/linux-speaking/venv/bin/python ~/linux-speaking/app/scripts/check_hearing.py
    Windows:  & "$env:USERPROFILE\\linux-speaking\\venv\\Scripts\\python.exe" `
                "$env:USERPROFILE\\linux-speaking\\app\\scripts\\check_hearing.py"

The questions it answers:

  1. The spelling box. Today, with a Parakeet model chosen, a Whisper model hears the
     letters, because it can be told to expect letters. Could the Parakeet do it?
  2. Punctuation said by itself ("question mark" after a pause): the same question.
  3. "Wake up" heard by a Whisper model through a short window, which is several times
     quicker than the usual way: is it heard as often, and is it woken by other things?
"""
from __future__ import annotations

import collections
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from dictation import audio, commands, config, models, spelling  # noqa: E402
from dictation.engine import Transcriber, normalise  # noqa: E402
from dictation.segmenter import END, START, Segmenter, SegmenterConfig  # noqa: E402
from dictation.settings import Settings, model_label  # noqa: E402

# (what to say, the letters it should give)
LETTERS = [(letter.upper(), letter) for letter in "abcdefghijklmnopqrstuvwxyz"] + [
    ("capital J", "J"), ("capital B", "B"), ("B as in bravo", "b"), ("D as in delta", "d"),
    ("E as in echo", "e"), ("P as in papa", "p"), ("S as in sierra", "s"), ("T as in tango", "t"),
    ("J O N", "jon"), ("T I", "ti")]
SIGNS = ["question mark", "full stop", "comma", "exclamation mark", "colon", "semicolon",
         "new paragraph", "new line"]
# (what to say, whether it should wake)
WAKING = [("wake up", True)] * 8 + [(said, False) for said in
                                    ("make up", "wait up", "okay", "wake me up", "hello", "walk up")]
SMALL, MEDIUM = "small.en", "medium.en"


def named(model: str) -> str:
    """A model by the name Settings gives it, shortened."""
    return model_label(model)[1].split(":")[0]


class Hearing:
    """The models, and each way of hearing that is to be compared."""

    def __init__(self, chosen: str):
        self.chosen = chosen
        self.ears = Transcriber(chosen)          # loads the chosen model, and its helper
        self.parakeet = chosen if self.ears._is_transducer(chosen) else ""
        self.whispers = [name for name in (SMALL, MEDIUM)
                         if models.kind(config.MODEL_DIR, name) == "whisper"]
        for name in self.whispers:
            self.ears._model(name)

    def letters(self) -> dict:
        ways = {"the spelling box as it is now": lambda sound: self.ears.letters(sound, spelling.PROMPT)}
        if SMALL in self.whispers:
            ways[f"{named(SMALL)}, told to expect letters, the usual way (as it was)"] = lambda sound: \
                self.ears._transcribe(sound, True, spelling.PROMPT, SMALL, False)
            ways[f"{named(SMALL)}, told to expect letters, the short window"] = lambda sound: \
                self.ears._hear_short(self.ears._model(SMALL), sound, spelling.PROMPT)
        if MEDIUM in self.whispers:
            ways[f"{named(MEDIUM)}, told to expect letters, the usual way"] = lambda sound: \
                self.ears._transcribe(sound, True, spelling.PROMPT, MEDIUM, False)
        if self.parakeet:
            ways[named(self.parakeet)] = lambda sound: \
                self.ears._by_transducer(self.parakeet, sound, speech_only=False)
        return ways

    def signs(self) -> dict:
        ways = {}
        if SMALL in self.whispers:
            ways[f"{named(SMALL)} (as now)"] = lambda sound: \
                self.ears._hear_short(self.ears._model(SMALL), sound)
        if self.parakeet:
            ways[named(self.parakeet)] = lambda sound: \
                self.ears._by_transducer(self.parakeet, sound, speech_only=False)
        return ways

    def waking(self) -> dict:
        ways = {}
        for name in self.whispers:
            ways[f"{named(name)}, the usual way"] = lambda sound, name=name: \
                self.ears._transcribe(sound, False, "", name, False)
            ways[f"{named(name)}, the short window"] = lambda sound, name=name: \
                self.ears._hear_short(self.ears._model(name), sound)
        if self.parakeet:
            ways[named(self.parakeet)] = lambda sound: \
                self.ears._asleep_by_transducer(self.parakeet, sound, None)
        return ways


def spelled(text: str) -> str:
    """The letters the spelling box would have taken `text` for."""
    try:
        steps, _ = spelling.parse(text)
        return spelling.apply("", steps)[0]
    except Exception:
        return ""


def plan(hearing: Hearing) -> list:
    """Everything to be said, in order: (part, what to say, how it is judged, the ways)."""
    wakes = lambda text: bool(text) and commands.is_wake(commands.normalise(text))
    todo = [("Letters, for the spelling box", said, (lambda text, want=want: spelled(text) == want),
             hearing.letters()) for said, want in LETTERS]
    todo += [("Punctuation said by itself", said,
              (lambda text, said=said: commands.normalise(text) == said), hearing.signs())
             for said in SIGNS]
    todo += [("\"Wake up\", and what should not wake it", said,
              (lambda text, woken=woken: wakes(text) == woken), hearing.waking())
             for said, woken in WAKING]
    return [item for item in todo if item[3]]


class Listener:
    """One phrase at a time from the microphone, cut where dictation would cut it."""

    def __init__(self, microphone: str):
        self.microphone = microphone

    def phrase(self, stop: threading.Event, longest: float = 12.0):
        """The next thing said, as sound: or None if `stop` was set first (a button was
        pressed)."""
        recorder = audio.open_microphone(self.microphone)
        try:
            segmenter = Segmenter(SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO))
            preroll = collections.deque(maxlen=config.PREROLL_FRAMES)
            said, nbytes, started = [], config.FRAME * 2, time.monotonic()
            while not stop.is_set():
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    raise audio.MicrophoneError(recorder.why() or "The microphone stopped.")
                frame = np.frombuffer(data, dtype=np.int16)
                level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
                event = segmenter.feed(level)
                if event == START:
                    said, started = list(preroll), time.monotonic()
                if segmenter.in_phrase or event == END:
                    said.append(frame)
                else:
                    preroll.append(frame)
                if event == END or (said and time.monotonic() - started > longest):
                    return normalise(np.concatenate(said).astype(np.float32) / 32768.0)
            return None
        finally:
            recorder.close()


class Speaker:
    """Stands in for the microphone when the check is itself being checked: says each
    thing in a made-up voice. (LS_CHECK_SPEAKER=espeak)"""

    def __init__(self):
        import ctypes
        self.lib = ctypes.CDLL("libespeak-ng.so.1")
        self.rate = self.lib.espeak_Initialize(1, 0, None, 0)
        self.samples = []
        kind = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int,
                                ctypes.c_void_p)

        def collect(wav, n, events) -> int:
            if wav and n > 0:
                self.samples.extend(wav[:n])
            return 0

        self.collect = kind(collect)     # kept, or it is gone before it is called
        self.lib.espeak_SetSynthCallback(self.collect)
        self.next = ""

    def phrase(self, stop: threading.Event, longest: float = 12.0):
        self.samples.clear()
        data = self.next.encode()
        self.lib.espeak_Synth(data, len(data) + 1, 0, 0, 0, 1, None, None)
        self.lib.espeak_Synchronize()
        sound = np.array(self.samples, dtype=np.float32) / 32768.0
        n = int(len(sound) * config.RATE / self.rate)
        sound = np.interp(np.linspace(0, len(sound) - 1, n), np.arange(len(sound)), sound)
        pad = np.zeros(4800, dtype=np.float32)
        return np.concatenate([pad, sound.astype(np.float32), pad])


def report(todo: list, results: dict) -> str:
    """The table: for each part, how many each way got right, how long it took, and what
    it wrote for the ones it got wrong."""
    lines = ["Linux Speaking: which model hears what best, with your own voice", ""]
    parts = list(dict.fromkeys(part for part, *_ in todo))
    for part in parts:
        items = [(at, item) for at, item in enumerate(todo) if item[0] == part and at in results]
        if not items:
            continue
        lines.append(f"{part}  ({len(items)} said)")
        for way in items[0][1][3]:
            answers = [results[at][way] for at, _ in items if way in results[at]]
            right = sum(ok for _, ok, _ in answers)
            took = statistics.median(seconds for _, _, seconds in answers) if answers else 0.0
            lines.append(f"    {right:3d} of {len(answers)} right, {took:.2f} s each: {way}")
            for at, item in items:
                text, ok, _ = results[at].get(way, ("", True, 0.0))
                if not ok:
                    lines.append(f"            you said \"{item[1]}\": it wrote \"{text}\"")
        lines.append("")
    if not any(at in results for at in range(len(todo))):
        lines.append("Nothing was said.")
    return "\n".join(lines)


def dictation_is_on() -> bool:
    """Whether Linux Speaking itself has the microphone just now: it would hear all this
    too, and with "wake up" among it, start typing."""
    try:
        with open(config.STATE_FILE, encoding="utf-8") as f:
            return f.read().strip() not in ("", "off")
    except OSError:
        return False


def kept_folder() -> str:
    return os.path.join(os.path.dirname(config.STATE_FILE), "hearing-check")


def keep(at: int, said: str, sound) -> None:
    """Keep one recording, named by its place and what was to be said."""
    import wave
    folder = kept_folder()
    try:
        os.makedirs(folder, exist_ok=True)
        slug = "-".join("".join(c if c.isalnum() else " " for c in said.lower()).split())
        with wave.open(os.path.join(folder, f"{at:03d}-{slug}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(config.RATE)
            w.writeframes((np.clip(sound, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    except OSError:
        pass


def again(chosen: str) -> int:
    """Go through the kept recordings once more, with every way of hearing as it is now,
    and print the table. No window, and nothing is recorded."""
    import glob
    import wave
    files = sorted(glob.glob(os.path.join(kept_folder(), "*.wav")))
    if not files:
        print(f"There are no kept recordings in {kept_folder()}: run the check first.")
        return 1
    todo = plan(Hearing(chosen))
    results = {}
    for path in files:
        try:
            at = int(os.path.basename(path)[:3])
            part, said, judge, ways = todo[at]
        except (ValueError, IndexError):
            continue
        with wave.open(path) as w:
            sound = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        results[at] = {}
        for way, hear in ways.items():
            started = time.monotonic()
            try:
                text = str(hear(sound) or "")
            except Exception as e:
                text = f"({type(e).__name__})"
            results[at][way] = (text, bool(judge(text)), time.monotonic() - started)
    text = report(todo, results)
    save(text)
    print(text)
    return 0


def save(text: str) -> str:
    path = os.path.join(os.path.dirname(config.STATE_FILE), "hearing-check.txt")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        return path
    except OSError:
        return ""


def main() -> int:
    from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
    from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                                 QPushButton, QVBoxLayout, QWidget)

    class Bridge(QObject):
        ready = pyqtSignal(object, object)   # the models are loaded: (the plan, or None; why not)
        asking = pyqtSignal(int)             # which one is to be said now
        heard = pyqtSignal(int, str)         # what was made of it, in a line
        ended = pyqtSignal(str)              # it is over: why, if something went wrong

    settings = Settings.load()
    chosen = settings.model or config.AWAKE_MODEL
    if "--again" in sys.argv[1:]:
        return again(chosen)
    app = QApplication(sys.argv)
    bridge = Bridge()
    state = {"todo": [], "results": {}, "paused": False, "again": False, "skip": False,
             "over": False}
    nudge = threading.Event()     # a button was pressed: whatever is being waited for ends
    self_check = os.environ.get("LS_CHECK_SPEAKER") == "espeak"

    window = QWidget()
    window.setWindowTitle("Check the hearing with my voice")
    layout = QVBoxLayout(window)
    top = QLabel("Loading the speech models… this takes a little while.")
    if dictation_is_on():
        top.setText("Linux Speaking's own microphone is on. Turn it off from its tray icon "
                    "first, or it will hear all of this too.\n" + top.text())
    top.setWordWrap(True)
    layout.addWidget(top)
    say = QLabel("")
    say.setAlignment(Qt.AlignmentFlag.AlignCenter)
    say.setStyleSheet("font-size: 34px; font-weight: bold; padding: 18px;")
    say.setWordWrap(True)
    layout.addWidget(say)
    last = QLabel("")
    last.setWordWrap(True)
    layout.addWidget(last)
    bar = QProgressBar()
    bar.setFormat("%v of %m")
    layout.addWidget(bar)
    row = QHBoxLayout()
    pause, again, skip, finish = (QPushButton(text) for text in
                                  ("Pause", "Say the last one again", "Skip this one",
                                   "Stop and show the results"))
    for button in (pause, again, skip, finish):
        button.setEnabled(False)
        row.addWidget(button)
    layout.addLayout(row)
    table = QPlainTextEdit()
    table.setReadOnly(True)
    table.setStyleSheet("font-family: monospace;")
    table.setVisible(False)
    layout.addWidget(table, 1)
    window.resize(680, 380)

    def work() -> None:
        try:
            hearing = Hearing(chosen)
            todo = plan(hearing)
        except Exception as e:  # no model, or one that won't load
            bridge.ready.emit(None, f"The speech models couldn't be loaded: {e}")
            return
        if not todo:
            bridge.ready.emit(None, "There is nothing to compare: it needs the Small Whisper "
                                    "model, and a Parakeet model chosen in Settings.")
            return
        listener = Speaker() if self_check else Listener(settings.microphone)
        bridge.ready.emit(todo, "")
        at = 0
        while at < len(todo) and not state["over"]:
            nudge.clear()
            while state["paused"] and not state["over"]:
                nudge.wait(0.2)
            if state["over"]:
                break
            if state["again"]:              # the one before this, said once more
                state["again"] = False
                at = max(0, at - 1)
                state["results"].pop(at, None)
            if state["skip"]:
                state["skip"] = False
                at += 1
                continue
            part, said, judge, ways = todo[at]
            bridge.asking.emit(at)
            if self_check:
                listener.next = said
            try:
                sound = listener.phrase(nudge)
            except Exception as e:
                bridge.ended.emit(f"The microphone couldn't be used: {e}")
                return
            if sound is None:
                continue                    # a button was pressed while it listened: see above
            if not self_check:
                keep(at, said, sound)       # so that it can be gone through again: see again()
            answers = {}
            for way, hear in ways.items():
                started = time.monotonic()
                try:
                    text = str(hear(sound) or "")
                except Exception as e:
                    text = f"({type(e).__name__})"
                answers[way] = (text, bool(judge(text)), time.monotonic() - started)
            state["results"][at] = answers
            marks = "   ".join(f"{'right' if ok else 'WRONG'}: {way.split(',')[0]} wrote \"{text}\""
                               for way, (text, ok, _) in answers.items())
            bridge.heard.emit(at, marks)
            time.sleep(0.05 if self_check else 0.7)
            at += 1
        bridge.ended.emit("")

    def on_ready(todo, why) -> None:
        if todo is None:
            top.setText(why)
            return
        state["todo"] = todo
        bar.setRange(0, len(todo))
        for button in (pause, again, skip, finish):
            button.setEnabled(True)

    def on_asking(at: int) -> None:
        part, said, _, _ = state["todo"][at]
        top.setText(f"{part}.  Say what is shown, then wait: it moves on by itself.")
        say.setText(said)
        bar.setValue(at)

    def on_heard(at: int, marks: str) -> None:
        last.setText(f"\"{state['todo'][at][1]}\":   {marks}")

    def on_ended(why: str) -> None:
        text = report(state["todo"], state["results"])
        where = save(text)
        say.setText("")
        top.setText((why + "\n" if why else "") + "Finished."
                    + (f" The table is also kept in {where}" if where else "")
                    + ("" if self_check else f"\nThe recordings are kept in {kept_folder()} so that "
                       "this can be gone through again without your saying it all again. "
                       "Delete that folder when you no longer want them kept."))
        last.setText("")
        bar.setValue(len(state["results"]))
        for button in (pause, again, skip, finish):
            button.setEnabled(False)
        table.setPlainText(text)
        table.setVisible(True)
        window.resize(820, 640)
        print(text, flush=True)
        if self_check:
            QTimer.singleShot(100, app.quit)

    def on_pause() -> None:
        state["paused"] = not state["paused"]
        pause.setText("Carry on" if state["paused"] else "Pause")
        if state["paused"]:
            top.setText("Paused. Nothing is being listened to. Press Carry on when you are ready.")
        nudge.set()

    def press(what: str) -> None:
        state[what] = True
        nudge.set()

    bridge.ready.connect(on_ready)
    bridge.asking.connect(on_asking)
    bridge.heard.connect(on_heard)
    bridge.ended.connect(on_ended)
    pause.clicked.connect(on_pause)
    again.clicked.connect(lambda: press("again"))
    skip.clicked.connect(lambda: press("skip"))
    finish.clicked.connect(lambda: press("over"))
    app.aboutToQuit.connect(lambda: press("over"))
    window.show()
    threading.Thread(target=work, daemon=True).start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
