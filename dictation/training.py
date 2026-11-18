"""Retraining a recogniser to one voice, from sentences read aloud (see reading.py).

The training is heavy: it wants a Python of its own with PyTorch and NeMo (some 2 GB),
about 14 GB of memory, and an hour or two. So it is no part of the app's own install, and
this module is only the app's side of it: what there is to train on, what the result is
called, starting the work as a process of its own that outlives the window and the app,
and following it by the notes it keeps. The work itself is done by the package beside
this one, `trainer`, which that other Python runs.

Nothing here needs more than Python's own library: the trainer uses it too.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import wave
from dataclasses import dataclass

from . import config

SAID = "said.txt"   # in a folder of sentences: "NNN<tab>the text", beside NNN.wav
RUNS = os.path.join(os.path.dirname(config.STATE_FILE), "training-runs")
MEMORY_GB = 14      # what a run comes to at its most, about
LATE = 600          # seconds after a run's start by which its process must have been born
LEAST = 30          # sentences: with fewer there is nothing to train on and test with
MARK = "-mine-"     # in the folder name of a model made here
CUTTER = "parakeet-tdt-0.6b-v2"  # the model that finds where each word is: see trainer/words.py
ABOUT = "trained.json"  # in such a model's folder: its name, and what it was made from
TAIL_SECONDS = 420  # after the last pass: making the app's files, and the comparison
PATIENCE = 8        # seconds a process that was asked to end has, before it is made to

ACTIVE = ("starting", "cutting", "fetching", "listening", "training", "exporting", "comparing")
# Getting ready, before the passes: a run can be ended at any moment of these and lose
# nothing, and it isn't looking for the file that asks it to stop.
EARLY = ("starting", "cutting", "fetching", "listening")
ENDED = ("done", "stopped", "failed")


@dataclass(frozen=True)
class Base:
    """A model that can be retrained."""
    key: str      # what the trainer is told
    label: str    # what the chooser shows
    folder: str   # the app's folder name for the model as it comes
    repo: str     # where its training checkpoint is published
    file: str
    loss: str     # how its training measures a mistake: "tdt" or "rnnt"


BASES = (
    Base("parakeet-unified", "Parakeet Unified", "parakeet-unified-en-0.6b",
         "nvidia/parakeet-unified-en-0.6b", "parakeet-unified-en-0.6b.nemo", "rnnt"),
    Base("parakeet-v2", "Parakeet v2", "parakeet-tdt-0.6b-v2",
         "nvidia/parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v2.nemo", "tdt"),
)
BY_KEY = {base.key: base for base in BASES}


def python() -> str:
    """The Python that has the training tools, or "" if they are not installed here."""
    for path in (os.path.join(config.TRAINING_DIR, "venv", "bin", "python"),
                 os.path.join(config.TRAINING_DIR, "venv", "Scripts", "python.exe")):
        if os.path.exists(path):
            return path
    return ""


def ready() -> bool:
    """Whether a run can be started: the tools are there, and the last install of them
    didn't stop half way or get stopped. (Their Python is made first, before the long
    download.)"""
    return bool(python()) and Install().state() not in ("installing", "failed", "stopped")


# ---- installing the tools ---------------------------------------------------------------
TOOLS_GB = 2        # what the tools come to on disk, about
ROOM_GB = 12        # disk wanted before fetching them: the tools, a model's checkpoint, a run


def install_command() -> list:
    """What installs the tools: the script that comes with the app, for this system."""
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if config.WINDOWS:
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", os.path.join(scripts, "install-training.ps1")]
    made = ["bash", os.path.join(scripts, "install-training.sh")]
    if shutil.which("systemd-run"):
        # A unit of its own, as a run has: closing or restarting the app doesn't end it.
        made = ["systemd-run", "--user", "--scope", "--quiet"] + made
    return made


def room_problem(free_bytes=None) -> str:
    """Why the tools can't be fetched for want of disk space, or ""."""
    if free_bytes is None:
        try:
            free_bytes = shutil.disk_usage(config.INSTALL_DIR).free
        except OSError:
            return ""
    if free_bytes < ROOM_GB * 1e9:
        return (f"The training tools and a first run want about {ROOM_GB} GB of disk space, "
                f"and {free_bytes / 1e9:.0f} GB is free.")
    return ""


