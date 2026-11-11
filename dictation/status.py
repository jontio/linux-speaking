"""What the tray icon shows and offers."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(Enum):
    OFF = "Off"            # microphone closed
    ASLEEP = "Asleep"      # listening only for "wake up"
    AWAKE = "Awake"        # dictating and taking commands
    HEARING = "Hearing"    # you are speaking
    THINKING = "Thinking"  # Whisper is working on what you said


@dataclass
class Status:
    state: State = State.OFF
    last_heard: str = ""
    writer_ready: bool = False  # something is in front to type into
    target: str = ""  # the program in front, such as "Writer" or "VS Code"
    ready: bool = True  # False while the speech models are still loading
    level: int = 0  # microphone level, 0 to 5 bars
    loud: bool = False  # the microphone signal is at or near its limit, and distorting
    meter: int = 0  # how far the sound is above the background, 0 to 100
    spelling: bool = False  # the spelling box is open
    spelled: str = ""      # the letters so far
    choosing: int = 0  # how many numbered matches are waiting for a choice
    update_waiting: bool = False  # an extension update needs LibreOffice closed
    voice_db: int = 0  # the last phrase's loudest point, in dB above the background

    @property
    def awake(self) -> bool:
        return self.state in (State.AWAKE, State.HEARING, State.THINKING)

    def label(self) -> str:
        """The state in words. Loading wins, as nothing can be recognised yet."""
        return self.state.value if self.ready else "Loading\u2026"

    def tooltip(self) -> str:
        lines = [f"Dictation: {self.label()}"]
        if self.state is not State.OFF and not self.writer_ready:
            lines.append("No program to type into is in front")
        elif self.state is not State.OFF and self.target:
            lines.append(f"Typing into {self.target}")
        if self.loud and self.state is not State.OFF:
            lines.append("Microphone too loud: turn it down")
        if self.update_waiting:
            lines.append("Update waiting: close LibreOffice for a moment")
        if self.last_heard:
            lines.append(f"Heard: {self.last_heard}")
        return "\n".join(lines)

    def voice_line(self) -> str:
        if not self.voice_db:
            return "No phrase heard yet."
        if self.voice_db >= 25:
            verdict = "good"
        elif self.voice_db >= 15:
            verdict = "weak, but usable"
        else:
            verdict = "too weak"
        return f"Last phrase: {self.voice_db} dB above the background ({verdict}; 25 or more is good)."

    def menu_toggle_label(self) -> str:
        return "Turn on" if self.state is State.OFF else "Turn off"
