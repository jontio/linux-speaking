"""Sums of money, written one way.

A recogniser writes "one hundred and twenty dollars" as "$120" and, a moment later, "a
hundred and fifty dollars" in words: it goes by what it saw most of when it was made, and
"a hundred" was mostly left in words. Dictated text shouldn't change its mind from one
sentence to the next, so a sum of money is always put in figures:

    a hundred and fifty dollars              $150
    twenty dollars and fifty cents           $20.50
    two thousand five hundred dollars        $2,500
    one point five million dollars           $1.5 million
    120 dollars                              $120
    twenty or thirty dollars                 $20 or $30
    a hundred NZ dollars                     NZ$100
    three hundred Australian dollars         AU$300
    a hundred euros                          €100
    a hundred UK pounds                      £100
    twenty pounds sterling and fifty pence   £20.50
    a twenty dollar note                     a $20 note

Only where a whole number stands straight before the money's name. "A few dollars",
"millions of dollars" and "a dollar" are left as they are, and so is "a hundred dollar
bill", where the "a" belongs to the bill.

Pounds are money only where that is said: "UK pounds", "British pounds", "pounds
sterling". "A hundred pounds" by itself is as likely a weight, and is left alone.

Whose dollars is written with two letters, "AU$" and not "A$": at the start of a phrase
a lone "A" is taken for the word and written small, which gave "a$300".
"""
from __future__ import annotations

import re

_UNITS = {word: n for n, word in enumerate(
    "one two three four five six seven eight nine".split(), 1)}
