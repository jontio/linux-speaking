"""Telling commands from dictation.

As in Dragon, a command is a whole phrase on its own, with a pause before and
after. Anything else is dictation. While asleep, only "wake up" counts: or "wake" by
itself, where the short words have been switched on.

A command is not one exact string of words, though, because nobody says it the same
way twice. "The" may be put in or left out ("go to the end of the line", "go to end of
line"), an "um" or "OK" may come first and a "please" last, and a count may be in
figures or in words. What is never done is to find a command inside a longer phrase:
"scratch that idea" is dictation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

WAKE = "wake"
# The setting that lets one word do as "wake up" or "go to sleep". Off unless asked for:
# a lone "sleep" can then no longer be dictated, and one word is easier to set off by
# accident than two.
SHORT = "short_wake"
SHORT_COMMANDS = {"wake": WAKE, "wake wake": WAKE, "sleep": "sleep"}

COMMANDS = {
    "wake up": WAKE,
    "go to sleep": "sleep",
    "tab": "tab",
    "press tab": "tab",
    "press tab key": "tab",
    "tab key": "tab",
    "shift tab": "outdent",
    "back tab": "outdent",
    "scratch that": "scratch",
    "undo that": "undo",
    "undo": "undo",
    "undo it": "undo",
    "undo this": "undo",
    "undue that": "undo",   # ways Whisper may hear "undo that"
    "on do that": "undo",   # ("and do that" is not one of them: people say it)
    "redo that": "redo",
    "redo": "redo",
    "redo it": "redo",
    "redo this": "redo",
    "re do that": "redo",   # as "Re-do that." comes out
    "re do it": "redo",
    "re do": "redo",
    "delete that": "delete",
    "that was a noise": "noise",  # takes back what a noise was written as, and keeps the sound
    "that was noise": "noise",
    "that was just a noise": "noise",
    "that was just noise": "noise",
    "that is a noise": "noise",
    "that's a noise": "noise",
    "spell that": "spell",
    "spell it": "spell",
    "spell this": "spell",
    "spell": "spell",
    "new paragraph": "new_paragraph",
    "new line": "new_line",
    "newline": "new_line",
    "press enter": "press_enter",
    "enter": "enter",  # the word by itself: its own setting, off unless asked for
    "select all": "select_all",
    "select everything": "select_all",
    "select all text": "select_all",
    "select whole document": "select_all",
    "select that": "select_last",
    "correct that": "select_last",  # Dragon's name for it: what is said next takes its place
    "unselect that": "unselect",
    "deselect that": "unselect",
    "cap that": "cap",
    "capitalize that": "cap",
    "capitalise that": "cap",
    "all caps that": "all_caps",
    "no caps that": "no_caps",
    "no cap that": "no_caps",   # how "no caps that" may be heard: not "no" and "cap that"
    "bold that": "bold",
    "italicize that": "italic",
    "italicise that": "italic",
    "underline that": "underline",
}
# (The ways of saying where to go, "go to the end of the line" and the rest, are not in
# the table: see _GO_TO.)

# Commands for the app's own windows. As a group they are the command "app": that name
# in `disabled` switches them all off.
APP = "app"
APP_COMMANDS = {
    "what can i say": "help",
    "open dictation settings": "settings",
    "dictation settings": "settings",
    "show microphone level": "meter",
    "show level meter": "meter",
    "close that window": "close",
}


@dataclass(frozen=True)
class Command:
    name: str
    arg: str = ""
    # Only perhaps a command: "Correct, John T." Said with a pause after the word, as a
    # sentence often is; the engine decides by what is on the page (see Engine.handle_text).
    maybe: bool = False


@dataclass(frozen=True)
class Dictation:
    text: str


def normalise(raw: str) -> str:
    """Lower case, no punctuation, single spaces: "Wake-up!" becomes "wake up"."""
    s = raw.lower().replace("’", "'")
    s = re.sub(r"\b(?:[a-z]\.){2,}", lambda m: m.group().replace(".", ""), s)  # "U.S." is "us"
    s = s.replace("-", " ")
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)     # "1,250" is one number
    s = re.sub(r"[^\w\s']", " ", s)
    return " ".join(s.split())


# Said without thinking before a command, or after it. They are not part of it:
# "OK, scratch that", "um, new paragraph", "go to sleep, please".
HESITATIONS = frozenset({"um", "uh", "er", "erm", "oh", "ok", "okay"})
# "No" is one too, but only where the recogniser heard a pause after it and wrote it
# down: "No, scratch that." With none it belongs to what follows: "No new line here."
# "And" is never one: "And select all." and "And delete that." are things people dictate.
PAUSED = "no"
POLITE = "please"


def _pauses_after(word: str, raw: str) -> list:
    """For each place `word` stands in `raw`, in turn, whether the recogniser wrote
    punctuation straight after it."""
    return [bool(_THEN_PUNCTUATION.match(raw, found.end()))
            for found in re.finditer(r"\b" + word + r"\b", raw, re.IGNORECASE)]


def without_fillers(phrase: str, least: int = 2, raw: str | None = None) -> str:
    """A normalised phrase without the "um" or "OK" it began with, and without "please"
    at either end. `raw` is the phrase as the recogniser wrote it: with it, a "no" that
    has punctuation straight after it goes as well ("No, scratch that.").

    The hesitation only goes if at least `least` words are left. One word is too easy
    to say by accident: "no, tab" and "OK, space" are things people dictate. "Please"
    goes even from one word, since nobody dictates "tab, please".
    """
    words = phrase.split()
    paused = iter(_pauses_after(PAUSED, raw) if raw is not None else ())
    while len(words) > least and (
            words[0] in HESITATIONS or (words[0] == PAUSED and next(paused, False))):
        del words[0]
    while len(words) > 1 and words[0] == POLITE:
        del words[0]
    while len(words) > 1 and words[-1] == POLITE:
        del words[-1]
    return " ".join(words)


def _without_the(phrase: str) -> str:
    """A normalised phrase without any "the" between its first word and its last: "go to
    the end of the line" is looked up as "go to end of line".

    A "the" that ends the phrase stays, and so the phrase is no command: it is the start
    of a sentence that a pause cut short. "New paragraph. The" is a break and a word to
    type, and "Undo the" goes on to say what."""
    words = phrase.split()
    return " ".join(words[:1] + [word for word in words[1:-1] if word != "the"] + words[1:][-1:])


_UNITS = "one two three four five six seven eight nine".split()
_TENS = {word: 10 * n for n, word in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)}
NUMBERS = {w: i for i, w in enumerate(
    _UNITS + "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
    "nineteen twenty".split(), start=1)}
NUMBERS.update({"to": 2, "too": 2, "for": 4, "won": 1})  # how Whisper may hear numbers
NUMBERS.update({"once": 1, "twice": 2})
ORDINALS = {w: i for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth".split(), start=1)}
# A count as it is said: figures, "forty two", or one word, which _count then looks up.
_N = r"(\d+|(?:" + "|".join(_TENS) + r") (?:" + "|".join(_UNITS) + r")|\w+)"
_BACKSPACE = re.compile(r"back ?space(?: " + _N + r")?(?: times?)?")
# "space", "space bar", "press space", "space 3". Not "space station": that is dictation.
_SPACE = re.compile(r"(?:press )?space ?(?:bar)?(?: " + _N + r")?(?: times?)?")
MAX_SPACES = 20
# "tab 3", "tab three times". "Tab" by itself is in COMMANDS.
_TAB = re.compile(r"(?:press )?tab(?: key)? " + _N + r"(?: times?)?")
MAX_TABS = 20
# Words that are a count after "backspace" but the start of a sentence after "space" or
# "tab": "space for everyone", "tab to the next box".
_NOT_A_COUNT = ("to", "too", "for", "won", "a")

# "Select" or "correct" and more words than this is a sentence that begins with the
# word, not a command: nobody picks out so many words by saying them all.
MAX_SELECT_WORDS = 8
# "Correct, yes." and "Select: the first one." The recogniser hears a pause after the
# word and writes it down. After a command word there is mostly none; but some people
# pause after "correct" before the words to put right, and then it is only perhaps a
# sentence: the engine keeps it one only if the words after it were typed a moment ago
# (see Engine._just_typed_words), which can be a whole sentence said over again:
# "Correct, I guess I'll carry on the other side" right after that sentence.
_THEN_PUNCTUATION = re.compile(r"\s*(?:[,.;:!?…]|[-–—]\s)")
MAYBE_SELECT_WORDS = 30


_DELETE_WORDS = re.compile(r"delete (?:the )?(?:last|previous) (?:" + _N + r" )?words?")
_MOVE_WORDS = re.compile(
    r"(?:move|go) (left|back|backward|backwards|right|forward|forwards) (?:" + _N + r" )?words?")
_MOVE_LINES = re.compile(r"(?:go |move )?(up|down) (?:" + _N + r" )?lines?")
_DELETE_LINES = re.compile(
    r"delete (?:(?:this|the|that|current) )?line|delete " + _N + r" lines?")
_GO_TO_LINE = re.compile(r"(?:go to|goto|jump to) line (?:number )?" + _N)
# "Go to the end of the line", "go to beginning of paragraph", "go to the top", "go to
# the end of the document". Looked for with every "the" taken out.
_GO_TO = re.compile(
    r"go to (end|start|beginning|top|bottom)(?: of (?:this )?(line|paragraph|document|file))?")
_LINE_VERBS = {"select": "select_line", "indent": "indent", "outdent": "outdent",
               "unindent": "outdent", "comment": "comment_line", "uncomment": "comment_line",
               "duplicate": "duplicate_line"}
_THIS_LINE = re.compile(r"(" + "|".join(_LINE_VERBS) + r") (?:this|that|current) line")
LINE_COMMANDS = {
    "select line": "select_line", "select this line": "select_line",
    "select the line": "select_line", "select current line": "select_line",
    "indent": "indent", "indent line": "indent", "indent that": "indent",
    "indent this line": "indent",
    "outdent": "outdent", "outdent line": "outdent", "outdent that": "outdent",
    "unindent": "outdent", "unindent line": "outdent", "outdent this line": "outdent",
    "comment line": "comment_line", "comment this line": "comment_line",
    "comment that": "comment_line", "uncomment line": "comment_line",
    "uncomment that": "comment_line", "toggle comment": "comment_line",
    "duplicate line": "duplicate_line", "duplicate this line": "duplicate_line",
    "duplicate that": "duplicate_line",
}
_WORD_MOVES = {"left": "word_left", "back": "word_left", "backward": "word_left",
               "backwards": "word_left", "right": "word_right", "forward": "word_right",
               "forwards": "word_right"}


def last_words_length(before: str, count: int) -> int:
    """How many characters to remove to delete the last `count` words before the cursor.

    Takes the punctuation and spaces after each word, and the space before the
    first, so "Hello big world." minus one word leaves "Hello big". If there are
    fewer words than asked for, it takes them all.

    A word runs back to the space before it, so a price, a number with a comma in it
    and an address each go whole: "costs $25.50" minus one word leaves "costs".
    """
    words = [m.start() for m in _SAID.finditer(before)]
    if not words or count < 1:
        return 0
    start = words[max(0, len(words) - count)]
    while start > 0 and before[start - 1].isspace():
        start -= 1
    return len(before) - start


_SAID = re.compile(r"\S*\w\S*")  # what stands between two spaces, if there is a word in it


def _number(said: str, most: int | None = None) -> int | None:
    """A number as it was said, in figures or in words up to "ninety nine", or None.
    One over `most` counts as `most`: "backspace 100" asks for as many as can be done,
    and is not a sentence to type."""
    tens, _, unit = said.partition(" ")
    if said.isdigit():
        n = int(said)
    elif tens in _TENS and (not unit or unit in _UNITS):
        n = _TENS[tens] + (_UNITS.index(unit) + 1 if unit else 0)
    else:
        n = NUMBERS.get(said, 0)
    if n < 1:
        return None
    return min(n, most) if most else n


def _count(said: str | None, most: int = 99) -> int | None:
    """A spoken count from 1 to `most`, or None if it isn't one. No word means 1."""
    if said is None or said == "a":
        return 1
    return _number(said, most)


