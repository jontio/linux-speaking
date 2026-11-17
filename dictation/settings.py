"""Which voice commands and punctuation words are switched on.

The tray's Settings window edits this. It is saved as JSON and read by the engine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import config, models, opinions, training

PATH = config.SETTINGS_FILE


@dataclass(frozen=True)
class Item:
    key: str            # a command name, or "say:<word>" for punctuation
    label: str          # what you say
    group: str
    default: bool = True
    phrases: tuple = ()  # for punctuation: the spoken phrases this switches


ITEMS = (
    Item("speech_only", "Leave out sounds that aren't speech  (Parakeet can write a rustle "
         "or a key press as \"yeah\")", "Hearing"),
    Item("quick_listening", "Quicker recognition: listen to only as much sound as the phrase "
         "needs  (a phrase that goes wrong is done again the usual way)", "Speed",
         default=False),
    Item("second_opinions", "Second opinions: each phrase is also heard by Small, and by Medium "
         "where the two differ  (a trial: a little more accurate, slower)", "Speed",
         default=False),
    Item("short_wake", "Wake, sleep  (the one word, said by itself, does as \"wake up\" or "
         "\"go to sleep\", which still work)", "Waking and sleeping", default=False),
    Item("scratch", "Scratch that", "Editing"),
    Item("undo", "Undo that", "Editing"),
    Item("delete", "Delete that", "Editing"),
    Item("delete_words", "Delete last word  (or \"delete last 3 words\")", "Editing"),
    Item("spell", "Spell that  (opens a box to spell a word letter by letter)", "Editing"),
    Item("tab", "Tab  (the Tab key)", "Editing"),
    Item("space", "Space  (the space bar; or \"space 3\")", "Editing"),
    Item("backspace", "Backspace  (or \"backspace 3\")", "Editing"),
    Item("new_paragraph", "New paragraph", "Line breaks", phrases=("new paragraph",)),
    Item("new_line", "New line", "Line breaks", phrases=("new line",)),
    Item("press_enter", "Press enter", "Line breaks"),
    Item("enter", "Enter  (the one word, said by itself, presses Enter)", "Line breaks",
         default=False),
    Item("line_end", "Go to end of line", "Moving the cursor"),
    Item("line_start", "Go to start of line", "Moving the cursor"),
    Item("word_left", "Move left 3 words  (or \"move back a word\")", "Moving the cursor"),
    Item("word_right", "Move right 3 words  (or \"move forward a word\")", "Moving the cursor"),
    Item("para_end", "Go to end of paragraph", "Moving the cursor"),
    Item("para_start", "Go to start of paragraph", "Moving the cursor"),
    Item("doc_top", "Go to top", "Moving the cursor"),
    Item("doc_end", "Go to bottom", "Moving the cursor"),
    Item("line_up", "Up 3 lines  (or \"up one line\")", "Lines"),
    Item("line_down", "Down 3 lines  (or \"down one line\")", "Lines"),
    Item("go_to_line", "Go to line 42  (VS Code, Kate)", "Lines"),
    Item("select_line", "Select line", "Lines"),
    Item("delete_line", "Delete line  (or \"delete 3 lines\")", "Lines"),
    Item("duplicate_line", "Duplicate line  (VS Code)", "Lines"),
    Item("indent", "Indent  (VS Code)", "Lines"),
    Item("outdent", "Outdent  (VS Code)", "Lines"),
    Item("comment_line", "Comment line, uncomment line  (VS Code)", "Lines"),
    Item("select", "Select <words>", "Selecting"),
    Item("choose_numbers", "Show numbers to choose from when several places match",
         "Selecting"),
    Item("select_all", "Select all", "Selecting"),
    Item("select_last", "Select that  (or \"correct that\")", "Selecting"),
    Item("unselect", "Unselect that", "Selecting"),
    Item("cap", "Cap that", "Formatting"),
    Item("all_caps", "All caps that", "Formatting"),
    Item("no_caps", "No caps that", "Formatting"),
    Item("bold", "Bold that", "Formatting"),
    Item("italic", "Italicize that", "Formatting"),
    Item("underline", "Underline that", "Formatting"),
    Item("other_apps", "Dictate into other programs' text boxes  (switches desktop "
         "accessibility on)", "Other programs", default=False),
    Item("vscode_cpp", "VS Code C/C++ coding commands  (in .c, .cpp, .h and .hpp files)",
         "Programming"),
    Item("numpad_plus", "Number pad + switches dictation between off and awake  (the key "
         "then no longer types a plus)", "Keyboard"),
    Item("no_greeting_comma", "No comma after Hello or Hi  (\"Hello Bob\", not "
         "\"Hello, Bob\")", "Punctuation"),
    Item("say:full stop", "Full stop  .", "Punctuation", phrases=("full stop",)),
    Item("say:period", "Period  .", "Punctuation", default=False, phrases=("period",)),
    Item("say:comma", "Comma  ,", "Punctuation", phrases=("comma",)),
    Item("say:question mark", "Question mark  ?", "Punctuation", phrases=("question mark",)),
    Item("say:exclamation mark", "Exclamation mark / point  !", "Punctuation",
         phrases=("exclamation mark", "exclamation point")),
    Item("say:colon", "Colon  :", "Punctuation", phrases=("colon",)),
    Item("say:semicolon", "Semicolon  ;", "Punctuation", phrases=("semicolon", "semi colon")),
    Item("say:hyphen", "Hyphen  -", "Punctuation", phrases=("hyphen",)),
    Item("say:ellipsis", "Ellipsis  …", "Punctuation", phrases=("ellipsis",)),
    Item("say:brackets", "Open bracket / close bracket  ( )", "Punctuation",
         phrases=("open bracket", "close bracket")),
    Item("say:quotes", "Open quote / close quote  “ ”", "Punctuation",
         phrases=("open quote", "close quote")),
)
BY_KEY = {item.key: item for item in ITEMS}
OPTIONS = frozenset({"choose_numbers", "vscode_cpp", "other_apps", "numpad_plus",
                     "quick_listening", "second_opinions", "no_greeting_comma",
                     "speech_only"})
WINDOWS_ONLY = frozenset({"numpad_plus"})  # settings that aren't commands


def _remote(saved) -> dict:
    """The other computer that does the listening, with anything missing filled in."""
    saved = saved if isinstance(saved, dict) else {}
    return {"on": bool(saved.get("on", False)), "address": str(saved.get("address", "")).strip(),
            "key": str(saved.get("key", "")).strip(), "model": str(saved.get("model", "")),
            "wake": bool(saved.get("wake", False))}


def _share(saved) -> dict:
    """Whether other computers may use this one's recogniser, and the key they need."""
    saved = saved if isinstance(saved, dict) else {}
    return {"on": bool(saved.get("on", False)), "key": str(saved.get("key", "")).strip()}


