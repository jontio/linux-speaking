"""Dictating C and C++ source code in Visual Studio Code.

Prose rules are no use in code, so in a C or C++ file a different set applies. Symbols
are spoken ("open bracket", "semicolon", "hash include"), everything else is lower case,
and spacing follows the usual C style: "x equals count plus one semicolon" becomes
"x = count + 1;".

It is aware of the file being edited. Names already in the file are recognised when spoken
as words, so "buffer size" becomes buffer_size or bufferSize, whichever the file uses. A new
name of several words is joined in the file's own style. Inside a string, words keep their
spaces, and after "//" ordinary prose dictation takes over.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .formatting import LINE, PARAGRAPH, Insertion

LANGUAGES = ("c", "cpp")

KEYWORDS = frozenset("""
    int char float double void long short unsigned signed bool auto const static struct
    union enum typedef if else for while do switch case default break continue return goto
    sizeof volatile extern register inline true false class public private protected
    virtual override template typename namespace using new delete this nullptr try catch
    throw operator friend explicit constexpr include define ifdef ifndef endif pragma elif
    undef final noexcept mutable static_cast dynamic_cast const_cast reinterpret_cast
""".split())
# After one of these, "star" and "ampersand" mark a pointer or reference: "int *p".
TYPE_WORDS = frozenset(
    "int char float double void long short unsigned signed bool auto const size_t string "
    "struct FILE".split())
# Keywords that stand for a value. After any other keyword, "minus" is a sign: "return -1".
VALUE_KEYWORDS = frozenset("true false this nullptr".split())
# These take a space before an opening bracket: "if (", but "printf(".
SPACE_BEFORE_BRACKET = frozenset("if for while switch return case catch else do".split())
# After one of these, angle brackets hug their contents: "vector<int>".
TEMPLATES = frozenset(
    "vector map set list deque array pair tuple optional function unique_ptr shared_ptr "
    "weak_ptr unordered_map unordered_set basic_string template static_cast dynamic_cast "
    "const_cast reinterpret_cast".split())

SPACE = "\x00space"  # an explicit "space": keeps two names apart


def _table(text: str) -> dict:
    """Parse lines of "spoken phrase | another phrase => symbol"."""
    table = {}
    for line in text.strip().splitlines():
        phrases, symbol = line.rsplit("=>", 1)
        for phrase in phrases.split("|"):
            table[tuple(phrase.split())] = symbol.strip() or " "
    return table


SYMBOLS = _table("""
    open bracket | open paren | open parenthesis | left bracket | left paren => (
    close bracket | close paren | close parenthesis | right bracket | right paren => )
    open brace | open curly | open curly bracket | left brace => {
    close brace | close curly | close curly bracket | right brace => }
    open square | open square bracket | left square | left square bracket => [
    close square | close square bracket | right square | right square bracket => ]
    open angle | open angle bracket | less than | left angle => <
    close angle | close angle bracket | greater than | right angle => >
    less than or equal | less than or equal to | less or equal | less equals => <=
    greater than or equal | greater than or equal to | greater or equal | greater equals => >=
    semicolon | semi colon => ;
    double colon | colon colon => ::
    colon => :
    comma => ,
    dot | period | full stop => .
    hash | hashtag | pound sign => #
    equals | equal | equal sign | equals sign => =
    double equals | equals equals | equal equal | is equal to | equal to => ==
    not equals | not equal | not equal to | bang equals => !=
    plus => +
    minus => -
    times | star | asterisk | multiplied by => *
    slash | forward slash | divided by => /
    double slash | slash slash | comment => //
    backslash | back slash => \\
    percent | percent sign | modulo | mod => %
    ampersand | address of => &
    and and | logical and | double ampersand => &&
    pipe | vertical bar => |
    or or | logical or | double pipe => ||
    caret => ^
    tilde => ~
    bang | exclamation mark | exclamation point | logical not => !
    question mark => ?
    arrow => ->
    plus plus | increment => ++
    minus minus | decrement => --
    plus equals => +=
    minus equals => -=
    times equals | star equals => *=
    slash equals | divide equals => /=
    shift left | left shift => <<
    shift right | right shift => >>
    underscore => _
    quote | double quote | quotes | quotation mark | open quote | close quote => "
    single quote | apostrophe => '
