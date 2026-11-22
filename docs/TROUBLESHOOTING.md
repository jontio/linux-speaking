# If something isn't working

For Linux and for Windows. Back to the [README](../README.md).

- [Look here first](#look-here-first)
- [On either system](#on-either-system)
- [On Linux](#on-linux)
- [On Windows](#on-windows)
- [When the installer stops](#when-the-installer-stops)
- [The log](#the-log)
- [Settings that are environment variables](#settings-that-are-environment-variables)
- [Reporting a problem](#reporting-a-problem)

## Look here first

Five things say what the program is doing:

- **The tray icon.** Purple with dots: loading. Red with a line through it: off, the
  microphone is closed. Orange with a "z": asleep, listening only for "wake up". Green:
  awake. Grey with a yellow "!": no speech model could be loaded.
- **The tray icon's tip.** Rest the mouse on the icon. It says the state, what was last
  heard, which program it is typing into while awake, and anything that is wrong and
  stays wrong, each with what to do about it: a speech model that won't load, a
  microphone that stopped, Thunderbird's add-on being an older one, the desktop not
  letting keys be pressed, a part missing for Word and Outlook, other computers not
  being able to use this one for recognition.
- **The top of Settings** lists the same things, and also a Writer extension that is
  waiting or couldn't be put in, and a key that Windows wouldn't give. A button beside
  them opens the log.
- **Notices.** A brief notice appears on screen when you said something and there was
  nothing in front to type it into, when a command couldn't be done, when the
  microphone can't be opened or stops, and when a speech model won't load. It says what
  to do.
- **Getting started**, in the tray icon's menu, opens the welcome window again. It shows
  the microphone's level, and has a box to try dictating into, which needs no other
  program: if words appear there, the microphone and the speech model are working.

## On either system

- **You talk and nothing is typed.** If the icon is not green, it isn't awake: say "wake
  up", or click the icon. If it is green and a notice says there is nothing to type
  into, the window in front is not one it has a link to. Click into one of the programs
  it works with, or tick **Dictate into other programs' text boxes** in Settings:
  see [Programs](PROGRAMS.md). The terminal you installed from, and a web browser, are
  not among them without that setting. The notice comes once a minute at most; the
  icon's tip says "(nothing to type into)" after each phrase that had nowhere to go.
- **Nothing is typed, though the icon is green.** If the icon has a **C** on it,
  **Commands only** is ticked in Settings (in the My shortcuts and commands box), and
  only commands are acted on. Untick it to dictate.
- **A command of my own does nothing.** Its words have to be said by themselves, exactly
  as written before the equals sign. Settings lists under the box any line it couldn't
  understand, and why. A line with `run:` needs **Let my own commands run programs**
  ticked. On Linux, pressing keys needs the desktop's leave: it asks the first time.
- **"Wake up" is ignored.** Open the microphone level from the tray icon's menu and
  speak. The bar should turn green. If it barely moves, or stays grey or blue, the
  microphone is too quiet or the wrong one is selected: in your desktop's sound settings
  on Linux, in Linux Speaking's own Settings on Windows. If it turns orange or red, it
  is too loud. Close the microphone level afterwards: dictation is off while it is open.
  It has to be "wake up", said by itself: "wake me up", "woke up" and "make up" don't
  wake it. It is the model you chose that listens for it: if it often misses, try
  another model in Settings.
- **The icon is grey with a "!", and its tip says "No speech model".** The tip says why,
  and what to do. If no model is installed, or one was cut short, open Settings and
  press **Install or remove models**. If a part the recogniser needs is missing, run
  the installer again: it puts right Python packages that no longer load. Once a model
  is there, loading is tried again by itself the next time the microphone hears a
  sound.
- **In a noisy room, what you say is acted on late.** A phrase is ended by the pause
  after it. Where the room hides the pause (keys being pressed, a fan, a microphone that
  turns itself up when you stop) the program sees your voice itself stop, and ends the
  phrase a little under a second after it. Other people talking near by are another
  matter: at about a fifth of your loudness at the microphone or less they are left
  out, but louder than that it can't tell them from you going on, and waits for them to
  pause. A headset, or a microphone nearer your mouth, is the cure for that. [The
  log](#the-log) says how each such phrase ended, and how loud the voice and the room
  were.
- **The icon is purple.** A speech model is being loaded. That takes a few seconds, and
  longer for a big model. What you say meanwhile waits, and is dealt with when the
  model is ready.
- **A notice says a model could not be loaded.** The model you chose wouldn't load, so
  dictation has stayed with the one that was in use, and Settings shows that one again.
  If it happens again with the same model, remove that model and install it afresh,
  from **Install or remove models**.
- **The icon is red and won't go green.** The microphone could not be opened, and a
  notice said why. Check that one is plugged in and chosen, then click the icon again.
- **A click on the icon, or the key, doesn't wake it, and a notice says a recording is
  being made.** The reading window or a voice-test recording has the microphone, and
  dictation beside it would type what is read aloud. Pause the reading, or stop the
  recording, first.
- **A notice says the microphone stopped.** It was unplugged, or the sound system was
  restarted. Dictation is switched off, and comes back asleep by itself when the
  microphone can be opened again: it is tried every two seconds for three minutes. Say
  "wake up" and carry on. If it stopped three times within a minute it is not tried
  again by itself: click the icon when the microphone is steady.
- **A command is typed as words.** A command has to be a phrase by itself, with a short
  pause before and after. Check too that it is ticked in Settings. "What can I say?" in
  the tray icon's menu lists what is understood.
- **A command does nothing, and a notice says the program can't do it.** The program in
  front has no such command: "duplicate line" and "comment line" are VS Code's only,
  and plain text has no bold. [Commands](COMMANDS.md#the-commands) says which work
  where.
- **A sentence that begins with "Select" or "Correct" selected something.** The words
  after it were found near the cursor, so it was taken for the command, and a notice
  said what was selected. Say "unselect that", and say the sentence in two parts.
- **The spelling box is slow to show a letter.** It measures over its first three
  letters how long the Medium model takes on this computer, and goes over to the Small
  one if that is more than a second, so the fourth letter on should be quicker. The
  log says so when it does. **Or it mishears more letters than it did:** it may have
  gone over to Small on a day the computer was busy. What it found is in the file
  `spelling-speed.json` (on Linux in `~/.local/state/linux-speaking`, on Windows in
  the `state` folder of the install folder): delete it and restart the program to have
  it measured again. The limit can be changed with
  `LS_SPELL_SLOW`, in seconds, [as below](#settings-that-are-environment-variables):
  a big number keeps Medium whatever it takes.
- **It writes "yeah" or "okay" when you made a noise.** See
  [Noises written as words](MODELS.md#noises-written-as-words).
- **The other computer is no longer used for recognition.** Both computers need this
  version of Linux Speaking, or a later one on each: the way they talk has changed, and
  a version from before is told to update. Settings says what is wrong under the
  address; meanwhile each computer does its own listening. See
  [Using another computer](OTHER-COMPUTER.md#if-it-stops-being-used).

## On Linux

- **Nothing works in Writer after an install or an update.** If LibreOffice was open at
  the time, the new extension is waiting, and the tray icon's tip says so. Save your
  work and close LibreOffice. A notice says "Writer is ready" when the extension is in,
  after ten seconds or so, and LibreOffice can then be opened again. If the extension
  can't be put in, a notice says so once and the top of Settings says why.
- **Writer never takes dictation.** Check that it is the LibreOffice from your
  distribution's packages. One installed as a Flatpak or a Snap can't be reached.
- **Kate isn't picked up.** Close Kate and start it again from the application menu, not
  from a terminal.
- **VS Code isn't picked up.** Restart VS Code, and check that "Linux Speaking" is in its
  Extensions list. If not: `code --install-extension ~/linux-speaking/linux-speaking.vsix`.
  A VS Code installed as a Flatpak can't be reached, because of its sandbox.
- **Thunderbird takes nothing, or stopped taking dictation after an update.** Its add-on
  has to be the one the installer made for this computer, with this computer's key in
  it. Add it again from `~/linux-speaking/linux-speaking-thunderbird.xpi` (Add-ons and
  Themes, the gear icon, Install Add-on From File) and open a new message. When this is
  the cause, the tray icon's tip and the top of Settings say "Thunderbird's add-on is an
  older one", or that it was made for another key, and the log says the same. That
  line goes as soon as the right add-on connects.
- **Thunderbird uses the processor all the time after an update.** The add-on from an
  earlier version is still installed. Remove it in Thunderbird, under Add-ons and
  Themes, and add the new one from its file, as above. An old add-on asks again the
  moment it is answered. This version keeps it waiting between its requests, and has
  Thunderbird keep nothing of the answers; an earlier one answered it at once, and
  Thunderbird then kept a file on the disk for every answer, which came to over a
  million in a day.
- **The tip says dictation into Thunderbird is off.** Another program is using the port
  on this computer that the add-on calls, 47613. Close that program, then quit Linux
  Speaking from the tray icon's menu and start it again.
- **Nothing is typed into VS Code's chat box or terminal.** Tick **Dictate into other
  programs' text boxes** in Settings, then close VS Code and open it again. The desktop
  also has to let Linux Speaking press keys: if the tip says it didn't, see
  [VS Code's panels](PROGRAMS.md#vs-codes-panels-and-other-programs-built-from-a-web-browser).
- **Text deletes itself in VS Code, or another program beeps continuously.** A key is stuck
  held down in the desktop's X11 layer. This can happen after using a remote or on-screen
  keyboard, such as KDE Connect's. Press that key once on a real keyboard, usually
  Backspace, or log out and back in.
- **There is no tray icon.** The desktop has no system tray, as GNOME as it comes has
  none. A small window called Linux Speaking then stands in for the icon, a quarter of
  a minute after the program starts: it says what dictation is doing, shows the
  notices, and has the menu's entries as buttons. It can be minimised, but not closed.
- **The icon is grey with a "!" after a distribution upgrade.** The system's Python is a
  newer one, and the old Python packages no longer load. The tip says that a part the
  recogniser needs is missing. Run the installer again.
- **The menu entry does nothing.** Run `~/linux-speaking/app/scripts/launch.sh` in a
  terminal and read what it says. If the program is already running, the menu entry
  only shows its Settings window: it never runs twice.
- **To see what each program's link answers** when asked whether it is in front:
  `systemctl --user kill -s USR1 linux-speaking`, then look at the log.

## On Windows

- **Nothing is typed into Notepad, a web page, or the new Outlook.** Those are "other
  programs": tick **Dictate into other programs' text boxes** in Settings. Without it,
  only Word, classic Outlook and Visual Studio Code are typed into.
- **The level doesn't move when you talk.** Choose your microphone in Settings: Windows'
  default recording device isn't always the one you expect. Check Windows' own privacy
  switch as well: in Windows' Settings, under Privacy and security, then Microphone,
  "Let desktop apps access your microphone" must be on. When Windows won't open the
  microphone at all, a notice says so and names that switch.
- **A headset isn't in the list of microphones.** Press **Look again** beside the
  chooser in Settings. Windows gives a fresh list only while nothing is being recorded,
  so listening stops for a moment while it is read. (When Settings opens, the list is
  read only as far as Windows allows without that.) If the microphone can't be opened
  again afterwards, a notice says so, and it is tried again every two seconds. A
  microphone you chose that is not plugged in now is shown as "(not connected now)",
  and Windows' default device is listened to meanwhile.
- **There is no icon.** Look behind the little arrow by the clock, and drag the icon out
  onto the taskbar.
- **The Start menu shortcut does nothing.** The Python it was installed with has been
  removed or replaced. Run the installer again: it sets the install's Python up afresh.
  (If Linux Speaking is already running, the shortcut shows its Settings window.)
- **The key no longer types what it used to.** The key chosen for switching dictation is
  handed to Linux Speaking alone. Choose another, or "None", under Keyboard in Settings.
- **The key chosen for switching dictation does nothing.** Another program has that key,
  and Windows wouldn't give it. Settings says so beside the chooser and at its top.
  Choose another key.
- **Nothing is typed into a Word document.** Word may have opened it in a way that
  doesn't allow changes, such as Protected View. Let Word edit it, and try again.
- **The tip says dictation into Word and Outlook is off.** A part it needs is missing
  from the install. Run the installer again.
- **VS Code isn't picked up.** Restart VS Code, and check that "Linux Speaking" is in its
  Extensions list. If not, in PowerShell:
  `code --install-extension "$env:USERPROFILE\linux-speaking\linux-speaking.vsix"`.
- **Task Manager shows no "Linux Speaking".** It runs under the name Python.

## When the installer stops

Both installers stop at the first thing that goes wrong and say what it was. Running
them again is safe, and carries on from what is already there.

- **"There isn't enough free disk space" (Linux).** A first install wants about 1.5 GB
  in your home folder.
- **"Linux Speaking needs Python 3.10 or newer", or "No Python on this PC will do".** On
  Linux, the system's Python is too old: a newer distribution is needed, or a newer
  Python named with `LS_PYTHON`. On Windows, run the installer in a PowerShell window and
  it offers to fetch one for itself; or install a 64-bit Python between 3.10 and 3.14
  from python.org beside what is there.
- **"This Python can't find PyQt6 or numpy" (Linux).** The Python it names is not the
  system's own, or the system packages are missing. See what `LS_PYTHON` is set to.
- **The system packages could not be installed (Linux).** The lines above the message
  are the package manager's own. When they are put right, run it again; or install the
  packages yourself and run it with `LS_SKIP_PACKAGES=1`.
- **The Python packages could not be installed.** If it was the connection, run it
  again. If a package "could not be found" or "failed to build", there may be none made
  yet for your version of Python: please open an issue with those lines.
- **A speech model could not be downloaded.** What arrived is kept, and running the
  installer again carries on. On a network that doesn't allow the download at all, see
  [Copying the speech models in by hand](MODELS.md#copying-the-speech-models-in-by-hand).
- **"This folder is ... and Linux Speaking installs itself into ...".** The folder you
  are installing from is the one it installs into. Rename or move it, as the message
  says.
- **PowerShell won't run the script (Windows).** Use the whole line from the
  instructions, with `-ExecutionPolicy Bypass`. On a PC managed by an employer a policy
  may still forbid it, and then it can't be installed there without their leave.

## The log

A log of what the engine is doing. Dictated text is never written to it, only its
length. The notices that were shown are in it too, without any words that were said or
written: after "select" it has only how many characters were selected, and a command
that couldn't be done goes by its name.

**Open the log**, in the tray icon's menu, shows what has been written since the
program started, the last 800 lines of it, with the time of each. **Copy all** there
takes it for a report, with the version, your system, the Python and the speech model in
use put at its head. The whole log is here:

- **Linux:** `journalctl --user -u linux-speaking -f`. On a system without systemd it is
  the file `~/.local/state/linux-speaking/log.txt`.
- **Windows:** the file `state\log.txt` in the install folder, which is
  `C:\Users\you\linux-speaking\state\log.txt` unless you installed elsewhere.

**To see why "wake up" was missed,** turn on extra logging by setting `LS_LOG_PHRASES`
to `1`, as described next, and restart the program. The log then shows the length and
loudness of each phrase heard while asleep, and the text of phrases of three words or
fewer. It is off by default.

## Settings that are environment variables

A few settings for unusual cases are environment variables, such as `LS_LOG_PHRASES`
above, or `LS_SHARE_PORT` for [another computer](OTHER-COMPUTER.md). The program starts
by itself, not from a terminal, so the variable has to be put where it will find it.

**On Linux**, where it runs as a service: `systemctl --user edit linux-speaking`, add
the two lines

```
[Service]
Environment=LS_LOG_PHRASES=1
```

and restart it with `systemctl --user restart linux-speaking`. To undo it, run the same
command and take the lines out. (Without systemd: stop it, then start it with the
variable in front, as in `LS_LOG_PHRASES=1 ~/linux-speaking/app/scripts/launch.sh start`.)

**On Windows**, in PowerShell:

```
[Environment]::SetEnvironmentVariable("LS_LOG_PHRASES", "1", "User")
```

Then quit Linux Speaking from the tray icon's menu and start it again from the Start
menu. To undo it, the same line with `$null` in place of `"1"`, and restart it again.

## Reporting a problem

Open an issue on GitHub. What to include is listed in
[CONTRIBUTING.md](../CONTRIBUTING.md#reporting-a-problem): in short, your system, the
program you were dictating into, what you said and what happened, and the lines of the
log from that moment. If an installer failed, include everything it printed.
