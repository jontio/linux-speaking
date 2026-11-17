# Changelog

## Unreleased

- Runs on Windows 10 and 11, dictating into Microsoft Word, classic Outlook and Visual
  Studio Code. `install.ps1` installs it and `uninstall.ps1` removes it.
- On Windows, a microphone chooser in Settings, and small numbers shown on screen over the
  matches for "select" in Word and Outlook.
- On Windows, the app's windows and the tray icon's menu can be given the look of
  Windows 10, Windows 7 or Windows XP, chosen under Appearance in Settings.
- On Windows, the "other programs" setting types into any text box that has the keyboard,
  such as a chat box, reading what is around the cursor through UI Automation. An empty
  box is read as empty: its hint ("Type a message") and the page around it are not taken
  for text before the cursor, so the first words get their capital and no space in front.
- The Visual Studio Code extension is packaged by a Python script, the same on Linux and
  Windows.
- "My words" in Settings: names and unusual words that get misheard. They are given to
  the recogniser as a hint, and a second listen without the hint keeps an ordinary word
  ordinary.
- On Linux, the "other programs" setting now covers VS Code's panels (an assistant's chat
  box, the terminal) and other programs built from a web browser. Their text boxes are
  read through the accessibility interface and typed into with key presses, which the
  desktop asks you to allow once. The installer switches on VS Code's
  `force-renderer-accessibility` so that its panels can be read.
- On Linux, dictation no longer comes back switched off after the service is restarted
  while it was on.
- A notice says when dictation is switched off, as it already did for awake and asleep.
- On Windows, Notepad and other programs with one of Windows' own edit boxes are read
  and written by messages to the box itself: the words are handed over whole, with no
  keys pressed. Sent as a burst of characters, Windows 11's Notepad wrote the last
  character of the burst for all of them, and sent as fast key presses it dropped some.
  Other programs that aren't built from a browser get key presses at about a hundred a
  second.
- On Windows, Notepad++ can be dictated into. Its editing area is asked for its text by
  message, since it offers nothing through the accessibility interface.
- "Second opinions", a tick box and a trial: each phrase is also heard by Whisper Small,
  and by Medium where the two differ, and the two that agree win. The voice test tries
  the same three together. A computer that shares its recogniser keeps three models
  loaded for guests, so that being asked for three in turn doesn't reload them each time.
- The Distil models are no longer shown the text before the cursor. It made them lose
  their place and leave out whole sentences; without it they are as accurate as the rest.
- Words spoken over a selection are fitted to what is around it. A word double-clicked in
  Word, which takes its space with it, is replaced without the space being lost.
- On Windows the installer fetches English dictionaries, so that an ordinary word in the
  middle of a sentence loses the capital the recogniser gave it.
- "Test them on my voice": read a passage once and see, for every installed recogniser,
  how many words it got wrong on your own voice and how long it took. The window has a
  tab for each step: reading, choosing what to try, and the results. Half of the passage
  is words easily taken for others ("better" and "beta"), and slips that every recogniser
  made alike, which were in the reading, are not counted. It also counts near misses:
  words that came out right, but that the recogniser was less than 90% sure of.
- "Question mark" said by itself after an unfinished question is typed. Whisper wrote a
  bare "?" for it, which was thrown away as no words at all.
- "Quicker recognition", a tick box: Whisper is given only as much sound as the phrase
  needs, which is three or four times quicker. A phrase that goes wrong is done again the
  usual way.
- Parakeet can be installed and chosen as the recogniser: quicker than Whisper and about
  as accurate as its Medium model, English only. The models window also offers NVIDIA's
  newer Parakeet Unified, and each of the two at full precision (2.5 GB), to try against
  the usual one in the voice test.
- In "Read aloud for training", a text read to its end can be gone through again.
- "Read aloud for training", a trial: a window that shows one sentence at a time and
  keeps the sound of each beside its text, as material for retraining a recogniser to
  one voice. Three hundred sentences come with it, or a text file of your own can be
  read. Nothing has to be pressed: it moves on when the recogniser has heard the sentence
  to its end. A sitting can be paused for a rest and carried on, and a later one begins
  where the last left off.
- In Settings, a tick box that would do nothing with the model in use is greyed, and
  says why when the mouse rests on it.
- "Wake" and "sleep" by themselves can stand for "wake up" and "go to sleep": tick
  **Wake, sleep** in Settings. The longer phrases go on working.
