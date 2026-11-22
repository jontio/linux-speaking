"""Your own words: names and unusual terms the recogniser should know about.

Whisper is given the words as a hint. A hint is strong: with "Joe" in it, "Jo" comes out
as "Joe". So when a hinted phrase contains one of the words, the phrase is heard again
without the hint and the two hearings are compared. Where the plain hearing has an
ordinary word written the ordinary way ("rose" in the middle of a sentence), that stands.
Where it has what looks like a name it didn't know ("John E." for "Johnny"), or the words
before call for a name ("Cheers,"), your word stands.

A recogniser that can't be given a hint, such as Parakeet, is helped the other way about:
what it wrote is searched for something that sounds like one of the words (by_sound). That
is thin evidence, so it is hedged. The sounds have to agree where a name is told from
another: the consonants, the first vowel and the number of syllables. "Dan" is not "Don",
"Dean" or "Danny"; but "Sara" is Sarah, "Jon" is John and "Zeffer" is Zephyr, which is
what the list is for. And the word still only goes in where a name fits, as above.

A word with both letters and figures in it, such as a part number ("vLR5340"), is not a
name, and isn't found by its sound: a sound has no figures in it. It is found by its
letters and figures, however the recogniser split them up or wrote them out ("VLR 5340",
"VLR-5340", "V L R fifty three forty"), and put in as you spelled it. Everyday words can
have the same letters and figures, so the letters have to be written as a code's are:
"a 380 pound gorilla" is no A380, and "we win 11 games" no Win11.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .formatting import ADDRESSED, SPOKEN
from .words import COMMON, I_WORDS, Lexicon

MAX_WORDS = 40
MAX_WORD_CHARS = 40
MAX_HINT_CHARS = 300

# Words that a name usually follows: greetings, sign-offs and introductions.
CUES = tuple(cue.split() for cue in (
    "hi", "hello", "hey", "dear", "morning", "afternoon", "evening", "thanks", "thank you",
    "cheers", "regards", "wishes", "best", "sincerely", "faithfully", "love", "from",
    "name is", "name's", "i'm", "i am", "call me", "called", "named",
))
# Those of them that open or close a message, where little but a name comes next. The
# rest ("I'm", "from", "best") are followed by all sorts of words.
GREETINGS = tuple(cue for cue in CUES if " ".join(cue) in (
    "hi", "hello", "hey", "dear", "morning", "afternoon", "evening", "thanks", "thank you",
    "cheers", "regards", "wishes", "best", "love", "sincerely", "faithfully", "name is",
    "name's", "call me"))
# Those that open a message. Straight after one, what is said is a name or a word that
# stands for the people written to, and little else: "Dear" and then "done" is Dan.
SALUTATIONS = tuple(cue for cue in CUES if " ".join(cue) in (
    "hi", "hello", "hey", "dear", "morning", "afternoon", "evening"))
# Words that are never taken for one of the person's names, whatever came before and
# however alike they sound: those that stand for the people spoken to, and the commonest.
_NEVER_A_NAME = COMMON | frozenset(ADDRESSED)
# Punctuation and line breaks said aloud: "cheers comma new line" still ends in a cue. So
# does "cheers comma enter": "enter" is said for the line break between a sign-off and the
# name under it (see letters.signoff). ("press enter" before "enter", which is part of it.)
SAID = tuple(phrase.split() for phrase, _ in SPOKEN) + (
    ["newline"], ["next", "line"], ["press", "enter"], ["enter"])
_EDGES = re.compile(r"^\W+|\W+$")
_SENTENCE_END = re.compile(r"[.!?][\"')\]”’]*$")


# ---- part numbers and the like ------------------------------------------------------------
_UNITS = dict(pair.split("=") for pair in (
    "zero=0 oh=0 nought=0 one=1 two=2 three=3 four=4 five=5 six=6 seven=7 eight=8 nine=9 "
    "ten=10 eleven=11 twelve=12 thirteen=13 fourteen=14 fifteen=15 sixteen=16 seventeen=17 "
    "eighteen=18 nineteen=19").split())
_TENS = dict(pair.split("=") for pair in
             "twenty=2 thirty=3 forty=4 fifty=5 sixty=6 seventy=7 eighty=8 ninety=9".split())
# Letters said by their names, as a recogniser may write them: "vee el ar" for VLR.
_LETTERS = dict(pair.split("=") for pair in (
    "ay=a bee=b cee=c see=c dee=d ee=e ef=f eff=f gee=g aitch=h haitch=h eye=i jay=j kay=k "
    "el=l ell=l em=m en=n pee=p cue=q queue=q ar=r are=r es=s ess=s tee=t tea=t you=u vee=v "
    "ex=x why=y zed=z zee=z").split())
LONGEST_CODE = 8  # pieces a code may have been heard as: "V L R fifty four H twenty"


def is_code(word: str) -> bool:
    """Whether one of the person's words is a code, such as a part number: letters and
    figures together, at least three of them ("MP3", "CO2"). A figure with its ending
    is not one: "3rd party", "10th"."""
    word = re.sub(r"\b\d+(?:st|nd|rd|th)\b", "", word.lower())
    return (any(c.isdigit() for c in word) and any(c.isalpha() for c in word)
            and len(_code_key(word)) >= 3)


def names(words) -> tuple:
    """The person's words without the codes: those that are looked for by their sound."""
    return tuple(word for word in words if not is_code(word))


