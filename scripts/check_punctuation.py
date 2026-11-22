"""How right the full stops, commas and capitals are in your own dictation samples.

The samples are those kept in the "Record dictation samples" window (Settings): each is
what you dictated, phrase by phrase as the recogniser wrote it, and the text as you put it
right. Each is typed again here, as the program would type it, with full stops put each of
the three ways it can put them (Settings: "Full stops at the ends of phrases"), and compared
with what you meant. Nothing leaves this computer, and the words are not shown unless you
ask (--show).

    python scripts/check_punctuation.py [--show] [--folder PATH]

From the install's own folder, with its own Python:
    Linux:    ~/linux-speaking/venv/bin/python ~/linux-speaking/app/scripts/check_punctuation.py
    Windows:  %USERPROFILE%\\linux-speaking\\venv\\Scripts\\python.exe
              %USERPROFILE%\\linux-speaking\\app\\scripts\\check_punctuation.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dictation import config, punctuation, samples, sense  # noqa: E402
from dictation.words import Lexicon  # noqa: E402

WAYS = (("said", "only where \"full stop\" is said"),
        ("pause", "at every pause"),
        ("words", "where the words show a sentence ended"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--show", action="store_true", help="show each sample as typed each way")
    parser.add_argument("--folder", default=samples.FOLDER, help="where the samples are")
    args = parser.parse_args()
    kept = samples.kept(args.folder)
    if not kept:
        print(f"No samples kept yet in {args.folder}. Record some in Settings: "
              "\"Record dictation samples\".")
        return 1
    decider = None
    if punctuation.installed(config.HELPER_MODEL_DIR):
        try:
            decider = punctuation.WordsDecider(punctuation.Model(config.HELPER_MODEL_DIR))
        except Exception as e:
            print(f"The punctuation model could not be loaded ({type(e).__name__}: {e}): "
                  "\"words\" falls back to the recogniser's own full stops.")
    else:
        print("The punctuation model isn't installed: \"words\" falls back to the recogniser's "
              "own full stops. Choose that way in Settings once, and it is fetched.")
    reader = None
    if not config.MAKE_SENSE:
        pass                              # as the program has it: switched off
    elif sense.installed(config.HELPER_MODEL_DIR):
        try:
            reader = sense.Reader(sense.Scorer(config.HELPER_MODEL_DIR))
        except Exception as e:
            print(f"The model that checks what was heard makes sense could not be loaded "
                  f"({type(e).__name__}: {e}): phrases are typed as heard.")
    else:
        print("The model that checks what was heard makes sense isn't installed: phrases are "
              "typed as heard. Switch dictation on once with \"Put right what was just typed\" "
              "ticked, and it is fetched.")
    lexicon = Lexicon.load_default()
    totals = {way: {} for way, _ in WAYS}
    for here, record in kept:
        written = [p["written"] for p in record.get("phrases", [])]
        meant = record.get("meant", "")
        if args.show:
            print(f"\n== {here}\n   meant: {meant!r}")
        for way, _ in WAYS:
            typed = samples.replay(written, way, decider if way == "words" else None,
                                   lexicon=lexicon, reader=reader)
            found = samples.score(typed, meant)
            for key, value in found.items():
                totals[way][key] = totals[way].get(key, 0) + value
            if args.show:
                print(f"   {way:5}: {typed!r}")
    print(f"\n{len(kept)} samples, {totals['said'].get('words', 0)} words "
          f"({totals['said'].get('misheard', 0)} misheard, which are left out below).\n")
    print(f"{'full stops put':40} {'stops right':>12} {'missed':>7} {'wrong':>6} "
          f"{'commas right':>13} {'missed':>7} {'wrong':>6} {'capitals wrong':>15} {'per 100 words':>14}")
    for way, label in WAYS:
        t = totals[way]
        errors = t["ends_missed"] + t["ends_wrong"] + t["commas_missed"] + t["commas_wrong"] + t["capitals_wrong"]
        per = 100.0 * errors / max(1, t["words"])
        print(f"{label:40} {t['ends_right']:>12} {t['ends_missed']:>7} {t['ends_wrong']:>6} "
              f"{t['commas_right']:>13} {t['commas_missed']:>7} {t['commas_wrong']:>6} "
              f"{t['capitals_wrong']:>15} {per:>14.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
