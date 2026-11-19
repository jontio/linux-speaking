# Linux Speaking on Windows

The same speech engine runs on Windows 10 and 11. The name says Linux because that is
where it began; this page is all you need to use it on Windows. For Linux, see
[Linux Speaking on Linux](LINUX.md). Back to the [README](../README.md).

- [What it dictates into](#what-it-dictates-into)
- [What you need](#what-you-need)
- [Installing](#installing)
- [The first run](#the-first-run)
- [Things to know](#things-to-know)
- [The installer's options](#the-installers-options)
- [On a work network](#on-a-work-network)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [How well tested is it?](#how-well-tested-is-it)

## What it dictates into

- **Microsoft Word**,
- **classic Outlook**, in a message you are writing, whether in its own window or as a
  reply in the reading pane,
- **Visual Studio Code**, with everything described for it in [Programs](PROGRAMS.md)
  and [Programming in C and C++](PROGRAMMING.md),
- **any other program's text boxes**, such as Notepad or a chat box in a web page, once
  you tick **Dictate into other programs' text boxes** in Settings. It is off to begin
  with, so without Word, classic Outlook or VS Code, tick it first: until then nothing
  is typed anywhere else, and a notice tells you so.

Word and Outlook are reached the way Dragon reached them, through Word's own automation
interface, so the spacing, capitals, "select", "scratch that" and "undo that" all work
as they do in LibreOffice Writer. When "select" finds several places, small yellow
numbers appear over them on screen.

LibreOffice and Thunderbird have no link of their own on Windows yet. They can be
dictated into as other programs' text boxes.

## What you need

- **To speak English.** Dictation and the spoken commands are in English only.
- **Windows 10 or 11 on a 64-bit Intel or AMD processor.** A PC with an ARM processor
  won't do: the packages it runs on are not made for one.
- **Python, 64-bit, version 3.10 to 3.14**, installed before you start: from
  [python.org](https://www.python.org/downloads/windows/) (the "Windows installer
  (64-bit)") or from the Microsoft Store. The installer turns away a 32-bit Python, one
  for ARM, and versions older or newer than those, and says which it found.
- **A microphone.** A headset works best.
- **About 1.5 GB of disk space** in your user folder: some 650 MB for the two speech
  models the installer fetches, and the rest for the Python packages. The recommended
  model, Parakeet Unified, is another 660 MB when you fetch it. (Round figures.) A PC
  that is short of space, or slow, can do without the models and have
  [another computer do the recognising](OTHER-COMPUTER.md#a-small-computer-with-no-speech-model-of-its-own):
  the installer asks.
- **An internet connection for the install.**
- **Leave to run a PowerShell script.** The command below asks for it for that one run.
  On a PC managed by an employer, a policy may forbid it, and PowerShell then says so.

Nothing needs administrator rights.

## Installing

1. **Install Python** if it isn't there (see above).
2. **Get this repository.** On its GitHub page, click the green **Code** button, then
   **Download ZIP**, and extract the ZIP. Or clone it with git. Either way, the folder
   must not be `linux-speaking` in your user folder (`C:\Users\you\linux-speaking`):
   that is where the program installs itself, and the installer says so and stops if it
   is run from there. A ZIP extracts under another name, so this only matters if you
   clone: `git clone https://github.com/jontio/linux-speaking linux-speaking-source`.
3. **Open PowerShell in that folder.** In File Explorer, open the folder, click in the
   address bar, type `powershell` and press Enter.
4. **Run the installer:**

   ```
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

It first asks one question: **Download the speech models now?** Press Enter for yes. Say
no on a PC that is to leave the recognising to another computer, or to fetch models
later from Settings. It asks once: an update keeps what you answered.

It says which Python it is using, then:

1. copies the program into `linux-speaking` in your user folder,
2. installs the Python packages it runs on, about 200 MB, shown as they arrive,
3. downloads two speech models (about 650 MB), with a count of how far it has got, unless
   you said no,
4. checks that the speech models load, which takes ten seconds or so,
5. fetches two English dictionaries, which it uses to tell a name from an ordinary word,
6. adds **Linux Speaking** and **Uninstall Linux Speaking** to the Start menu, and a
   shortcut that starts it when you sign in,
7. adds its extension to Visual Studio Code, if that is installed, and says whether that
   worked,
8. starts it.

It takes roughly five to twenty minutes, most of it downloading. If a download is cut short, run
it again: it carries on from where it stopped. If something goes wrong it stops and says
what, in plain words, before it says "Done".

Everything is in the one folder, `linux-speaking` in your user folder: the program
(`app`), its Python packages (`venv`), the speech models (`models`), your settings
(`settings.json`), and what it keeps as it runs (`state`: the log, and anything you
record).

## The first run

A microphone icon appears near the clock. Windows may tuck it behind the little arrow
there: drag it out onto the taskbar to keep it in view. It is purple while the speech
models load, then orange with a "z": asleep, and listening only for "wake up".

The first time, and only then, a **welcome window** opens. It:

- says what to do,
- shows the microphone's level as you speak, so you can see that you are heard,
- has a box to try dictating into, and a tick box for dictating into other programs'
  text boxes,
- has a button that fetches **Parakeet Unified**, the recommended speech model: the best
  so far, quick and with the fewest words wrong (a 660 MB download; see
  [Speech models](MODELS.md)),
- asks **which key**, if any, should switch dictation on and off,
- asks whether it should **start when you sign in**.

Then click into a Word document, an Outlook message you are writing, or a file in Visual
Studio Code, say **"wake up"**, and talk. Say **"go to sleep"** to stop.

The welcome window can be opened again at any time: **Getting started**, in the tray
icon's menu.

## Things to know

- **A key that switches dictation between off and awake**, whichever program is in
  front. A new install has none: choose one in the welcome window, or under Keyboard in
  Settings, from a short list (the number pad's +, Pause, Scroll Lock, F9, Ctrl+Alt+D,
  Ctrl+Alt+Space). While a key is chosen, Windows hands it to Linux Speaking and to
  nothing else: with the number pad's + chosen, that key no longer types a plus, and F9
  no longer does what Word and Outlook use it for. A line under the chooser says what
  the chosen key costs. Choose "None" to have the key back. If another program already
  has the key, Windows won't give it, and Settings says so beside the chooser and at
  its top: choose another. An install from before there was a choice keeps the number
  pad's +, which is what it had, and is not shown the welcome window.
- **Choose your microphone** in Settings if the level doesn't move when you talk.
  Windows' default recording device isn't always the one you expect. For a headset
  plugged in while the app is running, press **Look again** beside the chooser: Windows
  gives a fresh list only while nothing is being recorded, so listening stops for a
  moment while it is read. A microphone you chose that isn't plugged in now is shown as
  "(not connected now)"; Windows' default device is listened to meanwhile, and a notice
  says so.
- **Windows' own privacy switch** has to allow it: in Windows' Settings, under Privacy
  and security, then Microphone, "Let desktop apps access your microphone" must be on.
  If Windows won't open the microphone, a notice says so and names that switch, and
  dictation stays off.
- **If the microphone stops**, because a headset was unplugged, a notice says so.
  Dictation comes back asleep by itself when the microphone can be opened again.
- **Starting when you sign in** is a tick box in Settings, **Start when I sign in**.
- **The tray icon** may be tucked behind the little arrow by the clock. Drag it out to
  keep it in view. A click on it wakes dictation when it is asleep or off, and switches
  it off when it is awake.
- **In Task Manager it is called Python**, because that is the program that runs it.
- **The app's windows and the tray icon's menu can have the look of Windows 10, Windows 7
  (in two colours) or Windows XP**: the title bar, the window's colour, its buttons, tick
  boxes and scroll bars. Choose under Appearance, at the foot of Settings, and every
  window follows. It is drawn by the app itself; only the box for choosing a file stays
  Windows' own.
- **Other programs' text boxes**, such as a chat box in a web page or Notepad, can be
  dictated into by ticking "Dictate into other programs' text boxes" in Settings. The
  words are typed in as keystrokes (Notepad and its like are handed them whole), with
  the spacing and capitals still fitted to what is around the cursor. Nothing is typed
  unless Windows says a text box that can be edited has the keyboard, and never into a
  password box. Here "new line" is Shift+Enter, and "press enter" is the Enter key, which
  in a chat box sends the message. There are no choice numbers and no bold or italic.
- The **new Outlook** (the one with the "New Outlook" switch) only works that way, as
  another program's text box.
- **A document Word won't let be changed** (one it has opened in Protected View, for
  instance) can't be dictated into until Word allows editing.
- **Letting other computers use this one for speech recognition** (see
  [Using another computer](OTHER-COMPUTER.md)) is the one thing that wants an
  administrator: Windows' firewall has to let them in, and asks the first time.

## The installer's options

They are environment variables, set in PowerShell before the installer is run. In
PowerShell that is written like this (the `set` of the old command prompt does nothing
here):

```
$env:LS_NO_AUTOSTART = "1"
powershell -ExecutionPolicy Bypass -File install.ps1
```

| Option | What it does |
|---|---|
| `$env:LS_NO_AUTOSTART = "1"` | Doesn't set it to start when you sign in. `"0"` sets it to start again. Left out, a first install sets it to start, and an update keeps what was chosen before: if the shortcut was removed, by you or by the tick box in Settings, it is not put back. |
| `$env:LS_NO_START = "1"` | Doesn't start it now. |
| `$env:LS_PYTHON = "C:\path\to\python.exe"` | Builds on that Python. A version, such as `"3.12"`, is taken as one for the `py` launcher. Without it, the newest suitable Python is found by itself. |
| `$env:LS_INSTALL_DIR = "D:\apps\linux-speaking"` | Installs there instead of your user folder. It must be a folder of its own: one that doesn't exist yet, or an earlier install. See below. |
| `$env:LS_SKIP_PACKAGES = "1"` | Doesn't install or update the Python packages. |
| `$env:LS_SKIP_MODELS = "1"` | Answers the installer's question about the speech models for you: they are not downloaded, which saves about 600 MB. For installing with nobody at the keyboard. The install finishes without them and says what to do next: see [Using another computer](OTHER-COMPUTER.md#a-small-computer-with-no-speech-model-of-its-own). `"0"` answers yes. |

**Installing outside your user folder.** Your user folder is closed to the PC's other
accounts; a folder elsewhere usually is not. Since the install folder holds your
settings, your recordings and the program itself, the installer closes it to other
accounts when it is put elsewhere, so that only you and the PC's administrators can
open it, and says so. If it can't (a USB stick keeps no permissions at all), it warns
you, and the user folder is the safer place.

## On a work network

Some networks pass everything through a proxy that looks inside it. The installer
downloads the speech models with the app's own downloader, which uses Windows' proxy
settings and Windows' certificates, so this usually just works. If the models still
can't be fetched, the installer says why, keeps what has arrived, and stops. The models
can then be copied in by hand, from another computer or with a web browser: see
[Copying the speech models in by hand](MODELS.md#copying-the-speech-models-in-by-hand).
Run the installer again afterwards and it carries on from there.

If it is the Python packages that can't be fetched, that is pip's doing, and pip has
its own settings for a proxy. The lines it prints say what it could not reach.

## Updating

Download the new version, as when installing, and run the installer again from its
folder. Your settings, speech models and recordings are kept. So is your choice about
starting when you sign in. If Visual Studio Code was open, close it and open it again,
so that it loads the new extension. The first part of the
[changelog](../CHANGELOG.md) for the new version says if anything else is left for you
to do.

If the Python the install was built on has since been removed or replaced, the Start
menu shortcut does nothing at all when clicked. Run the installer again: it notices
that the install's own Python no longer runs, and sets it up afresh.

## Uninstalling

Choose **Uninstall Linux Speaking** in the Start menu. It is a copy of the uninstaller
that the installer keeps in the install folder, so it is there even if you deleted what
you downloaded. Or, in PowerShell:

```
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\linux-speaking\uninstall.ps1"
```

It finds the install folder by itself, wherever you installed.

**It asks before removing what is yours.** If you have read sentences aloud for
training, made a recording for the voice test, marked sounds as noises, or retrained a
model to your voice, it lists them, with how many and how big, and asks whether they
are to go too. Anything but "yes" keeps them where they are, in the install folder, and
a later install into the same folder finds them again. Adding `-Purge` to the command
removes them without asking, and `-Keep` keeps them without asking.

**What it removes:** the program, its Python packages, the speech models, your settings,
the log, the training tools, the three shortcuts (Start menu, uninstall, and starting
at sign-in), and the Visual Studio Code extension. Only what the installer and the app
put in the install folder is taken out of it.

**What is left:** Python itself, which you installed; the folder you downloaded; and
the Visual Studio Code extension if VS Code's `code` command wasn't found, in which
case remove "Linux Speaking" in VS Code's Extensions list.

It ends by saying what it did. If a file was still open somewhere and could not be
removed, it says that, and not that all has gone.

## How well tested is it?

Honestly: only partly. The Windows side is newer than the Linux one.

- **This version's installer has not yet been run from start to finish.** It and the
  uninstaller have been checked for slips of syntax with Windows PowerShell 5.1, and
  read through. The installer of the version before was run, on one Windows 11 PC.
- **The unit tests pass** on Windows 11 with Python 3.11.
- **The program itself has been used on one Windows 11 PC** with Microsoft 365, and
  nowhere else: not with other security programs, and not on a PC whose administrator
  restricts PowerShell.

If something fails for you, please open an issue:
[Troubleshooting](TROUBLESHOOTING.md#reporting-a-problem) says what to include.