def _write(path: str, said: dict, tries: int = 1) -> None:
    """Put notes at `path`, whole or not at all: written beside it and then put in its
    place, so that nobody ever reads half of them, and a write that fails (a full disk)
    leaves the notes there were. Raises OSError. On Windows a file can't be replaced
    while someone has it open, so that is tried `tries` times."""
    new = f"{path}.{os.getpid()}.{threading.get_ident()}.new"  # nobody else's, if two write at once
    try:
        with open(new, "w", encoding="utf-8") as f:
            json.dump(said, f)
        for attempt in range(tries):
            try:
                os.replace(new, path)
                return
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.remove(new)                # nothing half written is left lying beside them
        except OSError:
            pass
        raise


class Install:
    """Fetching the training tools: a long download, started apart from the app like a
    run, so that it goes on if the window or the app is closed, and followed by its log."""

    DONE = "== Done"  # what the install scripts say last

    def __init__(self, folder: str = ""):
        folder = folder or os.path.dirname(config.STATE_FILE)
        self.notes = os.path.join(folder, "training-install.json")
        self.log = os.path.join(folder, "training-install.log")

    def start(self) -> None:
        os.makedirs(os.path.dirname(self.notes), exist_ok=True)
        with open(self.log, "w", encoding="utf-8") as log:
            # Told where this install is: the script would otherwise take the usual place.
            process = subprocess.Popen(
                install_command(), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=dict(os.environ, LS_INSTALL_DIR=config.INSTALL_DIR,
                         LS_TRAINING_DIR=config.TRAINING_DIR), **apart())
        try:
            _write(self.notes, {"pid": process.pid, "started": time.time(), "born": _mark(process.pid)})
        except OSError:
            # Not left going with nothing to say that it is: it would not be shown, and
            # a second could be started beside it.
            _end(process.pid, None, _mark(process.pid), gently=False)
            raise

    def last_line(self) -> str:
        """The last thing the install said, for something to show while it goes on."""
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                lines = [line.strip() for line in f.read().replace("\r", "\n").split("\n")]
        except OSError:
            return ""
        return next((line[:200] for line in reversed(lines) if line), "")

    def _said(self):
        """The notes: None if there are none, and empty if they can't be made out."""
        try:
            with open(self.notes, encoding="utf-8") as f:
                said = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            return {}
        return said if isinstance(said, dict) else {}

    def _going(self, said: dict) -> bool:
        return not said.get("ended") and _alive(said.get("pid"), said.get("started"), said.get("born"))

    def state(self) -> str:
        """"" if it was never started, else "installing", "done", "failed", or "stopped"
        if it was stopped on purpose (see stop)."""
        said = self._said()
        if said is None:
            return "done" if python() else ""
        if self._going(said):
            return "installing"
        if not said.get("ended"):
            try:
                # Written down once seen: its process number may be another program's
                # by and by, and is not asked after again.
                _write(self.notes, dict(said, ended=True))
            except OSError:
                pass
        if python() and self.DONE in self.last_line():
            return "done"
        return "stopped" if said.get("stopped") else "failed"

    def stop(self) -> bool:
        """Stop the fetching of the tools, if it is going on: the install's process is
        ended, with everything it started. Returns at once, and says whether there was
        an install to stop. The state is then "stopped", not "failed", and the tools are
        not ready() until an install has finished. What had been fetched is kept, in the
        tools' folder: installing again carries on from it, and removing that folder
        removes it."""
        said = self._said()
        if not said or not self._going(said):
            return False
        try:
            _write(self.notes, dict(said, ended=True, stopped=True))
        except OSError:
            pass                          # stopped all the same: it will be said to have failed
        _end(said.get("pid"), said.get("started"), said.get("born"), gently=False)
        return True


