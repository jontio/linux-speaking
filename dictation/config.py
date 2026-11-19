"""Settings. Each can be overridden with an environment variable."""
from __future__ import annotations

import os

WINDOWS = os.name == "nt"


def cores() -> int:
    """How many processor cores this computer has, counting a core that runs two threads
    once. Whisper goes no faster, and on a small processor slower, with a thread for each
    of those two."""
    try:
        if WINDOWS:
            import ctypes

            class Info(ctypes.Structure):
                _fields_ = [("mask", ctypes.c_size_t), ("relationship", ctypes.c_int),
                            ("rest", ctypes.c_ubyte * 16)]

            size = ctypes.c_ulong(0)
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetLogicalProcessorInformation(None, ctypes.byref(size))
            entries = (Info * (size.value // ctypes.sizeof(Info)))()
            if not kernel32.GetLogicalProcessorInformation(entries, ctypes.byref(size)):
                raise OSError("no processor information")
            found = sum(1 for entry in entries if entry.relationship == 0)  # 0: a core
        else:
            together = set()
            base = "/sys/devices/system/cpu"
            for name in os.listdir(base):
                if name.startswith("cpu") and name[3:].isdigit():
                    with open(os.path.join(base, name, "topology", "thread_siblings_list")) as f:
                        together.add(f.read().strip())
            found = len(together)
        if found > 0:
            return found
    except Exception:
        pass
    return os.cpu_count() or 4

def _install_dir() -> str:
    given = os.environ.get("LS_INSTALL_DIR")
    if given:
        return given
    if WINDOWS:
        # The shortcuts that start the app there carry no settings, so an install put
        # somewhere other than the usual place is known by where the app itself is:
        # <install>\app\dictation, beside <install>\venv.
        app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.basename(app).lower() == "app" and os.path.isdir(
                os.path.join(os.path.dirname(app), "venv")):
            return os.path.dirname(app)
    return "~/linux-speaking"


# Where things are installed. The installer puts the speech models in "models" here.
INSTALL_DIR = os.path.normpath(os.path.expanduser(_install_dir()))
_OWN_MODELS = os.path.join(INSTALL_DIR, "models")
# The tools for retraining a recogniser to one voice, where they have been installed: a
# Python of their own with PyTorch and NeMo. See training.py.
TRAINING_DIR = os.path.normpath(os.path.expanduser(
    os.environ.get("LS_TRAINING_DIR", os.path.join(INSTALL_DIR, "training"))))
_SPEECH_NOTE = os.path.expanduser(
    "~/.var/app/net.mkiol.SpeechNote/cache/net.mkiol/dsnote/speech-models"
)
if os.path.isdir(os.path.join(_OWN_MODELS, "small.en")) \
        or not os.path.isdir(os.path.join(_SPEECH_NOTE, "en_fasterwhisper_small")):
    # The install's own. So it is where there are none at all, here or there: a computer
    # installed with no speech model, where one fetched later has to land in this folder.
    _DIR, _ASLEEP, _AWAKE = _OWN_MODELS, "base.en", "small.en"
else:  # models already downloaded by the Speech Note app
    _DIR, _ASLEEP, _AWAKE = _SPEECH_NOTE, "en_fasterwhisper_base", "en_fasterwhisper_small"
MODEL_DIR = os.environ.get("LS_MODEL_DIR", _DIR)
ASLEEP_MODEL = os.environ.get("LS_ASLEEP_MODEL", _ASLEEP)
AWAKE_MODEL = os.environ.get("LS_AWAKE_MODEL", _AWAKE)
THREADS = int(os.environ.get("LS_THREADS", "0")) or min(8, cores())
BEAM = int(os.environ.get("LS_BEAM", "5"))
# Give Whisper the text before the cursor, so it carries on in the same style.
USE_CONTEXT = os.environ.get("LS_USE_CONTEXT", "1") == "1"
CONTEXT_CHARS = int(os.environ.get("LS_CONTEXT_CHARS", "200"))
# Show a desktop notification on wake up and go to sleep.
NOTIFY = os.environ.get("LS_NOTIFY", "1") == "1"
# On Windows everything is kept together in the install folder.
STATE_FILE = os.path.expanduser(os.environ.get("LS_STATE_FILE") or (
    os.path.join(INSTALL_DIR, "state", "state") if WINDOWS
    else "~/.local/state/linux-speaking/state"))
SETTINGS_FILE = os.path.expanduser(os.environ.get("LS_SETTINGS_FILE") or (
    os.path.join(INSTALL_DIR, "settings.json") if WINDOWS
    else "~/.config/linux-speaking/settings.json"))
LOG_FILE = os.path.join(os.path.dirname(STATE_FILE), "log.txt")  # Windows, with no console
# Sounds that were written down as words and marked "that was a noise": see speech.py.
NOISE_DIR = os.path.join(os.path.dirname(STATE_FILE), "noises")
NOISE_SECONDS = 120.0  # how long after words were written "that was a noise" still means them
# The key this computer's engine and its Thunderbird add-on prove to each other that they
# hold. The installer makes it and builds it into the add-on: see mailbridge.py.
MAIL_KEY_FILE = os.path.expanduser(os.environ.get("LS_MAIL_KEY_FILE") or os.path.join(
    os.path.dirname(SETTINGS_FILE), "mail-key"))
RATE = 16000
FRAME = 320  # samples per 20 ms frame
PREROLL_FRAMES = 15  # audio kept from before a phrase starts (300 ms)
# Pause detection. Speech must be louder than MIN_LEVEL (out of 32768) and RATIO times
# louder than the room. The defaults suit a quiet microphone.
MIN_LEVEL = float(os.environ.get("LS_MIN_LEVEL", "60"))
RATIO = float(os.environ.get("LS_RATIO", "2.5"))
# Each phrase is turned up to this peak before Whisper hears it (1.0 is full scale).
NORMALISE_PEAK = float(os.environ.get("LS_NORMALISE_PEAK", "0.7"))
MAX_GAIN = float(os.environ.get("LS_MAX_GAIN", "60"))
LEVEL_STEPS = 5  # bars on the tray icon's level meter
# A fixed boost for quiet microphones. It can't improve a weak signal, only its numbers.
DEFAULT_BOOST = float(os.environ.get("LS_BOOST", "4"))
# A Writer extension update waiting for LibreOffice to be closed.
PENDING_EXTENSION = os.path.expanduser(
    os.environ.get("LS_PENDING_EXTENSION", os.path.join(INSTALL_DIR, "pending.oxt"))
)
# How long numbered matches stay on screen waiting for you to say a number.
CHOICE_SECONDS = float(os.environ.get("LS_CHOICE_SECONDS", "20"))
# A phrase this long, in seconds, has its loudness put in the log: see Engine._listen.
LONG_PHRASE = float(os.environ.get("LS_LONG_PHRASE", "8"))
# How long a command of the person's own that begins with "ask first" waits for "yes".
ASK_SECONDS = float(os.environ.get("LS_ASK_SECONDS", "10"))
CHOICE_WORDS = 1  # so few words said while numbers show, and no number: asked again, not typed
LOOK_SECONDS = 3.0  # while awake and idle: how often the program in front is looked for
MICROPHONE_WAIT, MICROPHONE_TRIES = 2.0, 90  # a microphone that stopped: tried again this often
MICROPHONE_DROPS = 3  # so many stops in a minute, and it is left for the person to try again
LOAD_AGAIN = 20.0  # with no speech model loaded: how long before loading is tried again
# The Thunderbird add-on connects to this port on this computer. LS_MAIL=0 turns it off.
MAIL_PORT = int(os.environ.get("LS_MAIL_PORT", "47613"))
# Sharing this computer's recogniser with others: the port, and the one address of this
# computer to answer on ("" answers on all of them).
DEFAULT_SHARE_PORT = 47614
SHARE_PORT = int(os.environ.get("LS_SHARE_PORT", str(DEFAULT_SHARE_PORT)))
SHARE_ADDRESS = os.environ.get("LS_SHARE_ADDRESS", "")
MAIL = os.environ.get("LS_MAIL", "0" if WINDOWS else "1") == "1"
# Dictation into Kate and KWrite, through the accessibility interface. LS_EDITOR=0 turns it off.
EDITOR = os.environ.get("LS_EDITOR", "0" if WINDOWS else "1") == "1"
# On Windows, typing into any other text box, when the "other programs" setting is on.
# LS_OTHER=0 turns it off altogether.
OTHER = os.environ.get("LS_OTHER", "1" if WINDOWS else "0") == "1"
# On Linux, the text boxes of a web browser and of programs built from one, such as VS
# Code's panels: read through the accessibility interface and typed into with key presses
# the desktop has allowed. Behind the same setting. LS_WEB=0 turns it off altogether.
WEB = os.environ.get("LS_WEB", "0" if WINDOWS else "1") == "1"
# Dictation into Microsoft Word and Outlook, on Windows. LS_OFFICE=0 turns it off.
OFFICE = os.environ.get("LS_OFFICE", "1" if WINDOWS else "0") == "1"
# The Whisper model that helps a Parakeet: with a Parakeet chosen for dictation, it
# hears what leans on a hint, which a Parakeet can't be given. With a Whisper model
# chosen it isn't loaded at all: the chosen model does everything. (It was once the model
# that listened for "wake up", whichever was chosen, and its setting keeps that name.)
WAKE_MODEL = os.environ.get("LS_WAKE_MODEL", AWAKE_MODEL)
# Source code leans on its hint most of all, the names in the file: so with a Parakeet
# chosen it is heard by a bigger Whisper where one is installed, loaded when code is first
# dictated and let go when none has been for this many seconds.
CODE_MODELS = tuple(name for name in os.environ.get("LS_CODE_MODELS", "medium.en").split(",") if name)
CODE_MODEL_IDLE = float(os.environ.get("LS_CODE_MODEL_IDLE", "600"))
# The spelling box is heard by the first of these that is installed, whichever model is
# chosen for dictation: single letters are the hardest thing there is to tell apart, and
# measured over the alphabet in five voices Medium with its hint got 106 of 130, Small 93,
# and the Parakeets 62 and 73. It is loaded and let go as the model for source code is.
SPELL_MODELS = tuple(name for name in os.environ.get("LS_SPELL_MODELS", "medium.en,small.en").split(",") if name)
# But a letter has to come back quickly, or the box is a trial to use. A model that takes
# longer than this, in seconds, to hear one on this computer is passed over for the next:
# how long each took is measured as the box is used, and remembered in this file.
# (Medium took 0.65 s on one computer, which is well enough, and 1.4 s on another, which
# with the dictation model's own hearing made each letter a wait of nearly two seconds.)
SPELL_SLOW = float(os.environ.get("LS_SPELL_SLOW", "1.0"))
SPELL_SPEEDS = os.path.join(os.path.dirname(STATE_FILE), "spelling-speed.json")
# "Wake up" is listened for on short phrases only: longer sound, such as a video
# playing, is not transcribed at all while asleep.
WAKE_MAX_SECONDS = float(os.environ.get("LS_WAKE_MAX_SECONDS", "6"))
# The menu entry touches this file to ask a running engine to show its Settings window.
SHOW_FILE = os.path.join(os.path.dirname(STATE_FILE), "show")
# The meter turns red when the microphone signal gets this close to its limit (1.0),
# where it starts to distort.
CLIP_LEVEL = float(os.environ.get("LS_CLIP_LEVEL", "0.9"))
# Dictation into Visual Studio Code, through its extension. LS_VSCODE=0 turns it off.
VSCODE = os.environ.get("LS_VSCODE", "1") == "1"
# While asleep, a phrase the model itself rates this likely to be noise is ignored, so
# that hiss, bumps and distant voices can't be mistaken for "wake up".
WAKE_NO_SPEECH = float(os.environ.get("LS_WAKE_NO_SPEECH", "0.5"))
