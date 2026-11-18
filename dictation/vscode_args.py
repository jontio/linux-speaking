"""Linux: the start-up switch that lets VS Code's panels be dictated into.

VS Code describes the text boxes in its panels (a chat box, the terminal) to other
programs only if it is started with "force-renderer-accessibility": true in its
argv.json. This adds that line, leaving the rest of the file, comments and all, as it is,
and can take it out again. VS Code has to be restarted afterwards.

It is for the app to add, when "Dictate into other programs' text boxes" is ticked in
Settings (switch_on), and for the uninstaller to take out again (switch_off):

    python -m dictation.vscode_args            adds it
    python -m dictation.vscode_args --remove   takes it out, if this program put it there
"""
from __future__ import annotations

import os
import re
import sys

SWITCH = "force-renderer-accessibility"
FOLDERS = ("~/.vscode", "~/.vscode-oss", "~/.vscode-insiders")
# The comment that goes in above the line. It is also how the line is known to be this
# program's own when it is taken out: one a person wrote themselves has no such comment.
COMMENT = "// Lets Linux Speaking read the text boxes in panels, such as a chat box."
_SET = re.compile(r'^(\s*)"' + SWITCH + r'"\s*:\s*(true|false)(\s*,?\s*)$', re.M)


def _code_end(line: str) -> int:
    """Where a line's settings end and a comment after them begins: its length if none."""
    quoted = False
    at = 0
    while at < len(line):
        if quoted and line[at] == "\\":
            at += 1                       # whatever follows a backslash is part of the text
        elif line[at] == '"':
            quoted = not quoted
        elif not quoted and line.startswith("//", at):
            return at
        at += 1
    return len(line)


def _is_setting(line: str) -> bool:
    """Whether a line holds something other than a comment or nothing."""
    return bool(line.strip()) and not line.strip().startswith("//")


def with_switch(text: str):
    """The text of an argv.json with the switch on, or None if it is on already."""
    found = _SET.search(text)
    if found:
        if found.group(2) == "true":
            return None
        return text[:found.start(2)] + "true" + text[found.end(2):]
    lines = text.split("\n")
    close = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "}"), None)
    if close is None:
        return None                       # not a file this can safely change
    last = next((i for i in range(close - 1, -1, -1) if _is_setting(lines[i])), None)
    if last is not None:
        end = _code_end(lines[last])
        code = lines[last][:end].rstrip()
        if not code.endswith(("{", ",")):
            lines[last] = code + "," + lines[last][len(code):]
    lines[close:close] = ["", "\t" + COMMENT, f'\t"{SWITCH}": true']
    return "\n".join(lines)


def without_switch(text: str):
    """The text of an argv.json with the line this program added taken out again, and its
    comment with it. None if there is nothing of ours in it: a switch somebody set
    themselves, with no such comment above it, is theirs and is left."""
    lines = text.split("\n")
    at = next((i for i in range(1, len(lines))
               if lines[i - 1].strip() == COMMENT and _SET.match(lines[i])), None)
    if at is None:
        return None
    code = lines[at][:_code_end(lines[at])].rstrip()
    first = at - 1
    if first > 0 and not lines[first - 1].strip():
        first -= 1                        # the blank line that went in above the comment
    del lines[first:at + 1]
    if not code.endswith(","):
        # Ours was the last setting, so the one before it was given a comma when ours went
        # in. If nothing follows now, that comma goes too, and the file is as it was.
        after = next((line for line in lines[first:] if _is_setting(line)), "")
        before = next((i for i in range(first - 1, -1, -1) if _is_setting(lines[i])), None)
        if after.strip() == "}" and before is not None:
            end = _code_end(lines[before])
            kept = lines[before][:end].rstrip()
            if kept.endswith(","):
                lines[before] = kept[:-1] + lines[before][len(kept):]
    return "\n".join(lines)


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _write(path: str, text: str) -> None:
    """All of the file or none of it: VS Code doesn't start well on half an argv.json."""
    path = os.path.realpath(path)         # a file that is a link stays a link
    new = path + ".linux-speaking-new"
    with open(new, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(new, os.stat(path).st_mode & 0o777)
    except OSError:
        pass                              # there was no file before: the usual rights will do
    os.replace(new, path)


def enable(folder: str) -> str:
    """Switch it on for the VS Code whose settings folder this is. A line saying what was done."""
    path = os.path.join(folder, "argv.json")
    text = _read(path)
    if text is None:
        if os.path.exists(path):
            return f"{path}: could not be read, so it has been left alone"
        text = "{\n}\n"
    changed = with_switch(text)
    if changed is None:
        return f"{path}: already on, or not a file to change"
    try:
        _write(path, changed)
    except OSError as e:
        return f"{path}: could not be changed ({e.strerror or e})"
    return f"{path}: switched on. Restart VS Code for it to take effect."


def disable(folder: str) -> str:
    """Take the line out again for the VS Code whose settings folder this is, if it was
    this program that put it there. A line saying what was done, or "" if nothing was."""
    path = os.path.join(folder, "argv.json")
    text = _read(path)
    changed = without_switch(text) if text is not None else None
    if changed is None:
        return ""
    try:
        _write(path, changed)
    except OSError as e:
        return f"{path}: could not be changed ({e.strerror or e})"
    return f"{path}: the line Linux Speaking added has been taken out."


def folders() -> list:
    """The settings folders of the VS Codes that have been run on this computer."""
    return [folder for folder in map(os.path.expanduser, FOLDERS) if os.path.isdir(folder)]


def switch_on() -> list:
    """Switch it on in every VS Code there is. A line for each, saying what was done."""
    return [enable(folder) for folder in folders()]


def switch_off() -> list:
    """Take out what switch_on put in. A line for each file that was changed."""
    return [line for line in map(disable, folders()) if line]


def main(args=None) -> int:
    args = sys.argv[1:] if args is None else list(args)
    if args == ["--remove"]:
        for line in switch_off():
            print(line)
        return 0
    if args:
        print("usage: python -m dictation.vscode_args [--remove]")
        return 2
    done = switch_on()
    for line in done:
        print(line)
    if not done:
        print("VS Code hasn't been run on this computer yet: nothing to switch on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