# ---- what there is to train on -----------------------------------------------------------
def day_folders(folder: str) -> list:
    """The folders that hold sentences: `folder` itself if it does, and those inside it.
    The reading window keeps a folder for each day."""
    folder = os.path.abspath(os.path.expanduser(folder))
    found = [folder] if os.path.exists(os.path.join(folder, SAID)) else []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        names = []
    return found + [os.path.join(folder, name) for name in names
                    if os.path.exists(os.path.join(folder, name, SAID))]


def sentences(folder: str) -> list:
    """[(the sound's file, what was said)] for every sentence under `folder`, in order."""
    found = []
    for day in day_folders(folder):
        try:
            with open(os.path.join(day, SAID), encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, ValueError):
            continue
        said = {}  # where a number is listed twice, the later line is its sound's
        for line in lines:
            number, tab, text = line.rstrip("\n").partition("\t")
            path = os.path.join(day, number + ".wav")
            if tab and text.strip() and os.path.exists(path):
                said.pop(path, None)
                said[path] = text
        found += said.items()
    return found


def found(folder: str) -> tuple:
    """(how many sentences, how many seconds of sound) there are under `folder`."""
    count, seconds = 0, 0.0
    for path, _ in sentences(folder):
        try:
            with wave.open(path, "rb") as sound:
                seconds += sound.getnframes() / max(1, sound.getframerate())
        except (OSError, EOFError, wave.Error):
            continue
        count += 1
    return count, seconds


def split(count: int) -> tuple:
    """Which of `count` sentences, by their place, are trained on, which are kept to
    choose the best pass by, and which are kept out of it altogether, to test the result
    on: (train, choose, test). One in six is for testing, and one in ten of the rest for
    choosing. Always the same ones, so a run that is carried on sees what it saw."""
    test = [at for at in range(count) if at % 6 == 5]
    rest = [at for at in range(count) if at % 6 != 5]
    return ([at for n, at in enumerate(rest) if n % 10 != 9], rest[9::10], test)


def split_of(texts: list) -> tuple:
    """split() for sentences given by their text, some of which may have been read more
    than once: every reading of a text goes the same way, so that what is tested on was
    never trained on in another reading."""
    place = {}
    for text in texts:
        place.setdefault(text, len(place))
    parts = [set(part) for part in split(len(place))]
    return tuple([at for at, text in enumerate(texts) if place[text] in part] for part in parts)


def words(text: str) -> list:
    text = "".join(c if c.isalnum() or c in "' " else " " for c in text.lower())
    return " ".join(text.split()).replace("to morrow", "tomorrow").split()


def wrong(said: str, heard: str) -> int:
    """How many words differ, counted the usual way (changed, missing or extra)."""
    a, b = words(said), words(heard)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]


# ---- what the result is called -----------------------------------------------------------
def slug(name: str) -> str:
    """A name as it can stand in a folder's name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")


def model_folder(base: Base, name: str) -> str:
    """The folder, among the speech models, of `base` retrained and called `name`."""
    return f"{base.folder}{MARK}{slug(name)}"


def name_problem(name: str) -> str:
    """Why `name` won't do for a new model, or ""."""
    if not name.strip():
        return "Give the new model a name."
    if not slug(name):
        return "The name needs some letters or figures in it."
    if name.strip().startswith("-"):
        return "The name can't begin with a dash."
    return ""


def about(model_dir: str, folder: str) -> dict:
    """What a model made here says of itself; empty for any other model."""
    try:
        with open(os.path.join(model_dir, folder, ABOUT), encoding="utf-8") as f:
            said = json.load(f)
        return said if isinstance(said, dict) else {}
    except (OSError, ValueError):
        return {}


def label(model_dir: str, folder: str) -> str:
    """How a model made here is listed, or "" for any other model."""
    said = about(model_dir, folder)
    if not said.get("name"):
        return ""
    base = BY_KEY.get(said.get("base", ""))
    return (f"{said['name']}: {base.label if base else 'a model'} retrained to your voice"
            f"  ({folder})")


