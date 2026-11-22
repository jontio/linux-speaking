"""What the person put right in their samples, noted for the review that decides the words.

Each sample keeps, phrase by phrase, what the recogniser wrote for it, and the text as
the person put it right (see samples.py). What the person changed in the box, one word
for another ("Junty" changed to "Jonti"), is noted here: a witness of what the recogniser
gets wrong for this voice.

It is NOT put in place of what is said. The same sound may be either — "junty" may be a
misspelling of "jaunty", and "chairs" of "cheers" — and only the words around it can say
which was meant, so a noted correction waits for the review that reads the context (and
is shown in the samples window until then). A blanket change would take a word away from
the person for good.

The notes are worked out again from the samples kept whenever one is kept or deleted, so
a sample deleted forgets what it taught. Only the pairs are kept, on this computer, in a
file only its owner can read, beside the samples.
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
    ("meant"): only what the person changed is noted. A sample with no "typed" (kept by an
    earlier version) teaches nothing. Only one word for one word: a pair of two words for
    one, or one for two, is too uncertain to act on later."""
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
    """The pairs noted last time, or {} if there are none that can be read."""
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
