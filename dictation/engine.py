"""The speech engine: microphone, pause detection, Whisper, and what to do with each phrase."""
from __future__ import annotations

import collections
import json
import math
import os
import queue
import secrets
import threading
import time

import numpy as np

from . import __version__, client, config
from .commands import (
    MOVES, SHORT_COMMANDS, Command, Dictation, choice, interpret, is_cancel, is_move,
    last_words_length, move_steps,
)
from .commands import normalise as plain_words
from .formatting import SPOKEN, fit
from .mailbridge import MailBridge, own_key
from .targets import Targets
from .vscode_target import VSCodeTarget
from .words import Lexicon, repetitive
from .settings import Settings, available_models, model_label
from .segmenter import END, FELL_AWAY, LIMIT, NO_VOICE, ROOM, START, Segmenter, SegmenterConfig
from .selecting import variants
from . import (accessibility, actions, audio, clicking, coding, endings, models, money, opinions, quick, remote,
               speech, spelling, training, vocabulary, voicetest)
from .status import State, Status



def log(message: str) -> None:
    """One line to the service log. Dictated text is never logged, only its length."""
    print(message, flush=True)


# Things Whisper invents from noise. Dropped unless Whisper is confident.
PHANTOMS = {"thank you", "thanks for watching", "you", "bye", "thank you very much"}


class _Scoring:
    """Stands in for a Whisper model's inner model while one piece of sound is heard, and
    finds out how likely Whisper thought each token it chose.

    The library gives no such figures when it searches for the best wording, which is how
    Whisper usually listens, and its switch for word probabilities makes it listen another
    way: several times slower, and writing things that weren't said. So the listening is
    left exactly as it is. Once the tokens are chosen, the library is asked to score those
    same tokens against the sound it has already taken in. `seconds` is what that scoring
    took, so that it can be left out of any timing.
    """

    def __init__(self, whisper):
        from faster_whisper.tokenizer import Tokenizer
        self._whisper, self._model = whisper, whisper.model
        tokenizer = Tokenizer(whisper.hf_tokenizer, self._model.is_multilingual,
                              task="transcribe", language="en")
        self._start, self._end = tokenizer.sot_sequence, tokenizer.eot
        self.takes = []     # voicetest.word_sureness() of each choosing
        self.seconds = 0.0

    def __getattr__(self, name):
        return getattr(self._model, name)

    def __enter__(self):
        self._whisper.model = self
        return self

    def __exit__(self, *_):
        self._whisper.model = self._model

    def generate(self, features, prompts, **options):
        results = self._model.generate(features, prompts, **options)
        started = time.monotonic()
        try:
            tokens = [token for token in results[0].sequences_ids[0] if token < self._end]
            if tokens:
                scored = self._model.align(features, self._start, [tokens], features.shape[1] * 2)[0]
                pieces = [self._whisper.hf_tokenizer.decode([token]) for token in tokens]
                self.takes.append(voicetest.word_sureness(
                    pieces, [math.log(max(float(p), 1e-9)) for p in scored.text_token_probs]))
            else:
                self.takes.append([])
        except Exception as e:  # the words still stand; only the sureness is lost
            log(f"whisper could not say how sure it was: {type(e).__name__}: {e}")
            self.takes.append(None)
        self.seconds += time.monotonic() - started
        return results

    def sureness(self, text: str):
        """[(word, how sure)] for the words of `text`, or None if it can't be told."""
        if any(take is None for take in self.takes):
            return None
        return voicetest.pieced_together(text, self.takes)


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


def from_pieces(result) -> str:
    """The words a Parakeet model wrote, put together from its own pieces.

    The library that runs the model joins the pieces into text itself, and leaves out a
    space that the model wrote as a piece of its own. The models do that before a dollar
    sign, so "I spent $120" came out as "I spent$120". Over some three hundred sentences
    with each of three models, that was the only difference between the two."""
    pieces = [str(piece) for piece in (getattr(result, "tokens", None) or ())]
    return " ".join("".join(pieces).split()) or str(getattr(result, "text", "")).strip()


def normalise(audio):
    """Turn a quiet phrase up so Whisper hears it at a normal level."""
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak <= 0:
        return audio
    return audio * min(config.NORMALISE_PEAK / peak, config.MAX_GAIN)