def _plain(text: str) -> str:
    """`text` in small letters and without accents, so that a word compares the same
    whether or not the recogniser wrote its accents."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def _code_key(text: str) -> str:
    """Letters and figures only, in small letters: how a code is compared, so that
    "VLR-5340", "vLR5340" and "VLR 5340" are one. Letters of any alphabet count, or a
    code that begins with a Greek letter would be the same as one that doesn't.

    A letter o beside a figure is taken for a nought, because a nought is said "oh" and
    written down as either. An o among letters is a letter: the "TO" of "TO-220"."""
    return re.sub(r"(?<=\d)o|o(?=\d)", "0", "".join(c for c in _plain(text) if c.isalnum()))


def _pieces(token: str):
    """The parts of one written word that are looked at one at a time: "fifty-three" is
    two. Each is (as written, bare), both without a possessive ending, and the bare one
    in small letters with nothing but its letters and figures."""
    for part in re.split(r"[-\u2010\u2011]", token.replace("\u2019", "'")):
        part = part[:-2] if part.lower().endswith("'s") else part
        yield part, "".join(c for c in _plain(part) if c.isalnum())


def _heard_key(tokens: list) -> str:
    """How a run of written words compares with a code: figures said as words become
    figures ("fifty three forty" is 5340), letters said by name become letters."""
    parts = []
    for token in tokens:
        for _, bare in _pieces(token):
            if bare in _TENS:
                parts.append(("tens", _TENS[bare]))
            elif bare in _UNITS:
                parts.append(("unit", _UNITS[bare]))
            else:
                parts.append(("text", _LETTERS.get(bare, bare)))
    out = []
    for at, (kind, value) in enumerate(parts):
        if kind == "tens":
            following = parts[at + 1] if at + 1 < len(parts) else ("", "")
            joined = following[0] == "unit" and len(following[1]) == 1 and following[1] != "0"
            out.append(value if joined else value + "0")   # "fifty three" is 53, "forty" 40
        else:
            out.append(value)
    return _code_key("".join(out))


# Names of letters that are no everyday word, so that written out they can only be a
# letter. The others ("you", "are", "see", "tea") are words first.
_SURE_LETTERS = frozenset(
    "cee dee ee ef eff aitch haitch el ell em en ar es ess vee zed zee".split())


def _written_as_a_code(tokens: list, at: int, count: int) -> bool:
    """Whether tokens[at:at + count] could be a code and not a few everyday words that
    happen to have its letters and figures: "a 380 pound gorilla" is not an A380, nor
    "you are 10 minutes late" a UR10, nor "we win 11 games" Win11.

    The run has to hang together: every word in it has a letter or a figure, and there
    is no punctuation inside it, where a sentence or a clause would end. And the first
    of its letters have to be written the way a code's are and an everyday word's are
    not: joined to the figures ("vlr5340"), in capitals ("VLR 5340", "Win 11" but not as
    the first word of a sentence, where every word has one), or as the name of a letter
    that is no word ("vee el ar"). What follows those may be written any way.
    """
    piece = tokens[at:at + count]
    for n, token in enumerate(piece):
        if not any(c.isalnum() for c in token):
            return False                       # a dash or an "&" by itself
        if (n and not token[0].isalnum()) or (n < count - 1 and not token[-1].isalnum()):
            return False                       # "VLR. 5340", "VLR (5340"
    starts = at == 0 or bool(_SENTENCE_END.search(tokens[at - 1]))
    for token in piece:
        for part, bare in _pieces(_EDGES.sub("", token)):
            if bare in _TENS or bare in _UNITS or not any(c.isalpha() for c in bare):
                continue                       # figures, in figures or in words
            if any(c.isdigit() for c in bare) or bare in _SURE_LETTERS:
                return True
            if len(bare) == 1:
                return part.isupper() and not (starts and bare in "ai")
            return part.isupper() or (part[0].isupper() and not starts)
        starts = False
    return False


def spell_codes(text: str, words) -> str:
    """`text` with each of the person's codes written as they spelled it, wherever the
    recogniser wrote the same letters and figures: split up, joined with hyphens, in
    other capitals, or said as words. Nothing else is changed."""
    codes = {}
    for word in words:
        if is_code(word):
            codes.setdefault(_code_key(word), word)
    tokens = text.split()
    if not codes or not tokens:
        return text
    out, at = [], 0
    while at < len(tokens):
        for count in range(min(LONGEST_CODE, len(tokens) - at), 0, -1):
            piece = tokens[at:at + count]
            word = codes.get(_heard_key(piece)) if _written_as_a_code(tokens, at, count) else None
            if word:
                lead = re.match(r"^[^\w]*", piece[0]).group()       # "(" before it stays
                tail = re.search(r"(?:['\u2019]s)?[^\w]*$", piece[-1]).group()   # and "'s," after
                out.append(lead + word + tail)
                at += count
                break
        else:
            out.append(tokens[at])
            at += 1
    return " ".join(out)


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


def _squashed(word: str) -> str:
    """A word's letters only, in small letters: "Deep Seek" and "DeepSeek" are one."""
    return "".join(c for c in _plain(str(word)) if c.isalnum())


