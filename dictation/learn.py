"""Words learned from the samples of real dictation: what the recogniser wrote, and what
the person meant instead.

Each sample keeps, phrase by phrase, what the recogniser wrote for it, and the text as
the person put it right (see samples.py). What is learned is only what the person changed
in the box: the sample keeps the text as the program typed it (tray.SamplesWindow), and
that is compared with the text as the person left it. What the program itself puts right
(sums of money in figures, the sound-alike tidy-up) is no word the recogniser got wrong,
and is never learned. A word put right for another is: "Junty" changed to "Jonti". Pairs
are counted over every sample kept, and one is used only where the form was changed in at
least half the places it was written; one form with two meanings is no telling, and is
left. A sample kept by an earlier version, which did not keep the program's own typing,
teaches nothing.

What is learned is used twice: a phrase said later with the heard form in it has the
learned form put in its place, and the learned forms go to the recogniser as a hint, so
that it hears them better next time. The pairs are worked out again from the samples kept
whenever one is kept or deleted, so a sample deleted forgets what it taught. Nothing but
the pairs is kept, on this computer, in a file only its owner can read, beside the
samples.
"""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

from . import config
from .samples import _for_its_owner, _private

LEARNED = os.path.join(os.path.dirname(config.STATE_FILE), "learned-words.json")
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")


def pairs(kept: list) -> dict:
    """{the form that was on screen, in small letters: the form meant, as it was written}
    from the samples kept (see samples.kept).

    The text the program itself typed ("typed") is compared with the text the person left
    ("meant"): only what the person changed is learned. A sample with no "typed" (kept by
    an earlier version) teaches nothing. Only one word for one word: a pair of two words
    for one, or one for two, is too uncertain to put in place of what will be said later."""
    counts, seen = {}, {}
    for _, record in kept:
        typed = " ".join(str(record.get("typed", "")).split())
        meant = str(record.get("meant", ""))
        if not typed:
            continue                       # (kept before the program's own typing was kept)
        heard_words, wanted_words = _TOKEN.findall(typed), _TOKEN.findall(meant)
        heard = [w.lower() for w in heard_words]
        wanted = [w.lower() for w in wanted_words]
        for word in heard:
            seen[word] = seen.get(word, 0) + 1
        for op, h1, h2, m1, m2 in SequenceMatcher(None, heard, wanted, autojunk=False).get_opcodes():
            if op == "replace" and (h2 - h1) == 1 and (m2 - m1) == 1:
                pair = (heard[h1], wanted[m1])
                if pair[0] != pair[1] and len(pair[0]) > 1 and len(pair[1]) > 1:
                    # (The form meant is kept as it was written: "Junty" was "Jonti".)
                    here = counts.setdefault(pair, [0, wanted_words[m1]])
                    here[0] += 1
    best = {}       # the form on screen: (the form meant as written, how many, its small letters)
    for (heard, wanted), (n, form) in counts.items():
        if n * 2 < seen.get(heard, n):
            continue                       # mostly left as typed: not this voice's slip
        held = best.get(heard)
        if held is None or n > held[1]:
            best[heard] = (form, n, wanted)
        elif n == held[1] and wanted != held[2]:
            best[heard] = (held[0], 0, held[2])   # two meanings for one form: no telling
    return {heard: record[0] for heard, record in best.items() if record[1]}


def load(path: str = LEARNED) -> dict:
    """The pairs learned last time, or {} if there are none that can be read."""
    try:
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return {}
    found = saved.get("pairs") if isinstance(saved, dict) else None
    if not isinstance(found, dict):
        return {}
    return {str(k).lower(): str(v) for k, v in found.items()
            if isinstance(k, str) and isinstance(v, str) and v}


def save(table: dict, path: str = LEARNED) -> None:
    """Write the pairs, only the person's own account able to read them. Raises OSError."""
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    _for_its_owner(folder)
    part = path + ".part"
    try:
        os.remove(part)
    except OSError:
        pass
    try:
        with os.fdopen(_private(part), "w", encoding="utf-8") as f:
            json.dump({"pairs": table}, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())    # (on the disk before it takes the old file's place)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def from_samples(folder: str = "", path: str = LEARNED) -> dict:
    """Work the pairs out again from the samples kept, save them if they have changed, and
    return them."""
    from . import samples
    table = pairs(samples.kept(folder or samples.FOLDER))
    if load(path) != table:
        save(table, path)
    return table


def words(table: dict) -> tuple:
    """The forms the person meant, each once, for the recogniser's hint."""
    seen, out = set(), []
    for wanted in table.values():
        if wanted.lower() not in seen:
            seen.add(wanted.lower())
            out.append(wanted)
    return tuple(out)


def apply(text: str, table: dict) -> str:
    """`text` with each learned form put in place of the form that was on screen, in the
    case it was written: a word that began a sentence keeps its capital, and a possessive
    ('s) stays with it. A form inside a contraction ("don't") is no such word, and stays."""
    if not table or not text:
        return text
    keys = sorted((key for key in table if key), key=len, reverse=True)
    if not keys:
        return text
    pattern = re.compile(r"(?<![^\W_])((?:"
                         + "|".join(re.escape(key) for key in keys)
                         + r"))(['’][sS])?(?![^\W_])(?!['’])", re.IGNORECASE)

    def put(match: re.Match) -> str:
        word, possessive = match.group(1), match.group(2) or ""
        meant = table.get(word.lower())
        if meant is None:
            return match.group()
        word = meant[:1].upper() + meant[1:] if word[:1].isupper() else meant
        return word + possessive
    return pattern.sub(put, text)