# ---- a run, and the notes it keeps --------------------------------------------------------
def free_memory_gb():
    """How much memory is to be had just now, or None if that can't be told."""
    if config.WINDOWS:
        import ctypes

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total", "available", "total_page", "available_page", "total_virtual",
                    "available_virtual", "available_extended")]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            return memory.available / 1e9
        return None
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1e6
    except (OSError, ValueError, IndexError):
        pass
    return None


def memory_problem(free=None) -> str:
    """Why a run can't be started for want of memory, or ""."""
    free = free_memory_gb() if free is None else free
    if free is not None and free < MEMORY_GB + 1:
        return (f"Training wants about {MEMORY_GB} GB of memory, and {free:.0f} GB is free "
                "just now. Closing other programs may make room.")
    return ""


def command(python_path: str, data: str, base: Base, name: str, job: str,
            resume: bool = False) -> list:
    """What starts the trainer: at low priority, and where the desktop can see to it,
    kept from taking more memory than it should need."""
    # "--name=..." and not "--name ...": a value that begins with a dash is still a value.
    made = [python_path, "-u", "-m", "dictation.trainer", f"--data={data}",
            f"--base={base.key}", f"--name={name}", f"--job={job}",
            f"--models={config.MODEL_DIR}"]
    if resume:
        made.append("--resume")
    if config.WINDOWS:
        return made  # its low priority is asked for when it is started: see Job.start
    if shutil.which("nice"):
        made = ["nice", "-n", "10"] + made
    if shutil.which("systemd-run"):
        # A unit of its own: it is not ended with the app, and its memory has a ceiling,
        # well above what it should need. (One set at what it needs ended a run that was
        # only writing its work down: what is being written counts too.)
        made = ["systemd-run", "--user", "--scope", "--quiet", "-p",
                f"MemoryHigh={MEMORY_GB + 3}G", "-p", f"MemoryMax={MEMORY_GB + 6}G",
                "-p", "MemorySwapMax=0"] + made
    return made


def environment() -> dict:
    """Everything the tools fetch or keep goes into their own folder."""
    home = config.TRAINING_DIR
    cache = os.path.join(home, "xdg-cache")
    # Its log is UTF-8 whatever the system's own code page: a name with an accent in it
    # would otherwise stop the trainer on Windows at the first thing it said.
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
                HF_HOME=os.path.join(home, "hf"), HF_HUB_DISABLE_TELEMETRY="1",
                XDG_CACHE_HOME=cache, NEMO_CACHE_DIR=os.path.join(cache, "nemo"),
                NUMBA_CACHE_DIR=os.path.join(cache, "numba"),
                MPLCONFIGDIR=os.path.join(cache, "mpl"))


def _pid(value) -> int:
    """A process number out of the notes, or 0 if what is there isn't one. Notes can be
    damaged, and a number that isn't a process's must not be asked after: a negative
    one would be taken to mean every process there is."""
    return value if type(value) is int and 0 < value < 2 ** 31 else 0


def _number(value):
    """A number out of the notes, or None if what is there isn't one."""
    if type(value) in (int, float) and math.isfinite(value):
        return value
    return None


def _sound(said) -> dict:
    """A run's notes as they were read, without whatever in them is not the kind of
    thing it should be. They are a file like any other and can be damaged: and what is
    made of them (the bar, the words, the asking after a process) must not fall over."""
    if not isinstance(said, dict):
        return {}
    kept = dict(said)
    for key in ("pass", "passes", "batch", "batches", "finished", "pass_seconds", "started", "updated"):
        if key in kept and _number(kept[key]) is None:
            del kept[key]
    for key in ("state", "error", "name", "base", "data", "folder", "born"):
        if key in kept and not isinstance(kept[key], str):
            del kept[key]
    for key in ("before", "after"):       # the comparison: words wrong, of how many
        counts = kept.get(key)
        if key in kept and not (isinstance(counts, dict) and all(
                _number(counts.get(part)) is not None for part in ("wrong", "words"))):
            del kept[key]
    return kept