def _ordinal(word: str) -> int | None:
    """Which one "second" or "2nd" is, or None."""
    figures = re.fullmatch(r"(\d+)(?:st|nd|rd|th)", word)
    return int(figures.group(1)) if figures else ORDINALS.get(word)


_CHOOSING = frozenset({"choose", "number", "pick", "select", "option", "the"})


def choice(raw: str, limit: int) -> int | None:
    """The number picked from a numbered list of `limit` matches, or None.

    "2", "two", "choose 2", "number two", "second", "the second one" and "two, please"
    all pick the second.
    """
    words = without_fillers(normalise(raw), least=1, raw=raw).split()
    while len(words) > 1 and words[0] in _CHOOSING:
        del words[0]
    if len(words) == 2 and words[1] == "one" and _ordinal(words[0]):
        del words[1]
    if len(words) != 1:
        return None
    n = _ordinal(words[0]) or _count(words[0])
    return n if n and n <= limit else None


CANCEL = frozenset({"cancel", "cancel that", "cancel it", "never mind", "nevermind", "none",
                    "none of them", "neither", "neither of them"})


def is_cancel(raw: str) -> bool:
    """Whether a phrase said while numbers are showing means "take them away"."""
    return without_fillers(normalise(raw), least=1, raw=raw) in CANCEL


