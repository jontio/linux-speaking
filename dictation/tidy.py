"""Putting right what was typed a moment ago, once what is said next shows what it was.

A phrase is heard and typed by itself. "The cat too" is a fair guess with nothing after
it, and wrong as soon as "the vet" follows. So when the next phrase comes, the end of
what was typed before it is looked over again together with the new words, and what was
probably not meant is changed as the new words go in.

Two things keep this from being a nuisance:

- **Only this program's own words are touched, and only while they are as it typed them.**
  The engine remembers the run of text it has typed, one phrase after another. What is
  before the cursor now is compared with that, from the cursor backwards: where the two
  part, the person has been at work, and nothing from there back is looked at again. So a
  word that was changed back by hand stays as it was put.
- **A change that is taken back is not made again.** "Undo that" straight after one says
  it was not wanted (see `Refused`).

Nothing here reads or writes a document. A change is made by the ordinary insertion of
the new phrase, which every program's link can already do: it takes out the last few
characters before the cursor and types them again, put right, with the new words after
them. That is one step to the program, so "scratch that" takes back the phrase and the
change that came with it, and what was there before is there again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

RUN_LENGTH = 400   # how much of what was typed is remembered, in characters
SENTENCES = 2      # how far back is looked: the sentence being gone on with, and one more


@dataclass(frozen=True)
class Change:
    """One thing to put right in a text: what stands from `start` to `end` becomes `new`.
    `kind` is what sort of change it is, for the log, where no word is ever written."""
    start: int
    end: int
    new: str
    kind: str = "word"


def ours(head: str, run: str) -> str:
    """The end of `head` (the text before the cursor) that this program typed and that
    nobody has changed since: as much of the end of `run` as `head` still ends with,
    from the start of a word. (Spaces at the very end are not held against it: the
    fitting of the next phrase may have taken one out.)"""
    stem = head.rstrip(" \t")
    space, run = head[len(stem):], run[-RUN_LENGTH:].rstrip(" \t")
    for at in range(len(run)):
        if at and not (run[at - 1].isspace() and not run[at].isspace()):
            continue                      # only from where a word starts
        if stem.endswith(run[at:]):
            # A word of the run that only happens to be the end of some longer word in
            # the text is not that word.
            before = stem[:len(stem) - len(run) + at]
            if at == 0 or not before or before[-1].isspace():
                return run[at:] + space
    return ""


_SENTENCE_START = re.compile(r"(?<=[.!?…])[\"”’)\]]*\s+(?=[\"“‘(\[]*[A-Z0-9])|\n+")


def last_sentences(text: str, count: int = SENTENCES) -> str:
    """The last `count` sentences of `text`: what a change may reach back into. A new
    line starts one too, so nothing above the line being written on is looked at unless
    it ends a sentence that is still within reach."""
    starts = [0] + [m.end() for m in _SENTENCE_START.finditer(text)]
    return text[starts[-count] if len(starts) >= count else 0:]


def amend(text: str, delete_before: int, before: str, run: str, checks, refused=None) -> tuple:
    """Fit the corrections of `checks` into an insertion that is about to be made.

    `text` and `delete_before` are the insertion as it stands: the new words, and how
    many characters before the cursor go first. `before` is the text before the cursor
    and `run` what this program has typed there (see the top of this file). Each of
    `checks` is called with the text to look over and where in it the new words start,
    and gives the Changes it is sure of.

    Returns (the text to insert, how many characters go first, the changes made, the
    text they were made in). With nothing to change the first two are `text` and
    `delete_before` as they were, and there are no changes.
    """
    head = before[:len(before) - delete_before] if delete_before else before
    mine = last_sentences(ours(head, run))
    whole, starts = mine + text, len(mine)
    found = []
    for check in checks:
        found += [c for c in check(whole, starts)
                  if 0 <= c.start <= c.end <= len(whole) and whole[c.start:c.end] != c.new]
    kept = []
    for change in sorted(found, key=lambda c: (c.start, c.end)):
        if kept and change.start < kept[-1].end:
            continue                      # two that would both change the same words: the first
        if refused is not None and refused.has(whole, change):
            continue
        kept.append(change)
    if not kept:
        return text, delete_before, [], whole
    fixed = whole
    for change in reversed(kept):
        fixed = fixed[:change.start] + change.new + fixed[change.end:]
    cut = min(starts, kept[0].start)      # all before the first change stays as it is
    return fixed[cut:], delete_before + (starts - cut), kept, whole


# ---- the join between one phrase and the next ---------------------------------------------
_ABBREVIATION = re.compile(r"(?:\b[A-Za-z]\.[A-Za-z]|\b(?:etc|Mr|Mrs|Ms|Dr|Prof|St|vs|No|Inc|Ltd|Co)|\b[A-Z])\.$")


def stop_before_comma(not_said: bool):
    """A check for a full stop that the recogniser put at the end of a phrase, where the
    next phrase goes on with a comma, a semicolon or a colon: "Hi Joe." and then
    ", how are you". The stop was the recogniser's guess that the sentence was over, and
    the comma says it was not.

    `not_said` is whether that stop is known not to have been said aloud. One that was
    said is the person's, and stays; so does the dot of "p.m." or "etc.", which is part
    of the word."""
    def check(whole: str, starts: int) -> list:
        if not not_said or starts < 2 or not re.match(r"[,;:]", whole[starts:]):
            return []
        typed = whole[:starts]
        if not typed.endswith(".") or typed.endswith("..") or _ABBREVIATION.search(typed):
            return []
        from .formatting import _shortening
        if typed.split() and _shortening(typed.split()[-1]):
            return []                     # "Acme Corp.", "approx.", "3 Jan.": the word's own
        return [Change(starts - 1, starts, "", "join")]
    return check


# After "hi" or "hello" at the start of a sentence, one word and then a comma or the end is
# nearly always the name of whoever is greeted. These are the words it could be instead.
_NOT_A_NAME = frozenset(
    "again all and are both can could dear do everybody everyone folks friend friends guys "
    "how i is it just love madam mate my no ok okay please sir so sorry team thank thanks that "
    "there this we well what world yes you".split())
_GREETED = re.compile(r"(?:^|(?<=[.!?…]\s)|(?<=\n))(hi|hello|hey)\s+([a-z][a-z'’-]*)(?=\s*(?:[,.!?]|$))",
                      re.IGNORECASE)


def name_after_greeting(changes: list):
    """A check that gives a capital to the name after a greeting, where an earlier check
    has just made the greeting out of another word ("high joe" to "hi joe"): heard as
    "high", the recogniser had no reason to write a name after it. Only then: a greeting
    the recogniser wrote itself has had its capitals from it already.

    `changes` is the list the earlier checks' changes are gathered in, as they stand."""
    def check(whole: str, starts: int) -> list:
        found = []
        for change in changes:
            if change.new.lower() not in ("hi", "hello", "hey"):
                continue
            fixed = whole[:change.start] + change.new + whole[change.end:]
            m = _GREETED.search(fixed, max(0, change.start - 1))
            if m is None or m.start(1) != change.start:
                continue
            word = m.group(2)
            if word.lower() in _NOT_A_NAME or not word.islower():
                continue
            at = m.start(2) - (len(change.new) - (change.end - change.start))   # in `whole`
            found.append(Change(at, at + len(word), word[:1].upper() + word[1:], "capital"))
        return found
    return check


