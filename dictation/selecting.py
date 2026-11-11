"""Finding the words for "select ..." near the cursor, like Dragon's Select-and-Say."""
from __future__ import annotations


def _norm_char(c: str) -> str:
    return "'" if c == "’" else c.lower()


def _words(phrase: str) -> list[str]:
    cleaned = "".join(
        _norm_char(c) if (c.isalnum() or c in "'’") else " " for c in phrase
    )
    return cleaned.split()


def find_all(text: str, phrase: str) -> list[tuple[int, int]]:
    """Start and end of every whole-word match for `phrase`, in order.

    Case and punctuation are ignored, so "cat sat" finds "Cat, sat".
    """
    target = _words(phrase)
    if not target:
        return []
    chars: list[str] = []
    index: list[int] = []  # position in `text` of each character in `chars`
    gap = True
    for i, c in enumerate(text):
        if c.isalnum() or c in "'\u2019":
            chars.append(_norm_char(c))
            index.append(i)
            gap = False
        elif not gap:
            chars.append(" ")
            index.append(i)
            gap = True
    flat = "".join(chars)
    needle = " ".join(target)
    found = []
    pos = flat.find(needle)
    while pos >= 0:
        end = pos + len(needle)
        if (pos == 0 or flat[pos - 1] == " ") and (end == len(flat) or flat[end] == " "):
            found.append((index[pos], index[end - 1] + 1))
        pos = flat.find(needle, pos + 1)
    return found


def find_nearest(text: str, caret: int, phrase: str) -> tuple[int, int] | None:
    """Start and end of the match for `phrase` closest to `caret`.

    Only whole words match. On a tie, the match before the cursor wins.
    """
    best = None
    for start, stop in find_all(text, phrase):
        if start <= caret <= stop:
            distance = 0
        elif caret < start:
            distance = start - caret
        else:
            distance = caret - stop
        key = (distance, 0 if stop <= caret else 1)
        if best is None or key < best[0]:
            best = (key, (start, stop))
    return best[1] if best else None
