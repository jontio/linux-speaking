"""Trying each recogniser on your own voice.

You read a passage aloud once. The recording is cut into phrases at the pauses, as
dictation would cut it, and every recogniser hears the same phrases. Because the words of
the passage are known, the words each one got wrong can be counted, and how long it took
can be timed. That says which model suits your voice, accent and microphone, which no
test on other people's recordings can.

The recording is kept, so the same test can be run again after anything changes.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import os
import re
import time
import wave
from dataclasses import asdict, dataclass, field

from . import config, opinions
from .formatting import SPOKEN

# About two and a half minutes, read at a steady pace. No figures, names or words spelled
# two ways, so that a difference from what a recogniser writes is a word it got wrong.
#
# Ordinary sentences don't tell good recognisers apart: read clearly, every one of them
# gets every word. So half of the passage is made of words that are one vowel away from
# another word ("pen" and "pin", "better" and "beta", "chair" and "cheer"), in sentences
# where the other word would make some sense too. Which of those a recogniser picks
# depends on how well it copes with the reader's own accent.
PASSAGE = (
    "Thanks for getting back to me so quickly about the meeting.",
    "I have read through the notes and I think most of it looks right.",
    "There are a few things we should talk about before Thursday afternoon.",
    "Could you send me the latest figures when you get a chance?",
    "I will be away from my desk tomorrow morning, but I can call you after lunch.",
    "It has been raining here all week and the garden is full of water.",
    "My brother is coming to stay with us this weekend with his children.",
    "Please remember to bring the keys, because the front door will be locked.",
    "Nothing important has changed, although the price went up a little in the autumn.",
    "I would rather wait until the weather gets better before we paint the fence.",
    "Let me know what you think, and I will write up a short summary.",
    "Which of these do you think is better?",
    "This version is much better than the beta we tested last week.",
    "I left the pen on the desk and put the pin back in the bag.",
    "We had fish and chips for dinner and the kids drank milk.",
    "Bring a spare chair up the stairs and share it with the others over here.",
    "I really do not care whether we go by ferry or by air.",
    "The men sat on the bed and said the weather had been bad.",
    "Send the letter later, after you check the data on the laptop.",
    "It is a bit of a mess, but I bet the rest of the list is fine.",
    "Fill the pool until it is full, then pull the cover over it.",
    "Set the dish on the left and let the pan sit in the sink.",
    "Her salary went up, so she bought celery and fresh bread.",
    "That is everything from me for now, so have a good evening.",
)
LONGEST_SECONDS = 360   # a recording stops by itself after this
CONTEXT = 200           # how much of what it has written so far a recogniser is shown
RECORDING = os.path.join(os.path.dirname(config.STATE_FILE), "voice-test.wav")
RESULTS = os.path.join(os.path.dirname(config.STATE_FILE), "voice-test.json")


# ---- counting the words that came out wrong ---------------------------------------
def words(text: str) -> list:
    """The words of `text` as they are compared: lower case, no punctuation."""
    text = text.lower().replace("’", "'").replace("-", " ")
    return re.sub(r"[^a-z0-9' ]", " ", text).split()


# Punctuation said aloud while reading: "comma", "question mark". Longest first.
_SAID_SIGNS = sorted((phrase.split() for phrase, _ in SPOKEN), key=len, reverse=True)


def _not_spoken_signs(heard: list) -> list:
    """The places in `heard` that are not punctuation said as words."""
    kept, at = [], 0
    while at < len(heard):
        for phrase in _SAID_SIGNS:
            if heard[at:at + len(phrase)] == phrase:
                at += len(phrase)
                break
        else:
            kept.append(at)
            at += 1
    return kept


def without_spoken_signs(heard: list) -> list:
    """`heard` without punctuation that was said as words.

    Some people read the passage as they dictate, saying "comma" and "full stop", and
    some don't; a recogniser may write what was said as the word or as the sign. None of
    that is a word got wrong, and the passage has none of those words in it, so they are
    left out of the count either way.
    """
    return [heard[at] for at in _not_spoken_signs(heard)]


def score(said: list, heard: list) -> tuple:
    """(words wrong, the places it went wrong), as the test counts them.

    Punctuation said aloud isn't counted, and neither is a word written as two or two as
    one, "riverbank" for "river bank": the recogniser heard that right.
    """
    wrong, slips = compare(said, without_spoken_signs(heard))
    kept = []
    for spoken, written in slips:
        if spoken.replace(" ", "") == written.replace(" ", ""):
            wrong -= compare(spoken.split(), written.split())[0]
        else:
            kept.append((spoken, written))
    return wrong, kept


# ---- the words that came out right, but only just -----------------------------------------
NEAR = 0.9  # a word written with less sureness than this, though right, was a near miss


class Heard(str):
    """What a recogniser wrote. It may also say how sure it was of each word."""
    sure = None   # [(word, sureness from 0 to 1), ...] as written; None if it doesn't say
    extra = 0.0   # seconds it spent finding that out, which are no part of the listening


def heard_as(text: str, sure, extra: float = 0.0) -> Heard:
    made = Heard(text)
    made.sure, made.extra = sure, extra
    return made


def pieced_together(text: str, takes: list):
    """The sureness of each word of `text`, from the times a recogniser chose words while
    writing it: `takes` is word_sureness() of each of those. Whisper may choose more than
    once for one piece of sound, trying again when it mistrusts itself, and long sound
    is chosen for in stretches. None if the takes can't be fitted to the text."""
    wanted = words(text)
    if not wanted:
        return []
    heard = [[part for word, _ in take for part in words(word)] for take in takes]
    for said, take in zip(reversed(heard), reversed(takes)):
        if said == wanted:
            return list(take)  # all of it at one go, which is the usual thing
    found, at = [], 0
    for said, take in zip(heard, takes):
        if said and wanted[at:at + len(said)] == said:
            found += take
            at += len(said)
    return found if at == len(wanted) else None


