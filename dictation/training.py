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
import os
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass

from . import config

SAID = "said.txt"   # in a folder of sentences: "NNN<tab>the text", beside NNN.wav
RUNS = os.path.join(os.path.dirname(config.STATE_FILE), "training-runs")
MEMORY_GB = 14      # what a run comes to at its most, about
LEAST = 30          # sentences: with fewer there is nothing to train on and test with
MARK = "-mine-"     # in the folder name of a model made here
CUTTER = "parakeet-tdt-0.6b-v2"  # the model that finds where each word is: see trainer/words.py
ABOUT = "trained.json"  # in such a model's folder: its name, and what it was made from
TAIL_SECONDS = 420  # after the last pass: making the app's files, and the comparison

ACTIVE = ("starting", "cutting", "fetching", "listening", "training", "exporting", "comparing")
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


# ---- installing the tools ---------------------------------------------------------------
TOOLS_GB = 2        # what the tools come to on disk, about
ROOM_GB = 12        # disk wanted before fetching them: the tools, a model's checkpoint, a run


def install_command() -> list:
    """What installs the tools: the script that comes with the app, for this system."""
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if config.WINDOWS:
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-File", os.path.join(scripts, "install-training.ps1")]
    return ["bash", os.path.join(scripts, "install-training.sh")]


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
            process = subprocess.Popen(install_command(), stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL, **apart())
        with open(self.notes, "w", encoding="utf-8") as f:
            json.dump({"pid": process.pid, "started": time.time()}, f)

    def last_line(self) -> str:
        """The last thing the install said, for something to show while it goes on."""
        try:
            with open(self.log, encoding="utf-8", errors="replace") as f:
                lines = [line.strip() for line in f.read().replace("\r", "\n").split("\n")]
        except OSError:
            return ""
        return next((line[:200] for line in reversed(lines) if line), "")

    def state(self) -> str:
        """"" if it was never started, else "installing", "done" or "failed"."""
        try:
            with open(self.notes, encoding="utf-8") as f:
                pid = json.load(f).get("pid")
        except (OSError, ValueError, AttributeError):
            return "done" if python() else ""
        if _alive(pid):
            return "installing"
        return "done" if python() and self.DONE in self.last_line() else "failed"


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
            with open(os.path.join(day, SAID), encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in lines:
            number, tab, text = line.rstrip("\n").partition("\t")
            path = os.path.join(day, number + ".wav")
            if tab and text.strip() and os.path.exists(path):
                found.append((path, text))
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
    made = [python_path, "-u", "-m", "dictation.trainer", "--data", data, "--base", base.key,
            "--name", name, "--job", job, "--models", config.MODEL_DIR]
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
    return dict(os.environ, HF_HOME=os.path.join(home, "hf"), HF_HUB_DISABLE_TELEMETRY="1",
                XDG_CACHE_HOME=cache, NEMO_CACHE_DIR=os.path.join(cache, "nemo"),
                NUMBA_CACHE_DIR=os.path.join(cache, "numba"),
                MPLCONFIGDIR=os.path.join(cache, "mpl"))


def _alive(pid) -> bool:
    if not pid:
        return False
    if config.WINDOWS:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # leave to ask only how it is
        if not handle:
            return False
        code = ctypes.c_ulong()
        asked = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(asked) and code.value == 259  # still going
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


class Job:
    """One run of the trainer, in a folder of its own: its notes (status.json), its log,
    and the model as it stood after the last pass, from which it can be carried on."""

    GRACE = 120  # seconds a run has, from being started, to say that it is there

    def __init__(self, folder: str):
        self.folder = folder
        self.notes = os.path.join(folder, "status.json")
        self.stop_file = os.path.join(folder, "stop")
        self.log = os.path.join(folder, "log.txt")

    def note(self, **fields) -> dict:
        """Add to the notes, and say when. The trainer's way of being followed."""
        said = self._read()
        said.update(fields, updated=time.time())
        os.makedirs(self.folder, exist_ok=True)
        with open(self.notes + ".new", "w", encoding="utf-8") as f:
            json.dump(said, f)
        os.replace(self.notes + ".new", self.notes)
        return said

    def _read(self) -> dict:
        try:
            with open(self.notes, encoding="utf-8") as f:
                said = json.load(f)
            return said if isinstance(said, dict) else {}
        except (OSError, ValueError):
            return {}

    def status(self, now=None) -> dict:
        """The notes. A run that should be going and isn't is said to have failed."""
        said = self._read()
        if said.get("state") in ACTIVE:
            now = time.time() if now is None else now
            waiting = not said.get("pid") and now - said.get("started", 0) < self.GRACE
            if not waiting and not _alive(said.get("pid")):
                said = dict(said, state="failed",
                            error="The training stopped without saying why. Its log may: "
                                  + self.log)
        return said

    def running(self) -> bool:
        return self.status().get("state") in ACTIVE

    def start(self, data: str, base: Base, name: str, resume: bool = False) -> None:
        """Start the trainer, or carry a stopped run on. It runs by itself from here."""
        os.makedirs(self.folder, exist_ok=True)
        for path in (self.stop_file,) + (() if resume else (self.notes,)):
            if os.path.exists(path):
                os.remove(path)  # a run begun afresh has no past: nothing of the last one shows
        self.note(state="starting", pid=0, started=time.time(), error="", name=name,
                  base=base.key, data=data, folder=model_folder(base, name))
        with open(self.log, "a", encoding="utf-8") as log:
            subprocess.Popen(command(python(), data, base, name, self.folder, resume),
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             env=environment(), **apart())

    def stop(self) -> None:
        """Ask the run to stop. It does at the next few sentences, keeping what it has
        finished: the passes done are not done again."""
        os.makedirs(self.folder, exist_ok=True)
        with open(self.stop_file, "w", encoding="utf-8"):
            pass


def job_for(base: Base, name: str) -> Job:
    return Job(os.path.join(RUNS, model_folder(base, name)))


def latest():
    """The run last heard from, or None: what the window shows when it is opened."""
    try:
        jobs = [Job(os.path.join(RUNS, name)) for name in os.listdir(RUNS)]
    except OSError:
        return None
    jobs = [job for job in jobs if os.path.exists(job.notes)]
    return max(jobs, key=lambda job: os.path.getmtime(job.notes), default=None)


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
