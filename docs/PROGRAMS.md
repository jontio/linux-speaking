# Programs

Which programs can be dictated into, how they differ, and how to dictate into the rest.
Back to the [README](../README.md).

- [The programs with a link of their own](#the-programs-with-a-link-of-their-own)
- [Differences between programs](#differences-between-programs)
- [Other programs](#other-programs)
- [VS Code's panels, and other programs built from a web browser](#vs-codes-panels-and-other-programs-built-from-a-web-browser)

## The programs with a link of their own

These are reached directly, so that the text around the cursor can be read and the words
fitted to it, and so that commands such as "select" and "scratch that" work.

| Program | On | How it is reached |
|---|---|---|
| LibreOffice Writer | Linux | An extension, which the installer adds |
| Thunderbird | Linux | An add-on, which you add by hand, once: see [the one manual step](LINUX.md#the-one-manual-step-thunderbird) |
| Visual Studio Code | Linux and Windows | An extension, which the installer adds |
| Kate and KWrite | Linux | The desktop's accessibility interface |
| Microsoft Word | Windows | Word's own automation interface |
| Classic Outlook | Windows | The same, in a message you are writing |

On Linux they have to be the programs from your distribution's packages. A LibreOffice
or a VS Code installed as a **Flatpak or a Snap can't be reached**, because such a
program is shut off from the rest of the desktop.

For anything else, there is one setting: see [Other programs](#other-programs).

## Differences between programs

- **Kate and KWrite** are plain text, so there is no bold or italic, "new paragraph" leaves
  a blank line, and "select" takes the nearest match without showing numbers. Start them
  from the application menu, not a terminal, or dictation can't see them.
- **Thunderbird** works in the message body only, not the address or subject boxes. If
  its add-on is one from an earlier version, nothing is typed there, and the tray
  icon's tip and the top of Settings say to add it again.
- **Visual Studio Code** is treated as plain text, with extras for Markdown files. After a
  heading or list marker the next words start with a capital. "New line" inside a list
  starts the next item, and on an empty item ends the list. "Bold that" and "italicize
  that" wrap the words in `**` and `*`. Words go into the file you have open, even if the
  keyboard is in the terminal or chat panel. In C and C++ files it switches to rules for
  source code: see [Programming in C and C++](PROGRAMMING.md).
- **Visual Studio Code and Thunderbird** look for the words of "select" and "correct"
  themselves, and for exactly those words. So a few things that are found elsewhere are
  not found there: "U.S." when the recogniser writes what you said as "US", without the
  dots, and a word said without the apostrophe or accent it is written with. See
  [Selecting and correcting](COMMANDS.md#selecting-and-correcting).
- **Word and classic Outlook**, on Windows, work as Writer does. When "select" finds
  several places, small yellow numbers appear over them on screen. "Cap that" there is
  Word's own title case, which brings an acronym down: "NASA" becomes "Nasa", where the
  other programs keep it.
- **A command the program in front hasn't got** is not typed as words. A notice says
  that the program can't do it.

## Other programs

For programs without their own link, there is a setting, off by default: **Dictate into
other programs' text boxes**. With it on, when none of the programs above is in front,
your words go into whichever text box has the keyboard, with the same spacing, capitals
and commands as in Kate.

Password boxes are always refused. A one-line box turns "new line" into a space. As in
Kate, "select" takes the nearest match.

**On Linux** it works with Qt and GTK programs. It uses the desktop's accessibility
interface, the one screen readers use. Ticking the setting switches that interface on,
if it was off, and unticking it switches it back off. (The desktop may remember the
switch from one login to the next. Uninstalling puts it back as well.) A program that
was already open when you ticked the setting may not show its text boxes until it has
been closed and started again. It does not work in terminal programs such as Konsole,
or in Firefox. Ticking it also sets Visual Studio Code up to have its panels dictated
into, if VS Code has been run on this computer: see
[below](#vs-codes-panels-and-other-programs-built-from-a-web-browser).

**On Windows** the words are typed in as keystrokes (Notepad and its like are handed
them whole), with the spacing and capitals still fitted to what is around the cursor.
Nothing is typed unless Windows says a text box that can be edited has the keyboard.
Here "new line" is Shift+Enter, and "press enter" is the Enter key, which in a chat box
sends the message. There are no choice numbers and no bold or italic. The new Outlook
(the one with the "New Outlook" switch) only works this way.

## VS Code's panels, and other programs built from a web browser

This part is for Linux.

The same setting covers the text boxes that Qt and GTK don't draw: the chat box of an
assistant in VS Code, VS Code's terminal, and the boxes of programs built from a web
browser. In VS Code that is only while no file is the one in front in its editor: with a
file there, your words go into the file through VS Code's own extension, wherever the
keyboard is. (A chat that is open as a tab of its own, in front of the files, counts as
no file in front.)

These programs let their text boxes be read through the accessibility interface, but not
written. So Linux Speaking reads what is around the cursor there, and types the words as
key presses. The grey hint in an empty box ("Type a message") is not taken for text: the
first words get their capital and no space in front.

Two things have to be set up, once each:

1. **The program has to describe its text boxes**, which it only does if asked when it
   starts. For VS Code that is one line in `~/.vscode/argv.json`:

   ```json
   "force-renderer-accessibility": true
   ```

   Linux Speaking adds it when you tick **Dictate into other programs' text boxes**, if
   VS Code has been run on this computer, with a comment above it saying whose it is. A
   notice then says to close VS Code and open it again, which it needs before the line
   takes effect. If VS Code is first run after you ticked the setting, the line goes in
   the next time Linux Speaking starts, with the same notice. (The installer doesn't
   touch that file. In VS Code, **Preferences: Configure Runtime Arguments** opens it.)
   Nothing else about VS Code changes, and it
   goes on updating as usual. If VS Code asks whether you are using a screen reader, say
   no. Uninstalling Linux Speaking takes the line out again, if it was Linux Speaking
   that put it there. Chrome and its relatives take the same switch on their command
   line, `--force-renderer-accessibility`.

2. **The desktop has to allow Linux Speaking to press keys.** On a Wayland desktop no
   program may type into another without leave. The first time you dictate into such a
   box, the desktop asks whether Linux Speaking may control the keyboard. Allow it, and
   let it be remembered. Your first phrase waits for the answer, for up to 25 seconds,
   and is then typed; if you took longer, say it again. Only the keyboard is asked for:
   nothing is seen of the screen. To take the leave back, delete
   `~/.local/state/linux-speaking/keys-token` and the desktop will ask again.

What to know:

- It has been tried with VS Code on KDE Plasma (Wayland). Other programs built from a
  browser should behave the same once started with the switch, but haven't been tried.
- The leave to press keys is asked of the desktop through its "remote desktop" service.
  A desktop that has none, or whose service can't press keys, can't give it, and nothing
  can then be typed into these boxes. The same goes if you answer no. The tray icon's
  tip and the top of Settings then say that the desktop didn't let it press keys, and
  the desktop is asked again the next time you dictate into such a box, five minutes
  later or more. [The log](TROUBLESHOOTING.md#the-log) has the desktop's own reason.
- A character the keyboard hasn't got is typed plain: "café" as "cafe", curly quotes as
  straight ones, a long dash as a hyphen.
- In a chat box "new line" is Shift+Enter, and "press enter" sends the message, as the
  Enter key does there.
- "Scratch that" takes back the last phrase only while it is still what is just before
  the cursor. After "correct ..." the cursor has gone back from the phrase: then it is
  taken back, and the old words typed again, as long as the text between the two is as
  it was. See [Selecting and correcting](COMMANDS.md#selecting-and-correcting).
