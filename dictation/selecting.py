"""Finding the words for "select ..." near the cursor, like Dragon's Select-and-Say.

A word said by itself in a command has nothing around it to say how it is spelled, so
"select two" may be heard as "two", "2", "to" or "too", whichever is in the document.
Words that sound the same are therefore looked for as well.

The same goes for how a thing is written rather than which word it is. The command
comes without its punctuation, so "1250" has to find "1,250" and "us" has to find
"U.S."; a number may be in words on one side and in figures on the other ("twenty one"
and "21"); and the recogniser may spell the American way what the document spells the
British way ("color", "colour"). Where the words are there just as they were heard,
those places are taken first. Only if there are none do the looser ways count: other
spellings, a missing apostrophe or accent ("dogs" for "dog's", "cafe" for "café"), a
title written short ("doctor" for "Dr.") and words that sound the same.
"""
from __future__ import annotations

import re
import unicodedata
from itertools import product

from .words import fold, spellings

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
# A title or the like said in full, and how it is written short. In the document the
# short one has its stop: see _PIECE.
_SHORT = {"doctor": ("dr",), "mister": ("mr",), "missus": ("mrs",), "professor": ("prof",),
          "saint": ("st",), "street": ("st",), "mount": ("mt",), "versus": ("vs",),
          "junior": ("jr",), "senior": ("sr",)}
for _long, _shorts in list(_SHORT.items()):
    for _one in _shorts:
        _SHORT[_one] = _SHORT.get(_one, ()) + (_long,)
MAX_VARIANTS = 12