# How the first word of "wake up" is written, and may be written for it.
_WAKE_WORDS = frozenset({"wake", "awake", "weak", "wakeup"})
# And how "up" may be heard after it: "up", "upp", "ups", "app", "op", "cup", "hup".
_LIKE_UP = re.compile(r"[a-z]?[aou]pp?s?")


def is_wake(phrase: str, short: bool = False) -> bool:
    """True if a normalised phrase is "wake up", allowing for a slight mishearing.

    It has to be said on its own: "wake up the kids" doesn't count. And it has to begin
    with "wake", or with "awake" or "weak", which are that word misheard: "make up",
    "woke up", "take up" and "walk up" are near it letter for letter, and are things
    said to somebody else in the room. So is "wake me up": every word that follows has
    to be "up" or a mishearing of it, as "app" and "op" are.

    With `short`, "wake" by itself counts too. That word exactly: one so short has too
    many neighbours ("wait", "week", "make", "awake") for a near miss to be let through.
    """
    if phrase in ("wake up", "wakeup", "wake up wake up"):
        return True
    if short and SHORT_COMMANDS.get(phrase) == WAKE:
        return True
    words = phrase.split()
    if not 2 <= len(words) <= 3 or words[0] not in _WAKE_WORDS:
        return False
    return all(_LIKE_UP.fullmatch(word) for word in words[1:])


