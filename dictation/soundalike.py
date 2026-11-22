"""Telling one sound-alike word from another by the words around it.

"Take the cat too", a pause, "the vet": the recogniser wrote "too" because, when it had
to write it, nothing came after. Once "the vet" is there, anyone can see it was "to".
This looks over the last sentence or two of what has been typed and says which
sound-alike words are now plainly the wrong one of their set. It is plain string work:
it changes nothing itself, and whoever calls it decides what to do with what it says.

It only ever offers one word of a set in place of another of the same set (SETS, below),
and it is made to say nothing rather than say something doubtful:

- It looks hardest where a pause fell, at the join between what was typed before and the
  phrase typed now: the last word before it and the first word after it. That is where
  the recogniser had to guess, with the words on one side still unsaid. There the other
  word has to be THRESHOLD times as likely as the one written, and it has to have been
  met next to what stands on the side the recogniser could not see.
- Away from a join the recogniser had the words on both sides, and knows far more of the
  language than this does. It is overruled only where the other word is ELSEWHERE times
  as likely, and has been met next to what stands on each side of it.
- A word inside quotation marks is left alone, and so is any word the caller says is the
  person's own.

How likely a word is in a place comes from counting: how often each word of a set stood
after this word, before that one, between the two, in a shelf of books that are in the
public domain (see scripts/make_soundalike_data.py, which made the counts in
soundalike.txt; the file names the books). The figures are taken with a pinch of salt in
the direction of saying nothing: a word met four times in a place is counted as met
twice, and a word never met there as met once.

What it can't know:

- Whether a sentence ended at the pause. Nobody says "full stop" after every sentence,
  and the full stop the recogniser puts after each phrase is taken off. So "I want that
  too", a pause, "the vet said no" looks to it just as "take the cat too", "the vet"
  does, and it makes "to" of both. It takes it that the sentence goes on.
- Anything the books don't say. They are stories, most from before 1960: "hi" hardly
  comes into them, so "high" for "hi" at the start of a greeting goes by a few patterns
  written by hand instead (see _greeting), and a set whose words are used otherwise now
  ("site", "cell") is not here at all.
- More than the two words either side. "I want to by a new car": "to by a" is in the
  books one time in ten ("close to by a ..."), which is not rare enough to act on.
"""
from __future__ import annotations

import math
import os
import re
import threading
from dataclasses import dataclass

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soundalike.txt")

# How many times likelier the other word has to be than the one that was written: at a
# join, and anywhere else. Both can be passed to suggest() to try other values.
THRESHOLD = 60.0
ELSEWHERE = 1200.0
# And at a join, how far the side the recogniser could not see has to favour the other
# word by itself.
ACROSS = 2.0
SEEN = 3            # times a word has to have been met in a place for that to count
SENTENCES = 2       # how many sentences back from the phrase are looked over
CERTAIN = 1000.0    # no change is said to be likelier than this: counting isn't that sure
SURE_OF_A_PATTERN = 100.0   # what a pattern written by hand is given, having no counts: see _greeting

# The sets of words that sound alike (or near enough that a recogniser mixes them), each
# in the order its counts are kept in. They were written down by hand: the words English
# writers most often mix up, those a recogniser was seen to mix up where a pause fell
# ("bare" and "bear", "guessed" and "guest"), and others that are said the same. A set is
# only here if, tried on books the counts were not taken from, it put right a fair share
# of the mix-ups and next to never touched a word that was right. The sets that were
# tried and left out, and why, are in scripts/make_soundalike_data.py, which prints the
# figures for all of them. "hi" and "high" go by patterns, not by counts: see _greeting.
SETS = (
    ("to", "too", "two"),
    ("their", "there", "they're"),
    ("your", "you're"),
    ("its", "it's"),
    ("then", "than"),
    ("here", "hear"),
    ("by", "buy", "bye"),
    ("no", "know"),
    ("new", "knew"),
    ("right", "write"),
    ("where", "wear"),
    ("whether", "weather"),
    ("for", "four"),
    ("one", "won"),
    ("our", "hour"),
    ("which", "witch"),
    ("would", "wood"),
    ("see", "sea"),
    ("some", "sum"),
    ("week", "weak"),
    ("meet", "meat"),
    ("way", "weigh"),
    ("road", "rode"),
    ("through", "threw"),
    ("passed", "past"),
    ("allowed", "aloud"),
    ("bare", "bear"),
    ("guessed", "guest"),
    ("made", "maid"),
    ("pair", "pear"),
    ("dear", "deer"),
    ("seen", "scene"),
    ("sent", "scent", "cent"),
    ("grown", "groan"),
    ("heard", "herd"),
    ("knows", "nose"),
    ("missed", "mist"),
    ("morning", "mourning"),
    ("none", "nun"),
    ("poor", "pour"),
    ("tied", "tide"),
    ("wore", "war"),
    ("warn", "worn"),
    ("hair", "hare"),
    ("oh", "owe"),
    ("pray", "prey"),
    ("ring", "wring"),
    ("rose", "rows"),
    ("side", "sighed"),
    ("thrown", "throne"),
    ("were", "we're"),
    ("ate", "eight"),
    ("blue", "blew"),
    ("forth", "fourth"),
)