_UNITS = "one two three four five six seven eight nine".split()
_TEENS = ("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
          "nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def same(word: str) -> frozenset:
    """`word` and the other way of writing it, if it is a number: "two" and "2"."""
    return frozenset({word, _SAME[word]}) if word in _SAME else frozenset({word})


def alike(word: str) -> frozenset:
    """`word` and every word that sounds the same, numbers in both their forms, and a
    title in its long form and its short one."""
    found = set(_SHORT.get(word, ()))
    for form in same(word):
        for sound in _SOUND_OF.get(form, (form,)):
            found |= same(sound)
    return frozenset(found)


def _under_hundred(words: list, at: int) -> tuple:
    """(how many words, the number) for "seven", "seventeen" or "seventy seven" at
    words[at]. (0, 0) if no number is said there."""
    word = words[at] if at < len(words) else ""
    if word in _TENS:
        tens = 10 * (_TENS.index(word) + 2)
        if at + 1 < len(words) and words[at + 1] in _UNITS:
            return 2, tens + _UNITS.index(words[at + 1]) + 1
        return 1, tens
    if word in _UNITS:
        return 1, _UNITS.index(word) + 1
    return (1, _TEENS.index(word) + 10) if word in _TEENS else (0, 0)


def _under_thousand(words: list, at: int) -> tuple:
    """As _under_hundred, with "three hundred" and "three hundred and five" as well."""
    count, total = _under_hundred(words, at)
    end = at + count
    if count == 1 and total < 10 and words[end:end + 1] == ["hundred"]:
        total, end = total * 100, end + 1
        skip = end + (words[end:end + 1] == ["and"])
        more, rest = _under_hundred(words, skip)
        if more:
            total, end = total + rest, skip + more
    return end - at, total


def _said_number(words: list, at: int) -> tuple:
    """(how many words, the figures) for a number of two words or more that starts at
    words[at]: "twenty one", "three hundred and five", "two thousand", and a year said
    in two halves, "nineteen eighty four". (0, "") if there is none: a number of one
    word has its figure in `same`."""
    count, total = _under_thousand(words, at)
    end = at + count
    if count and words[end:end + 1] == ["thousand"]:
        end += 1
        skip = end + (words[end:end + 1] == ["and"])
        more, rest = _under_thousand(words, skip)
        total, end = total * 1000 + rest, (skip + more if more else end)
    elif count and 10 <= total < 100:
        more, rest = _under_hundred(words, end)
        if more and rest >= 10:
            total, end = total * 100 + rest, end + more
    return (end - at, str(total)) if end - at >= 2 else (0, "")


def _readings(words: list) -> list:
    """The ways `words` may stand in a document where a number is among them, the
    likeliest first: with a number said in several words written in figures ("twenty
    one" as "21"), then the words themselves, then with figures from 21 to 99 written
    out. Each is a list of words."""
    figures, out, at = [], [], 0
    while at < len(words):
        count, number = _said_number(words, at)
        figures.append(number if count else words[at])
        at += count or 1
    for word in words:
        if word.isdigit() and 20 < int(word) < 100 and int(word) % 10:
            out += [_TENS[int(word) // 10 - 2], _UNITS[int(word) % 10 - 1]]
        else:
            out.append(word)
    return [reading for n, reading in enumerate((figures, words, out))
            if reading not in (figures, words, out)[:n]]


def variants(phrase: str) -> list:
    """Other ways `phrase` might be written in the document, the likeliest first: the
    same numbers the other way, the other side of the Atlantic's spelling, then words
    that sound the same. Without `phrase` itself.

    For programs that look for the words themselves, and only for exactly those.
    """
    words = _words(phrase)
    if not words:
        return []
    found = []
    for reading in _readings(words):
        choices = []
        for word in reading:
            twins = sorted(same(word) - {word})
            if word.isdigit() and 4 <= len(word) <= 6:
                twins.append(f"{int(word):,}")       # "1250" may be written "1,250"
            choices.append([word] + twins + sorted(spellings(word))
                           + sorted(alike(word) - same(word)))
        for combination in product(*choices):
            written = " ".join(combination)
            if list(combination) != words and written not in found:
                found.append(written)
            if len(found) >= MAX_VARIANTS:
                break
    # One changed word is likelier than several.
    return sorted(found[:MAX_VARIANTS],
                  key=lambda v: sum(a != b for a, b in zip(v.split(), words)))


# One word as it stands in a document. A number with commas in it is one word, and so
# are initials with their stops ("U.S.", "p.m.") and a title with its stop ("Dr."): the
# command that asks for them has none of those marks, and "select us" has to find "U.S.".
_PIECE = re.compile(
    r"\d{1,3}(?:,\d{3})+(?!\d)"
    r"|(?<![^\W_])(?:[^\W\d_]\.){2,}"
    r"|(?<![^\W_])(?:dr|mr|mrs|ms|prof|st|mt|vs|jr|sr)\.(?![^\W_])"
    r"|(?:[^\W_]|['’])+", re.IGNORECASE)


def _bare(word: str, start: int, end: int):
    """A word without the quote marks at either end of it, and where it then is, or None
    if it was only quote marks: 'hello' is hello, and the boys' toys are the boys'."""
    lead = len(word) - len(word.lstrip("'"))
    trail = len(word) - len(word.rstrip("'"))
    return (word[lead:len(word) - trail], start + lead, end - trail) if lead < len(word) else None


def _spans(text: str) -> list:
    """(word, start, end) for each word of `text`: lower case, and without the commas
    of a number or the stops of a shortening, which are within its start and end."""
    spans = []
    for piece in _PIECE.finditer(text):
        word = piece.group().lower().replace("’", "'")
        if "," in word or "." in word:
            spans.append((word.replace(",", "").replace(".", ""), piece.start(), piece.end()))
        else:
            spans.append(_bare(word, piece.start(), piece.end()))
    return [span for span in spans if span is not None]


def _words(phrase: str) -> list[str]:
    return [word for word, _, _ in _spans(phrase)]


def _loose(word: str) -> str:
    """How a word compares when its spelling is not to be trusted: without apostrophes
    or accents, and with a British spelling made American."""
    plain = "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))
    return fold(plain.replace("'", ""))


def _find(spans: list, wanted: list, key=None) -> list:
    """Start and end of each place where the words match `wanted`, a set for each word.
    With `key`, the words on both sides are compared as `key` makes them."""
    if key:
        spans = [(key(word), start, end) for word, start, end in spans]
        wanted = [{key(word) for word in choices} for choices in wanted]
    found = []
    for at in range(len(spans) - len(wanted) + 1):
        if all(spans[at + n][0] in choices for n, choices in enumerate(wanted)):
            found.append((spans[at][1], spans[at + len(wanted) - 1][2]))
    return found


def _find_readings(text: str, phrase: str, choices, key=None) -> list:
    """Every place where `phrase` is, in any of its readings, in order. `choices` gives
    the words that will do for one word of it."""
    spans, found = _spans(text), set()
    for reading in _readings(_words(phrase)):
        found.update(_find(spans, [choices(word) for word in reading], key))
    return sorted(found)


def find_exact(text: str, phrase: str) -> list[tuple[int, int]]:
    """Start and end of every whole-word match for `phrase` as it was heard, in order.

    Case and punctuation are ignored, so "cat sat" finds "Cat, sat", "1250" finds "1,250"
    and "us" finds "U.S.". A number matches in words or in figures.
    """
    return _find_readings(text, phrase, same) if _words(phrase) else []


def find_all(text: str, phrase: str) -> list[tuple[int, int]]:
    """The places to offer for "select `phrase`", in order.

    Words that sound the same count too, "to" and "too" for "two", because which of them
    was written down for the command is a matter of chance. So does the same word
    spelled another way: "color" for "colour", "dogs" for "dog's", "cafe" for "café".
    """
    return _find_readings(text, phrase, alike, _loose) if _words(phrase) else []


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


def back_to(mark: int, start: int, end: int, new_start: int, new_end: int, grew: int) -> int:
    """Where the cursor goes back to after "correct ...".

    It was at `mark` when the words from `start` to `end` were chosen. Other words have
    since been said in their place: they run from `new_start` to `new_end`, and all that
    came after has moved along by `grew`.

    A cursor that was before the words is where it was. One that was after them has moved
    along with the text. One that was among them is left at the end of the new words.
    """
    if mark <= start:
        return min(mark, new_start)
    if mark >= end:
        return max(new_end, mark + grew)
    return new_end
