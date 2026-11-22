"""Telling speech from other sounds, so that a rustle or a key press isn't written down.

Parakeet, given a short noise by itself, writes a word for it about one time in ten, and
the word is nearly always "yeah", or else "uh" or "okay". With real speech in the same
phrase it leaves a noise beside it alone. So it is the phrase that is nothing but a noise
which has to be caught, and loudness can't catch it: a rustle is as loud as a word.

A voice detector can. Silero's, a small neural network, comes with faster-whisper, which
already uses it for Whisper. It marks the stretches of a sound that are speech. Two things
are asked of a phrase that Parakeet has written words for:

- Is there anything like speech in it, on the detector's easy reading? If not, it was a
  noise, whatever was written.
- If what was written is only the words Parakeet makes of noises, is there clear speech
  behind them: a tenth of a second, on the detector's usual reading? If not, it was a
  noise. Somebody who really says "yeah" passes easily.

The figures come from trying it: some 750 phrases cut from recordings of things that are
not voices (typing, mouse clicks, a clock, sipping, dripping water), 400 one-word commands
spoken by many people, and 51 read sentences, all cut and turned up as dictation does it
and put through the app's own code. Parakeet Unified wrote words for 77 of the things,
nearly all "yeah", "uh" or "okay", and 75 of those were left out. Of 364 commands it had
heard rightly one was lost, and of the sentences none. Had the commands been noise words
themselves, the second question would have cost 3 of them. The usual Parakeet writes a
wider run of words for noises, and 37 of its 49 were left out, with no command lost.
Coughs, sneezes and laughs are made with the voice: about half of what is written for
those remains. Asking the detector takes about 6 thousandths of a second.

A third thing is asked, of the recogniser itself: how sure was it? It gives each piece
it writes a probability. Of real short speech (those commands, and 265 single words cut
from one person's read sentences) the least sure word was at 0.99 in the middle of the
range, and under 0.71 one time in ten. Of noises that had words written for them it was
at 0.51 in the middle, and over 0.83 one time in ten. So:

- A noise word by itself, even with clear speech behind it (a sneeze, a laugh, a sigh),
  stands only if the recogniser was sure of it.
- One or two words of any other kind, with no clear speech behind them, stand only if it
  was sure. A model retrained on single words (see training.py) writes all sorts of
  short words for a noise, "hit", "back", "hey", where the stock one writes "yeah".

Tried on the same sounds with three models, these two took what was still written for
the voiced noises from 9 of them to between 2 and 4, at the cost of one more of the 364
commands, and of 4 of the 265 single words, all of them a quarter of a second of "the"
or "and" cut out of a sentence.

The recorded noises are not everyone's, though. A rustle of clothing at a laptop's own
microphone may pass all of this. So whoever is dictating can say "that was a noise": what
was written is taken back, and the sound is kept on the computer (keep_noise, below), for
the rules to be tried against the noises that are really made there.
"""
from __future__ import annotations

import collections
import os
import re
import stat
import threading
import time
import wave

import numpy as np

from . import config, opinions

SOME = 0.3            # the detector's easy reading: is there anything like speech here?
CLEAR = 0.5           # its usual reading
CLEAR_SECONDS = 0.1   # how much clear speech has to stand behind a noise word
SURE_OF_NOISE_WORD = 0.8  # how sure the recogniser must be of a noise word by itself
FEW = 2               # so few words are doubted, of whatever kind, with no clear speech
SURE_OF_FEW = 0.75    # unless the recogniser was this sure of them
MOST_NOISES = 300     # how many sounds marked as noises are kept
LIST = "list.txt"     # beside them: each one's file, what it was written as, what was measured

# What Parakeet writes for a noise: an assent, a hesitation, a laugh. Hyphens left out.
NOISE_WORDS = opinions.MURMURS | frozenset("yeah yep yup uhhuh ho okay ok yo".split())

