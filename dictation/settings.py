"""Which voice commands and punctuation words are switched on.

The tray's Settings window edits this. It is saved as JSON and read by the engine.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import config

PATH = config.SETTINGS_FILE


@dataclass(frozen=True)
class Item:
    key: str            # a command name, or "say:<word>" for punctuation
    label: str          # what you say
    group: str
    default: bool = True
    phrases: tuple = ()  # for punctuation: the spoken phrases this switches


ITEMS = (
    Item("scratch", "Scratch that", "Editing"),
    Item("undo", "Undo that", "Editing"),
    Item("delete", "Delete that", "Editing"),
    Item("delete_words", "Delete last word  (or \"delete last 3 words\")", "Editing"),
    Item("spell", "Spell that  (opens a box to spell a word letter by letter)", "Editing"),
    Item("tab", "Tab  (the Tab key)", "Editing"),
    Item("backspace", "Backspace  (or \"backspace 3\")", "Editing"),
    Item("new_paragraph", "New paragraph", "Line breaks", phrases=("new paragraph",)),
    Item("new_line", "New line", "Line breaks", phrases=("new line",)),
    Item("press_enter", "Press enter", "Line breaks"),
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
    Item("select_last", "Select that", "Selecting"),
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
OPTIONS = frozenset({"choose_numbers", "vscode_cpp", "other_apps"})  # settings that aren't commands


class Settings:
    def __init__(self, states: dict | None = None, path: str | None = None, model: str = "",
                 microphone: str = ""):
        self.states = dict(states or {})
        self.path = path
        self.model = model  # the chosen speech model's folder name, or "" for the default
        self.microphone = microphone  # Windows: the recording device's name, or "" for the default

    @classmethod
    def load(cls, path: str = PATH) -> "Settings":
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            states, model = saved.get("states", {}), str(saved.get("model", ""))
            microphone = str(saved.get("microphone", ""))
        except (OSError, ValueError, AttributeError):
            states, model, microphone = {}, "", ""
        return cls({k: bool(v) for k, v in states.items() if k in BY_KEY}, path, model, microphone)

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            saved = {"states": self.states, "model": self.model}
            if self.microphone:
                saved["microphone"] = self.microphone
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
    ("distil_large", 5, "Distil large: most accurate, slow"),
    ("distil-large", 5, "Distil large: most accurate, slow"),
    ("distil_small", 3, "Distil small: about as quick as Small"),
    ("distil-small", 3, "Distil small: about as quick as Small"),
    ("large", 7, "Large: most accurate, very slow"),
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
            return order, f"{label}{extra}  ({name})"
    return 9, name


def available_models(model_dir: str) -> list:
    """(folder name, description) for each speech model in `model_dir`, smallest first."""
    try:
        names = [n for n in os.listdir(model_dir)
                 if os.path.exists(os.path.join(model_dir, n, "model.bin"))]
    except OSError:
        names = []
    return [(n, model_label(n)[1]) for n in sorted(names, key=lambda n: (model_label(n)[0], n))]