# How each letter sounds when it is said by its name: the "E" of "John E".
_LETTER_SOUNDS = dict(pair.split("=") for pair in (
    "a=A b=bE c=sE d=dE e=E f=ef g=jE h=Ak i=I j=jA k=kA l=el m=em n=en o=o p=pE q=kU "
    "r=ar s=es t=tE u=U v=vE w=dublU x=eks y=wI z=sed").split())
# How a run of vowels sounds, where its letters one by one would not say. A capital is
# the long sound: the "a" of "Kate" beside that of "Kat", the "o" of "Joan" beside that
# of "John". (The "au" of "jaunty" goes with the short one.)
_VOWEL_RUNS = dict(pair.split("=") for pair in (
    "ai=A ay=A ae=A ei=A ea=E ee=E ie=E au=o aw=o oa=O ow=O oe=O oo=U ue=U ew=U ui=U eu=U "
    "ou=W oi=Y oy=Y y=i").split())
_LONG = {"a": "A", "e": "E", "i": "I", "o": "O", "u": "U"}
_VOWEL = "aeiouyw"
_VOWEL_SOUNDS = "aeiouAEIOUWY"
# The vowel a name ends with, by kind: the "a" of "Maria", the "o" of "Mario", and one
# kind for "Katie", "Katy", "Lindsay" and the E of "John E".
_ENDS_WITH = {"a": "a", "o": "o", "O": "o", "u": "u", "U": "u", "W": "u", "Y": "o"}
# Names whose spelling doesn't say how they sound, as one that does.
_SAID_AS = {"sean": "shaun", "stephen": "steven", "geoff": "jeff", "geoffrey": "jeffrey"}


