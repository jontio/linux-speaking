# How Linux Speaking works

## The parts

```
microphone ─► parec ─► pause detector ─► Whisper ─► command or dictation?
                                           ▲                │
                             text before   │                ▼
                             the cursor    └──── the program in front
                                         (Writer, Thunderbird, VS Code, Kate, KWrite)
tray icon ◄── off / asleep / awake / hearing / thinking, and what is wrong
```

Everything runs as one program, a Python program in `dictation/` with a Qt tray icon.
On Linux it is a user service, `linux-speaking`, started at login; where there is no
systemd, the menu entry starts it directly (`scripts/launch.sh`). On Windows a shortcut
starts it. Only one copy runs, whichever way it was started: see "One copy, and asking
it to do things", below.

| File | What it does |
|---|---|
| `engine.py` | The microphone, Whisper, the asleep/awake state, what to do with each phrase, and what to tell the person (`tell`, and the list of what is wrong in `Status.problems`) |
| `audio.py` | Recording from the microphone, on Linux and on Windows. When it can't be opened it raises `MicrophoneError`, whose words are for the person to read; a recording that stopped by itself says why (`why()`); `works()` tries a microphone that had stopped; `microphones(fresh=True)` reads Windows' list of them again |
| `status.py` | What the engine is doing, and what is wrong and stays wrong, for the tray icon and its tooltip |
| `config.py` | Where things are kept, and the advanced settings read from the environment |
| `segmenter.py` | Cuts the microphone stream into phrases at each pause |
| `commands.py` | Decides whether a phrase is a command or dictation |
| `formatting.py` | Fits a phrase into the text around the cursor: spaces, capitals, punctuation words |
| `words.py` | Tells names from ordinary words, using the system's Hunspell dictionary |
| `selecting.py` | Finds the words for "select ..." |
| `coding.py` | The rules for dictating C and C++ source code |
| `hotkey.py` | Windows: the key that switches dictation off and on, chosen from `KEYS`; none is taken until one is chosen |
| `control.py` | Seeing that only one copy of the app runs, and asking the running one to do something: `python -m dictation.control toggle`, for a key of the person's own |
| `autostart.py` | Whether the app starts when the person signs in, and switching that: the login service on Linux, a shortcut in the Startup folder on Windows |
| `accessibility.py` | Linux: switching the desktop's accessibility interface on for "other programs", and off again |
| `endings.py` | Recovers "question mark" said after a pause, when Whisper wrote the sign instead |
| `vocabulary.py` | The person's own words: a hint for Whisper, and a second hearing to check it; for Parakeet, which takes no hint, putting them in by sound where a name was written |
| `spelling.py` | Turns spoken letters into letters for "spell that" |
| `settings.py` | Which commands are switched on, the choice of speech model, the person's own words and shortcuts, and the key chosen on Windows |
| `voicetest.py` | Trying every recogniser on a recording of your own voice, and scoring each |
| `reading.py` | Reading sentences aloud for training: cutting the microphone's sound into a piece for each sentence, judging when a sentence has been read to its end, and keeping each beside its text |
| `reading_text.py` | The sentences that come with it |
| `training.py` | The app's side of retraining a model on those sentences: what there is to train on, what the result is called, starting the work as a process of its own and following it by the notes it keeps |
| `trainer/` | The retraining itself, run by a Python of its own that has PyTorch and NeMo: the passes, the loss for a processor (Parakeet v2's TDT loss is written out here; Parakeet Unified's plain transducer loss is torchaudio's), cutting single words out of the sentences to learn from beside them (`words.py` says why), making the app's 8-bit files, and the comparison on sentences and single words kept back |
| `speech.py` | Tells speech from other sounds, with a voice detector and with how sure the recogniser was, so that a noise Parakeet wrote a word for is left out; keeps the sounds marked "that was a noise" |
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
| `vscode_args.py` | Linux: the start-up switch that makes VS Code describe its panels' text boxes. The app puts it in when "other programs" is ticked, and looks again at each start; the uninstaller takes it out |
| `vscode_target.py` | Talks to the VS Code extension |
| `word_target.py` | Windows: drives Word, and messages in classic Outlook |
| `keys_target.py` | Windows: any other program's text box, read through UI Automation or by messages and typed into. What it decides to type is shared with `web_target.py` |
| `winapi.py` | Windows: the calls to Windows itself that those two need |
| `pipe.py` | Windows: named pipes, where Linux has sockets in the runtime folder, and making sure that a pipe is this person's before anything is sent down it |
| `looks.py` | Windows: the look of Windows 10, 7 or XP for the app's windows and the tray menu, if one is chosen |
| `tray.py` | The tray icon and its windows: Settings, the welcome window, "What can I say?", the log, the microphone level, the models, the voice test, reading and training, and the small window that stands in for the icon where the desktop has no tray |

Beside the program are a few things the installers lean on:

| File | What it does |
|---|---|
| `requirements.txt` | The Python packages an install runs on, with the versions they were last tried with. `install.sh` and `install.ps1` both install from it |
| `scripts/fetch_models.py` | Fetches the two speech models a new install needs, with the app's own downloader (`models.py`): it shows how far it has got and carries on from where it stopped |
| `scripts/check_install.py` | Run by both installers before they say "Done": that the packages load, that the models are where the app will look, and that they load |
| `scripts/launch.sh` | Linux: starts the app, through the login service or directly, and passes `toggle`, `wake`, `sleep`, `off` and `settings` on to `control.py`. The menu entry runs it |

## Who may talk to the engine

The engine takes its orders from a microphone, but it talks to other programs, and each
of those links is a way in for something that shouldn't be there.

- **Sockets (Writer, VS Code on Linux)** are files in the user's runtime folder, which
  only that user can open.
- **Named pipes (VS Code on Windows)** have names every account on the computer can see,
  and anyone may make one. Before anything is sent down a pipe, `pipe.py` asks Windows
  three things of the pipe it has opened: who owns the pipe itself, which another
  account can't set to this one's; whether it is labelled as made by a program that
  Windows keeps apart from the person's own; and, as a second look, who the process at
  its other end runs as. If Windows won't hand the label over, the owner alone decides,
  and the log says so once. A pipe found to be another account's is not asked again
  while it is there, and no time is spent waiting on a busy pipe that was never found
  to be this person's.
- **Thunderbird** is reached over a port on the computer itself, with a key that each end
  proves it holds: see Thunderbird under "Reaching each program", below. It keeps out
  another person's program and one that is kept apart from your files. A program running
  as you, with your files to read, could read the key as it could read anything else.
  The engine attends to only so many callers on that port at once and gives each a few
  seconds to send its request, and a stranger asking can't take the add-on's turn from
  it. An add-on from before the key is told nothing and kept waiting as an idle poll
  is; `MailBridge.problem` says in words for the person what to do, and says nothing
  once the right add-on has connected. Every answer is sent with `Cache-Control:
  no-store`, and the add-on asks without caching: Thunderbird otherwise keeps a file on
  the disk for every exchange.
- **Another computer** doing the recognising (`remote.py`) is reached over the network,
  with a key typed into both. This computer says hello with a number it has made up, and
  the other answers with a number of its own, a "turn", and proof made from the key and
  both numbers: so one that only answers to the right name is found out before it is
  given any sound. Each request is signed over a turn, which is good once and for a
  minute, and each answer over the request's numbers, bringing the next turn. Ahead of
  each request's body comes a shorter proof, over the turn, the request's number and how
  much is to follow: the sharing computer reads no body until that is checked and the
  turn is good. It attends to eight callers at once and turns the rest away, and gives a
  caller one allowance of time for the whole of a request: five seconds to show that it
  holds the key, then time for the sound in keeping with its length, 30 seconds and up
  to 55 for a long phrase on a slow link. A request's first lines sent again by somebody
  who overheard them hold a place for six seconds. The turns given at hello are counted
  apart from those given with signed replies, so a stranger's hellos can't push out a
  turn that came with a signed reply. A caller's very first turn, the one its own hello
  brought, still can be pushed out by a flood of hellos: it then says hello again. The
  asking computer gives each exchange one allowance of
  time, reads no more than an answer could come to, and takes any failure at all to mean
  it should do the listening itself. The hello's answer carries a number for the way of
  talking; one without it is said to be older and is sent nothing. An answer
  that isn't signed is not believed. What is sent is hidden as well. With the hello each
  computer sends half of a key made for the occasion (X25519); the proof covers both
  halves, so nobody between them can put in their own. The key they then share is never
  sent, lasts one run of requests and is forgotten, so a recording of the traffic can't
  be read later even with the key from Settings. Each request and reply is sealed under a
  key of its own made from it (ChaCha20-Poly1305, from the `cryptography` package). Where
  that package is missing the link is not used at all, in either direction: nothing goes
  in the clear. Still to be seen: that phrases are sent, when, and how long each is.
  Still possible: a stranger who keeps the eight places busy keeps real callers out,
  and they then do their own listening.
- **settings.json** can hold the keys, and on Linux is written for its owner only. So
  are the sounds marked "that was a noise", and the list of them: a folder of them from
  an earlier version is closed to other accounts when the program starts.

## Listening

`parec` records the default microphone at 16 kHz. The pause detector works on the loudness
of 20 ms frames. It measures the room for half a second, then treats anything well above
that level as speech, and ends a phrase after 650 ms of quiet. A phrase that never pauses
is cut at 20 seconds.

In a room that isn't quiet no pause shows: keys are being pressed, a fan roars, the
microphone turns itself up when the talking stops. So while a phrase is being taken down
a voice detector is asked, ten times a second, whether there is still speech in it
(`speech.VoiceWatch`). When there has been none for 0.7 seconds the phrase is ended,
though the sound goes on. Talk that goes on far softer than the phrase's own (other
people, in the background) ends it too, after 1.2 seconds, and starts a phrase of its
own. Where the detector isn't installed, the voice's pitch is looked for instead, which
is slower.

