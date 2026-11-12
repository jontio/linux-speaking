# How Linux Speaking works

## The parts

```
microphone ─► parec ─► pause detector ─► Whisper ─► command or dictation?
                                           ▲                │
                             text before   │                ▼
                             the cursor    └──── the program in front
                                         (Writer, Thunderbird, VS Code, Kate, KWrite)
tray icon ◄── off / asleep / awake / hearing / thinking
```

Everything runs as one user service, `linux-speaking`, started at login. It is a Python
program in `dictation/`, with a Qt tray icon.

| File | What it does |
|---|---|
| `engine.py` | The microphone, Whisper, the asleep/awake state, and what to do with each phrase |
| `segmenter.py` | Cuts the microphone stream into phrases at each pause |
| `commands.py` | Decides whether a phrase is a command or dictation |
| `formatting.py` | Fits a phrase into the text around the cursor: spaces, capitals, punctuation words |
| `words.py` | Tells names from ordinary words, using the system's Hunspell dictionary |
| `selecting.py` | Finds the words for "select ..." |
| `coding.py` | The rules for dictating C and C++ source code |
| `hotkey.py` | Windows: the number pad + key that switches dictation off and on |
| `vocabulary.py` | The person's own words: a hint for Whisper, and a second hearing to check it |
| `spelling.py` | Turns spoken letters into letters for "spell that" |
| `settings.py` | Which commands are switched on, and the choice of speech model |
| `targets.py` | Picks the program in front |
| `client.py` | Talks to the LibreOffice extension |
| `mailbridge.py` | Talks to the Thunderbird add-on |
| `editor_target.py` | Drives Kate and KWrite |
| `vscode_target.py` | Talks to the VS Code extension |
| `tray.py` | The tray icon and its windows |

## Listening

`parec` records the default microphone at 16 kHz. The pause detector works on the loudness
of 20 ms frames. It measures the room for half a second, then treats anything well above
that level as speech, and ends a phrase after 650 ms of quiet. A phrase that never pauses
is cut at 20 seconds.

Each phrase is turned up to a normal level and given to Whisper, through faster-whisper,
on the processor. While asleep, only phrases under six seconds are transcribed, and only
"wake up", or a near miss of it, does anything. While awake, Whisper is also given the
text before the cursor, so that it carries on in the same style.

## Commands and dictation

A phrase is a command only if the whole phrase matches one, after removing case and
punctuation. Anything else is dictation. That is why "scratch that" on its own removes
text, while "I would scratch that idea" is typed.

For dictation, the engine asks the program in front for the text before and after the
cursor on the current line or paragraph. `formatting.fit` then decides the leading and
trailing spaces, the capital on the first word, and turns punctuation words into
punctuation. The result is an insertion: text, plus a count of spaces to remove either
side. All of this happens in the engine, so the rules behave the same in every program.

## Reaching each program

Every program answers the same small set of requests, as JSON:

```
{"op": "status"}                      is your window in front?
{"op": "context"}                     the text before and after the cursor
{"op": "insert", "text": ..., "delete_before": n, "delete_after": n, "capitalise_next": bool}
{"op": "command", "name": "scratch" | "undo" | "backspace" | "select" | ..., "arg": ...}
```

How each is reached:

- **LibreOffice Writer:** an extension (`extension/`) runs inside LibreOffice and listens
  on a socket in the user's runtime folder. Requests are passed to LibreOffice's main
  thread. Numbered choices are drawn with Writer's ruby text, without adding undo steps.
  An update to the extension can only be installed while LibreOffice is closed, so it is
  staged, and the tray installs it when LibreOffice next closes.
- **Thunderbird:** an add-on (`thunderbird/`) runs a script inside each compose window.
  An add-on can't be called from outside, so it keeps one HTTP request open to the engine
  on `127.0.0.1:47613` and receives its instructions as the reply. The engine refuses
  requests that come from web pages. Edits use the editor's own commands, so Thunderbird's
  undo works.
- **Visual Studio Code:** an extension (`vscode/`) runs in each VS Code window and listens
  on its own socket, `linux-speaking-vscode-<process id>.sock`, in the user's runtime
  folder. The engine asks each window whether it is in front. Each phrase is one edit, so
  one undo takes it back. Numbered choices are editor decorations. The extension is
  packaged as a `.vsix` by `scripts/build-vsix.sh` and installed with
  `code --install-extension`.
  In C and C++ files it also reports what the editor's language server says is in scope at
  the cursor, by running VS Code's own completion command. `coding.py` uses that to correct
  misheard names and to tell a keyword from a number by position.
