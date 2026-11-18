# Contributing

## Reporting a problem

[Troubleshooting](docs/TROUBLESHOOTING.md) may already have the answer. If not, open an
issue and include:

- **On Linux:** your distribution and its version, your desktop (KDE Plasma, or
  another), and whether you use Wayland or X11.
- **On Windows:** Windows 10 or 11, where your Python came from (python.org or the
  Microsoft Store) and its version, and, if Word or Outlook is involved, which Office it
  is and whether Outlook is the classic one or the new one.
- which version of Linux Speaking it is (About, in the tray icon's menu, says),
- which program you were dictating into,
- which speech model was in use (Settings says),
- what you said, what you expected, and what happened,
- the relevant lines of the log. On Linux: `journalctl --user -u linux-speaking`. On
  Windows: `state\log.txt` in the install folder. The log never contains what you
  dictated, only its length.

If an installer failed, include its full output, from the first line: that line says
which Python it used.

## Sending a change

1. Run the rule tests: `python3 -m unittest discover -s tests -t .` (they need numpy; those of the
   link to another computer need `cryptography` too, and are skipped without it).
2. If you changed how a program is driven, run its test from [docs/DESIGN.md](docs/DESIGN.md).
3. If you changed an installer or one of the scripts, say which systems you ran it on.
   `bash -n` finds slips in the shell scripts. The Python packages both installers
   install are listed, with the versions last tried, in `requirements.txt`: bring that
   up to date when you have tried newer ones.
4. Describe what you changed and how you tested it.

New spoken commands usually need three small changes: the phrase in
`dictation/commands.py`, a tick box in `dictation/settings.py`, and a test. If it is
something a newcomer should know, add it to [docs/COMMANDS.md](docs/COMMANDS.md) too.
The README is kept short on purpose: what it is, what it needs, how to install it and
the first minute. The rest goes in the pages under `docs/`.

By contributing you agree that your contribution is licensed under the GNU General Public
License, version 3 or later, the same as the rest of the project.
