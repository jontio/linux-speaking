---
name: Something isn't working
about: A problem with dictating, with a command, or with installing
title: ''
labels: ''
assignees: ''
---

<!-- docs/TROUBLESHOOTING.md may already have the answer. If not, fill in what you can.
     Nothing you dictated is in the log: only how long each phrase was. -->

**What happened**

What you said or did, what you expected, and what happened instead.

**Where**

- Linux Speaking version (About, in the tray icon's menu):
- The program you were dictating into:
- The speech model in use (Settings says):

**Your system: fill in one**

On Linux:

- Distribution and version:
- Desktop (KDE Plasma, or another):
- Wayland or X11:

On Windows:

- Windows 10 or 11:
- Python: its version, and whether it came from python.org or the Microsoft Store:
- If Word or Outlook is involved: which Office, and classic Outlook or the new one:

**The log**

The lines from when it happened. On Linux: `journalctl --user -u linux-speaking`
(without systemd: `~/.local/state/linux-speaking/log.txt`). On Windows: `state\log.txt`
in the install folder.

```
paste here
```

**If an installer failed**

Everything it printed, from the first line.

```
paste here
```
