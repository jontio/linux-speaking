"""Which voice commands and punctuation words are switched on.

The tray's Settings window edits this. It is saved as JSON and read by the engine.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass

from . import actions, config, models, opinions, training

PATH = config.SETTINGS_FILE


@dataclass(frozen=True)
class Item:
    key: str            # a command name, or "say:<word>" for punctuation
    label: str          # its line in Settings: for a command, what you say, in quotes
    group: str
    default: bool = True
    phrases: tuple = ()  # for punctuation: the spoken phrases this switches


ITEMS = (
    Item("speech_only", "Leave out sounds that aren't speech  (Parakeet can write a rustle "
         "or a key press as \"yeah\")", "Hearing"),
    Item("aloud", "Leave out whispering  (only what is said aloud, with the voice, is "
         "written or acted on)", "Hearing", default=False),
    Item("quick_listening", "Quicker recognition with Whisper models  (now and then a phrase "
         "is done twice)", "Speed", default=False),
    Item("second_opinions", "Second opinions: each phrase is heard by two or three models  "
         "(experimental: a little more accurate, slower)", "Speed", default=False),
    Item("short_wake", "\"Wake\", \"sleep\"  (said by themselves; \"wake up\" and \"go to "
         "sleep\" still work)", "Waking and sleeping", default=False),
    Item("noise", "\"That was a noise\"  (takes back what a rustle or a click was written as, "
         "and saves that sound in a folder)", "Hearing", default=False),
    Item("scratch", "\"Scratch that\"", "Editing"),
    Item("undo", "\"Undo that\"", "Editing"),
    Item("redo", "\"Redo that\"", "Editing"),
    Item("delete", "\"Delete that\"", "Editing"),
    Item("delete_words", "\"Delete last word\"  (or \"delete last 3 words\")", "Editing"),
    Item("spell", "\"Spell that\"  (opens a box to spell a word letter by letter)", "Editing"),
    Item("tab", "\"Tab\"  (the Tab key)", "Editing"),
    Item("space", "\"Space\"  (the space bar; or \"space 3\")", "Editing"),
    Item("backspace", "\"Backspace\"  (or \"backspace 3\")", "Editing"),
    Item("new_paragraph", "\"New paragraph\"", "Line breaks", phrases=("new paragraph",)),
    Item("new_line", "\"New line\"", "Line breaks", phrases=("new line",)),
    Item("press_enter", "\"Press enter\"", "Line breaks"),
    Item("enter", "\"Enter\"  (the one word, said by itself, presses Enter)", "Line breaks",
         default=False),
    Item("line_end", "\"Go to end of line\"", "Moving the cursor"),
    Item("line_start", "\"Go to start of line\"", "Moving the cursor"),
    Item("word_left", "\"Move left 3 words\"  (or \"move back a word\")", "Moving the cursor"),
    Item("word_right", "\"Move right 3 words\"  (or \"move forward a word\")", "Moving the cursor"),
    Item("para_end", "\"Go to end of paragraph\"", "Moving the cursor"),
    Item("para_start", "\"Go to start of paragraph\"", "Moving the cursor"),
    Item("doc_top", "\"Go to top\"", "Moving the cursor"),
    Item("doc_end", "\"Go to bottom\"", "Moving the cursor"),
    Item("line_up", "\"Up 3 lines\"  (or \"up one line\")", "Lines"),
    Item("line_down", "\"Down 3 lines\"  (or \"down one line\")", "Lines"),
    Item("go_to_line", "\"Go to line 42\"  (VS Code, Kate, Word)", "Lines"),
    Item("select_line", "\"Select line\"", "Lines"),
    Item("delete_line", "\"Delete line\"  (or \"delete 3 lines\")", "Lines"),
    Item("duplicate_line", "\"Duplicate line\"  (VS Code)", "Lines"),
    Item("indent", "\"Indent\"  (VS Code, Word)", "Lines"),
    Item("outdent", "\"Outdent\"  (VS Code, Word)", "Lines"),
    Item("comment_line", "\"Comment line\", \"uncomment line\"  (VS Code)", "Lines"),
    Item("select", "\"Select\" and the words  (\"select the black cat\")", "Selecting"),
    Item("correct", "\"Correct\" and the words  (as \"select\"; what is said next takes their "
         "place, and the cursor goes back)", "Selecting"),
    Item("choose_numbers", "Show numbers to choose from when several places match",
         "Selecting"),
    Item("select_all", "\"Select all\"", "Selecting"),
    Item("select_last", "\"Select that\"  (or \"correct that\")", "Selecting"),
    Item("unselect", "\"Unselect that\"", "Selecting"),
    Item("cap", "\"Cap that\"", "Formatting"),
    Item("all_caps", "\"All caps that\"", "Formatting"),
    Item("no_caps", "\"No caps that\"", "Formatting"),
    Item("bold", "\"Bold that\"", "Formatting"),
    Item("italic", "\"Italicize that\"", "Formatting"),
    Item("underline", "\"Underline that\"", "Formatting"),
    Item("keep_final", "Keep the full stop or question mark the recogniser writes at the end "
         "of a phrase", "Formatting", default=False),
    Item("money", "Write sums of money as figures  (\"a hundred and fifty dollars\" is "
         "typed as $150)", "Formatting"),
    Item("other_apps", "Dictate into other programs' text boxes  (uses the desktop's "
         "accessibility service)", "Other programs", default=False),
    # The whole of it is shown: what it says in brackets would be moved to its help, and
    # "Click OK" by itself read as one command, not as "click" and whatever is there.
    Item("click", "\"Click\" and the words on a button, link or menu in the window in front",
         "Other programs", default=False),
    Item("vscode_cpp", "VS Code C/C++ coding commands  (in .c, .cpp, .h and .hpp files)",
         "Programming"),
    Item("app", "\"What can I say\", \"open dictation settings\", \"show microphone level\", "
         "\"close that window\"", "This program's windows"),
    Item("commands_only", "Commands only  (nothing you say is typed: only commands are acted "
         "on, the program's and your own)", "My shortcuts and commands", default=False),
    Item("run_programs", "Let my own commands run programs  (the lines with \"run:\" under "
         "My shortcuts and commands)", "My shortcuts and commands", default=False),
    Item("no_greeting_comma", "No comma after Hello or Hi  (\"Hello Bob\", not "
         "\"Hello, Bob\")", "Punctuation"),
    Item("say:full stop", "\"Full stop\"  .", "Punctuation", phrases=("full stop",)),
    Item("say:period", "\"Period\"  .", "Punctuation", default=False, phrases=("period",)),
    Item("say:comma", "\"Comma\"  ,", "Punctuation", phrases=("comma",)),
    Item("say:question mark", "\"Question mark\"  ?", "Punctuation", phrases=("question mark",)),
    Item("say:exclamation mark", "\"Exclamation mark\" / \"exclamation point\"  !", "Punctuation",
         phrases=("exclamation mark", "exclamation point")),
    Item("say:colon", "\"Colon\"  :", "Punctuation", phrases=("colon",)),
    Item("say:semicolon", "\"Semicolon\"  ;", "Punctuation", phrases=("semicolon", "semi colon")),
    Item("say:hyphen", "\"Hyphen\"  -", "Punctuation", phrases=("hyphen",)),
    Item("say:ellipsis", "\"Ellipsis\"  …", "Punctuation", phrases=("ellipsis",)),
    Item("say:brackets", "\"Open bracket\" / \"close bracket\", or \"open paren\" / "
         "\"close paren\"  ( )", "Punctuation",
         phrases=("open bracket", "close bracket", "open paren", "close paren",
                  "open parenthesis", "close parenthesis")),
    Item("say:quotes", "\"Open quote\" / \"close quote\"  “ ”", "Punctuation",
         phrases=("open quote", "close quote")),
    Item("say:quote", "\"Quote\" / \"unquote\"  “ ”", "Punctuation", default=False,
         phrases=("quote", "unquote", "end quote")),
    Item("say:single quotes", "\"Open single quote\" / \"close single quote\"  ‘ ’",
         "Punctuation", phrases=("open single quote", "close single quote")),
    Item("say:square brackets", "\"Open square bracket\" / \"close square bracket\"  [ ]",
         "Punctuation", phrases=("open square bracket", "close square bracket")),
    Item("say:curly brackets", "\"Open curly bracket\" / \"close curly bracket\", or \"open "
         "brace\" / \"close brace\"  { }", "Punctuation",
         phrases=("open curly bracket", "close curly bracket", "open brace", "close brace")),
    Item("say:dash", "\"Dash\"  –", "Punctuation", default=False, phrases=("dash",)),
    Item("say:em dash", "\"Em dash\" / \"en dash\"  — –", "Punctuation",
         phrases=("em dash", "en dash")),
    Item("say:slash", "\"Slash\"  /", "Punctuation", default=False, phrases=("slash",)),
    Item("say:forward slash", "\"Forward slash\" / \"backslash\"  / \\", "Punctuation",
         phrases=("forward slash", "backslash", "back slash")),
    Item("say:apostrophe", "\"Apostrophe\"  '", "Punctuation", phrases=("apostrophe",)),
    Item("say:at sign", "\"At sign\"  @", "Punctuation", phrases=("at sign",)),
    Item("say:ampersand", "\"Ampersand\"  &", "Punctuation", phrases=("ampersand",)),
    Item("say:percent sign", "\"Percent sign\"  %", "Punctuation", phrases=("percent sign",)),
    Item("say:hash sign", "\"Hash sign\" / \"number sign\"  #", "Punctuation",
         phrases=("hash sign", "number sign")),
    Item("say:dollar sign", "\"Dollar sign\" / \"euro sign\"  $ €", "Punctuation",
         phrases=("dollar sign", "euro sign")),
)
BY_KEY = {item.key: item for item in ITEMS}

# More about each one than its line has room for: shown when the mouse rests on it.
HELP = {
    "speech_only": "Parakeet now and then writes a word for a rustle or a key press. Ticked, each "
                   "phrase it writes words for is also put to a voice detector, and its own doubt "
                   "is weighed: a sound with nothing like speech in it is left out, and so is a "
                   "lone \"yeah\" or \"okay\" that it wasn't sure of. For Parakeet models only. "
                   "If a noise still gets through, tick \"That was a noise\" below and say it.",
    "aloud": "For whispering to somebody, or to yourself, without it being written. A voice "
             "has a pitch and a whisper is only breath: ticked, each phrase is looked at for "
             "voice before anything else is done with it, and one that is mostly breath is "
             "left out. Many rustles and clicks go the same way. Speak as quietly as you like, "
             "so long as it is with your voice. \"Wake up\" has to be said aloud too. A "
             "single short word may now and then be left out as well: say it again, a little "
             "more fully. With any model. The tray icon's tip says when something was left "
             "out for this.",
    "noise": "Say it straight after a rustle or a click has been written as words. The words "
             "are taken back, as \"scratch that\" would, and that one sound is kept in the "
             "\"noises\" folder on this computer, with what it was written as, so that what "
             "tells your noises from your speech can be found out. It acts only on the last "
             "thing written, within two minutes. Nothing is sent anywhere. Unticked, as it is to "
             "begin with, the words \"that was a noise\" are typed like any others.",
    "quick_listening": "Whisper is given only as much sound as the phrase needs, which is quicker. "
                       "Now and then it loses its place that way; that is spotted, and the phrase "
                       "is done again the usual way. With a Parakeet model in use it only quickens "
                       "what Whisper still hears: spelling, source code and second opinions.",
    "second_opinions": "Each phrase is heard by the model you chose, then by a second one, and by a "
                       "third only where those two differ; the two that agree win. The others are "
                       "Small and Medium, or, if you dictate with one of those, the other one and "
                       "Parakeet v2. They have to be installed.",
    "short_wake": "\"Wake\" said by itself wakes dictation, and \"sleep\" by itself puts it to "
                  "sleep. \"Wake up\" and \"go to sleep\" go on working.",
    "scratch": "Takes back the last phrase you dictated. Said again, it takes back the one before. "
               "If the phrase was said over words that were selected, they come back, selected again.",
    "undo": "The program's own Undo: it takes back the last change, whatever made it.",
    "redo": "The program's own Redo: it does again what \"undo that\" has just taken back.",
    "delete": "Removes what is selected. With nothing selected, removes the last phrase you dictated.",
    "delete_words": "Removes the last word before the cursor, or the last few: \"delete last 3 "
                    "words\".",
    "spell": "Opens a small box for a word the recogniser doesn't know. Say its letters one at a "
             "time or a few together, with \"capital J\", \"space\", \"hyphen\" or \"double L\" "
             "where wanted, then \"done\" to put the word in, or \"cancel\".",
    "tab": "Presses the Tab key: an indent, or on to the next box of a form.",
    "space": "Types a space, or several: \"space 3\".",
    "backspace": "Removes the character before the cursor, or several: \"backspace 3\". With "
                 "something selected, it removes that.",
    "new_paragraph": "Starts a new paragraph. In plain text that is a blank line.",
    "new_line": "Starts a new line without starting a new paragraph. In a chat box this is the "
                "one to use: it doesn't send the message.",
    "press_enter": "Presses the Enter key. In a chat box that sends the message.",
    "enter": "The one word \"enter\", said by itself, presses the Enter key, as \"press enter\" "
             "does. Unticked to begin with, since the word turns up in ordinary speech.",
    "line_end": "Moves the cursor to the end of the line it is on. \"Move to\" and \"jump to\" work "
                "in place of \"go to\".",
    "line_start": "Moves the cursor to the start of the line it is on.",
    "word_left": "Moves the cursor back by words: \"move left 3 words\", \"move back a word\".",
    "word_right": "Moves the cursor on by words: \"move right 3 words\", \"move forward a word\".",
    "para_end": "Moves the cursor to the end of the paragraph. Said again there, it goes on to the "
                "end of the next one.",
    "para_start": "Moves the cursor to the start of the paragraph. Said again there, it goes back "
                  "to the start of the one before.",
    "doc_top": "Moves the cursor to the very start of the document.",
    "doc_end": "Moves the cursor to the very end of the document.",
    "line_up": "Moves the cursor up by lines: \"up 3 lines\", \"up one line\".",
    "line_down": "Moves the cursor down by lines: \"down 3 lines\", \"down one line\".",
    "go_to_line": "Jumps to a line by its number, in VS Code, Kate and Word.",
    "select_line": "Selects the line the cursor is on, so that what you say next takes its place.",
    "delete_line": "Removes the line the cursor is on, or several from there down: \"delete 3 "
                   "lines\".",
    "duplicate_line": "Puts a copy of the line under it. In VS Code.",
    "indent": "Moves the line, or the selected lines, in by one step. In VS Code and Word.",
    "outdent": "Moves the line, or the selected lines, back out by one step. In VS Code and Word.",
    "comment_line": "Makes the line a comment, or makes a comment a line of code again. In VS Code.",
    "select": "Selects those words near the cursor: \"select the black cat\". What you say next "
              "takes their place. Words that sound the same are found too (\"two\" finds \"2\" and "
              "\"too\"). If the words aren't there, what you said is typed.",
    "correct": "For putting a mistake right further up without losing your place. The words are "
               "selected as for \"select\"; what you say next takes their place; then the cursor "
               "goes back to where it was. \"Unselect that\" goes back and changes nothing.",
    "choose_numbers": "When \"select\" or \"correct\" finds the words in several places, a small "
                      "number is shown over each: say the number, or \"cancel\". Unticked, the "
                      "nearest place is taken. (Kate and boxes that are typed into always take the "
                      "nearest.)",
    "select_all": "Selects the whole document, or all the text of the box.",
    "select_last": "Selects the last phrase you dictated, so that what you say next takes its place.",
    "unselect": "Clears the selection and leaves the words as they are. After \"correct\", the "
                "cursor goes back to where it was.",
    "cap": "Gives every word of the selection, or of the last phrase, a capital: \"The Quick Brown "
           "Fox\".",
    "all_caps": "Puts the selection, or the last phrase, all in capitals.",
    "no_caps": "Puts the selection, or the last phrase, all in small letters.",
    "bold": "Makes the selection, or the last phrase, bold. Not in plain text; in VS Code, in "
            "Markdown files.",
    "italic": "Makes the selection, or the last phrase, italic. Not in plain text; in VS Code, in "
              "Markdown files.",
    "underline": "Underlines the selection, or the last phrase. In Writer, Word, Outlook and "
                 "Thunderbird.",
    "other_apps": "When none of the programs with a link of their own is in front, your words go "
                  "into whichever text box has the keyboard, with the same spacing, capitals and "
                  "commands. Never into a password box.",
    "vscode_cpp": "In C and C++ files in VS Code, what you say is written as code: \"open "
                  "bracket\", \"semicolon\", \"equals\", and names from the file said as words. "
                  "Unticked, such a file is dictated into as plain text.",
    "keep_final": "A recogniser ends nearly every phrase with a full stop, and a question with "
                  "a question mark. Unticked, that last mark is left off: a pause in the middle "
                  "of a sentence would get one too, and you say \"full stop\" where you want "
                  "one. Ticked, it is kept, which suits short messages said in one go; expect a "
                  "stray full stop where you paused part way through a sentence.",
    "money": "A recogniser writes \"one hundred and twenty dollars\" as $120 and then \"a "
             "hundred and fifty dollars\" in words. Ticked, a sum of money is always put in "
             "figures: $150, $20.50, $2,500, $1.5 million, \"$20 or $30\". Whose dollars "
             "is kept: NZ$100, AU$300, US$50, CA$20. Euros are written €100. Pounds are "
             "written £100 where you say they are money (\"UK pounds\", \"British pounds\", "
             "\"pounds sterling\"): \"a hundred pounds\" alone may be a weight and is left. "
             "Only where a whole number stands straight before the word: \"a few dollars\" "
             "and \"a dollar\" stay as they are. Unticked, each sum is left as the recogniser "
             "wrote it.",
    "commands_only": "For using this program for voice commands and not for dictation. "
                     "Ticked, nothing you say is typed: only commands are acted on, the ones "
                     "that come with this program and the shortcuts and commands of your own "
                     "in the box above. Whatever else is heard is left alone. \"Wake up\" and "
                     "\"go to sleep\" work as always. The tray icon shows a C while this is "
                     "ticked, so that nobody wonders why nothing is typed. Unticked, which is "
                     "how it starts, what is no command is dictation, and is typed.",
    "run_programs": "A command of your own may start a program: a line with \"run:\" under My "
                    "shortcuts and commands. A program is started only by the words of such a "
                    "line, said by themselves, and nothing you say is passed on to it. All the "
                    "same, a phrase may be misheard, or said by a video. So it is off until "
                    "you tick this, and a command that runs a program has to be two words or "
                    "more. Begin a command with \"ask first\" and it waits for you to say "
                    "\"yes\". Pressing keys and opening files and web pages don't need this.",
    "click": "Say \"click\" and the name that a button, a link, a tick box, a tab or a menu "
             "shows, and it is pressed: \"click OK\", \"click save\", \"click file\". The window "
             "in front is asked, through the desktop's accessibility service, what it has "
             "that can be pressed, and the one of that name is pressed through the same "
             "service: no mouse is moved. The start of a name will do, where no shorter name "
             "has those words. If nothing there has the name, what you said is typed like "
             "any other words. Not every program says what is in its windows: where one "
             "doesn't, nothing can be found in it. Off to begin with: ticked, a phrase that "
             "begins with \"click\" is looked for as a name before it is taken for words.",
    "app": "For working this program's own windows without the mouse. \"What can I say\" opens "
           "the list of everything that can be said. \"Open dictation settings\" opens this "
           "window. \"Show microphone level\" opens the level meter. \"Close that window\" "
           "closes whichever of this program's windows is open; with none open, those words "
           "are typed like any others.",
    "no_greeting_comma": "Ticked: \"Hello Bob\". Unticked: \"Hello, Bob\".",
}


def help_for(key: str) -> str:
    """What a tick box is for, at more length than its line: for the mouse resting on it."""
    if key in HELP:
        return HELP[key]
    if key.startswith("say:"):
        return ("Say it while dictating and the sign is typed in its place, fitted to the words "
                "around it. Unticked, what you said is typed as words.")
    return ""
# Settings that aren't commands: they are asked about by name, not left out of what is heard.
OPTIONS = frozenset({"choose_numbers", "vscode_cpp", "other_apps", "keep_final", "money",
                     "quick_listening", "second_opinions", "no_greeting_comma",
                     "speech_only", "aloud", "run_programs", "commands_only"})
WINDOWS_ONLY = frozenset()  # tick boxes shown on Windows only: none now

MOST_SHORTCUTS, LONGEST_SHORTCUT = 200, 2000


def parse_shortcuts(text: str) -> tuple:
    """The person's own shortcuts and commands as typed into Settings, one to a line,
    "what is said = what is typed", or "= keys: ...", "= open: ...", "= run: ..." for a
    command that does something (see actions.py): ({said: what is written after the
    sign}, [the lines that couldn't be understood, and why]).

    A line that starts with a space carries on the text of the one above, as a new line
    of it: an address is written as it will be typed. Nothing needs escaping, so a
    backslash is a backslash. A line that is empty or starts with # is passed over."""
    found, problems, last = {}, [], None
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[:1] in " \t":
            if last is None:
                problems.append(_shortened(line.strip()))
            elif len(found[last]) + len(line.strip()) < LONGEST_SHORTCUT:
                found[last] += "\n" + line.strip()
            continue
        said, sign, typed = line.partition("=")
        said = " ".join(said.lower().split())
        typed, last = typed.strip(), None
        if not sign or not said or not typed or len(typed) > LONGEST_SHORTCUT:
            problems.append(_shortened(line.strip()))
        elif len(found) >= MOST_SHORTCUTS and said not in found:
            problems.append(f"{said}  (only {MOST_SHORTCUTS} are kept)")
        else:
            found[said] = typed
            last = said
    # A command of the person's own, which does something and types nothing (see
    # actions.py), has to be one that can be done: or it is left out, and said why.
    for said, written in list(found.items()):
        wrong = actions.problem(said, written)
        if wrong:
            del found[said]
            problems.append(f"{said}  ({wrong})")
    return found, problems


def _shortened(line: str) -> str:
    return line if len(line) <= 60 else line[:57] + "..."


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


_saving = threading.Lock()  # one save at a time: the engine's worker saves, and so do the windows


class Settings:
    def __init__(self, states: dict | None = None, path: str | None = None, model: str = "",
                 microphone: str = "", words=(), remote=None, share=None, look: str = "",
                 hotkey: str = "", shortcuts=None):
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
        self.hotkey = hotkey  # the key that switches dictation on and off, by its name: "" for none
        self.shortcuts = dict(shortcuts or {})  # what is said, in small letters -> the text it types
        self.first_time = False  # whether load() found no settings file at all

    @classmethod
    def load(cls, path: str = PATH) -> "Settings":
        # Looked at before anything is read. A file that is there, even one that can't be
        # read or made out, is not a first time.
        first_time = not os.path.exists(path)
        try:
            if os.name != "nt" and os.stat(path).st_mode & 0o077:
                os.chmod(path, 0o600)  # one saved before it was kept to its owner
        except OSError:
            pass
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            states, model = saved.get("states", {}), str(saved.get("model", ""))
            microphone = str(saved.get("microphone", ""))
            words = saved.get("words", [])
            words = [str(w) for w in words] if isinstance(words, list) else []
            remote, share = saved.get("remote"), saved.get("share")
            look = str(saved.get("look", ""))
            if not isinstance(states, dict):
                states = {}
            if "hotkey" in saved:
                hotkey = saved["hotkey"] if isinstance(saved["hotkey"], str) else ""
            else:
                # A file from before there was a choice of key. It had a tick box for the
                # + of the number pad, which was on unless the file says otherwise. (Read
                # here, from the states as they were saved: that tick box is no more.)
                hotkey = "Number pad +" if states.get("numpad_plus", True) else ""
            shortcuts = saved.get("shortcuts")
            shortcuts = {said: typed for said, typed in shortcuts.items()
                         if isinstance(said, str) and isinstance(typed, str)
                         } if isinstance(shortcuts, dict) else {}
        except (OSError, ValueError, AttributeError):
            states, model, microphone, words, remote, share, look = {}, "", "", [], None, None, ""
            hotkey, shortcuts = "", {}
        loaded = cls({k: bool(v) for k, v in states.items() if k in BY_KEY}, path, model,
                     microphone, words, remote, share, look, hotkey, shortcuts)
        loaded.first_time = first_time
        return loaded

    def save(self) -> None:
        if not self.path:
            return
        with _saving:
            # Where the settings really are. If the file is a link to one kept somewhere
            # else (with the rest of a person's settings, say), it is that one that is
            # written, and the link stays a link.
            path = os.path.realpath(self.path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # The key is written even when there is none: its being missing is how a
            # file from before there was a choice of key is known (see load).
            saved = {"states": dict(self.states), "model": self.model, "hotkey": self.hotkey}
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
            if self.shortcuts:
                saved["shortcuts"] = dict(self.shortcuts)
            # Written beside the file and then put in its place, so that a write cut short
            # (a full disk, the power going) leaves the old settings and not half of the
            # new. Only the person's own account may read it: it can hold the keys for
            # sharing. The file beside it has a name nobody else is using: another
            # program saving at the same moment has its own.
            new = f"{path}.{os.getpid()}.{threading.get_ident()}.new"
            try:
                with os.fdopen(os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w",
                               encoding="utf-8") as f:
                    json.dump(saved, f, indent=1, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                for attempt in range(20):
                    try:
                        os.replace(new, path)
                        break
                    except PermissionError:   # Windows: something has the old one open just now
                        if attempt == 19:
                            raise
                        time.sleep(0.05)
            except BaseException:
                try:
                    os.remove(new)        # nothing half written is left lying beside it
                except OSError:
                    pass
                raise

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

    def set_hotkey(self, name: str) -> None:
        """The key that switches dictation on and off, by its name in hotkey.KEYS: "" for
        none. (Windows.)"""
        self.hotkey = str(name)
        self.save()

    def shortcuts_text(self) -> str:
        """The shortcuts as they are shown in Settings: see parse_shortcuts."""
        return "\n".join(f"{said} = " + typed.replace("\n", "\n    ")
                         for said, typed in getattr(self, "shortcuts", {}).items())

    def set_shortcuts(self, text: str) -> list:
        """Set the shortcuts from what was typed into Settings. The lines that couldn't be
        understood are handed back, for the window to show; the rest are kept."""
        found, problems = parse_shortcuts(text)
        if found != getattr(self, "shortcuts", {}):
            self.shortcuts = found
            self.save()
        return problems

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
    ("parakeet-unified", 11, "Parakeet Unified: the best so far, not Whisper"),
    ("parakeet", 10, "Parakeet v2: quick and accurate, not Whisper"),
    ("turbo", 8, "Large turbo: quicker than Large"),
    ("large", 9, "Large: most accurate, very slow"),
    ("medium", 6, "Medium: accurate, slow"),
    ("small", 4, "Small: good, and quick enough for most computers"),
    ("base", 2, "Base: quicker, less accurate"),
    ("tiny", 1, "Tiny: quickest, least accurate"),
)


# The model to suggest to somebody new: the fewest words wrong of those tried, and quick.
# (The installer fetches Small and Base, which is what "wake up" is listened for with.)
RECOMMENDED = "parakeet-unified-en-0.6b"


def model_label(name: str) -> tuple[int, str]:
    """An order and a plain description for a model folder name."""
    low = name.lower()
    if low == RECOMMENDED:
        return 11, f"Parakeet Unified: recommended, the best so far  ({name})"
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


def wake_there(remote: dict, model_dir: str) -> tuple:
    """(whether the other computer listens for "wake up" as well, whether it has to).

    It has to where this computer has no speech model of its own: there is nothing here
    to hear "wake up" with. With a model here it is as it was chosen, which is not to,
    to begin with: then nothing is sent while dictation is asleep."""
    forced = not available_models(model_dir)
    return forced or bool(remote.get("wake")), forced


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