SHORT_WINDOW_FRAMES = 1000  # ten seconds of sound, as Whisper counts it
SHORT_SECONDS = 9.0         # sound up to this long goes through that window whole
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
    """The recogniser. The model chosen in Settings does the listening: dictation, the
    commands, and "wake up" while asleep. One rule, whichever model it is.

    Most models are Whisper. A transducer such as Parakeet is quicker, but it can't be
    shown the text before the cursor or be given words to expect. So with a Parakeet
    chosen, what leans on those goes to a Whisper model that is kept beside it for the
    purpose: the spelling box and the short second listen for punctuation to the helper
    (`helper_name`, Small), and source code to a bigger one where it is installed, which
    is loaded when code is first dictated and let go when none has been for a while.
    With a Whisper model chosen there is only that one: it does all of it.
    """

    def __init__(self, dictation_model: str = ""):
        self._loaded = {}  # folder name -> model, so a model used for both is loaded once
        # One piece of listening at a time: this computer's own, or one done for another
        # computer that has been let in (see remote.py).
        self.lock = threading.RLock()
        self._guests = []  # models loaded because another computer asked: latest last
        self._scorable = {}  # Whisper models: whether each can say how sure it was
        self.quick = False  # give Whisper only as much sound as the phrase needs: see quick.py
        self.speech_only = True  # a noise Parakeet wrote a word for is left out: see speech.py
        self.left_out = ""       # what the last phrase was written as, if it was left out as a noise
        self._extras = {}        # Whisper models loaded for source code or for spelling: when last used
        self._letter_times = {}  # how long each model took to hear a letter, the last few times
        self._letter_speeds = None  # and what was found before: see _too_slow
        self.not_speech = 0.0  # for the last phrase heard asleep: how likely it was noise
        self.ignored = ""      # and what it was taken for, if it was ignored as noise
        self.helper_name = config.WAKE_MODEL  # the Whisper that helps a Parakeet: see the class
        self._short_window = True  # until it turns out this library can't do it
        self.dictation_name = ""
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
            self._loaded[name] = sherpa_onnx.OfflineRecognizer.from_transducer(
                **models.transducer_files(config.MODEL_DIR, name),
                num_threads=config.THREADS, model_type="nemo_transducer",
            )
        return self._loaded[name]

    def _is_transducer(self, name: str) -> bool:
        return models.kind(config.MODEL_DIR, name) == "transducer"

    def _by_transducer(self, name: str, audio, sure: bool = False, speech_only=None) -> str:
        """The words. With `sure`, a voicetest.Heard that also says how sure the
        recogniser was of each word, where its library tells. A noise that was written
        down as a word is left out, unless `speech_only` (or this computer's own choice,
        if that is None) says not to: see speech.py."""
        recogniser = self._transducer(name)
        stream = recogniser.create_stream()
        stream.accept_waveform(config.RATE, audio)
        recogniser.decode_stream(stream)
        result = stream.result
        text = from_pieces(result)
        each = voicetest.word_sureness(list(result.tokens), getattr(result, "ys_log_probs", None))
        self.measured = None  # for a phrase of a word or two: what was measured of it
        self.left_out = ""
        if text and (getattr(self, "speech_only", True) if speech_only is None else speech_only):
            least = min((how for _, how in each), default=None) if each else None
            numbers = {"seconds": round(len(audio) / config.RATE, 1)}
            why = speech.not_speech(text, audio, sure=least, numbers=numbers)
            if len(numbers) > 1:
                self.measured = numbers
            if why:
                log(f"a sound of {len(audio) / config.RATE:.1f} s left out, {len(text)} characters: {why}"
                    + speech.told(numbers))
                self.left_out = text
                return voicetest.heard_as("", []) if sure else ""
        if not sure:
            return text
        return voicetest.heard_as(text, each)

    def use(self, name: str) -> None:
        """Switch the dictation model. Raises if it can't be loaded, leaving the old one.
        A Parakeet has its Whisper helper loaded beside it; a Whisper model needs none,
        and what was loaded to help the last one is let go."""
        with self.lock:
            if self._is_transducer(name):
                self._transducer(name)
                self._model(self.helper_name)
            else:
                self._model(name)
            self.dictation_name = name
            self._extras = {}
            for other in list(self._loaded):
                if other not in self._in_use():
                    del self._loaded[other]  # free its memory

    def _in_use(self) -> tuple:
        """The models that are to stay loaded: the chosen one, its helper if it is a
        Parakeet, the one hearing source code just now, and the guests'."""
        helper = (self.helper_name,) if self._is_transducer(self.dictation_name) else ()
        return (self.dictation_name, *helper, *getattr(self, "_extras", {}), *self._guests)

    def _whisper_name(self, code: bool = False) -> str:
        """The Whisper model for listening that leans on a hint: the chosen model if it
        is one. With a Parakeet chosen, its helper; or for source code a bigger one,
        where one of config.CODE_MODELS is installed."""
        if not self._is_transducer(self.dictation_name):
            return self.dictation_name
        if not code:
            return self.helper_name
        return self._extra(config.CODE_MODELS, self.helper_name, "source code")

    def _letters_name(self) -> str:
        """The Whisper model that hears the spelling box: see config.SPELL_MODELS. The
        first of them that is installed and is quick enough on this computer."""
        usual = self.dictation_name if not self._is_transducer(self.dictation_name) \
            else self.helper_name
        here = [name for name in config.SPELL_MODELS
                if models.kind(config.MODEL_DIR, name) == "whisper"]
        quick = [name for name in here if not self._too_slow(name)] or here[-1:]
        return self._extra(tuple(quick), usual, "the spelling box")

    def _speeds(self) -> dict:
        """How long each model was found to take over a letter on this computer."""
        if getattr(self, "_letter_speeds", None) is None:
            try:
                with open(config.SPELL_SPEEDS, encoding="utf-8") as f:
                    found = json.load(f)
                self._letter_speeds = {str(k): float(v) for k, v in found.items()} \
                    if isinstance(found, dict) else {}
            except (OSError, ValueError, TypeError):
                self._letter_speeds = {}
        return self._letter_speeds

    def _too_slow(self, name: str) -> bool:
        return self._speeds().get(name, 0.0) > config.SPELL_SLOW

    def _timed(self, name: str, seconds: float) -> None:
        """One more letter heard by `name`, in so long. After three it is known how quick
        the model is here: that is kept, and a model that is too slow is let go, so that
        the next letter goes to the next one. It is the quickest of the three that is
        gone by: a computer that was busy for one of them isn't a slow computer."""
        times = getattr(self, "_letter_times", None)
        if times is None:
            times = self._letter_times = {}
        mine = times.setdefault(name, [])
        if len(mine) >= 3:
            return                 # found out already, since the program was started
        mine.append(seconds)
        if len(mine) < 3:
            return
        usual = min(mine)
        speeds = self._speeds()
        speeds[name] = round(usual, 2)
        try:
            os.makedirs(os.path.dirname(config.SPELL_SPEEDS), exist_ok=True)
            with open(config.SPELL_SPEEDS, "w", encoding="utf-8") as f:
                json.dump(speeds, f)
        except OSError:
            pass
        if usual > config.SPELL_SLOW:
            log(f"the spelling box: {name} takes {usual:.1f} s over a letter on this computer "
                f"at its quickest, which is too slow (over {config.SPELL_SLOW:g} s): "
                "a quicker model hears the box from now on")
            self._extras.pop(name, None)
            if name not in self._in_use():
                self._loaded.pop(name, None)

    def ready_for_letters(self) -> None:
        """The spelling box has been opened: load the model that hears it now, so that
        the first letter isn't kept waiting for that."""
        with self.lock:
            try:
                self._model(self._letters_name())
            except Exception as e:
                log(f"the model for the spelling box could not be loaded: {type(e).__name__}")

    def _extra(self, wanted: tuple, otherwise: str, what_for: str) -> str:
        """The first of `wanted` that is installed, kept loaded for a while for the one
        purpose: or `otherwise`, which is loaded anyway."""
        name = next((each for each in wanted
                     if models.kind(config.MODEL_DIR, each) == "whisper"), otherwise)
        if name in (self.dictation_name, otherwise):
            return name
        if name not in self._extras and name not in self._loaded:
            log(f"{what_for} is heard by {name}, loaded now")
        self._extras[name] = time.monotonic()
        return name

    def _let_go_of_code_model(self) -> None:
        """A Whisper that was loaded for source code or for spelling is let go when it
        hasn't been used for a while: it is the biggest thing in memory."""
        for name, used in list(getattr(self, "_extras", {}).items()):
            if time.monotonic() - used > config.CODE_MODEL_IDLE:
                del self._extras[name]
                if name not in self._in_use():
                    self._loaded.pop(name, None)
                    log(f"not used for a while: {name} let go")

    def answer(self, header: dict, audio) -> dict:
        """One piece of listening done for another computer: see remote.py."""
        started = time.monotonic()
        with self.lock:
            code = bool(header.get("code", False))
            if header.get("kind") == "alone":
                text, model, awake = self.hear_alone(audio), self._whisper_name(), True
            else:
                awake = bool(header.get("awake", True))
                # Asleep, it is "wake up" that is listened for, by the guest's own model as
                # everything else of its is. (A guest from before that was so doesn't ask
                # for it, and gets this computer's Whisper as it used to.)
                same = not awake and bool(header.get("wake_same", False))
                model = self._guest_model(header) if awake or same else self._whisper_name()
                exact = bool(header.get("exact", False))
                if awake and exact and self._is_transducer(model):
                    model = self._whisper_name(code)  # what leans on the prompt is Whisper's work
                wanted = header.get("speech_only")  # not said: this computer's own choice, then
                wanted = None if wanted is None else bool(wanted)
                if awake and header.get("sure") and not exact:  # for a voice test
                    text = self.hear_with(model, audio, str(header.get("prompt", "")),
                                          bool(header.get("quick", False)), sure=True,
                                          speech_only=wanted)
                else:
                    text = self.transcribe(audio, awake, str(header.get("prompt", "")), model,
                                           quick=bool(header.get("quick", False)), exact=exact,
                                           speech_only=wanted, code=code,
                                           letters=bool(header.get("letters", False)))
            reply = {"ok": True, "text": str(text), "model": model,
                     "not_speech": 0.0 if awake else self.not_speech,
                     "ignored": "" if awake else self.ignored,
                     "seconds": round(time.monotonic() - started, 2)}
            if getattr(text, "sure", None) is not None:
                reply["sure"] = [[word, round(how, 4)] for word, how in text.sure]
                reply["extra"] = round(text.extra, 3)  # seconds spent on that, not on listening
            return reply

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
        own = tuple(n for n in self._in_use() if n not in self._guests)
        if name not in own:
            if name in self._guests:
                self._guests.remove(name)
            self._guests.append(name)
            while len(self._guests) > GUEST_MODELS:
                old = self._guests.pop(0)
                if old not in own:
                    self._loaded.pop(old, None)
        return name

    def hear_with(self, name: str, audio, prompt: str = "", quick: bool = False,
                  sure: bool = False, speech_only=None) -> str:
        """`audio` as the model `name` hears it, whichever model is in use. For the voice
        test, which tries them all, and asks with `sure` how sure it was of each word:
        the answer is then a voicetest.Heard."""
        with self.lock:
            if self._is_transducer(name):
                return self._by_transducer(name, audio, sure=sure, speech_only=speech_only)
            if not sure:
                return self._transcribe(audio, True, prompt, name, quick)
            if name not in self._scorable:
                self._scorable[name] = models.whisper_can_be_scored(config.MODEL_DIR, name)
                if not self._scorable[name]:
                    log(f"{name} can't be asked how sure it was: its file doesn't bear it out")
            if not self._scorable[name]:
                return voicetest.heard_as(self._transcribe(audio, True, prompt, name, quick), None)
            with _Scoring(self._model(name)) as scoring:
                text = self._transcribe(audio, True, prompt, name, quick)
            return voicetest.heard_as(text, scoring.sureness(text), scoring.seconds)

    def renewed(self, name: str) -> bool:
        """The files of the model `name` have been made again (it was retrained under the
        same name). What is loaded of it is the old one: it is let go, and loaded afresh
        if it is the one in use. True if anything was loaded of it."""
        with self.lock:
            if self._loaded.pop(name, None) is None:
                return False
            if name in (self.dictation_name, *self._guests):
                (self._transducer if self._is_transducer(name) else self._model)(name)
            return True

    def release(self, name: str) -> None:
        """Forget a model loaded by hear_with, unless it is one in use."""
        with self.lock:
            if name not in self._in_use():
                self._loaded.pop(name, None)

    def hear_alone(self, audio) -> str:
        """A second or so of sound by itself, with only the sound to go on. A Whisper
        model does it: the chosen one, or the helper of a Parakeet.

        Whisper takes in half a minute of sound however little there is, and that is
        most of the time it takes. Given ten seconds it hears a short clip just the same
        in a quarter of the time. Given much less it starts to repeat itself.
        """
        with self.lock:
            model = self._model(self._whisper_name())
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

    def _hear_short(self, model, audio, hint: str = "", beam: int = 0) -> str:
        """A short sound through a short window. `hint` is shown to the model as what
        came before, as a prompt is: for the spelling box, that it is letters. `beam` is
        how many ways of writing it are followed at once: the usual number if not given."""
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.tokenizer import Tokenizer
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                              task="transcribe", language="en")
        before = tokenizer.encode(" " + hint.strip()) if hint.strip() else []
        prompt = model.get_prompt(tokenizer, before, without_timestamps=True)
        features = pad_or_trim(model.feature_extractor(audio), SHORT_WINDOW_FRAMES)
        result = model.model.generate(model.encode(features), [prompt],
                                      beam_size=beam or config.BEAM,
                                      max_length=len(prompt) + 32 if before else 32)[0]
        return tokenizer.decode(result.sequences_ids[0]).strip()

    def letters(self, audio, hint: str) -> str:
        """What was said into the spelling box: a letter or a few, by the model that tells
        letters apart best, told that it is letters. Through the short window, which a
        letter fits in many times over, and which takes a quarter of the time."""
        with self.lock:
            self._let_go_of_code_model()
            name = self._letters_name()
            first = None
            if len(audio) <= SHORT_SECONDS * config.RATE and self._short_window:
                was_loaded = name in self._loaded
                model = self._model(name)
                started = time.monotonic()
                try:
                    # One way of writing it followed, not five: a letter is one piece,
                    # and it was no worse so (91 of 102 against 89) and a sixth quicker.
                    first = self._hear_short(model, audio, hint, beam=1)
                    if was_loaded:     # not the time it was loaded: that is no measure
                        self._timed(name, time.monotonic() - started)
                except Exception as e:  # an older library that insists on the half minute
                    self._short_window = False
                    log(f"the short listening window isn't available: {e}")
            if first is None:
                first = self._transcribe(audio, True, hint, name, False)
            # And the model chosen for dictation hears it as well: it knows the voice, and
            # is the better at whole words, "done" among them. See spelling.choose.
            second = self._chosen_hears(audio, hint, name)
            return first if second is None else spelling.choose(first, second)

    def _chosen_hears(self, audio, hint: str, besides: str):
        """What the model chosen for dictation makes of something said into the spelling
        box: None if it is the model that has heard it already, or can't be asked."""
        chosen = self.dictation_name
        try:
            if self._is_transducer(chosen):
                return self._by_transducer(chosen, audio, speech_only=False)
            if chosen != besides and not self._too_slow(chosen) and self._short_window \
                    and len(audio) <= SHORT_SECONDS * config.RATE:
                started = time.monotonic()
                heard = self._hear_short(self._model(chosen), audio, hint)
                self._timed(chosen, time.monotonic() - started)
                return heard
        except Exception as e:
            log(f"the chosen model could not be asked about the spelling box: {type(e).__name__}")
        return None

    def transcribe(self, audio, awake: bool, prompt: str = "", model: str = "",
                   quick=None, exact: bool = False, speech_only=None, code: bool = False,
                   letters: bool = False) -> str:
        """The words in `audio`, as the chosen model hears them: awake or asleep. `model`,
        `quick` and `speech_only` are for a guest that says which model it wants, whether
        to try the quick way, and whether a noise written as a word is to be left out;
        left out, this computer's own choices are used. `exact` is for listening that
        depends on the prompt, such as spelled letters, which a Parakeet can't be given:
        with one chosen that goes to a Whisper model, and with `code`, to the one kept
        for source code."""
        if awake and exact and letters:
            return self.letters(audio, prompt)      # the spelling box: see letters()
        with self.lock:
            self._let_go_of_code_model()
            model = model or self.dictation_name
            if self._is_transducer(model):
                if not awake:
                    return self._asleep_by_transducer(model, audio, speech_only)
                if not exact:
                    return self._by_transducer(model, audio, speech_only=speech_only)
                model = self._whisper_name(code)
            return self._transcribe(audio, awake, prompt, model,
                                    self.quick if quick is None else quick)

    def _asleep_by_transducer(self, model: str, audio, speech_only=None) -> str:
        """What was said while asleep, which only matters if it is "wake up", as the
        Parakeet chosen for dictation hears it. As with Whisper, long sound is not
        listened to at all: a video playing, a conversation. And a sound that is no
        speech is left out, where that is switched on: what it was written as is kept
        in `ignored`, for the log to show what "wake up" was taken for."""
        self.not_speech, self.ignored = 0.0, ""
        if len(audio) > config.WAKE_MAX_SECONDS * config.RATE:
            return ""
        text = self._by_transducer(model, audio, speech_only=speech_only)
        if not text and getattr(self, "left_out", ""):
            self.not_speech, self.ignored = 1.0, self.left_out
        return text

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
            segments, _ = self._model(model).transcribe(
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
        self.on_event = lambda name: None  # "ready", "wake", "sleep", "off"...: see _events
        # Something to tell the person at once, in a sentence: (text, "info" or "problem").
        self.on_notice = lambda text, kind="info": None
        self._told = {}            # when each notice was last given, so none is repeated at once
        self.on_level = lambda: None  # the level meter changed
        self.boost = config.DEFAULT_BOOST
        self.settings = Settings.load()
        self.status.commands_only = self.settings.enabled("commands_only")  # see _apply_mode
        if getattr(self.settings, "first_time", False) and os.path.exists(config.STATE_FILE):
            # No settings were ever saved, but dictation has been switched on or off here
            # before: this is an install from before the settings were kept at once, and
            # not a newcomer's. It is not shown the welcome, and on Windows it keeps the
            # key it has always had, which a newcomer has to choose.
            self.settings.first_time = False
            if config.WINDOWS and not self.settings.hotkey:
                self.settings.hotkey = "Number pad +"
            try:
                self.settings.save()
            except OSError:
                pass
        key = own_key(config.MAIL_KEY_FILE) if config.MAIL else ""
        mail = MailBridge(config.MAIL_PORT, key) if key else None
        self._standing = {}        # what is wrong and stays wrong, by what it is about
        if config.MAIL and not key:
            log("the key for Thunderbird's add-on can't be kept: dictation into Thunderbird is off")
            self._standing["mail"] = ("Dictation into Thunderbird is off: its key couldn't be "
                                      "kept in the settings folder.")
        if mail is not None and not mail.start():
            log(f"port {config.MAIL_PORT} is in use: dictation into Thunderbird is off")
            self._standing["mail"] = (f"Dictation into Thunderbird is off: another program is "
                                      f"using port {config.MAIL_PORT} on this computer.")
            mail = None
        self._mail = mail
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
                self._standing["office"] = ("Dictation into Word and Outlook is off: a part "
                                            "it needs is missing. Run the installer again.")
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
        self._asked = None   # a command of the person's own waiting for "yes": (said, steps, until)
        self._doer = actions.Doer()  # presses keys, opens things, runs programs: see actions.py
        self._heard_sound = None  # the last phrase heard awake: (sound, words, model, measures)
        self._typed_sound = None  # and, if its words were typed, that with (when, taken back)
        self._where_typed = ""  # the program the last words went into
        self._load_tried = 0.0  # when loading the speech model was last tried and failed
        self._held = ""  # "awake" or "asleep" while listening is stopped for a recording
        self._holds = 0  # how many windows are recording
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
        self._vscode_switch()
        speech.for_its_owner_alone(config.NOISE_DIR)   # kept noises: nobody else's to hear
        self._problems()
        threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    # ---- telling the person ---------------------------------------------
    def tell(self, text: str, kind: str = "info", every: float = 0.0, logged: str = "") -> None:
        """Show the person a sentence now. `every` is how many seconds must pass before
        the same one is shown again: a thing that goes wrong with every phrase is said
        once, not with every phrase. `logged` is what the log is given in its place,
        where the sentence has words in it that were said or written: those never go
        in the log."""
        now = time.monotonic()
        if every and now - self._told.get(text, -1e9) < every:
            return
        self._told[text] = now
        log(f"told: {logged or text}")
        self.on_notice(text, kind)

    def _problems(self) -> None:
        """Bring the list of what is wrong up to date: see Status.problems."""
        found = dict(self._standing)
        said = getattr(self._mail, "problem", "")
        if said:
            found["mail"] = said
        said = getattr(self.targets.other, "problem", "")
        if said:
            found["keys"] = said
        if self.share_problem:
            found["share"] = "Other computers can't use this one for recognition: " + self.share_problem
        now = list(found.values())
        if now != self.status.problems:
            self.status.problems = now
            self.on_event("problems")
            self.on_change()

    def _watch(self) -> None:
        """While awake and idle, look every few seconds at which program is in front, so
        that the tray's tip says where the words will go before they are said. The
        looking is done on the worker, in its turn: the programs' links are not all safe
        to use from two threads at once."""
        while self._running:
            time.sleep(config.LOOK_SECONDS)
            if self.status.state is State.AWAKE and self._phrases.empty() and not self._holds:
                self._phrases.put(("call", self._look))
            elif not self.status.awake and self.status.target_known:
                self.status.target_known = False   # nobody is keeping it true now
                self.on_change()
            self._problems()

    def _look(self) -> None:
        if self.status.state is not State.AWAKE:
            return
        self.targets.pick()
        was = (self.status.writer_ready, self.status.target, self.status.target_known)
        self.status.writer_ready = bool(self.targets.name)
        self.status.target, self.status.target_known = self.targets.name, True
        if was != (self.status.writer_ready, self.status.target, True):
            self.on_change()

    # ---- on / off -------------------------------------------------------
    def turn_on(self, awake: bool = False, quietly: bool = False) -> bool:
        """Open the microphone. False if it couldn't be: the person is told why, unless
        `quietly` (a try made by the program itself, which will be made again)."""
        chosen = self.settings.microphone
        with self._lock:
            if self._recorder is not None:
                return True
            try:
                self._recorder = audio.open_microphone(chosen)
            except Exception as e:
                why = str(e) if isinstance(e, audio.MicrophoneError) else (
                    f"The microphone can't be opened: {e}.")
                log(f"could not open the microphone: {e}")
                self._standing["microphone"] = why
                self._problems()
                if not quietly:
                    self.tell(why, "problem")
                return False
            recorder = self._recorder
        if not quietly and self._standing.pop("microphone", None):
            self._problems()
        if chosen and config.WINDOWS and chosen not in audio.microphones():
            self.tell(f"The microphone chosen in Settings, \"{chosen}\", isn't connected: "
                      "Windows' own choice is being used.", "problem", every=600)
        if getattr(self, "_drops", None) and not quietly:
            self._drops = []              # switched on by hand: a clean slate
        self._set(State.AWAKE if awake else State.ASLEEP)
        threading.Thread(target=self._listen, args=(recorder,), daemon=True).start()
        return True

    def microphones(self) -> list:
        """The recording devices as they are now, for Settings (Windows). The list can
        only be read again while nothing is being recorded, so if dictation is on and
        nobody is speaking, the microphone is closed for the moment that takes."""
        if not config.WINDOWS:
            return []
        if self.status.state in (State.ASLEEP, State.AWAKE) and not self._holds:
            awake = self.status.awake
            self.turn_off(remember=False)
            found = audio.microphones(fresh=True)
            if not self.turn_on(awake=awake):
                # It was open a moment ago. Said (turn_on has), and tried again until it
                # opens, as for one that stopped by itself.
                self.on_event("off")
                threading.Thread(target=self._come_back, daemon=True).start()
            return found
        return audio.microphones(fresh=True)

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
        if remember:
            # Switched off by the person: nothing is waiting to come back by itself.
            if self._standing.pop("microphone", None):
                self._problems()
        if remember and was_on:
            self.on_event("off")

    def wake(self) -> None:
        if self.status.state is State.OFF:
            if not self.turn_on(awake=True):
                return                    # no microphone: it has been said, and nothing is awake
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
        """Keep whether dictation is on or off, for the next start. Written only when
        it changes: waking and sleeping are both "on", and need nothing written."""
        now = "off" if self.status.state is State.OFF else "on"
        if now == getattr(self, "_kept_state", None):
            return
        try:
            os.makedirs(os.path.dirname(config.STATE_FILE), exist_ok=True)
            with open(config.STATE_FILE, "w") as f:
                f.write(now)
            self._kept_state = now
        except OSError:
            pass

    # ---- microphone -----------------------------------------------------
    def _listen(self, recorder) -> None:
        segmenter = Segmenter(SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO))
        watch = speech.VoiceWatch()   # sees the voice stop where the room is too loud for a pause
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
                watch.start(len(phrase))
                self._hearing(True)
            if segmenter.in_phrase or event == END:
                phrase.append(frame)
            else:
                preroll.append(frame)
            if segmenter.in_phrase and event is None:
                seen = watch.feed(frame)
                if seen == speech.BEGAN_LATE:
                    # The room's noise began this phrase, and only now is there a voice in
                    # it. What came before is dropped, so that the voice isn't kept waiting
                    # behind it, or cut short by the limit on how long a phrase may be.
                    dropped = len(phrase) - watch.frames_for(watch.BEFORE)
                    if dropped > 0:
                        phrase = phrase[dropped:]
                        watch.began_at(len(phrase))
                        segmenter.began_again(len(phrase))
                        log(f"a voice began {dropped * config.FRAME / config.RATE:.1f} s into a "
                            "sound: what came before it was left out")
                elif seen == speech.GONE:
                    # The voice has stopped and the sound goes on. The phrase is over: all
                    # of it up to a moment after the voice was last heard.
                    spare = watch.frames_since_voice() - watch.frames_for(watch.AFTER)
                    if 0 < spare < len(phrase):
                        phrase = phrase[:-spare]
                    event = segmenter.cut() or None
            if event == END and segmenter.ended_by == ROOM:
                # No phrase: a fan, a hum, flat from its start. Nothing of it is taken
                # down, and it is the room from now on.
                seconds = len(phrase) * config.FRAME / config.RATE
                phrase = []
                preroll.clear()
                log(f"a sound of {seconds:.1f} s was the room, as flat as a fan: left out "
                    f"(room {segmenter.room_was:.0f}, now {segmenter.noise:.0f})")
                if self.status.state is State.HEARING:
                    self.status.state = State.AWAKE
                    self.on_change()
                continue
            if event == END:
                audio = np.concatenate(phrase).astype(np.float32) / 32768.0
                phrase = []
                preroll.clear()
                self.status.voice_db = best
                if segmenter.ended_by == LIMIT and not watch.heard:
                    segmenter.was_the_room()   # twenty seconds with no voice in them
                seconds = len(audio) / config.RATE
                if segmenter.ended_by in (FELL_AWAY, NO_VOICE, LIMIT) or seconds >= config.LONG_PHRASE:
                    # Not the usual pause, or a long time coming: said in the log, in
                    # loudness only. It is what to look at when somebody says a phrase
                    # took a long time to be acted on: whether the room was louder than
                    # it was taken to be, and whether what was left was a steady noise or
                    # something that rose and fell, as other people talking does.
                    low, high = segmenter.tail_spread
                    how = {FELL_AWAY: "because the sound fell away from the voice, though the "
                                      "room stayed louder than it had been",
                           NO_VOICE: "because the voice in it had stopped, though the sound "
                                     "went on",
                           LIMIT: "at the longest a phrase may be: the sound never fell quiet"
                           }.get(segmenter.ended_by, "at a pause")
                    voice = segmenter.voice_was or 1.0
                    log(f"a phrase of {seconds:.1f} s ended {how} (voice {segmenter.voice_was:.0f}, "
                        f"its last second {segmenter.tail_was:.0f}, "
                        f"{100 * segmenter.tail_was / voice:.0f}% of the voice, "
                        f"{'level' if segmenter.tail_steady else 'rising and falling'}, "
                        f"from {low:.2f} to {high:.2f} of its middle; "
                        f"room {segmenter.room_was:.0f}, now {segmenter.noise:.0f})")
                self._phrases.put(("audio", audio))
        self.status.level = self.status.meter = 0
        self.status.loud = False
        self.on_level()
        if self._recorder is recorder:  # the recorder died by itself
            # Not the person's doing, so it isn't kept as their choice. When the service
            # is stopped the recorder is stopped first, and keeping "off" then meant
            # dictation came back switched off after every restart.
            why = ""
            try:
                why = recorder.why()
            except Exception:
                pass
            self.turn_off(remember=False)
            if not self._running:
                return
            self.on_event("off")
            said = "The microphone stopped" + (f": {why}" if why else ".")
            log(said)
            # One that stops again and again is not tried for ever.
            now = time.monotonic()
            self._drops = [at for at in getattr(self, "_drops", []) if now - at < 60] + [now]
            again = len(self._drops) < config.MICROPHONE_DROPS
            self._standing["microphone"] = said.rstrip(".") + (
                ". Dictation will come back asleep when it can be opened again." if again
                else ". It keeps stopping: click the icon to try it again.")
            self._problems()
            self.tell(self._standing["microphone"], "problem", every=60)
            if again:
                threading.Thread(target=self._come_back, daemon=True).start()

    def _come_back(self) -> None:
        """After the microphone stopped by itself (unplugged, the sound system restarted):
        try it every couple of seconds for a few minutes, and come back asleep when it
        works, so that somebody dictating without their hands can say "wake up" and carry
        on. Nobody is told anything until it really is back."""
        for _ in range(config.MICROPHONE_TRIES):
            time.sleep(config.MICROPHONE_WAIT)
            if not self._running or self.status.state is not State.OFF or self._holds \
                    or "microphone" not in self._standing:
                return                    # switched on, or off, by somebody meanwhile
            if audio.works(self.settings.microphone) and self.turn_on(awake=False, quietly=True):
                if self._standing.pop("microphone", None):
                    self._problems()
                self.on_event("sleep")
                return

    def _hearing(self, on: bool) -> None:
        if on and self.status.state is State.AWAKE:
            self.status.state = State.HEARING
            self.on_change()

    # ---- phrases --------------------------------------------------------
    def _work(self) -> None:
        # Load the speech models straight away. Anything said meanwhile waits in the queue.
        if self._no_model_here():
            self._there_only()
        elif self._transcriber is None:
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
                log(f"a phrase went wrong: {type(e).__name__}: {e}")
                self.tell("Something went wrong with that phrase, and it was not typed. The "
                          "log says more.", "problem", every=30)
                self._back_to_awake()

    def _load(self, model: str, before: str | None = None) -> None:
        """Load the speech models, or switch the dictation model. Runs on the worker.
        `before` is the choice that was in force, to go back to if the new one won't load."""
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
                    self.tell(f"{named(model)} could not be loaded, so "
                              f"{named(self._transcriber.dictation_name)} is being used.", "problem")
                    self.on_event("model")
            else:
                try:
                    self._transcriber.use(model or config.AWAKE_MODEL)
                except Exception as e:
                    # The one in use is still loaded: stay with it, and say so, and put
                    # the choice back so that Settings doesn't name a model that isn't used.
                    log(f"could not load {model}: {e}; staying with "
                        f"{self._transcriber.dictation_name}")
                    if before is not None:
                        self.settings.set_model(before)
                    self.tell(f"{named(model or config.AWAKE_MODEL)} could not be loaded. Still "
                              f"using {named(self._transcriber.dictation_name)}.", "problem")
                    self.on_event("model")
            log(f"ready, dictation model {self._transcriber.dictation_name}")
            self.status.failed = ""
            self.on_event("ready")
        except Exception as e:
            log(f"loading failed: {type(e).__name__}: {e}")
            self._load_tried = time.monotonic()
            if self._no_model_here():
                self._there_only()        # nothing to load, and nothing wrong: see there
                return
            failed = no_model(e)
            if failed != self.status.failed:
                self.status.failed = failed
                self.on_event("failed")
        self.status.ready = self._transcriber is not None
        self.on_change()

    def model_installed(self, name: str) -> None:
        """A speech model has just been installed. On a computer that had none loaded
        it is put to use straight away: nobody should have to go looking for how."""
        if self._transcriber is None:
            log(f"the first speech model here, {name}: it is put to use")
            self.set_model(name)

    # ---- a computer with no speech model of its own ---------------------------------------
    def _no_model_here(self) -> bool:
        """Whether this computer has no speech model, and another computer is set up to
        do the listening: a small computer, with no room for a model or no speed for
        one. That is a way of installing it, and nothing is wrong."""
        return (self._transcriber is None and self._offload is not None
                and not available_models(config.MODEL_DIR))

    def _there_only(self) -> None:
        """Ready, with no model here: the other computer hears everything, "wake up"
        too. What it can't be asked for is not heard, which is said while it is so (see
        _listening_moved)."""
        if self.status.failed or not self.status.ready:
            log("no speech model on this computer: the other computer does all the "
                "listening, \"wake up\" too")
        self.status.failed = ""
        self.status.ready = True
        self.on_event("ready")
        self.on_change()

    def setting_changed(self, key: str) -> None:
        """Called when a tick box in Settings is changed."""
        if key == "other_apps":
            self.apply_accessibility()
            self._vscode_switch()
        if key == "commands_only":
            self._apply_mode()

    def _vscode_switch(self) -> None:
        """VS Code only shows its panels to other programs when started with a switch for
        that. It is put in when "other programs" is ticked, and not at install, so nobody
        has it who never wanted this; and looked at again at each start, for a VS Code
        that was first run after the box was ticked."""
        if not (config.WEB and self.settings.enabled("other_apps")):
            return
        try:
            from . import vscode_args
            changed = [line for line in vscode_args.switch_on() if "switched on" in line]
        except Exception as e:
            changed = []
            log(f"VS Code's start-up switch could not be set: {e}")
        for line in changed:
            log(line)
        if changed:
            self.tell("To dictate into VS Code's panels, close VS Code and open it "
                      "again: it has been set to show them to this program.", "info")

    def apply_accessibility(self) -> None:
        """Other programs only show their text boxes while desktop accessibility is on."""
        if config.EDITOR:
            said = accessibility.apply(self.settings.enabled("other_apps"))
            if said:
                log(said)

    def set_model(self, model: str) -> None:
        """Choose the dictation model. It is loaded in the background."""
        before = self.settings.model
        self.settings.set_model(model)
        if self._offload is not None:
            self._offload.otherwise = self._otherwise()
        self.status.ready = False
        self.on_change()
        self._phrases.put(("call", lambda: self._load(model, before)))

    def model_renewed(self, name: str) -> None:
        """A training run has made the model `name` again. If it is loaded, the new one
        takes its place: otherwise dictation would go on with the old until a restart."""
        def renew():
            ears = self._transcriber
            try:
                if ears is not None and hasattr(ears, "renewed") and ears.renewed(name):
                    log(f"model {name} was retrained: the new one is loaded")
            except Exception as e:
                log(f"the retrained {name} could not be loaded: {e}")

        self._phrases.put(("call", renew))

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
        speech_only = self.settings.enabled("speech_only")
        for each in (ears, self._transcriber):
            if hasattr(each, "quick"):
                each.quick = quickly
                each.speech_only = speech_only
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
        alone = self._transcriber is None      # no speech model here to carry on with
        self.status.listening_on = (
            offload.client.host if there
            else "nowhere: the other computer can't be reached" if alone
            else "this computer: the other can't be reached")
        log("recognition on the other computer" if there
            else f"no recognition: no speech model on this computer. {problem}" if alone
            else f"recognition on this computer. {problem}")
        if alone and not there:
            self._standing["remote"] = (
                "Nothing you say can be heard. This computer has no speech model of its own, "
                "and the other computer does the listening: "
                + (problem if problem else "it isn't answering.")
                + " It is asked again as you speak.")
        else:
            self._standing.pop("remote", None)
        self._problems()
        self.on_change()

    def set_remote(self, on: bool, address: str, key: str, model: str, wake: bool) -> None:
        """Choose another computer to do the listening. From the Settings window."""
        self.settings.set_remote(on=on, address=address, key=key, model=model, wake=wake)
        log("another computer for recognition: " + ("on" if self.settings.remote["on"] else "off"))
        self._apply_remote()
        self._standing.pop("remote", None)     # it is asked afresh, and says how it is then
        if self._transcriber is None and not available_models(config.MODEL_DIR):
            # No speech model here: whether anything can be heard turns on this choice.
            if self._offload is not None:
                self._there_only()
            else:
                self.status.failed, self.status.ready = no_model(None), False
                self.on_event("failed")
                self.on_change()

    def check_remote(self) -> dict:
        """Ask the other computer what it offers. Waits for the answer, so not for the
        thread that draws the windows. {"ok": True, "version": ..., "models": [[name,
        label], ...], "model": its own choice} or {"ok": False, "why": ...}."""
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
            # The port is taken, at login the network isn't up yet, or nothing can be
            # encrypted here (which says so itself). Keep trying.
            problem = (f"can't answer on port {config.SHARE_PORT}: {e.strerror}"
                       if e.strerror else str(e))
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
        typed anywhere. unhold() puts things back as they were, once every window that
        asked for a hold has let go."""
        self._holds += 1
        if self.status.state is not State.OFF:
            self._held = "awake" if self.status.awake else "asleep"
            self.turn_off(remember=False)

    def unhold(self, asleep: bool = False) -> bool:
        """Let go of a hold. `asleep` brings dictation back asleep even if it was awake,
        for when nobody is there to have asked for it. Returns whether that was done."""
        self._holds = max(0, self._holds - 1)
        if self._holds:
            return False
        held, self._held = self._held, ""
        if held:
            self.turn_on(awake=held == "awake" and not asleep)
        return held == "awake" and asleep

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
                "phrase", sound, True, written, candidate.name, (), candidate.quick, sure=True,
                speech_only=self.settings.enabled("speech_only"))
            if reply.get("model") != candidate.name:
                raise remote.RemoteError("The other computer no longer has this model.")
            try:  # how sure it was of each word, if that computer says
                sure = [(str(word), float(how)) for word, how in reply["sure"]]
                extra = float(reply.get("extra", 0.0))
            except (KeyError, TypeError, ValueError):
                sure, extra = None, 0.0
            return voicetest.heard_as(str(reply.get("text", "")), sure, extra)
        if self._transcriber is None or not hasattr(self._transcriber, "hear_with"):
            raise RuntimeError("the speech models are still loading")
        return self._transcriber.hear_with(candidate.name, sound, written, candidate.quick,
                                           sure=True,
                                           speech_only=self.settings.enabled("speech_only"))

    def hear_reading(self, sound) -> str:
        """A sentence read aloud for training, as the recogniser in use hears it: on the
        other computer, if that does the listening. For the reading window, which moves
        on when the sentence has been heard to its end. Raises if nothing can listen."""
        ears = self._ears()
        if ears is None:
            raise RuntimeError("the speech models are still loading")
        return ears.transcribe(normalise(sound), True, "")

    def test_done(self, candidate) -> None:
        """Free the models the voice test loaded for a recogniser."""
        for member in candidate.team or (candidate,):
            if member.where == "here" and hasattr(self._transcriber, "release"):
                self._transcriber.release(member.name)

    def run_soon(self, action) -> None:
        """Run something on the worker, after anything already heard. For the tray's buttons."""
        self._phrases.put(("call", action))

    def _only_breath(self, audio) -> bool:
        """Whether a phrase is to be left out because there is too little voice in it: a
        whisper, or a noise. Only asked where the person wants whispering left out. What
        was measured goes in the log, as figures, so that the line can be drawn from
        what is really said and whispered at this microphone. See speech.voiced."""
        if not self.settings.enabled("aloud"):
            return False
        share = speech.voiced(audio)
        long = len(audio) / config.RATE
        if share >= speech.VOICED:
            if share < 2 * speech.VOICED:  # near the line: worth knowing about
                log(f"a sound of {long:.1f} s taken for speech: voice in {share:.0%} of it")
            return False
        log(f"a sound of {long:.1f} s left out, a whisper or a noise: voice in {share:.0%} of it")
        if self.status.awake:
            self.status.last_heard = "(a whisper or a noise: left out)"
        self._back_to_awake()
        return True

    def handle_audio(self, audio) -> None:
        if self._only_breath(audio):
            return
        if self._transcriber is None and not self._no_model_here():
            # No speech model could be loaded when the program started. One may have been
            # installed since: try again, but now and then, not with every sound.
            # (With none installed and another computer doing the listening, there is
            # nothing to load: the sound goes there. So it does while a model that is
            # installed won't load.)
            if time.monotonic() - self._load_tried >= config.LOAD_AGAIN:
                self._load(self.settings.model)
            if self._transcriber is None and self._offload is None:
                return
        awake = self.status.awake
        prompt = hint = before = ""
        prose = False
        exact = {}  # {"exact": True} when the listening leans on the prompt: see Transcriber
        if awake and self.status.spelling:
            self.status.state = State.THINKING
            self.on_change()
            prompt = spelling.PROMPT
            exact = {"exact": True, "letters": True}
        elif awake:
            self.status.state = State.THINKING
            self.on_change()
            context = self.targets.request({"op": "context"})
            self.status.writer_ready = bool(context.get("ok"))
            self._typing_into(self.targets.name)
            if self._coding(context) and coding.where(context.get("before", ""))[0] != "comment":
                prompt = coding.prompt(self._names(), self._scope)
                exact = {"exact": True, "code": True}
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
        # What is measured of a short phrase belongs to this hearing and no other: a
        # Whisper hearing measures nothing, and must not be left with the figures of
        # whatever a Parakeet model last heard (an earlier phrase, a second opinion, a
        # voice test, another computer's phrase).
        if getattr(self._transcriber, "measured", None) is not None:
            self._transcriber.measured = None
        text = ears.transcribe(sound, awake, hint + prompt, **exact)
        measured = getattr(ears, "measured", None)
        # The person's codes, such as part numbers, are put in as they spelled them wherever
        # their letters and figures were written: there is no doubt about those to settle.
        names = vocabulary.names(self.settings.words)
        if hint and text:
            text = vocabulary.spell_codes(text, self.settings.words)
        if hint and vocabulary.mentions(text, names):
            # The hint is strong enough to turn an ordinary word into one of the person's
            # own. Hear it again without, and keep their word only where it fits.
            plain = vocabulary.spell_codes(ears.transcribe(sound, awake, prompt),
                                           self.settings.words)
            settled = vocabulary.settle(text, plain, before, names, self.lexicon)
            log("own word heard: " + ("kept" if vocabulary.mentions(
                settled, names) else "an ordinary word after all"))
            text = settled
        elif hint and text and not isinstance(
                interpret(text, True, self.settings.disabled_commands()), Command):
            # The hint brought none of the person's words: a recogniser that can't take a
            # hint, or one that didn't follow it. Put one in where what was written
            # sounds like it and a name fits. Never in a command: "Undo." is not "Andy".
            text = vocabulary.by_sound(text, before, names, self.lexicon)
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
        # Kept until the next phrase, in memory only, in case this one turns out to have
        # been a noise and is said to be: see "that was a noise".
        self._heard_sound = (sound, text, getattr(ears, "dictation_name", ""),
                             measured) if awake and text else None
        self.handle_text(text, awake)

    def _checked(self, text: str, sound, prompt: str) -> str:
        """`text` as a second recogniser lets it stand, or as a third settled it where the
        two differed. See opinions.py. They listen where the first did: on the other
        computer if it has them, else on this one."""
        offload = self._offload
        there = offload is not None and bool(offload.there)
        first = (offload.model_there if there else "") or getattr(
            self._transcriber, "dictation_name", "")
        # The spoken signs that are switched on are not for the opinions to argue over.
        # (One that is switched off is only words, like any others.)
        off = set(self.settings.spoken_off())
        said = sorted((phrase.split() for phrase, _ in SPOKEN if phrase not in off),
                      key=len, reverse=True)
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
                reply = self._offload.client.hear("phrase", sound, True, prompt, name, (), quickly,
                                                  speech_only=self.settings.enabled("speech_only"))
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
            self._letters_ahead()
            self._back_to_awake()
            return
        if isinstance(action, Command) and action.name in ("wake", "sleep"):
            said = plain_words(text)  # the one word, where that was what was said
            long = "wake up" if action.name == "wake" else "go to sleep"
            self.status.last_heard = said if said in SHORT_COMMANDS else long
            (self.wake if action.name == "wake" else self.sleep)()
            return
        if self._answered(text, awake):
            return
        typed = self._shortcut(text) if awake else None
        steps = self._steps(typed) if typed is not None else None
        if steps:
            # One of the person's own commands: said by itself, it does what they wrote.
            self._own_command(text, steps)
            self._back_to_awake()
            return
        if typed is not None:
            # One of the person's own shortcuts: said by itself, it types their text,
            # exactly as they wrote it, fitted to what is before it like anything else.
            self.status.last_heard = text
            first, _, rest = typed.partition("\n")
            reply = self._dictate(first, exact=True, as_written=True,
                                  then="\u2028" + rest.replace("\n", "\u2028") if rest else "")
            self._note(reply)
            self._typed_sound = None
            log(f"shortcut, {len(typed)} characters: {outcome(reply)}")
            self._back_to_awake()
            return
        if isinstance(action, Command) and action.name == "click":
            # A button, a link, a tick box or a menu of the program in front, by its name.
            # If nothing there has the name, those were only words, and are typed.
            if self._click(text, action.arg):
                self._back_to_awake()
                return
            action = Dictation(text)
        if isinstance(action, Command) and action.name == "app":
            # For this program's own windows. "Close that window" with none of them open
            # is only words, and is typed.
            if action.arg == "close" and not self.status.own_windows:
                action = Dictation(text)
            else:
                self.status.last_heard = text
                log(f"command app {action.arg}")
                self.on_event("app:" + action.arg)
                self._back_to_awake()
                return
        if isinstance(action, Command):
            self.status.last_heard = text
            self._last_typed = None       # a command in between: see _dictate
            # "Press enter" is the Enter key: a new paragraph. So is "enter" by itself,
            # where that has been switched on.
            name = "press_enter" if action.name == "enter" else action.name
            reply = {"why": "unknown request"}
            if name == "noise":
                reply = self._was_noise()
            elif name == "delete_words":
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
                    # An empty line selects nothing, and "delete" with nothing selected
                    # would take out the last phrase said: there the line itself goes.
                    chosen = self.targets.request({"op": "context"}).get("selected")
                    reply = self.targets.request({"op": "command", "name": "delete"} if chosen
                                                 else {"op": "command", "name": "backspace",
                                                       "arg": "1"})
            if reply.get("why") == "unknown request":  # not a move, or an older extension
                reply = self.targets.request({
                    "op": "command", "name": name, "arg": action.arg,
                    "nearest": not self.settings.enabled("choose_numbers"),
                })
            older = name == "correct" and reply.get("why") == "unknown command"
            if older:
                # A program whose link was made before "correct": the words are
                # highlighted all the same, and the cursor stays with them.
                name = "select"
                reply = self.targets.request({
                    "op": "command", "name": name, "arg": action.arg,
                    "nearest": not self.settings.enabled("choose_numbers"),
                })
            if (name in ("select", "correct") and reply.get("why") == "can't find that"
                    and not reply.get("sounds_tried")):
                # A program that looks for the words itself looks for exactly those. Ask
                # again for the same numbers written the other way and for words that
                # sound the same: "two" may be "2" in the document.
                # Initials first, where the recogniser wrote them with dots. "U.S." is the
                # one word "us" by now, but a program that looks for the words itself
                # takes the dots for breaks between words, and finds it only as "u s".
                dotted = interpret(text.replace(".", " "), awake, self.settings.disabled_commands())
                dotted = [dotted.arg] if (isinstance(dotted, Command) and dotted.name == action.name
                                          and dotted.arg != action.arg) else []
                for other in dotted + variants(action.arg):
                    again = self.targets.request({
                        "op": "command", "name": name, "arg": other,
                        "nearest": not self.settings.enabled("choose_numbers"),
                    })
                    if again.get("ok"):
                        reply = again
                        break
            tab = {"op": "command", "name": "tab"}
            if name == "tab" and reply.get("why") == "unknown command":
                # Where there is no Tab command, a tab character does the same job.
                tab = {"op": "insert", "text": "\t"}
                reply = self.targets.request(tab)
            if name == "tab" and reply.get("ok") and action.arg.isdigit():
                # "Tab three times": the key again, the same way, for the rest of the count.
                for _ in range(int(action.arg) - 1):
                    if not self.targets.request(tab).get("ok"):
                        break
            if name == "press_enter" and reply.get("why") == "unknown command":
                # Where Enter isn't known as a command, it is a new paragraph.
                reply = self.targets.request({"op": "command", "name": "new_paragraph"})
            if action.name in ("select", "correct") and reply.get("why") == "can't find that":
                # Words that aren't there to be selected: most likely a sentence that
                # begins with "Select" or "Correct". It is typed like any other, as
                # Dragon does.
                log(f"command {action.name}: can't find that, so it is typed")
                action = Dictation(text)
            else:
                if reply.get("choices", 0) > 1:
                    self._start_choosing(reply["choices"])
                self._selected_that = action.name == "select_last" and bool(reply.get("ok"))
                self._note(reply)
                self._say_how_it_went(action, text, reply)
                typed = getattr(self, "_typed_sound", None)
                if typed and reply.get("ok") and action.name in ("scratch", "undo", "delete"):
                    self._typed_sound = (*typed[:5], True, *typed[6:])  # taken back already
                if older and reply.get("ok"):
                    self.status.last_heard += ("  (the cursor will stay there: this program's "
                                               "Linux Speaking extension is an older one)")
                log(f"command {action.name}: {outcome(reply)}"
                    + (", and the words it was said over are back" if reply.get("restored") else "")
                    + (", as select: the program's extension is older" if older else ""))
        if isinstance(action, Dictation) and self.status.commands_only:
            # Commands only: what is no command is not typed, and is not kept. Said, but
            # not with every phrase: a room full of talk is what the choice is for.
            self.status.last_heard = f"{brief(text)}  (commands only: not typed)"
            self._typed_sound = None
            self.tell("That was no command, so nothing was typed: \"Commands only\" is "
                      "ticked in Settings.", every=60.0)
            log(f"commands only, {len(text)} characters: not a command, not typed")
        elif isinstance(action, Dictation):
            self.status.last_heard = text
            reply = self._dictate(action.text)
            self._note(reply)
            # The sound these words were written for, and whether they are still there.
            self._typed_sound = (*self._heard_sound, time.monotonic(), False, self.targets.name) \
                if reply.get("ok") and getattr(self, "_heard_sound", None) else None
            if reply.get("too_far"):
                self.status.last_heard += "  (too far to go back: the cursor is after the new words)"
            log(f"dictation, {len(action.text)} characters: {outcome(reply)}"
                + speech.told(self._typed_sound[3] if self._typed_sound else None)
                + (", and the cursor went back" if reply.get("back") else "")
                + (", and the cursor stayed: too far to go back" if reply.get("too_far") else ""))
        if self.status.state in (State.THINKING, State.HEARING):
            self.status.state = State.AWAKE
        self.on_change()

    # ---- choosing between numbered matches ----------------------------------
    def _say_how_it_went(self, action, text: str, reply: dict) -> None:
        """A word on the screen about a command that leaves nothing to see, or failed.
        A change to the text shows itself; these don't."""
        said = plain_words(text)
        if reply.get("ok"):
            if reply.get("choices", 0) > 1:
                self.tell(f"Say a number, 1 to {reply['choices']}, or \"cancel\".")
            elif action.name in ("select", "correct"):
                self.tell(f"Selected: {action.arg}",
                          logged=f"Selected: ({len(action.arg)} characters)")
            return
        why = reply.get("why", "")
        if why in NOWHERE:
            return                        # said already: see _note
        # (In the log the command goes by its name: what was said may have words of the
        # document in it, as "select the black cat" has.)
        if why == "unknown command":
            self.tell(f"{self.targets.name or 'This program'} can't do \"{said}\".", "problem",
                      logged=f"{self.targets.name or 'this program'} can't do {action.name}")
        elif why:
            self.tell(f"\"{said}\" couldn't be done: {why}.", "problem",
                      logged=f"{action.name} couldn't be done: {why}")

    # ---- commands only, and commands of the person's own --------------------------------
    def _apply_mode(self) -> None:
        """Commands only, where nothing is typed and only commands are acted on, or the
        usual way, where what is no command is dictation: as it is chosen in Settings.
        It is a setting and not something said: somebody who wants this program for its
        commands alone ticks it once, and nothing heard can then switch typing back on."""
        wanted = self.settings.enabled("commands_only")
        if wanted != self.status.commands_only:
            self.status.commands_only = wanted
            log("commands only: nothing is typed" if wanted else "dictation and commands")
            self.on_change()

    def _steps(self, written: str):
        """The steps of one of the person's own commands, as it is written: None if it
        is a shortcut that types a text."""
        try:
            return actions.parse(written)
        except ValueError:
            return None      # Settings left out what it couldn't read: this is one typed in since

    def _own_command(self, text: str, steps: list) -> None:
        """Do one of the person's own commands, or ask first, or say why not."""
        self.status.last_heard = text
        self._last_typed = None           # a command in between: see _dictate
        self._typed_sound = None
        if actions.runs_programs(steps) and not self.settings.enabled("run_programs"):
            self.tell(f"\"{brief(text)}\" runs a program, and that is switched off. To allow "
                      "it, tick \"Let my own commands run programs\" in Settings.", "problem",
                      logged="a command that runs a program was said: switched off")
            log(f"own command ({actions.kinds(steps)}): running programs is switched off")
            return
        if steps[0] == ("ask",):
            self._asked = (text, steps[1:], time.monotonic() + config.ASK_SECONDS)
            self.status.last_heard = f"{text}  (say \"yes\" to do it)"
            self.tell(f"{brief(text).capitalize()}? Say \"yes\" to do it. Anything else "
                      "leaves it.", logged="a command asks first")
            log(f"own command ({actions.kinds(steps[1:])}): asking first")
            return
        self._carry_out(steps)

    def _answered(self, text: str, awake: bool) -> bool:
        """Whether `text` was the "yes" that a command was waiting for: then it is done.
        Anything else, or "yes" said too late, leaves it, and is heard as what it is."""
        asked, self._asked = getattr(self, "_asked", None), None
        if not asked or not awake or not text.strip():
            if asked and time.monotonic() < asked[2] and not text.strip():
                self._asked = asked       # nothing was heard: it is still waiting
            return False
        said, steps, until = asked
        late = time.monotonic() > until
        if late or plain_words(text) not in YES:
            self.tell(f"\"{brief(said)}\" was left.", logged="the command that asked was left")
            log("own command: not done, no yes")
            if late or not (plain_words(text) in NO or is_cancel(text)):
                return False              # something else was said: it is heard as usual
            self.status.last_heard = text  # "no" was the answer, and is not typed
            self._back_to_awake()
            return True
        self.status.last_heard = text
        self._carry_out(steps)
        self._back_to_awake()
        return True

    def _carry_out(self, steps: list) -> None:
        """Do the steps of one of the person's own commands, in order, up to the first
        that can't be done: that one is said."""
        doer = self._doer
        where = ""    # the program the keys went to, where that can be told: for the log
        for count, step in enumerate(steps, 1):
            try:
                if step[0] == "keys":
                    for at, chord in enumerate(step[1]):
                        if at:
                            doer.wait(actions.BETWEEN_KEYS)
                        where = doer.press(chord) or where
                elif step[0] == "open":
                    doer.open(step[1])
                elif step[0] == "run":
                    doer.run(step[1])
                elif step[0] == "wait":
                    doer.wait(step[1])
                elif step[0] == "type":
                    top, _, rest = step[1].partition("\n")
                    reply = self._dictate(top, exact=True, as_written=True,
                                          then="\u2028" + rest.replace("\n", "\u2028") if rest else "")
                    self._note(reply)
                    if not reply.get("ok"):
                        raise actions.ActionError("")     # said already: see _note
            except actions.ActionError as e:
                if str(e):
                    self.tell(str(e), "problem", logged=f"a step of a command failed: {step[0]}")
                log(f"own command ({actions.kinds(steps)}): step {count}, {step[0]}, failed")
                return
            except Exception as e:  # nothing here may stop the listening
                self.tell(f"That command's step {count} ({step[0]}) went wrong. The log "
                          "says how.", "problem")
                log(f"own command ({actions.kinds(steps)}): step {count}, {step[0]}: "
                    f"{type(e).__name__}: {e}")
                return
            said = actions.done(step)
            if said:
                self.tell(said, logged=f"a command did: {step[0]}")
                self._note_what_came_forward(step[0])
        log(f"own command ({actions.kinds(steps)}): done" + (f", keys to {where}" if where else ""))

    def _letters_ahead(self) -> None:
        """The spelling box is being opened: the model that hears letters is loaded now,
        to one side, so that the first letter isn't kept waiting for it. (Not where
        another computer does the listening: it is that one's model then.)"""
        ready = getattr(getattr(self, "_transcriber", None), "ready_for_letters", None)
        if ready is not None and getattr(self, "_offload", None) is None:
            threading.Thread(target=ready, daemon=True).start()

    def _click(self, text: str, name: str) -> bool:
        """Press what is called `name` in the window in front. True if that was done, or
        if it was there and couldn't be pressed (which is said): False if nothing there
        has the name, and the phrase is to be typed as the words it then is."""
        press = getattr(self, "_presser", None) or clicking.click
        try:
            reply = press(name)
        except clicking.CantClick as e:
            self.status.last_heard = text
            self.tell(str(e), "problem", logged="a click couldn't be done")
            log("command click: there, but it couldn't be pressed")
            return True
        except Exception as e:   # nothing here may stop the listening
            log(f"command click: {type(e).__name__}: {e}")
            return False
        if not reply.get("ok"):
            log(f"command click: {reply.get('why', 'not done')}, so it is typed"
                + (f" ({reply['looked_at']} things looked at)" if "looked_at" in reply else ""))
            return False
        self.status.last_heard = text
        self._last_typed = None           # a command in between: see _dictate
        self._typed_sound = None
        where = clicking.in_front()
        log(f"command click: {reply.get('kind', 'pressed')}" + (f", in {where}" if where else ""))
        return True

    def _note_what_came_forward(self, kind: str) -> None:
        """A moment after a command opened or ran something, put in the log which program
        is in front: whether the new window came forward can't be seen from here, and it
        is the first thing to know when somebody says it didn't. Its name only."""
        look = getattr(self._doer, "in_front", None)
        if look is None or not look():
            return                      # it can't be told on this system

        def noted() -> None:
            log(f"after a command's \"{kind}\", in front: {look() or 'not known'}")

        timer = threading.Timer(1.5, noted)
        timer.daemon = True
        timer.start()

    def _shortcut(self, text: str):
        """The text one of the person's own shortcuts types, if `text` is one: or None."""
        mine = getattr(self.settings, "shortcuts", None)
        if not mine:
            return None
        said = plain_words(text)
        for phrase, typed in mine.items():
            if plain_words(phrase) == said:
                return typed
        return None

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
            if (not is_cancel(text) and len(plain_words(text).split()) <= config.CHOICE_WORDS
                    and self._shortcut(text) is None
                    and not isinstance(interpret(text, True, self.settings.disabled_commands()),
                                       Command)):
                # One word that is neither a number nor a command: most likely the number
                # was misheard ("to", "for", "tree"). Typing it into the document, over
                # what the numbers are showing on, would be worse than asking again.
                # Anything longer is somebody carrying on, and is typed as it always was.
                count = self.status.choosing
                self.status.last_heard = text + f"  (say a number, 1 to {count}, or \"cancel\")"
                self.tell(f"That wasn't a number. Say a number, 1 to {count}, or \"cancel\".")
                log("a single word said while numbers were showing: not typed")
                self._back_to_awake()
                return True
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

    def _was_noise(self) -> dict:
        """ "That was a noise": what was last written was no speech. It is taken back,
        unless it already has been, and its sound is kept (speech.keep_noise) so that
        the rules for telling noise from speech can be tried on it."""
        typed, self._typed_sound = getattr(self, "_typed_sound", None), None
        if typed is None or time.monotonic() - typed[4] > config.NOISE_SECONDS:
            return {"ok": False, "why": "nothing was just written"}
        sound, text, model, measured, _, gone = typed[:6]
        where = typed[6] if len(typed) > 6 else ""
        # "Scratch that" takes back the last thing said in whichever program is in front
        # now. If that is no longer the one the noise was written in, its last phrase
        # was real, and is left: the sound is kept all the same.
        self.targets.pick()
        elsewhere = bool(where) and not gone and self.targets.name != where
        if elsewhere:
            self.tell(f"That sound is kept. What it was written as is in {where}: take it "
                      "out there.")
        reply = {"ok": True} if gone or elsewhere else self.targets.request(
            {"op": "command", "name": "scratch"})
        try:
            speech.keep_noise(config.NOISE_DIR, sound, text, model, measured)
            log(f"kept as a noise: a sound of {len(sound) / config.RATE:.1f} s that "
                f"{len(text)} characters were written for" + speech.told(measured))
        except OSError as e:
            log(f"the noise could not be kept: {e}")
        return reply

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

    def _dictate(self, raw: str, exact: bool = False, then: str = "",
                 as_written: bool = False) -> dict:
        """Fit a phrase to the text around the cursor, then have the program in front
        insert it. `then` is more text to go straight after it, exactly as it is.
        `as_written` keeps every letter of the phrase as it was given, small or capital,
        wherever it lands: for a shortcut, whose text may be an address.

        The fitting is done here, not in the extension, so changes to the rules and
        settings never need LibreOffice to be restarted.
        """
        spoken_off = [p for p, _ in SPOKEN] if exact else self.settings.spoken_off()
        context = self.targets.request({"op": "context"})
        if not context.get("ok"):
            return context
        before, after = context.get("before", ""), context.get("after", "")
        place, comment = coding.where(before) if self._coding(context) and not exact else ("", "")
        plain = not place and not exact and not then   # ordinary dictated prose
        if place in ("code", "string"):
            # Source code has its own rules, and knows the names already in the file.
            ins = coding.fit_code(raw, before, after, self._names(), self._scope)
        else:
            # Prose, including a comment in a source file, which starts after its "//".
            #
            # Whether the last sentence end was said aloud is remembered from one phrase
            # to the next, because the text can't tell: "at 3 p.m." ends the same whether
            # "full stop" was said after it or the speaker only paused. Said, the next
            # phrase starts a sentence; not said, it carries on. It is only trusted while
            # the text before the cursor still ends with what was last typed here.
            if not exact and self.settings.enabled("money"):
                raw = money.in_figures(raw, before)   # sums of money one way: see money.py
            last = getattr(self, "_last_typed", None)   # (program, the end of what was typed, said)
            carried = None
            if (plain and last and last[0] == self.targets.name
                    and before.rstrip(" ").endswith(last[1])):
                carried = last[2]
            ins = fit(raw, comment if place == "comment" else before, after,
                      self.lexicon, spoken_off=spoken_off, names=self.settings.words,
                      keep_final=self.keep_final or exact or self.settings.enabled("keep_final"),
                      greeting_comma=exact or not self.settings.enabled("no_greeting_comma"),
                      after_said_end=carried)
            # (A word that was spelled keeps its last full stop: "e.g." was spelled so.)
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
        if exact and (as_written or any(c.isupper() for c in raw)):
            at = text.lower().find(raw.lower())  # keep the capitals exactly as spelled
            if at >= 0:
                text = text[:at] + raw + text[at + len(raw):]
        if then:
            text = text.rstrip(" ") + then
        said_end = bool(getattr(ins, "said_end", False))
        if plain and not text and said_end and not (
                ins.delete_before or ins.delete_after or ins.capitalise_next):
            # "Full stop" said by itself where a stop already stands ("at 3 p.m."): that
            # one does for both, nothing is typed, and it is remembered as said.
            last = getattr(self, "_last_typed", None)
            self._last_typed = (self.targets.name, last[1] if last else before.rstrip(" ")[-40:], True)
            return {"ok": True}
        reply = self.targets.request({
            "op": "insert", "text": text, "delete_before": ins.delete_before,
            "delete_after": ins.delete_after, "capitalise_next": ins.capitalise_next,
        })
        if reply.get("why") == "unknown request":  # an extension from before "insert"
            reply = self.targets.request({"op": "dictate", "text": raw, "spoken_off": spoken_off})
        typed = text.rstrip(" ")[-40:]
        self._last_typed = ((self.targets.name, typed, said_end)
                            if plain and typed and reply.get("ok") else None)
        return reply

    def _typing_into(self, name: str) -> None:
        if name != self.status.target:
            log(f"typing into {name or 'nothing'}")
        self.status.target = name

    def _note(self, reply: dict) -> None:
        nowhere = not reply.get("ok") and reply.get("why") in NOWHERE
        self.status.writer_ready = not nowhere
        self.status.target_known = True
        self._typing_into(self.targets.name)
        if nowhere:
            # Nothing was in front to type into, and the words are gone: say so where it
            # will be seen, once a minute at most, and say what would work.
            self.status.last_heard += "  (nothing to type into)"
            self.tell(nothing_to_type_into(self.settings.enabled("other_apps")), "problem",
                      every=60)
            # And what each program answered, at most twice a minute, so the log shows why.
            now = time.monotonic()
            if now - self._explained_at > 30:
                self._explained_at = now
                log("nothing to type into. " + self.targets.describe())
        elif not reply.get("ok") and reply.get("why"):
            why = reply["why"]
            if why == "error" and reply.get("error"):
                # The program refused, and said why: a document that can't be changed.
                why = f"{self.targets.name or 'the program'} wouldn't take it: {brief(reply['error'])}"
            self.status.last_heard += f"  ({why})"


