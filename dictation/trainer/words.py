"""Single words, cut out of the sentences read aloud, to be learned from beside them.

Why: a recogniser learns only from what it gets wrong or is unsure of. In a sentence the
words around a word settle what it is ("the pen is on the desk" is not a pin), so the
recogniser is already right, and learns next to nothing about how this voice says the
vowel. Trained on sentences alone, it heard single words no better than before. A word
heard with nothing round it has only its sound to go by, and there the voice is learned:
on words cut from sentences kept out of the training, one pass took Parakeet Unified from
56 in a hundred right to 80, with whole sentences heard as well as before.

The cutting needs to know when each word was said. Parakeet v2 says so closely. (Parakeet
Unified writes each word a third of a second or so after it was said, and not evenly.)
Whisper's word times are as loose as Unified's: against v2's, about a third of either's
word beginnings fall within 0.06 s, of words that last a quarter of a second. And v2's
cuts are good in themselves: nineteen in twenty of the words cut with them are whole.
So it is done with the app's build of Parakeet v2 (training.CUTTER), where that is
installed, whichever model is being retrained; only sentences it writes word for word are used, so that each
piece is known to be the word it is taken for.
"""
import numpy as np

from .. import training

RATE = 16000
PEAK, MOST_GAIN = 0.7, 60.0
LEAD = 0.05                   # seconds kept before a word's first piece
SHORTEST, LONGEST = 0.18, 1.2  # a word shorter or longer than this was not cut out cleanly
LAST = 0.25                   # how long the last word of a sentence is taken to run on

# Little words that are swallowed in running speech: cut out, they are a grunt that nobody
# could put a word to, and learning to write one for it would be learning to write words
# for noises.
SMALL = frozenset("""the and have was will when been are had with that this from for but not you she his her
they them then than were what into your our out its has can did all any who how why too very just over some
more much such also only both each being does done off one two him got get let may might must shall should
would could about after again before because while where which there their these those here upon under""".split())


def spans(pieces, times, lasts) -> list:
    """[[word as written, when it begins, when its last piece ends], ...] from the pieces
    a recogniser wrote, when it wrote each, and how long it took each to last."""
    found = []
    for piece, at, last in zip(pieces, times, lasts):
        bare = piece.strip().lstrip("▁")
        if piece[:1] in (" ", "▁") or not found:
            found.append([bare, at, at + last])
        else:
            found[-1][0] += bare
            found[-1][2] = at + last
    return [span for span in found if training.words(span[0])]


def pieces_of(text: str, heard: list, seconds: float) -> list:
    """[(the word, where it begins, where it ends), ...] in seconds: the words of a
    sentence worth cutting out. `heard` is spans() of what the recogniser wrote for it.
    Empty unless that is the sentence word for word."""
    wanted = training.words(text)
    if len(heard) != len(wanted) or any(training.words(span[0]) != [word]
                                        for span, word in zip(heard, wanted)):
        return []
    found = []
    for at, (word, (_, start, end)) in enumerate(zip(wanted, heard)):
        end = heard[at + 1][1] if at + 1 < len(heard) else min(seconds, end + LAST)
        if (len(word) >= 3 and word.isalpha() and word not in SMALL
                and SHORTEST <= end - start <= LONGEST):
            found.append((word, max(0.0, start - LEAD), end))
    return found


def cut(files: dict, data: list, threads: int) -> list:
    """Single words from sentences: [(name, sound, "Word."), ...] for `data`, which is
    [(name, sound, text), ...]. Each is turned up by itself, as the app turns up a word
    said by itself, and written as a recogniser writes one: a capital and a full stop."""
    import sherpa_onnx
    recogniser = sherpa_onnx.OfflineRecognizer.from_transducer(
        **files, num_threads=threads or 4, model_type="nemo_transducer")
    made = []
    for name, sound, text in data:
        stream = recogniser.create_stream()
        stream.accept_waveform(RATE, sound)
        recogniser.decode_stream(stream)
        result = stream.result
        lasts = list(getattr(result, "durations", [])) or [0.08] * len(result.tokens)
        heard = spans(list(result.tokens), list(result.timestamps), lasts)
        for word, start, end in pieces_of(text, heard, len(sound) / RATE):
            piece = sound[int(start * RATE):int(end * RATE)]
            peak = float(np.max(np.abs(piece))) if len(piece) else 0.0
            if peak > 0:
                made.append((f"{name}:{word}", piece * min(PEAK / peak, MOST_GAIN),
                             word.capitalize() + "."))
    return made
