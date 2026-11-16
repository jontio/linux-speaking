"""The speech engine: microphone, pause detection, Whisper, and what to do with each phrase."""
from __future__ import annotations

import collections
import math
import os
import queue
import secrets
import threading
import time

import numpy as np

from . import __version__, client, config
from .commands import (
    MOVES, Command, Dictation, choice, interpret, is_cancel, is_move, last_words_length,
    move_steps,
)
from .formatting import SPOKEN, fit
from .mailbridge import MailBridge
from .targets import Targets
from .vscode_target import VSCodeTarget
from .words import Lexicon, repetitive
from .settings import Settings, available_models
from .segmenter import END, START, Segmenter, SegmenterConfig
from .selecting import variants
from . import (accessibility, audio, coding, endings, models, opinions, quick, remote, spelling,
               vocabulary, voicetest)
from .status import State, Status



def log(message: str) -> None:
    """One line to the service log. Dictated text is never logged, only its length."""
    print(message, flush=True)


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


SHORT_WINDOW_FRAMES = 1000  # ten seconds of sound, as Whisper counts it
GUEST_MODELS = 3            # how many models are kept loaded for other computers


def shown(model: str, prompt: str) -> str:
    """The text a model is shown as what came before: none at all for a Distil model.

    The Distil models were made without ever being shown earlier text. Given some, they
    lose their place: on one real recording Distil medium got 125 words in 266 wrong with
    the text before the cursor and 6 without it. Whisper's own models take it in their
    stride.
    """
    return "" if "distil" in model.lower() else prompt