def _mark(pid) -> str:
    """What tells the process that has this number now from any other that has it
    before or after: when it was started, as the system itself counts, which no setting
    of the clock changes. "" if that can't be told. On Linux it is the count since the
    computer started, with which start of the computer that was; on Windows, the time
    Windows wrote down when it made the process."""
    pid = _pid(pid)
    if not pid:
        return ""
    if config.WINDOWS:
        born = _born(pid)
        return "" if born is None else f"{born:.7f}"
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as f:
            return f"{f.read().strip()}:{ticks}"
    except (OSError, ValueError, IndexError):
        return ""


def _born(pid):
    """When the process with this number was started, as the clock had it, or None if
    that can't be told."""
    try:
        if config.WINDOWS:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return None
            made, ended, inside, outside = (wintypes.FILETIME() for _ in range(4))
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            asked = kernel.GetProcessTimes(handle, ctypes.byref(made), ctypes.byref(ended),
                                           ctypes.byref(inside), ctypes.byref(outside))
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
            if not asked:
                return None
            # Hundreds of nanoseconds since 1601, as Windows counts.
            return ((made.dwHighDateTime << 32) + made.dwLowDateTime) / 1e7 - 11644473600
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8", errors="replace") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])  # since the computer started
        with open("/proc/stat", encoding="utf-8") as f:
            started = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return started + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, TypeError, OverflowError, IndexError, StopIteration, AttributeError):
        return None


def _alive(pid, since=None, mark=None) -> bool:
    """Whether the process with this number is still going, and is ours. `mark` is what
    _mark() gave for ours when its number was noted: a process whose mark is another has
    the number second-hand, and isn't it. Notes from before there were marks have only
    `since`, when ours was started as the clock then had it: one born well after that
    isn't it either. (That goes by the clock, which can be put forward under a run that
    is going: which is why there are marks.)"""
    pid, since = _pid(pid), _number(since)
    if not pid:
        return False
    if mark and isinstance(mark, str):
        now = _mark(pid)
        if now and now != mark:
            return False
    elif since:
        born = _born(pid)
        if born is not None and born > since + LATE:
            return False
    if config.WINDOWS:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # leave to ask only how it is
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulong)]
        asked = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        return bool(asked) and code.value == 259  # still going
    try:
        # One the app started itself and that has ended stays on the books until asked
        # after: this asks, so that it isn't taken for alive.
        if os.waitpid(int(pid), os.WNOHANG)[0]:
            return False
    except (ChildProcessError, OSError, ValueError):
        pass                              # not the app's own child: nothing to ask
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8", errors="replace") as f:
            if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                return False              # ended, and only waiting to be asked after
    except (OSError, ValueError, IndexError):
        pass
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError):
        pass
    return True


def apart() -> dict:
    """How a long piece of work is started so that it is no part of the app: it goes on
    when the app is closed, has no window of its own, and gives way to everything else."""
    if config.WINDOWS:
        return {"creationflags": (subprocess.BELOW_NORMAL_PRIORITY_CLASS
                                  | subprocess.CREATE_NO_WINDOW
                                  | subprocess.CREATE_NEW_PROCESS_GROUP)}
    return {"start_new_session": True}


def _signal(pid: int, how) -> None:
    """Send a signal to a process that was started apart(), and to all it has started:
    they are a group of their own, which goes by its first process's number."""
    try:
        os.killpg(pid, how)
    except ProcessLookupError:
        try:
            os.kill(pid, how)             # not at the head of a group: itself, then
        except OSError:
            pass                          # gone already
    except OSError:
        pass