_TEENS = {word: n for n, word in enumerate(
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), 10)}
_TENS = {word: 10 * n for n, word in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
_BIG = {"thousand": 10 ** 3, "million": 10 ** 6, "billion": 10 ** 9}
_WORD = "|".join(list(_UNITS) + list(_TEENS) + list(_TENS) + list(_BIG) + ["hundred", "point"])
_FIGURES = r"\d[\d,]*(?:\.\d+)?"
_PIECE = rf"(?:{_FIGURES}|{_WORD}|and|an?)"
_NUMBER = rf"{_PIECE}(?:[ -]{_PIECE})*"
# Whose dollars, where it was said: the sign then says so too.
_WHOSE = {"us": "US$", "u.s.": "US$", "american": "US$", "nz": "NZ$", "new zealand": "NZ$",
          "kiwi": "NZ$", "australian": "AU$", "aussie": "AU$", "canadian": "CA$",
          "hong kong": "HK$", "singapore": "SG$", "singaporean": "SG$"}
# Pounds are money only where that was said: before the word, or "sterling" after it.
_STERLING = ("uk", "u.k.", "british", "english")
_SIGNS = {"dollar": "$", "euro": "€", "pound": "£"}
_HUNDREDTHS = {"dollar": ("cent", "cents"), "euro": ("cent", "cents"),
               "pound": ("pence", "penny")}
_SUM = re.compile(
    rf"(?<![\w$€£-])(?:(?P<first>{_NUMBER}) (?P<link>or|to) )?(?P<number>{_NUMBER})[ -]"
    rf"(?P<whose>(?:{'|'.join(re.escape(w) for w in (*_WHOSE, *_STERLING))}) )?"
    rf"(?P<unit>dollars?|euros?|pounds?)\b(?P<sterling> sterling\b)?"
    rf"(?: and (?P<cents>{_NUMBER}) (?P<small>cents?|pence|penny)\b)?",
    re.IGNORECASE)
_AMOUNT = r"\d[\d,]*(?:\.\d+)?(?: (?:thousand|million|billion))?"
# "$120 dollars", as is now and then written: and "$100 Australian dollars", "£20 sterling".
_DOUBLED = re.compile(
    rf"\$(?P<dollars>{_AMOUNT}) (?P<whose>(?:{'|'.join(re.escape(w) for w in _WHOSE)}) )?dollars?\b"
    rf"|(?P<euros>€{_AMOUNT}) euros?\b"
    rf"|(?P<pounds>£{_AMOUNT}) (?:(?:(?:{'|'.join(re.escape(w) for w in _STERLING)}) )?pounds?\b"
    rf"(?: sterling\b)?|sterling\b)",
    re.IGNORECASE)


def _under_hundred(words: list, at: int) -> tuple:
    """(how many words, the number) for a number under a hundred at words[at]: (0, 0) if
    there is none."""
    word = words[at] if at < len(words) else ""
    if word in _TENS:
        if words[at + 1:at + 2] and words[at + 1] in _UNITS:
            return 2, _TENS[word] + _UNITS[words[at + 1]]
        return 1, _TENS[word]
    if word in _TEENS:
        return 1, _TEENS[word]
    if word in _UNITS:
        return 1, _UNITS[word]
    return 0, 0


def number(words: list):
    """The number `words` say, all of them: "a hundred and fifty" is 150, "fifteen
    hundred" 1500, "two thousand five hundred" 2500, "one point five million" 1500000.
    Figures count as words of their own: "120", "2,000", "1.5 million". None if the
    words are not one whole number."""
    words = [word.lower() for word in words]
    if not words:
        return None
    if re.fullmatch(_FIGURES, words[0]):
        value = float(words[0].replace(",", ""))
        if len(words) == 1:
            return value
        if len(words) == 2 and words[1] in _BIG:
            return value * _BIG[words[1]]
        return None
    if "point" in words:
        # "One point five million": a few figures after the point, then how big.
        at = words.index("point")
        whole = number(words[:at])
        after = words[at + 1:]
        scale = _BIG.get(after[-1], 1) if after else 1
        digits = after[:-1] if after and after[-1] in _BIG else after
        if whole is None or not digits or not all(d in _UNITS or d == "zero" for d in digits):
            return None
        fraction = "".join(str(_UNITS.get(d, 0)) for d in digits)
        return (whole + float("0." + fraction)) * scale
    total, at = 0, 0
    last = 10 ** 12                       # each part must be smaller than the one before
    while at < len(words):
        if words[at] == "and":
            if at == 0 or at == len(words) - 1:
                return None
            at += 1
            continue
        if words[at] in ("a", "an"):
            # Only as "a hundred", "a thousand", "a million": and only at the very start.
            if at != 0 or words[at + 1:at + 2] not in (["hundred"], ["thousand"], ["million"],
                                                      ["billion"]):
                return None
            count, part = 1, 1
        else:
            count, part = _under_hundred(words, at)
            if not count:
                return None
        at += count
        if words[at:at + 1] == ["hundred"]:
            part *= 100
            at += 1
            more = at + (words[at:at + 1] == ["and"])
            count, rest = _under_hundred(words, more)
            if count:
                part, at = part + rest, more + count
        scale = 1
        if words[at:at + 1] and words[at] in _BIG:
            scale = _BIG[words[at]]
            at += 1
        if scale >= last or (scale == 1 and last == 1):
            return None                   # "two thousand five thousand", "twenty thirty"
        total, last = total + part * scale, scale
    return float(total) if total else None


def _written(value: float, cents: int = 0) -> str:
    """A sum in figures, without its sign: 150, 2,500, 20.50, 1.5 million."""
    if not cents:
        for name in ("billion", "million"):
            scale = _BIG[name]
            if value >= scale and (value * 10) % scale == 0:   # a round number of tenths
                return f"{value / scale:g} {name}"
    if cents or value != int(value):
        return f"{value + cents / 100:,.2f}"
    return f"{int(value):,}"


_SCALES = dict(_BIG, hundred=100)


def _sum(said: list, singular: bool = False):
    """(what stands before the number, the number) for the longest run of words at the
    end of `said` that is a whole number: or None if there is no such run. What stands
    before is kept as it was: "apples and" of "apples and twenty", the "a" of "a twenty
    dollar note"."""
    for start in range(len(said)):
        words = said[start:]
        value = number(words)
        if value is None or (singular and words[0].lower() in ("a", "an")):
            continue
        lead = " ".join(said[:start])
        return (lead + " " if lead else ""), value
    return None


_ALONE = re.compile(rf"\s*({_NUMBER})\s*([.,!?]?)\s*", re.IGNORECASE)


def in_figures(text: str, before: str = "") -> str:
    """`text` with each sum of money that is written in words put in figures: see the top
    of this file. Everything else is as it was.

    `before` is the text that stands before where it will go. Straight after a money
    sign a number by itself is the sum, and goes in figures too: with the 5 of "$5"
    selected, "six" makes "$6" and not "$six"."""
    if before[-1:] in tuple(_SIGNS.values()):
        alone = _ALONE.fullmatch(text)
        value = number(re.split(r"[ -]", alone.group(1))) if alone else None
        if value is not None:
            return _written(value) + alone.group(2)
    low = text.lower()
    if not any(name in low for name in (*_SIGNS, "sterling")):
        return text

    def one(found) -> str:
        unit = found.group("unit").lower()
        singular = not unit.endswith("s")
        kind = unit.rstrip("s")
        whose = (found.group("whose") or "").strip().lower()
        if kind == "dollar":
            sign = "" if whose in _STERLING or found.group("sterling") else _WHOSE.get(whose, "$")
        elif kind == "pound":
            # Only where it was said to be money: a hundred pounds may be a weight.
            sign = "£" if whose in _STERLING or (found.group("sterling") and not whose) else ""
        else:
            sign = "" if whose or found.group("sterling") else "€"
        cents = found.group("cents")
        if not sign or (cents and found.group("small").lower() not in _HUNDREDTHS[kind]):
            return found.group(0)         # "fifty British dollars", "five dollars and ten pence"
        pence = number(re.split(r"[ -]", cents)) if cents else 0
        if cents and (pence is None or pence != int(pence) or not 0 < pence < 100):
            return found.group(0)
        said = re.split(r"[ -]", found.group("number"))
        made = _sum(said, singular)
        if made is None:
            return found.group(0)
        lead, value = made
        written = sign + _written(value, int(pence or 0))
        if not found.group("first"):
            return lead + written
        # "Twenty or thirty dollars": the first is a sum too, of the same money. And in
        # "two or three hundred dollars" it is of the same hundreds.
        earlier = re.split(r"[ -]", found.group("first"))
        before = None if lead else _sum(earlier)
        if before is None:
            return f"{found.group('first')} {found.group('link')} {lead}{written}"
        shared = 1
        if (len(said) > 1 and said[-1].lower() in _SCALES
                and not any(word.lower() in _SCALES for word in earlier)):
            shared = _SCALES[said[-1].lower()]
        elif len(said) == 1 and len(earlier) == 1 and not pence:
            # And in figures a recogniser writes "two or three hundred" as "2 or 300":
            # the smaller number is of the same hundreds, or thousands.
            scale = 1000 if value % 1000 == 0 else 100 if value % 100 == 0 else 1
            if before[1] == int(before[1]) and before[1] < value / scale < 100:
                shared = scale
        return f"{before[0]}{sign}{_written(before[1] * shared)} {found.group('link')} {written}"

    def once(found) -> str:
        if found.group("dollars"):
            whose = (found.group("whose") or "").strip().lower()
            return _WHOSE.get(whose, "$") + found.group("dollars")
        return found.group("euros") or found.group("pounds")

    return _DOUBLED.sub(once, _SUM.sub(one, text))
