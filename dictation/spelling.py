"""Spelling a word aloud, one letter at a time, as in Dragon's "spell that".

Turns what Whisper heard into steps: letters to add, or "backspace", "clear", "done"
and "cancel". Whisper writes spoken letters in many ways ("J-O-N-T-I", "Jay", "Bee",
"Alpha"), so letter names, the radio alphabet and common mishearings all count. So do
the ways people make a letter clear ("B for bravo", "B as in boy": one b), "all caps"
before a run of capitals, a mark said after its letter ("a macron", "e acute"), and the
names of the signs that turn up in names and addresses.
"""
from __future__ import annotations

import re
import unicodedata

# What to tell Whisper it is hearing, so it writes letters rather than words.
PROMPT = ("Spelling a word one letter at a time: J, O, N, T, I. Capital B, A, Z. "
          "Space. Backspace. Done.")

LETTERS = {
    "a": "a", "ay": "a", "eh": "a", "alpha": "a", "alfa": "a",
    "b": "b", "be": "b", "bee": "b", "bravo": "b",
    "c": "c", "see": "c", "sea": "c", "cee": "c", "charlie": "c",
    "d": "d", "dee": "d", "delta": "d",
    "e": "e", "ee": "e", "echo": "e",
    "f": "f", "ef": "f", "eff": "f", "foxtrot": "f",
    "g": "g", "gee": "g", "golf": "g",
    "h": "h", "aitch": "h", "haitch": "h", "hotel": "h",
    "i": "i", "eye": "i", "india": "i",
    "j": "j", "jay": "j", "juliet": "j", "juliett": "j",
    "k": "k", "kay": "k", "okay": "k", "kilo": "k",
    "l": "l", "el": "l", "ell": "l", "lima": "l",
    "m": "m", "em": "m", "mike": "m",
    "n": "n", "en": "n", "in": "n", "november": "n",   # "in" is how N is often written
    "o": "o", "oh": "o", "owe": "o", "oscar": "o",
    "p": "p", "pee": "p", "pea": "p", "papa": "p",
    "q": "q", "queue": "q", "cue": "q", "quebec": "q",
    "r": "r", "are": "r", "ar": "r", "romeo": "r",
    "s": "s", "ess": "s", "es": "s", "sierra": "s",
    "t": "t", "tee": "t", "tea": "t", "tango": "t",
    "u": "u", "you": "u", "uniform": "u",
    "v": "v", "vee": "v", "victor": "v",
    "w": "w", "whiskey": "w", "whisky": "w",
    "x": "x", "ex": "x", "xray": "x",
    "y": "y", "why": "y", "wye": "y", "yankee": "y",
    "z": "z", "zed": "z", "zee": "z", "zulu": "z",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "space": " ", "hyphen": "-", "dash": "-", "minus": "-", "apostrophe": "'",
    "underscore": "_", "dot": ".", "period": ".", "point": ".", "at": "@", "comma": ",",
    "colon": ":", "semicolon": ";", "slash": "/", "backslash": "\\", "ampersand": "&",
    "plus": "+", "equals": "=", "hash": "#", "percent": "%", "dollar": "$", "asterisk": "*",
    "star": "*",
}
PAIRS = {  # two-word names
    ("double", "u"): "w", ("double", "you"): "w", ("x", "ray"): "x", ("full", "stop"): ".",
    ("at", "sign"): "@", ("forward", "slash"): "/", ("back", "slash"): "\\",
    ("hash", "sign"): "#", ("number", "sign"): "#", ("percent", "sign"): "%",
    ("plus", "sign"): "+", ("equals", "sign"): "=", ("dollar", "sign"): "$",
    ("question", "mark"): "?", ("exclamation", "mark"): "!", ("exclamation", "point"): "!",
    ("open", "bracket"): "(", ("close", "bracket"): ")", ("open", "paren"): "(",
    ("close", "paren"): ")",
}
CAPITAL = {"capital", "cap", "uppercase", "upper"}
# After "all", these put the rest of the phrase in capitals: "all caps N A S A".
CAPITALS = {"caps", "capitals", "capital", "uppercase"}
# Said after a letter, the mark that goes on it: "a macron" is ā, "e acute" is é.
ACCENTS = {"macron": "COMBINING MACRON", "acute": "COMBINING ACUTE ACCENT",
           "grave": "COMBINING GRAVE ACCENT", "umlaut": "COMBINING DIAERESIS",
           "circumflex": "COMBINING CIRCUMFLEX ACCENT", "cedilla": "COMBINING CEDILLA"}
# With the ways a recogniser has written them when it expected letters: "dumb" for
# "done", "council" for "cancel". Nothing else that is said into the box sounds so.
DONE = {"done", "finished", "finish", "insert", "enter", "accept", "dumb", "dun", "dunn"}
CANCEL = {"cancel", "abort", "council", "counsel", "console"}
PHRASES = {  # whole phrases, after normalising
    "that's it": "done", "thats it": "done", "all done": "done", "i'm done": "done",
    "never mind": "cancel", "nevermind": "cancel", "forget it": "cancel",
    "scratch that": "backspace", "delete that": "backspace", "undo that": "backspace",
    "start again": "clear", "start over": "clear", "clear that": "clear",
}
BACKSPACE = {"backspace", "delete", "back", "markspace"}
CLEAR = {"clear", "reset"}


# The radio alphabet: words that can't be mistaken for one another, as letters can.
RADIO = {word: word[0] for word in (
    "alpha alfa bravo charlie delta echo foxtrot golf hotel india juliet juliett kilo lima "
    "mike november oscar papa quebec romeo sierra tango uniform victor whiskey whisky "
    "xray yankee zulu").split()}
