"""The microphone: 16 kHz mono, 16-bit, read a frame at a time."""
from __future__ import annotations

import subprocess

from . import config

# On Linux parec is used, not pw-record, because it lets the client be named. The
# desktop's microphone indicator then says "Linux Speaking is using the microphone".
RECORD_COMMAND = [
    "parec", "--raw", f"--rate={config.RATE}", "--channels=1", "--format=s16le",
    "--latency-msec=20", "--client-name=Linux Speaking",
    "--stream-name=Listening for dictation",
    "--property=application.icon_name=audio-input-microphone",
]


class _Parec:
    def __init__(self):
        self._process = subprocess.Popen(
            RECORD_COMMAND, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self, nbytes: int) -> bytes:
        return self._process.stdout.read(nbytes)

    def close(self) -> None:
        self._process.terminate()


class _SoundDevice:
    """Windows: a recording device, through PortAudio."""

    def __init__(self, name: str = ""):
        import sounddevice
        self._stream = sounddevice.RawInputStream(
            samplerate=config.RATE, channels=1, dtype="int16", blocksize=config.FRAME,
            device=_device(name))
        self._stream.start()

    def read(self, nbytes: int) -> bytes:
        try:
            data, _ = self._stream.read(nbytes // 2)
        except Exception:  # closed from another thread, or the device went away
            return b""
        return bytes(data)

    def close(self) -> None:
        try:
            self._stream.abort()
            self._stream.close()
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


def _device(name: str):
    """The device called `name`, or None, meaning Windows' default, if there isn't one."""
    if name:
        for number, found in _inputs():
            if found == name:
                return number
    return None


def microphones() -> list:
    """The names of the recording devices that can be chosen. Windows only; elsewhere the
    desktop's own sound settings choose, and this is empty."""
    if not config.WINDOWS:
        return []
    try:
        return [name for _, name in _inputs()]
    except Exception:
        return []


def open_microphone(name: str = ""):
    """Start recording. The result has read(nbytes), which returns less at the end, and close()."""
    return _SoundDevice(name) if config.WINDOWS else _Parec()