def _place(edge: str, of: str | None) -> str | None:
    """The command for "go to the `edge` of the `of`", or None where that says too
    little: "go to the end" could be the end of the line or of everything."""
    first = edge in ("start", "beginning", "top")
    if of in ("line", "paragraph") and edge not in ("top", "bottom"):
        return ("line_" if of == "line" else "para_") + ("start" if first else "end")
    if of in ("document", "file") or (of is None and edge in ("top", "bottom")):
        return "doc_top" if first else "doc_end"
    return None


def _command(phrase: str, disabled, short: bool) -> Command | bool | None:
    """The command that a normalised phrase is. None if it is none; False if it is one
    that is switched off, and so is to be typed."""
    if short and phrase in SHORT_COMMANDS:
        return Command(SHORT_COMMANDS[phrase])
    # "Move to end of line" and "jump to top" are the same as "go to ...".
    for other in ("move to ", "jump to ", "goto "):
        if phrase.startswith(other):
            phrase = "go to " + phrase[len(other):]
    bare = _without_the(phrase)
    name = COMMANDS.get(phrase) or COMMANDS.get(bare)
    if name:
        return Command(name) if name not in disabled or name in (WAKE, "sleep") else False
    if bare in APP_COMMANDS:
        return Command(APP, APP_COMMANDS[bare]) if APP not in disabled else False
    m = _GO_TO.fullmatch(bare)
    name = _place(*m.groups()) if m else None
    if name:
        return Command(name) if name not in disabled else False
    m = _BACKSPACE.fullmatch(bare)
    if m and "backspace" not in disabled and _count(m.group(1)):
        return Command("backspace", str(_count(m.group(1))))
    # "Space for" and "space to" are the start of a sentence, not a count, though the
    # same words are taken for numbers after "backspace". The same goes for "tab".
    m = _SPACE.fullmatch(bare)
    if (m and "space" not in disabled and _count(m.group(1))
            and m.group(1) not in _NOT_A_COUNT):
        return Command("space", str(_count(m.group(1), MAX_SPACES)))
    m = _TAB.fullmatch(bare)
    if m and "tab" not in disabled and _count(m.group(1)) and m.group(1) not in _NOT_A_COUNT:
        times = _count(m.group(1), MAX_TABS)
        return Command("tab", str(times) if times > 1 else "")
    m = _DELETE_WORDS.fullmatch(bare)
    if m and "delete_words" not in disabled and _count(m.group(1)):
        return Command("delete_words", str(_count(m.group(1))))
    m = _THIS_LINE.fullmatch(bare)
    name = _LINE_VERBS[m.group(1)] if m else LINE_COMMANDS.get(bare)
    if name and name not in disabled:
        return Command(name)
    # As it was said, "the" and all: "down the line" is something people say and write.
    m = _MOVE_LINES.fullmatch(phrase)
    if m and f"line_{m.group(1)}" not in disabled and _count(m.group(2)):
        return Command(f"line_{m.group(1)}", str(_count(m.group(2), 999)))
    m = _DELETE_LINES.fullmatch(bare)
    if m and "delete_line" not in disabled and _count(m.group(1)):
        return Command("delete_line", str(_count(m.group(1))))
    m = _GO_TO_LINE.fullmatch(bare)
    if m and "go_to_line" not in disabled and _number(m.group(1)):
        return Command("go_to_line", str(_number(m.group(1))))
    m = _MOVE_WORDS.fullmatch(bare)
    if m and _WORD_MOVES[m.group(1)] not in disabled and _count(m.group(2)):
        return Command(_WORD_MOVES[m.group(1)], str(_count(m.group(2))))
    return None


