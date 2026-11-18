"""Telling names from ordinary words.

Whisper capitalises the first word of every phrase. When a phrase goes into
the middle of a sentence, that capital has to go, unless the word is a name.

Also here: telling that two spellings are one word. The dictionary on a computer is
British or American, and the recogniser may write the other: "colour" and "color" are
both everyday words, and are the same word when one is looked for or compared.
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
    we're they're you're he's she's what's
    back done fine good here home late okay people please ready right sorry still sure
    team thanks time today tomorrow yesterday""".split()
)

# Forms of "I" keep their capital everywhere.
I_WORDS = frozenset({"i", "i'm", "i've", "i'll", "i'd"})

# Words that lead up to a name without being part of it: "ask Tom", "in May", "the
# Smiths". With a capital and another capitalised word after it, any other word may be
# the first half of a name: "New" Zealand, "Mark" Jones, "Will" Smith.
LEAD_INS = (COMMON - {"will"}) | frozenset(
    """although ask asked best between call called dear during email emailed give gave
    hello help hey hi hope left let love maybe meet met near perhaps phone phoned ring rang
    say says saw seen send sent set since tell told thank though tonight unless until visit
    visited wake whether within without""".split()
)

# Everyday words that a dictionary lists as names as well, because somebody or somewhere
# is called that: Mr Fields, Mrs Banks, the United States. At the start of a phrase they
# are far more often the word ("the report" and then "States that...", "three" and then
# "Fields"), so there they lose the recogniser's capital like any other word. A name
# that is seldom anything else ("James", "Wales", "Holmes") is not here. Nor is
# "Windows", which in what is dictated at a computer is the system more often than the
# glass: somebody for whom it isn't can list "windows" among their own words.
EVERYDAY_FORMS = frozenset(
    """acts angers armour banks barking borders bridges burns cascades chambers chronicles
    classics coloured combs dives downs fates fields flowers flushing furies gates graces
    graves grey groves hawks jobs judges logos marks masters meadows miles mills numbers ops
    parks pigs pines powers queens revelations rivers rules scopes sessions shields shires
    sparks spears staples states summers tours tyre villas walls watts weeks wheeling
    winters worms writings""".split()
)

# The same word as it is spelled in Britain and in America, where no rule covers it.
_BRITISH = dict(pair.split("=") for pair in (
    "grey=gray centre=center metre=meter litre=liter theatre=theater fibre=fiber "
    "defence=defense offence=offense licence=license practise=practice programme=program "
    "catalogue=catalog dialogue=dialog analogue=analog cheque=check tyre=tire plough=plow "
    "judgement=judgment jewellery=jewelry aluminium=aluminum mum=mom").split())
_AMERICAN = {american: british for british, american in _BRITISH.items()}
_ENDINGS = r"(?=(?:s|ed|ing|ite|ites|able|ably|ful|fully|less|er|ers|hood|ly)?$)"
_OUR = re.compile(r"(?<=[a-z]{2})our" + _ENDINGS)        # colour, favourite: not four, hour
# The other way there is no rule, or "doctor" would be "doctour": these are the words.
_OR = re.compile(
    r"^(arm|behavi|cand|clam|col|endeav|fav|ferv|flav|harb|hon|hum|lab|neighb|od|parl|rig|"
    r"rum|sav|savi|splend|tum|val|vap|vig)or" + _ENDINGS)
_ISE = re.compile(r"is(?=(?:e|es|ed|ing|er|ers|ation|ations|able)$)")   # realise, organisation
_IZE = re.compile(r"iz(?=(?:e|es|ed|ing|er|ers|ation|ations|able)$)")
_YSE = re.compile(r"ys(?=(?:e|es|ed|ing|er|ers)$)")                     # analyse
_YZE = re.compile(r"yz(?=(?:e|es|ed|ing|er|ers)$)")


def fold(word: str) -> str:
    """`word`, in small letters, with a British spelling made American, so that "colour"
    and "color", "realise" and "realize" compare as the one word they are."""
    word = _YSE.sub("yz", _ISE.sub("iz", _OUR.sub("or", word)))
    return _BRITISH.get(word, word)


def spellings(word: str) -> frozenset:
    """Other ways `word`, in small letters, may be spelled on the other side of the
    Atlantic. They are guesses made by rule, so now and then one is no word at all
    ("sise" for "size"): they are for looking up, in a dictionary or a document, and
    never for writing down."""
    found = {fold(word), _OR.sub(r"\1our", word), _IZE.sub("is", word), _YZE.sub("ys", word),
             _AMERICAN.get(word, word)}
    return frozenset(found - {word})

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


def repetitive(text: str) -> bool:
    """Whether `text` is mostly the same few words over and over.

    Whisper, shown such text as what came before, carries on with it whatever is said:
    after "say say say say" even "the weather is nice" is written down as "say say say".
    """
    words = re.findall(r"[\w'’]+", text.lower())
    return len(words) >= 6 and len(set(words)) * 2 < len(words)


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
    def from_hunspell(cls, *paths: str) -> "Lexicon":
        """The words of one or more Hunspell dictionaries (their .dic files)."""
        lower, capitalised = set(), set()
        for path in paths:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
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
        """The first English dictionary found, or common words only.

        Linux has the system's own. Where there is none, as on Windows, the installer
        puts dictionaries in a folder of its own, and all of those are used together.
        """
        for path in DICTIONARIES:
            if os.path.exists(path):
                return cls.from_hunspell(path)
        try:
            from . import config
        except ImportError:  # inside the Writer extension, which carries only the rule modules
            return cls()
        folder = os.path.join(config.INSTALL_DIR, "dictionaries")
        try:
            own = sorted(os.path.join(folder, name) for name in os.listdir(folder)
                         if name.endswith(".dic"))
            if own:
                return cls.from_hunspell(*own)
        except OSError:
            pass
        return cls()

    @property
    def has_dictionary(self) -> bool:
        return bool(self.lower)

    def ordinary(self, word: str) -> bool:
        """Whether `word` is an everyday word, as far as is known. A British dictionary
        knows "colour" and an American one "color": either way both are everyday words."""
        low = word.lower().replace("’", "'")
        if low in COMMON or any(s in self.lower for s in _stems(low)):
            return True
        return any(s in self.lower for other in spellings(low) for s in _stems(other))

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
        if (core.replace("’", "'") in self.capitalised and low not in self.lower
                and low not in COMMON and low not in EVERYDAY_FORMS):
            # The dictionary has it as a name and not as a word: "James" is not "jam"
            # with an ending, nor "Wales" more than one "wale". (But "States" is "state"
            # with one, far more often than it is the United States: see EVERYDAY_FORMS.)
            return token
        if self.ordinary(low):
            return lead + core[0].lower() + core[1:] + rest
        return token
