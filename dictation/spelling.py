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
    "n": "n", "en": "n", "november": "n",
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
DONE = {"done", "finished", "finish", "insert", "enter", "accept"}
CANCEL = {"cancel", "abort"}
PHRASES = {  # whole phrases, after normalising
    "that's it": "done", "thats it": "done", "all done": "done", "i'm done": "done",
    "never mind": "cancel", "nevermind": "cancel", "forget it": "cancel",
    "scratch that": "backspace", "delete that": "backspace", "undo that": "backspace",
    "start again": "clear", "start over": "clear", "clear that": "clear",
}
BACKSPACE = {"backspace", "delete", "back"}
CLEAR = {"clear", "reset"}


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
            # "B for bravo", "B as in boy": the word only says which letter was meant.
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
