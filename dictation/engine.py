"""The speech engine: microphone, pause detection, Whisper, and what to do with each phrase."""
from __future__ import annotations

import collections
import math
import os
import queue
import subprocess
import threading
import time

import numpy as np

from . import client, config
from .commands import (
    MOVES, Command, Dictation, choice, interpret, is_move, last_words_length, move_steps,
)
from .formatting import SPOKEN, fit
from .mailbridge import MailBridge
from .targets import Targets
from .vscode_target import VSCodeTarget
from .words import Lexicon
from .settings import Settings
from .segmenter import END, START, Segmenter, SegmenterConfig
from . import accessibility, coding, spelling
from .status import State, Status



def log(message: str) -> None:
    """One line to the service log. Dictated text is never logged, only its length."""
    print(message, flush=True)


# parec is used, not pw-record, because it lets the client be named. The desktop's
# microphone indicator then says "Linux Speaking is using the microphone".
RECORD_COMMAND = [
    "parec", "--raw", f"--rate={config.RATE}", "--channels=1", "--format=s16le",
    "--latency-msec=20", "--client-name=Linux Speaking",
    "--stream-name=Listening for dictation",
    "--property=application.icon_name=audio-input-microphone",
]

# Things Whisper invents from noise. Dropped unless Whisper is confident.
PHANTOMS = {"thank you", "thanks for watching", "you", "bye", "thank you very much"}


def level_step(rms: float) -> int:
    """Loudness as 0 to 5 bars: 0 is silence, 5 is a strong microphone signal."""
    if rms < 1:
        return 0
    db = 20 * math.log10(rms / 32768.0)
    return max(0, min(config.LEVEL_STEPS, round((db + 60) / 8)))


def meter_value(loudness: float, noise: float) -> tuple[int, int]:
    """How far a sound stands above the background: (0 to 100 for the bar, decibels).

    The bar is full at 40 dB. Speech wants 25 dB or more to be recognised well.
    """
    if loudness < 1 or noise < 1:
        return 0, 0
    db = max(0.0, 20 * math.log10(loudness / noise))
    return min(100, round(db * 2.5)), round(db)


def read_number(path: str, default: float) -> float:
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return default