_unusable = False  # the detector can't be used at all, so nothing more is asked of it
_failures = 0      # how many times running it has failed to answer
MOST_FAILURES = 5  # after so many running it is taken to be broken, and not asked again


def only_noise_words(text: str) -> bool:
    """Whether `text` is nothing but the words Parakeet writes for a noise."""
    words = [opinions._key(word).replace("-", "") for word in text.split()]
    words = [word for word in words if word]
    return bool(words) and all(word in NOISE_WORDS for word in words)


def spoken(audio, threshold: float):
    """How many seconds of `audio` (numbers from -1 to 1 at config.RATE) the detector
    takes for speech, reading it at `threshold`. None if there is no detector to ask,
    or it didn't answer: then everything stands as it was written.

    A detector that isn't there (it didn't come with the install) is not asked again.
    One that is there and fails is: a failure may be of the moment (no memory to spare,
    say), and to give it up for that would leave noises written as words until the app
    was next started. Only when it has failed MOST_FAILURES times running is it taken to
    be broken."""
    global _unusable, _failures
    if _unusable:
        return None
    try:
        from faster_whisper import vad
    except Exception as e:
        _unusable = True
        print(f"the voice detector can't be used, so noises may be written as words: "
              f"{type(e).__name__}: {e}", flush=True)
        return None
    try:
        spans = vad.get_speech_timestamps(audio, vad.VadOptions(
            threshold=threshold, min_speech_duration_ms=0, min_silence_duration_ms=100,
            speech_pad_ms=0))
        seconds = sum(span["end"] - span["start"] for span in spans) / config.RATE
    except Exception as e:
        _failures += 1
        if _failures >= MOST_FAILURES:
            _unusable = True
            print(f"the voice detector has failed {_failures} times running and is not asked "
                  f"again, so noises may be written as words: {type(e).__name__}: {e}", flush=True)
        elif _failures == 1:              # said once for a run of them, not for each
            print(f"the voice detector didn't answer, so this phrase stands as it was written: "
                  f"{type(e).__name__}: {e}", flush=True)
        return None
    _failures = 0
    return seconds


PIECE_OF_SPEECH = 512     # the detector reads a sound in pieces of so many samples (32 ms)
_no_pieces = False        # it can't be read piece by piece here: see likelihoods()
_piece_failures = 0       # how many times running that has failed


_loaded = threading.Event()   # the detector has been loaded, or found not to be there
_loading = threading.Lock()   # (held for good once loading has started)


def ready_detector() -> None:
    """Load the detector if it isn't yet, on a thread of its own. Loading it brings in
    faster_whisper and much with it, and builds an onnxruntime session: done the first time
    a phrase is looked at, on the thread that reads the microphone, it held the reading up,
    and on Windows the sound read meanwhile was lost (the first phrase after a start, which
    is often "wake up")."""
    if _loaded.is_set() or not _loading.acquire(blocking=False):
        return

    def load():
        try:
            likelihoods(np.zeros(PIECE_OF_SPEECH, dtype=np.float32))
        finally:
            _loaded.set()
    threading.Thread(target=load, daemon=True).start()


def watched(audio):
    """likelihoods(), for the thread that reads the microphone: None (do without: the voice's
    pitch is looked for) until the detector is loaded, which this starts if nothing has."""
    if not _loaded.is_set():
        ready_detector()
        return None
    return likelihoods(audio)