def word_sureness(pieces, log_probs):
    """[(word, how sure)] from the pieces a recogniser wrote and the log of the probability
    it gave each one as it chose it. A piece that begins with a space begins a word. A
    word is as sure as its least sure piece. Punctuation isn't counted: where a comma
    goes is not hearing. None if the recogniser didn't say how sure it was."""
    if log_probs is None or len(pieces) != len(log_probs):
        return None
    found = []
    for piece, log_prob in zip(pieces, log_probs):
        sure = math.exp(min(0.0, float(log_prob)))
        bare = piece.strip().lstrip("\u2581")
        counted = any(c.isalnum() for c in bare)
        if piece[:1] in (" ", "\u2581") or not found:
            found.append([bare, sure if counted else 1.0])
        else:
            found[-1][0] += bare
            if counted:
                found[-1][1] = min(found[-1][1], sure)
    return [(word, sure) for word, sure in found if word]


def _right(said: list, heard: list) -> list:
    """For each word of `heard`, whether it is the word of `said` that belongs there, by
    the same matching as compare()."""
    rows, columns = len(said) + 1, len(heard) + 1
    cost = [[0] * columns for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(columns):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, columns):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (said[i - 1] != heard[j - 1]))
    right, i, j = [False] * len(heard), len(said), len(heard)
    while i > 0 or j > 0:
        if i > 0 and j > 0 and said[i - 1] == heard[j - 1] and cost[i][j] == cost[i - 1][j - 1]:
            right[j - 1] = True
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + 1:
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return right


def near_misses(said: list, phrases: list):
    """The words a recogniser got right without being sure of them: [(word, sureness)],
    the least sure first. `phrases` is what word_sureness() gave for each phrase. None if
    the recogniser didn't say how sure it was, of any phrase.

    The first word of a phrase is left out. The doubt there is mostly whether to give it
    a capital, which is not a matter of hearing.
    """
    flat = []  # (the word as it is compared, how sure, whether it began its phrase)
    for sure in phrases:
        if sure is None:
            return None
        first = True
        for word, how in sure:
            for part in words(word):
                flat.append((part, how, first))
                first = False
    kept = _not_spoken_signs([word for word, _, _ in flat])
    right = _right(said, [flat[at][0] for at in kept])
    found = [flat[at][:2] for at, good in zip(kept, right)
             if good and not flat[at][2] and flat[at][1] < NEAR]
    return sorted(found, key=lambda pair: pair[1])


def rescore(result) -> None:
    """Count a result's wrong words again from the places where it went wrong. For
    results kept from before the counting changed."""
    wrong, slips = 0, []
    for said, heard in result.slips:
        count, parts = score(words(said), words(heard))
        wrong += count
        slips += [list(pair) for pair in parts]
    result.wrong, result.slips = wrong, slips