# What a program answers when it isn't there to be typed into.
# What does as "yes" to a command of the person's own that asks first, and as "no". Not
# "yeah" or "okay": those are what a noise is most often written as.
YES = frozenset({"yes", "yes do it", "do it", "yes please", "yes go ahead", "go ahead"})
NO = frozenset({"no", "no thanks", "no thank you", "leave it", "don't", "do not", "stop"})
NOWHERE = ("writer not running", "writer not focused", "no writer document",
           "mail not running", "mail not focused", "mail not answering",
           "editor not focused")


def nothing_to_type_into(others_too: bool) -> str:
    """What to tell somebody whose words had nowhere to go: where they can go."""
    known = "Word, Outlook or VS Code" if config.WINDOWS else "Writer, Thunderbird, Kate or VS Code"
    return (f"Nothing to type into. Click in {known}"
            + (", or in a text box of another program." if others_too else
               ", or tick \"Dictate into other programs' text boxes\" in Settings."))


def brief(text, most: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= most else text[:most - 3] + "..."


def named(model: str) -> str:
    """A speech model by the name people know it by: "Small", "Parakeet Unified"."""
    try:
        given = training.label(config.MODEL_DIR, model)   # one retrained here has a name of its own
    except OSError:
        given = ""
    return (given or model_label(model)[1]).split(":")[0].split("  (")[0].strip() or model


def no_model(error) -> str:
    """Why there is no speech model to recognise with, and what to do, in plain words."""
    press = ("Open Settings and press \"Install or remove models\u2026\", or have another "
             "computer do the listening: \"Another computer\", further down in Settings.")
    if isinstance(error, ImportError):
        return (f"A part the recogniser needs is missing ({getattr(error, 'name', '') or error}). "
                "Run the installer again.")
    if not available_models(config.MODEL_DIR):
        return "No speech model is installed. " + press
    return f"The speech model could not be loaded ({brief(error, 80)}). " + press


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
