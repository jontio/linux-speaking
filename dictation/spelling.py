"""Spelling a word aloud, one letter at a time, as in Dragon's "spell that".

Turns what Whisper heard into steps: letters to add, or "backspace", "clear", "done"
and "cancel". Whisper writes spoken letters in many ways ("J-O-N-T-I", "Jay", "Bee",
"Alpha"), so letter names, the radio alphabet and common mishearings all count.
"""
from __future__ import annotations

import re

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
    "space": " ", "hyphen": "-", "dash": "-", "apostrophe": "'", "underscore": "_",
    "dot": ".", "period": ".", "point": ".", "at": "@",
}
PAIRS = {  # two-word names
    ("double", "u"): "w", ("double", "you"): "w", ("x", "ray"): "x", ("full", "stop"): ".",
    ("at", "sign"): "@",
}
CAPITAL = {"capital", "cap", "uppercase", "upper"}
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
    original = re.findall(r"[A-Za-z0-9']+", raw.replace("’", "'"))
    tokens = [t.lower() for t in original]
    joined = " ".join(tokens)
    if joined in PHRASES:
        return [PHRASES[joined]], []
    steps: list = []
    unknown: list = []
    capital = False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        pair = tuple(tokens[i:i + 2])
        add = None
        if pair == ("back", "space"):
            steps.append("backspace")
            i += 2
            continue
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
            if capital:
                add = add[0].upper() + add[1:]
                capital = False
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
