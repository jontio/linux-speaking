"""Fitting dictated text into the text around the cursor, the way Dragon did.

This is plain string work, so it can be tested without LibreOffice. The Writer
side passes in the text before and after the cursor in the current paragraph
and applies the returned Insertion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .words import Lexicon

PARAGRAPH = " "  # Writer turns this into a paragraph break
LINE = " "       # Writer turns this into a line break
BREAKS = PARAGRAPH + LINE

OPENERS = "([{“‘"
ATTACH_LEFT = ",.;:!?)]}%…”’"  # no space before these
SENTENCE_END = ".!?"
ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "st.", "e.g.", "i.e.", "vs.", "cf.")

# Spoken punctuation. Longer phrases come first so "semi colon" beats "colon".
SPOKEN = (
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("question mark", "?"),
    ("new paragraph", PARAGRAPH),
    ("new line", LINE),
    ("open bracket", "("),
    ("close bracket", ")"),
    ("open quote", "“"),
    ("close quote", "”"),
    ("semi colon", ";"),
    ("semicolon", ";"),
    ("full stop", "."),
    ("period", "."),
    ("ellipsis", "…"),
    ("hyphen", "-"),
    ("comma", ","),
    ("colon", ":"),
)

# Phrases that stay ordinary words unless they are switched on in Settings.
DEFAULT_OFF = ("period",)

# While working, each spoken symbol is held as a private-use character, so it
# can't be confused with punctuation Whisper wrote itself.
_SYM_BASE = 0xE000
_SYMBOLS = [symbol for _, symbol in SPOKEN]
_PROTECT = ""  # wraps a "literal" phrase so it stays as words
_PROTECT_SPACE = ""


def _phrase_regex(phrase: str) -> str:
    return r"[\s-]+".join(re.escape(w) for w in phrase.split())


_SPOKEN_RES = [
    (
        phrase,
        re.compile(
            r"[,.;:!?]*\s*(?<![\w'])" + _phrase_regex(phrase)
            + r"(?![\w'])[,.;:!?]*",
            re.IGNORECASE,
        ),
        chr(_SYM_BASE + i),
    )
    for i, (phrase, _) in enumerate(SPOKEN)
]
_LITERAL_RE = re.compile(
    r"(?<![\w'])literal\s+("
    + "|".join(_phrase_regex(p) for p, _ in SPOKEN)
    + r")(?![\w'])",
    re.IGNORECASE,
)


def _is_sym(token: str) -> bool:
    return len(token) == 1 and _SYM_BASE <= ord(token) < _SYM_BASE + len(_SYMBOLS)


def _sym(token: str) -> str:
    return _SYMBOLS[ord(token) - _SYM_BASE]


def _cap_first(token: str) -> str:
    for i, c in enumerate(token):
        if c.isalpha():
            return token[:i] + c.upper() + token[i + 1:]
    return token


def _ends_sentence(token: str) -> bool:
    t = token.rstrip("\"')]}”’")
    return bool(t) and t[-1] in SENTENCE_END


@dataclass(frozen=True)
class Insertion:
    """What to do at the cursor."""

    text: str
    delete_before: int = 0       # spaces to remove before the cursor first
    delete_after: int = 0        # spaces to remove after the cursor first
    capitalise_next: bool = False  # capitalise the word after the insertion


def sentence_start(before: str) -> bool:
    """True if text typed after `before` should start with a capital."""
    if before[-1:] in (PARAGRAPH, LINE, "\n", "\r"):
        return True
    s = before.rstrip(" \t" + OPENERS + "\"')]}”’")
    if not s or s[-1] in BREAKS + "\n\r":
        return True
    low = s.lower()
    for abbr in ABBREVIATIONS:
        if low.endswith(abbr):
            cut = len(low) - len(abbr)
            if cut == 0 or not low[cut - 1].isalnum():
                return False
    return s[-1] in SENTENCE_END


def _opening_context(before: str) -> bool:
    """True if the cursor sits just after an opening bracket or quote."""
    if not before:
        return False
    prev = before[-1]
    if prev in OPENERS:
        return True
    if prev in "\"'":
        return len(before) == 1 or before[-2].isspace() or before[-2] in OPENERS
    return False


def fit(
    raw: str,
    before: str,
    after: str,
    lexicon: Lexicon | None = None,
    keep_final: bool = False,
    spoken_off=None,
) -> Insertion:
    """Fit one dictated phrase from Whisper between `before` and `after`.

    `keep_final` keeps Whisper's own full stop or question mark at the end of
    the phrase. By default it is dropped, as Dragon only typed punctuation you
    spoke. It is always dropped when inserting into the middle of a sentence.

    `spoken_off` lists spoken punctuation phrases to leave as ordinary words.
    """
    off = set(DEFAULT_OFF if spoken_off is None else spoken_off)
    lexicon = lexicon or Lexicon()
    text = " ".join(raw.split())

    after_text = after.lstrip(" \t")
    mid_sentence = bool(after_text) and after_text[0] not in BREAKS + "\n\r"
    if not keep_final or mid_sentence:
        text = re.sub(r"[.!?]+$", "", text)

    text = _LITERAL_RE.sub(
        lambda m: _PROTECT + m.group(1).replace(" ", _PROTECT_SPACE) + _PROTECT,
        text,
    )
    for phrase, regex, marker in _SPOKEN_RES:
        if phrase not in off:
            text = regex.sub(" " + marker + " ", text)

    tokens = text.split()
    if not tokens:
        return Insertion("")

    # Capitals: the first word follows the document, later ones follow the
    # punctuation spoken in this phrase.
    capital = sentence_start(before)
    first_word = True
    for i, token in enumerate(tokens):
        if _is_sym(token):
            symbol = _sym(token)
            if symbol in SENTENCE_END or symbol in BREAKS:
                capital = True
            elif symbol in ATTACH_LEFT:
                capital = False
            continue
        if capital:
            tokens[i] = _cap_first(token)
        elif first_word:
            tokens[i] = lexicon.decapitalise(token)
        first_word = False
        capital = _ends_sentence(token)

    # Spaces between tokens.
    out = []
    prev = None
    for token in tokens:
        if prev is not None:
            cur = _sym(token) if _is_sym(token) else ""
            prv = _sym(prev) if _is_sym(prev) else ""
            joined = (
                (cur and (cur in ATTACH_LEFT or cur in BREAKS or cur == "-"))
                or (prv and (prv in OPENERS or prv in BREAKS or prv == "-"))
            )
            if not joined:
                out.append(" ")
        out.append(_sym(token) if _is_sym(token) else token)
        prev = token
    result = "".join(out).replace(_PROTECT, "").replace(_PROTECT_SPACE, " ")

    # Spaces against the document.
    first, last = result[0], result[-1]
    delete_before = 0
    if first in ATTACH_LEFT or first in BREAKS or first == "-":
        delete_before = len(before) - len(before.rstrip(" \t"))
    elif before and not before[-1].isspace() and before[-1] not in BREAKS + "-/" \
            and not _opening_context(before):
        result = " " + result

    delete_after = 0
    if last in BREAKS:
        delete_after = len(after) - len(after_text)
    elif after and (after[0].isalnum() or after[0] in OPENERS + "\"'") \
            and last not in OPENERS + "-":
        result = result + " "

    capitalise_next = (
        mid_sentence
        and (last in SENTENCE_END or last in BREAKS)
        and after_text[0].islower()
    )
    return Insertion(result, delete_before, delete_after, capitalise_next)


def preview(before: str, after: str, ins: Insertion) -> str:
    """The paragraph as it reads after applying `ins`. Used by the tests."""
    head = before[: len(before) - ins.delete_before]
    tail = after[ins.delete_after:]
    if ins.capitalise_next:
        tail = _cap_first(tail)
    return head + ins.text + tail