Each phrase is turned up to a normal level and given to Whisper, through faster-whisper,
on the processor. While asleep, only phrases under six seconds are transcribed, and only
"wake up", or a mishearing of it such as "wake app" or "weak up", does anything (or
"wake" by itself, that word exactly, where the short words are switched on). "Make up",
"woke up" and "wake me up" are things said to somebody else in the room, and do
nothing. While awake, Whisper is also given the text before the cursor, so that it
carries on in the same style.

A microphone that can't be opened is not a state of its own: the engine stays off and
tells the person why, in `audio.MicrophoneError`'s own words. One that stops by itself
(unplugged, the sound system restarted) is tried again every two seconds for three
minutes, and dictation comes back asleep when it works, so that somebody working by
voice alone can say "wake up" and carry on. Three stops within a minute, and it is left
for the person to try.

If no speech model can be loaded, `Status.failed` holds the reason and the state reads
"No speech model". Loading is tried again when a sound next arrives, twenty seconds or
more later, in case a model has been installed meanwhile.

## Commands and dictation

A phrase is a command only if the whole phrase matches one, after removing case and
punctuation. Anything else is dictation. That is why "scratch that" on its own removes
text, while "I would scratch that idea" is typed. The whole phrase is looked up as it
was said, and then without an "um" or "OK" before it, without "please" at either end
and without "the", so that a command need not be said in exactly one way
(`commands.interpret`). A "no" before it goes only where the recogniser wrote a pause
after it, "and" never goes, and a phrase that ends with "the" is no command. What is
never done is to find a command inside a longer phrase.

