# Linux Speaking on Linux

What you need, what the installer does, and how to start, stop, update and remove it.
For Windows, see [Linux Speaking on Windows](WINDOWS.md). Back to the [README](../README.md).

- [What you need](#what-you-need)
- [Installing](#installing)
- [The one manual step: Thunderbird](#the-one-manual-step-thunderbird)
- [The installer's options](#the-installers-options)
- [How well tested is the installer?](#how-well-tested-is-the-installer)
- [Starting and stopping](#starting-and-stopping)
- [A key of your own](#a-key-of-your-own)
- [Updating](#updating)
- [Uninstalling](#uninstalling)

## What you need

- **To speak English.** Dictation and the spoken commands are in English only. Whatever
  is said is taken for English.
- **A Linux desktop.** It was built and tested on Kubuntu 26.04, with KDE Plasma on
  Wayland and on X11. Nothing else has been tried. The parts that are KDE's own (the
  launchers for Kate and KWrite, refreshing the menu) are passed over quietly on other
  desktops. Its icon lives in the system tray; where there is none, as on GNOME as it
  comes, a small window stands in for the icon, with the menu's entries as buttons.
- **A microphone.** A headset works best, because an open microphone also hears your
  speakers. The sound is taken from PulseAudio, or from PipeWire through its PulseAudio
  service, with the `parec` program. The microphone used is the one your desktop's sound
  settings have as the default.
- **LibreOffice Writer**, and optionally Thunderbird, Visual Studio Code, Kate or KWrite.
  The installer installs LibreOffice Writer from your distribution's packages if it isn't
  there. A LibreOffice or a VS Code that was installed as a **Flatpak or a Snap can't be
  reached**: such a program is shut off from the rest of the desktop, and keeps its
  extensions somewhere else. Use the one from your distribution's packages for
  dictation. The installer says so if it finds a Flatpak or Snap LibreOffice.
- **Python 3.10 or newer.** The system's own Python is used, even if another one (from
  conda, pyenv and the like) comes first in your terminal. The installer prints the
  version it found, and stops with a plain message if it is too old.
- **git**, to fetch the program. A fresh Kubuntu hasn't got it: `sudo apt install git`.
- **An internet connection for the install**, and **your password** once, for the system
  packages. After that nothing needs the internet, except fetching another speech model
  when you ask for one.
- **A package manager it knows**: apt (Kubuntu, KDE neon, Debian), dnf (Fedora), pacman
  (Arch, Manjaro, EndeavourOS) or zypper (openSUSE). On any other system, install the
  packages listed [below](#the-system-packages) yourself and run the installer with
  `LS_SKIP_PACKAGES=1`.
- **systemd, if it is to start at login by itself.** Without a systemd user session the
  installer says so and carries on: the program is then started from the application
  menu. See [Starting and stopping](#starting-and-stopping).
- **Disk space: about 1.5 GB** in your home folder. Some 650 MB of that is the two
  speech models the installer fetches (Base, 150 MB, and Small, 490 MB), and the rest is
  the Python packages they run on. The recommended model, Parakeet Unified, is another
  660 MB when you fetch it. The installer checks that there is room before it starts. A
  computer that is short of space, or slow, can do without the models and have
  [another computer do the recognising](OTHER-COMPUTER.md#a-small-computer-with-no-speech-model-of-its-own):
  the installer asks.
  These are round figures, not measurements.
- **Memory and processor.** A reasonably recent processor: on an 8-core laptop chip a
  phrase takes about a second to appear after you stop speaking. No graphics card is
  used. The speech models are held in memory for as long as it runs, which is about as
  much as they take on disk.
- **It listens while asleep.** Asleep, every short sound is still put to the Small
  model, to see whether it was "wake up". Longer sound, such as a video playing, is not
  looked at. So it uses some of the processor now and then even when you aren't
  dictating. Switch it off from the tray icon, and the microphone is closed.

## Installing

```
git clone https://github.com/jontio/linux-speaking linux-speaking-source
cd linux-speaking-source
./install.sh
```

The folder you clone into must not be `~/linux-speaking` itself: that is where the
program installs, and the installer says so and stops if it is run from there. Run it as
yourself, not as root.

The installer first lists the system packages it wants, then asks for your password,
once, to install them. Everything else goes in `~/linux-speaking` in your home folder,
but for a few small things that tie it into your desktop: the service that starts it at
login, its menu entry, launchers for Kate and KWrite that switch their accessibility on,
and beside your settings the key for Thunderbird's add-on. It then:

1. sets up the speech engine: Python packages, a few hundred megabytes of them, shown as
   they arrive,
2. downloads two speech models (about 650 MB), with a count of how far it has got, unless
   you said no when it asked,
3. checks that the speech models load, which takes ten seconds or so,
4. installs the LibreOffice Writer extension,
5. builds the Thunderbird add-on,
6. installs the Visual Studio Code extension, if VS Code or VSCodium is installed,
7. lets Kate and KWrite be dictated into,
8. adds "Linux Speaking" to the application menu, under Utilities,
9. starts the tray icon, now and at every login.

Right at the start it asks one question: **Download the speech models now?** Press Enter
for yes. Say no on a computer that is to leave the recognising to another one, or to
fetch models later from Settings. It asks once: an update keeps what you answered.

It takes roughly five to fifteen minutes, most of it downloading. If a download is cut short,
run the installer again: it carries on from where it stopped.

At the end it says what it did. If LibreOffice was open, the Writer extension could not
go in: it is left waiting, and the app puts it in once LibreOffice has been closed. If
something could not be set up, the closing lines say what, and not that all is well.

The installer does not download **Parakeet Unified**, the recommended speech model: the
welcome window offers it with one button when the app first starts. See
[Speech models](MODELS.md).

It does not change VS Code's `argv.json`. The one line that lets VS Code's panels be
read is added by the app, and only when you tick **Dictate into other programs' text
boxes** in Settings: see [Programs](PROGRAMS.md#vs-codes-panels-and-other-programs-built-from-a-web-browser).

### The system packages

These are what the installer asks the system for. On Kubuntu, KDE neon and Debian:

```
python3 python3-venv python3-pip python3-numpy python3-pyqt6 python3-gi
gir1.2-atspi-2.0 at-spi2-core pulseaudio-utils zip unzip rsync
libreoffice-writer python3-uno hunspell-en-us
```

On Fedora, Arch and openSUSE it asks for the same things under those systems' names (the
lists are at the top of `install.sh`). In words: Python 3 with venv and pip, numpy, PyQt6
and PyGObject, the AT-SPI accessibility library, `parec` from the PulseAudio utilities,
zip, unzip and rsync, LibreOffice Writer with its Python support, and an English
Hunspell dictionary.

If refreshing the package lists fails, because of one source that no longer answers, the
installer says so and carries on with what the system knows. If the packages themselves
can't be installed, it stops before changing anything else, and says how to go on
without that step.

## The one manual step: Thunderbird

Thunderbird doesn't let another program install an add-on, so if you use it:

1. In Thunderbird, open the menu and choose **Add-ons and Themes**.
2. Click the gear icon and choose **Install Add-on From File**.
3. Pick `~/linux-speaking/linux-speaking-thunderbird.xpi`.
4. Open a new message or reply. Compose windows that were already open won't have it.

Two things to know about that file:

- **It is for this computer only.** Don't pass it on: on another computer, run the
  installer there, and it makes that computer's own.
- **If you had the add-on from an earlier version, add it again from this file.** The
  old one is no longer answered. While an old one is asking, the tray icon's tip and
  the top of Settings say "Thunderbird's add-on is an older one", and how to add the
  new one.

The reason is a key. The file holds one, made for your computer, and the add-on and the
speech engine each prove to the other that they hold it. So another person's program on
the same computer, or a program that is kept apart from your files, can't pass itself
off as either of them: it can't read what you dictate, or reach into the message you are
writing. An add-on from before there was a key has none, and is told nothing.

## The installer's options

They are set in front of the command, as in `LS_SKIP_PACKAGES=1 ./install.sh`.

| Option | What it does |
|---|---|
| `LS_INSTALL_DIR=~/somewhere/linux-speaking` | Installs there instead of `~/linux-speaking`. It must be a folder of its own: one that doesn't exist yet, or an earlier install. A folder with other things in it is refused. |
| `LS_SKIP_PACKAGES=1` | Doesn't ask the system for packages, and so doesn't ask for your password. For when they are there already, or you install them yourself. |
| `LS_SKIP_MODELS=1` | Answers the installer's question about the speech models for you: they are not downloaded, which saves about 600 MB. For installing with nobody at the keyboard. The install finishes without them and says what to do next: see [Using another computer](OTHER-COMPUTER.md#a-small-computer-with-no-speech-model-of-its-own). `LS_SKIP_MODELS=0` answers yes. |
| `LS_SKIP_INTEGRATIONS=1` | Doesn't touch LibreOffice, Thunderbird, VS Code, Kate, the menu or the login service, and doesn't start the program. |
| `LS_NO_AUTOSTART=1` | Doesn't set it to start at every login. `LS_NO_AUTOSTART=0` sets it to start again. Left out, a first install sets it to start, and an update keeps whatever was chosen before. |
| `LS_NO_START=1` | Doesn't start it now. |
| `LS_PYTHON=/usr/bin/python3.12` | Builds on that Python instead of the system's `/usr/bin/python3`. It has to be one that can see the distribution's PyQt6. |
| `LS_ENGINE_ONLY=1` | Only copies the program and restarts it. For development. |

## How well tested is the installer?

Honestly: only partly.

- **This version's installer has been run as an update**, on one Kubuntu 26.04 machine
  that already had the program and the system packages.
- **It has not yet been run as a fresh install** on a clean system, or on one without
  systemd, and the package lists for Fedora, Arch and openSUSE are untested.
- **The unit tests pass** on that machine, and so do the live tests against
  LibreOffice, Thunderbird, Kate and VS Code.

If it fails for you, please open an issue with the output.

## Starting and stopping

- **Quit**, in the tray icon's menu, stops it. **Linux Speaking** in the application
  menu, under Utilities, starts it again and shows its Settings window. Clicking the
  menu entry while it is running only shows that window: it never runs twice, however
  it is started.
- **Turning it off** from the tray icon closes the microphone but leaves it running,
  ready to be switched on again.
- **Starting at login.** The installer sets it to. To change that, use **Start when I
  sign in** in Settings, or one of:

  ```
  systemctl --user disable linux-speaking     # don't start at login
  systemctl --user enable linux-speaking      # start at login
  ```

  To install without it, run `LS_NO_AUTOSTART=1 ./install.sh`. Running the installer
  again later, to update, leaves your choice as it finds it.
- **From a terminal:**

  ```
  ~/linux-speaking/app/scripts/launch.sh start      # start it, if it isn't running
  ~/linux-speaking/app/scripts/launch.sh stop       # stop it
  ~/linux-speaking/app/scripts/launch.sh restart    # both
  ```

  Where it runs as a service, `systemctl --user stop linux-speaking` and
  `systemctl --user start linux-speaking` do the same.

### Without systemd

On a system with no systemd user session (Void, Artix, Devuan and others), the installer
says so, sets up no login service, and carries on. The menu entry then starts the
program itself, and so does the command above. To have it start at login, add this
command to your desktop's autostart settings:

```
~/linux-speaking/app/scripts/launch.sh start
```

**Start when I sign in** in Settings is greyed on such a system, and says why: it
switches the login service, and there is none.

Its log is then the file `~/.local/state/linux-speaking/log.txt`, where on other systems
it is in the journal. To start it by hand, with what it says shown in the terminal:

```
cd ~/linux-speaking/app && ../venv/bin/python -m dictation.tray
```

## A key of your own

Dictation can be switched from the keyboard, which helps in a noisy room, or when you
would rather not say "wake up" aloud. There is a command for it, to bind to whatever key
you like in your desktop's settings:

```
~/linux-speaking/app/scripts/launch.sh toggle
```

`toggle` does what a click on the tray icon does: it wakes dictation if it is asleep or
off, and switches it off if it is awake. In its place can go `wake`, `sleep`, `off`, or
`settings`, which shows the Settings window. The key is answered within a third of a
second.

Settings has the same thing under **Keyboard**: a command that does what `toggle` does,
written out in full for your install, with a **Copy** button to take it to your
desktop's shortcut settings.

In KDE Plasma:

1. Open **System Settings**, then **Keyboard**, then **Shortcuts**.
2. Click **Add New**, then **Command or Script**.
3. For the command, give the line above, with the path written out in full:
   `/home/yourname/linux-speaking/app/scripts/launch.sh toggle`. Give it a name, such as
   "Dictation on and off", and add it.
4. Select the new entry, click **Add custom shortcut**, and press the key or keys you
   want. A key that few programs use is best, such as Pause, Scroll Lock or Ctrl+Alt+D.
5. Click **Apply**.

Other desktops have the same thing under their keyboard settings, as a "custom
shortcut".

What the launcher runs is this, from the folder `~/linux-speaking/app`:

```
~/linux-speaking/venv/bin/python -m dictation.control toggle
```

It prints one line saying what it asked for. If the app isn't running it says so, and
does nothing.

## Updating

```
cd linux-speaking-source
git pull
./install.sh
```

`git pull` fetches the new version, and the installer puts it in place and restarts the
program. Running the installer without `git pull` changes nothing: it installs the
version that is in the folder. Your settings, speech models and recordings are kept. So
is your choice about starting at login.

If you deleted the folder you cloned, clone it again as under
[Installing](#installing), and run the installer from there. Deleting it does no harm:
the install is complete without it, and a copy of the uninstaller is kept in
`~/linux-speaking/app`.

After a distribution upgrade the system's Python is a newer one, and the speech engine's
Python packages, which were built for the old one, no longer load: the tray icon turns
grey with a yellow "!", and its tip says "No speech model" and that a part the
recogniser needs is missing. Run the installer again. It notices, throws the old
packages away and fetches them afresh.

After updating, read the first part of the [changelog](../CHANGELOG.md) for the new
version: it says what is left for you to do by hand. If you use Thunderbird and the
add-on changed, add it again from the file, as
[above](#the-one-manual-step-thunderbird). If LibreOffice or VS Code was open during
the update, close it and open it again.

## Uninstalling

```
./uninstall.sh
```

Run it from the folder you cloned, or, if that has gone, from the copy that is kept
with the install: `~/linux-speaking/app/uninstall.sh`. It finds the install folder by
itself, even if you installed somewhere other than `~/linux-speaking`.

**It asks before removing what is yours.** If you have read sentences aloud for
training, made a recording for the voice test, marked sounds as noises, or retrained a
model to your voice, it lists them, with how many and how big, and asks whether they
are to go too. Anything but "yes" keeps them where they are, and a later install finds
them again. Two options answer the question beforehand:

```
./uninstall.sh --purge     # remove those too, without asking   (or LS_PURGE=1)
./uninstall.sh --keep      # keep them, without asking          (or LS_KEEP=1)
```

If LibreOffice is open it asks you to close it first, so that the Writer extension can
be taken out.

**What it removes:** the program and its Python packages, the speech models, your
settings (with "My words" and your shortcuts in them, and the key for Thunderbird's
add-on beside them), what the app kept as it ran in `~/.local/state/linux-speaking`
(whether dictation was on, the desktop's leave to press keys, what stopped training
runs had kept, and the like), the login service and anything you added to it with
`systemctl --user edit`, the menu entry, the Writer extension, the VS Code extension,
and the training tools. Only what the installer and the app put in the install folder
is taken out of it; if you had put anything else there, it is left, and the uninstaller
says so.

**What it puts back:**

- Kate's and KWrite's launchers. The copies the installer made are removed; if you had a
  launcher of your own, the one setting that was added to it is taken out again.
- The desktop's accessibility switch, if it was "Dictate into other programs' text
  boxes" that switched it on.
- VS Code's `argv.json`, if the app added its line to it: the line and its comment are
  taken out. A `"force-renderer-accessibility"` line that you wrote yourself, or one that
  was already there and set to `false`, is not touched.

**What is left, for you to remove if you want to:**

- **The Thunderbird add-on.** Remove it in Thunderbird, under Add-ons and Themes.
- **The system packages** the installer asked for, listed
  [above](#the-system-packages), LibreOffice Writer among them. Other programs may
  need them by now, so they are not touched.
- **The folder you cloned**, such as `~/linux-speaking-source`.
- **The desktop's own note that Linux Speaking may press keys**, if you ever allowed
  that for VS Code's panels or web pages. Linux Speaking's side of it is removed; the
  desktop keeps its side.
- **Download caches**: pip's, in `~/.cache/pip` (`pip cache purge` empties it), and,
  from versions before this one, perhaps Hugging Face's in `~/.cache/huggingface`.
- **The training tools, if you had put them somewhere else** with `LS_TRAINING_DIR`.
  Set that variable when you run the uninstaller and they go too; otherwise delete that
  folder.
- **The Writer extension, if LibreOffice was open** and there was nobody to ask to close
  it. The uninstaller says so, and how to remove it.

The uninstaller ends by saying what it did. If something could not be removed, it says
that, and not that all has gone.