# Sets that are held to more than the others: so many times the threshold. On the books
# kept back these were wrong too often at the ordinary one, and seldom enough at this.
HARDER = {"whether": 3.0, "sent": 3.0, "morning": 3.0, "poor": 3.0}


@dataclass(frozen=True)
class Change:
    """One word that looks to be the wrong one of its set: where it is in the text that
    was looked over, what to put there, what is there now, and how many times likelier
    the new word was reckoned to be (never more than CERTAIN)."""

    start: int
    end: int
    new: str
    old: str
    sure: float


# ---- cutting text into words ------------------------------------------------------------
# What is kept of a text is its words, and where its sentences and clauses break: a word
# is known by its neighbours, and a full stop or a comma is a neighbour too.
END, BREAK, NUMBER = ".", ",", "#"
_PIECE = re.compile(
    r"(?P<word>[^\W\d_]+(?:['’][^\W\d_]+)*)"
    r"|(?P<number>\d+(?:[.,:/]\d+)*)"
    r"|(?P<end>[.!?…]+|[\n\r  \x0b\x0c]+)"
    r"|(?P<stop>[,;:]|[—–]|--+|\s-\s)"
    r"|(?P<quote>[\"“”‘’'])")
_SHORT = frozenset("mr mrs ms dr st prof".split())   # the stop after these ends no sentence


def pieces(text: str) -> list:
    """`text` as a list of (what it is to its neighbours, start, end, inside quotation
    marks, as written). What it is: the word in small letters, NUMBER for figures, END
    where a sentence ends, BREAK for a comma and its like. Quotation marks are not
    pieces themselves: they only say which words are inside them."""
    found, double, single, plain = [], False, False, False
    for m in _PIECE.finditer(text):
        kind, start, end = m.lastgroup, m.start(), m.end()
        if kind == "quote":
            mark = m.group()
            if mark == '"':
                double = not double
            elif mark == "“":
                double = True
            elif mark == "”":
                double = False
            elif mark == "‘":
                single = True
            elif mark == "’":
                single = False
            else:
                # A plain ' opens a quotation before a word that follows a space, and
                # closes one where no letter follows it. Anywhere else it is the mark
                # of a letter left out or of belonging ("the dogs' bowl").
                before, after = text[start - 1:start], text[end:end + 1]
                if not plain and (not before or before.isspace() or before in "([{") and after.isalnum():
                    plain = True
                elif plain and not after.isalnum():
                    plain = False
            continue
        quoted = double or single or plain
        if kind == "word":
            found.append((m.group().lower().replace("’", "'"), start, end, quoted, m.group()))
        elif kind == "number":
            found.append((NUMBER, start, end, quoted, m.group()))
        elif kind == "end":
            if m.group() == "." and found and found[-1][0] in _SHORT and found[-1][2] == start:
                continue                  # "Mr. Smith": the sentence goes on
            if not found or found[-1][0] != END:
                found.append((END, start, end, quoted, m.group()))
        elif not found or found[-1][0] not in (END, BREAK):
            found.append((BREAK, start, end, quoted, m.group()))
    return found


