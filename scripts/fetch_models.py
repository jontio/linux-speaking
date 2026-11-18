"""Fetches the speech models a new install needs, for both installers.

    python scripts/fetch_models.py <the models folder> [name ...]

With no names it fetches Base and Small, the two Whisper models that listening for
"wake up" and the first dictation need. It uses the app's own downloader
(dictation/models.py), the one behind "Install or remove models" in Settings: that
checks the free disk space first, checks each file when it has arrived, carries on from
where it stopped if it is run again, and goes through the system's own proxy and
certificate settings.

It ends with 0 when the models are there, and with 1, having said why, when they aren't.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dictation import models  # noqa: E402

NEEDED = ("base.en", "small.en")

BY_HAND = """
What has arrived so far is kept: run the installer again and it carries on from there.

If this computer can't reach huggingface.co at all (some work networks don't allow it),
the models can be copied in by hand, from another computer or with a web browser. See
"Copying the speech models in by hand" in docs/MODELS.md. They go in:
  {folder}"""


class Progress:
    """One line that counts up, on a terminal; a line every tenth of the way otherwise."""

    def __init__(self, name: str, out=None):
        self.name = name
        self.out = out or sys.stdout
        self.live = bool(getattr(self.out, "isatty", lambda: False)())
        self.shown = -1

    def __call__(self, done: int, total: int) -> None:
        percent = min(100, int(100 * done / total)) if total else 0
        step = percent if self.live else percent - percent % 10
        if step == self.shown:
            return
        self.shown = step
        line = f"  {self.name}: {step}% of {models.size_text(total)}"
        self.out.write("\r" + line + "   " if self.live else line + "\n")
        self.out.flush()

    def end(self) -> None:
        if self.live and self.shown >= 0:
            self.out.write("\n")
            self.out.flush()


def reason(error: Exception) -> str:
    """What went wrong, with what lay behind it if the downloader knew: a certificate
    that a work network swapped in reads very differently from a cable pulled out."""
    cause = error.__cause__
    behind = str(getattr(cause, "reason", "") or cause or "").strip()
    return f"{error}" + (f"\n  (The computer's own words for it: {behind})" if behind else "")


def fetch(folder: str, names=NEEDED, download=models.Download, out=None) -> int:
    out = out or sys.stdout
    for name in names:
        known = models.BY_NAME.get(name)
        if known is None:
            print(f"{name} is not a model this knows where to fetch. The ones it knows: "
                  + ", ".join(sorted(models.BY_NAME)), file=out)
            return 1
        if models.is_installed(folder, name):
            print(f"  {name}: already here", file=out)
            continue
        progress = Progress(name, out)
        try:
            download(known, folder, progress).run()
        except models.Cancelled:
            progress.end()
            print(f"{name}: stopped.", file=out)
            return 1
        except models.Failed as e:
            progress.end()
            print(f"\n{name} could not be downloaded. {reason(e)}", file=out)
            print(BY_HAND.format(folder=folder), file=out)
            return 1
        except KeyboardInterrupt:
            progress.end()
            print(f"\n{name}: stopped. What has arrived is kept, and running this again "
                  "carries on from there.", file=out)
            return 1
        progress.end()
    return 0


def main(args) -> int:
    if not args:
        print(__doc__.strip())
        return 2
    return fetch(os.path.abspath(args[0]), tuple(args[1:]) or NEEDED)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