""")
SYMBOLS[("space",)] = SPACE
SYMBOLS[("new", "line")] = LINE
SYMBOLS[("new", "paragraph")] = PARAGRAPH

FORMATTERS = {
    ("camel", "case"): "camel", ("camel",): "camel",
    ("pascal", "case"): "pascal", ("pascal",): "pascal",
    ("snake", "case"): "snake", ("snake",): "snake",
    ("upper", "case"): "upper", ("all", "caps"): "upper", ("constant",): "upper",
    ("no", "space"): "smash", ("one", "word"): "smash",
}

# Names that are said as several words, or that have capitals.
BUILTIN = {
    ("size", "of"): "sizeof", ("null", "pointer"): "nullptr", ("null", "ptr"): "nullptr",
    ("null",): "NULL", ("print", "f"): "printf", ("f", "print", "f"): "fprintf",
    ("s", "print", "f"): "sprintf", ("scan", "f"): "scanf", ("mal", "lock"): "malloc",
    ("c", "out"): "cout", ("see", "out"): "cout", ("c", "in"): "cin", ("see", "in"): "cin",
    ("end", "l"): "endl", ("end", "line"): "endl", ("c", "err"): "cerr",
    ("standard", "io"): "stdio", ("std", "io"): "stdio", ("standard", "lib"): "stdlib",
    ("std", "lib"): "stdlib", ("io", "stream"): "iostream", ("i", "o", "stream"): "iostream",
    ("size", "t"): "size_t", ("arg", "c"): "argc", ("arg", "v"): "argv",
    ("str", "len"): "strlen", ("str", "copy"): "strcpy", ("str", "cmp"): "strcmp",
    ("mem", "copy"): "memcpy", ("mem", "set"): "memset", ("file",): "FILE",
    ("static", "cast"): "static_cast", ("dynamic", "cast"): "dynamic_cast",
    ("const", "cast"): "const_cast", ("reinterpret", "cast"): "reinterpret_cast",
    ("unique", "pointer"): "unique_ptr", ("unique", "ptr"): "unique_ptr",
    ("shared", "pointer"): "shared_ptr", ("shared", "ptr"): "shared_ptr",
    ("unordered", "map"): "unordered_map", ("unordered", "set"): "unordered_set",
    ("if", "def"): "ifdef", ("if", "n", "def"): "ifndef", ("if", "not", "def"): "ifndef",
    ("end", "if"): "endif",
}
for _bits in ("8", "16", "32", "64"):
    BUILTIN[("u", "int", _bits, "t")] = BUILTIN[("uint", _bits, "t")] = f"uint{_bits}_t"
    BUILTIN[("int", _bits, "t")] = f"int{_bits}_t"

_UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
          "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
NUMBER_WORDS = {w: i for i, w in enumerate(_UNITS)}
NUMBER_WORDS.update({w: 20 + 10 * i for i, w in enumerate(_TENS)})

# After a backslash, the letter of an escape, and the ways Whisper hears it said.
ESCAPES = {"n": "n", "en": "n", "and": "n", "in": "n", "end": "n", "an": "n", "int": "n",
           "ent": "n", "inn": "n", "hen": "n", "ann": "n", "on": "n", "then": "n",
           "t": "t", "tee": "t", "tea": "t", "tab": "t", "r": "r", "are": "r", "our": "r",
           "zero": "0", "0": "0", "oh": "0", "o": "0", "null": "0"}


def escape_letter(tok: str, in_string: bool) -> str | None:
    """The escape meant by the word after a backslash. In a string anything else would be
    an error, so a short word with an "n" in it is taken for the commonest one, \\n."""
    if tok in ESCAPES:
        return ESCAPES[tok]
    if in_string and tok.isalpha() and len(tok) <= 4 and "n" in tok:
        return "n"
    return None

# A single letter said on its own, as the recogniser tends to write it.
LETTER_NAMES = {"ay": "a", "bee": "b", "cee": "c", "see": "c", "sea": "c", "dee": "d", "ee": "e",
                "eff": "f", "gee": "g", "aitch": "h", "eye": "i", "jay": "j", "kay": "k",
                "el": "l", "em": "m", "en": "n", "oh": "o", "pee": "p", "pea": "p",
                "queue": "q", "cue": "q", "are": "r", "ar": "r", "ess": "s", "tee": "t",
                "tea": "t", "you": "u", "vee": "v", "ex": "x", "why": "y", "zed": "z",
                "zee": "z"}

# ---- judging by where the cursor is ------------------------------------------------------
# Words the recogniser writes for a keyword, taken as the keyword at the start of a statement.
AT_START = {"four": "for", "fore": "for", "4": "for", "wile": "while", "wild": "while", "els": "else",
            "avoid": "void", "car": "char", "chore": "char", "bull": "bool", "flote": "float",
            "returned": "return", "returns": "return", "brake": "break", "struck": "struct",
            "strict": "struct", "in": "int", "inn": "int", "ent": "int"}
# Words taken as a number where a value is expected, such as after "=" or "times".
AS_NUMBER = {"to": "2", "too": "2", "for": "4", "fore": "4", "won": "1", "ate": "8",
             "tree": "3", "free": "3", "oh": "0"}
COMPARISONS = frozenset("< > <= >= == !=".split())
# After one of these a value is expected.
VALUE_AFTER = frozenset(
    "= == != <= >= < > + - * / % && || ( , [ += -= *= /= << >> ? : ! & | ^".split())
# After one of these the next name is being declared, so it is new: never corrected.
DECLARING = frozenset("struct class enum union namespace define typedef typename using goto".split())
# Phrases for brackets, matched loosely: "open racket" is "open bracket".
LOOSE = {"open bracket": "(", "close bracket": ")", "open brace": "{", "close brace": "}",
         "open square": "[", "close square": "]", "open angle": "<", "close angle": ">",
         "semi colon": ";"}
SNAP = 0.86  # how alike a misheard name must be to a real one to be corrected to it


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def sound(word: str) -> str:
    """A rough spelling of how a word sounds, so "sighs" and "size" come out the same."""
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    for old, new in (("ph", "f"), ("gh", ""), ("ck", "k"), ("qu", "kw"), ("x", "ks"),
                     ("z", "s"), ("c", "k"), ("y", "i")):
        w = w.replace(old, new)
    w = w[:1] + re.sub(r"[aeiouhw]", "", w[1:])
    return re.sub(r"(.)\1+", r"\1", w)


def alike(said: str, name: str) -> float:
    """How likely `said`, as written by the recogniser, is the name `name`: 0 to 1."""
    words = "".join(spoken(name))
    said = said.lower()
    if said == words:
        return 1.0
    score = (_ratio(said, words) + _ratio(sound(said), sound(words))) / 2
    if 3 <= len(words) < len(said) and words[0] == said[0]:
        letters = iter(said)
        if all(c in letters for c in words):  # an abbreviation: "ptr" for "pointer"
            score = max(score, 0.88)
    return score


def snap(words: list, candidates) -> str | None:
    """The one name in `candidates` that the said words clearly sound like, or None."""
    said = "".join(words)
    scored = sorted(((alike(said, c), c) for c in candidates), reverse=True)[:2]
    if not scored or scored[0][0] < SNAP:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.04:
        return None  # two names fit about equally well: leave it alone
    return scored[0][1]


def loose_symbol(first: str, second: str) -> str | None:
    """The bracket two words were probably meant to be, if they nearly spell its name."""
    if max(_ratio(first, "open"), _ratio(first, "close"), _ratio(first, "semi")) < 0.6:
        return None
    best = max(LOOSE, key=lambda phrase: _ratio(first + " " + second, phrase))
    return LOOSE[best] if _ratio(first + " " + second, best) >= 0.8 else None


def position(items: list, before: str) -> str:
    """Where the next word falls: "start" of a statement, where a "value" is expected,
    or "" for anywhere else."""
    if not items:
        tail = before.rstrip()
        if not tail or tail[-1] in "{};":
            return "start"
        if re.search(r"(?:\b(?:return|case)|[=(,\[+\-*/%<>&|!?:^])$", tail):
            return "value"
        return ""
    kind, text = items[-1]
    if kind == "break" or (kind == "op" and text in "{};"):
        return "start"
    if (kind == "op" and text in VALUE_AFTER) or (kind == "id" and text in ("return", "case")):
        return "value"
    return ""


def declaring(items: list, before: str, types=()) -> bool:
    """True if the next name is being introduced, as after "int" or "struct"."""
    words = [text for kind, text in items if kind != "space"]
    if not words:
        words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[^\sA-Za-z0-9_]", before)
    while words and words[-1] in ("*", "&"):
        words.pop()
    return bool(words) and (words[-1] in TYPE_WORDS or words[-1] in DECLARING
                            or words[-1] in types or words[-1].endswith("_t"))


# What Whisper is told it is hearing: spoken code, in words, so that it writes words.
PROMPT = ("hash include open angle stdio dot h close angle new line int main open bracket "
          "close bracket open brace new line int count equals zero semicolon new line "
          "print f open bracket quote hello quote close bracket semicolon")

_TOKEN = re.compile(
    r"\d+\.\d+|\d+[a-z0-9_]*|[a-z_][a-z0-9_]*(?:\.[a-z0-9_]+)*"
    r"|<<=|>>=|==|!=|<=|>=|&&|\|\||->|::|\+\+|--|\+=|-=|\*=|/=|<<|>>|//"
    r"|[=+\-*/<>()\[\]{}#&|%^~\"\;:" + LINE + PARAGRAPH + "]")


# Ways Whisper writes the symbol words that mean the same thing.
ALIASES = {"brackets": "bracket", "braces": "brace", "parens": "paren", "curlies": "curly",
           "parentheses": "parenthesis", "semicolons": "semicolon", "colons": "colon",
           "openbracket": "open bracket", "closebracket": "close bracket",
           "openbrace": "open brace", "closebrace": "close brace",
           "openangle": "open angle", "closeangle": "close angle",
           "newline": "new line", "plusplus": "plus plus", "minusminus": "minus minus"}


def tokens(raw: str) -> list:
    """Whisper's text as lower-case words and symbols, without its prose punctuation.

    Commas, full stops and the like are dropped, because in code they have to be spoken.
    A dot inside a name, as in "stdio.h" or "3.14", is kept.
    """
    s = raw.lower().replace("’", "'")
    s = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", s)        # "semi-colon"
    s = re.sub(r"(?<=[a-z])'(?=[a-z])", "", s)         # "don't"
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)            # "1,000"
    s = re.sub(r"\.(?![a-z0-9_])|(?<![a-z0-9_])\.", " ", s)
    s = re.sub(r"[,?!']", " ", s)
    out = []
    for token in _TOKEN.findall(s):
        if token in ALIASES:
            out += ALIASES[token].split()
        elif "." in token and not token[0].isdigit():   # "stdio.h" is three tokens
            parts = token.split(".")
            for i, part in enumerate(parts):
                out += ([part] if i == 0 else [".", part])
        else:
            out.append(token)
    return out


# ---- names in the file -----------------------------------------------------------------
def spoken(name: str) -> tuple:
    """A name as the words someone would say: "bufferSize" and "buffer_size" both give
    ("buffer", "size")."""
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name.replace("_", " "))
    parts = re.sub(r"([A-Za-z])(\d)|(\d)([A-Za-z])", lambda m: (
        m.group(1) + " " + m.group(2) if m.group(1) else m.group(3) + " " + m.group(4)), parts)
    return tuple(parts.lower().split())


def reserved(name: str) -> bool:
    """True for names that belong to the compiler, such as __LINE__ and _Nonnull. A language
    server lists them as in scope, but nobody means them when they say "line"."""
    return name.startswith("__") or (name[:1] == "_" and name[1:2].isupper())


def known_names(names) -> dict:
    """Spoken words -> the name to write, for the names in the file plus common ones.

    `names` should be nearest first: the first name seen for a set of words wins.
    """
    known = {}
    for name in names:
        words = spoken(name)
        if words and name.lower() not in KEYWORDS:
            known.setdefault(words, name)
            known.setdefault((name.lower(),), name)  # in case Whisper writes it as one word
    for words, name in BUILTIN.items():
        known.setdefault(words, name)
    return known


def name_style(names) -> str:
    """Whether the file joins words like_this or likeThis. Like_this if there is no telling."""
    snake = sum(1 for n in names if re.search(r"[a-z0-9]_[a-z0-9]", n))
    camel = sum(1 for n in names if re.search(r"[a-z][A-Z]", n) and "_" not in n)
    return "camel" if camel > snake else "snake"


def join(words: list, style: str) -> str:
    if style == "camel":
        return words[0] + "".join(w[:1].upper() + w[1:] for w in words[1:])
    if style == "pascal":
        return "".join(w[:1].upper() + w[1:] for w in words)
    if style == "upper":
        return "_".join(words).upper()
    if style == "smash":
        return "".join(words)
    return "_".join(words)


# ---- from words to code items -----------------------------------------------------------
def _longest(table: dict, toks: list, at: int, least: int = 1):
    """The longest entry of `table` that matches the tokens at `at`."""
    for size in range(min(6, len(toks) - at), least - 1, -1):
        found = table.get(tuple(toks[at:at + size]))
        if found is not None:
            return size, found
    return 0, None


def parse(toks: list, known: dict, style: str, in_string: bool = False,
          before: str = "", scope=None) -> list:
    """Turn tokens into (kind, text) items: "id" for names, keywords and numbers, "op" for
    symbols, "text" for words inside a string, "space" and "break".

    `scope` is what the language server says is in scope at the cursor, as name -> kind.
    With it, a word that is not a name here but sounds like one that is gets corrected.
    """
    scope = scope or {}
    real = [n for n, kind in scope.items() if kind in ("variable", "function", "type", "namespace")]
    types = {n for n, kind in scope.items() if kind == "type"}
    items = []
    run = []          # plain words that may be one name
    wanted = None     # a case style asked for, for the next name
    capital = False

    def candidates():
        # Where a value is expected, a type name is not what was meant.
        if position(items, before) == "value":
            return [n for n in real if scope[n] != "type"]
        return real

    def flush():
        nonlocal wanted
        if not run:
            return
        if wanted:
            items.append(("id", join(run, wanted)))
        elif (real and not all((w.lower(),) in known for w in run)
                and not declaring(items, before, types) and snap(run, candidates())):
            # Not a name here, but it sounds like one that is: that is what was meant.
            items.append(("id", snap(run, candidates())))
        elif len(run) == 1 or all((w.lower(),) in known for w in run):
            # Separate things that are each already known, such as two variables.
            items.extend(("id", known.get((w.lower(),), w)) for w in run)
        else:
            items.append(("id", join(run, style)))
        run.clear()
        wanted = None

    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "literal" and i + 1 < len(toks):  # "literal comma" is the word itself
            run.append(toks[i + 1])
            i += 2
            continue
        if tok in ("capital", "cap") and i + 1 < len(toks) and toks[i + 1].isalpha():
            capital = True
            i += 1
            continue
        if items and items[-1] == ("op", "\\"):
            letter = escape_letter(tok, in_string)
            if letter:
                items.append(("esc", letter))        # "backslash n"
                i += 1
                continue
            size, symbol = _longest(SYMBOLS, toks, i)
            if in_string and symbol == '"':
                items.append(("esc", '"'))           # an escaped quote: the string goes on
                i += size
                continue
        size, symbol = _longest(SYMBOLS, toks, i)
        if in_string and symbol == LINE:
            # A string can't hold a real line break, so "new line" here means the escape.
            items += [("op", "\\"), ("esc", "n")]
            i += size
            continue
        if in_string and tok == "tab":
            items += [("op", "\\"), ("esc", "t")]
            i += 1
            continue
        if not size and not tok[0].isalnum() and tok[0] != "_":
            size, symbol = 1, tok                    # a symbol Whisper wrote itself
        if size:
            flush()
            if symbol == SPACE:
                items.append(("space", " "))
            elif symbol in (LINE, PARAGRAPH):
                items.append(("break", symbol))
            elif symbol == "//" and not in_string:
                # The rest of the phrase is the comment: ordinary words, not code.
                rest = " ".join(toks[i + size:])
                items.append(("op", "//"))
                if rest:
                    items.append(("text", rest[:1].upper() + rest[1:]))
                return items
            else:
                if symbol == '"':
                    in_string = not in_string
                items.append(("op", symbol))
            i += size
            continue
        word = tok.capitalize() if capital else tok
        capital = False
        if (not in_string and not wanted and tok == "is" and ("is",) not in known
                and i + 1 < len(toks)):
            # "i is less than ten": the "is" is how people talk, not part of the code.
            size, symbol = _longest(SYMBOLS, toks, i + 1)
            if symbol in COMPARISONS or toks[i + 1] in COMPARISONS:
                i += 1
                continue
        if (not in_string and not wanted and not run and (tok.isalpha() or tok == "4")
                and (tok,) not in known):
            where_now = position(items, before)
            following = toks[i + 1] if i + 1 < len(toks) else ""
            if where_now == "start" and tok in AT_START and (
                    AT_START[tok] != "int" or following.isalpha()):
                items.append(("id", AT_START[tok]))  # "four open bracket" is "for ("
                i += 1
                continue
            if where_now == "value" and tok in AS_NUMBER:
                items.append(("id", AS_NUMBER[tok]))  # "x times to" is "x * 2"
                i += 1
                continue
        if (not in_string and not wanted and i + 1 < len(toks) and tok.isalpha()
                and toks[i + 1].isalpha() and (tok,) not in known and tok not in KEYWORDS):
            symbol = loose_symbol(tok, toks[i + 1])
            if symbol:                               # "open racket"
                flush()
                items.append(("op", symbol))
                i += 2
                continue
        if in_string:                                # words in a string are just words
            items.append(("text", word))
            i += 1
            continue
        if not wanted and not run:
            size, style_name = _longest(FORMATTERS, toks, i)
            if size and i + size < len(toks):
                wanted = style_name
                i += size
                continue
        if not wanted:
            size, name = _longest(known, toks, i, least=2)   # a name said as several words
            if size:
                flush()
                items.append(("id", name))
                i += size
                continue
            if tok in NUMBER_WORDS:
                value = NUMBER_WORDS[tok]
                if value >= 20 and i + 1 < len(toks) and 0 < NUMBER_WORDS.get(toks[i + 1], 0) < 10:
                    value += NUMBER_WORDS[toks[i + 1]]       # "twenty one"
                    i += 1
                flush()
                items.append(("id", str(value)))
                i += 1
                continue
            if tok in KEYWORDS or tok[0].isdigit():
                flush()
                items.append(("id", tok))
                i += 1
                continue
        if not wanted and not run and known.get((tok,)) in types:
            # A type's name stands alone: what follows it is the thing being declared.
            items.append(("id", known[(tok,)]))
            i += 1
            continue
        run.append(word)
        i += 1
    flush()
    return items


# ---- spacing ----------------------------------------------------------------------------
@dataclass
class _Tok:
    text: str
    kind: str                  # "id", "op" or "text"
    hug_before: bool = False   # no space before it
    hug_after: bool = False    # no space after it
    value: bool = False        # something an operator can follow: a name, ")" and so on


class _State:
    def __init__(self, line: str, in_string: bool):
        self.line = line           # the current line so far, to spot "#include"
        self.in_string = in_string
        self.in_char = False
        self.angle = 0             # open angle brackets that hug their contents
        self.ternary = 0

    @property
    def include(self) -> bool:
        return self.line.lstrip().startswith("#include")


def _is_type(text: str) -> bool:
    return text in TYPE_WORDS or text.endswith("_t")


def _classify(kind: str, text: str, prev: _Tok | None, st: _State) -> _Tok:
    """Decide how a token sits against its neighbours."""
    tok = _Tok(text, kind)
    value_before = prev is not None and prev.value
    if kind == "esc":  # the letter of an escape such as \n: what follows runs straight on
        tok.value, tok.hug_after = True, st.in_string
        return tok
    if st.in_string and not (kind == "op" and text == '"'):
        if kind == "op":
            tok.hug_before = text in ",.;:!?\\"
            # A dot in an included file's name has no space after it: "my_header.h".
            tok.hug_after = text in "\\%" or (text == "." and st.include)
        return tok
    if kind != "op":
        tok.value = text not in KEYWORDS or text in VALUE_KEYWORDS
        tok.hug_before = st.include and st.angle > 0
        return tok
    if text == '"':
        if st.in_string:
            tok.hug_before, tok.value = True, True
        else:
            tok.hug_after = True
        st.in_string = not st.in_string
    elif text == "'":
        if st.in_char:
            tok.hug_before, tok.value = True, True
        else:
            tok.hug_after = True
        st.in_char = not st.in_char
    elif text == "(":
        named = prev is not None and prev.kind == "id"
        tok.hug_before = (named and prev.text not in SPACE_BEFORE_BRACKET) or (
            value_before and not named)
        tok.hug_after = True
    elif text == "[":
        tok.hug_before = value_before or (prev is not None and prev.kind == "id")
        tok.hug_after = True
    elif text in (")", "]"):
        tok.hug_before, tok.value = True, True
    elif text == "}":
        tok.value = True
    elif text in (",", ";"):
        tok.hug_before = True
    elif text == ":":
        if st.ternary:
            st.ternary -= 1
        else:
            tok.hug_before = True
    elif text == "?":
        st.ternary += 1
    elif text in (".", "->", "::"):
        tok.hug_before, tok.hug_after = True, True
    elif text in ("#", "\\"):
        tok.hug_after = True
    elif text in ("!", "~"):
        tok.hug_after = True
    elif text in ("++", "--"):
        if value_before:
            tok.hug_before, tok.value = True, True
        else:
            tok.hug_after = True
    elif text in ("-", "+", "*", "&"):
        pointer = text in "*&" and prev is not None and prev.kind == "id" and _is_type(prev.text)
        if not value_before or pointer:
            tok.hug_after = True  # a sign, a pointer mark or address-of: it belongs to what follows
    elif text == "<":
        if st.include:
            tok.hug_after = True
            st.angle += 1
        elif prev is not None and prev.kind == "id" and prev.text in TEMPLATES:
            tok.hug_before, tok.hug_after = True, True
            st.angle += 1
    elif text == ">" and st.angle:
        st.angle -= 1
        tok.hug_before, tok.value = True, True
    if st.include and st.angle and text != "<":
        tok.hug_before = True
    return tok


_OPERATORS = ("<<=", ">>=", "==", "!=", "<=", ">=", "&&", "||", "->", "::", "++", "--",
              "+=", "-=", "*=", "/=", "<<", ">>")


def _tail(before: str, st: _State) -> _Tok | None:
    """The last token already on the line, as far as spacing is concerned."""
    text = before.rstrip()
    if not text:
        return None
    m = re.search(r"[A-Za-z0-9_]+$", text)
    if m:
        word = m.group(0)
        return _Tok(word, "id", value=word not in KEYWORDS or word in VALUE_KEYWORDS)
    op = next((o for o in _OPERATORS if text.endswith(o)), text[-1])
    if st.in_string and text[-1] in "%\\":
        return _Tok(text[-1], "op", hug_after=True)  # "%d" and "\n" have no space inside
    if op == "<" and st.angle:
        return _Tok(op, "op", hug_after=True)  # an include's or a template's opening bracket
    if op == '"':
        return _Tok(op, "op", hug_after=st.in_string, value=not st.in_string)
    earlier = _tail(text[: -len(op)], st) if op in ("-", "+", "*", "&", "++", "--") else None
    return _classify("op", op, earlier, _State(st.line, False))


# ---- where the cursor is ---------------------------------------------------------------------
def where(before: str) -> tuple:
    """What the cursor is in, from the line so far: ("code", ""), ("string", "") or
    ("comment", the comment's text so far)."""
    stripped = before.lstrip()
    if stripped.startswith(("/*", "*")) and not stripped.startswith("*/"):
        return "comment", stripped.lstrip("/*").lstrip()
    quote = ""
    i = 0
    while i < len(before):
        c = before[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif before.startswith("//", i):
            return "comment", before[i + 2:].lstrip()
        i += 1
    return ("string", "") if quote == '"' else ("code", "")


def prompt(names=(), scope=None) -> str:
    """What to tell Whisper before it hears code: spoken code, and names as words, so that
    it writes them the same way. Names in scope at the cursor come first."""
    near = [n for n, kind in (scope or {}).items()
            if kind in ("variable", "function", "type") and not reserved(n)]
    ordered = list(dict.fromkeys(near[:20] + list(names)))
    said = [" ".join(spoken(n)) for n in ordered[:25]]
    return PROMPT + (" " + " ".join(s for s in said if s) if said else "")


def fit_code(raw: str, before: str, after: str, names=(), scope=None) -> Insertion:
    """Fit one dictated phrase of code between `before` and `after` on the current line.

    `names` are the names already in the file, nearest to the cursor first. `scope`, if
    there is a language server, is what it says is in scope at the cursor: name -> kind.
    """
    names = [n for n in names if not reserved(n)]
    scope = {n: kind for n, kind in (scope or {}).items() if not reserved(n)}
    place, _ = where(before)
    st = _State(before, place == "string")
    known = known_names([n for n, kind in scope.items() if kind != "keyword"] + names)
    toks = tokens(raw)
    if len(toks) == 1 and toks[0] in LETTER_NAMES and (toks[0],) not in known:
        toks = [LETTER_NAMES[toks[0]]]  # one letter said on its own: "dee" is d
    items = parse(toks, known, name_style(names), st.in_string, before, scope)
    if not items:
        return Insertion("")
    # An angle bracket opened earlier on the line, in another phrase, is still open.
    if st.include:
        st.angle = max(0, before.count("<") - before.count(">"))
    elif re.search(r"\w<[^<>;(){}]*$", before):
        st.angle = 1
    prev = _tail(before, st)
    out = []
    delete_before = 0
    forced = False
    last = None
    first = True
    for kind, text in items:
        if kind == "space":
            forced = True
            continue
        if kind == "break":
            out.append(text)
            st.line, st.angle, prev, forced, first, last = "", 0, None, False, False, None
            continue
        tok = _classify(kind, text, prev, st)
        gap = forced or (prev is not None and not prev.hug_after and not tok.hug_before)
        if first and before[-1:].isspace():
            # The line already ends in a space. Something that hugs what is before it,
            # such as ";", takes that space away, unless it is the line's indentation.
            if tok.hug_before and not forced and before.strip():
                delete_before = len(before) - len(before.rstrip(" \t"))
            gap = False
        elif first and not before:
            gap = False
        if gap:
            out.append(" ")
        out.append(text)
        st.line += (" " if gap else "") + text
        prev, last, forced, first = tok, tok, False, False
    if forced:
        out.append(" ")
    elif (last is not None and not last.hug_after and after[:1]
            and (after[0].isalnum() or after[0] == "_")):
        out.append(" ")  # keep it apart from the name that follows
    return Insertion("".join(out), delete_before, 0, False)