def own_wrong(result, shared: list) -> int:
    """How many words a recogniser got wrong by itself: its count without the slips that
    every recogniser made alike, which were the reader's. `shared` is from shared_slips()."""
    # Each shared slip is taken off as often as this recogniser made it, and no oftener
    # than all of them did.
    mine = Counter(map(tuple, result.slips))
    return result.wrong - sum(score(words(said), words(heard))[0] * min(times, mine[said, heard])
                              for (said, heard), times in Counter(map(tuple, shared)).items())


def shared_slips(results: list) -> list:
    """Slips that every recogniser made alike. Those are most likely the reader's: a word
    read differently from the page is "wrong" for all of them. Only recognisers that did
    reasonably well are asked, and at least three of them."""
    fair = [r for r in results if not r.problem and r.total and r.wrong <= 0.2 * r.total]
    if len(fair) < 3:
        return []
    shared = Counter(map(tuple, fair[0].slips))
    for result in fair[1:]:
        shared &= Counter(map(tuple, result.slips))  # as often as the one that made it least
    found = []
    for pair in map(tuple, fair[0].slips):  # in the order they came, each as often as shared
        if shared[pair] > 0:
            shared[pair] -= 1
            found.append(list(pair))
    return found


def compare(said: list, heard: list) -> tuple:
    """(how many words are wrong, [(what was said, what was written), ...]).

    A word is wrong if it was changed, left out, or put in where none was said. The pairs
    show each place where the two part company.
    """
    rows, columns = len(said) + 1, len(heard) + 1
    cost = [[0] * columns for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(columns):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, columns):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (said[i - 1] != heard[j - 1]))
    # Walk back from the end to find where they differ, joining neighbours into one slip.
    slips, i, j = [], len(said), len(heard)
    spoken, written = [], []

    def close():
        if spoken or written:
            slips.append((" ".join(reversed(spoken)), " ".join(reversed(written))))
            spoken.clear()
            written.clear()

    while i > 0 or j > 0:
        if i > 0 and j > 0 and said[i - 1] == heard[j - 1] and cost[i][j] == cost[i - 1][j - 1]:
            close()
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + 1:
            spoken.append(said[i - 1])
            written.append(heard[j - 1])
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            spoken.append(said[i - 1])
            i -= 1
        else:
            written.append(heard[j - 1])
            j -= 1
    close()
    return cost[-1][-1], list(reversed(slips))


# ---- the recording --------------------------------------------------------------------
def phrases(samples, boost: float = 1.0) -> list:
    """The recording cut at its pauses, the way dictation cuts what it hears.

    `samples` is 16-bit sound at config.RATE. Each phrase comes back as numbers from -1
    to 1, ready for a recogniser.
    """
    import collections
    import numpy as np
    from .segmenter import END, START, Segmenter, SegmenterConfig
    segmenter = Segmenter(SegmenterConfig(min_level=config.MIN_LEVEL, ratio=config.RATIO, flat_ms=0))
    preroll = collections.deque(maxlen=config.PREROLL_FRAMES)
    found, phrase = [], []
    for at in range(0, len(samples) - config.FRAME + 1, config.FRAME):
        frame = samples[at:at + config.FRAME]
        level = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2))) * boost
        event = segmenter.feed(level)
        if event == START:
            phrase = list(preroll)
        if segmenter.in_phrase or event == END:
            phrase.append(frame)
        else:
            preroll.append(frame)
        if event == END:
            found.append(np.concatenate(phrase).astype(np.float32) / 32768.0)
            phrase = []
            preroll.clear()
    if segmenter.in_phrase and phrase:  # the recording was stopped mid-phrase
        found.append(np.concatenate(phrase).astype(np.float32) / 32768.0)
    return found


def _text_file(path: str) -> str:
    """Beside a recording, the text that was read for it."""
    return os.path.splitext(path)[0] + ".txt"


def save_recording(samples, path: str = RECORDING) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(config.RATE)
        f.writeframes(samples.astype("<i2").tobytes())
    with open(_text_file(path), "w", encoding="utf-8") as f:
        f.write(" ".join(PASSAGE))


def load_recording(path: str = RECORDING):
    """The saved recording, or None if there isn't one that can be used. One made by
    reading a different text is no use: its words can't be counted against this one."""
    import numpy as np
    if recording_is_old(path):
        return None
    try:
        with wave.open(path, "rb") as f:
            if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, config.RATE):
                return None
            return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2")
    except (OSError, wave.Error, EOFError):
        return None


