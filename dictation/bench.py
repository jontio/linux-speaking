"""How the three ways of putting full stops do on the person's own samples.

The samples are those kept in the "Record dictation samples" window (samples.py). Each is
typed again as the program would type it, with full stops put each of the three ways it
can put them, and compared with what was meant. This is what the samples window shows
when it is asked, and what scripts/check_punctuation.py prints.
"""
from __future__ import annotations

from . import config, punctuation, samples, sense
from .words import Lexicon

WAYS = (("said", "only where \"full stop\" is said"),
        ("pause", "at every pause"),
        ("words", "where the words show a sentence ended"))
SHORT = {"said": "said", "pause": "at every pause", "words": "where the words decide"}
ERRORS = ("ends_missed", "ends_wrong", "commas_missed", "commas_wrong", "capitals_wrong")


def check(folder: str = "", decider=None, reader=None, lexicon=None,
          with_texts: bool = False, build: bool = True) -> dict:
    """The scores of each way on the samples in `folder`, and the one that did best.
    `decider` (punctuation.WordsDecider) and `reader` (sense.Reader) are made here if not
    given and `build` is set; where they can't be, "words" falls back as the program
    would, and "model" in the result is False. `with_texts` adds each sample's typing each
    way, for showing."""
    folder = folder or samples.FOLDER
    kept = samples.kept(folder)
    if build:
        if decider is None and punctuation.installed(config.HELPER_MODEL_DIR):
            try:
                decider = punctuation.WordsDecider(punctuation.Model(config.HELPER_MODEL_DIR))
            except Exception:
                decider = None
        if reader is None and config.MAKE_SENSE and sense.installed(config.HELPER_MODEL_DIR):
            try:
                reader = sense.Reader(sense.Scorer(config.HELPER_MODEL_DIR))
            except Exception:
                reader = None
    lexicon = lexicon or Lexicon.load_default()
    totals = {way: {} for way in SHORT}
    texts, phrases = [], 0
    for here, record in kept:
        written = [p["written"] for p in record.get("phrases", [])]
        phrases += len(written)
        meant = record.get("meant", "")
        typed_ways = {}
        for way in SHORT:
            typed = samples.replay(written, way, decider if way == "words" else None,
                                   lexicon=lexicon, reader=reader)
            found = samples.score(typed, meant)
            for key, value in found.items():
                totals[way][key] = totals[way].get(key, 0) + value
            typed_ways[way] = typed
        if with_texts:
            texts.append((here, meant, typed_ways))
    ways = {}
    for way in SHORT:
        t = totals[way]
        errors = sum(t.get(key, 0) for key in ERRORS)
        ways[way] = {key: t.get(key, 0) for key in
                     ("words", "misheard", "ends_right", "ends_missed", "ends_wrong",
                      "commas_right", "commas_missed", "commas_wrong", "capitals_wrong")}
        ways[way].update({"errors": errors,
                          "per_100": round(100.0 * errors / max(1, t.get("words", 0)), 1)})
    best = ""
    if kept:
        # A way whose typing was taken back to nothing scores no errors at all (its words
        # come out as "misheard", which are left out): it is no winner.
        fitting = [way for way in SHORT
                   if not (ways[way]["words"] and ways[way]["misheard"] >= ways[way]["words"])]
        scored = sorted(fitting, key=lambda way: ways[way]["errors"])
        if len(scored) == 1 or (len(scored) > 1
                                and ways[scored[0]]["errors"] < ways[scored[1]]["errors"]):
            best = scored[0] if scored else ""   # a tie is no telling
    result = {"samples": len(kept), "phrases": phrases,
              "words": totals["said"].get("words", 0),
              "misheard": totals["said"].get("misheard", 0),
              "ways": ways, "best": best, "model": decider is not None}
    if with_texts:
        result["texts"] = texts
    return result