class Settings:
    def __init__(self, states: dict | None = None, path: str | None = None, model: str = "",
                 microphone: str = "", words=(), remote=None, share=None, look: str = ""):
        self.states = dict(states or {})
        self.path = path
        self.model = model  # the chosen speech model's folder name, or "" for the default
        self.microphone = microphone  # Windows: the recording device's name, or "" for the default
        self.look = look  # Windows: the look of the Settings window and the menu: see looks.py
        self.words = tuple(words)  # the person's own names and terms: see vocabulary.py
        # Another computer that does the listening, and letting others use this one: see
        # remote.py. Each is a dict; an empty one means it has never been set up.
        self.remote = _remote(remote)
        self.share = _share(share)

    @classmethod
    def load(cls, path: str = PATH) -> "Settings":
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            states, model = saved.get("states", {}), str(saved.get("model", ""))
            microphone = str(saved.get("microphone", ""))
            words = saved.get("words", [])
            words = [str(w) for w in words] if isinstance(words, list) else []
            remote, share = saved.get("remote"), saved.get("share")
            look = str(saved.get("look", ""))
        except (OSError, ValueError, AttributeError):
            states, model, microphone, words, remote, share, look = {}, "", "", [], None, None, ""
        return cls({k: bool(v) for k, v in states.items() if k in BY_KEY}, path, model,
                   microphone, words, remote, share, look)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            saved = {"states": self.states, "model": self.model}
            if self.microphone:
                saved["microphone"] = self.microphone
            if self.words:
                saved["words"] = list(self.words)
            if self.remote["address"] or self.remote["key"]:
                saved["remote"] = self.remote
            if self.share["key"]:
                saved["share"] = self.share
            if self.look:
                saved["look"] = self.look
            json.dump(saved, f, indent=1, sort_keys=True)

    def enabled(self, key: str) -> bool:
        return self.states.get(key, BY_KEY[key].default)

    def set(self, key: str, on: bool) -> None:
        self.states[key] = bool(on)
        self.save()

    def set_model(self, model: str) -> None:
        self.model = model
        self.save()

    def set_microphone(self, microphone: str) -> None:
        self.microphone = microphone
        self.save()

    def set_look(self, look: str) -> None:
        self.look = look
        self.save()

    def set_words(self, words) -> None:
        self.words = tuple(words)
        self.save()

    def set_remote(self, **changes) -> None:
        self.remote = _remote({**self.remote, **changes})
        self.save()

    def set_share(self, **changes) -> None:
        self.share = _share({**self.share, **changes})
        self.save()

    def wake_words(self) -> tuple:
        """What to say to wake it and to send it to sleep: the shortest that will do."""
        return ("wake", "sleep") if self.enabled("short_wake") else ("wake up", "go to sleep")

    def disabled_commands(self) -> frozenset:
        """Names of commands that are switched off."""
        return frozenset(
            i.key for i in ITEMS
            if not i.key.startswith("say:") and i.key not in OPTIONS and not self.enabled(i.key)
        )

    def spoken_off(self) -> list:
        """Spoken phrases that should be typed as ordinary words."""
        return sorted(p for i in ITEMS if not self.enabled(i.key) for p in i.phrases)


