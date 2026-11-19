"""Fitting dictated text into the text around the cursor, the way Dragon did.

This is plain string work, so it can be tested without LibreOffice. The Writer
side passes in the text before and after the cursor in the current paragraph
and applies the returned Insertion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .words import COMMON, I_WORDS, LEAD_INS, Lexicon

PARAGRAPH = " "  # Writer turns this into a paragraph break
LINE = " "       # Writer turns this into a line break
BREAKS = PARAGRAPH + LINE

OPENERS = "([{“‘"
ATTACH_LEFT = ",.;:!?)]}%…”’"  # no space before these
SENTENCE_END = ".!?"
ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "st.", "e.g.", "i.e.", "vs.", "cf.")
# Other shortenings. A sentence can end with one of these, so its full stop says nothing
# about what comes next: but the stop is the word's own, and is never taken off it.
SHORTENINGS = frozenset(
    "etc. inc. ltd. co. corp. jr. sr. approx. dept. est. vol. pp. ave. blvd. rd. mt. prof. "
    "esq. feb. apr. jun. jul. aug. sep. sept. oct. nov. dec. tues. thur. thurs. fri.".split())
# Shortenings that are ordinary words as well: "No. 5" and "I said no."
_SOMETIMES = frozenset("no. fig. gen. col. jan. mar. mon. wed. sat. sun.".split())

# Spoken punctuation, with the British name and the American one where they differ.
# Where one phrase ends with another ("semi colon" and "colon", "em dash" and "dash"),
# the longer is looked for first: see _SPOKEN_RES.
SPOKEN = (
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("question mark", "?"),
    ("new paragraph", PARAGRAPH),
    ("new line", LINE),
    ("open bracket", "("),
    ("close bracket", ")"),
    ("open paren", "("),
    ("close paren", ")"),
    ("open parenthesis", "("),
    ("close parenthesis", ")"),
    ("open square bracket", "["),
    ("close square bracket", "]"),
    ("open curly bracket", "{"),
    ("close curly bracket", "}"),
    ("open brace", "{"),
    ("close brace", "}"),
    ("open quote", "“"),
    ("close quote", "”"),
    ("open single quote", "‘"),
    ("close single quote", "’"),
    ("quote", "“"),      # or the closing one, if one is open: see _paired
    ("unquote", "”"),
    ("end quote", "”"),
    ("semi colon", ";"),
    ("semicolon", ";"),
    ("full stop", "."),
    ("period", "."),
    ("ellipsis", "…"),
    ("hyphen", "-"),
    ("dash", "–"),       # with a space either side: "wait – what"
    ("em dash", "—"),
    ("en dash", "–"),    # with none: "pages 5–10"
    ("slash", "/"),
    ("forward slash", "/"),
    ("backslash", "\\"),
    ("back slash", "\\"),
    ("apostrophe", "'"),
    ("at sign", "@"),
    ("ampersand", "&"),
    ("percent sign", "%"),
    ("hash sign", "#"),
    ("number sign", "#"),
    ("dollar sign", "$"),
    ("euro sign", "€"),
    ("comma", ","),
    ("colon", ":"),
)

# Phrases that stay ordinary words unless they are switched on in Settings: each is an
# everyday word as well ("a trial period", "dash to the shops", "quote me a price").
DEFAULT_OFF = ("period", "dash", "slash", "quote", "unquote", "end quote")

# Other ways a recogniser writes one of the phrases. They are switched with it. (There
# are none now. "Newline" as one word was one, for "new line": but inside a sentence that
# is the word for the character, "strip the trailing newline", and is typed. Said by
# itself it is still the command: see commands.py.)
_ALSO: dict = {}

# How a sign sits against the words beside it, where the sign alone doesn't say: the
# rest go by ATTACH_LEFT and OPENERS, or have a space either side, as "&" and "–" do.
_NO_SPACES = frozenset({"hyphen", "em dash", "en dash", "slash", "forward slash", "at sign"})
_NO_SPACE_BEFORE = frozenset({"apostrophe"})
# (A backslash has a space before it, "ends with \n", except inside a path: see _in_a_path.)
_NO_SPACE_AFTER = frozenset({"hash sign", "number sign", "dollar sign", "euro sign",
                             "backslash", "back slash"})
# What an apostrophe is followed by without a space: "dog apostrophe s" is "dog's".
_AFTER_APOSTROPHE = frozenset({"s", "t", "d", "m", "ll", "re", "ve"})

# A punctuation word is left as a word where the sentence is plainly talking about it,
# or about something else of the same name: "put a comma there", "the word colon", "a new
# line manager", "colon cancer", "the question mark key".
_ARTICLE = re.compile(r"(?:\b(?:a|an|the)|(?:^|[.!?]\s+)(?:A|An|The)|\b[Tt]he words?)\s*$")
_WORD_AFTER = {   # the phrase, and words it follows as an ordinary word
    "colon": frozenset("ascending descending transverse sigmoid irritable spastic".split()),
    "period": frozenset("trial grace waiting notice probation probationary cooling "
                        "incubation transition".split()),
}
_WORD_BEFORE = {  # the phrase, and words it comes before as an ordinary word
    "colon": frozenset("cancer cleanse surgery polyp polyps screening".split()),
    "period": frozenset("of drama piece pain pains".split()),
    "comma": frozenset("separated delimited".split()),
    "dash": frozenset("of".split()),
    "slash": frozenset("and".split()),
    "at sign": frozenset("in up off on out".split()),   # "at sign in", "at sign up"
}
# Where an article is no sign that the phrase is only words:
# a hyphen inside a word that has one in it, "state hyphen of hyphen the hyphen art";
_HYPHENED_ARTICLE = re.compile(r"(?:\bhyphen|-)\s*(?:a|an|the)\s*$", re.IGNORECASE)
# an opening bracket or quote whose closing one is said later, "a open quote quick close
# quote fix" (see _CLOSERS, below the phrases);
_CLOSED_BY = {"(": ")", "[": "]", "{": "}", "“": "”", "‘": "’"}
# and the letter A at the start of a sentence, where what follows the sign is another
# letter or a figure, "A comma B comma and C", or the rest of a word that is written with
# the letter and a hyphen, "A hyphen level maths".
_AFTER_THE_LETTER_A = frozenset(
    "level levels list lister listers frame frames team grade side class plus minus sharp "
    "flat road roads type shaped game".split())

# While working, each spoken symbol is held as a private-use character, so it
# can't be confused with punctuation Whisper wrote itself.
_SYM_BASE = 0xE000
_SYMBOLS = [symbol for _, symbol in SPOKEN]
_PHRASES = [phrase for phrase, _ in SPOKEN]
_LOWER = ""  # after a sign: the next word's capital is the recogniser's, not the speaker's
_PROTECT = ""  # wraps a "literal" phrase so it stays as words
_PROTECT_SPACE = ""


def _phrase_regex(phrase: str) -> str:
    ways = [r"[\s-]+".join(re.escape(w) for w in phrase.split())]
    return "(?:" + "|".join(ways + [re.escape(other) for other in _ALSO.get(phrase, ())]) + ")"


_SPOKEN_RES = [
    (
        phrase,
        re.compile(
            r"[,.;:!?]*\s*(?<![\w'])" + "(" + _phrase_regex(phrase) + ")"
            + r"(?![\w'])[,.;:!?]*",
            re.IGNORECASE,
        ),
        chr(_SYM_BASE + i),
    )
    for i, (phrase, _) in enumerate(SPOKEN)
]
# The longest phrase is looked for first, so that "semi colon" is found before "colon"
# and "open single quote" before "quote".
_SPOKEN_RES.sort(key=lambda found: -len(found[0]))
_LITERAL_RE = re.compile(
    r"(?<![\w'])literal\s+("
    + "|".join(_phrase_regex(p) for p in sorted(_PHRASES, key=len, reverse=True))
    + r")(?![\w'])",
    re.IGNORECASE,
)
_LAST_WORD = re.compile(r"([\w'’.]+)\s*$")
_NEXT_WORD = re.compile(r"\s*([\w'’]+)")
_OWN = "[,.;:!?]*"  # the recogniser's own punctuation beside a phrase: taken with it
# For each opening sign, what finds its closing one further on in a phrase: said, or put
# in already (the longer phrases are seen to first).
_CLOSERS = {
    opener: re.compile(
        r"(?<![\w'])(?:" + "|".join(_phrase_regex(p) for p, s in SPOKEN if s == closer)
        + r")(?![\w'])|[" + "".join(chr(_SYM_BASE + i) for i, (_, s) in enumerate(SPOKEN)
                                    if s == closer) + "]", re.IGNORECASE)
    for opener, closer in _CLOSED_BY.items()
}


def _a_sign_after_all(phrase: str, sign: str, article: str, head: str, tail: str,
                      trail: str) -> bool:
    """Whether a punctuation phrase that follows an article is the sign all the same:
    `article` is what was found before it, `head` and `tail` the text on either side."""
    if phrase == "hyphen" and _HYPHENED_ARTICLE.search(head):
        return True                        # "state hyphen of hyphen the hyphen art"
    if phrase.startswith("open ") and sign in _CLOSED_BY and _CLOSERS[sign].search(tail):
        return True                        # "a open quote quick close quote fix"
    following = _NEXT_WORD.match(tail) if not trail else None
    if article.split()[-1:] == ["A"] and following:
        word = following.group(1)          # as it was written: a letter has its capital
        return bool(re.fullmatch(r"[A-Z]|\d+", word)) or (
            phrase == "hyphen" and word.lower() in _AFTER_THE_LETTER_A)
    return False


def _as_a_sign(phrase: str, marker: str, line_before: str = ""):
    """What to put for one place where the punctuation phrase `phrase` was written: its
    private-use character, or the words as they were, where they are only words there.
    `line_before` is the line in the document up to the cursor, for a phrase that
    starts with one."""
    sign = _SYMBOLS[ord(marker) - _SYM_BASE]

    def put(found: re.Match) -> str:
        head, tail = found.string[:found.start()], found.string[found.end():]
        lead = re.match(_OWN, found.group(0)).group()
        trail = re.search(_OWN + "$", found.group(0)).group()
        before = _LAST_WORD.search(head) if not lead else None
        after = _NEXT_WORD.match(tail) if not trail else None
        said_before = before.group(1).lower() if before else ""
        said_after = after.group(1).lower() if after else ""
        if not head.strip() and not lead and tail.strip():
            head = line_before  # "Put a" and then "comma after the name"
            before = _LAST_WORD.search(head)
            said_before = before.group(1).lower() if before else ""
        # An article is written small, or large where a sentence starts. A capital "A"
        # anywhere else is the letter: "from point A comma go on" has a comma in it.
        article = None if lead else _ARTICLE.search(head)
        if article and _a_sign_after_all(phrase, sign, article.group(), head, tail, trail):
            article = None
        if (article or said_before in _WORD_AFTER.get(phrase, ())
                or said_after in _WORD_BEFORE.get(phrase, ())
                or (phrase == "at sign" and not trail and tail[:1] == "-")):   # "at sign-in"
            # Only words here. They are wrapped, as after "literal", so that a shorter
            # phrase is not then found inside them: the "colon" of "a semi colon".
            at = found.start(1) - found.start()
            written = found.group(1)
            return (found.group(0)[:at] + _PROTECT + written.replace(" ", _PROTECT_SPACE)
                    + _PROTECT + found.group(0)[at + len(written):])
        # "Is it 5 p.m. question mark": the stop before the phrase is the shortening's
        # own, so it stays. Before a full stop that was said, one stop does for both.
        last = _LAST_WORD.search(head)
        kept = "." if (lead[:1] == "." and sign not in (".", "…") and last
                       and own_stop(last.group(1) + ".")) else ""
        # "Hello. Comma. How are you": the recogniser took each piece for a sentence, so
        # the capital it gave the next word means nothing.
        lower = _LOWER if re.search("[.!?]", trail) else ""
        return kept + " " + marker + " " + lower + " "
    return put


# "Hello, Bob": the recogniser puts a comma between a greeting and the name of the person
# greeted. It is what the grammar books say, and not what most people write. The comma is
# only taken out before a name or a word that stands for one, so "Hello, how are you"
# keeps its comma.
#
# Where the greeting starts the phrase or a sentence, that is all there is to it. Further
# on in a sentence ("so if I say hello, Jill") it is taken out too, but with more care,
# because there a comma before a name may be doing other work:
# - only after the words that are nothing but greetings. "Morning" and "evening" are also
#   times of day, and "I saw her this morning, Bob" keeps its comma; so do "he sends his
#   greetings, Dave" and "you're welcome, Dave".
# - only where the name ends what is being said, or is joined on to more ("hello, Jill
#   and..."). In "I said hello, Bob said goodbye" the name begins something new, and the
#   comma is what keeps the two apart.
ADDRESSED = ("everyone", "everybody", "all", "both", "there", "team", "folks", "guys")
# The words that are nothing but greetings, wherever they stand ("hello there" too), and
# those that are greetings only at the start of a sentence: "he sends his greetings,
# Dave" and "you're welcome, Dave" keep their commas.
_ONLY_GREETINGS = (r"(?:hello|hallo|hullo|hi|hiya|heya|hey|howdy|yo|g['’]?day|kia\s+ora)"
                   r"(?:\s+there)?")
_GREETING_COMMA = re.compile(
    r"(^|[.!?…]\s+)"
    r"(" + _ONLY_GREETINGS + r"|greetings|welcome(?:\s+back)?"
    r"|good\s+(?:morning|afternoon|evening|day)|morning|afternoon|evening)"
    r"\s*,\s+"
    r"(?=(?:" + "|".join(ADDRESSED) + r")\b|(?!I\b|I')[A-Z])",
    re.IGNORECASE,
)
_GREETING_COMMA_WITHIN = re.compile(
    r"(\w\s+|[,;:]\s+|[\"“‘(])(" + _ONLY_GREETINGS + r")\s*,\s+(?=[^\W\d_])", re.IGNORECASE)
# A name, of one word or several, each with a capital: "Jill", "Mary-Ann", "Bob O'Brien".
_NAME = re.compile(r"[A-Z][^\W\d_]*(?:['’-][^\W\d_]+)*(?:\s+[A-Z][^\W\d_]*(?:['’-][^\W\d_]+)*)*")
# What may follow the name for the comma to go: nothing, a mark, or a word that joins on.
_NAME_ENDS_IT = re.compile(r"\s*(?:$|[.,!?;:…)\"”’]|(?:and|or|but)\b)", re.IGNORECASE)
_ADDRESSED = re.compile(r"(?:" + "|".join(ADDRESSED) + r")\b", re.IGNORECASE)
_DAYS = frozenset("monday tuesday wednesday thursday friday saturday sunday".split())
_MONTHS = frozenset("january february march april may june july august september october "
                    "november december".split())


def without_greeting_comma(text: str) -> str:
    """`text` without the comma the recogniser puts after "Hello" and the like."""
    def join(m: re.Match) -> str:
        rest = text[m.end():]
        # The pattern ignores case, for "hello" and "Hello" alike. A name has a capital.
        # So have the days and the months, and words written all in capitals, and what
        # follows those is a sentence: "Hello, Monday works for me", "Hi, OK, I will".
        word = re.match(r"[^\W\d_]*", rest).group()
        named = rest[:1].isupper() and not (
            word.isupper() or word.lower() in _DAYS or word.lower() in _MONTHS)
        if not (named or _ADDRESSED.match(rest)):
            return m.group(0)
        return m.group(1) + m.group(2) + " "

    def join_within(m: re.Match) -> str:
        rest = text[m.end():]
        who = _ADDRESSED.match(rest) or _NAME.match(rest)
        if who is None:
            return m.group(0)
        if not _ADDRESSED.match(rest):                 # each word of a name has to be one
            for word in re.findall(r"[^\W\d_]+", who.group()):
                if word == "I" or (len(word) > 1 and word.isupper()) \
                        or word.lower() in _DAYS or word.lower() in _MONTHS:
                    return m.group(0)
        if not _NAME_ENDS_IT.match(rest[who.end():]):
            return m.group(0)
        return m.group(1) + m.group(2) + " "
    return _GREETING_COMMA_WITHIN.sub(join_within, _GREETING_COMMA.sub(join, text))


def _is_sym(token: str) -> bool:
    return len(token) == 1 and _SYM_BASE <= ord(token) < _SYM_BASE + len(_SYMBOLS)


def _sym(token: str) -> str:
    return _SYMBOLS[ord(token) - _SYM_BASE]


def _cap_first(token: str) -> str:
    """`token` with a capital, as the first word of a sentence. Not a word that is
    written with its first letter small and a capital later on, such as "iPhone" or
    "vLR5340": that is how it is spelled, wherever it stands."""
    for i, c in enumerate(token):
        if c.isalpha():
            if c.islower() and any(d.isupper() for d in token[i + 1:]):
                return token
            return token[:i] + c.upper() + token[i + 1:]
    return token


def _ends_sentence(token: str) -> bool:
    t = token.rstrip("\"')]}”’")
    return bool(t) and t[-1] in SENTENCE_END


def own_stop(token: str) -> bool:
    """Whether `token` ends in a full stop that is the word's own, whether or not a
    sentence ends there too: "Dr.", "e.g.", "U.S.", "p.m.", "Ph.D.", "etc."."""
    t = token.strip("\"'()[]{}“”‘’").lower()
    return (t in ABBREVIATIONS or t in SHORTENINGS
            or bool(re.fullmatch(r"(?:[a-z]{1,2}\.){2,}", t)))


def _shortening(token: str) -> bool:
    """Whether the full stop that ends `token` may be the word's own and not a
    sentence's. After such a word the recogniser's capital, or the lack of one, is the
    only sign of whether a sentence began, so the next word is left as it wrote it."""
    return own_stop(token) or token.strip("\"'()[]{}“”‘’").lower() in _SOMETIMES


def _without_final(text: str) -> str:
    """`text` without the full stop or question mark the recogniser ends every phrase
    with. A shortening keeps the stop that is its own: "at 5 p.m."."""
    bare = re.sub(r"[.!?]+$", "", text)
    if bare != text and text[len(bare)] == "." and own_stop((bare.split() or [""])[-1] + "."):
        return bare + "."
    return bare


# A line that so far holds only the mark of a list item, a heading or a quotation.
_MARKER = re.compile(r"[ \t]*(?:[-*+>\u2013\u2014]|#{1,6}|\d+\))(?:[ \t]+\[[ xX]\])?[ \t]+")


@dataclass(frozen=True)
class Insertion:
    """What to do at the cursor."""

    text: str
    delete_before: int = 0       # spaces to remove before the cursor first
    delete_after: int = 0        # spaces to remove after the cursor first
    capitalise_next: bool = False  # capitalise the word after the insertion
    # Whether the text ends with a full stop, question mark or exclamation mark that was
    # said in this phrase: "at 5 p.m. full stop", and "full stop" said by itself after
    # "p.m.", where the one stop does for both and nothing is typed. The caller hands it
    # back with the next phrase (fit's `after_said_end`), because after "p.m." or "etc."
    # the text alone can't say whether a sentence ended.
    said_end: bool = False


def sentence_start(before: str) -> bool:
    """True if text typed after `before` should start with a capital."""
    if before[-1:] in (PARAGRAPH, LINE, "\n", "\r"):
        return True
    line = re.split("[\n\r" + PARAGRAPH + LINE + "]", before)[-1]
    if _MARKER.fullmatch(line):
        return True                       # "- " or "# ": what follows starts the item
    closers = " \t" + OPENERS + "\"')]}”’"
    s = before.rstrip(closers)
    if s[-1:] and s[-1] in "*_`" and _opening_context(s):
        s = s.rstrip("*_`").rstrip(closers)  # "**" before bold words is not yet a word
    if not s or s[-1] in BREAKS + "\n\r":
        return True
    low = s.lower()
    for abbr in ABBREVIATIONS:
        if low.endswith(abbr):
            cut = len(low) - len(abbr)
            if cut == 0 or not low[cut - 1].isalnum():
                return False
    return s[-1] in SENTENCE_END


def _closes(mark: str, before: str) -> bool:
    """Whether a straight quote mark standing just after the cursor closes one that was
    opened before it, as when a program types the pair and puts the cursor between."""
    if mark == '"':
        return before.count('"') % 2 == 1
    if mark == "'":  # not the ones inside words: don't, it's
        return len(re.findall(r"(?<![A-Za-z])'|'(?![A-Za-z])", before)) % 2 == 1
    return False


def _opening_context(before: str) -> bool:
    """True if the cursor sits just after an opening bracket or quote."""
    if not before:
        return False
    prev = before[-1]
    if prev in OPENERS:
        return True
    if prev in "\"'":
        return len(before) == 1 or before[-2].isspace() or before[-2] in OPENERS
    if prev in "*_`":
        # Markdown's marks, typed by hand: "**" before bold words, "`" before code. After
        # a space or at the start of a line they open; after a word they have closed.
        head = before.rstrip(prev)
        opens = not head or head[-1].isspace() or head[-1] in OPENERS
        # One "*" by itself at the start of a line is a list item's mark with its space
        # still to come.
        item = prev == "*" and len(before) - len(head) == 1 and not head.strip(" \t")
        return opens and not item
    return False


def _hug(token: str) -> str:
    """How a spoken sign sits against the words beside it: "left" for no space before
    it, "right" for none after it, "both", or "" for a space either side, which is also
    the answer for a word."""
    if not _is_sym(token):
        return ""
    phrase, sign = _PHRASES[ord(token) - _SYM_BASE], _sym(token)
    if sign in BREAKS or phrase in _NO_SPACES:
        return "both"
    if sign in ATTACH_LEFT or phrase in _NO_SPACE_BEFORE:
        return "left"
    if sign in OPENERS or phrase in _NO_SPACE_AFTER:
        return "right"
    return ""


def _marker(phrase: str) -> str:
    return chr(_SYM_BASE + _PHRASES.index(phrase))


_APOSTROPHE, _AT_SIGN = _marker("apostrophe"), _marker("at sign")
_BACKSLASHES = frozenset({_marker("backslash"), _marker("back slash")})


def _in_a_path(text: str) -> bool:
    """Whether `text` stops part of the way through a file path as Windows writes one,
    so that a backslash goes straight on: after a drive ("C:"), after "." or "..", and
    after anything with a backslash in it already ("C:\\users"). Anywhere else a backslash
    has a space before it, as in "ends with \\n"."""
    # What stands since the last space, or since a bracket or quote that opened: "(C:".
    run = re.split(r"[\s" + re.escape(OPENERS) + "\"'*_`$]", text)[-1] if text else ""
    return "\\" in run or bool(re.fullmatch(r"[A-Za-z]:|\.\.?", run))


def _said_end(tokens: list, before_them: bool = False) -> bool:
    """Whether `tokens` end with a full stop, question mark or exclamation mark that was
    said, with nothing after it but closing brackets and quotes that were said too.
    `before_them` is whether such a sign was said just before the first of them."""
    for token in reversed(tokens):
        if not _is_sym(token):
            return False
        if _sym(token) in SENTENCE_END:
            return True
        if _sym(token) not in ")]}”’":
            return False
    return before_them


def _paired(tokens: list, before: str) -> list:
    """`tokens` with each "quote" made the opening mark or the closing one: it closes
    if a quotation is open, in this phrase or in the text before it, and opens if not.
    So "quote" does for both, as well as "quote ... unquote"."""
    plain, opening, closing = _marker("quote"), _marker("open quote"), _marker("close quote")
    open_now = before.count("“") > before.count("”")
    out = []
    for token in tokens:
        if token == plain:
            token = closing if open_now else opening
        if _is_sym(token) and _sym(token) in "“”":
            open_now = _sym(token) == "“"
        elif "“" in token or "”" in token:
            open_now = token.rfind("“") > token.rfind("”")
        out.append(token)
    return out


_WORD_IN = re.compile(r"^(\W*)([\w'’]+)(.*)$", re.DOTALL)
# Months that are everyday words too, and the words a date comes after: "in May", not
# "you may".
_MONTH_WORDS = frozenset({"may", "march", "august"})
_BEFORE_A_DATE = frozenset(
    "in of since until till by from during before after last next this early late mid "
    "every each".split())
# Some of those come before a verb as well: "I think this" and then "May be a problem".
# After one of them "May" is the month only if what follows could follow a month.
_BEFORE_A_VERB_TOO = frozenset("this from after before by".split())
_AFTER_A_MONTH = frozenset(
    "we you he she it they the and or to until till through onwards onward at in on next "
    "last this of is was will has had are were would could should can".split())
_BEFORE_A_NAME = frozenset("hi hello hey dear thanks cheers".split())
# With a capital and another capitalised word straight after it, the first word of a
# phrase may be the first half of a name. Not any word, though: "Next Monday", "Using
# Python" and "Especially John" have a name in them and are not one. It has to be a word
# the dictionary lists as a name too ("Mark" Jones, "Will" Smith, "New" Zealand), or one
# of these, which names often begin with.
_OPENS_A_NAME = frozenset(
    "new old north south east west central upper lower little big great uncle aunt auntie "
    "professor doctor president mayor judge sir lady lord king queen prince princess "
    "captain saint lake mount port cape fort high air radio kiwi black happy merry visual "
    "open".split())
# Words that seldom start a sentence. After "p.m." or "etc.", whose stop may or may not
# end one, a phrase that begins with one of these goes on with the sentence: where the
# caller can't say whether a stop was said there (fit's `after_said_end`).
_GOES_ON = frozenset("and or of to with from by until than because".split())


def _own_spelling(tokens: list, at: int, names) -> str:
    """How the person spelled the word at tokens[at], if one of their own words starts
    there, or "". For an entry of several words ("New Plymouth") all of them have to be
    there: "new" by itself is not theirs."""
    cores = [re.sub("['’]s$", "", found.group(2).lower()) if found else ""
             for found in map(_WORD_IN.match, tokens[at:at + 6])]
    for name in names:
        parts = name.split()
        if parts and parts[0].isalnum() and [part.lower() for part in parts] == cores[:len(parts)]:
            return parts[0]
    return ""


# Titles: what comes after one is somebody's name, whatever else the word may mean
# ("Dr. Smith", "Mr. Baker", "St. Hill").
_TITLES = frozenset("dr mr mrs ms mx miss prof st mt sir dame rev fr capt sgt lt".split())


def _without_capital(tokens: list, at: int, previous: str, names, lexicon: Lexicon) -> str:
    """tokens[at] where no capital is called for, as the first word of a phrase that goes
    on with a sentence: with a small letter, unless its capital belongs to a name.

    The dictionary alone can't say: "new", "mark", "will", "may" and "rose" are all
    everyday words. So the capital also stays on one of the person's own words, on a word
    that names begin with where another capitalised word comes straight after it ("New
    Zealand", "Mark Jones": see _OPENS_A_NAME), on a name the dictionary knows where it
    stands by itself after a greeting ("Hello" and then "Mark"), and on a month where a
    date fits ("in May"). `previous` is the word before, in small letters.
    """
    token = tokens[at]
    found = _WORD_IN.match(token)
    if not found:
        return token
    lead, core, rest = found.groups()
    low = core.lower().replace("’", "'")
    own = _own_spelling(tokens, at, names)
    if own:
        return lead + own + core[len(own):] + rest  # as they spelled it, capital or none
    if not core[0].isupper():
        return token
    if previous.rstrip(".") in _TITLES:
        return token                      # "See Dr." and then "Smith": a title is followed by a name
    after = tokens[at + 1] if at + 1 < len(tokens) else ""
    following = None if _is_sym(after) or after == _LOWER else _WORD_IN.match(after)
    # The word that comes straight after this one, with no mark between them: or "".
    next_word = following.group(2) if following and not rest and not following.group(1) else ""
    small = next_word[:1].islower()
    # Whether it runs on into more of a sentence: "Will do", "It was", "May I ask".
    goes_on = small or next_word.lower().replace("’", "'") in I_WORDS
    if low in _MONTH_WORDS and (previous in _BEFORE_A_DATE or after[:1].isdigit()):
        # "This", "from" and "by" lead up to the verb as well: "I think this" and then
        # "May be a problem", but "we fly out this" and then "May and come back in June".
        verb = (low == "may" and previous in _BEFORE_A_VERB_TOO and small
                and next_word.lower() not in _AFTER_A_MONTH)
        if not verb:
            return token
    if (previous in _BEFORE_A_NAME and core in lexicon.capitalised and not goes_on
            and (low not in COMMON or low == "will")):
        # "Hello" and then "Mark": a name the dictionary knows, where one fits. Not
        # "Thanks" and then "Will do", "In advance" or "It was great": a dictionary lists
        # "It", "In" and "So" with capitals as well, for what they are short for.
        return token
    opens_a_name = (not lexicon.has_dictionary or core in lexicon.capitalised
                    or low in _OPENS_A_NAME)
    if next_word and low not in LEAD_INS and opens_a_name:
        if (next_word[0].isupper() and next_word.lower().replace("’", "'") not in I_WORDS
                and not (len(next_word) > 1 and next_word.isupper())):
            return token
    return lexicon.decapitalise(token)


# Names that end in two plus signs, as they are to be written.
_PLUS_PLUS = {"c": "C++", "g": "g++", "clang": "clang++", "notepad": "Notepad++"}
_PLUS_PLUS_RE = re.compile(
    r"(?<![\w+#])(" + "|".join(_PLUS_PLUS) + r")(?: ?\?\?(?!\?)| plus plus\b)", re.IGNORECASE)


def plus_plus(text: str) -> str:
    """`text` with "C++" written so, where a recogniser wrote it another way.

    Parakeet Unified writes "C plus plus" as "C ??": two question marks, which are then
    taken for the end of a question and dropped, so that only "C" was typed, with a
    capital on the word after it. Parakeet v2 writes the words, "C plus plus". Whisper
    writes "C++", which is left as it is. The same for the few other names that end so."""
    if "??" not in text and "plus plus" not in text.lower():
        return text
    return _PLUS_PLUS_RE.sub(lambda found: _PLUS_PLUS[found.group(1).lower()], text)


def fit(
    raw: str,
    before: str,
    after: str,
    lexicon: Lexicon | None = None,
    keep_final: bool = False,
    spoken_off=None,
    greeting_comma: bool = True,
    names=(),
    after_said_end: bool | None = None,
) -> Insertion:
    """Fit one dictated phrase from Whisper between `before` and `after`.

    `keep_final` keeps Whisper's own full stop or question mark at the end of
    the phrase. By default it is dropped, as Dragon only typed punctuation you
    spoke. It is always dropped when inserting into the middle of a sentence. The
    stop of a shortening is the word's own and always stays: "at 5 p.m.".

    `spoken_off` lists spoken punctuation phrases to leave as ordinary words.

    `greeting_comma` off takes out the recogniser's comma in "Hello, Bob". A comma that
    was said, and came through as the word, is put in all the same.

    `names` are the person's own words. One of them keeps the capital they gave it
    where the dictionary would take it for an everyday word: "Rose", "Mark".

    `after_said_end` is what the phrase before this one said of its ending: the
    `said_end` of its Insertion, for a caller that knows `before` still ends with what
    that phrase typed. It matters after a shortening's stop, which may be the word's own
    and no more ("at 5 p.m." and then "on Tuesday") or the end of a sentence as well
    ("at 5 p.m. full stop" and then "To book, phone us"). True: a sentence ended there,
    so this phrase starts one, with a capital, whatever its first word, and after "Dr."
    and "St." too. False: none did, so after a shortening's own stop the phrase carries
    on, with no capital unless the word has one by rights. None, for when it isn't
    known: a capital after "p.m.", unless the first word is one that seldom starts a
    sentence ("and", "to", "from"). After any other full stop, and after a question mark
    or a line break, a capital comes as it always has, whatever is passed.
    """
    off = set(DEFAULT_OFF if spoken_off is None else spoken_off)
    lexicon = lexicon or Lexicon()
    text = plus_plus(" ".join(raw.split()))

    after_text = after.lstrip(" \t")
    mid_sentence = bool(after_text) and after_text[0] not in BREAKS + "\n\r"
    if not keep_final or mid_sentence:
        text = _without_final(text)

    if not greeting_comma:
        text = without_greeting_comma(text)

    text = _LITERAL_RE.sub(
        lambda m: _PROTECT + m.group(1).replace(" ", _PROTECT_SPACE) + _PROTECT,
        text,
    )
    word_before = re.search(r"([\w'’]+)[ \t]*$", before)
    previous = word_before.group(1).lower() if word_before else ""
    if not previous:
        # A title with its stop ("See Dr.") is still the word before: see _TITLES.
        titled = re.search(r"([A-Za-z]+)\.[ \t]*$", before)
        if titled and titled.group(1).lower() in _TITLES:
            previous = titled.group(1).lower()
    line_before = re.split("[\n\r" + BREAKS + "]", before)[-1] if word_before else ""
    for phrase, regex, marker in _SPOKEN_RES:
        if phrase not in off:
            text = regex.sub(_as_a_sign(phrase, marker, line_before), text)

    tokens = _paired(text.split(), before)
    if not tokens:
        return Insertion("")

    # Capitals: the first word follows the document, later ones follow the
    # punctuation spoken in this phrase.
    capital = sentence_start(before)
    # Whether the text before ends with the stop of "p.m.", "etc." or "Dr.": the word's own.
    own = before.rstrip(" \t").endswith(".") and own_stop(before.split()[-1])
    # "At 5 p.m." and then "full stop": the stop that is there does for both.
    merged = own and _is_sym(tokens[0]) and _sym(tokens[0]) == "."
    if merged:
        tokens, capital = tokens[1:], True
        if all(token == _LOWER for token in tokens):
            return Insertion("", capitalise_next=mid_sentence and after_text[0].islower(),
                             said_end=True)
    elif after_said_end and _stop_before(before):
        capital = True   # a sentence ended there, and it was said: even after "St."
    elif capital and own:
        if after_said_end is None:
            # Not known. "We met at 5 p.m." and then "and went home" goes on with it.
            capital = tokens[0].lower() not in _GOES_ON
        else:
            capital = False  # no stop was said: "at 5 p.m." and then "on Tuesday"
    first_word, lower = True, False
    for i, token in enumerate(tokens):
        if token == _LOWER:
            lower = True
            continue
        if _is_sym(token):
            symbol = _sym(token)
            if symbol in SENTENCE_END or symbol in BREAKS:
                capital = True
            elif symbol in ATTACH_LEFT:
                capital = False
            continue
        if capital:
            tokens[i] = _cap_first(token)
        elif first_word or lower:
            # The capital the recogniser gives the first word of a phrase, and of what
            # it took for a new sentence after a comma that was said, means nothing.
            tokens[i] = _without_capital(tokens, i, previous, names, lexicon)
        first_word = lower = False
        previous = token.strip(".,;:!?\"'()").lower()
        # After "U.S." or "etc." the next word is left as the recogniser wrote it: a
        # sentence may have ended there or not, and only it heard which.
        capital = _ends_sentence(token) and not _shortening(token)
    tokens = [token for token in tokens if token != _LOWER]

    # Spaces between tokens. (A backslash goes straight on to a path that is being
    # written, here or in the document where the phrase is joined on to it.)
    path = before if before and (_joins_on(before) or _opening_context(before)) else ""
    out = []
    prev = None
    for token in tokens:
        if prev is not None:
            joined = (
                _hug(token) in ("left", "both") or _hug(prev) in ("right", "both")
                or (prev == _APOSTROPHE and token.lower() in _AFTER_APOSTROPHE)
                or (token in _BACKSLASHES and _in_a_path(path + "".join(out)))
            )
            if not joined:
                out.append(" ")
        out.append(_sym(token) if _is_sym(token) else token)
        prev = token
    result = "".join(out).replace(_PROTECT, "").replace(_PROTECT_SPACE, " ")

    # Spaces against the document. A sign that was said sits as _hug has it; anything
    # else goes by its first and last characters. An "@" that starts a phrase starts a
    # name ("@jonti"), so it gets the space a word would.
    first, last = result[0], result[-1]
    said_first, said_last = _is_sym(tokens[0]), _is_sym(tokens[-1])
    delete_before = 0
    if (_hug(tokens[0]) in ("left", "both") and tokens[0] != _AT_SIGN) if said_first \
            else (first in ATTACH_LEFT or first == "-"):
        delete_before = len(before) - len(before.rstrip(" \t"))
    elif before and not before[-1].isspace() and not _joins_on(before) \
            and not _opening_context(before) \
            and not (tokens[0] in _BACKSLASHES and _in_a_path(before)):
        result = " " + result

    delete_after = 0
    if last in BREAKS:
        delete_after = len(after) - len(after_text)
    elif after and (after[0].isalnum() or after[0] in OPENERS + "\"'") \
            and not (_hug(tokens[-1]) in ("right", "both") if said_last else last in OPENERS + "-") \
            and not _closes(after[0], before):
        result = result + " "

    capitalise_next = (
        mid_sentence
        and said_last and (last in SENTENCE_END or last in BREAKS)
        and after_text[0].islower()
    )
    return Insertion(result, delete_before, delete_after, capitalise_next,
                     _said_end(tokens, merged))


def _stop_before(before: str) -> bool:
    """Whether `before` ends with a full stop, question mark or exclamation mark, with
    nothing after it but spaces and closing brackets and quotes."""
    s = before.rstrip(" \t" + OPENERS + "\"')]}”’")
    return bool(s) and s[-1] in SENTENCE_END


def _joins_on(before: str) -> bool:
    """Whether the text before the cursor ends in a sign that the next word is written
    straight after: a hyphen, a slash, "@", "$", or a dash with no space before it
    ("pages 5–"), which is the kind that has none after it either."""
    last = before[-1]
    if last in BREAKS + "-/\\@$€":
        return True
    return last in "–—" and len(before) > 1 and not before[-2].isspace()


def preview(before: str, after: str, ins: Insertion) -> str:
    """The paragraph as it reads after applying `ins`. Used by the tests."""
    head = before[: len(before) - ins.delete_before]
    tail = after[ins.delete_after:]
    if ins.capitalise_next:
        tail = _cap_first(tail)
    return head + ins.text + tail


def title(text: str) -> str:
    """`text` with a capital on each word, for "cap that". A letter after an apostrophe
    is left small: "Don't Stop", not "Don'T Stop". Capitals that are there already stay,
    so "the NASA report" is "The NASA Report", and so does the small first letter of a
    word spelled like "iPhone". Only text that is all in capitals is brought down first:
    "ALL THE WAY" is "All The Way"."""
    if not any(c.islower() for c in text):
        text = text.lower()
    return re.sub(r"(?<![\w'\u2019])[^\W\d_][\w'\u2019]*", lambda found: _cap_first(found.group()), text)
