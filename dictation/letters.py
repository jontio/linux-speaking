"""The opening and the end of a letter or an email, as they are said.

A letter or an email often starts "Hi Joe, ..." and ends "Cheers, Joe", and these are the very
places a recogniser gets wrong, for want of anything around them to go by: a name is
written in small letters ("hi joe"), "comma" said straight after it is heard as the word
"common", and a sign-off said by itself on its line is misheard ("Chairs" for "Cheers").
And people say "enter" for the line break between a sign-off and their name.

So, only in those places:

- `said(text)`: in a phrase that opens with a greeting and a name, or with a sign-off,
  "common" straight after them is "comma", however the recogniser marked the pauses ("Hi,
  Joe, common", "Hi Joe. Common new paragraph."); after "Hi all" or "Hello everyone", or
  "Hi" by itself, where only a line break or a pause comes after it. The name after a
  greeting gets its capital.
- `signoff(whole, starts)`: a check for tidy.amend (see tidy.py): a short line that is a
  sign-off, or sounds like one, followed by "enter" or "new line" and a name, is laid out
  as a sign-off: "Cheers," and the name on the next line.

Nowhere else is anything touched: "a common mistake", "chairs for the table" and "enter
the room" are left as they are.
"""
from __future__ import annotations

import re

from .formatting import LINE, PARAGRAPH

GREETINGS = r"(?:hi|hello|hey|hiya|dear|good\s+(?:morning|afternoon|evening)|morning|g['’]?day|kia\s+ora)"
SIGNOFFS = (r"(?:cheers|thanks|thank\s+you|many\s+thanks|regards|kind\s+regards|best\s+regards|warm\s+regards|"
            r"best\s+wishes|all\s+the\s+best|best|yours\s+sincerely|yours\s+faithfully|yours\s+truly|"
            r"take\s+care|love|speak\s+soon|talk\s+soon)")
# What a sign-off said by itself on its line is heard as, by a recogniser with nothing else
# to go by: only these, and only there.
MISHEARD_SIGNOFFS = {"chairs": "Cheers", "chair's": "Cheers", "chairs.": "Cheers", "cheer's": "Cheers",
                     "cheer": "Cheers", "chess": "Cheers", "jeers": "Cheers", "regard": "Regards"}
# The words after a greeting that are not a name: "hi there", "hello everyone".
NOT_A_NAME = frozenset(("there all everyone everybody team folks guys again both you mate sir madam "
                        "friend friends world and how what so well yes no ok okay thanks thank i it is "
                        "this that we").split())
# Of those, the ones that say who the greeting is to, as a name does: after "Hi all" and
# "Hello everyone", as after "Hi Joe", "common" said there is the comma. (Not after "Hi how".)
ADDRESSEES = frozenset(("there all everyone everybody team folks guys again both you mate sir madam "
                        "friend friends world").split())

_BREAK = "\n\r" + LINE + PARAGRAPH
# What "comma" said after a pause is heard as (the "n" of "comma new paragraph" is heard twice).
_COMMA_HEARD = r"(?:common|commons|coma|comer|commer|karma|comma's)"
# Where "common" by itself is the comma: with nothing after it, a line break said after it, or
# a pause the recogniser wrote as a mark ("Common, how are you?"). Not with more words straight
# after it: "Common sense is rare" is words.
_THEN_A_BREAK = r"(?=\s*(?:$|[.,!?;:]|new\s+paragraph\b|new\s+line\b|next\s+line\b|enter\b))"
_COMMA_ALONE = re.compile(r"(?i)^(\W*)" + _COMMA_HEARD + r"\b" + _THEN_A_BREAK)
# A greeting and who it is to, however the recogniser marked the pause between them: "Hi Joe",
# "Hi, Joe", "Dear Dr Smith", "Hello everyone".
_TO = r"(\s*" + GREETINGS + r",?\s+(?:(?:mr|mrs|ms|miss|dr|prof)\.?\s+)?)([a-z][a-z'’-]*)"
_GREETED_LINE = re.compile(r"(?i)^" + _TO + r"\s*[,.!]?\s*$")
_GREETING_LINE = re.compile(r"(?i)^\s*" + GREETINGS + r"\s*[,.!]?\s*$")     # "Hi", by itself
_SIGNED_LINE = re.compile(r"(?i)^\s*" + SIGNOFFS + r"\s*[,.!]?\s*$")
# "Hi Joe, common", "Hi, Joe, common", and with a stop after the name, "Hi Joe. Common":
# there only before a break, as "Hi Joe. Common sense is rare." is words.
_OPENING = re.compile(r"(?i)^" + _TO + r"(?:,?\s+|\.\s+(?=" + _COMMA_HEARD + r"\b" + _THEN_A_BREAK + r"))"
                      + _COMMA_HEARD + r"\b")