def _end(pid, since, mark, gently: bool) -> bool:
    """End a process that was started apart(), with everything it has started. Returns
    at once, with whether there was one to end: a thread of its own sees that it has
    gone, and makes it go if it hasn't in PATIENCE seconds. Nothing is done unless the
    process with that number is still ours: see _alive() for `since` and `mark`.

    `gently` first asks, as Ctrl+C would: Python then clears up after itself (what it
    had unpacked in the temporary folder, say). Windows has no way to ask a program
    with no window, so there it is ended outright."""
    pid = _pid(pid)

    def still() -> bool:
        return _alive(pid, since, mark)

    def gone_in(seconds: float) -> bool:
        until = time.monotonic() + seconds
        while still():
            if time.monotonic() >= until:
                return False
            time.sleep(0.1)
        return True

    def see_to_it() -> None:
        if config.WINDOWS:
            try:  # the process and all that came of it, by Windows' own tool for that
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
            return
        if gently:
            if gone_in(PATIENCE):
                return
            _signal(pid, signal.SIGTERM)
        if not gone_in(PATIENCE):
            _signal(pid, signal.SIGKILL)

    if not pid or not still():
        return False
    if not config.WINDOWS:
        _signal(pid, signal.SIGINT if gently else signal.SIGTERM)  # now: the rest can wait
    threading.Thread(target=see_to_it, daemon=True).start()
    return True


