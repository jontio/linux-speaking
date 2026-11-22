"""Where a sentence ends, when a phrase ends at a pause.

A recogniser hears each phrase by itself, cut where the speaker paused, and writes it as if
it were the whole of what was said: nearly always with a full stop at the end. But people
pause to think in the middle of a sentence, and then that stop is wrong, and so is the
capital that follows it: "it should be an option. That the user can select."

There are three ways to have it, chosen in Settings (SENTENCE_ENDS):

- "said": a full stop only where "full stop" is said. The recogniser's own stop at the end
  of a phrase is left off. Nothing is ever wrong, but nothing ends unless it is said.
- "pause": the recogniser's stop is kept. Every pause ends a sentence.
- "words": the recogniser's stop is held back, and the words decide. When the next phrase
  comes, the words either side of the join are looked at, and the join gets a full stop,
  a question mark, a comma or nothing, put in with the next phrase; a capital follows a
  sentence end, and the next phrase goes on in small letters where none was. Dragon did
  this: "Periods will only appear at the end of a sentence once you have started the next
  utterance or said New Line or New Paragraph."

Why the next phrase has to be waited for: a sentence can only be seen to have ended once
it is seen what comes next. A measurement of this (Microsoft's, for long dictation, 2022):
showing a punctuation model the phrase before a pause did almost nothing for it, and
showing it the phrase after did nearly everything.

The held stop is typed when nothing more is coming to decide it: before "new line", "new
paragraph" or "press enter", and when dictation is put to sleep or switched off, where the
line it ends looks like a sentence (Engine._finish_sentence).

What decides is a Decider: given the text before the join and the phrase after it, and the
mark the recogniser held back, it says which mark goes at the join. Here is only the one
that keeps the recogniser's mark (what "pause" does), for when no better one is there.
"""
from __future__ import annotations

import re

SENTENCE_ENDS = ("said", "words", "pause")
DEFAULT = "said"
ENDS = (".", "?", "!")
MARKS = ("", ",", ".", "?", "!")
# A line ends a sentence when it is finished by "new line" or the like only if it is this
# many words long or longer: "Dear Sam", "Best regards" and the items of a list are not
# sentences, and get no stop.
SENTENCE_WORDS = 4


def sentence_ends(settings) -> str:
    """Which way the settings say it is to be (see SENTENCE_ENDS). Settings from before
    there was a choice had a tick box for keeping the recogniser's stop: that is "pause"."""
    chosen = getattr(settings, "sentence_ends", "")
    if chosen in SENTENCE_ENDS:
        return chosen
    enabled = getattr(settings, "enabled", None)
    return "pause" if enabled is not None and enabled("keep_final") else DEFAULT


def held_mark(raw: str) -> str:
    """The mark the recogniser put at the end of a phrase: ".", "?", "!", or "" for none.
    (Closing quotes and brackets after it don't count against it.)"""
    stripped = raw.rstrip().rstrip("\"'”’)]}")
    return stripped[-1:] if stripped[-1:] in ENDS else ""


class WithJoin(str):
    """A phrase's words, heard with the end of the phrase before in front (see
    config.LEFT_CONTEXT), and what the recogniser wrote where the two meet, as `join`: (the
    mark or "", whether the next word has a capital), as `at_join`, or None where nothing is
    known. It goes back with the words, not on the recogniser that heard them, which another
    computer's phrase may be heard on in between. (Not `join`: every str has a join already.)
    `at_join_sure`: how surely the mark was written, from 0 to 1, or None where the
    recogniser doesn't say (an older one, or one that gives no figures)."""
    at_join = None
    at_join_sure = None


def heard(text: str, join, sure=None) -> str:
    """`text` with the join it was heard with (see WithJoin), or `text` as it is."""
    if join is None:
        return text
    out = WithJoin(text)
    out.at_join = tuple(join)
    out.at_join_sure = sure
    return out


def ends_marked(text: str) -> bool:
    """Whether `text` ends with a mark already, so that none is to be put after it: a
    comma, a stop or any sign said or written there (looked for inside closing quotes and
    brackets too: 'He said, "Go away."'), or an opening quote or bracket ("He said “")."""
    stripped = text.rstrip(" \t")
    if not stripped:
        return False
    if stripped[-1] in "“‘([{" or re.search(r"(?:^|\s)[\"']$", stripped):
        return True
    inner = stripped.rstrip("\"'”’)]}")
    return bool(inner) and inner[-1] in ".,;:?!…"


class Decider:
    """Decides the mark at a join. This one keeps what the recogniser wrote, which is
    what the "pause" choice does: for when nothing better can be had."""

    name = "the recogniser's own"

    def decide(self, before: str, phrase: str, held: str) -> str:
        """The mark for the join between `before` (the text before it, the end of which
        is the phrase the recogniser ended with `held`) and `phrase` (what is to be typed
        after it, as it will be typed, without the join's mark)."""
        return held


def joined(head: str, text: str, mark: str, cap_first) -> tuple:
    """`text` (an insertion to go after `head`) with `mark` put at the join, and how many
    characters of `head` it takes out first: (text, delete_before). After a sentence end
    the first word gets a capital (`cap_first` is the program's own, which leaves "iPhone"
    as it is). The mark goes straight after the last word, whatever spaces were there."""
    if not mark:
        return text, 0
    trailing = len(head) - len(head.rstrip(" \t"))
    body = text.lstrip(" ")
    if mark in ENDS:
        found = re.match(r"([\"'“‘(\[]*)(\S+)", body)
        if found:
            body = body[:found.start(2)] + cap_first(found.group(2)) + body[found.end(2):]
    return mark + " " + body, trailing


def looks_like_a_sentence(line: str) -> bool:
    """Whether a line that is about to be ended reads as a sentence, so that the held stop
    belongs at its end: words enough, and not a greeting, a sign-off or a heading."""
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", line)
    return len(words) >= SENTENCE_WORDS