def _selecting(phrase: str, raw: str, disabled) -> Command | None:
    """ "Select the cat" highlights those words. "Correct the cat" does too, and puts the
    cursor back where it was once something has been said in their place. If the words
    aren't there, the engine types the phrase instead.

    A sentence can begin with either word. Where the words are in the document it can't
    be told from the command, but two things give it away before that: the recogniser
    wrote punctuation straight after the word ("Correct, yes."), or more follows than
    anyone selects by saying it.
    """
    for said in ("select", "correct"):
        if said in disabled or not phrase.startswith(said + " "):
            continue
        words = phrase[len(said) + 1:]
        first = re.search(r"\b" + said + r"\b", raw, re.IGNORECASE)
        if first and _THEN_PUNCTUATION.match(raw, first.end()):
            # ("Correct, I guess I'll carry on the other side": perhaps the command, said
            # after a pause with the sentence just said; the engine tells by whether those
            # words are what it has just typed.)
            if len(words.split()) <= MAYBE_SELECT_WORDS:
                return Command(said, words, maybe=True)
            return None
        if len(words.split()) > MAX_SELECT_WORDS:
            return None
        return Command(said, words)
    return _clicking(phrase, raw, disabled)


CLICK = "click"
MAX_CLICK_WORDS = 6   # a button's name is short: more words than this is a sentence


def _clicking(phrase: str, raw: str, disabled) -> Command | None:
    """ "Click OK" presses the button, the link, the tick box or the menu of that name in
    the program in front. If nothing there has the name, the engine types the phrase
    instead, as it does for "select" with words that aren't there. Like "select", it is
    given away as a sentence by punctuation straight after the word, or by its length."""
    if CLICK in disabled or not phrase.startswith(CLICK + " "):
        return None
    words = phrase[len(CLICK) + 1:].split()
    if words[:1] == ["on"]:
        words = words[1:]
    if words[:1] == ["the"] and len(words) > 1:
        words = words[1:]
    if len(words) > 1 and words[-1] in ("button", "link", "tab", "menu", "checkbox"):
        words = words[:-1]
    first = re.search(r"\b" + CLICK + r"\b", raw, re.IGNORECASE)
    if not words or len(words) > MAX_CLICK_WORDS or (
            first and _THEN_PUNCTUATION.match(raw, first.end())):
        return None
    return Command(CLICK, " ".join(words))