def likelihoods(audio):
    """How likely the detector takes each 32 thousandths of a second of `audio` to be
    speech, from 0 to 1 (`audio` is numbers from -1 to 1 at config.RATE). The last piece
    ends where the sound ends: what is over, at the start, is left out. None if the
    detector isn't there or can't be read this way: whoever asks then does without.

    This is asked several times a second while a phrase is being taken down (see
    VoiceWatch), and is kept apart from spoken(), which is asked once of each phrase: if
    this way of reading the detector fails, that one goes on being used."""
    global _no_pieces, _piece_failures
    if _no_pieces:
        return None
    try:
        from faster_whisper import vad
        model = vad.get_vad_model()
    except Exception as e:
        _no_pieces = True
        print(f"the voice detector can't be used to see a voice stop, so a noisy room is "
              f"judged by the voice's pitch alone: {type(e).__name__}: {e}", flush=True)
        return None
    try:
        sound = np.asarray(audio, dtype=np.float32)
        sound = sound[len(sound) % PIECE_OF_SPEECH:]
        if not len(sound):
            return np.zeros(0, dtype=np.float32)
        marks = np.asarray(model(sound), dtype=np.float32).reshape(-1)
        if len(marks) != len(sound) // PIECE_OF_SPEECH:
            raise ValueError(f"{len(marks)} answers for {len(sound) // PIECE_OF_SPEECH} pieces")
    except Exception as e:
        _piece_failures += 1
        if _piece_failures >= MOST_FAILURES:
            _no_pieces = True
            print(f"the voice detector has failed {_piece_failures} times running at seeing a "
                  f"voice stop and is not asked that again: {type(e).__name__}: {e}", flush=True)
        return None
    _piece_failures = 0
    return marks


def not_speech(text: str, audio, spoken=spoken, sure=None, numbers=None) -> str:
    """Why `text`, written for `audio`, is taken for a noise and not for speech: or ""
    if it stands. `spoken` is the detector, which a test can stand in for. `sure` is how
    sure the recogniser was of its least sure word, from 0 to 1, if it said. `numbers`,
    if given, is filled with what was measured, for the log."""
    if not text.strip():
        return ""
    some = spoken(audio, SOME)
    if some is None:
        return ""
    if some <= 0:
        return "nothing like speech in it"
    noise_words = only_noise_words(text)
    few = len(text.split()) <= FEW
    doubted = noise_words or (few and sure is not None and sure < SURE_OF_FEW)
    if not (doubted or (few and numbers is not None)):
        return ""                         # the usual reading isn't taken unless it matters
    clear = spoken(audio, CLEAR)
    if clear is None:
        return ""
    if numbers is not None:
        numbers.update(clear=round(clear, 2), sure=None if sure is None else round(sure, 2))
    if noise_words:
        if clear <= CLEAR_SECONDS:
            return "a noise word, with no clear speech behind it"
        if sure is not None and sure < SURE_OF_NOISE_WORD:
            return "a noise word that the recogniser wasn't sure of"
    elif clear <= CLEAR_SECONDS and sure is not None and sure < SURE_OF_FEW:
        return "a word or two that the recogniser wasn't sure of, with no clear speech behind"
    return ""