def recording_is_old(path: str = RECORDING) -> bool:
    """Whether there is a recording, but of a text that has since been changed."""
    if not os.path.exists(path):
        return False
    try:
        with open(_text_file(path), encoding="utf-8") as f:
            return f.read() != " ".join(PASSAGE)
    except (OSError, ValueError):
        return True


# ---- the recognisers, and how each did --------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    where: str        # "here", or "there" for the other computer; "team" for several
    name: str         # the model's folder
    label: str        # as it is shown
    quick: bool       # Whisper given only as much sound as the phrase needs
    whisper: bool = True
    team: tuple = ()  # for several together: the first, who checks it, and who settles it

    def title(self) -> str:
        if self.team:
            return self.label
        way = ("" if not self.whisper else ", quicker recognition" if self.quick else ", usual way")
        place = " on the other computer" if self.where == "there" else ""
        return f"{self.label}{way}{place}"


@dataclass
class Result:
    title: str
    where: str
    name: str
    quick: bool
    wrong: int = 0
    total: int = 0
    seconds: float = 0.0     # for a phrase, on average
    slips: list = field(default_factory=list)
    problem: str = ""        # why it could not be tried, if it couldn't
    note: str = ""           # anything else worth saying about how it went
    near: int = -1           # words right but under NEAR sure: -1 if the recogniser doesn't say
    shaky: list = field(default_factory=list)  # those words, least sure first: [word, percent]

    def percent(self) -> float:
        return 100.0 * self.wrong / self.total if self.total else 0.0


def candidates(here: list, there: list, ways=(True, False),
               is_whisper=lambda where, name: True) -> list:
    """Every recogniser to try. `here` and `there` are [(name, label), ...] as the model
    chooser shows them; `ways` is the quick way (True), the usual way (False), or both."""
    found = []
    for where, listed in (("here", here), ("there", there)):
        # "Small: recommended  (small.en)" is shown as "Small", unless two are called that.
        short = [label.split(":")[0].strip() or name for name, label in listed]
        for (name, label), brief in zip(listed, short):
            shown = brief if short.count(brief) == 1 else f"{brief} ({name})"
            if not is_whisper(where, name):
                found.append(Candidate(where, name, shown, False, whisper=False))
                continue
            for quick in ways:
                found.append(Candidate(where, name, shown, quick))
    return found


# Who checks a transducer's hearing, and who settles it where the two differ. On the one
# recording this was tried on, each of the three got words wrong that the other two got
# right: see opinions.py.
CHECKS = ("small.en", "small")
SETTLES = ("medium.en", "medium")


def teams(found: list) -> list:
    """Recognisers working together, from those in `found`: a transducer such as Parakeet,
    checked by one Whisper and settled by another. All on this computer, all on the other,
    or the transducer here and the two Whispers there, which can then listen at the same
    time."""
    def pick(where: str, names: tuple, whisper: bool = True):
        fit = [c for c in found if c.where == where and c.whisper == whisper and not c.team
               and (c.name in names or not names)]
        fit.sort(key=lambda c: (names.index(c.name) if names else 0, not c.quick))
        return fit[0] if fit else None

    made = []
    for first_at, others_at, place in (("here", "here", ""),
                                       ("here", "there", " on the other computer"),
                                       ("there", "there", ", all on the other computer")):
        first = pick(first_at, (), whisper=False)
        second, third = pick(others_at, CHECKS), pick(others_at, SETTLES)
        if first and second and third:
            made.append(Candidate(
                "team", "+".join(member.name for member in (first, second, third)),
                f"{first.label}, checked by {second.label} and {third.label}{place}",
                second.quick, whisper=False, team=(first, second, third)))
    return made


def hear_together(team: tuple, sound, written: str, hear) -> tuple:
    """(the words, whether the third was asked) for one phrase heard by a team.

    The first two listen at the same time if they are on different computers. The third
    listens only if those two differ, which is what keeps this cheap.
    """
    first, second, third = team
    if first.where != second.where:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            one, other = pool.map(lambda member: hear(member, sound, written), (first, second))
    else:
        one, other = hear(first, sound, written), hear(second, sound, written)
    if opinions.same(one, other):
        return one, False
    return opinions.settle(one, other, hear(third, sound, written)), True