def interpret(raw: str, awake: bool, disabled=frozenset()) -> Command | Dictation | None:
    """Decide what one phrase from Whisper means. None means ignore it.

    A command named in `disabled` is typed as ordinary dictation. Waking and
    sleeping can't be disabled; SHORT in `disabled` only takes the one-word ways of
    saying them away.

    The phrase is looked up as it was said, then without the "um" or "OK" before it
    and the "please" after it: "no caps that" is a command as it stands, and "no,
    scratch that" is one once the "no" is gone. (That "no" has to have a pause after
    it, which the recogniser writes as a comma: "No new line here" is a sentence.)
    """
    phrase = normalise(raw)
    if not phrase:
        return None
    short = SHORT not in disabled
    plain = without_fillers(phrase, raw=raw)
    if not awake:
        return Command(WAKE) if is_wake(phrase, short) or is_wake(plain, short) else None
    for said in dict.fromkeys((phrase, plain)):
        found = _command(said, disabled, short)
        if found is not None:
            return found or Dictation(raw)
    # "Scratch that, scratch that." Said twice in a breath, a command is done once: only
    # one thing can be done for a phrase, and doing it is nearer to what was wanted than
    # typing it. Not the line breaks: as dictation, said twice, they come out as two.
    words = plain.split()
    if len(words) >= 4 and words[:len(words) // 2] == words[len(words) // 2:]:
        found = _command(" ".join(words[:len(words) // 2]), disabled, short)
        if found and found.name not in ("new_line", "new_paragraph"):
            return found
    return _selecting(plain, raw, disabled) or Dictation(raw)


# Cursor-movement commands, as steps for the Writer extension's "move" request:
# ["view" or "text", method, arguments...]. Adding one here needs no extension update.
MOVES = {
    "line_end": [["view", "gotoEndOfLine", False]],
    "line_start": [["view", "gotoStartOfLine", False]],
    "para_end": [["text", "gotoEndOfParagraph", False]],
    "para_start": [["text", "gotoStartOfParagraph", False]],
    "doc_top": [["view", "gotoStart", False]],
    "doc_end": [["view", "gotoEnd", False]],
}


WORD_STEPS = {"word_left": ["text", "gotoPreviousWord", False],
              "word_right": ["text", "gotoNextWord", False]}


LINE_STEPS = {"line_up": "goUp", "line_down": "goDown"}
WHOLE_LINE = [["view", "gotoStartOfLine", False], ["view", "gotoEndOfLine", True]]


def is_move(name: str) -> bool:
    return (name in MOVES or name in WORD_STEPS or name in LINE_STEPS
            or name in ("select_line", "delete_line", "select_all"))


def move_steps(name: str, before: str, after: str, count: int = 1) -> list:
    """The steps for a cursor-movement command, given the text around the cursor.

    "Move left 3 words" is one step back a word, three times.

    Already at the end of a paragraph, "go to end of paragraph" goes on to the end of
    the next one. Already at the start, "go to start of paragraph" goes back to the
    start of the one before. So repeating either command walks through the document.
    """
    if name in WORD_STEPS:
        return [WORD_STEPS[name]] * max(1, min(99, count))
    if name in LINE_STEPS:
        return [["view", LINE_STEPS[name], max(1, min(999, count)), False]]
    if name == "select_all":
        return [["view", "gotoStart", False], ["view", "gotoEnd", True]]
    if name in ("select_line", "delete_line"):
        # The line is selected; deleting it is a second step. For several, the selection
        # is first carried down over the lines after it.
        more = max(1, min(99, count)) - 1 if name == "delete_line" else 0
        return (WHOLE_LINE[:1] + [["view", "goDown", more, True]] + WHOLE_LINE[1:]) if more \
            else WHOLE_LINE
    if name == "para_end" and not after:
        return [["text", "gotoNextParagraph", False], ["text", "gotoEndOfParagraph", False]]
    if name == "para_start" and not before:
        return [["text", "gotoPreviousParagraph", False],
                ["text", "gotoStartOfParagraph", False]]
    return MOVES[name]