def _vowel(run: str) -> tuple:
    """(how it sounds, how many syllables) for a run of vowel letters inside a word. Two
    vowels that are no pair are said one after the other: the "ia" of "Maria"."""
    letters = "".join("i" if c == "y" else c for c in run if c != "w")
    sound = _VOWEL_RUNS.get(run) or ("w" not in run and _VOWEL_RUNS.get(letters))
    if sound:
        return sound, 1
    letters = re.sub(r"(.)\1+", r"\1", letters) or run
    return letters, min(len(letters), 2)


def _word_sounds(word: str) -> list:
    """One word as it sounds, in pieces: [vowel?, the sound, syllables, stressed by a
    silent e?] for each run of consonants or of vowels. Consonants stand for themselves,
    less the ones that make no difference ("ph" is "f", the "h" of "John" and "Sarah" is
    nothing). Vowels are kept apart as far as spelling tells: short or long ("Kat",
    "Kate"), which of them ("Dan", "Don", "Dean"), and how many there are ("Dan", "Danny",
    "Maria").

    Where another letter makes another name the consonants are kept apart too, now that
    a name the dictionary knows may be replaced: the "h" a word starts with ("Helen" is
    not Ellen, nor "Emma" Hemi), "c" before e, i and y ("Bruce" is not Brook), and "ch"
    ("March" is not Mark, nor "Charlie" Carly), unless r or l follows ("Chris", "Chloe").
    """
    s = "".join(c for c in _plain(word) if "a" <= c <= "z")
    if len(s) == 1:      # a letter said by its name: the "E" of "John E"
        return [[c in _VOWEL_SOUNDS, c, 1 if c in _VOWEL_SOUNDS else 0, False]
                for c in _LETTER_SOUNDS[s]]
    s = _SAID_AS.get(s, s)
    said_e = s.endswith("nte")   # "Dante": there the last e is said
    s = s.replace("ph", "f").replace("ck", "k").replace("gh", "")
    s = re.sub(r"ch(?=[rl])", "k", s).replace("ch", "C")
    s = re.sub(r"c(?=[eiy])", "s", s)
    s = re.sub(r"^h(?=[aeiouy])", "H", s)
    s = re.sub(r"[cq]", "k", s).replace("x", "ks").replace("z", "s").replace("h", "")
    runs = []  # (whether it is vowels, the letters)
    for run in re.findall(f"[{_VOWEL}]+|[^{_VOWEL}]+", s):
        if run[0] in "wy" and len(run) > 1:
            runs.append((False, run[0]))  # before a vowel they are consonants: "will", "yes"
            run = run[1:]
        runs.append((run[0] in _VOWEL, run))
    vowels = [n for n, (vowel, _) in enumerate(runs) if vowel]
    sounds = []
    for n, (vowel, run) in enumerate(runs):
        last = n == len(runs) - 1
        if not vowel:
            sounds.append([False, run, 0, False])
        elif last and run == "e" and len(vowels) > 1 and not said_e:
            # Silent. It makes the vowel before one consonant long, "Kate", "June", and
            # the one before any stressed: the end of "Michelle" is not that of "Michael".
            if n >= 2 and runs[n - 2][0]:
                if runs[n - 2][1] in _LONG and len(runs[n - 1][1]) == 1:
                    sounds[n - 2][1] = _LONG[runs[n - 2][1]]
                sounds[n - 2][3] = True
        elif last and run == "ea" and len(vowels) > 1:
            sounds.append([True, "a", 2, False])                             # "Andrea"
        elif last and run in ("y", "i", "ie", "ey", "ee", "ea"):
            alone = len(vowels) == 1
            sounds.append([True, "I" if alone and run in ("y", "i", "ie") else "E", 1, False])
        elif last and run == "o":
            sounds.append([True, "O", 1, False])                             # "Jo"
        else:
            sounds.append([True, *_vowel(run), False])
    return sounds