- **Kate and KWrite:** there is no add-on. The engine uses the accessibility interface
  (AT-SPI), as a screen reader does. Qt only offers that interface when asked, so the
  installer adds `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` to the two programs' launchers. It
  is not switched on for the whole desktop.

With the "other programs" setting on, the same code serves any program's focused text box,
not only Kate's. That needs accessibility on for the whole desktop, so `accessibility.py`
turns the desktop's switch on, and off again when the setting is unticked. Programs that
have their own link are skipped, and so are password boxes.

### Word and Outlook, on Windows

`word_target.py` runs in the engine and speaks to Word through COM, Word's automation
interface. Classic Outlook's message editor is Word underneath, so one piece of code
serves both.

It doesn't ask Windows for "the running Word". It asks which control has the keyboard,
and if that is a Word editing area (window class `_WwG`, in Word and in Outlook alike) it
asks that window for its own automation object. That gives exactly the document being
typed in, and works for a reply in Outlook's reading pane as well as a message window. For
Outlook it also asks whether the window in front is a message being written, so that a
message being read isn't offered.

All COM calls are made on one thread of the target's own. COM wants objects used from the
thread that got them, and a busy Word (a dialog open, say) can't then hold up the engine:
a request that isn't answered in time simply fails.

Word has nowhere to draw numbers over matches, so for "select" the target asks Word where
each match is on screen and the tray shows a small label there. The labels follow the text
if it scrolls and go when another window comes to the front.

On Windows the engine reads the microphone with `sounddevice` instead of `parec`, and
talks to the VS Code extension over a named pipe instead of a socket file (`pipe.py`).

### Adding another program

Write something that answers the four requests above, and add it to `targets.py`. If the
program is a Qt or GTK text editor, `editor_target.py` may already work for it once its
name is added to `APPS` and it is started with accessibility on.

## Tests

| Command | What it covers | Needs |
|---|---|---|
| `python3 -m unittest discover -s tests -t .` | All the rules | Python only |
| `PYTHONPATH=. scripts/test-writer.sh` | The Writer extension, in a hidden LibreOffice with a throwaway profile | LibreOffice |
| `PYTHONPATH=. PYTHON=~/linux-speaking/venv/bin/python scripts/test-writer.sh scripts/engine_test.py` | The engine end to end, with synthesized speech | The above, an install, libespeak-ng |
| `scripts/test-thunderbird.sh` | The add-on's editing code, in headless Firefox | Firefox |
| `PYTHONPATH=. scripts/test-thunderbird-e2e.sh` | The whole add-on, in a throwaway Thunderbird profile | Thunderbird |
| `PYTHONPATH=. scripts/test-vscode.sh` | The VS Code extension, in a separate VS Code window with its own settings, which shows briefly | VS Code, a desktop session |
| `PYTHONPATH=. scripts/test-form.sh` | Any program's text boxes, using a small form window that shows briefly | PyQt6, a desktop session |
| `PYTHONPATH=. scripts/test-editor.sh` | Kate's editor, using a scratch KWrite window that shows briefly | KWrite, a desktop session |

| `venv\Scripts\python.exe app\scripts\word_test.py` (on Windows, in the install folder) | Word, using a blank document of its own that it closes unsaved | Word |
| `venv\Scripts\python.exe app\scripts\outlook_test.py` (the same) | An Outlook message, using a new one of its own that it discards | Classic Outlook, open |

`scripts/deploy.sh user@host` installs or updates another computer over ssh, which is
handy when you develop on one machine and dictate on another.

## Settings and files

| Path | What it holds |
|---|---|
| `~/linux-speaking/` | The program, its Python packages, the speech models |
| `~/.config/linux-speaking/settings.json` | Your Settings choices |
| `~/.local/state/linux-speaking/` | Whether dictation was on, and whether the meter window was open |
| `~/.config/systemd/user/linux-speaking.service` | The login service |

Advanced settings are environment variables beginning `LS_`, listed in
`dictation/config.py`.
