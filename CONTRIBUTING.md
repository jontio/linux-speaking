# Contributing

## Reporting a problem

Open an issue and include:

- your distribution and its version, and whether you use Wayland or X11,
- which program you were dictating into,
- what you said, what you expected, and what happened,
- the relevant lines from `journalctl --user -u linux-speaking`. The log never contains
  what you dictated, only its length.

If the installer failed, include its full output.

## Sending a change

1. Run the rule tests: `python3 -m unittest discover -s tests -t .`
2. If you changed how a program is driven, run its test from [docs/DESIGN.md](docs/DESIGN.md).
3. Describe what you changed and how you tested it.

New spoken commands usually need three small changes: the phrase in
`dictation/commands.py`, a tick box in `dictation/settings.py`, and a test.

By contributing you agree that your contribution is licensed under the GNU General Public
License, version 3 or later, the same as the rest of the project.