def places(names: list, at: int) -> list:
    """The places a word is known by, for the word at `at` in a list of names (the first
    of each piece; None where what stands there is not known): [(kind, key), ...] for
    those that can be told. L and R are the word before and the word after; LL and RR the
    two before and the two after; B the two it stands between."""
    def name(i):
        return names[i] if 0 <= i < len(names) else None
    l2, l1, r1, r2 = name(at - 2), name(at - 1), name(at + 1), name(at + 2)
    told = []
    if l1 is not None:
        told.append(("L", l1))
        if l2 is not None and l1 != END:
            told.append(("LL", l2 + " " + l1))
    if r1 is not None:
        told.append(("R", r1))
        if r2 is not None and r1 != END:
            told.append(("RR", r1 + " " + r2))
    if l1 is not None and r1 is not None:
        told.append(("B", l1 + " " + r1))
    return told


# ---- the counts -------------------------------------------------------------------------
class _Counts:
    """One set's counts: how often each of its words was met in all, and in each place."""

    def __init__(self, words: tuple, totals: tuple):
        self.words, self.totals = words, totals
        self.met = {}     # "L going" -> (how often each word of the set stood there)


_tables, _loading = None, threading.Lock()


def tables(path: str = "") -> dict:
    """{word: its set's counts}, read from the file of counts the first time it is asked
    for (a tenth of a second, once). A set is looked at only if it is both in SETS and
    in the file: so one can be taken out of SETS without the file being made again."""
    global _tables
    with _loading:
        if _tables is None or path:
            found, now = {}, None
            try:
                with open(path or DATA, encoding="utf-8") as lines:
                    for line in lines:
                        line = line.rstrip("\n")
                        if not line or line.startswith("#"):
                            continue
                        key, _, figures = line.rpartition("\t")
                        if key.startswith("= "):
                            words = tuple(key[2:].split(" "))
                            now = None
                            if words in SETS:          # a set taken out of SETS is not looked at
                                now = _Counts(words, tuple(int(n) for n in figures.split(" ")))
                                for word in words:
                                    found.setdefault(word.lower(), now)
                        elif now is not None:
                            now.met[key] = tuple(int(n) for n in figures.split(" "))
            except (OSError, ValueError):
                found = {}                # no counts, or not ones that can be read: it says nothing
            if path:
                return found
            _tables = found
        return _tables


def ratio(counts: _Counts, key: str, other: int, written: int) -> tuple:
    """(how many times likelier this place makes the word `other` than the word
    `written`, whether `other` has really been met there). Reckoned so as to say too
    little rather than too much: a word met a few times is counted as met fewer, and one
    never met as met once."""
    met = counts.met.get(key)
    if met is None:
        return 1.0, False
    a, w = met[other], met[written]
    low = max(a - math.sqrt(a), 0.5) / counts.totals[other]
    high = (w + math.sqrt(w) + 1.0) / counts.totals[written]
    return low / high, a >= SEEN


def _wider(counts: _Counts, key: str, narrower: float, met: bool, other: int, written: int) -> tuple:
    """What a wider place (two words where `narrower` went by one, or both sides where it
    went by each) makes of `narrower`, how many times likelier the word `other` was
    reckoned than the word `written`; and whether `other` has been met.

    Where the written word has itself been met in the wider place, that place is the
    better witness, and is taken at its word: "going to" is common, but before "far" it
    is "going too". Where only the other word has been met there, the wider place has
    met too little to say how sure it is, and the two are met half way. Where neither
    has, it says nothing."""
    row = counts.met.get(key)
    if row is None:
        return narrower, met
    how, there = ratio(counts, key, other, written)
    if row[written] >= SEEN:
        return how, there
    if there:
        return (math.sqrt(how * narrower) if narrower > how else how), True
    return narrower, met


def weigh(counts: _Counts, told: list, other: int, written: int) -> tuple:
    """(how many times likelier the word `other` is than the word `written` in a place,
    whether it has been met with what stands before it, whether with what stands after,
    whether between the very two it stands between). `told` is places()'s account."""
    by_kind = dict(told)
    sides, seen = [], []
    for near, far in (("L", "LL"), ("R", "RR")):
        how, met = 1.0, False
        if near in by_kind:
            how, met = ratio(counts, near + " " + by_kind[near], other, written)
            if far in by_kind:
                how, met = _wider(counts, far + " " + by_kind[far], how, met, other, written)
        sides.append(how)
        seen.append(met)
    before = counts.totals[other] / counts.totals[written]    # how common each is anyway
    likelier, between = before * sides[0] * sides[1], False
    if "B" in by_kind:
        key = "B " + by_kind["B"]
        row = counts.met.get(key)
        if row is not None:
            between = row[other] >= SEEN
            likelier = before * _wider(counts, key, sides[0] * sides[1], False, other, written)[0]
    return likelier, seen[0], seen[1], between