Before the commands, all but waking, sleeping and "spell that", a phrase is tried
against the person's own shortcuts, which are kept in the settings: one of those said
by itself types its text, exactly as written, capitals and all.

For dictation, the engine asks the program in front for the text before and after the
cursor on the current line or paragraph. `formatting.fit` then decides the leading and
trailing spaces, the capital on the first word, and turns punctuation words into
punctuation. The result is an insertion: text, plus a count of spaces to remove either
side. All of this happens in the engine, so the rules behave the same in every program.

One thing the text can't tell is carried from one phrase to the next. After "p.m." or
"etc." the stop is the word's own, and the text reads the same whether "full stop" was
said after it or the speaker only paused. So `fit` says whether a sentence end was said
(`Insertion.said_end`), and the engine hands that back with the next phrase
(`after_said_end`), for as long as the text before the cursor still ends with what was
last typed in the same program.

## Telling the person

The engine has two ways of saying something, and the tray shows both.

- **A notice now** (`Engine.tell`): a sentence, and whether it is news or a problem. It
  is for what would otherwise leave nothing to see: words that had nowhere to go, a
  command the program in front can't do, what "select" selected, a microphone that
  can't be opened. A thing that goes wrong with every phrase is said once in a while,
  not with every phrase: `tell` is given how long to wait before the same sentence is
  shown again. Every notice is also written to the log, but never with words in it
  that were said or written: where a notice has such words, `tell` is given what the log
  gets in its place (`logged`), as "Selected: (12 characters)" or a command's name.