- The level meter window opens the microphone by itself, so it works whether dictation
  is on or off, and has the reading window's bar and colours, with each phrase judged in
  words above it. Dictation is off while it is open, and comes back as it was when it is
  closed. It no longer opens by itself when the program starts; a second start of the
  program shows Settings.
- "Train on my voice", a trial: retrains Parakeet (Unified or v2) on the sentences read aloud, from
  a window that asks for the folder, the model to start from and a name for the result.
  It learns from the sentences and from single words cut out of them, runs by itself
  for half an hour or more, can be stopped and carried on, tests the result on sentences
  and single words kept out of the training, and puts it among the speech models. It needs
  training tools of about 2 GB, which the window installs with one button on Linux and
  on Windows.
- Parakeet no longer writes "yeah" for a rustle or a key press. A phrase it writes words
  for is also put to a voice detector, and one with no speech in it is left out. "Leave
  out sounds that aren't speech" in Settings switches that off.
- Whisper uses one thread for each processor core, not two, which is quicker on small
  processors.
- Another computer can do the speech recognition: one shares its recogniser, the other
  sends it each phrase over the network and carries on by itself if it can't be reached.
- Speech models can be installed and removed from Settings: nine of them, from Tiny to
  Large, downloaded from Hugging Face and checked before use.
- On Windows, the number pad's + key switches dictation between off and awake, whichever
  program is in front. A setting turns this off and gives the key back.
- A full stop, question mark or exclamation mark said after a short pause is no longer
  lost now and then. The last words of such a phrase are listened to again by themselves.
- On Windows the program's windows carry its own name and icon on the taskbar, also
  when Python came from the Microsoft Store, which used to show Python's. "Awake" and the
  other notices are small pop-ups of its own by the clock, no longer Windows
  notifications labelled Python.
- "Enter" by itself can press the Enter key, like "press enter". It is a setting, off to
  start with.
- "Correct that" highlights the last phrase, the same as "select that". What is said
  next takes its place.
- Words spoken over a phrase highlighted with "select that" keep the space before them.
  In Word and Kate the highlight no longer takes in that space.
- "Space" said by itself types a space, and "space 3" three of them.
- "Hello Bob", not "Hello, Bob": the comma the recogniser puts between a greeting and a
  name is left out. A setting brings it back.
- "Select" finds words that sound the same as the one heard, and numbers written either
  way: "select two" finds "2", "two", "to" and "too".
- "Cancel" takes away the numbers shown for "select" without typing anything.
- Text before the cursor that is one word over and over is no longer shown to the
  recogniser, which used to carry on repeating it whatever was said.
- On Windows, a passing error from Word no longer sends the next words to be typed in as
  keystrokes, and the log says which program is being typed into and what an error was.
- Clicking the tray icon when dictation is off turns it on awake, ready to talk, not
  asleep.

## 0.5.0

- Dictation into Visual Studio Code, with extras for Markdown: capitals after heading and
  list markers, lists that carry on with "new line", and bold and italic as `**` and `*`.
- Coding by voice in C and C++ files in VS Code: spoken symbols, C-style spacing,
  indentation, and names recognised from the file. One setting switches it on or off.
- With a C/C++ language server such as clangd in VS Code, misheard names are corrected to
  the ones in scope, and keywords and numbers are judged by where the cursor is.
- An optional setting to dictate into any Qt or GTK program's text boxes, through the
  desktop's accessibility interface. Password boxes are refused.
- Speaking over a selection no longer adds spaces around the replacement.
- "Move left 3 words" and "move right 3 words".
- "Select all" and "tab".
- "Move to" and "jump to" work wherever "go to" does.
- Line commands: up and down by lines, go to line, select line, delete line, and in
  VS Code duplicate line, indent, outdent and comment line.
- "Press enter" is a single line break in plain-text editors.
- The tray icon is red when off, orange when asleep and green when awake.
- A demo video, linked from the README.
- Fixed: faint noises could wake it up.

## 0.4.0

The first public release.

- Dictation into LibreOffice Writer, Thunderbird messages, Kate and KWrite, sent to
  whichever is in front.
- "Wake up" and "go to sleep" by voice.
- Spacing, capitals and punctuation words fitted to the text around the cursor.
- Editing commands: scratch that, undo that, backspace, delete last word, delete that,
  select with numbered choices, select that, unselect that, spell that.
- Cursor commands by line, paragraph and document.
- Formatting commands: cap, all caps, no caps, bold, italic, underline.
- A tray icon with a microphone level meter that turns red when the signal is too loud.
- A Settings window to switch commands and punctuation words on and off and to choose the
  speech model.
- An installer and uninstaller for KDE Plasma desktops.
