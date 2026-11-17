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
| `endings.py` | Recovers "question mark" said after a pause, when Whisper wrote the sign instead |
| `vocabulary.py` | The person's own words: a hint for Whisper, and a second hearing to check it |
| `spelling.py` | Turns spoken letters into letters for "spell that" |
| `settings.py` | Which commands are switched on, and the choice of speech model |
| `voicetest.py` | Trying every recogniser on a recording of your own voice, and scoring each |
| `reading.py` | Reading sentences aloud for training: cutting the microphone's sound into a piece for each sentence, judging when a sentence has been read to its end, and keeping each beside its text |
| `reading_text.py` | The sentences that come with it |
| `training.py` | The app's side of retraining a model on those sentences: what there is to train on, what the result is called, starting the work as a process of its own and following it by the notes it keeps |
| `trainer/` | The retraining itself, run by a Python of its own that has PyTorch and NeMo: the passes, the loss for a processor (Parakeet v2's TDT loss is written out here; Parakeet Unified's plain transducer loss is torchaudio's), cutting single words out of the sentences to learn from beside them (`words.py` says why), making the app's 8-bit files, and the comparison on sentences and single words kept back |
| `speech.py` | Tells speech from other sounds with a voice detector, so that a noise Parakeet wrote a word for is left out |
| `opinions.py` | One phrase as two recognisers heard it, with a third settling where they differ |
| `quick.py` | Giving Whisper only as much sound as a phrase needs, with a safety net |
| `remote.py` | Another computer doing the recognising: the server that shares it, the client, and the fallback |
| `models.py` | The speech models that can be had: downloading one, checking it, removing one |
| `targets.py` | Picks the program in front |
| `client.py` | Talks to the LibreOffice extension |
| `mailbridge.py` | Talks to the Thunderbird add-on |
| `editor_target.py` | Drives Kate and KWrite |
| `web_target.py` | Linux: text boxes that can be read but not written through the accessibility interface (VS Code's panels, web pages), typed into |
| `portal_keys.py` | Linux: pressing keys with the desktop's leave, through its remote-desktop portal |
| `vscode_args.py` | Linux: the start-up switch that makes VS Code describe its panels' text boxes |
| `vscode_target.py` | Talks to the VS Code extension |
| `looks.py` | Windows: the look of Windows 10, 7 or XP for the app's windows and the tray menu, if one is chosen |
| `tray.py` | The tray icon and its windows |

## Listening

`parec` records the default microphone at 16 kHz. The pause detector works on the loudness
of 20 ms frames. It measures the room for half a second, then treats anything well above
that level as speech, and ends a phrase after 650 ms of quiet. A phrase that never pauses
is cut at 20 seconds.

Each phrase is turned up to a normal level and given to Whisper, through faster-whisper,
on the processor. While asleep, only phrases under six seconds are transcribed, and only
"wake up", or a near miss of it, does anything (or "wake" by itself, that word exactly,
where the short words are switched on). While awake, Whisper is also given the
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

### VS Code's panels and web pages, on Linux

Kate's kind of text box can be read and written through AT-SPI. A text box drawn by
Chromium, which is what VS Code's panels and every browser-built program have, can only be
read: there is a Text interface and no EditableText. `web_target.py` handles those. It
finds the focused box that has the one interface and not the other, reads its text,
cursor and selection, and types.

- **Reading.** The box's own text is the whole of what was typed, with line breaks, and
  the cursor is a place in it. A hint shown while the box is empty is made by the page out
  of decoration (a `::before`), which AT-SPI gives as a thing inside the box, standing in
  the text as one object character and tagged `::before`. Those are taken out, so an empty
  box reads as empty. Nothing has to be guessed from where the cursor is drawn, as it has
  to be on Windows.
- **Typing.** A Wayland desktop lets no program press keys in another without the
  person's leave. `portal_keys.py` asks through the desktop's remote-desktop portal, for
  the keyboard only, and keeps the token the desktop hands back so that it is asked once.
  Keys are sent by what they type (keysyms), and the desktop finds the key and whether
  Shift is needed. A character the keyboard hasn't got is not typed at all by the
  desktop, so `typable()` makes text plain first: what is remembered as typed, for
  "scratch that", is then what really went in.
- **The program has to be asked to describe itself.** Chromium keeps its accessibility
  tree off unless started with `force-renderer-accessibility`. VS Code reads that from
  `argv.json`, which `vscode_args.py` edits for the installer.

Everything that decides what to type, and the commands, is `keys_target.py`'s, which the
Windows target for other programs' text boxes also is: `WebBoxTarget` only replaces how a
box is found and read, and how keys are pressed. `targets.py` asks it last, so a file open
in VS Code's editor still goes through VS Code's own extension.

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

### Other programs' text boxes, on Windows

`keys_target.py` reads what is around the cursor through UI Automation and puts the
words in one of three ways, by what the program in front is:

- A browser, or a program built from one, is sent each character as itself, in a burst.
- One of Windows' own edit boxes, plain or rich, is read and written by messages to the
  box itself, with the accessibility interface kept out of it. Its text and where the
  cursor is are asked for (`WM_GETTEXT`, `EM_GETSEL`), and the words are handed over whole
  (`EM_REPLACESEL`): no keys are pressed, they take the place of anything selected, and
  Undo takes them back in one step. Notepad's text area is such a box. Windows 11's Notepad
  can't be typed into quickly: sent a burst of characters it writes the last one of the
  burst for each of them, and sent key presses as fast it drops some near the start.
  The hand-over is followed by a Shift key message. Notepad takes its text cursor off the
  screen a few seconds after text arrives with no key pressed, and puts it back at the
  next key; watched ten times a second, the cursor went within 1.5 to 5.5 seconds
  without that message and stayed with it. Reading it through the accessibility
  interface made the cursor go as well, which is why the box is asked by message.
- The editing area of Notepad++ (Scintilla) offers nothing through the accessibility
  interface, but answers the same messages for its text and its selection, counting in
  bytes. It is read that way and typed into with key presses.
- Anything else is sent presses of the keys that make the characters, with Shift where a
  key needs it, one character at a time at about a hundred a second. Only a character the
  keyboard hasn't got is sent as itself.

Commands such as "scratch that" are key presses everywhere.

Two things about web pages, and programs built from them, shape how it reads:

- What has the keyboard can be the whole page, with the text box somewhere inside it, and
  reading on from the cursor runs out of the box into the page. So the box is looked for
  from the cursor outwards, and only its own text is read. A cursor at the end of the box
  can count as beyond it, so "nothing after the cursor" is settled by comparing the two,
  not by cutting the range back.
- An empty box's hint ("Type a message") is given as if it were the box's text. Read as
  text before the cursor, it would earn the first words a space and cost them their
  capital. A plain input box says it holds nothing, and that settles it. A chat box often
  gives the hint as what it holds too. There the hint is told by where it is drawn: typed
  text ends at the cursor, and a hint starts at the cursor and runs on to the right. The
  cursor's place is asked of the window (its caret object), because the text reader can
  put the cursor at the far end of the hint, where typed text would put it. Any text to
  the left of the cursor on its line means the box has been typed in.

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
| `~/.local/state/linux-speaking/` | Whether dictation was on |
| `~/.local/state/linux-speaking/training/` | Sentences read aloud for training: a folder for each day, with each one's sound and `said.txt`, the list of what was read |
| `~/.config/systemd/user/linux-speaking.service` | The login service |

Advanced settings are environment variables beginning `LS_`, listed in
`dictation/config.py`.
