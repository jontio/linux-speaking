# Changelog

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