_OPENING_ALONE = re.compile(r"(?i)^(\s*" + GREETINGS + r")[,.!]?\s+" + _COMMA_HEARD + r"\b" + _THEN_A_BREAK)
_GREETED = re.compile(r"(?i)^(\s*" + GREETINGS + r",?\s+)([a-z][a-z'’-]*)"
                      r"(?=\s*(?:[,.!]|\bcomma\b|" + _COMMA_HEARD + r"\b|$))")
_CLOSING = re.compile(r"(?i)^(\s*" + SIGNOFFS + r")(?:,?\s+|[.!]\s+(?=" + _COMMA_HEARD + r"\b" + _THEN_A_BREAK
                      + r"))" + _COMMA_HEARD + r"\b")


_A_BREAK_NEXT = re.compile(r"(?i)" + _THEN_A_BREAK)


def _to_someone(word: str) -> bool:
    """Whether `word`, after a greeting, says who it is to: a name, or "all" or "everyone"."""
    return word.lower() not in NOT_A_NAME or word.lower() in ADDRESSEES


def _comma_after(found: re.Match, text: str) -> bool:
    """Whether the "common" that `found` (an _OPENING match) ends with is the comma: after a
    name, yes; after "all", "everyone" and the like only with a break after it, as "Hello
    there, common ground" is words."""
    word = found.group(2).lower()
    if word not in NOT_A_NAME:
        return True
    return word in ADDRESSEES and bool(_A_BREAK_NEXT.match(text, found.end()))


def said(text: str, before: str = "") -> str:
    """A phrase as the recogniser wrote it, with "common" taken as "comma" straight after
    a greeting and a name, or after a sign-off, and a small-lettered name after a greeting
    given its capital. Each only at the start of the phrase; and the first where the greeting
    or the sign-off is the line before the phrase, `before` ("Hi Joe", and then "Common new
    paragraph."), said with a pause after it. The comma said takes the place of any mark the
    recogniser wrote for the pause before it: "Hi, Joe. Common new paragraph." is "Hi Joe,"."""
    line = re.split("[" + _BREAK + "]", before)[-1] if before else ""
    greeted = _GREETED_LINE.match(line)
    if ((greeted and _to_someone(greeted.group(2))) or _GREETING_LINE.match(line)
            or _SIGNED_LINE.match(line)) and _COMMA_ALONE.match(text):
        text = _COMMA_ALONE.sub(lambda m: m.group(1) + "comma", text, count=1)
    found = _OPENING.match(text)
    if found and _comma_after(found, text):
        text = found.group(1) + found.group(2) + " comma" + text[found.end():]
    else:
        found = _OPENING_ALONE.match(text) or _CLOSING.match(text)
        if found:
            text = found.group(1) + " comma" + text[found.end():]
    found = _GREETED.match(text)
    if found and found.group(2).lower() not in NOT_A_NAME and found.group(2).islower():
        name = found.group(2)
        text = text[:found.start(2)] + name[:1].upper() + name[1:] + text[found.end(2):]
    return text


# ---- the sign-off line ----------------------------------------------------------------------
def signoff(names=()):
    """A check for tidy.amend: on the last line of the text, a sign-off (or one of the words
    a sign-off is misheard as, there alone on its line) followed by "enter" or "new line"
    and a name becomes the sign-off with a comma, a line break and the name: "Chairs,
    enter, Joe" is "Cheers," and "Joe" on the next line. `names` are the person's own
    words, which are spelled as they spell them."""
    own = {str(n).lower(): str(n) for n in names}
    signoffs = re.compile(r"(?i)^" + SIGNOFFS + r"$")
    pattern = re.compile(
        r"(?i)(?:^|(?<=[" + _BREAK + r"]))(?P<off>[^\W\d_][\w'’ ]{0,24}?)(?P<mark>[,.]?)\s*"
        r"(?:,\s*)?(?:\b(?:enter|new\s+line)\b[,.]?\s*)(?P<name>[^\W\d_][\w'’-]*)[.]?\s*$")

    def check(whole: str, starts: int) -> list:
        from .tidy import Change
        found = pattern.search(whole)
        if not found or found.end("name") <= starts:
            return []
        off = found.group("off").strip()
        word = MISHEARD_SIGNOFFS.get(off.lower())
        if word is None:
            if not signoffs.match(off):
                return []
            word = off[:1].upper() + off[1:]
        name = found.group("name")
        name = own.get(name.lower(), name[:1].upper() + name[1:])
        return [Change(found.start("off"), len(whole), word + "," + LINE + name, "layout")]
    return check