- **What is wrong and stays wrong** (`Status.problems`): a list of sentences, each
  saying what to do. The engine brings it up to date every few seconds from its own
  notes and from what the links say of themselves (`MailBridge.problem`, the `problem`
  of the target that presses keys, and why other computers can't use this one for
  recognition). The tray icon's tip lists them, and so does the top of Settings.

While dictation is awake and idle, the engine also looks every few seconds at which
program is in front, so that the tip says where words will go before they are said.

## One copy, and asking it to do things

Two copies of the app would both type what is said, so only one runs. `control.py` sees
to it: a lock on the file `running` in the state folder on Linux, a named mutex on
Windows. A second start leaves a request for the first to show itself, and ends.

Requests are words left in a small file in the state folder (`show`), which the tray
looks for a few times a second. `python -m dictation.control toggle` leaves one, and
so do `wake`, `sleep`, `off` and `settings`: that is what a key of the person's own is
bound to on Linux, where desktops differ too much in how a program may take a key for
the app to take one itself. On Windows the app takes the chosen key (`hotkey.py`).

## Reaching each program

Every program answers the same small set of requests, as JSON:

```
{"op": "status"}                      is your window in front?
{"op": "context"}                     the text before and after the cursor
{"op": "insert", "text": ..., "delete_before": n, "delete_after": n, "capitalise_next": bool}
{"op": "command", "name": "scratch" | "undo" | "backspace" | "select" | ..., "arg": ...}
{"op": "move", "steps": [...]}        Writer only: cursor movement spelled out by the engine
{"op": "symbols"}                     VS Code only: the names in the file and in scope
```

A `select` or `correct` command also carries `"nearest": true` when the numbers to choose
from are switched off. A program that doesn't know a request answers "unknown request",
and one that doesn't know a command "unknown command"; the engine then tries the next
best thing.

The command `correct` is `select` with a way back. The program remembers where the cursor
was, and the `insert` that next replaces those same words ends with the cursor there again
(its reply then has `"back": true`). `unselect` goes back too. The place is kept by the
program, in its own terms: a text cursor in Writer, a range in Word and in Thunderbird, a
count from the top of the text in VS Code and Kate. In a box that is typed into, it is so
many presses of an arrow key from the words. It is only for what is said next: any other
command forgets it ("space" is sent as words, and so stands in their place), and nothing is gone back to unless the words chosen are still the
selection, so a click somewhere else in between is respected. A place that was after the
words moves along with the text, one that was before them stays, and one right beside them
is kept on the side of them it was on (`selecting.back_to`). Where the way back is by arrow
keys there is a limit to how many are pressed (`FAR` in `keys_target.py`, or `FAR_PACED`
where keys go in one at a time); past it the
cursor stays, the reply has `"too_far": true`, and the engine says so. A program whose
link is older answers "unknown command"; the engine asks it to `select` instead and says
that the cursor will stay.