class Transcriber:
    """The recogniser. One model listens for "wake up", and one, chosen in Settings, takes
    dictation.

    Most models are Whisper. A transducer such as Parakeet can take dictation too: it is
    quicker, but it can't be shown the text before the cursor or be given words to
    expect. So "wake up", spelling and source code, which lean on those, always go to
    Whisper.
    """

    def __init__(self, dictation_model: str = ""):
        self._loaded = {}  # folder name -> model, so a model used for both is loaded once
        # One piece of listening at a time: this computer's own, or one done for another
        # computer that has been let in (see remote.py).
        self.lock = threading.RLock()
        self._guests = []  # models loaded because another computer asked: latest last
        self.quick = False  # give Whisper only as much sound as the phrase needs: see quick.py
        self.not_speech = 0.0  # for the last phrase heard asleep: how likely it was noise
        self.ignored = ""      # and what it was taken for, if it was ignored as noise
        self.wake_name = config.WAKE_MODEL
        self._short_window = True  # until it turns out this library can't do it
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

    def _transducer(self, name: str):
        if name not in self._loaded:
            import sherpa_onnx
            folder = os.path.join(config.MODEL_DIR, name)
            self._loaded[name] = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=os.path.join(folder, "encoder.int8.onnx"),
                decoder=os.path.join(folder, "decoder.int8.onnx"),
                joiner=os.path.join(folder, "joiner.int8.onnx"),
                tokens=os.path.join(folder, "tokens.txt"),
                num_threads=config.THREADS, model_type="nemo_transducer",
            )
        return self._loaded[name]

    def _is_transducer(self, name: str) -> bool:
        return models.kind(config.MODEL_DIR, name) == "transducer"

    def _by_transducer(self, name: str, audio) -> str:
        recogniser = self._transducer(name)
        stream = recogniser.create_stream()
        stream.accept_waveform(config.RATE, audio)
        recogniser.decode_stream(stream)
        return stream.result.text.strip()

    def use(self, name: str) -> None:
        """Switch the dictation model. Raises if it can't be loaded, leaving the old one."""
        with self.lock:
            (self._transducer if self._is_transducer(name) else self._model)(name)
            old, self.dictation_name = self.dictation_name, name
            if old and old not in (name, self.wake_name, *self._guests):
                del self._loaded[old]  # free its memory

    def answer(self, header: dict, audio) -> dict:
        """One piece of listening done for another computer: see remote.py."""
        started = time.monotonic()
        with self.lock:
            if header.get("kind") == "alone":
                text, model, awake = self.hear_alone(audio), self.wake_name, True
            else:
                awake = bool(header.get("awake", True))
                model = self._guest_model(header) if awake else self.wake_name
                exact = bool(header.get("exact", False))
                if awake and exact and self._is_transducer(model):
                    model = self.wake_name  # what leans on the prompt is Whisper's work
                text = self.transcribe(audio, awake, str(header.get("prompt", "")), model,
                                       quick=bool(header.get("quick", False)), exact=exact)
            return {"ok": True, "text": text, "model": model,
                    "not_speech": 0.0 if awake else self.not_speech,
                    "ignored": "" if awake else self.ignored,
                    "seconds": round(time.monotonic() - started, 2)}

    def _guest_model(self, header: dict) -> str:
        """The model to use for another computer: the one it asked for if it is installed
        here, else the first of its other choices that is, else this computer's own.

        Three models are kept loaded for guests, besides this computer's own two: a
        guest that wants second opinions on a phrase asks for three in turn.
        """
        installed = {name for name, _ in available_models(config.MODEL_DIR)}
        others = header.get("otherwise", [])
        wanted = [header.get("model", "")] + (list(others) if isinstance(others, list) else [])
        name = next((m for m in wanted if isinstance(m, str) and m in installed),
                    self.dictation_name)
        own = (self.dictation_name, self.wake_name)
        if name not in own:
            if name in self._guests:
                self._guests.remove(name)
            self._guests.append(name)
            while len(self._guests) > GUEST_MODELS:
                old = self._guests.pop(0)
                if old not in own:
                    self._loaded.pop(old, None)
        return name

    def hear_with(self, name: str, audio, prompt: str = "", quick: bool = False) -> str:
        """`audio` as the model `name` hears it, whichever model is in use. For the voice
        test, which tries them all."""
        with self.lock:
            if self._is_transducer(name):
                return self._by_transducer(name, audio)
            return self._transcribe(audio, True, prompt, name, quick)

    def release(self, name: str) -> None:
        """Forget a model loaded by hear_with, unless it is one in use."""
        with self.lock:
            if name not in (self.dictation_name, self.wake_name, *self._guests):
                self._loaded.pop(name, None)

    def hear_alone(self, audio) -> str:
        """A second or so of sound by itself, with only the sound to go on. The model
        that listens for "wake up" does it: short phrases alone are its work.

        Whisper takes in half a minute of sound however little there is, and that is
        most of the time it takes. Given ten seconds it hears a short clip just the same
        in a quarter of the time. Given much less it starts to repeat itself.
        """
        with self.lock:
            model = self._model(self.wake_name)
            if self._short_window:
                try:
                    return self._hear_short(model, audio)
                except Exception as e:  # an older library that insists on the half minute
                    self._short_window = False
                    log(f"the short listening window isn't available: {e}")
            segments, _ = model.transcribe(
                audio, language="en", beam_size=config.BEAM,
                condition_on_previous_text=False, without_timestamps=True,
            )
            return " ".join(s.text.strip() for s in segments).strip()

    def _hear_short(self, model, audio) -> str:
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.tokenizer import Tokenizer
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                              task="transcribe", language="en")
        prompt = model.get_prompt(tokenizer, [], without_timestamps=True)
        features = pad_or_trim(model.feature_extractor(audio), SHORT_WINDOW_FRAMES)
        result = model.model.generate(model.encode(features), [prompt],
                                      beam_size=config.BEAM, max_length=32)[0]
        return tokenizer.decode(result.sequences_ids[0]).strip()

    def transcribe(self, audio, awake: bool, prompt: str = "", model: str = "",
                   quick=None, exact: bool = False) -> str:
        """The words in `audio`. `model` and `quick` are for a guest that says which
        model it wants and whether to try the quick way; left out, this computer's own
        choices are used. `exact` is for listening that depends on the prompt, such as
        spelled letters: it is always done by Whisper."""
        with self.lock:
            model = model or self.dictation_name
            if awake and self._is_transducer(model):
                if not exact:
                    return self._by_transducer(model, audio)
                model = self.wake_name
            return self._transcribe(audio, awake, prompt, model,
                                    self.quick if quick is None else quick)

    def _quick_try(self, model: str, audio, prompt: str):
        """The words, heard the quick way, or None if it has to be done the usual way."""
        seconds = len(audio) / config.RATE
        frames = quick.window_frames(len(audio), config.RATE)
        if frames >= quick.FULL or not quick.install():
            return None
        try:
            with quick.window(frames):
                segments, _ = self._model(model).transcribe(
                    audio, language="en", beam_size=1,
                    condition_on_previous_text=False, without_timestamps=True,
                    initial_prompt=shown(model, prompt) or None,
                    vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                    temperature=0.0, max_new_tokens=quick.token_limit(seconds),
                )
                segments = list(segments)  # the listening happens here, inside the window
        except ValueError:  # the text before the cursor left no room for the answer
            return None
        text = self._kept(segments)
        problem = "Whisper was unsure" if quick.unsure(segments) else quick.runaway(text, seconds)
        if problem:
            log(f"quick listen set aside ({problem}): done the usual way")
            return None
        return text

    @staticmethod
    def _kept(segments) -> str:
        """The words of `segments`, without the ones Whisper makes up out of silence."""
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

    def _transcribe(self, audio, awake: bool, prompt: str, model: str, quickly: bool) -> str:
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
        if quickly:
            text = self._quick_try(model, audio, prompt)
            if text is not None:
                return text
        segments, _ = self._model(model).transcribe(
            audio, language="en", beam_size=config.BEAM,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=shown(model, prompt) or None,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
        )
        return self._kept(segments)


