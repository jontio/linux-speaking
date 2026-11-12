"""Telling names from ordinary words.

Whisper capitalises the first word of every phrase. When a phrase goes into
the middle of a sentence, that capital has to go, unless the word is a name.
"""
from __future__ import annotations

import os
import re

# Words that are almost never names. Used with or without a dictionary.
COMMON = frozenset(
    """a about after again all also always an and any are as at be because been
    before being both but by can could did do does down each even ever every for
    from get go going got had has have he her here him his how if in into is it
    its just know like make many me more most much my never no not now of off on
    once one only or other our out over said same see she should so some such
    than that the their them then there these they thing think this those
    through to too two up us very was way we well were what when where which
    while who why will with would yes yet you your
    don't can't won't isn't wasn't didn't doesn't it's that's there's let's
    we're they're you're he's she's what's""".split()
)

# Forms of "I" keep their capital everywhere.
I_WORDS = frozenset({"i", "i'm", "i've", "i'll", "i'd"})

DICTIONARIES = (
    "/usr/share/hunspell/en_NZ.dic",
    "/usr/share/hunspell/en_GB.dic",
    "/usr/share/hunspell/en_US.dic",
)

_WORD = re.compile(r"^(\W*)([\w'’]+)(.*)$", re.DOTALL)
_SUFFIXES = (
    ("'s", ""), ("’s", ""), ("ies", "y"), ("es", ""), ("s", ""),
    ("ed", ""), ("ed", "e"), ("d", ""), ("ing", ""), ("ing", "e"), ("ly", ""),
)


def _stems(word: str):
    yield word
    for suffix, replacement in _SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            yield word[: -len(suffix)] + replacement


class Lexicon:
    """Knows which words are ordinary words and which are names."""

    def __init__(self, lower=(), capitalised=()):
        self.lower = set(lower)
        self.capitalised = set(capitalised)

    @classmethod
    def from_hunspell(cls, path: str) -> "Lexicon":
        lower, capitalised = set(), set()
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f):
                word = line.split("/")[0].split("\t")[0].strip()
                if not word or (n == 0 and word.isdigit()):
                    continue
                if word[0].isupper():
                    capitalised.add(word)
                else:
                    lower.add(word.lower())
        return cls(lower, capitalised)

    @classmethod
    def load_default(cls) -> "Lexicon":
        """The first English dictionary found, or common words only."""
        for path in DICTIONARIES:
            if os.path.exists(path):
                return cls.from_hunspell(path)
        return cls()

    @property
    def has_dictionary(self) -> bool:
        return bool(self.lower)

    def ordinary(self, word: str) -> bool:
        """Whether `word` is an everyday word, as far as is known."""
        low = word.lower().replace("’", "'")
        return low in COMMON or any(s in self.lower for s in _stems(low))

    def decapitalise(self, token: str) -> str:
        """Lower-case the first letter of `token` unless it looks like a name."""
        m = _WORD.match(token)
        if not m:
            return token
        lead, core, rest = m.groups()
        if not core[0].isupper():
            return token
        low = core.lower().replace("’", "'")
        if low in I_WORDS:
            return token
        if len(core) > 1 and core.isupper():  # NASA, TV
            return token
        if any(c.isupper() for c in core[1:]):  # McDonald, LibreOffice
            return token
        if self.ordinary(low):
            return lead + core[0].lower() + core[1:] + rest
        return token