def _side(table: _Counts, told: list, near: str, other: int, written: int) -> float:
    """How far one side by itself (the word next to it, and the two) favours `other`."""
    by_kind = dict(told)
    if near not in by_kind:
        return 1.0
    how, met = ratio(table, near + " " + by_kind[near], other, written)
    far = near + near
    if far in by_kind:
        how = _wider(table, far + " " + by_kind[far], how, met, other, written)[0]
    return how


# ---- "hi" and "high" ----------------------------------------------------------------------
# The books the counts come from say "good morning": "hi" as a greeting is hardly in them.
# So these two go by what a greeting looks like. "High" at the start of a sentence is a
# greeting where a person is spoken to next: a word that stands for people, a comma, or
# a name with a comma or the end after it. "High Street" and "High Court" are not names
# of people. And "hi" after "the", "too" or "very" was "high".
_SPOKEN_TO = frozenset("there everyone everybody all guys folks team again both".split())
_NOT_PEOPLE = frozenset(
    "street court school church commissioner priest table tea mass noon water tide time "
    "wycombe road holborn german dutch seas command sheriff heaven".split())
_AFTER_A_NAME = frozenset(
    "how hope thanks thank just are is can could did do have i i'm i've i'll we we're it's "
    "good nice great sorry please what what's when where any long hows how's and".split())
_BEFORE_HIGH = frozenset("the a very too so as how that this quite really rather is was are were be "
                         "been flying up on from in".split())
_AFTER_HI = frozenset("above up in on over and as enough tide time water price prices".split())


def _greeting(parts: list, at: int, known_start: bool):
    """"hi" where "high" was written, or "high" where "hi" was, with how sure; or None.
    `known_start` says the first of `parts` begins a sentence."""
    word = parts[at][0]
    def name(i):
        return parts[i][0] if 0 <= i < len(parts) else None
    # (The first word of the text that was handed over is taken to start a sentence
    # where it has a capital: text is cut short before it is handed over, and there is
    # no telling otherwise.)
    first = (at == 0 and (known_start or parts[at][4][:1].isupper())) or name(at - 1) == END
    nxt, after = name(at + 1), name(at + 2)
    if word == "high" and first and nxt is not None:
        if nxt in _SPOKEN_TO and after in (None, END, BREAK):
            return "hi", SURE_OF_A_PATTERN * 2
        if nxt == BREAK and after is not None and after not in (END, BREAK):
            return "hi", SURE_OF_A_PATTERN     # "High, how are you"
        if nxt not in (END, BREAK, NUMBER) and nxt not in _NOT_PEOPLE and after is not None:
            named = parts[at + 1][4][:1].isupper()
            then = name(at + 3)
            if named and after in (END, BREAK):
                return "hi", SURE_OF_A_PATTERN * 2   # "High Joe, ..."
            if after == BREAK and then in _AFTER_A_NAME:
                return "hi", SURE_OF_A_PATTERN     # "high joe, how are you": the name without its capital
        return None
    if word == "hi" and not first:
        if name(at - 1) in _BEFORE_HIGH and nxt in _AFTER_HI:
            return "high", SURE_OF_A_PATTERN * 2
        if name(at - 1) in ("too", "very", "so", "that", "as") and nxt in (None, END, BREAK, "for", "to"):
            return "high", SURE_OF_A_PATTERN
    return None


