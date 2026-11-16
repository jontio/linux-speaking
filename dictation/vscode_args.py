"""Linux: the start-up switch that lets VS Code's panels be dictated into.

VS Code describes the text boxes in its panels (a chat box, the terminal) to other
programs only if it is started with "force-renderer-accessibility": true in its
argv.json. This adds that line, leaving the rest of the file, comments and all, as it is.
VS Code has to be restarted afterwards.

Run by the installer: python -m dictation.vscode_args
"""
from __future__ import annotations

import os
import re

SWITCH = "force-renderer-accessibility"
FOLDERS = ("~/.vscode", "~/.vscode-oss", "~/.vscode-insiders")
_SET = re.compile(r'^(\s*)"' + SWITCH + r'"\s*:\s*(true|false)(\s*,?\s*)$', re.M)


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
    last = next((i for i in range(close - 1, -1, -1)
                 if lines[i].strip() and not lines[i].strip().startswith("//")), None)
    if last is not None and not lines[last].rstrip().endswith(("{", ",")):
        lines[last] = lines[last].rstrip() + ","
    lines[close:close] = ["",
                          "\t// Lets Linux Speaking read the text boxes in panels, such as a chat box.",
                          f'\t"{SWITCH}": true']
    return "\n".join(lines)


def enable(folder: str) -> str:
    """Switch it on for the VS Code whose settings folder this is. A line saying what was done."""
    path = os.path.join(folder, "argv.json")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = "{\n}\n"
    changed = with_switch(text)
    if changed is None:
        return f"{path}: already on, or not a file to change"
    with open(path, "w", encoding="utf-8") as f:
        f.write(changed)
    return f"{path}: switched on. Restart VS Code for it to take effect."


def main() -> int:
    done = False
    for folder in map(os.path.expanduser, FOLDERS):
        if os.path.isdir(folder):
            print(enable(folder))
            done = True
    if not done:
        print("VS Code hasn't been run on this computer yet: nothing to switch on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
