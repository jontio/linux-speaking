"""What the tray icon shows and offers."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class State(Enum):
    OFF = "Off"            # microphone closed
    ASLEEP = "Asleep"      # listening only for "wake up"
    AWAKE = "Awake"        # dictating and taking commands
    HEARING = "Hearing"    # you are speaking
    THINKING = "Thinking"  # the speech model is working on what you said


@dataclass
class Status:
    state: State = State.OFF
    last_heard: str = ""
    writer_ready: bool = False  # something is in front to type into
    target: str = ""  # the program in front, such as "Writer" or "VS Code"
    target_known: bool = False  # the program in front has been looked for since waking
    ready: bool = True  # False while the speech models are still loading
    failed: str = ""  # why no speech model could be loaded, in plain words: "" when one was
    level: int = 0  # microphone level, 0 to 5 bars
    loud: bool = False  # the microphone signal is at or near its limit, and distorting
    meter: int = 0  # how far the sound is above the background, 0 to 100
    spelling: bool = False  # the spelling box is open
    spelled: str = ""      # the letters so far
    choosing: int = 0  # how many numbered matches are waiting for a choice
    update_waiting: bool = False  # an extension update needs LibreOffice closed
    voice_db: int = 0  # the last phrase's loudest point, in dB above the background
    listening_on: str = ""  # where the recognising is done, if another computer is set up
    # Things that stay wrong until somebody does something about them: each a plain
    # sentence that says what. The engine keeps the list; the tray and Settings show it.
    problems: list = field(default_factory=list)
    own_windows: int = 0  # how many of this program's own windows are open (the tray says)

    @property
    def awake(self) -> bool:
        return self.state in (State.AWAKE, State.HEARING, State.THINKING)

    def label(self) -> str:
        """The state in words. Having no model wins, then loading: nothing can be
        recognised in either case, whatever the microphone is doing."""
        if self.failed:
            return "No speech model"
        return self.state.value if self.ready else "Loading\u2026"

    def tooltip(self) -> str:
        lines = [f"Dictation: {self.label()}"]
        if self.failed:
            lines.append(self.failed)
        elif self.state is State.ASLEEP and self.ready:
            lines[0] += ". Say \"wake up\" to dictate."
        # Where the words will go is only said once it has been looked for, and only
        # while awake, which is when it is kept up to date: said at other times it was
        # often wrong, and "nothing in front" before anybody had looked.
        if self.awake and self.target_known and not self.failed:
            if not self.writer_ready:
                lines.append("Nothing to type into is in front")
            elif self.target:
                lines.append(f"Typing into {self.target}")
        if self.listening_on and self.state is not State.OFF:
            lines.append(f"Recognising on {self.listening_on}")
        if self.loud and self.state is not State.OFF:
            lines.append("Microphone too loud: turn it down")
        if self.update_waiting:
            lines.append("The Writer extension is waiting to go in: close LibreOffice for a moment")
        lines.extend(self.problems)
        if self.last_heard:
            lines.append(f"Heard: {self.last_heard}")
        return "\n".join(lines)

    def menu_toggle_label(self) -> str:
        return ("Turn the microphone on" if self.state is State.OFF
                else "Turn the microphone off")