class Engine:
    """Owns the state. `on_change` is called from worker threads on every change."""

    def __init__(self, on_change=lambda: None, transcriber=None):
        self.status = Status()
        self.on_change = on_change
        self.on_event = lambda name: None  # "ready", "wake", "sleep" or "off", for notices
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
        office = None
        if config.OFFICE:
            try:
                from .word_target import WordTarget
                office = WordTarget()
            except Exception as e:
                log(f"dictation into Word and Outlook is off: {e}")
        other = None
        if config.OTHER:
            try:
                from .keys_target import KeysTarget
                other = KeysTarget(lambda: self.settings.enabled("other_apps"))
            except Exception as e:
                log(f"dictation into other programs is off: {e}")
        elif config.WEB:
            try:
                from .web_target import WebBoxTarget
                other = WebBoxTarget(lambda: self.settings.enabled("other_apps"))
            except Exception as e:
                log(f"dictation into web pages and VS Code's panels is off: {e}")
        self.targets = Targets(mail, editor, VSCodeTarget() if config.VSCODE else None, office,
                               other)
        self.lexicon = Lexicon.load_default()
        self.keep_final = os.environ.get("LS_KEEP_FINAL") == "1"
        self._transcriber = transcriber
        self.status.ready = transcriber is not None
        self._phrases: queue.Queue = queue.Queue()
        self._recorder = None
        self._lock = threading.Lock()
        self._choice_timer = None
        self._explained_at = -60.0
        self._selected_that = False  # the last thing done was "select that" or "correct that"
        self._held = ""  # "awake" or "asleep" while listening is stopped for a recording
        self._names_at = 0.0
        self._names_list = []
        self._scope = {}
        self._running = True
        self._offload = None       # another computer that does the listening: see remote.py
        self._server = None        # other computers using this one's recogniser
        self._share_timer = None
        self.share_problem = ""
        self._apply_remote()
        self._apply_sharing()
        self.apply_accessibility()
        threading.Thread(target=self._work, daemon=True).start()

    # ---- on / off -------------------------------------------------------
    def turn_on(self, awake: bool = False) -> None:
        with self._lock:
            if self._recorder is not None:
                return
            try:
                self._recorder = audio.open_microphone(self.settings.microphone)
            except Exception as e:
                log(f"could not open the microphone: {e}")
                self.status.last_heard = f"(could not open the microphone: {e})"
                self.on_change()
                return
            recorder = self._recorder
        self._set(State.AWAKE if awake else State.ASLEEP)
        threading.Thread(target=self._listen, args=(recorder,), daemon=True).start()

    def turn_off(self, remember: bool = True) -> None:
        """Stop listening. `remember` is off when it is only for a moment (the microphone
        is being changed, a recording made) or the program is closing: then nothing is
        kept and nobody is told."""
        self._stop_choosing()  # don't leave numbers showing in the document
        was_on = self.status.state is not State.OFF
        with self._lock:
            recorder, self._recorder = self._recorder, None
        if recorder is not None:
            recorder.close()
        self._set(State.OFF, remember)
        if remember and was_on:
            self.on_event("off")

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
        self._apply_sharing()  # stops answering other computers
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
            data = recorder.read(nbytes)
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
            # Not the person's doing, so it isn't kept as their choice. When the service
            # is stopped the recorder is stopped first, and keeping "off" then meant
            # dictation came back switched off after every restart.
            self.turn_off(remember=False)
            self.on_event("off")

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
        if self._offload is not None:
            self._offload.otherwise = self._otherwise()
        self.status.ready = False
        self.on_change()
        self._phrases.put(("call", lambda: self._load(model)))

    def set_microphone(self, name: str) -> None:
        """Choose the recording device (Windows). Listening restarts on the new one."""
        self.settings.set_microphone(name)
        log("microphone changed")
        if self.status.state is not State.OFF:
            awake = self.status.awake
            self.turn_off(remember=False)
            self.turn_on(awake=awake)

    def set_words(self, text: str) -> None:
        """Set the person's own words, from what was typed into Settings."""
        words = vocabulary.parse(text)
        if words != self.settings.words:
            self.settings.set_words(words)
            log(f"own words changed: {len(words)}")

    # ---- another computer doing the listening, and others using this one ------------
    def _ears(self):
        """What does the listening: this computer's recogniser, or another computer's.
        Both are told here whether the quick way is switched on."""
        ears = self._offload if self._offload is not None else self._transcriber
        quickly = self.settings.enabled("quick_listening")
        for each in (ears, self._transcriber):
            if hasattr(each, "quick"):
                each.quick = quickly
        return ears

    def _otherwise(self) -> tuple:
        """The models to ask the other computer for if it hasn't the one chosen for it."""
        return (self.settings.model or config.AWAKE_MODEL, config.AWAKE_MODEL)

    def _apply_remote(self) -> None:
        """Set up, or drop, the other computer that does the listening."""
        chosen = self.settings.remote
        self._offload = None
        self.status.listening_on = ""
        if chosen["on"] and chosen["address"] and chosen["key"]:
            try:
                other = remote.Client(chosen["address"], chosen["key"])
            except remote.RemoteError as e:
                log(f"another computer for recognition: {e}")
            else:
                self._offload = remote.Offload(
                    lambda: self._transcriber, other, chosen["model"], self._otherwise(),
                    wake=chosen["wake"], on_where=self._listening_moved)
                self.status.listening_on = other.host
        self.on_change()

    def _listening_moved(self, there: bool, problem: str) -> None:
        """Called when the listening moves to the other computer or back to this one."""
        offload = self._offload
        if offload is None:
            return
        self.status.listening_on = (
            offload.client.host if there else "this computer: the other can't be reached")
        log("recognition on the other computer" if there
            else f"recognition on this computer. {problem}")
        self.on_change()

    def set_remote(self, on: bool, address: str, key: str, model: str, wake: bool) -> None:
        """Choose another computer to do the listening. From the Settings window."""
        self.settings.set_remote(on=on, address=address, key=key, model=model, wake=wake)
        log("another computer for recognition: " + ("on" if self.settings.remote["on"] else "off"))
        self._apply_remote()

    def check_remote(self) -> dict:
        """Ask the other computer what it offers. Waits for the answer, so not for the
        thread that draws the windows. {"ok": True, "models": [[name, label], ...],
        "model": its own choice} or {"ok": False, "why": ...}."""
        chosen = self.settings.remote
        if not chosen["address"] or not chosen["key"]:
            return {"ok": False, "why": "Fill in the address and the key first."}
        try:
            answer = remote.Client(chosen["address"], chosen["key"]).status()
        except remote.RemoteError as e:
            return {"ok": False, "why": str(e)}
        models = [pair for pair in answer.get("models", [])
                  if isinstance(pair, list) and len(pair) == 2]
        return {"ok": True, "models": models, "model": str(answer.get("model", "")),
                "version": str(answer.get("version", ""))}

    def set_sharing(self, on: bool) -> None:
        """Let other computers use this one's recogniser, or stop. The key is made the
        first time and kept, so computers already set up carry on working."""
        self.settings.set_share(on=on, key=self.settings.share["key"] or secrets.token_hex(16))
        log("sharing the recogniser: " + ("on" if on else "off"))
        self._apply_sharing()

    def _apply_sharing(self) -> None:
        if self._share_timer is not None:
            self._share_timer.cancel()
            self._share_timer = None
        if self._server is not None:
            self._server.stop()
            self._server = None
        share = self.settings.share
        if not (share["on"] and share["key"] and self._running):
            self.share_problem = ""
            return
        server = remote.Server(config.SHARE_ADDRESS, config.SHARE_PORT, share["key"],
                               self._hear_for_guest, self._describe)
        try:
            server.start()
        except OSError as e:
            # The port is taken, or at login the network isn't up yet. Keep trying.
            problem = f"can't answer on port {config.SHARE_PORT}: {e.strerror or e}"
            if problem != self.share_problem:
                log(f"sharing the recogniser: {problem}")
            self.share_problem = problem
            self._share_timer = threading.Timer(30, self._apply_sharing)
            self._share_timer.daemon = True
            self._share_timer.start()
            return
        self._server, self.share_problem = server, ""
        log(f"sharing the recogniser on port {server.port}")

    def _hear_for_guest(self, header: dict, sound) -> dict:
        """One piece of listening for another computer. Runs on the server's thread."""
        transcriber = self._transcriber
        if transcriber is None or not hasattr(transcriber, "answer"):
            return {"ok": False, "why": "still loading"}
        return transcriber.answer(header, sound)

    def _describe(self) -> dict:
        return {"version": __version__,
                "models": [list(pair) for pair in available_models(config.MODEL_DIR)],
                "model": getattr(self._transcriber, "dictation_name", "")}

    # ---- trying each recogniser on the person's own voice: see voicetest.py -----------
    def hold(self) -> None:
        """Stop listening while a recording is made, so that what is read aloud isn't
        typed anywhere. unhold() puts things back as they were."""
        if self.status.state is not State.OFF:
            self._held = "awake" if self.status.awake else "asleep"
            self.turn_off(remember=False)

    def unhold(self) -> None:
        held, self._held = self._held, ""
        if held:
            self.turn_on(awake=held == "awake")

    def test_candidates(self, both_ways: bool) -> list:
        """Every recogniser the voice test can try: this computer's models, and the
        other computer's if one is set up and answers. Waits for that answer. Whisper is
        tried the way it is set to be used, or both ways."""
        here = available_models(config.MODEL_DIR)
        there = []
        if self.settings.remote["address"] and self.settings.remote["key"]:
            answer = self.check_remote()
            there = [tuple(pair) for pair in answer.get("models", [])] if answer.get("ok") else []
        quickly = self.settings.enabled("quick_listening")
        found = voicetest.candidates(
            here, there, (True, False) if both_ways else (quickly,),
            # The other computer's models are told apart by name, this one's by their files.
            lambda where, name: ("parakeet" not in name.lower() if where == "there"
                                 else models.kind(config.MODEL_DIR, name) != "transducer"))
        return found + voicetest.teams(found)

    def test_hear(self, candidate, sound, written: str) -> str:
        """One phrase heard by one recogniser, for the voice test."""
        sound = normalise(sound)
        if candidate.where == "there":
            chosen = self.settings.remote
            reply = remote.Client(chosen["address"], chosen["key"]).hear(
                "phrase", sound, True, written, candidate.name, (), candidate.quick)
            if reply.get("model") != candidate.name:
                raise remote.RemoteError("The other computer no longer has this model.")
            return str(reply.get("text", ""))
        if self._transcriber is None or not hasattr(self._transcriber, "hear_with"):
            raise RuntimeError("the speech models are still loading")
        return self._transcriber.hear_with(candidate.name, sound, written, candidate.quick)

    def test_done(self, candidate) -> None:
        """Free the models the voice test loaded for a recogniser."""
        for member in candidate.team or (candidate,):
            if member.where == "here" and hasattr(self._transcriber, "release"):
                self._transcriber.release(member.name)

    def run_soon(self, action) -> None:
        """Run something on the worker, after anything already heard. For the tray's buttons."""
        self._phrases.put(("call", action))

    def handle_audio(self, audio) -> None:
        if self._transcriber is None:
            self._transcriber = Transcriber(self.settings.model)
        awake = self.status.awake
        prompt = hint = before = ""
        prose = False
        exact = {}  # {"exact": True} when the listening leans on the prompt: see Transcriber
        if awake and self.status.spelling:
            self.status.state = State.THINKING
            self.on_change()
            prompt = spelling.PROMPT
            exact = {"exact": True}
        elif awake:
            self.status.state = State.THINKING
            self.on_change()
            context = self.targets.request({"op": "context"})
            self.status.writer_ready = bool(context.get("ok"))
            self._typing_into(self.targets.name)
            if self._coding(context) and coding.where(context.get("before", ""))[0] != "comment":
                prompt = coding.prompt(self._names(), self._scope)
                exact = {"exact": True}
            else:
                if context.get("ok"):
                    before = context.get("before", "")
                if config.USE_CONTEXT:
                    prompt = before[-config.CONTEXT_CHARS:]
                    if repetitive(prompt):
                        prompt = ""  # Whisper would carry on repeating it
                hint = vocabulary.hint(self.settings.words)
                prose = True
        peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
        sound = normalise(audio)
        ears = self._ears()
        text = ears.transcribe(sound, awake, hint + prompt, **exact)
        if hint and vocabulary.mentions(text, self.settings.words):
            # The hint is strong enough to turn an ordinary word into one of the person's
            # own. Hear it again without, and keep their word only where it fits.
            plain = ears.transcribe(sound, awake, prompt)
            settled = vocabulary.settle(text, plain, before, self.settings.words, self.lexicon)
            log("own word heard: " + ("kept" if vocabulary.mentions(
                settled, self.settings.words) else "an ordinary word after all"))
            text = settled
        elif hint and text:
            # The hint brought none of the person's words: a recogniser that can't take a
            # hint, or one that didn't follow it. Put one in where what was written
            # sounds like it and a name fits.
            text = vocabulary.by_sound(text, before, self.settings.words, self.lexicon)
        if prose and text and not self.status.choosing and self.settings.enabled("second_opinions"):
            text = self._checked(text, sound, prompt)
        if prose and endings.only_signs(text):
            text = self._lone_sign(text, sound)
        if prose and text:
            text = self._spoken_ending(text, sound)
        if not awake and os.environ.get("LS_LOG_PHRASES") == "1":
            # Short phrases are logged in full, to show how "wake up" gets misheard.
            heard = text or getattr(ears, "ignored", "")
            note = " (ignored as noise)" if not text and heard else ""
            likely = getattr(ears, "not_speech", 0.0)
            log(f"asleep, phrase of {len(audio) / config.RATE:.1f}s, peak {peak:.3f}, "
                f"{self.status.voice_db} dB above background, "
                + (f"heard {heard!r}" if len(heard.split()) <= 3 else f"{len(heard)} characters")
                + f"{note}, {likely:.0%} likely not speech")
        self.handle_text(text, awake)

    def _checked(self, text: str, sound, prompt: str) -> str:
        """`text` as a second recogniser lets it stand, or as a third settled it where the
        two differed. See opinions.py. They listen where the first did: on the other
        computer if it has them, else on this one."""
        offload = self._offload
        there = offload is not None and bool(offload.there)
        first = (offload.model_there if there else "") or getattr(
            self._transcriber, "dictation_name", "")
        said = sorted((phrase.split() for phrase, _ in SPOKEN), key=len, reverse=True)
        started = time.monotonic()
        text, outcome = opinions.checked(
            text, first, lambda name: self._hear_by(name, sound, prompt, there), said,
            lambda words: vocabulary.mentions(" ".join(words), self.settings.words))
        log(f"second opinion: {outcome}  ({time.monotonic() - started:.1f} s)")
        return text

    def _hear_by(self, name: str, sound, prompt: str, there: bool):
        """`sound` as the model `name` hears it: on the other computer if `there` and it
        has that model, else on this one. None if neither can."""
        quickly = self.settings.enabled("quick_listening")
        if there:
            try:
                reply = self._offload.client.hear("phrase", sound, True, prompt, name, (), quickly)
                if reply.get("model") == name:
                    return str(reply.get("text", ""))
            except remote.RemoteError:
                pass
        ears = self._transcriber
        if not hasattr(ears, "hear_with") or not models.is_installed(config.MODEL_DIR, name):
            return None
        if models.kind(config.MODEL_DIR, name) == "transducer" and not models.transducers_usable():
            return None
        return ears.hear_with(name, sound, prompt, quickly)

    def _lone_sign(self, text: str, sound) -> str:
        """The words for a phrase that came out as a sign and nothing else, such as "?"
        for "question mark" said by itself. See endings.said_alone."""
        off = set(self.settings.spoken_off())
        spoken = [(phrase, sign) for phrase, sign in SPOKEN if phrase not in off]
        hear_alone = getattr(self._ears(), "hear_alone", None)
        heard = hear_alone(sound) if hear_alone and len(sound) <= 6 * config.RATE else ""
        phrase = endings.said_alone(text, heard, spoken)
        log("only a sign was written: " + ("it was said as words" if phrase else "left out"))
        return phrase or text

    def _spoken_ending(self, text: str, sound) -> str:
        """`text`, with "question mark" or the like put back if it was said after a pause
        and Whisper wrote the sign instead of the words. See endings.py."""
        phrases = endings.end_phrases(self.settings.spoken_off())
        hear_alone = getattr(self._ears(), "hear_alone", None)
        if hear_alone is None or self.status.choosing or not endings.worth_checking(text, phrases):
            return text
        if not isinstance(interpret(text, True, self.settings.disabled_commands()), Dictation):
            return text  # a command, such as "scratch ... that"
        burst = endings.trailing_burst(sound, config.RATE)
        if burst is None:
            return text
        fixed = endings.with_phrase(text, hear_alone(endings.cut(sound, burst, config.RATE)), phrases)
        log("pause before the last words: "
            + ("punctuation was said there" if fixed else "they were ordinary words"))
        return fixed or text

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
            # "Press enter" is the Enter key: a new paragraph. So is "enter" by itself,
            # where that has been switched on.
            name = "press_enter" if action.name == "enter" else action.name
            reply = {"why": "unknown request"}
            if name == "delete_words":
                reply = self._delete_words(int(action.arg))
            elif name == "space":
                # The space bar, as many times as asked. Every program can do this, as it
                # is only text being put in.
                reply = self.targets.request({"op": "insert", "text": " " * int(action.arg or 1)})
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
            if (name == "select" and reply.get("why") == "can't find that"
                    and not reply.get("sounds_tried")):
                # A program that looks for the words itself looks for exactly those. Ask
                # again for the same numbers written the other way and for words that
                # sound the same: "two" may be "2" in the document.
                for other in variants(action.arg):
                    again = self.targets.request({
                        "op": "command", "name": name, "arg": other,
                        "nearest": not self.settings.enabled("choose_numbers"),
                    })
                    if again.get("ok"):
                        reply = again
                        break
            if name == "tab" and reply.get("why") == "unknown command":
                # Where there is no Tab command, a tab character does the same job.
                reply = self.targets.request({"op": "insert", "text": "\t"})
            if name == "press_enter" and reply.get("why") == "unknown command":
                # Where Enter isn't known as a command, it is a new paragraph.
                reply = self.targets.request({"op": "command", "name": "new_paragraph"})
            if reply.get("choices", 0) > 1:
                self._start_choosing(reply["choices"])
            self._selected_that = action.name == "select_last" and bool(reply.get("ok"))
            self._note(reply)
            log(f"command {action.name}: {outcome(reply)}")
        elif isinstance(action, Dictation):
            self.status.last_heard = text
            reply = self._dictate(action.text)
            self._note(reply)
            log(f"dictation, {len(action.text)} characters: "
                f"{outcome(reply)}")
        if self.status.state in (State.THINKING, State.HEARING):
            self.status.state = State.AWAKE
        self.on_change()

    # ---- choosing between numbered matches ----------------------------------
    def _start_choosing(self, count: int) -> None:
        self.status.choosing = count
        self.status.last_heard += f"  (say a number, 1 to {count}, or \"cancel\")"
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
            if not is_cancel(text):
                return False
            self.status.last_heard = "cancel"  # "cancel" itself is not typed
            log("command cancel: ok")
            if self.status.state in (State.THINKING, State.HEARING):
                self.status.state = State.AWAKE
            self.on_change()
            return True
        if self._choice_timer is not None:
            self._choice_timer.cancel()
            self._choice_timer = None
        self.status.choosing = 0
        self.status.last_heard = f"choose {n}"
        reply = self.targets.request({"op": "command", "name": "choose", "arg": str(n)})
        self._note(reply)
        log(f"command choose: {outcome(reply)}")
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
                f"{outcome(reply)}")
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
                      self.lexicon, keep_final=self.keep_final, spoken_off=spoken_off,
                      greeting_comma=exact or not self.settings.enabled("no_greeting_comma"))
        text = ins.text
        replacing_last, self._selected_that = self._selected_that, False
        edges = context.get("selected_edges")
        if context.get("selected") and not replacing_last:
            # Spoken over a selection, the words take its place, fitted to what is on
            # either side of it like any others: a double click in Word takes the space
            # after the word too, and the new word needs that space back.
            #
            # The one thing fitting gets wrong is a selection that starts or ends inside
            # a word: "ought" in "thought". There no space belongs. A program that says
            # how the selection starts and ends lets that be told; for one that doesn't,
            # no spaces are added, as it always was.
            #
            # After "correct that" the fitting is always right: the phrase it highlights
            # was put in whole.
            if isinstance(edges, (list, tuple)) and len(edges) == 2:
                first, last = (str(edge) for edge in edges)
                if before[-1:].isalnum() and first.isalnum():
                    text = text.lstrip(" ")
                if after[:1].isalnum() and last.isalnum():
                    text = text.rstrip(" ")
            else:
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

    def _typing_into(self, name: str) -> None:
        if name != self.status.target:
            log(f"typing into {name or 'nothing'}")
        self.status.target = name

    def _note(self, reply: dict) -> None:
        self.status.writer_ready = bool(reply.get("ok")) or reply.get("why") not in (
            "writer not running", "writer not focused", "no writer document",
            "mail not running", "mail not focused", "mail not answering",
            "editor not focused",
        )
        self._typing_into(self.targets.name)
        if not reply.get("ok") and reply.get("why"):
            self.status.last_heard += f"  ({reply['why']})"
        if reply.get("why") in ("writer not running", "writer not focused", "no writer document"):
            # Nothing was in front to type into. Say what each program answered, at most
            # twice a minute, so the log shows why.
            now = time.monotonic()
            if now - self._explained_at > 30:
                self._explained_at = now
                log("nothing to type into. " + self.targets.describe())


def outcome(reply: dict) -> str:
    """A reply in a word or two for the log, with the program's own error if it gave one."""
    if reply.get("ok"):
        return "ok"
    return f"{reply.get('why')}" + (f": {reply['error']}" if reply.get("error") else "")


def saved_on() -> bool:
    """Whether dictation was on when it last ran. On, the first time."""
    try:
        with open(config.STATE_FILE) as f:
            return f.read().strip() != "off"
    except OSError:
        return True