def sound_key(text: str) -> str:
    """Roughly how `text` sounds, for telling whether something the recogniser wrote is
    one of the person's words spelled another way.

    Two things sound the same when their consonants are the same, their first vowels are
    of the same kind, and they have as many syllables (a silent "e" at the end is none).
    So "Joe" and "Jo" come out alike, and "Johnny", "Jonny", "Johnie" and "John E", and so do "Sara"
    and "Sarah", "Jon" and "John", "Zeffer" and "Zephyr": the vowels after the first are
    where spellings of one name differ. And "Dan", "Don", "Dean", "Diane", "Donna" and
    "Danny" do not, nor "Mary", "Maria" and "Murray".

    Two of the later vowels are kept apart from the rest all the same, because they make
    another name: the one that a silent "e" stresses ("Michelle" is not Michael, nor
    "Simone" Simon), and the one a name ends with ("Maria" is not Mario).

    For a word the dictionary doesn't know there is a looser match as well: see _near.
    """
    sounds = []
    # (A capital inside a word starts a word of its own: "LibreOffice" is said as two.)
    for word in re.split(r"[\s-]+|(?<=[a-z])(?=[A-Z])", text):
        if any("a" <= c <= "z" for c in _plain(word)):
            sounds += _word_sounds(word)
    key, first = [], True
    for n, (vowel, sound, syllables, stressed) in enumerate(sounds):
        if not vowel:
            key.append(sound)
        elif first:
            key.append(sound + "." * (syllables - 1))
            first = False
        elif n == len(sounds) - 1:
            key.append("." * (syllables - 1) + _ENDS_WITH.get(sound[-1], "e"))
        else:
            key.append(":" if stressed else "." * syllables)
    return re.sub(r"([^" + _VOWEL_SOUNDS + r".:])\1+", r"\1", "".join(key))


def _near(key: str) -> str:
    """A sound key with a short "u" for its first vowel taken as the short "o": "Junny" is
    near "Johnny". The two sounds are close, and a recogniser that has to make up a spelling
    for a name it doesn't know writes either. Only for a word made up like that (see
    _made_up): a real word or a known name has to sound the same, "Russ" is not Ross."""
    return re.sub("^([^" + _VOWEL_SOUNDS + "]*)u", r"\1o", key, count=1)


def _joined_made_up(cores: list, lexicon: Lexicon) -> bool:
    """Whether tokens joined make a word in no dictionary, as "Deep Seek" does for
    "DeepSeek": no ordinary run of English words can be one of the person's as well, and one
    of theirs written as two is otherwise held back for want of a capital ("Deep Seek is
    useful" at the start of a sentence, or written in small letters). A letter said by
    itself ("I") is no such word."""
    joined = _squashed("".join(cores))
    return len(joined) > 1 and joined not in I_WORDS and _made_up(joined, lexicon)


def _joined_like_hinted(p: list, h: list, h1: int, h2: int, p1: int, p2: int,
                        lexicon: Lexicon) -> bool:
    """Whether the plain hearing's two words, with nothing between them, are the hinted
    word written as two: the same sound, and the two joined no word at all ("Deep Seek"
    for "DeepSeek"). A comma or a stop between them is a break, and no word: "pay, pal"
    is not "PayPal". (Their sound is of the words as they were written: the capital in the
    middle of "GitHub" is what makes it two, and the plain hearing's "git hub".)"""
    if p2 - p1 != 2 or not p[p1][-1:].isalnum() or not p[p1 + 1][:1].isalnum():
        return False
    if not _joined_made_up(p[p1:p2], lexicon):
        return False
    return sound_key(" ".join(h[h1:h2])) == sound_key(" ".join(p[p1:p2]))


