"""Settings. Each can be overridden with an environment variable."""
from __future__ import annotations

import os

# Where things are installed. The installer puts the speech models in "models" here.
INSTALL_DIR = os.path.expanduser(os.environ.get("LS_INSTALL_DIR", "~/linux-speaking"))
_OWN_MODELS = os.path.join(INSTALL_DIR, "models")
_SPEECH_NOTE = os.path.expanduser(
    "~/.var/app/net.mkiol.SpeechNote/cache/net.mkiol/dsnote/speech-models"
)
if os.path.isdir(os.path.join(_OWN_MODELS, "small.en")):
    _DIR, _ASLEEP, _AWAKE = _OWN_MODELS, "base.en", "small.en"
else:  # models already downloaded by the Speech Note app
    _DIR, _ASLEEP, _AWAKE = _SPEECH_NOTE, "en_fasterwhisper_base", "en_fasterwhisper_small"
MODEL_DIR = os.environ.get("LS_MODEL_DIR", _DIR)
ASLEEP_MODEL = os.environ.get("LS_ASLEEP_MODEL", _ASLEEP)
AWAKE_MODEL = os.environ.get("LS_AWAKE_MODEL", _AWAKE)
THREADS = int(os.environ.get("LS_THREADS", "8"))
BEAM = int(os.environ.get("LS_BEAM", "5"))
# Give Whisper the text before the cursor, so it carries on in the same style.
USE_CONTEXT = os.environ.get("LS_USE_CONTEXT", "1") == "1"
CONTEXT_CHARS = int(os.environ.get("LS_CONTEXT_CHARS", "200"))
# Show a desktop notification on wake up and go to sleep.
NOTIFY = os.environ.get("LS_NOTIFY", "1") == "1"
STATE_FILE = os.path.expanduser(
    os.environ.get("LS_STATE_FILE", "~/.local/state/linux-speaking/state")
)
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
METER_FILE = os.path.join(os.path.dirname(STATE_FILE), "meter")
# A Writer extension update waiting for LibreOffice to be closed.
PENDING_EXTENSION = os.path.expanduser(
    os.environ.get("LS_PENDING_EXTENSION", os.path.join(INSTALL_DIR, "pending.oxt"))
)
# How long numbered matches stay on screen waiting for you to say a number.
CHOICE_SECONDS = float(os.environ.get("LS_CHOICE_SECONDS", "20"))
# The Thunderbird add-on connects to this port on this computer. LS_MAIL=0 turns it off.
MAIL_PORT = int(os.environ.get("LS_MAIL_PORT", "47613"))
MAIL = os.environ.get("LS_MAIL", "1") == "1"
# Dictation into Kate and KWrite, through the accessibility interface. LS_EDITOR=0 turns it off.
EDITOR = os.environ.get("LS_EDITOR", "1") == "1"
# "Wake up" is listened for with the wake model, on short phrases only: longer sound,
# such as a video playing, is not transcribed at all while asleep.
WAKE_MODEL = os.environ.get("LS_WAKE_MODEL", AWAKE_MODEL)
WAKE_MAX_SECONDS = float(os.environ.get("LS_WAKE_MAX_SECONDS", "6"))
# The menu entry touches this file to ask a running engine to show its meter window.
SHOW_FILE = os.path.join(os.path.dirname(STATE_FILE), "show")
# The meter turns red when the microphone signal gets this close to its limit (1.0),
# where it starts to distort.
CLIP_LEVEL = float(os.environ.get("LS_CLIP_LEVEL", "0.9"))
# Dictation into Visual Studio Code, through its extension. LS_VSCODE=0 turns it off.
VSCODE = os.environ.get("LS_VSCODE", "1") == "1"
# While asleep, a phrase the model itself rates this likely to be noise is ignored, so
# that hiss, bumps and distant voices can't be mistaken for "wake up".
WAKE_NO_SPEECH = float(os.environ.get("LS_WAKE_NO_SPEECH", "0.5"))
