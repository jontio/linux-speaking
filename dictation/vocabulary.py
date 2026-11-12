"""Your own words: names and unusual terms the recogniser should know about.

Whisper is given the words as a hint. A hint is strong: with "Jonti" in it, "a jaunty
tune" comes out as "a Jonti tune". So when a hinted phrase contains one of the words, the
phrase is heard again without the hint and the two hearings are compared. Where the plain
hearing has an ordinary word written the ordinary way ("jaunty" in the middle of a
sentence), that stands. Where it has what looks like a name it didn't know ("John T."),
or the words before call for a name ("Cheers,"), your word stands.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .formatting import SPOKEN
from .words import I_WORDS, Lexicon

MAX_WORDS = 40
MAX_WORD_CHARS = 40
MAX_HINT_CHARS = 300

# Words that a name usually follows: greetings, sign-offs and introductions.
CUES = tuple(cue.split() for cue in (
    "hi", "hello", "hey", "dear", "morning", "afternoon", "evening", "thanks", "thank you",
    "cheers", "regards", "wishes", "best", "sincerely", "faithfully", "love", "from",
    "name is", "name's", "i'm", "i am", "call me", "called", "named",
))
# Punctuation and line breaks said aloud: "cheers comma new line" still ends in a cue.
SAID = tuple(phrase.split() for phrase, _ in SPOKEN) + (["newline"],)
_EDGES = re.compile(r"^\W+|\W+$")
_SENTENCE_END = re.compile(r"[.!?][\"')\]”’]*$")


def parse(text) -> tuple:
    """The words in what was typed into Settings: one to a line, or with commas between."""
    if not isinstance(text, str):
        text = "\n".join(str(word) for word in text or ())
    words, seen = [], set()
    for word in re.split(r"[\n,]", text):
        word = " ".join(word.split())[:MAX_WORD_CHARS].strip()
        if word and _key(word) and word.lower() not in seen:
            seen.add(word.lower())
            words.append(word)
    return tuple(words[:MAX_WORDS])


def hint(words) -> str:
    """The words as the start of a prompt for Whisper, or "" if there are none."""
    kept, length = [], 0
    for word in words:
        length += len(word) + 2
        if length > MAX_HINT_CHARS:
            break
        kept.append(word)
    return ", ".join(kept) + ". " if kept else ""


def mentions(text: str, words) -> bool:
    """Whether any of the words is in `text`."""
    return any(_marks([_key(token) for token in text.split()], words))


def settle(hinted: str, plain: str, before: str, words, lexicon: Lexicon | None = None) -> str:
    """One phrase from two hearings of it: `hinted` with the words given, `plain` without.

    `before` is the text before the cursor.
    """
    lexicon = lexicon or Lexicon()
    h, p = hinted.split(), plain.split()
    h_keys, p_keys = [_key(token) for token in h], [_key(token) for token in p]
    mine = _marks(h_keys, words)
    out, kept = [], []  # the tokens, and for each whether it is a word of theirs that stood
    matcher = SequenceMatcher(None, h_keys, p_keys, autojunk=False)
    for op, h1, h2, p1, p2 in matcher.get_opcodes():
        if op == "equal" or not any(mine[h1:h2]):
            out += h[h1:h2]
            kept += [False] * (h2 - h1)
            continue
        alone = h1 == 0 and h2 == len(h) and all(mine)  # the word, said by itself
        lead = [_key(token) for token in before.split()[-3:]] + h_keys[:h1]
        if p2 > p1 and (alone or _cued(lead) or _looks_like_a_name(p, p1, p2, lexicon)):
            out += h[h1:h2]
            kept += mine[h1:h2]
        else:
            out += p[p1:p2]
            kept += [False] * (p2 - p1)
    if not any(kept):
        # The hint changed nothing that stood, so the plain hearing is the truer one.
        return plain if any(mine) else hinted
    return " ".join(_spelled(out, kept, words))


def _key(token: str) -> str:
    """A word as it is compared: lower case, without the punctuation around it or a
    possessive ending."""
    key = _EDGES.sub("", token.lower().replace("’", "'"))
    return key[:-2] if key.endswith("'s") and len(key) > 2 else key


def _places(keys: list, word: str):
    """Where `word` is in `keys`: (index, number of tokens) for each place."""
    want = [key for key in map(_key, word.split()) if key]
    for at in range(len(keys) - len(want) + 1 if want else 0):
        if keys[at:at + len(want)] == want:
            yield at, len(want)


def _marks(keys: list, words) -> list:
    """For each of `keys`, whether it is part of one of the words."""
    marks = [False] * len(keys)
    for word in words:
        for at, count in _places(keys, word):
            marks[at:at + count] = [True] * count
    return marks


def _cued(lead: list) -> bool:
    """Whether the words just before are ones a name follows."""
    lead = [part for key in lead for part in key.split("-") if part]
    while True:
        said = next((phrase for phrase in SAID if lead[-len(phrase):] == phrase), None)
        if said is None:
            break
        del lead[-len(said):]
    return any(lead[-len(cue):] == cue for cue in CUES)


def _looks_like_a_name(tokens: list, start: int, end: int, lexicon: Lexicon) -> bool:
    """Whether Whisper, unhinted, wrote tokens[start:end] as a name or an unknown word.

    A capital in the middle of a sentence is its way of writing a name. The first word of
    a sentence, and of every phrase, has a capital anyway, so there the dictionary decides.
    """
    for at in range(start, end):
        core, key = _EDGES.sub("", tokens[at]), _key(tokens[at])
        if not core or not core[0].isalpha() or key in I_WORDS:
            continue
        ordinary = lexicon.ordinary(key)
        first = at == 0 or bool(_SENTENCE_END.search(tokens[at - 1]))
        if core[0].isupper():
            if not first or not ordinary:
                return True
        elif lexicon.has_dictionary and not ordinary:
            return True
    return False


def _spelled(tokens: list, kept: list, words) -> list:
    """`tokens` with each word of theirs that stood written as it is in the list,
    capitals and all. A word listed without capitals is left as it was heard."""
    tokens = list(tokens)
    keys = [_key(token) for token in tokens]
    for word in words:
        if word == word.lower():
            continue
        parts = [part for part in word.split() if _key(part)]
        for at, count in _places(keys, word):
            if any(kept[at:at + count]) and count == len(parts):
                for n, part in enumerate(parts):
                    tokens[at + n] = re.sub(re.escape(_EDGES.sub("", part)), lambda _: part,
                                            tokens[at + n], count=1, flags=re.IGNORECASE)
    return tokens
