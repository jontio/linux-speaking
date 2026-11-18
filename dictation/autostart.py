"""Whether the app starts when the person signs in, and switching that.

On Windows it is started by a shortcut in the Startup folder, which the installer puts
there beside the one in the Start menu. On Linux it is a systemd user service, which is
enabled or not. Where there is no systemd it can't be told, and nothing is switched: the
app is then started from the application menu.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from . import APP_NAME, config

SHORTCUT = "Linux Speaking.lnk"       # as install.ps1 names it, in both folders
SERVICE = "linux-speaking.service"    # as install.sh names it
CSIDL_PROGRAMS, CSIDL_STARTUP = 0x0002, 0x0007


# ---- Windows ------------------------------------------------------------------------------
def _folder(which: int, name: str) -> str:
    """One of Windows' own folders for this person: where it says it is, or else where it
    usually is."""
    try:
        import ctypes
        from ctypes import wintypes
        found = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, which, None, 0, found) == 0 and found.value:
            return found.value
    except Exception:
        pass
    menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                        "Programs")
    return os.path.join(menu, name) if name else menu


def startup_shortcut() -> str:
    return os.path.join(_folder(CSIDL_STARTUP, "Startup"), SHORTCUT)


def menu_shortcut() -> str:
    return os.path.join(_folder(CSIDL_PROGRAMS, ""), SHORTCUT)


def make_shortcut(place: str) -> None:
    """Write the shortcut that starts the app, as the installer writes it."""
    from win32com.client import Dispatch
    install = config.INSTALL_DIR
    link = Dispatch("WScript.Shell").CreateShortcut(place)
    link.TargetPath = os.path.join(install, "venv", "Scripts", "pythonw.exe")
    link.Arguments = "-m dictation.tray"
    link.WorkingDirectory = os.path.join(install, "app")
    link.IconLocation = os.path.join(install, "linux-speaking.ico")
    link.Description = APP_NAME
    link.Save()


def _windows_state(startup: str) -> bool:
    return os.path.exists(startup)


def _windows_switch(on: bool, startup: str, menu: str, make) -> str:
    try:
        if not on:
            if os.path.exists(startup):
                os.remove(startup)
            return ""
        os.makedirs(os.path.dirname(startup), exist_ok=True)
        if os.path.exists(menu):
            # The Start menu's own shortcut starts the app the same way: a copy of it
            # is exactly what the installer would have put here.
            shutil.copyfile(menu, startup)
        else:
            make(startup)
        return ""
    except Exception as e:
        return ("Windows wouldn't let the shortcut in the Startup folder be "
                + ("made" if on else "removed") + f": {getattr(e, 'strerror', None) or e}")


# ---- Linux --------------------------------------------------------------------------------
def _systemctl(run, *words: str):
    """What systemctl answers for this person's own services: (its exit code, what it
    said), or None if there is no systemd to ask."""
    try:
        # It answers at once, as a rule. The window that asks is not kept waiting long
        # for one that doesn't.
        done = run(["systemctl", "--user", *words, SERVICE], capture_output=True, text=True,
                   timeout=4)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, ((done.stdout or "") + "\n" + (done.stderr or "")).strip()


def _linux_state(run):
    answer = _systemctl(run, "is-enabled")
    if answer is None:
        return None
    said = answer[1].splitlines()[0].strip() if answer[1] else ""
    if said == "enabled":
        return True
    if said == "disabled":
        return False
    return None  # no such service, or one set up some other way: not ours to switch


def _linux_switch(on: bool, run) -> str:
    answer = _systemctl(run, "enable" if on else "disable")
    if answer is None:
        return CANT_TELL
    code, said = answer
    if code == 0:
        return ""
    last = said.splitlines()[-1].strip() if said else ""
    return ("The desktop wouldn't " + ("switch that on" if on else "switch that off")
            + (f": {last}" if last else "."))


CANT_TELL = ("Whether it starts when you sign in can't be told on this system: it has no "
             "systemd service for it. Start it from the application menu when you want it.")


# ---- for the windows ------------------------------------------------------------------------
def state(run=subprocess.run, startup: str = ""):
    """True if the app starts when the person signs in, False if not, None if it can't
    be told (and so can't be switched from here)."""
    if config.WINDOWS:
        return _windows_state(startup or startup_shortcut())
    return _linux_state(run)


def switch(on: bool, run=subprocess.run, startup: str = "", menu: str = "",
           make=make_shortcut) -> str:
    """Have the app start at sign-in, or not. Returns what went wrong, in words for the
    person, or "" if it is done."""
    if config.WINDOWS:
        return _windows_switch(on, startup or startup_shortcut(), menu or menu_shortcut(), make)
    return _linux_switch(on, run)
