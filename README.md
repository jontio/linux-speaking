# Linux Speaking

Voice dictation that works *with* your programs instead of just typing at them. Say
**"wake up"**, talk, and your words go into the document in front of you, with the
spacing and capitals already right for where the cursor is. Edit by voice with commands
like **"scratch that"**, **"select"** and **"spell that"**.

- **English only.** Dictation and the spoken commands are in English. No other language
  is offered.
- **For Linux and for Windows.** On Linux it dictates into LibreOffice Writer,
  Thunderbird, Visual Studio Code, Kate and KWrite. It was built and tested on KDE Plasma.
  On Windows 10 and 11 it dictates into Microsoft Word, classic Outlook and Visual Studio
  Code: see [Linux Speaking on Windows](docs/WINDOWS.md). On both, one setting lets it
  type into other programs' text boxes too.
- **Nothing goes to the cloud.** There is no account and no service behind it: what you
  say is recognised on your own computer, with no graphics card needed. If you have a
  second, faster computer of your own, you can choose to have that one do the
  recognising instead; what goes between the two is encrypted, and goes nowhere else.

[![Watch the demo: writing C in VS Code by voice](docs/images/demo.png)](https://youtu.be/RrhKpiO7YL8)

*Watch the demo on YouTube: a small C program written in VS Code by voice (under 3 minutes).*

![Dictating into LibreOffice Writer](docs/images/writer.png)

It was inspired by how Dragon NaturallySpeaking worked with Microsoft Word: the dictation
program knew what text was around the cursor. Linux Speaking is an independent project and
has no connection with Dragon or its makers.

## What it does

- **Wake up and go to sleep by voice.** No push-to-talk key is needed. While asleep it
  listens only for "wake up".
- **Fits what you say to the document.** Put the cursor after a full stop and the next
  phrase starts with a space and a capital. Put it mid-sentence and it doesn't.
- **Punctuation by name.** "Comma", "full stop", "question mark", "new line", "new
  paragraph".
- **Editing commands.** Scratch that, undo that, redo that, backspace, delete last word. Select a
  word or phrase, then dictate over it to replace it. "Correct" a word further up, and
  the cursor goes back to where you were.
- **Numbered choices.** If "select fox" matches several places, a small number appears
  over each and you say which one.
- **Spell that.** A box opens and you spell a word letter by letter.
- **Your own words and shortcuts.** Names it should know how to spell, and phrases of
  your own that type a text of your own ("my address").
- **"What can I say?"** in the tray icon's menu, or said aloud, opens a list of every
  command that you can search.
- **A tray icon** that shows whether it is off, asleep, awake or hearing you. Rest the
  mouse on it and it says where your words will go, and anything that is wrong. A brief
  notice on screen says when something you said could not be typed or done.
- **A welcome window** the first time, with the microphone's level and a box to try
  dictating into, before any other program is involved.

## What you need

On Linux (for Windows, see [the Windows page](docs/WINDOWS.md#what-you-need)):

- **To speak English.** Everything said is taken for English.
- **A Linux desktop.** It was built and tested on Kubuntu 26.04 (KDE Plasma, on Wayland
  and on X11). Other desktops have not been tried. Where there is no system tray, as on
  GNOME as it comes, a small window stands in for the tray icon.
- **A microphone**, with PulseAudio or PipeWire's PulseAudio service carrying the sound,
  as nearly every desktop has. A headset works best, because an open microphone also
  hears your speakers.
- **LibreOffice Writer**, and optionally Thunderbird, Visual Studio Code, Kate or KWrite.
  They have to be the ones from your distribution's packages: a LibreOffice or VS Code
  installed as a Flatpak or Snap can't be reached.
- **Python 3.10 or newer**, which every current distribution has, and **git** to fetch
  the program.
- **An internet connection for the install**, and your password once: the installer asks
  the system for some packages, LibreOffice Writer among them, and says which before it
  asks.
- **About 1.5 GB of disk space** in your home folder: some 650 MB for the two speech
  models the installer fetches and the rest for the Python packages they run on. The
  recommended model, fetched afterwards, is another 660 MB. (Round figures.)
- **A reasonably recent processor.** On an 8-core laptop chip a phrase takes about a
  second to appear after you stop speaking. The speech models are kept in memory while
  it runs.

[Linux Speaking on Linux](docs/LINUX.md) has the whole list, with what the installer
installs and changes.

## Installing

### On Linux

```
git clone https://github.com/jontio/linux-speaking linux-speaking-source
cd linux-speaking-source
./install.sh
```

(If there is no `git`, install it first: `sudo apt install git` on Kubuntu. The folder
you clone into must not be `~/linux-speaking` itself: that is where the program installs,
and the installer says so and stops if it is run from there.)

The installer lists the system packages it wants and asks for your password once.
Everything else goes in `~/linux-speaking`. It takes roughly five to fifteen minutes, most of it
downloading, and shows what it is fetching as it goes. At the end it says what it set up,
what it couldn't, and the one step that is left to you if you use Thunderbird.

[Linux Speaking on Linux](docs/LINUX.md) says what it does step by step, its options, how
well tested it is, and how to update and uninstall.

### On Windows

1. Install a 64-bit **Python**, version 3.10 to 3.14, from
   [python.org](https://www.python.org/downloads/windows/) or the Microsoft Store.
2. Download this repository (the green **Code** button on GitHub, then **Download ZIP**)
   and extract it.
3. Open PowerShell in the extracted folder and run:

   ```
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

Nothing needs administrator rights. [Linux Speaking on Windows](docs/WINDOWS.md) has the
details.

## The first minute

1. **A welcome window opens** the first time. It says what to do, shows the microphone's
   level as you speak, so you can see that you are heard, and has a box to try
   dictating into before any other program is involved. On Windows it also asks which
   key, if any, should switch dictation on and off, and whether to start when you sign
   in.
2. **Get the recommended model.** The welcome window has a button for it: **Parakeet
   Unified**, the best of the models so far (quick, and it gets the fewest words wrong),
   and the one to use. It is a 660 MB download, which is why the installer doesn't fetch
   it for you; dictation works meanwhile with the Small model the installer did fetch.
   (Parakeet Unified is NVIDIA's, under the NVIDIA Open Model License.
   [Speech models](docs/MODELS.md) has more.)
3. **Look at the tray icon.** Purple with dots: loading. Orange with a "z": asleep, and
   listening only for "wake up". Green: awake. Red with a line through it: off, with the
   microphone closed.
4. **Click into** a Writer document, a Thunderbird message, a file in VS Code, or a Kate
   or KWrite window (on Windows: Word, an Outlook message, or VS Code).
5. **Say "wake up".** The icon turns green. Talk in phrases: the words appear each time
   you pause, about a second later.
6. **Say "go to sleep"** when you are done.

Then:

- **A click on the tray icon** wakes it when it is asleep or off, and switches it off
  when it is awake. A right-click gives the menu: "What can I say?", the microphone
  level, Settings, and "Getting started", which opens the welcome window again.
- **A command is a phrase said by itself**, with a short pause before and after. "What
  can I say?" lists them all, and so does [Commands](docs/COMMANDS.md).
- **A key can do the switching** in a noisy room. On Windows choose one in Settings. On
  Linux bind a key of your own to a command: see
  [a key of your own](docs/LINUX.md#a-key-of-your-own).
- **For other programs**, such as a chat box in a web page, tick **Dictate into other
  programs' text boxes** in Settings. See [Programs](docs/PROGRAMS.md).

## If something isn't working

Look first at the tray icon's tip, by resting the mouse on the icon, or at the top of
Settings: anything that is wrong and stays wrong is listed there, with what to do about
it. These are the commonest things. [Troubleshooting](docs/TROUBLESHOOTING.md) has the
rest, for both systems, and says where the log is.

- **You talk and nothing is typed.** A notice says so when no program it can type into
  is in front. Click into one of the programs listed above, or tick **Dictate into other
  programs' text boxes** in Settings.
- **The icon stays red when you click it, or is grey with a "!".** Red: the microphone
  could not be opened, and a notice said why. Grey: no speech model could be loaded,
  and the tip says what to do.
- **"Wake up" is ignored.** Open the microphone level from the tray icon's menu and
  speak. The bar should turn green. If it barely moves, the microphone is too quiet or
  the wrong one is chosen in your sound settings (on Windows, in Settings here).
- **Nothing appears in Writer straight after installing.** If LibreOffice was open during
  the install, its extension is waiting. Close LibreOffice for ten seconds and open it
  again.
- **Kate or VS Code isn't picked up.** Close it and start it again, Kate from the
  application menu and not from a terminal.
- **Thunderbird takes nothing.** Its add-on has to be added by hand, once: see
  [the one manual step](docs/LINUX.md#the-one-manual-step-thunderbird).
- **There is no tray icon.** On Windows it may be behind the little arrow by the clock.
  On a Linux desktop without a system tray, look for a small window called Linux
  Speaking, which stands in for the icon.

## Updating and removing

- **Linux:** to update, `git pull` in the folder you cloned and run `./install.sh`
  again. `./uninstall.sh` removes it, and asks before it removes anything you recorded.
  More in [Linux Speaking on Linux](docs/LINUX.md#updating).
- **Windows:** to update, download the new version and run the installer again. To
  remove it, use **Uninstall Linux Speaking** in the Start menu. More in
  [Linux Speaking on Windows](docs/WINDOWS.md#updating).
- **After an update**, the first part of the [changelog](CHANGELOG.md) for the new
  version says what is left for you to do by hand, such as adding Thunderbird's add-on
  again.

## Where the rest is

| Page | What it has |
|---|---|
| [Linux Speaking on Linux](docs/LINUX.md) | What you need, what the installer does and its options, the Thunderbird step, a key of your own, starting and stopping, updating, uninstalling |
| [Linux Speaking on Windows](docs/WINDOWS.md) | The same for Windows: what you need, installing, things to know, updating, uninstalling |
| [Commands](docs/COMMANDS.md) | Everything you can say: commands, punctuation, the spelling box, your own words and shortcuts |
| [Programs](docs/PROGRAMS.md) | How each program differs, other programs' text boxes, VS Code's panels |
| [Programming in C and C++](docs/PROGRAMMING.md) | Dictating source code in VS Code |
| [Speech models](docs/MODELS.md) | Choosing a model, noises and whispering, testing models on your voice, training one on your voice |
| [Using another computer](docs/OTHER-COMPUTER.md) | Having a faster computer do the recognising |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | When something isn't working, on Linux and on Windows, and the log |
| [How it works](docs/DESIGN.md) | The design, for those who want to change it or add a program |

## How it works

A speech engine listens to the microphone, cuts what you say into phrases at each pause,
and runs a speech model on each one (NVIDIA's Parakeet, which is the one recommended, or
OpenAI's [Whisper](https://github.com/openai/whisper)). It decides whether a phrase is a command or dictation, reads the text around
the cursor from the program in front, fits the words to it, and asks that program to
insert them. Each program is reached a different way: a LibreOffice extension, a
Thunderbird add-on, a VS Code extension, Word's own automation interface, and the
desktop's accessibility interface for Kate and KWrite.

[docs/DESIGN.md](docs/DESIGN.md) has the details, including how to add another program.

## Developing

The rule tests need only Python 3.10 or newer and numpy. The tests of the link to
another computer also want the `cryptography` package, and the tests of the app's own
windows want PyQt6: each is skipped without it. To run them:

```
python3 -m unittest discover -s tests -t .
```

The others drive real programs and are described in [docs/DESIGN.md](docs/DESIGN.md).
The Python packages an install runs on, and the versions they were last tried with, are
in [requirements.txt](requirements.txt), which both installers use.
See [CONTRIBUTING.md](CONTRIBUTING.md) for how to report a problem or send a change, and
[CHANGELOG.md](CHANGELOG.md) for what has changed.

## Licence

Linux Speaking is free software under the
[GNU General Public License, version 3](LICENSE) or (at your option) any later version.
It comes with no warranty.

It builds on NVIDIA's Parakeet and OpenAI's Whisper speech models,
[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), which runs the first,
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) and
[CTranslate2](https://github.com/OpenNMT/CTranslate2), which run the second, Silero's
voice detector, and
[PyQt6](https://www.riverbankcomputing.com/software/pyqt/). The speech models are
downloaded from Hugging Face when you install and are not part of this repository.