class Job:
    """One run of the trainer, in a folder of its own: its notes (status.json), its log,
    and the model as it stood after the last pass, from which it can be carried on."""

    GRACE = 120  # seconds a run has, from being started, to say that it is there
    TRIES = 40   # times a note is tried again, where the window has it open (Windows)

    def __init__(self, folder: str):
        self.folder = folder
        self.notes = os.path.join(folder, "status.json")
        self.stop_file = os.path.join(folder, "stop")
        self.end_file = os.path.join(folder, "end")  # there if the run was ended on purpose: see end()
        self.log = os.path.join(folder, "log.txt")

    def note(self, **fields) -> dict:
        """Add to the notes, and say when. The trainer's way of being followed.

        On Windows a file can't be read or replaced while someone else has it open, and
        the window looks at these notes every second. So both are tried again for a
        moment, and a note that still can't be written is let go: the next one has it
        all. The work is never stopped for the sake of a note."""
        said = self._read(sure=True)
        said.update(fields, updated=time.time())
        if "pid" in fields:
            # With a process's number goes what tells that process from any other that
            # has the number later, noted while it is certainly the one: see _mark().
            said["born"] = _mark(fields["pid"])
        self.kept = said
        try:
            os.makedirs(self.folder, exist_ok=True)
            _write(self.notes, said, self.TRIES)
        except OSError:
            if not fields.get("state"):
                return said               # how far a pass has come: the next note will say
            raise                         # a change of state must be seen
        return said

    def _read(self, sure: bool = False) -> dict:
        """The notes as they are on disk, without whatever in them is not the kind of
        thing it should be. With `sure`, for adding to them: what this run last wrote is
        used if they can't be read just now, so nothing is dropped."""
        for attempt in range(self.TRIES if sure else 1):
            try:
                with open(self.notes, encoding="utf-8") as f:
                    return _sound(json.load(f))
            except FileNotFoundError:
                return {}
            except (OSError, ValueError):
                time.sleep(0.05 if sure else 0)
        return dict(getattr(self, "kept", {})) if sure else {}

    def adrift(self) -> bool:
        """Whether the folder is there with no notes that say what it is: none at all,
        or none that can be made out. (Not notes that only can't be read this moment,
        with someone else writing them.) Nothing can be carried on from such a folder,
        and it may hold a model as far as it had got: so it is listed, to be cleared."""
        try:
            with open(self.notes, encoding="utf-8") as f:
                return _sound(json.load(f)).get("state") not in ACTIVE + ENDED
        except FileNotFoundError:
            return os.path.isdir(self.folder)
        except ValueError:
            return True
        except OSError:
            return False

    def status(self, now=None) -> dict:
        """The notes. A run that should be going and isn't is said to have failed: or to
        have been stopped, if it was ended on purpose (see end)."""
        said = self._read()
        if said.get("state") in ACTIVE:
            now = time.time() if now is None else now
            pid = _pid(said.get("pid"))
            waiting = not pid and now - said.get("started", 0) < self.GRACE
            if not waiting and not _alive(pid, said.get("started"), said.get("born")):
                said = dict(said, state="failed",
                            error="The training stopped without saying why.")
        if said.get("state") == "failed" and os.path.exists(self.end_file):
            said = dict(said, state="stopped", error="")
        return said

    def running(self) -> bool:
        return self.status().get("state") in ACTIVE

    def start(self, data: str, base: Base, name: str, resume: bool = False) -> None:
        """Start the trainer, or carry a stopped run on. It runs by itself from here."""
        os.makedirs(self.folder, exist_ok=True)
        fresh = dict(state="starting", pid=0, started=time.time(), error="", name=name,
                     base=base.key, data=data, folder=model_folder(base, name))
        if resume:
            self.note(**fresh)
        else:
            # A run begun afresh has no past: nothing of the last one shows. Its notes
            # take the place of the old ones in one step. Were the old ones removed first
            # and the new then not written (a disk that is full, as one may be after a
            # pass has been kept), the folder would be left with none, and unlisted.
            self.kept = dict(fresh, born="", updated=time.time())
            _write(self.notes, self.kept, self.TRIES)
        for path in (self.stop_file, self.end_file):
            if os.path.exists(path):
                os.remove(path)
        with open(self.log, "a", encoding="utf-8") as log:
            process = subprocess.Popen(
                command(python(), data, base, name, self.folder, resume),
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env=environment(), **apart())
        try:
            # Noted at once, with its mark, so that it is known to be going from the first
            # moment. The trainer notes the same itself when it has loaded.
            self.note(pid=_pid(process.pid))
        except OSError:
            pass

    def size(self) -> int:
        """How much disk the run's folder holds. A file kept under two names is one file."""
        seen, total = set(), 0
        for folder, _, names in os.walk(self.folder):
            for name in names:
                try:
                    said = os.stat(os.path.join(folder, name))
                except OSError:
                    continue
                which = (said.st_dev, said.st_ino) if said.st_ino else os.path.join(folder, name)
                if which not in seen:
                    seen.add(which)
                    total += said.st_size
        return total

    def discard(self) -> None:
        """Remove everything of a run that is over. It can't be carried on after that."""
        if not self.running():
            shutil.rmtree(self.folder, ignore_errors=True)

    def stop(self) -> None:
        """Ask the run to stop. During the passes it does at the next few sentences,
        keeping what it has finished: the passes done are not done again. Before the
        passes, while it is getting ready, it isn't looking: it may be fetching the
        model it starts from, which is 2.5 GB the first time. So then it is ended at
        once (see end), which loses nothing."""
        os.makedirs(self.folder, exist_ok=True)
        with open(self.stop_file, "w", encoding="utf-8"):
            pass
        self.end()

    def end(self) -> bool:
        """End the run at once, if it is still getting ready (the stages in EARLY), and
        say whether it was. Returns straight away: the run is asked to end as Ctrl+C
        would ask it, and made to if it hasn't in a few seconds, or at once if this is
        the second time of asking. Its notes then say "stopped", and it can be carried
        on: what had been fetched is kept.

        Not during the passes, where stop() loses nothing and this could lose a pass's
        work: nor after them, while the model is being made and put in its place, which
        is a few minutes and is not to be cut short."""
        said = self._read()
        if said.get("state") not in EARLY \
                or not _alive(said.get("pid"), said.get("started"), said.get("born")):
            return False
        again = os.path.exists(self.end_file)
        try:
            with open(self.end_file, "w", encoding="utf-8"):
                pass                      # what says afterwards that it was stopped, and didn't fail
        except OSError:
            pass
        return _end(said.get("pid"), said.get("started"), said.get("born"), gently=not again)


def job_for(base: Base, name: str) -> Job:
    return Job(os.path.join(RUNS, model_folder(base, name)))


def unfinished() -> list:
    """[(run, bytes)] for the runs that were stopped or that failed and still hold the
    model as it stood, some 2.4 GB each: what "carry on" would start from. And for the
    folders of runs whose notes are lost, which can only be cleared."""
    try:
        jobs = [Job(os.path.join(RUNS, name)) for name in sorted(os.listdir(RUNS))]
    except OSError:
        return []
    found = []
    for job in jobs:
        if job.status().get("state") in ("stopped", "failed") or job.adrift():
            size = job.size()
            if size > 1e6:                # the notes and the log alone are not worth saying
                found.append((job, size))
    return found


