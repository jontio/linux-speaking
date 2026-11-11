"""Telling commands from dictation.

As in Dragon, a command is a whole phrase on its own, with a pause before and
after. Anything else is dictation. While asleep, only "wake up" counts.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

WAKE = "wake"

COMMANDS = {
    "wake up": WAKE,
    "go to sleep": "sleep",
    "scratch that": "scratch",
    "undo that": "undo",
    "undo": "undo",
    "undo it": "undo",
    "undo this": "undo",
    "undue that": "undo",   # ways Whisper may hear "undo that"
    "and do that": "undo",
    "on do that": "undo",
    "delete that": "delete",
    "spell that": "spell",
    "spell it": "spell",
    "spell this": "spell",
    "spell": "spell",
    "new paragraph": "new_paragraph",
    "new line": "new_line",
    "press enter": "press_enter",
    "go to end of line": "line_end",
    "go to the end of the line": "line_end",
    "go to start of line": "line_start",
    "go to the start of the line": "line_start",
    "go to beginning of line": "line_start",
    "go to end of paragraph": "para_end",
    "go to the end of the paragraph": "para_end",
    "go to start of paragraph": "para_start",
    "go to the start of the paragraph": "para_start",
    "go to beginning of paragraph": "para_start",
    "go to top": "doc_top",
    "go to the top": "doc_top",
    "go to bottom": "doc_end",
    "go to the bottom": "doc_end",
    "select that": "select_last",
    "unselect that": "unselect",
    "cap that": "cap",
    "all caps that": "all_caps",
    "no caps that": "no_caps",
    "bold that": "bold",
    "italicize that": "italic",
    "italicise that": "italic",
    "underline that": "underline",
}


@dataclass(frozen=True)
class Command:
    name: str
    arg: str = ""


@dataclass(frozen=True)
class Dictation:
    text: str


def normalise(raw: str) -> str:
    """Lower case, no punctuation, single spaces: "Wake-up!" becomes "wake up"."""
    s = raw.lower().replace("’", "'").replace("-", " ")
    s = re.sub(r"[^\w\s']", " ", s)
    return " ".join(s.split())


NUMBERS = {w: i for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split(), start=1)}
NUMBERS.update({"to": 2, "too": 2, "for": 4, "won": 1})  # how Whisper may hear numbers
_CHOICE = re.compile(r"(?:choose |number |pick |select |option )?(\w+)")
_BACKSPACE = re.compile(r"back ?space(?: (\w+))?(?: times?)?")


_DELETE_WORDS = re.compile(r"delete (?:the )?(?:last|previous) (?:(\w+) )?words?")
_WORD = re.compile(r"[\w'\u2019-]+")


def last_words_length(before: str, count: int) -> int:
    """How many characters to remove to delete the last `count` words before the cursor.

    Takes the punctuation and spaces after each word, and the space before the
    first, so "Hello big world." minus one word leaves "Hello big". If there are
    fewer words than asked for, it takes them all.
    """
    words = [m.start() for m in _WORD.finditer(before)]
    if not words or count < 1:
        return 0
    start = words[max(0, len(words) - count)]
    while start > 0 and before[start - 1].isspace():
        start -= 1
    return len(before) - start


def _count(word: str | None) -> int | None:
    """A spoken count from 1 to 99, or None if it isn't one. No word means 1."""
    if word is None:
        return 1
    if word.isdigit():
        return int(word) if 1 <= int(word) <= 99 else None
    return NUMBERS.get(word)


def choice(raw: str, limit: int) -> int | None:
    """The number picked from a numbered list of `limit` matches, or None.

    "2", "two", "choose 2" and "number two" all pick the second.
    """
    m = _CHOICE.fullmatch(normalise(raw))
    n = _count(m.group(1)) if m else None
    return n if n and n <= limit else None


def is_wake(phrase: str) -> bool:
    """True if a normalised phrase is "wake up", allowing for a slight mishearing.

    It has to be said on its own: "wake up the kids" doesn't count.
    """
    if phrase in ("wake up", "wakeup", "wake up wake up"):
        return True
    if len(phrase.split()) > 3:
        return False
    return difflib.SequenceMatcher(None, phrase, "wake up").ratio() >= 0.8


def interpret(raw: str, awake: bool, disabled=frozenset()) -> Command | Dictation | None:
    """Decide what one phrase from Whisper means. None means ignore it.

    A command named in `disabled` is typed as ordinary dictation. Waking and
    sleeping can't be disabled.
    """
    phrase = normalise(raw)
    if not phrase:
        return None
    if not awake:
        return Command(WAKE) if is_wake(phrase) else None
    name = COMMANDS.get(phrase)
    if name and (name not in disabled or name in (WAKE, "sleep")):
        return Command(name)
    if name:
        return Dictation(raw)
    m = _BACKSPACE.fullmatch(phrase)
    if m and "backspace" not in disabled and _count(m.group(1)):
        return Command("backspace", str(_count(m.group(1))))
    m = _DELETE_WORDS.fullmatch(phrase)
    if m and "delete_words" not in disabled and _count(m.group(1)):
        return Command("delete_words", str(_count(m.group(1))))
    if "select" not in disabled and phrase.startswith("select ") \
            and len(phrase) > len("select "):
        return Command("select", phrase[len("select "):])
    return Dictation(raw)


# Cursor-movement commands, as steps for the Writer extension's "move" request:
# ["view" or "text", method, arguments...]. Adding one here needs no extension update.
MOVES = {
    "line_end": [["view", "gotoEndOfLine", False]],
    "line_start": [["view", "gotoStartOfLine", False]],
    "para_end": [["text", "gotoEndOfParagraph", False]],
    "para_start": [["text", "gotoStartOfParagraph", False]],
    "doc_top": [["view", "gotoStart", False]],
    "doc_end": [["view", "gotoEnd", False]],
}


def move_steps(name: str, before: str, after: str) -> list:
    """The steps for a cursor-movement command, given the text around the cursor.

    Already at the end of a paragraph, "go to end of paragraph" goes on to the end of
    the next one. Already at the start, "go to start of paragraph" goes back to the
    start of the one before. So repeating either command walks through the document.
    """
    if name == "para_end" and not after:
        return [["text", "gotoNextParagraph", False], ["text", "gotoEndOfParagraph", False]]
    if name == "para_start" and not before:
        return [["text", "gotoPreviousParagraph", False],
                ["text", "gotoStartOfParagraph", False]]
    return MOVES[name]
