"""Second and third opinions: one phrase as more than one recogniser heard it.

Different recognisers get different words wrong. Where two of them write the same, it is
almost always right. Where they differ, a third is asked and the two that agree win.

Two alone are no better than the better of them, because nothing says which is right. On
one reader's recording of 314 words, Parakeet got one wrong, Whisper Small three and
Medium two, none of them the same word; the three together got none wrong.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .formatting import own_stop
from .words import fold

_EDGES = re.compile(r"^\W+|\W+$")
# One word written two ways. Which way is not something recognisers differ on in what
# they heard, so neither is put to the vote: "Dr. Smith" and "Doctor Smith" are the same.
_SAME_WORD = {"dr": "doctor", "mr": "mister", "mrs": "missus", "prof": "professor",
              "vs": "versus", "okay": "ok"}


# Who is asked, in this order, leaving out whichever heard the phrase first.
GIVERS = ("small.en", "medium.en", "parakeet-tdt-0.6b-v2")


def others(first: str) -> tuple:
    """Who gives the second and the third opinion on what the model `first` heard."""
    rest = [name for name in GIVERS if name != first]
    return rest[0], rest[1]


def checked(text: str, first: str, ask, ignore=(), keep=None) -> tuple:
    """(the words, what happened) for a phrase the model `first` heard as `text`.

    `ask(model)` gives that model's hearing of the same phrase, or None if it can't be
    had. The third is asked only if the second differs. `ignore` and `keep` are as for
    settle().
    """
    second_name, third_name = others(first)
    second = ask(second_name)
    if second is None:
        return text, "nobody to ask"
    if same(text, second, ignore):
        return text, "the same"
    if not _words(second.split()) and not murmur(text):
        # Whisper says nothing at all to some short phrases that were really said,
        # "period" among them. Its silence only counts against a murmur.
        return text, "the second heard nothing, and it stood"
    third = ask(third_name)
    if third is None:
        return text, "differed, with nobody to settle it"
    settled = settle(text, second, third, ignore, keep)
    if not _words(settled.split()) and not murmur(text):
        return text, "differed, and stood"
    return settled, "differed, and changed" if settled != text else "differed, and stood"


# What a recogniser makes of a murmur, a sigh or a cough.
MURMURS = frozenset("mm mmm hm hmm hmmm mhm mmhmm uh um uhm umm er erm ah oh eh huh ha".split())


def murmur(text: str) -> bool:
    """Whether `text` is nothing but the sounds a recogniser writes for a murmur."""
    words = [word.replace("-", "") for word in _words(text.split())]
    return bool(words) and all(word in MURMURS for word in words)


def same(first: str, second: str, ignore=()) -> bool:
    """Whether two hearings have the same words. Capitals and punctuation don't count,
    and neither do the phrases in `ignore`: see settle()."""
    return ([key for key in _keys(first.split(), ignore) if key]
            == [key for key in _keys(second.split(), ignore) if key])


def settle(first: str, second: str, third: str, ignore=(), keep=None) -> str:
    """`first`, with `second`'s words wherever the two differ and `third` sides with
    `second`. Where the third agrees with neither, `first` stands.

    `first` is whose punctuation and capitals the rest of the phrase keeps.

    `ignore` lists phrases, each a list of words, that are not to be compared:
    punctuation said aloud. One recogniser writes "question mark" and another "?", and
    which of those it is has its own rules elsewhere. Such words in `first` always stay.

    `keep(words)` says whether words of `first` are to stand whatever the others heard:
    the person's own names, which only a recogniser that was told of them writes.
    """
    a, b = first.split(), second.split()
    a_keys, b_keys = _keys(a, ignore), _keys(b, ignore)
    judge = [key for key in _keys(third.split(), ignore) if key]
    as_first = [key for key in a_keys if key]
    out = []
    matcher = SequenceMatcher(None, a_keys, b_keys, autojunk=False)
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            out += a[a1:a2]
            continue
        # What isn't compared stays where it is, at either end of the place they differ.
        lead = a1
        while lead < a2 and not a_keys[lead]:
            lead += 1
        tail = a2
        while tail > lead and not a_keys[tail - 1]:
            tail -= 1
        theirs = [token for token, key in zip(b[b1:b2], b_keys[b1:b2]) if key]
        as_second = [key for key in a_keys[:a1] + b_keys[b1:b2] + a_keys[a2:] if key]
        if ((tail == lead and not theirs) or (keep is not None and keep(a[lead:tail]))
                or _apart(as_second, judge) >= _apart(as_first, judge)):
            out += a[a1:a2]
        else:
            out += a[a1:lead]
            out += _in_place_of(a[lead:tail], theirs, starts=lead == 0, bare=tail < a2)
            out += a[tail:a2]
    return " ".join(out)


def _in_place_of(old: list, new: list, starts: bool, bare: bool = False) -> list:
    """`new` words, dressed as the `old` ones they replace were: the punctuation after
    them, and a capital if they start the phrase and the old ones had one. `bare` leaves
    the new words without punctuation after them: something said aloud follows."""
    new = list(new)
    if not new:
        return new
    if bare:
        new[-1] = re.sub(r"\W+$", "", new[-1])
    if not old:
        return new
    tail = re.search(r"\W*$", old[-1]).group()
    if own_stop(old[-1]):
        tail = tail[1:]  # the stop was that word's own: "St. John" is not "Saint. John"
    if tail and new[-1][-1:].isalnum() and not bare:
        new[-1] += tail
    was, now = _EDGES.sub("", old[0]), _EDGES.sub("", new[0])
    if starts and was[:1].isupper() and now[:1].islower():
        new[0] = new[0].replace(now, now[0].upper() + now[1:], 1)
    return new


def _key(token: str) -> str:
    """A word as it is compared: lower case, without the punctuation around it, and
    with one spelling for the words that have a British and an American one ("colour",
    "color") or a long and a short one ("Doctor", "Dr.")."""
    key = _EDGES.sub("", token.lower().replace("\u2019", "'"))
    return fold(_SAME_WORD.get(key, key))


def _keys(tokens: list, ignore=()) -> list:
    """How each of `tokens` is compared, or "" for one that isn't: punctuation by itself,
    and the words of a phrase in `ignore`."""
    keys = [_key(token) for token in tokens]
    at = 0
    while at < len(keys):
        for phrase in ignore:
            if phrase and keys[at:at + len(phrase)] == list(phrase):
                keys[at:at + len(phrase)] = [""] * len(phrase)
                at += len(phrase) - 1
                break
        at += 1
    return keys


def _words(tokens: list) -> list:
    return [key for key in map(_key, tokens) if key]


def _apart(one: list, other: list) -> int:
    """How many words have to be changed, put in or taken out to make `one` into `other`."""
    row = list(range(len(other) + 1))
    for i, word in enumerate(one, start=1):
        last, row[0] = row[0], i
        for j, against in enumerate(other, start=1):
            last, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, last + (word != against))
    return row[-1]