def _made_up(core: str, lexicon: Lexicon) -> bool:
    """Whether the recogniser made `core` up: it is in no dictionary, as an everyday word or
    as a name. Without a dictionary nothing can be told, so nothing is."""
    return (lexicon.has_dictionary and core.isalpha() and core not in lexicon.capitalised
            and not lexicon.ordinary(core.lower()))


def _part_of_a_name(tokens: list, at: int, lexicon: Lexicon) -> bool:
    """Whether the word at tokens[at] could be half of a name the recogniser wrote as two
    words: a capital letter by itself, as in "John E"; a capitalised word that the
    dictionary lists as a name, or that is no everyday one; or any capitalised word
    that doesn't start a sentence, where the capital is the recogniser's way of writing
    a name ("Libre Office", "Git Hub"). Never "I", and never a word written small,
    however it sounds: "saw Amy" is not "Sam"."""
    core = _EDGES.sub("", tokens[at])
    if not core or not core[0].isupper() or _key(tokens[at]) in I_WORDS:
        return False
    starts = at == 0 or bool(_SENTENCE_END.search(tokens[at - 1]))
    return (len(core) == 1 or not starts or core in lexicon.capitalised
            or not lexicon.ordinary(_key(tokens[at])))


def by_sound(text: str, before: str, words, lexicon: Lexicon | None = None) -> str:
    """`text` with a listed word put in where something that sounds like it was written
    and a name fits there. For a recogniser that can't be given the words as a hint.

    The places are found by sound. Sound alone is thin evidence, so the word goes in
    only where the recogniser wrote a name or a word it didn't know ("I spoke to Johnie"
    for Johnny), or where it stands by itself right after a greeting or a sign-off
    ("Cheers," and then "Johnie"). Elsewhere an everyday word stays: "I'm done" is not
    "I'm Dan", nor "from time to time" anything to do with Tom.

    What sounds the same is the same, whether or not the dictionary knows it as a name:
    the list is there to put right a name the recogniser spelled the usual way. With
    "Jon" listed, "John" is Jon, and with "Sarah", "Sara" is Sarah. A name that sounds
    different is somebody else's and stays (see sound_key): "Don" is not Dan. A word in
    no dictionary at all, which the recogniser made up, may be a little further off
    ("Junny" for Johnny: see _near). Two words are taken for one name only where both look
    like parts of one, as "John E" and "Libre Office" do and "saw Amy" doesn't.
    """
    lexicon = lexicon or Lexicon()
    keys, near = {}, {}
    for word in names(words):  # a code has figures, which a sound hasn't: see spell_codes
        key = sound_key(word)
        if len(key) >= 3:
            keys.setdefault(key, word)
            near.setdefault(_near(key), word)
    tokens = text.split()
    if not keys or not tokens:
        return text
    out, at, found = [], 0, False
    while at < len(tokens):
        for count in (1, 2):  # one word if it will do, else two: "John E"
            piece = tokens[at:at + count]
            cores = [re.sub("['’]s$", "", _EDGES.sub("", token)) for token in piece]
            if len(piece) < count:
                continue
            if count == 2 and not (piece[0][-1:].isalnum() and (
                    all(_part_of_a_name(tokens, at + n, lexicon) for n in range(count))
                    or (piece[-1][:1].isalnum() and _joined_made_up(cores, lexicon)))):
                # (Two words with nothing between them: a comma or a stop there ends a
                # clause or a sentence, and "John. Tea" is no "Jonti".)
                continue
            word = keys.get(sound_key(" ".join(_key(token) for token in piece)))
            if word is None and count == 1 and _made_up(cores[0], lexicon):
                word = near.get(_near(sound_key(cores[0])))
            if word and (" ".join(cores) != word or _key(" ".join(piece)) != _key(word)):
                lead = re.match(r"\W*", piece[0]).group()       # the bracket before it stays,
                tail = re.search(r"(?:['’]s)?[^\w']*$", piece[-1]).group()  # the comma after
                following = tokens[at + count][:1] if at + count < len(tokens) else ""
                if count == 2 and len(cores[-1]) == 1 and tail[:1] == "." and following.islower():
                    tail = tail[1:]  # "John E. yesterday": the stop was the initial's
                out.append(lead + word + tail)
                at += count
                found = True
                break
        else:
            out.append(tokens[at])
            at += 1
    return settle(" ".join(out), text, before, words, lexicon, names_only=True) if found else text