def soundalikes(head: str, protected=(), join: float = 0.0, join_known: bool = True):
    """A check for a word that should have been another that sounds the same: "too" in
    "take the cat too" once "the vet" follows. See soundalike.py, which decides.

    `head` is all the text before the new words, typed by this program or not: what is
    not its own is read for context and never changed. `protected` are the person's own
    words. `join` is how many times likelier the other word has to be where the two
    phrases meet; 0 leaves it to soundalike.py. (After a long pause the sentence may
    well have ended there, which nothing in the words shows: so the caller asks as much
    there as anywhere else.)

    `join_known` says whether it is known if a sentence ended where the two phrases
    meet. Where it isn't, the word either side of the join is left as it is: those are
    the very words that turn on it. "It works too" and then "let me know" (a sentence
    ended) reads, with the stop left off, just as "take the cat too" and then "the vet"
    does; and "who told you" and then "no, I did" as "you know". Measured on read and
    written dictation, every change made there was wrong."""
    from . import soundalike

    def check(whole: str, starts: int) -> list:
        mine = whole[:starts]
        if not head.endswith(mine):
            return []
        context = head[-max(len(last_sentences(head)), len(mine)):] if head else ""
        offset = len(context) - len(mine)          # where `whole` starts in context + phrase
        extra = {"threshold": join} if join else {}
        found = soundalike.suggest(context, whole[starts:], protected=protected,
                                   changeable_from=offset, **extra)
        changes = [Change(c.start - offset, c.end - offset, c.new, "word")
                   for c in found if c.start >= offset]
        if not join_known:
            words = [(m.start(), m.end()) for m in re.finditer(r"[^\W_]+(?:['’][^\W_]+)*", whole)]
            last_before = max((w for w in words if w[1] <= starts), default=None)
            first_after = min((w for w in words if w[0] >= starts), default=None)
            near = {w for w in (last_before, first_after) if w is not None}
            changes = [c for c in changes if not any(c.start < e and s < c.end for s, e in near)]
        return changes
    return check


def chained(*checks):
    """One check made of several, each of the later ones told what the earlier found:
    `checks` are functions of the list of changes so far, each giving a check."""
    def check(whole: str, starts: int) -> list:
        found = []
        for make in checks:
            found += make(found)(whole, starts)
        return found
    return check


