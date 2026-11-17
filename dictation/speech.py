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
"""
from __future__ import annotations

from . import config, opinions

SOME = 0.3            # the detector's easy reading: is there anything like speech here?
CLEAR = 0.5           # its usual reading
CLEAR_SECONDS = 0.1   # how much clear speech has to stand behind a noise word

# What Parakeet writes for a noise: an assent, a hesitation, a laugh. Hyphens left out.
NOISE_WORDS = opinions.MURMURS | frozenset("yeah yep yup uhhuh ho okay ok yo".split())

_unusable = False  # the detector couldn't be used, so nothing more is asked of it


def only_noise_words(text: str) -> bool:
    """Whether `text` is nothing but the words Parakeet writes for a noise."""
    words = [opinions._key(word).replace("-", "") for word in text.split()]
    words = [word for word in words if word]
    return bool(words) and all(word in NOISE_WORDS for word in words)


def spoken(audio, threshold: float):
    """How many seconds of `audio` (numbers from -1 to 1 at config.RATE) the detector
    takes for speech, reading it at `threshold`. None if there is no detector to ask."""
    global _unusable
    if _unusable:
        return None
    try:
        from faster_whisper import vad
        spans = vad.get_speech_timestamps(audio, vad.VadOptions(
            threshold=threshold, min_speech_duration_ms=0, min_silence_duration_ms=100,
            speech_pad_ms=0))
        return sum(span["end"] - span["start"] for span in spans) / config.RATE
    except Exception as e:  # without it everything stands as it was written
        _unusable = True
        print(f"the voice detector can't be used, so noises may be written as words: "
              f"{type(e).__name__}: {e}", flush=True)
        return None


def not_speech(text: str, audio, spoken=spoken) -> str:
    """Why `text`, written for `audio`, is taken for a noise and not for speech: or ""
    if it stands. `spoken` is the detector, which a test can stand in for."""
    if not text.strip():
        return ""
    some = spoken(audio, SOME)
    if some is None:
        return ""
    if some <= 0:
        return "nothing like speech in it"
    if only_noise_words(text):
        clear = spoken(audio, CLEAR)
        if clear is not None and clear <= CLEAR_SECONDS:
            return "a noise word, with no clear speech behind it"
    return ""