def settle(hinted: str, plain: str, before: str, words, lexicon: Lexicon | None = None,
           names_only: bool = False) -> str:
    """One phrase from two hearings of it: `hinted` with the words given, `plain` without.

    `before` is the text before the cursor. With `names_only`, a word of theirs stands
    only where the plain hearing has what looks like a name, where it ends what is said
    right after a greeting or sign-off, or where it is all that was said: for when
    `hinted` is not a hearing at all, but `plain` with their words put in by sound.
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
        named = (_looks_like_a_name(p, p1, p2, lexicon)
                 or _joined_like_hinted(p, h, h1, h2, p1, p2, lexicon))
        everyday = all(lexicon.ordinary(key) for key in p_keys[p1:p2] if key)
        # Whether what was said there ends with it: the phrase, or a part with a mark after.
        ends = h2 == len(h) or h[h2 - 1][-1:] in ",.!?;:"
        # "Hi team," and "Thanks, done." A greeting calls for a name, but these are what
        # people say there instead of one, and the commonest words of all. Only the first
        # kind count where the word is all that follows "Dear" or "Hello": there
        # "Dear done," is Dan, though "Hi, can you send it" is still no Khan.
        never = frozenset(ADDRESSED) if ends and _cued(lead, SALUTATIONS) else _NEVER_A_NAME
        if all(key in never for key in p_keys[p1:p2]):
            fits = False
        elif names_only:
            # (By itself: "Johnie." on a line of its own, signing a letter, is Johnny.)
            fits = alone or named or (ends and _cued(lead, GREETINGS))
        else:
            # After a greeting little but a name comes. After "I'm" or "from" all sorts
            # of words do, so there an everyday word stays: "I'm done" is not "I'm Dan".
            fits = alone or named or _cued(lead, GREETINGS) or (_cued(lead) and not everyday)
        if p2 > p1 and fits:
            out += h[h1:h2]
            kept += mine[h1:h2]
        else:
            out += p[p1:p2]
            kept += [False] * (p2 - p1)
    if not any(kept):
        # The hint changed nothing that stood; but the same words may be in the person's
        # own spelling in one hearing and not the other ("DeepSeek" and "deepseek"): that
        # spelling is the truer one — unless the words are everyday ones, which the own
        # word must not take the place of ("I will go" is not "I Will go").
        if any(mine) and hinted.lower() == plain.lower():
            everyday = all(lexicon.ordinary(key) for key in p_keys if key)
            exact = [str(word) for word in words if str(word).strip()]
            in_hinted = any(word in hinted for word in exact)
            in_plain = any(word in plain for word in exact)
            if not everyday and in_hinted and not in_plain:
                return hinted
            return plain
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


def _cued(lead: list, cues=CUES) -> bool:
    """Whether the words just before are ones a name follows."""
    lead = [part for key in lead for part in key.split("-") if part]
    while True:
        said = next((phrase for phrase in SAID if lead[-len(phrase):] == phrase), None)
        if said is None:
            break
        del lead[-len(said):]
    return any(lead[-len(cue):] == cue for cue in cues)


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
                    # The part as it is listed, marks of its own and all (".NET"), in
                    # place of the same letters: with those marks, if they are there
                    # already, so that they are not written twice.
                    there = re.escape(part) + "|" + re.escape(_EDGES.sub("", part))
                    tokens[at + n] = re.sub(there, lambda _: part, tokens[at + n], count=1,
                                            flags=re.IGNORECASE)
    return tokens
