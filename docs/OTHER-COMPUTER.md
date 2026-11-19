# Using another computer for the recognition

Recognising speech is the slow part, and a faster computer on the same network can do it.
Both computers need Linux Speaking installed, on Linux or on Windows. Back to the
[README](../README.md).

## Setting it up

1. On the faster computer, open Settings and tick **Let other computers use this one for
   speech recognition**. It shows an address and a key.
2. On the other one, tick **Use another computer for speech recognition**, type in that
   address and key, and press **Connect**. Choose which of the faster computer's models to
   use, or leave it to pick the same one as here. The address is what the faster
   computer shows: its name on the network, such as `office-pc`, with `:` and a port
   after it only if the port was changed. Something that could not be an address, such
   as one with a space in it, is turned away when you press Connect, and the line under
   the address says so.

From then on each phrase is sent there and the words come back. With the sound goes
what the recogniser is shown to help it: the last 200 characters before the cursor, your
own words from Settings, and in a C or C++ file the names in it. The tray icon's tooltip
says where the recognising is being done.

If that computer is off or out of reach, this one does the work itself, so no phrase is
lost, and tries the other again after twenty seconds. (A computer with
[no speech model of its own](#a-small-computer-with-no-speech-model-of-its-own) has
nothing to do the work with: see there.) The same happens if the other
computer is slow to answer, or if something else answers at its address: it is given
five seconds to say hello and a minute for a phrase. The tray icon's tip then says that
the recognising is being done on this computer, and the line under the address in
Settings says what went wrong when Settings is next opened, such as "The other computer
took too long to answer."

## A small computer with no speech model of its own

A computer with little disk space, or too slow to recognise speech, can leave all of it
to the other one and have no speech model at all. The program and what it runs on take
about half a gigabyte on Linux and about 600 MB on Windows. The two models an ordinary
install starts with are another 600 MB, and are what is left out.

1. Install it as usual. The installer asks **Download the speech models now?** Answer
   **n**. It says at the end that no model was installed, and the tray icon says "No
   speech model" until the next step is done.
2. Set the other computer up as above: **Let other computers use this one** there, and
   **Use another computer** here, with its address and key.

That is all. The icon turns orange, and what you say is heard on the other computer.

- **"Wake up" is listened for on the other computer too.** With no model here there is
  nothing to hear it with, so the short sounds heard while dictation is asleep are sent
  as well. **Listen for "wake up" there too** is ticked and greyed in Settings, and its
  tip says why. Switch dictation off, from the tray icon or with your key, and nothing
  is listened to or sent.
- **If the other computer can't be reached, nothing is heard.** There is no model here
  to carry on with. The tray icon's tip and the top of Settings say so, with the
  reason. A phrase is tried twice before it is given up, and the other computer is
  asked again five seconds later, as you speak.
- **Installing a model later makes it an ordinary install.** "Install or remove models"
  in Settings fetches one, and the first to arrive is put to use straight away. (A
  Parakeet model needs the Small model beside it: Small is fetched first, by itself.)
  The tick box is then yours to set, and is unticked to begin with: "wake up" is
  listened for here, and this computer carries on by itself when the other is out of
  reach.
- **The installer asks once.** An update keeps what you answered, in a note in the
  models folder, `left-out.txt`. For installing with nobody to ask, `LS_SKIP_MODELS=1`
  answers no and `LS_SKIP_MODELS=0` answers yes: see the installer's options for
  [Linux](LINUX.md#the-installers-options) and [Windows](WINDOWS.md).
- **On Linux the installer also asks the system for packages**, LibreOffice Writer
  among them, which is a large one if it isn't there already. `LS_SKIP_PACKAGES=1`
  leaves that step out, and the installer then lists what it needs for you to install
  yourself: see [Linux](LINUX.md#the-installers-options).
- **To save more space**, the packages the installer downloaded are kept in a cache by
  Python's installer, a few hundred megabytes. It can be emptied afterwards:
  `~/linux-speaking/venv/bin/python -m pip cache purge` on Linux, and on Windows
  `& "$env:USERPROFILE\linux-speaking\venv\Scripts\python.exe" -m pip cache purge`.

## Things to know

- **"Wake up" is still listened for on this computer**, so nothing is sent while dictation
  is asleep. A tick box sends that too, which wakes it sooner on a slow computer. (On a
  computer with no speech model the other one has to listen for it: see above.)
- **Each computer proves to the other that it holds the key**, before any sound is sent,
  and the key itself is never sent. A computer that merely answers at the same address is
  given nothing, and nothing it says is typed. Every answer is signed too, and a request
  is good once only, so one that was overheard can't be sent again. Both computers need
  this version or a later one: an older one is told to update.
- **A computer without the key can't use up the sharing one.** The sharing computer
  attends to eight callers at once and turns the rest away, gives each a few seconds to
  show that it holds the key, and reads nothing more of a request until it has. What a
  stranger can still do is keep those eight places busy, and then your own computer
  does its own listening meanwhile.
- **A long phrase over a slow link is given time.** Once a computer has shown that it
  holds the key, it has half a minute to send the sound, and more for a long phrase, up
  to 55 seconds.
- **What is sent is encrypted**: the sound, the text that goes with it, and the words
  that come back. The two computers agree a key afresh for each run of phrases, which is
  never sent and is then forgotten, so what was overheard can't be read later either, not
  even by someone who has since got hold of the key in Settings. What can still be seen
  from outside is that phrases are being sent, when, and how long each one is. It was
  made for your own network; nothing about it has been looked over by anyone whose trade
  is breaking such things, so across the open internet a VPN is still the wiser way.
- **The faster computer listens on port 47614.** Its firewall has to let that through. On
  Windows, the firewall asks the first time, and allowing it needs an administrator: it
  is the one thing in Linux Speaking that does. Set `LS_SHARE_ADDRESS` to one of the
  computer's addresses to answer only there, and `LS_SHARE_PORT` for another port.
  [Troubleshooting](TROUBLESHOOTING.md#settings-that-are-environment-variables) says how
  such a variable is set for a program that starts by itself.
- **The voice test and reading aloud use it too.** If another computer does your
  recognising, its models can be tried in the voice test, and the recording is sent to
  it for that. Each sentence read aloud for training is sent to it to be heard; it keeps
  nothing.

## If it stops being used

Both computers need this version of Linux Speaking, or a later one on each. The way the
two talk has changed, and what goes between them is encrypted now, so a version from
before is told to update: Settings says under the address which of the two is the older
one. Meanwhile each computer does its own listening. Once the older one is updated, the
other computer is used again by itself: it is tried afresh with a phrase every twenty
seconds or so.

If the sharing computer can't share at all, because its port is in use or the part that
does the encrypting is missing, its tray icon's tip and the top of its Settings say
"Other computers can't use this one for recognition" and why. The line under its tick
box in Settings says "Not working yet", and it tries again every half a minute.