_AS_IN = ("in", "for", "like")


def parse(raw: str) -> tuple[list, list]:
    """What one phrase means while spelling: (steps, words not understood).

    Each step is a string to add, or one of "backspace", "clear", "done", "cancel".
    """
    # The letter W, written out as the dictionary has it. As two words, "double U", it is
    # the letter W as well (see PAIRS): that is how it is said, and a recogniser may write
    # it so. Two of the letter u are "U U".
    raw = re.sub(r"\bdouble-(?:u|you)\b", " w ", raw.replace("’", "'"), flags=re.IGNORECASE)
    # Letters of any alphabet: "é" and "ā" are letters too.
    original = re.findall(r"(?:[^\W_]|')+", raw)
    tokens = [t.lower() for t in original]
    joined = " ".join(tokens)
    if joined in PHRASES:
        return [PHRASES[joined]], []
    if joined == "an":
        return ["n"], []     # the letter N, said by itself: "A, N" is written as two
    # "B as in bravo" is said so that the letter can't be mistaken: so it is the word
    # that settles it, whatever the letter was heard as. ("We are in Bravo" is how a
    # recogniser once wrote it.)
    if 3 <= len(tokens) <= 6 and tokens[-1] in RADIO and tokens[-2] in _AS_IN:
        letter = RADIO[tokens[-1]]
        return [letter.upper() if set(tokens[:-2]) & (CAPITAL | CAPITALS) else letter], []
    steps: list = []
    unknown: list = []
    capital = shout = False
    lettered = False  # whether the last thing added was one letter
    i = 0
    while i < len(tokens):
        token = tokens[i]
        pair = tuple(tokens[i:i + 2])
        add = None
        if pair == ("back", "space"):
            steps.append("backspace")
            lettered = False
            i += 2
            continue
        if token == "all" and i + 1 < len(tokens) and tokens[i + 1] in CAPITALS:
            shout = True
            i += 2
            continue
        if lettered and i + 1 < len(tokens) and (
                token in ("for", "like") or pair == ("as", "in") and i + 2 < len(tokens)):
            # "B for bravo", "B as in boy": the word says which letter was meant, and
            # is what to go by if the letter itself was heard as another.
            word = tokens[i + 1] if token != "as" else tokens[i + 2]
            meant = RADIO.get(word) or (word[0] if word.isalpha() and len(word) > 1 else "")
            if meant and steps and len(steps[-1]) == 1 and steps[-1].lower() != meant:
                steps[-1] = meant.upper() if steps[-1].isupper() else meant
            i += 2 if token != "as" else 3
            lettered = False
            continue
        if lettered and token in ACCENTS:
            steps[-1] = unicodedata.normalize("NFC", steps[-1] + unicodedata.lookup(ACCENTS[token]))
            i += 1
            continue
        lettered = False
        if pair in PAIRS:
            add = PAIRS[pair]
            i += 1
        elif token in CAPITAL and i + 1 < len(tokens):
            capital = True
            i += 1
            continue
        elif token == "double" and i + 1 < len(tokens) and tokens[i + 1] in LETTERS:
            add = LETTERS[tokens[i + 1]] * 2
            i += 1
        elif token in DONE:
            steps.append("done")
        elif token in CANCEL:
            steps.append("cancel")
        elif token in BACKSPACE:
            steps.append("backspace")
        elif token in CLEAR:
            steps.append("clear")
        elif token in LETTERS:
            add = LETTERS[token]
        elif len(token) == 1 and token.isalnum():
            add = token
        elif original[i].isupper() and token.isalpha() and len(token) <= 12:
            add = token  # Whisper ran the letters together, as in "JONTI"
        elif token.isdigit():
            add = token
        else:
            unknown.append(original[i])
        if add is not None:
            if shout:
                add = add.upper()
            elif capital:
                add = add[0].upper() + add[1:]
            capital = False
            lettered = len(add) == 1 and add.isalpha()
            steps.append(add)
        i += 1
    return steps, unknown


COMMAND_STEPS = frozenset({"done", "cancel", "backspace", "clear"})


def choose(by_letters: str, by_words: str) -> str:
    """Of two hearings of one thing said into the spelling box, the one to go by.

    `by_letters` is the model that tells letters apart best, told to expect letters;
    `by_words` is the model chosen for dictation, which knows the voice and is the better
    at whole words. Told to expect letters, the first wrote "dumb" for "done"; left to
    itself, the second writes "And" for N. So a word of command goes by the second where
    it wrote one and nothing else; where the first wrote nothing the box knows, the
    second is taken if it did; and letters go by the first.

    Measured on 140 letters and words in four voices: 110 right by the first alone, 85
    by the second, 115 by the two so. The second never took a letter for a command."""
    first, first_unknown = parse(by_letters)
    second, second_unknown = parse(by_words)
    if second and not second_unknown and all(step in COMMAND_STEPS for step in second):
        return by_words
    if not first or first_unknown:
        return by_words if second and not second_unknown else by_letters
    return by_letters


def apply(spelled: str, steps: list) -> tuple[str, str]:
    """Apply steps to the letters so far. Returns (letters, "", "done" or "cancel")."""
    for step in steps:
        if step == "backspace":
            spelled = spelled[:-1]
        elif step == "clear":
            spelled = ""
        elif step in ("done", "cancel"):
            return spelled, step
        else:
            spelled += step
    return spelled, ""
