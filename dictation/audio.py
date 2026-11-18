"""The microphone: 16 kHz mono, 16-bit, read a frame at a time."""
from __future__ import annotations

import collections
import subprocess
import threading

from . import config

# On Linux parec is used, not pw-record, because it lets the client be named. The
# desktop's microphone indicator then says "Linux Speaking is using the microphone".
RECORD_COMMAND = [
    "parec", "--raw", f"--rate={config.RATE}", "--channels=1", "--format=s16le",
    "--latency-msec=20", "--client-name=Linux Speaking",
    "--stream-name=Listening for dictation",
    "--property=application.icon_name=audio-input-microphone",
]


class MicrophoneError(Exception):
    """The microphone can't be recorded from. Its text is written for the person
    dictating to read: what is wrong and what to do about it."""


class _Parec:
    def __init__(self):
        try:
            self._process = subprocess.Popen(
                RECORD_COMMAND, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            raise MicrophoneError(
                "The recording program \"parec\" isn't installed. It comes with the "
                "desktop's sound system (the package pulseaudio-utils).") from None
        except OSError as e:
            raise MicrophoneError(f"The microphone can't be opened: {e.strerror or e}.") from None
        # What parec says when it gives up is the only clue to why: with no sound server
        # to talk to it ends at once, and without this nobody was ever told.
        self._said = collections.deque(maxlen=5)
        threading.Thread(target=self._listen_for_trouble, daemon=True).start()

    def _listen_for_trouble(self) -> None:
        try:
            for line in self._process.stderr:
                line = line.decode("utf-8", "replace").strip()
                if line:
                    self._said.append(line)
        except (OSError, ValueError):
            pass

    def read(self, nbytes: int) -> bytes:
        return self._process.stdout.read(nbytes)

    def why(self) -> str:
        """Why the recording stopped by itself, if it said: "" otherwise."""
        try:
            self._process.wait(timeout=0.5)  # so that its last words have arrived
        except (subprocess.TimeoutExpired, OSError):
            pass
        said = self._said[-1] if self._said else ""
        if "onnection refused" in said or "onnection failure" in said:
            return ("No sound server answered. This program records through the "
                    "PulseAudio service, which PipeWire also provides (pipewire-pulse).")
        return said

    def close(self) -> None:
        self._process.terminate()


_streams = 0  # Windows: how many recordings this program has open


class _SoundDevice:
    """Windows: a recording device, through PortAudio."""

    def __init__(self, name: str = ""):
        global _streams
        self._why = ""
        try:
            import sounddevice
            if not _streams:
                _look_again(sounddevice)  # a headset plugged in since the list was last read
            self._stream = sounddevice.RawInputStream(
                samplerate=config.RATE, channels=1, dtype="int16", blocksize=config.FRAME,
                device=_device(name))
            self._stream.start()
        except Exception as e:
            raise MicrophoneError(
                "Windows wouldn't open the microphone. Check that one is plugged in, and "
                "that Windows lets desktop apps use it (Settings, Privacy & security, "
                f"Microphone).  [{_short(e)}]") from None
        _streams += 1
        self._open = True

    def read(self, nbytes: int) -> bytes:
        try:
            data, _ = self._stream.read(nbytes // 2)
        except Exception as e:  # closed from another thread, or the device went away
            self._why = _short(e)
            return b""
        return bytes(data)

    def why(self) -> str:
        """Why the recording stopped by itself, if it said: "" otherwise."""
        return self._why

    def close(self) -> None:
        global _streams
        if self._open:
            self._open = False
            _streams = max(0, _streams - 1)
        try:
            self._stream.abort()
            self._stream.close()
        except Exception:
            pass


def _short(error) -> str:
    text = " ".join(str(error).split())
    return text if len(text) <= 120 else text[:117] + "..."


def _look_again(sounddevice) -> None:
    """Have PortAudio read the list of devices again: it reads it once, when it starts,
    and never notices a headset plugged in later. Only while nothing is being recorded,
    as starting it again ends every recording it has open."""
    try:
        sounddevice._terminate()
        sounddevice._initialize()
    except Exception:
        pass


def _inputs() -> list:
    """(number, name) of each recording device, as Windows' simplest sound interface
    lists them. That interface converts to the rate we want by itself."""
    import sounddevice
    apis = sounddevice.query_hostapis()
    return [(number, device["name"]) for number, device in enumerate(sounddevice.query_devices())
            if device["max_input_channels"] > 0 and apis[device["hostapi"]]["name"] == "MME"
            and not device["name"].startswith("Microsoft Sound Mapper")]


# Windows' simplest sound interface, the one recorded through, cuts a device's name off
# at this many letters: "Microphone (Realtek High Defini".
CUT_AT = 31
_WHOLE_NAMES = ("Windows WASAPI", "Windows DirectSound")  # these give all of a name


def whole(name: str) -> str:
    """All of a recording device's name, for showing: "Microphone (Realtek High
    Definition Audio)" for "Microphone (Realtek High Defini". Windows' newer sound
    interfaces list the same devices with their names whole, so the one that begins this
    way is looked for there. `name` itself if it wasn't cut, or if none or more than one
    begins so.

    Only for showing. The device is still chosen, remembered and opened by the cut name."""
    if not config.WINDOWS or len(name) < CUT_AT:
        return name
    try:
        import sounddevice
        apis = sounddevice.query_hostapis()
        found = {device["name"] for device in sounddevice.query_devices()
                 if device["max_input_channels"] > 0
                 and apis[device["hostapi"]]["name"] in _WHOLE_NAMES
                 and device["name"].startswith(name)}
    except Exception:
        return name
    return found.pop() if len(found) == 1 else name


def _device(name: str):
    """The device called `name`, or None, meaning Windows' default, if there isn't one."""
    if name:
        for number, found in _inputs():
            if found == name:
                return number
    return None


def microphones(fresh: bool = False) -> list:
    """The names of the recording devices that can be chosen. Windows only; elsewhere the
    desktop's own sound settings choose, and this is empty.

    `fresh` reads the list from Windows again, which can only be done while this program
    has no recording open: with one open, the list is as it was when that one started."""
    if not config.WINDOWS:
        return []
    try:
        if fresh and not _streams:
            import sounddevice
            _look_again(sounddevice)
        return [name for _, name in _inputs()]
    except Exception:
        return []


def works(name: str = "") -> bool:
    """Whether the microphone can be recorded from just now: it is opened, a moment of
    sound is read, and it is closed again. For trying one that had stopped, without
    anybody being told until it is really back."""
    try:
        recorder = open_microphone(name)
    except Exception:
        return False
    try:
        return len(recorder.read(config.FRAME * 2)) == config.FRAME * 2
    finally:
        recorder.close()


def open_microphone(name: str = ""):
    """Start recording. The result has read(nbytes), which returns less at the end,
    close(), and why(), which says why it stopped if it stopped by itself. Raises
    MicrophoneError, with words for the person to read, if it can't be started."""
    return _SoundDevice(name) if config.WINDOWS else _Parec()