def latest():
    """The run last heard from, or None: what the window shows when it is opened."""
    def heard(job):
        try:
            return os.path.getmtime(job.notes)
        except OSError:
            return None                   # no notes, or gone this moment

    try:
        jobs = [Job(os.path.join(RUNS, name)) for name in os.listdir(RUNS)]
    except OSError:
        return None
    return max((job for job in jobs if heard(job) is not None),
               key=lambda job: heard(job) or 0.0, default=None)


# ---- saying how it is going ---------------------------------------------------------------
def time_text(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min" if minutes % 60 else f"{minutes // 60} h"


def _passes_done(said: dict) -> float:
    """Passes finished, and the part of the one under way."""
    if said.get("state") != "training":
        return float(said.get("finished", 0))
    return max(0, said.get("pass", 1) - 1) + said.get("batch", 0) / max(1, said.get("batches", 1))


def fraction(said: dict) -> float:
    """How far a run has come, from 0 to 1."""
    state = said.get("state")
    if state in ("training", "stopped", "failed"):
        return 0.05 + 0.85 * min(1.0, _passes_done(said) / max(1, said.get("passes", 1)))
    return {"done": 1.0, "starting": 0.01, "cutting": 0.02, "fetching": 0.03, "listening": 0.04,
            "exporting": 0.92, "comparing": 0.96}.get(state, 0.0)


def time_left(said: dict):
    """Seconds a run still wants, or None if that can't be told yet."""
    each = said.get("pass_seconds")
    if said.get("state") != "training" or not each:
        return None
    return max(0.0, max(1, said.get("passes", 1)) - _passes_done(said)) * each + TAIL_SECONDS


def result_text(said: dict) -> str:
    """What the comparison found, on the sentences kept out of the training."""
    before, after = said.get("before"), said.get("after")
    if not before or not after:
        return ""
    text = (f"On the {after.get('sentences', 0)} sentences kept back to test it, "
            f"{base_label(said)} as it comes got {before['wrong']} of {before['words']} words "
            f"wrong, and retrained {after['wrong']}.")
    if before.get("near") is not None and after.get("near") is not None:
        text += (f" Words right but not sure of: {before['near']} before, "
                 f"{after['near']} after.")
    if before.get("alone_of") and after.get("alone_of"):
        text += (f" Of {after['alone_of']} single words cut from them: {before['alone']} "
                 f"right before, {after['alone']} after.")
    return text


def base_label(said: dict) -> str:
    base = BY_KEY.get(said.get("base", ""))
    return base.label if base else "the model"


def describe(said: dict) -> tuple:
    """(a headline, a line of detail) for the notes of a run."""
    state = said.get("state", "")
    name = said.get("name", "")
    if state == "starting":
        return "Starting…", "The training tools take a minute to load."
    if state == "cutting":
        return ("Cutting single words out of the sentences\u2026",
                "They are learned from too: with nothing round it, a word has only your "
                "voice to go by.")
    if state == "fetching":
        return (f"Fetching {base_label(said)} to start from…",
                "About 2.5 GB, the first time only.")
    if state == "listening":
        return ("Hearing the test sentences with the model as it comes…",
                "So that there is something to compare the result with.")
    if state == "training":
        left = time_left(said)
        return (f"Training: pass {said.get('pass', 1)} of {said.get('passes', 1)}",
                f"At most {time_text(left)} to go: it stops sooner if it stops getting better."
                if left is not None else "How long it will take is known after a minute or two.")
    if state == "exporting":
        return "Making the model the app can use…", "A few minutes."
    if state == "comparing":
        return "Comparing it with the model it started from…", "A minute or two."
    if state == "done":
        return f"Finished: “{name}” is among the speech models.", result_text(said)
    if state == "stopped":
        done = said.get("finished", 0)
        return ("Stopped.", (f"{done} of {said.get('passes', 0)} passes are done and kept. "
                             if done else "") + "Carry on whenever you like.")
    if state == "failed":
        return "It could not be finished.", said.get("error", "")
    return "", ""
