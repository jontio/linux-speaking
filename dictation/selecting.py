"""Finding the words for "select ..." near the cursor, like Dragon's Select-and-Say.

A word said by itself in a command has nothing around it to say how it is spelled, so
"select two" may be heard as "two", "2", "to" or "too", whichever is in the document.
Words that sound the same are therefore looked for as well.
"""
from __future__ import annotations

from itertools import product

# The same number, in words and in figures. Either may be written for the other.
_FIGURES = dict(pair.split("=") for pair in (
    "zero=0 one=1 two=2 three=3 four=4 five=5 six=6 seven=7 eight=8 nine=9 ten=10 "
    "eleven=11 twelve=12 thirteen=13 fourteen=14 fifteen=15 sixteen=16 seventeen=17 "
    "eighteen=18 nineteen=19 twenty=20 thirty=30 forty=40 fifty=50 sixty=60 seventy=70 "
    "eighty=80 ninety=90 first=1st second=2nd third=3rd fourth=4th fifth=5th sixth=6th "
    "seventh=7th eighth=8th ninth=9th tenth=10th"
).split())
_SAME = {**_FIGURES, **{figure: word for word, figure in _FIGURES.items()}}

# Different words that sound the same.
_SOUNDS = tuple(group.split() for group in (
    "two to too", "four for fore", "one won", "eight ate", "fourth forth",
    "there their they're", "your you're", "its it's", "who's whose", "let's lets",
    "here hear", "where wear ware", "right write rite", "no know", "new knew", "not knot",
    "by buy bye", "see sea", "be bee", "which witch", "would wood", "whether weather",
    "our hour", "or oar ore", "i eye aye", "hi high", "whole hole", "through threw",
    "wait weight", "week weak", "way weigh", "made maid", "mail male", "meet meat",
    "peace piece", "plain plane", "principal principle", "read red reed", "road rode rowed",
    "role roll", "sale sail", "scene seen", "sight site cite", "so sew sow", "some sum",
    "son sun", "stair stare", "steal steel", "tail tale", "waist waste", "aloud allowed",
    "bare bear", "brake break", "cell sell", "cent sent scent", "dear deer", "die dye",
    "fair fare", "flour flower", "hair hare", "heal heel he'll", "him hymn", "knight night",
    "pair pear", "pole poll", "rain reign rein", "raise rays", "sore soar", "toe tow",
    "we've weave", "affect effect", "accept except", "than then",
))
_SOUND_OF = {word: frozenset(group) for group in _SOUNDS for word in group}
MAX_VARIANTS = 12


def same(word: str) -> frozenset:
    """`word` and the other way of writing it, if it is a number: "two" and "2"."""
    return frozenset({word, _SAME[word]}) if word in _SAME else frozenset({word})


def alike(word: str) -> frozenset:
    """`word` and every word that sounds the same, numbers in both their forms."""
    found = set()
    for form in same(word):
        for sound in _SOUND_OF.get(form, (form,)):
            found |= same(sound)
    return frozenset(found)


def variants(phrase: str) -> list:
    """Other ways `phrase` might be written in the document, the likeliest first: the
    same numbers the other way, then words that sound the same. Without `phrase` itself.

    For programs that look for the words themselves, and only for exactly those.
    """
    words = _words(phrase)
    if not words:
        return []
    choices = []
    for word in words:
        twins = sorted(same(word) - {word})
        choices.append([word] + twins + sorted(alike(word) - same(word)))
    found = []
    for combination in product(*choices):
        if list(combination) != words:
            found.append(" ".join(combination))
        if len(found) >= MAX_VARIANTS:
            break
    # One changed word is likelier than several.
    return sorted(found, key=lambda v: sum(a != b for a, b in zip(v.split(), words)))


def _norm_char(c: str) -> str:
    return "'" if c == "’" else c.lower()


def _words(phrase: str) -> list[str]:
    cleaned = "".join(
        _norm_char(c) if (c.isalnum() or c in "'’") else " " for c in phrase
    )
    return cleaned.split()


def _spans(text: str) -> list:
    """(word, start, end) for each word of `text`, lower case."""
    spans, start = [], None
    for i, c in enumerate(text):
        if c.isalnum() or c in "'’":
            if start is None:
                start = i
        elif start is not None:
            spans.append(("".join(map(_norm_char, text[start:i])), start, i))
            start = None
    if start is not None:
        spans.append(("".join(map(_norm_char, text[start:])), start, len(text)))
    return spans


def _find(spans: list, wanted: list) -> list:
    """Start and end of each place where the words match `wanted`, a set for each word."""
    found = []
    for at in range(len(spans) - len(wanted) + 1):
        if all(spans[at + n][0] in choices for n, choices in enumerate(wanted)):
            found.append((spans[at][1], spans[at + len(wanted) - 1][2]))
    return found


def find_exact(text: str, phrase: str) -> list[tuple[int, int]]:
    """Start and end of every whole-word match for `phrase` as it was heard, in order.

    Case and punctuation are ignored, so "cat sat" finds "Cat, sat". A number matches in
    words or in figures.
    """
    target = _words(phrase)
    return _find(_spans(text), [same(word) for word in target]) if target else []


def find_all(text: str, phrase: str) -> list[tuple[int, int]]:
    """The places to offer for "select `phrase`", in order.

    Words that sound the same count too, "to" and "too" for "two", because which of them
    was written down for the command is a matter of chance.
    """
    target = _words(phrase)
    return _find(_spans(text), [alike(word) for word in target]) if target else []


def find_nearest(text: str, caret: int, phrase: str) -> tuple[int, int] | None:
    """Start and end of the match for `phrase` closest to `caret`.

    Only whole words match. On a tie, the match before the cursor wins. Words that only
    sound the same are taken when the phrase as heard isn't there at all.
    """
    best = None
    for start, stop in find_exact(text, phrase) or find_all(text, phrase):
        if start <= caret <= stop:
            distance = 0
        elif caret < start:
            distance = start - caret
        else:
            distance = caret - stop
        key = (distance, 0 if stop <= caret else 1)
        if best is None or key < best[0]:
            best = (key, (start, stop))
    return best[1] if best else None