# ---- what was taken back ----------------------------------------------------------------
class Refused:
    """The changes the person has taken back, so that they are not made again.

    "Undo that" straight after a change says plainly that it was not wanted: it is not
    made again in the same words. "Scratch that" may only mean that the new phrase was
    misheard, so it counts for half: twice, and it is the same. And one kind of swap
    ("too" for "to") refused in two places is not made anywhere, until the program is
    started afresh. All of it is kept in memory only."""

    ENOUGH = 2         # what an "undo that" counts for, and what it takes for one place
    EVERYWHERE = 4     # and for one kind of swap, wherever it is

    def __init__(self):
        self._places, self._swaps = {}, {}

    @staticmethod
    def _place(whole: str, change: Change) -> tuple:
        """Where a change is, in a form that is the same when the words around are:
        the two words before it, what it changes, and what to."""
        words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", whole[:change.start].lower())[-2:]
        return tuple(words), whole[change.start:change.end].lower(), change.new.lower()

    def add(self, whole: str, change: Change, sure: bool = True) -> None:
        """Note that a change was taken back: by "undo that" (`sure`), or by "scratch that"."""
        place, weight = self._place(whole, change), self.ENOUGH if sure else 1
        self._places[place] = self._places.get(place, 0) + weight
        self._swaps[place[1:]] = self._swaps.get(place[1:], 0) + weight

    def has(self, whole: str, change: Change) -> bool:
        place = self._place(whole, change)
        return (self._places.get(place, 0) >= self.ENOUGH
                or self._swaps.get(place[1:], 0) >= self.EVERYWHERE)


# ---- a sentence heard again in one piece ----------------------------------------------------
# A sentence said in two phrases is heard as two, and each loses what the other would have
# told the recogniser. With the two sounds put together it is heard as it would have been
# without the pause. What comes back is typed in place of the two phrases, as two phrases
# still, so that "scratch that" takes away the last of them as it would have.
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def _words(text: str) -> list:
    """The words of `text`, each as (where it starts, where it ends, the word in small letters)."""
    return [(m.start(), m.end(), m.group().lower()) for m in _WORD.finditer(text)]


def _pairs(old: list, new: list) -> list:
    """How two lists of words line up: for each word of `old`, which word of `new` stands
    in its place, or None if it is gone. The fewest changes that turn one into the other."""
    n, m = len(old), len(new)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (old[i - 1] != new[j - 1]))
    lined, i, j = [None] * n, n, m
    while i and j:
        if cost[i][j] == cost[i - 1][j - 1] + (old[i - 1] != new[j - 1]):
            lined[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif cost[i][j] == cost[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return lined


def words_changed(old: str, new: str) -> int:
    """How many words have to change, come or go to turn `old` into `new`."""
    a, b = [w for _, _, w in _words(old)], [w for _, _, w in _words(new)]
    lined = _pairs(a, b)
    kept = sum(1 for i, j in enumerate(lined) if j is not None and a[i] == b[j])
    return max(len(a), len(b)) - kept


def worth_typing(old: str, new: str) -> bool:
    """Whether what was heard the second time is to take the place of what was typed.

    Not if it is the same. Not if it is far from it either: heard twice, a sentence comes
    out much the same, with a word or two put right. Something else altogether means one
    of the two hearings went wrong, and there is no telling which: what is on the page,
    and has been seen there, stays."""
    if old == new or not new.strip():
        return False
    count = max(len(_words(old)), len(_words(new)))
    return words_changed(old, new) <= max(2, count // 4)


def split_like(new: str, first: str, second: str):
    """`new` cut in two where `first` and `second`, the two phrases as they were typed,
    met: (its first part, its second), or None if no such place can be found. The marks
    between the two words at the join go with the second, as a comma said at the start of
    a phrase does."""
    old_first, old_second, now = _words(first), _words(second), _words(new)
    if not old_first or not old_second or len(now) < 2:
        return None
    was = [w for _, _, w in old_first + old_second]
    lined = _pairs(was, [w for _, _, w in now])
    if not any(j is not None and was[i] == now[j][2] for i, j in enumerate(lined)):
        return None                       # not one word the same: nothing to go by
    # The first word of the second phrase that still has a word in its place: the cut is
    # before it. (And after the last of the first phrase's that has, which must be the
    # word before: otherwise words have come or gone at the join itself.)
    after = next((lined[i] for i in range(len(old_first), len(lined)) if lined[i] is not None), None)
    before = next((lined[i] for i in range(len(old_first) - 1, -1, -1) if lined[i] is not None), None)
    if after is None or before is None or after == 0:
        return None
    if before != after - 1:
        # Words that are new at the join: they go with whichever phrase is the shorter
        # for it, which is nearly always the one that lost a word there.
        after = before + 1 if len(old_first) <= len(old_second) else after
    cut = now[after - 1][1]
    return new[:cut], new[cut:]


def kinds(changes) -> str:
    """What was changed, for the log: how many things of each kind, and never the words."""
    names = {"word": "a word that sounds like another", "join": "a full stop before a comma",
             "capital": "a capital for a name", "heard": "words heard again",
             "layout": "a sign-off laid out"}
    counted = {}
    for change in changes:
        counted[change.kind] = counted.get(change.kind, 0) + 1
    return ", ".join((names.get(kind, kind) if n == 1 else f"{n} x {names.get(kind, kind)}")
                     for kind, n in counted.items())