def try_one(candidate: Candidate, sounds: list, said: list, hear, progress=lambda done: None,
            cancelled=lambda: False, clock=time.monotonic):
    """One recogniser on every phrase. `hear(candidate, sound, written so far)` gives the
    words, as a Heard if it can say how sure it was of them. Returns its Result, or None
    if it was cancelled part way."""
    result = Result(candidate.title(), candidate.where, candidate.name, candidate.quick,
                    total=len(said))
    try:
        for member in (candidate.team or (candidate,)) if sounds else ():
            hear(member, sounds[0], "")  # loads the model: not counted in the time
        written, spent, asked, sures = "", 0.0, 0, []
        for at, sound in enumerate(sounds):
            if cancelled():
                return None
            started = clock()
            if candidate.team:
                text, settled = hear_together(candidate.team, sound, written[-CONTEXT:], hear)
                asked += settled
                sures.append(None)  # several together: nobody's sureness is the answer's
            else:
                text = hear(candidate, sound, written[-CONTEXT:])
                sures.append(getattr(text, "sure", None))
                spent -= getattr(text, "extra", 0.0)  # not time dictation would take
            spent += clock() - started
            written = (written + " " + text).strip()
            progress(at + 1)
        result.seconds = spent / len(sounds) if sounds else 0.0
        result.wrong, slips = score(said, words(written))
        result.slips = [list(pair) for pair in slips]
        missed = near_misses(said, sures) if sounds else None
        if missed is not None:
            result.near = len(missed)
            result.shaky = [[word, int(100 * how)] for word, how in missed[:40]]  # 89.9 is not 90
        if candidate.team:
            first, second, third = candidate.team
            result.note = (f"{first.label} and {second.label} differed in {asked} of "
                           f"{len(sounds)} phrases, and {third.label} was asked to settle those.")
    except Exception as e:  # one recogniser failing doesn't stop the rest being tried
        result.problem = str(e) or type(e).__name__
    return result


def suggested(results: list):
    """Which of them to use: the quickest of those nearly as accurate as the best. The
    result itself, for the window's button that puts it to use, or None.

    Nearly means within a word or two. Every recogniser heard the same recording, so a
    word more is a real difference, but one word is too little to choose by."""
    # Several working together aren't a model to choose: they are a tick box in Settings.
    tried = [r for r in results if not r.problem and r.total and r.where != "team"]
    if not tried:
        return None
    best = min(r.wrong for r in tried)
    near = [r for r in tried if r.wrong <= best + max(1, round(0.005 * r.total))]
    return min(near, key=lambda r: (r.seconds, r.wrong))


def suggestion(results: list) -> str:
    """The name of the one to use, as the results show it, or ""."""
    pick = suggested(results)
    return pick.title if pick is not None else ""


# A recording ends by itself, for somebody who can't reach the button: once the passage
# has had time to be read by the quickest of readers, a long enough quiet is the end of it.
READ_WORDS_A_SECOND = 4.0  # quicker than anybody reads aloud
QUIET_END = 8.0            # seconds with nothing said, after that, that end the recording


def least_seconds() -> float:
    """The least time the passage takes to read aloud."""
    return len(words(" ".join(PASSAGE))) / READ_WORDS_A_SECOND


def read_out(seconds: float, quiet: float) -> bool:
    """Whether a recording can be taken as finished: it has gone on for `seconds`, and
    nothing has been said for the last `quiet` of them."""
    return seconds >= least_seconds() and quiet >= QUIET_END


def _fingerprint() -> str:
    """A short mark of the passage, kept with results so they aren't shown for another."""
    import hashlib
    return hashlib.sha256(" ".join(PASSAGE).encode("utf-8")).hexdigest()[:16]


def save_results(results: list, path: str = RESULTS) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"when": time.strftime("%Y-%m-%d %H:%M"), "passage": _fingerprint(),
                   "results": [asdict(r) for r in results]}, f, indent=1)


def load_results(path: str = RESULTS) -> tuple:
    """(when it was run, [Result, ...]), or ("", []) if it never was, or was run on a
    text that has since been changed."""
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("passage") != _fingerprint():
            return "", []
        results = [Result(**r) for r in saved.get("results", [])]
        for result in results:
            rescore(result)
        return str(saved.get("when", "")), results
    except (OSError, ValueError, TypeError, AttributeError):
        return "", []
