# Changelog

## Unreleased

- Runs on Windows 10 and 11, dictating into Microsoft Word, classic Outlook and Visual
  Studio Code. `install.ps1` installs it and `uninstall.ps1` removes it.
- On Windows, a microphone chooser in Settings, and small numbers shown on screen over the
  matches for "select" in Word and Outlook.
- On Windows, the "other programs" setting types into any text box that has the keyboard,
  such as a chat box, reading what is around the cursor through UI Automation.
- The Visual Studio Code extension is packaged by a Python script, the same on Linux and
  Windows.
- "My words" in Settings: names and unusual words that get misheard. They are given to
  the recogniser as a hint, and a second listen without the hint keeps an ordinary word
  ordinary.
- On Windows, the number pad's + key switches dictation between off and awake, whichever
  program is in front. A setting turns this off and gives the key back.
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