# ---- a voice, or only breath ---------------------------------------------------------
# Somebody who is dictating may want to whisper to the person beside them, or to
# themselves, without it being written. A whisper is speech to every recogniser, and to
# the voice detector above as well. What it lacks is the voice itself. A voice has a
# pitch: the sound repeats itself every few thousandths of a second, as the vocal cords
# open and close. A whisper is breath shaped by the mouth, and repeats nothing.
#
# So a phrase is looked at in pieces of 40 thousandths of a second, in the part of the
# sound where pitch shows (80 to 1000 Hz: below that is breath on the microphone, which
# is a slow wave and so looks like itself a moment later too). A piece has voice in it if
# it is like itself one period on, for some period a voice can have, if the pieces beside
# it agree about that period, and if it is among the loud pieces of the phrase. What is
# asked of the phrase is how much of its loud part is voice.
#
# Tried on 300 sentences and 349 single words read by one man, 801 one-word commands
# from many people, 205 acted sentences in an ordinary, a careful and a subdued voice,
# and 160 acted whispered ones (these last two from a public set of studio recordings),
# cut as dictation cuts them: see VOICED, below, for what came of it. Real whispers are
# not free of voice: a tenth of a second here and there is common, which is why it is a
# share that is asked for and not any voice at all.
PIECE, STEP = 640, 160      # a piece of the sound and how far on the next starts, in samples
PITCH_BAND = (80, 1000)     # Hz: where a voice's pitch shows
PERIODS = (config.RATE // 400, config.RATE // 60)  # a voice's period in samples, 400 to 60 Hz
ALIKE = 0.6                 # how like itself, one period on, a piece with voice in it is
LOUD = 20.0                 # dB under the loudest piece: quieter pieces are not counted
NEAR_BEST = 0.05            # peaks this close to the best are as good: the shortest is the pitch
DRIFT = 0.15                # how much the period may change from one piece to the next
RUN = 3                     # voice lasts: so many pieces in a row, or it was chance
# Of the whispered sentences 2 in 160 reached this share, and of pieces of them the length
# of a word about 1 in 10. Of the spoken sentences every one did, and of single words that
# a recogniser had heard rightly 94 in 100: the ones lost were said very short, or in a
# noisy room, where the room counts as part of the phrase. At 0.2 it was 6 whispered
# sentences in 160, 1 short piece in 6, and 96 single words in 100. The whispers were one
# person's, in a studio: the engine logs what it measures of each phrase near the line
# (figures only), so that the line can be moved to suit a real desk and microphone.
VOICED = 0.25               # the share of a phrase's loud part that is voice, if it was said aloud


def voiced(audio) -> float:
    """How much of the loud part of `audio` is voice, from 0 to 1. Somebody talking
    scores a half or more; a whisper, a rustle or a click scores little or nothing."""
    sound = np.asarray(audio, dtype=np.float64)
    if len(sound) < PIECE:
        return 0.0
    # Only the part of the sound where pitch shows.
    whole = np.fft.rfft(sound)
    pitch = np.fft.rfftfreq(len(sound), 1.0 / config.RATE)
    low = np.fft.irfft(np.where((pitch >= PITCH_BAND[0]) & (pitch <= PITCH_BAND[1]), whole, 0),
                       len(sound))
    count = 1 + (len(sound) - PIECE) // STEP
    at = np.arange(PIECE)[None, :] + STEP * np.arange(count)[:, None]
    pieces = sound[at]
    pieces = pieces - pieces.mean(axis=1, keepdims=True)
    level = (pieces ** 2).mean(axis=1)
    if level.max() <= 0:
        return 0.0
    loud = level >= level.max() * 10 ** (-LOUD / 10)
    # How like itself each piece is, one period on, for every period a voice can have:
    # the two stretches multiplied together, over what each amounts to by itself.
    low = low[at]
    lags = np.arange(PERIODS[0] - 1, PERIODS[1] + 2)
    together = np.fft.irfft(np.abs(np.fft.rfft(low, 1024, axis=1)) ** 2, axis=1)[:, lags]
    squares = np.cumsum(low ** 2, axis=1)
    first = squares[:, PIECE - 1 - lags]
    second = squares[:, -1:] - squares[:, lags - 1]
    alike = together / np.sqrt(np.maximum(first * second, 1e-30))
    # Only a true peak counts: a slow wave is like itself at every short step, which is
    # not a pitch. And a sound that repeats every period repeats every two and three as
    # well, so of the peaks about as good as the best it is the shortest that is taken:
    # or the period would seem to jump about from one piece to the next.
    peak = (alike[:, 1:-1] >= alike[:, :-2]) & (alike[:, 1:-1] >= alike[:, 2:])
    alike = np.where(peak, alike[:, 1:-1], -1.0)
    best = alike.max(axis=1)
    period = lags[1:-1][(alike >= best[:, None] - NEAR_BEST).argmax(axis=1)]
    has = (best >= ALIKE) & loud
    total = run = 0
    for n in range(count):
        if has[n] and (run == 0 or abs(period[n] - period[n - 1]) <= DRIFT * period[n - 1]):
            run += 1
            continue
        if run >= RUN:
            total += run
        run = 1 if has[n] else 0
    if run >= RUN:
        total += run
    return total / max(1, int(loud.sum()))


BEGAN_LATE, GONE = "the voice began late", "the voice has gone"


class VoiceWatch:
    """Whether there is still a voice in what is being listened to: looked at several
    times a second, while a phrase is being taken down.

    A phrase ends at the pause after it, and a pause is quiet. In a room that isn't
    quiet (a fan that roars, keys being pressed, wind on the microphone) no pause comes:
    the phrase ran on to its limit, twenty seconds, before anything was done with what
    had been said. But the voice can be seen to have stopped though the sound goes on.

    feed() is given each frame of the phrase. It answers GONE when a voice has been
    heard in the phrase and none has been for GONE_AFTER seconds: the phrase is over.
    And it answers BEGAN_LATE when a voice is first heard well into a phrase that the
    room's noise had started: what came before it is only the room.

    The voice detector is asked (likelihoods(), above): it says of each 32 thousandths
    of a second whether it is speech. So the moment the voice stopped is known closely,
    and the wait after it need be little longer than the pause that ends a phrase in a
    quiet room. It used to be the voice's pitch that was looked for, a second of sound
    at a time, four times a second, and that was slow and could be blind:

    - A second of sound still has voice in it for most of a second after the voice has
      stopped, and the wait was counted from the last such second. A word said in a room
      where keys were being pressed was acted on 2.2 seconds after it ended, where in a
      quiet room it is 0.66.
    - A short word among louder noises might never be seen at all: voice had to make up
      a share of the loud part of the second, and the noises were the loud part. Nothing
      then ended the phrase but its limit, twenty seconds. Of 65 short words among key
      presses that was 3 to 11, depending on how hard the keys were pressed and how
      quietly the word was said.
    - It was not given the start of the phrase, which is kept from before the sound was
      loud enough to begin one: of a word a quarter of a second long, that is most.

    With the detector those are 0.82 to 0.84 seconds (0.9 for one word in ten, 1.04 at
    the most), and none or one of the 65. (Measured on one man's recorded sentences, 65
    short words cut from them or made by a speaking program, and 40 of the sentences,
    with made noises mixed in: steady, swelling and sinking, coming on with the voice,
    key presses, and other recordings as people talking; a loud voice and a quiet one.
    Not in a real room.) The price: in such a room a sentence with a long pause in it is
    now cut there, as it is in a quiet room. Of the 40 sentences that was 4 or 5 among
    key presses, where it had been one or none, and is 5 or 6 in a quiet room.

    Other people talking are speech to the detector too. What tells them from the one
    who is dictating is how loud they are at the microphone. So a phrase also ends when
    for SOFT_AFTER seconds there has been talk, but none as much as QUIETER of the
    loudness of the speech this phrase has had. Behind a loud voice, talk a tenth as
    loud had kept 6 sentences in 24 and 16 short words in 45 from being ended within
    eight seconds: now none and one, and the phrase is ended about 1.2 seconds after the
    voice. Talk a fifth as loud is told from the voice only some of the time, and louder
    than that hardly ever: nothing here can tell it from the person going on. It might
    be the same person, in an aside: so of such a phrase nothing is left out (`soft`
    says so), and the softer talk begins a phrase of its own at once. (At 0.3 for
    QUIETER, talk a fifth and a third as loud is told apart far more often: but somebody
    who trails off at a quarter of their loudness has the sentence cut in two.)

    Where the detector isn't there to ask, the pitch is looked for as before.

    Nothing is ever cut for want of a voice that was never there: somebody who dictates
    in a whisper is listened to as before."""

    SPAN = 1.5        # seconds of sound each look takes in
    EVERY = 0.1       # seconds between one look and the next
    FIRST = 0.3       # seconds of a phrase there have to be before it is looked at
    SPEECH = 0.5      # how likely the detector has to take a piece to be speech
    RUN = 3           # so many pieces in a row are a voice (a tenth of a second): fewer may be a click
    GONE_AFTER = 0.7  # seconds without a voice, once there has been one, that end the phrase
    QUIETER = 0.2     # how loud, beside the speech of this phrase, talk has to be to be its voice
    SOFT_AFTER = 1.2  # seconds of nothing but far softer talk that end it
    LATE = 2.0        # a voice first heard later than this began in a phrase the room had started
    BEFORE = 1.5      # seconds kept from before the look that first heard a voice
    AFTER = 0.4       # and seconds kept after the voice was last heard: of 65 short words said
                      # quietly over a noise half as loud, a quarter of a second cut one short
    # Without the detector, by the voice's pitch (see voiced()):
    WINDOW = 1.0      # seconds of sound each look takes in
    SLOWLY = 0.25     # seconds between one look and the next
    HEARD = 0.15      # the share of a look's loud part that has to be voice
    GONE_SLOWLY = 1.25  # seconds without a voice, counted from the last look that heard one

    def __init__(self, rate: int = config.RATE, frame: int = config.FRAME, detector=watched):
        self.per_second = rate / frame
        self.frame = frame
        self.detector = detector
        self.recent = collections.deque(maxlen=round(max(self.SPAN, self.WINDOW) * self.per_second))
        self.by_pitch = False       # the detector couldn't be asked: the pitch is looked for
        self.start()

    def start(self, frames: int = 0, kept=()) -> None:
        """A phrase begins: `frames` of it have been kept already, from before the sound
        was loud enough to start it. `kept` is those frames: a short word may be half
        over by the time its phrase has started, and without its beginning the detector
        did not take what was left of it for speech."""
        self.frames = frames        # how many frames of this phrase there have been
        self.heard = False          # whether a voice has been heard in it
        self.last = 0               # the frame at which a voice was last heard, however soft
        self.soft = False           # GONE was for talk that went on, but far more softly
        self.recent.clear()
        self.recent.extend(kept)
        self.by_pitch = False       # the detector is asked afresh: it may only have failed once
        self._since_look = 0
        self._loud = 0.0            # how loud the speech of this phrase has been
        self._mine = 0              # the frame at which speech about that loud was last heard

    def began_at(self, frames: int) -> None:
        """The phrase was cut down to its last `frames`, at which a voice was just heard."""
        self.frames = self.last = self._mine = frames

    def frames_since_voice(self) -> int:
        return int(self.frames - self.last) if self.heard else 0

    def frames_for(self, seconds: float) -> int:
        return round(seconds * self.per_second)

    def feed(self, frame):
        """One more frame of the phrase (its samples, as whole numbers). BEGAN_LATE, GONE,
        or None for nothing to do."""
        self.recent.append(frame)
        self.frames += 1
        self._since_look += 1
        if self.by_pitch:
            return self._look_for_pitch()
        if (self._since_look < self.frames_for(self.EVERY)
                or len(self.recent) < self.frames_for(self.FIRST)):
            return None
        span = list(self.recent)[-self.frames_for(self.SPAN):]
        sound = np.concatenate(span).astype(np.float32) / 32768.0
        sound = sound[len(sound) % PIECE_OF_SPEECH:]
        # The detector is shown the sound turned up, as the recogniser is: of short words
        # said quietly in a noisy room it missed 2 to 5 in 15 as they came, and at most 2
        # turned up. How loud each piece is, is taken from the sound as it came.
        peak = float(np.max(np.abs(sound))) if len(sound) else 0.0
        gain = min(config.NORMALISE_PEAK / peak, config.MAX_GAIN) if peak > 0 else 1.0
        marks = self.detector(sound * gain) if self.detector else None
        if marks is None or len(marks) != len(sound) // PIECE_OF_SPEECH:
            self.by_pitch = True    # for the rest of this phrase: one way or the other, not both
            return self._look_for_pitch()
        self._since_look = 0
        return self._seen(sound, np.asarray(marks))

    def _seen(self, sound, marks):
        """What a look found: `marks` is the detector's reading of `sound`, piece by piece."""
        pieces = len(marks)
        if not pieces:
            return None
        loud = np.sqrt(np.mean(sound.reshape(pieces, PIECE_OF_SPEECH) ** 2, axis=1))
        speech = marks >= self.SPEECH
        # Only speech that lasts is a voice: the pieces that are in a run of them.
        lasting, at, last_run = np.zeros(pieces, dtype=bool), 0, None
        while at < pieces:
            if not speech[at]:
                at += 1
                continue
            end = at
            while end < pieces and speech[end]:
                end += 1
            if end - at >= self.RUN:
                lasting[at:end] = True
                last_run = (at, end)
                # How loud this phrase's speech is: the loudest pieces of its loudest run.
                self._loud = max(self._loud, float(np.sort(loud[at:end])[(3 * (end - at)) // 4]))
            at = end
        if last_run is None:
            return self._gone()
        frames_per_piece = PIECE_OF_SPEECH / self.frame
        when = lambda piece: self.frames - (pieces - piece) * frames_per_piece
        self.last = max(self.last, when(last_run[1]))
        # The voice of this phrase: speech that is not far softer than its speech has been.
        # It is followed piece by piece, and not run by run: talk in the background runs
        # on from the voice without a break, and is no part of it.
        mine = np.nonzero(lasting & (loud >= self.QUIETER * self._loud))[0]
        if len(mine):
            self._mine = max(self._mine, when(int(mine[-1]) + 1))
        first, self.heard = not self.heard, True
        if first and self.frames > self.frames_for(self.LATE):
            return BEGAN_LATE
        return self._gone()

    def _gone(self):
        if not self.heard:
            return None
        if self.frames - self.last >= self.frames_for(self.GONE_AFTER):
            self.soft = False       # no speech at all: the voice has stopped
            return GONE
        if self.frames - self._mine >= self.frames_for(self.SOFT_AFTER):
            self.soft = True        # speech goes on, but far softer than this phrase's
            return GONE
        return None

    def _look_for_pitch(self):
        """A look the way it was done before there was a detector to ask."""
        window = self.frames_for(self.WINDOW)
        if self._since_look < self.frames_for(self.SLOWLY) or len(self.recent) < window:
            return None
        self._since_look = 0
        sound = np.concatenate(list(self.recent)[-window:]).astype(np.float64) / 32768.0
        if voiced(sound) >= self.HEARD:
            first, self.heard, self.last = not self.heard, True, self.frames
            self._mine = self.frames
            return BEGAN_LATE if first and self.frames > self.frames_for(self.LATE) else None
        if self.heard and self.frames - self.last >= self.frames_for(self.GONE_SLOWLY):
            return GONE
        return None


def told(numbers) -> str:
    """What was measured of a short phrase, for the log: no words, only figures."""
    if not numbers or "clear" not in numbers:
        return ""
    sure = numbers.get("sure")
    return (f" ({numbers.get('seconds', 0)} s, {numbers['clear']} s of clear speech"
            + (f", sure {sure}" if sure is not None else "") + ")")


# The app's own sounds, by their names: "noise-", a count, and when (by the clock that
# has no summer time), or as they were named before, by the day and the time alone. No
# other file in the folder is ever counted, taken away for being the oldest, or removed.
_OWN = re.compile(r"noise-(\d+)-\d{8}T\d{6}Z\.wav|\d{8}-\d{6}(?:-\d+)?\.wav")
_keeping = threading.Lock()  # one at a time at the folder: the count is read, then used


def _own(folder: str) -> list:
    """The names of the app's own sounds in `folder`, oldest first. Those named with a
    count go by it: it goes up by one each time, whatever the clock does (put back an
    hour in the autumn, or set right), so the newest is never taken for the oldest.
    Those from before the count are older than all of them, and go by their names."""
    def age(name: str):
        count = _OWN.fullmatch(name).group(1)
        return (1, int(count), name) if count else (0, 0, name)

    return sorted((name for name in os.listdir(folder) if _OWN.fullmatch(name)), key=age)


def _for_its_owner(path: str, mode: int) -> None:
    """Close to other accounts a folder or file that was made open to them: as these
    were, before they were made for their owner alone."""
    try:
        if os.name != "nt" and stat.S_IMODE(os.stat(path).st_mode) & 0o077:
            os.chmod(path, mode)
    except OSError:
        pass


def for_its_owner_alone(folder: str) -> None:
    """Close the folder of kept noises, and the app's own files in it, to the computer's
    other accounts. For a folder from before they were kept so: done when the program
    starts, and not only when the next noise is kept."""
    if not os.path.isdir(folder):
        return
    _for_its_owner(folder, 0o700)
    try:
        names = _own(folder) + [LIST]
    except OSError:
        return
    for name in names:
        _for_its_owner(os.path.join(folder, name), 0o600)


def keep_noise(folder: str, audio, text: str, model: str = "", numbers=None) -> str:
    """Keep a sound that was written down as words and wasn't speech: the sound itself,
    and beside it a line saying what it was taken for. Only on this computer, and only
    the last MOST_NOISES of them. Returns the sound's file. Raises OSError.

    It is the sound of the room, and words that were written there: so the folder and
    what is in it are for the person's own account, and nobody else's, to read."""
    import numpy as np
    samples = (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2")
    with _keeping:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        _for_its_owner(folder, 0o700)
        count = max((int(_OWN.fullmatch(name).group(1) or 0) for name in _own(folder)), default=0)
        when = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        while True:
            count += 1
            path = os.path.join(folder, f"noise-{count:06d}-{when}.wav")
            try:  # made new, and for its owner alone, or not at all
                made = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                               0o600)
                break
            except FileExistsError:
                pass                      # another program's, of the same moment: the next count
        try:
            with os.fdopen(made, "wb") as out, wave.open(out, "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(config.RATE)
                f.writeframes(samples.tobytes())
        except OSError:
            try:
                os.remove(path)           # not half a sound
            except OSError:
                pass
            raise
        said = dict(numbers or {}, seconds=round(len(samples) / config.RATE, 2), model=model)
        listed = os.path.join(folder, LIST)
        _for_its_owner(listed, 0o600)
        with os.fdopen(os.open(listed, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a",
                       encoding="utf-8") as f:
            f.write("\t".join([os.path.basename(path), " ".join(text.split()),
                               " ".join(f"{key}={value}" for key, value in sorted(said.items()))]) + "\n")
        kept = _own(folder)
        for old in kept[:-MOST_NOISES]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        if len(kept) > MOST_NOISES:
            _tidy_list(folder)
    return path


def _tidy_list(folder: str) -> None:
    """Keep only the lines of the list whose sound is still there. The new list is
    written beside the old and put in its place, so the list is never half of itself."""
    path = os.path.join(folder, LIST)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        there = set(os.listdir(folder))
        with os.fdopen(os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                       encoding="utf-8") as f:
            f.writelines(line for line in lines if line.split("\t", 1)[0] in there)
        os.replace(path + ".new", path)
    except OSError:
        pass


def noises_kept(folder: str) -> tuple:
    """(how many sounds marked as noises are kept, how many bytes they come to). Other
    sounds that have been put in the folder are not among them."""
    try:
        names = _own(folder)
    except OSError:
        return 0, 0
    size = 0
    for name in names:
        try:
            size += os.path.getsize(os.path.join(folder, name))
        except OSError:
            pass
    return len(names), size


def forget_noises(folder: str) -> None:
    """Remove the sounds marked as noises, and the list of them. Only those: anything
    else that has been put in the folder is left, whatever kind of file it is, and so
    is the folder then."""
    with _keeping:
        try:
            names = _own(folder) + [LIST, LIST + ".new"]
        except OSError:
            return
        for name in names:
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
        try:
            os.rmdir(folder)  # only if nothing else is in it
        except OSError:
            pass