A program that looks for the words itself looks for exactly those, so when it can't
find them the engine asks again: for initials with their letters apart, where the
recogniser wrote them with dots ("U.S." reaches the engine's rules as "us", and such a
program reads the text's "U.S." as "u s"), and then for `selecting.variants`, which are
the same numbers written the other way, the other spelling and words that sound the
same. If the words for `select` or `correct` still can't be found, the engine types the
phrase as dictation: a sentence may begin with "Select" or "Correct".

How each is reached:

- **LibreOffice Writer:** an extension (`extension/`) runs inside LibreOffice and listens
  on a socket in the user's runtime folder. Requests are passed to LibreOffice's main
  thread. Numbered choices are drawn with Writer's ruby text, without adding undo steps.
  The extension can only be installed while LibreOffice is closed, so if the installer
  finds it open the extension is staged, and the tray installs it when LibreOffice next
  closes and says when it is in. If that fails, it is said once, with the reason, and
  not tried again until the app next starts. The extension carries its own copies of
  `formatting.py`, `words.py` and `selecting.py` (`scripts/build-oxt.sh`), which it
  uses to find the words for "select" and for "cap that". A change to those rules
  reaches Writer only when the extension has been built and installed again; the
  fitting of dictated words is done in the engine, and needs no such thing.
- **Thunderbird:** an add-on (`thunderbird/`) runs a script inside each compose window.
  An add-on can't be called from outside, so it keeps one HTTP request open to the engine
  on `127.0.0.1:47613` and receives its instructions as the reply. The engine refuses
  requests that come from web pages. Anything else on the computer could ask there too,
  or listen there in the engine's place, so the two prove themselves to each other with a
  key: `scripts/build-xpi.sh` makes one for the computer it runs on, keeps it beside the
  settings (`mail-key`, for its owner only) and writes it into the add-on's file. The
  add-on's first request brings a number it has made up; every one after that brings one
  too and is signed over the number the engine's last answer gave; the engine's every
  answer is signed over the request's number. Nothing is handed to a request that isn't so signed, and the add-on does
  nothing an answer that isn't tells it. Edits use the editor's own commands, so
  Thunderbird's undo works.
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
  "scratch that", is then what really went in. If the desktop refuses, or has no such
  portal, the target's `problem` says so for the person, and the question is put again
  after five minutes.
- **The program has to be asked to describe itself.** Chromium keeps its accessibility
  tree off unless started with `force-renderer-accessibility`. VS Code reads that from
  `argv.json`, which `vscode_args.py` edits: for the app, which adds the line when
  "other programs" is ticked (`switch_on`) and tells the person to restart VS Code, and
  for the uninstaller, which takes it out again (`--remove`). With the box ticked, the
  app looks again each time it starts, for a VS Code that was first run later. The
  installer leaves the
  file alone. The line goes in with a comment above it, and only a line with that
  comment is ever taken out: one a person wrote themselves is theirs.

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
words in one of four ways, by what the program in front is:

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
| `python3 -m unittest discover -s tests -t .` | All the rules, and the app's own windows, made off screen with a stand-in engine and a throwaway folder for settings | Python and numpy (and `cryptography` for the tests of the link to another computer, and PyQt6 for those of the windows: each is skipped without it) |
| `PYTHONPATH=. scripts/test-writer.sh` | The Writer extension, in a hidden LibreOffice with a throwaway profile | LibreOffice |
| `PYTHONPATH=. PYTHON=~/linux-speaking/venv/bin/python scripts/test-writer.sh scripts/engine_test.py` | The engine end to end, with synthesized speech | The above, an install, libespeak-ng |
| `scripts/test-thunderbird.sh` | The add-on's editing code, in headless Firefox | Firefox |
| `PYTHONPATH=. scripts/test-thunderbird-e2e.sh` | The whole add-on, in a throwaway Thunderbird profile | Thunderbird |
| `PYTHONPATH=. scripts/test-vscode.sh` | The VS Code extension, in a separate VS Code window with its own settings, which shows briefly | VS Code, a desktop session |
| `PYTHONPATH=. scripts/test-form.sh` | Any program's text boxes, using a small form window that shows briefly | PyQt6, a desktop session |
| `PYTHONPATH=. scripts/test-editor.sh` | Kate's editor, using a scratch KWrite window that shows briefly | KWrite, a desktop session |
| `PYTHONPATH=. scripts/test-click.sh` | "Click OK": a scratch window with a button and a tick box, pressed by their names; it shows briefly | PyQt6, a desktop session |
| `venv\Scripts\python.exe app\scripts\word_test.py` (on Windows, in the install folder) | Word, using a blank document of its own that it closes unsaved | Word |
| `venv\Scripts\python.exe app\scripts\outlook_test.py` (the same) | An Outlook message, using a new one of its own that it discards | Classic Outlook, open |

`scripts/deploy.sh user@host` installs or updates another computer over ssh, which is
handy when you develop on one machine and dictate on another.

## Settings and files

| Path | What it holds |
|---|---|
| `~/linux-speaking/` | The program (`app`), its Python packages (`venv`), the speech models (`models`), the training tools if they were installed (`training`), and the files the installer built for this computer: `linux-speaking-thunderbird.xpi`, `linux-speaking.vsix`, and `pending.oxt` while a Writer extension waits for LibreOffice to be closed |
| `~/linux-speaking/app/requirements.txt` | The Python packages the install runs on, as both installers install them |
| `~/.config/linux-speaking/settings.json` | Your Settings choices, your own words and shortcuts, and the keys for sharing a recogniser: for its owner only. It is written beside itself and then put in place, so it is never half a file; if it is a link to a file kept elsewhere, it stays a link |
| `~/.config/linux-speaking/mail-key` | The key the engine and this computer's Thunderbird add-on prove to each other: for its owner only |
| `~/.local/state/linux-speaking/` | What the app keeps as it runs: whether dictation was on (`state`); the voice test's recording and results; the desktop's leave to press keys (`keys-token`); a note that it was the app that switched the desktop's accessibility on (`accessibility-turned-on`) |
| `~/.local/state/linux-speaking/running` | The lock that sees to it that only one copy of the app runs. It holds nothing, and is let go by the system when the app ends, however it ends |
| `~/.local/state/linux-speaking/show` | Requests left for the running app, by the menu entry and by `control.py`. It is taken away as soon as it is read |
| `~/.local/state/linux-speaking/log.txt` | The log, on a system without systemd. With systemd it is in the journal |
| `~/.local/state/linux-speaking/training/` | Sentences read aloud for training: a folder for each day, with each one's sound and `said.txt`, the list of what was read |
| `~/.local/state/linux-speaking/noises/` | Sounds that were written as words and marked "that was a noise": the last 300, for its owner only. Each is named by a count and the time in UTC, as in `noise-000123-20261118T051809Z.wav`, and `list.txt` has a line for each with what it was written as. Only files so named, and those named by date and time alone that earlier versions kept, are the app's to count and remove |
| `~/.local/state/linux-speaking/training-runs/` | A folder for each retraining: its notes, its log, and while it is unfinished the model as it stands (about 2.4 GB) |
| `~/.config/systemd/user/linux-speaking.service` | The login service, where there is systemd |
| `~/.local/share/applications/linux-speaking.desktop` | The menu entry, which runs `scripts/launch.sh` |

On Windows all of it is in the install folder, `linux-speaking` in your user folder: the
settings beside the program, and the rest in `state`, with the engine's log (`log.txt`).
There is no lock file there: a named mutex does that job.

Advanced settings are environment variables beginning `LS_`. Most are listed in
`dictation/config.py`. A few are read where they are used: `LS_KEEP_FINAL` (keep a phrase's
last full stop) and `LS_LOG_PHRASES` in `engine.py`, `LS_WINDOW_ICON` in `tray.py`,
`LS_TRAIN_PARTS` in the trainer, and `LS_OFFICE_TEST_WINDOW` in `word_target.py`, which
is for its test.