# ---- speech models -----------------------------------------------------------------
_SIZES = (  # (text in the folder name, order, description), most specific first
    ("distil_large", 7, "Distil large: most accurate, slow"),
    ("distil-large", 7, "Distil large: most accurate, slow"),
    ("distil_medium", 5, "Distil medium: quicker than Medium"),
    ("distil-medium", 5, "Distil medium: quicker than Medium"),
    ("distil_small", 3, "Distil small: about as quick as Small"),
    ("distil-small", 3, "Distil small: about as quick as Small"),
    ("parakeet-unified", 11, "Parakeet Unified: a newer Parakeet, not Whisper"),
    ("parakeet", 10, "Parakeet: quick and accurate, not Whisper"),
    ("turbo", 8, "Large turbo: quicker than Large"),
    ("large", 9, "Large: most accurate, very slow"),
    ("medium", 6, "Medium: accurate, slow"),
    ("small", 4, "Small: recommended"),
    ("base", 2, "Base: quicker, less accurate"),
    ("tiny", 1, "Tiny: quickest, least accurate"),
)


def model_label(name: str) -> tuple[int, str]:
    """An order and a plain description for a model folder name."""
    low = name.lower()
    for key, order, label in _SIZES:
        if key in low:
            extra = ", many languages" if "multilang" in low else ""
            extra += ", at full precision" if low.endswith("-full") else ""
            return order, f"{label}{extra}  ({name})"
    return 99, name


def available_models(model_dir: str) -> list:
    """(folder name, description) for each speech model in `model_dir`, smallest first."""
    try:
        names = [n for n in os.listdir(model_dir)
                 if models.kind(model_dir, n)
                 and not n.endswith(".part")]  # one still being fetched: see models.py
    except OSError:
        names = []
    # A model retrained here goes by the name it was given: see training.py.
    return [(n, training.label(model_dir, n) or model_label(n)[1])
            for n in sorted(names, key=lambda n: (model_label(n)[0], n))]


def without_effect(chosen: str, remote: dict, model_dir: str) -> dict:
    """{setting: why it would do nothing as things stand}, for Settings to grey those
    out. `chosen` is the model in use on this computer, `remote` the other computer that
    does the listening, if one is set up.

    Most settings are about what is done with the words, whichever model wrote them, and
    are never here. These few are about the listening itself."""
    def parakeet(name: str) -> bool:
        # By its name, too: a model on the other computer can't be looked at from here.
        return "parakeet" in name.lower() or models.kind(model_dir, name) == "transducer"

    there = remote.get("model", "") if remote.get("on") else ""
    found = {}
    if not parakeet(chosen) and not (there and parakeet(there)):
        found["speech_only"] = ("Only Parakeet models write a noise as a word. The model in use is "
                                "a Whisper one, which leaves noises out by itself.")
    if not remote.get("on"):
        # With the listening done on another computer, the opinions are asked for there.
        wanted = opinions.others(chosen)
        missing = [name for name in wanted if not models.kind(model_dir, name)]
        if missing:
            found["second_opinions"] = (
                "The second and third opinions are given by "
                + " and ".join(model_label(name)[1].split(":")[0] for name in wanted)
                + ". Not installed: " + ", ".join(missing)
                + ". \"Install or remove models\" has them.")
    return found