def write_text(path: str, text: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
    except OSError:
        pass


def normalise(audio):
    """Turn a quiet phrase up so Whisper hears it at a normal level."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak <= 0:
        return audio
    return audio * min(config.NORMALISE_PEAK / peak, config.MAX_GAIN)


class Transcriber:
    """Whisper. One model listens for "wake up", and one, chosen in Settings, takes dictation."""

    def __init__(self, dictation_model: str = ""):
        self._loaded = {}  # folder name -> model, so a model used for both is loaded once
        self.not_speech = 0.0  # for the last phrase heard asleep: how likely it was noise
        self.ignored = ""      # and what it was taken for, if it was ignored as noise
        self.wake_name = config.WAKE_MODEL
        self.dictation_name = ""
        self._model(self.wake_name)
        self.use(dictation_model or config.AWAKE_MODEL)

    def _model(self, name: str):
        if name not in self._loaded:
            from faster_whisper import WhisperModel
            self._loaded[name] = WhisperModel(
                os.path.join(config.MODEL_DIR, name),
                device="cpu", compute_type="int8", cpu_threads=config.THREADS,
            )
        return self._loaded[name]

    def use(self, name: str) -> None:
        """Switch the dictation model. Raises if it can't be loaded, leaving the old one."""
        self._model(name)
        old, self.dictation_name = self.dictation_name, name
        if old and old not in (name, self.wake_name):
            del self._loaded[old]  # free its memory

    def transcribe(self, audio, awake: bool, prompt: str = "") -> str:
        if not awake:
            if len(audio) > config.WAKE_MAX_SECONDS * config.RATE:
                return ""  # too long to be "wake up": a video playing, or a conversation
            # Whisper's own filtering is off here, because it once threw away a real
            # "wake up" on a noisy microphone. No hint towards the phrase is given either:
            # with one, hiss and bumps were written down as "Wake up." What is kept is
            # the model's own estimate of whether it heard speech at all.
            segments, _ = self._model(self.wake_name).transcribe(
                audio, language="en", beam_size=config.BEAM,
                condition_on_previous_text=False, without_timestamps=True,
                no_speech_threshold=None,
            )
            segments = list(segments)
            text = " ".join(s.text.strip() for s in segments).strip()
            self.not_speech = max((s.no_speech_prob for s in segments), default=1.0)
            self.ignored = text if self.not_speech > config.WAKE_NO_SPEECH else ""
            return "" if self.ignored else text
        segments, _ = self._model(self.dictation_name).transcribe(
            audio, language="en", beam_size=config.BEAM,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=prompt or None,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        )
        parts = []
        for s in segments:
            text = s.text.strip()
            if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:
                continue
            plain = text.lower().strip(" .!?,")
            if plain in PHANTOMS and s.avg_logprob < -0.5:
                continue
            parts.append(text)
        return " ".join(parts).strip()


class Engine:
    """Owns the state. `on_change` is called from worker threads on every change."""

    def __init__(self, on_change=lambda: None, transcriber=None):
        self.status = Status()
        self.on_change = on_change
        self.on_event = lambda name: None  # "wake" or "sleep", for notifications
        self.on_level = lambda: None  # the level meter changed
        self.boost = config.DEFAULT_BOOST
        self.settings = Settings.load()
        mail = MailBridge(config.MAIL_PORT) if config.MAIL else None
        if mail is not None and not mail.start():
            log(f"port {config.MAIL_PORT} is in use: dictation into Thunderbird is off")
            mail = None
        editor = None
        if config.EDITOR:
            try:
                from .editor_target import EditorTarget
                editor = EditorTarget(lambda: self.settings.enabled("other_apps"))
            except Exception as e:  # the accessibility library isn't installed
                log(f"dictation into Kate is off: {e}")
        self.targets = Targets(mail, editor, VSCodeTarget() if config.VSCODE else None)
        self.lexicon = Lexicon.load_default()
        self.keep_final = os.environ.get("LS_KEEP_FINAL") == "1"
        self._transcriber = transcriber
        self.status.ready = transcriber is not None
        self._phrases: queue.Queue = queue.Queue()
        self._recorder = None
        self._lock = threading.Lock()
        self._choice_timer = None
        self._explained_at = -60.0
        self._names_at = 0.0
        self._names_list = []
        self._scope = {}
        self._running = True
        self.apply_accessibility()
        threading.Thread(target=self._work, daemon=True).start()

    # ---- on / off -------------------------------------------------------
    def turn_on(self, awake: bool = False) -> None:
        with self._lock:
            if self._recorder is not None:
                return
            self._recorder = subprocess.Popen(
                RECORD_COMMAND,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            recorder = self._recorder
        self._set(State.AWAKE if awake else State.ASLEEP)
        threading.Thread(target=self._listen, args=(recorder,), daemon=True).start()

    def turn_off(self, remember: bool = True) -> None:
        self._stop_choosing()  # don't leave numbers showing in the document
        with self._lock:
            recorder, self._recorder = self._recorder, None
        if recorder is not None:
            recorder.terminate()
        self._set(State.OFF, remember)

    def wake(self) -> None:
        if self.status.state is State.OFF:
            self.turn_on(awake=True)
        else:
            self._set(State.AWAKE)
        self.on_event("wake")

    def sleep(self) -> None:
        self._stop_choosing()
        self.status.spelling = False
        if self.status.state is not State.OFF:
            self._set(State.ASLEEP)
            self.on_event("sleep")

    def quit(self) -> None:
        self._running = False
        self.turn_off(remember=False)  # quitting isn't the same as switching off

    def _set(self, state: State, remember: bool = True) -> None:
        if state is not self.status.state:
            log(f"state {state.value.lower()}")
        self.status.state = state
        if remember:
            self._save()
        self.on_change()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(config.STATE_FILE), exist_ok=True)
            with open(config.STATE_FILE, "w") as f:
                f.write("off" if self.status.state is State.OFF else "on")
        except OSError:
            pass

    # ---- microphone -----------------------------------------------------
    def _listen(self, recorder) -> None:
        segmenter = Segmenter(SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO))
        loudest, count, best = 0.0, 0, 0
        clip_at = config.CLIP_LEVEL * 32767
        clipped, loud_for = False, 0  # `loud_for` holds the warning for a second
        preroll = collections.deque(maxlen=config.PREROLL_FRAMES)
        phrase = []
        nbytes = config.FRAME * 2
        while True:
            data = recorder.stdout.read(nbytes)
            if len(data) < nbytes:
                break
            # The audio itself is kept untouched, so it can't be clipped. The boost only
            # scales the loudness numbers that the pause detector works with.
            frame = np.frombuffer(data, dtype=np.int16)
            level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * self.boost
            loudest, count = max(loudest, level), count + 1
            if int(np.max(np.abs(frame.astype(np.int32)))) >= clip_at:
                clipped = True
            if count == 10:  # five times a second
                meter, db = meter_value(loudest, segmenter.noise)
                step = min(config.LEVEL_STEPS, round(meter / 100 * config.LEVEL_STEPS))
                loudest, count = 0.0, 0
                if segmenter.in_phrase:
                    best = max(best, db)
                loud_for = 5 if clipped else max(0, loud_for - 1)
                clipped = False
                loud = loud_for > 0
                if (step != self.status.level or meter != self.status.meter
                        or loud != self.status.loud):
                    self.status.level, self.status.meter, self.status.loud = step, meter, loud
                    self.on_level()
            event = segmenter.feed(level)
            if event == START:
                best = 0
                phrase = list(preroll)
                self._hearing(True)
            if segmenter.in_phrase or event == END:
                phrase.append(frame)
            else:
                preroll.append(frame)
            if event == END:
                audio = np.concatenate(phrase).astype(np.float32) / 32768.0
                phrase = []
                preroll.clear()
                self.status.voice_db = best
                self._phrases.put(("audio", audio))
        self.status.level = self.status.meter = 0
        self.status.loud = False
        self.on_level()
        if self._recorder is recorder:  # the recorder died by itself
            self.turn_off()

    def _hearing(self, on: bool) -> None:
        if on and self.status.state is State.AWAKE:
            self.status.state = State.HEARING
            self.on_change()

    # ---- phrases --------------------------------------------------------
    def _work(self) -> None:
        # Load the speech models straight away. Anything said meanwhile waits in the queue.
        if self._transcriber is None:
            self._load(self.settings.model)
        elif not self.status.ready:
            self.status.ready = True
        self.on_change()
        while self._running:
            kind, item = self._phrases.get()
            try:
                if kind == "call":
                    item()
                elif self.status.state is not State.OFF:
                    self.handle_audio(item)
            except Exception as e:  # keep listening whatever happens
                self.status.last_heard = f"(error: {e})"
                self.on_change()

    def _load(self, model: str) -> None:
        """Load the speech models, or switch the dictation model. Runs on the worker."""
        self.status.ready = False
        self.on_change()
        try:
            if self._transcriber is None:
                try:
                    self._transcriber = Transcriber(model)
                except Exception as e:
                    if not model:
                        raise
                    log(f"could not load {model}: {e}; using the default")
                    self.settings.set_model("")
                    self._transcriber = Transcriber()
            else:
                self._transcriber.use(model or config.AWAKE_MODEL)
            log(f"ready, dictation model {self._transcriber.dictation_name}")
            self.on_event("ready")
        except Exception as e:
            self.status.last_heard = f"(could not load the speech model: {e})"
            log(f"loading failed: {e}")
        self.status.ready = self._transcriber is not None
        self.on_change()

    def setting_changed(self, key: str) -> None:
        """Called when a tick box in Settings is changed."""
        if key == "other_apps":
            self.apply_accessibility()

    def apply_accessibility(self) -> None:
        """Other programs only show their text boxes while desktop accessibility is on."""
        if config.EDITOR:
            said = accessibility.apply(self.settings.enabled("other_apps"))
            if said:
                log(said)

    def set_model(self, model: str) -> None:
        """Choose the dictation model. It is loaded in the background."""
        self.settings.set_model(model)
        self.status.ready = False
        self.on_change()
        self._phrases.put(("call", lambda: self._load(model)))

    def run_soon(self, action) -> None:
        """Run something on the worker, after anything already heard. For the tray's buttons."""
        self._phrases.put(("call", action))

    def handle_audio(self, audio) -> None:
        if self._transcriber is None:
            self._transcriber = Transcriber(self.settings.model)
        awake = self.status.awake
        prompt = ""
        if awake and self.status.spelling:
            self.status.state = State.THINKING
            self.on_change()
            prompt = spelling.PROMPT
        elif awake:
            self.status.state = State.THINKING
            self.on_change()
            context = self.targets.request({"op": "context"})
            self.status.writer_ready = bool(context.get("ok"))
            self.status.target = self.targets.name
            if self._coding(context) and coding.where(context.get("before", ""))[0] != "comment":
                prompt = coding.prompt(self._names(), self._scope)
            elif config.USE_CONTEXT and context.get("ok"):
                prompt = context.get("before", "")[-config.CONTEXT_CHARS:]
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        text = self._transcriber.transcribe(normalise(audio), awake, prompt)
        if not awake and os.environ.get("LS_LOG_PHRASES") == "1":
            # Short phrases are logged in full, to show how "wake up" gets misheard.
            heard = text or getattr(self._transcriber, "ignored", "")
            note = " (ignored as noise)" if not text and heard else ""
            likely = getattr(self._transcriber, "not_speech", 0.0)
            log(f"asleep, phrase of {len(audio) / config.RATE:.1f}s, peak {peak:.3f}, "
                f"{self.status.voice_db} dB above background, "
                + (f"heard {heard!r}" if len(heard.split()) <= 3 else f"{len(heard)} characters")
                + f"{note}, {likely:.0%} likely not speech")
        self.handle_text(text, awake)

    def handle_text(self, text: str, awake: bool) -> None:
        """Act on one transcribed phrase. Split out so it can be tested."""
        if self.status.choosing and text.strip():
            if self._choose(text):
                return
        action = interpret(text, awake, self.settings.disabled_commands())
        if self.status.spelling and awake and not (
                isinstance(action, Command) and action.name == "sleep"):
            self._spell(text)
            return
        if isinstance(action, Command) and action.name == "spell":
            self.status.last_heard = text
            self.status.spelling, self.status.spelled = True, ""
            log("spelling started")
            self._back_to_awake()
            return
        if isinstance(action, Command) and action.name == "wake":
            self.status.last_heard = "wake up"
            self.wake()
            return
        if isinstance(action, Command) and action.name == "sleep":
            self.status.last_heard = "go to sleep"
            self.sleep()
            return
        if isinstance(action, Command):
            self.status.last_heard = text
            # "Press enter" is the Enter key: a new paragraph.
            name = action.name
            reply = {"why": "unknown request"}
            if name == "delete_words":
                reply = self._delete_words(int(action.arg))
            elif is_move(name):
                before = after = "x"  # only the paragraph moves need the real text
                if name in ("para_end", "para_start"):
                    context = self.targets.request({"op": "context"})
                    if context.get("ok"):
                        before, after = context.get("before", ""), context.get("after", "")
                count = int(action.arg) if action.arg.isdigit() else 1
                reply = self.targets.request(
                    {"op": "move", "steps": move_steps(name, before, after, count)})
                if name == "delete_line" and reply.get("ok"):
                    # Where the line could only be selected, deleting it is a second step.
                    reply = self.targets.request({"op": "command", "name": "delete"})
            if reply.get("why") == "unknown request":  # not a move, or an older extension
                reply = self.targets.request({
                    "op": "command", "name": name, "arg": action.arg,
                    "nearest": not self.settings.enabled("choose_numbers"),
                })
            if name == "tab" and reply.get("why") == "unknown command":
                # Where there is no Tab command, a tab character does the same job.
                reply = self.targets.request({"op": "insert", "text": "\t"})
            if name == "press_enter" and reply.get("why") == "unknown command":
                # Where Enter isn't known as a command, it is a new paragraph.
                reply = self.targets.request({"op": "command", "name": "new_paragraph"})
            if reply.get("choices", 0) > 1:
                self._start_choosing(reply["choices"])
            self._note(reply)
            log(f"command {action.name}: {'ok' if reply.get('ok') else reply.get('why')}")
        elif isinstance(action, Dictation):
            self.status.last_heard = text
            reply = self._dictate(action.text)
            self._note(reply)
            log(f"dictation, {len(action.text)} characters: "
                f"{'ok' if reply.get('ok') else reply.get('why')}")
        if self.status.state in (State.THINKING, State.HEARING):
            self.status.state = State.AWAKE
        self.on_change()

    # ---- choosing between numbered matches ----------------------------------
    def _start_choosing(self, count: int) -> None:
        self.status.choosing = count
        self.status.last_heard += f"  (say a number, 1 to {count})"
        self._choice_timer = threading.Timer(config.CHOICE_SECONDS, self._stop_choosing)
        self._choice_timer.daemon = True
        self._choice_timer.start()

    def _stop_choosing(self) -> None:
        """Take the numbers away without choosing."""
        if self._choice_timer is not None:
            self._choice_timer.cancel()
            self._choice_timer = None
        if self.status.choosing:
            self.status.choosing = 0
            self.targets.broadcast({"op": "command", "name": "cancel_choices"})
            self.on_change()

    def _choose(self, text: str) -> bool:
        """Handle a phrase said while numbers are showing. True if it picked one."""
        n = choice(text, self.status.choosing)
        if n is None:
            self._stop_choosing()  # anything else cancels, then is handled as usual
            return False
        if self._choice_timer is not None:
            self._choice_timer.cancel()
            self._choice_timer = None
        self.status.choosing = 0
        self.status.last_heard = f"choose {n}"
        reply = self.targets.request({"op": "command", "name": "choose", "arg": str(n)})
        self._note(reply)
        log(f"command choose: {'ok' if reply.get('ok') else reply.get('why')}")
        if self.status.state in (State.THINKING, State.HEARING):
            self.status.state = State.AWAKE
        self.on_change()
        return True

    # ---- source code ----------------------------------------------------------------
    def _coding(self, context: dict) -> bool:
        """True if the cursor is in a C or C++ file and the coding commands are on."""
        return (context.get("language") in coding.LANGUAGES
                and self.settings.enabled("vscode_cpp") and not self.status.spelling)

    def _names(self) -> list:
        """The names in the file being edited, nearest the cursor first."""
        now = time.monotonic()
        if now - self._names_at > 2.0:
            reply = self.targets.request({"op": "symbols"})
            self._names_list = reply.get("names", []) if reply.get("ok") else []
            # What the editor's C/C++ language server says is in scope at the cursor.
            self._scope = {item["name"]: item["kind"] for item in reply.get("scope", [])
                           if isinstance(item, dict) and "name" in item}
            self._names_at = now
        return self._names_list

    def _delete_words(self, count: int) -> dict:
        """Delete the last words before the cursor, using the backspace command."""
        context = self.targets.request({"op": "context"})
        if not context.get("ok"):
            return context
        length = last_words_length(context.get("before", ""), count)
        if not length:
            return {"ok": False, "why": "no word before the cursor"}
        reply = {"ok": True}
        while length > 0 and reply.get("ok"):  # backspace takes at most 99 at a time
            step = min(length, 99)
            reply = self.targets.request({"op": "command", "name": "backspace", "arg": str(step)})
            length -= step
        return reply

    def _back_to_awake(self) -> None:
        if self.status.state in (State.THINKING, State.HEARING):
            self.status.state = State.AWAKE
        self.on_change()

    # ---- spelling a word, letter by letter ------------------------------------------
    def _spell(self, text: str) -> None:
        steps, unknown = spelling.parse(text)
        self.status.spelled, outcome = spelling.apply(self.status.spelled, steps)
        self.status.last_heard = text + (
            f"  (not a letter: {' '.join(unknown)})" if unknown else "")
        if outcome:
            self.finish_spelling(outcome == "done")
        else:
            self._back_to_awake()

    def finish_spelling(self, insert: bool) -> None:
        """Close the spelling box, putting the word in the document if `insert`."""
        word, self.status.spelled = self.status.spelled, ""
        self.status.spelling = False
        self.on_change()  # closes the box
        if insert and word.strip():
            # The box may have taken the keyboard. Give the desktop a moment to hand it
            # back to the document before typing.
            for _ in range(30):
                self.targets.pick()
                if self.targets.name:
                    break
                time.sleep(0.1)
            # Typed exactly as spelled: no punctuation words, and capitals only where said.
            reply = self._dictate(word, exact=True)
            self._note(reply)
            log(f"spelled word, {len(word)} characters: "
                f"{'ok' if reply.get('ok') else reply.get('why')}")
        else:
            log("spelling cancelled")
        self._back_to_awake()

    def _dictate(self, raw: str, exact: bool = False) -> dict:
        """Fit a phrase to the text around the cursor, then have Writer insert it.

        The fitting is done here, not in the extension, so changes to the rules and
        settings never need LibreOffice to be restarted.
        """
        spoken_off = [p for p, _ in SPOKEN] if exact else self.settings.spoken_off()
        context = self.targets.request({"op": "context"})
        if not context.get("ok"):
            return context
        before, after = context.get("before", ""), context.get("after", "")
        place, comment = coding.where(before) if self._coding(context) and not exact else ("", "")
        if place in ("code", "string"):
            # Source code has its own rules, and knows the names already in the file.
            ins = coding.fit_code(raw, before, after, self._names(), self._scope)
        else:
            # Prose, including a comment in a source file, which starts after its "//".
            ins = fit(raw, comment if place == "comment" else before, after,
                      self.lexicon, keep_final=self.keep_final, spoken_off=spoken_off)
        text = ins.text
        if context.get("selected"):
            # Spoken over a selection, the words take its place. The spacing around it
            # was already right for what was there, so none is added.
            text = text.strip(" ")
        if exact and any(c.isupper() for c in raw):
            at = text.lower().find(raw.lower())  # keep the capitals exactly as spelled
            if at >= 0:
                text = text[:at] + raw + text[at + len(raw):]
        reply = self.targets.request({
            "op": "insert", "text": text, "delete_before": ins.delete_before,
            "delete_after": ins.delete_after, "capitalise_next": ins.capitalise_next,
        })
        if reply.get("why") == "unknown request":  # an extension from before "insert"
            reply = self.targets.request({"op": "dictate", "text": raw, "spoken_off": spoken_off})
        return reply

    def _note(self, reply: dict) -> None:
        self.status.writer_ready = bool(reply.get("ok")) or reply.get("why") not in (
            "writer not running", "writer not focused", "no writer document",
            "mail not running", "mail not focused", "mail not answering",
            "editor not focused",
        )
        self.status.target = self.targets.name
        if not reply.get("ok") and reply.get("why"):
            self.status.last_heard += f"  ({reply['why']})"
        if reply.get("why") in ("writer not running", "writer not focused", "no writer document"):
            # Nothing was in front to type into. Say what each program answered, at most
            # twice a minute, so the log shows why.
            now = time.monotonic()
            if now - self._explained_at > 30:
                self._explained_at = now
                log("nothing to type into. " + self.targets.describe())


def saved_on() -> bool:
    """Whether dictation was on when it last ran. On, the first time."""
    try:
        with open(config.STATE_FILE) as f:
            return f.read().strip() != "off"
    except OSError:
        return True