# ---- what is said of a text -------------------------------------------------------------
def _like(old: str, new: str) -> str:
    """`new` with the capitals of `old`: "Too" gives "To", "TOO" gives "TO"."""
    if len(old) > 1 and old.isupper():
        return new.upper()
    if old[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def suggest(before: str, phrase: str, after: str = "", protected=(),
            threshold: float = THRESHOLD, elsewhere: float = ELSEWHERE,
            changeable_from: int = 0) -> list:
    """The sound-alike words that look to be the wrong one of their set, in the text
    `before` + `phrase`: a list of Change, in the order they stand, each with its place
    in that joined text.

    `before` is what was typed before this phrase (the last sentence or two is all that
    is looked at; "" where the phrase starts a paragraph) and `phrase` what has just
    been typed after it, as it was typed. `after` is what follows the cursor, if
    anything: it is never changed, only read. A word is left alone if it is in
    `protected` (the person's own words, in any capitals), inside quotation marks, or
    before `changeable_from` in the joined text (what the program did not type itself).

    `threshold` and `elsewhere` are how many times likelier the other word has to be: at
    the join between `before` and `phrase`, and anywhere else. The join is where the
    recogniser could not see the other side, and so where it is looked at hardest; with
    no `before`, there is no join."""
    counts = tables()
    text = before + phrase
    join = len(before)
    parts = pieces(text + after) if after else pieces(text)
    if not parts:
        return []
    names = [part[0] for part in parts]
    # What stands before the first word is known only where the text starts a paragraph;
    # what stands after the last is never known: more may be said.
    known_start = not before.strip()
    protected = {str(word).lower() for word in protected}
    # The pieces either side of the join, if there is one with words on both sides.
    last_before = max((i for i, part in enumerate(parts) if part[2] <= join), default=None)
    first_after = min((i for i, part in enumerate(parts) if join <= part[1] < len(text)),
                      default=None)
    if not before.strip() or last_before is None or first_after is None:
        last_before = first_after = None
    if known_start:
        names = [END] + names             # a paragraph starts as a sentence does
    shift = 1 if known_start else 0
    # Only the last sentence or two before the phrase are looked over: what is further
    # back was looked over when it was typed, and has been read by the person since.
    ends = [part[1] for part in parts if part[0] == END and part[2] <= join]
    changeable_from = max(changeable_from, ends[-SENTENCES] if len(ends) >= SENTENCES else 0)
    found = []
    for at, (word, start, end, quoted, written) in enumerate(parts):
        if start < changeable_from or end > len(text) or quoted or word in (END, BREAK, NUMBER):
            continue
        if word in protected:
            continue
        if word in ("hi", "high"):
            greeting = _greeting(parts, at, known_start)
            if greeting is not None and greeting[1] >= threshold:
                found.append(Change(start, end, _like(written, greeting[0]), written, greeting[1]))
            continue
        table = counts.get(word)
        if table is None:
            continue
        where = "before" if at == last_before else "after" if at == first_after else ""
        chosen = decide(table, names, at + shift, where, threshold, elsewhere)
        if chosen is not None:
            found.append(Change(start, end, _like(written, table.words[chosen[0]]), written,
                                min(chosen[1], CERTAIN)))
    return found


def decide(table: _Counts, names: list, at: int, where: str = "",
           threshold: float = THRESHOLD, elsewhere: float = ELSEWHERE):
    """Whether the word at `at` in `names` (see pieces()) should be another of its set:
    (which of the set, how many times likelier) or None. `where` is "before" for the
    last word before a join, "after" for the first word after one, and "" for anywhere
    else."""
    lower = [word.lower() for word in table.words]
    mine = lower.index(names[at])
    told = places(names, at)
    harder = HARDER.get(table.words[0], 1.0)
    threshold, elsewhere = threshold * harder, elsewhere * harder
    best = None
    for other in range(len(lower)):
        if other == mine:
            continue
        likelier, left, right, between = weigh(table, told, other, mine)
        if where == "before":
            # The recogniser could not see what came after: that side has to speak, by
            # itself or with the word before (met between these very two).
            good = likelier >= threshold and (
                between or right and _side(table, told, "R", other, mine) >= ACROSS)
        elif where == "after":
            good = likelier >= threshold and (
                between or left and _side(table, told, "L", other, mine) >= ACROSS)
        else:
            good = likelier >= elsewhere and (between or left and right)
        if good and (best is None or likelier > best[1]):
            best = (other, likelier)
    return best


def apply(text: str, changes: list) -> str:
    """`text` with the changes made: for trying it, and for the log."""
    for change in sorted(changes, key=lambda c: c.start, reverse=True):
        text = text[:change.start] + change.new + text[change.end:]
    return text
