"""The tray icon. Run with: python -m dictation.tray"""
from __future__ import annotations

import os
import queue
import signal
import socket
import subprocess
import threading
import sys
import time

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from . import (APP_NAME, HOMEPAGE, __version__, audio, config, looks, models, reading, training,
               voicetest)
from .engine import Engine, meter_value, saved_on, write_text
from .reading_text import SENTENCES
from .settings import ITEMS, WINDOWS_ONLY, available_models, model_label, without_effect
from .status import State

LOADING_COLOUR = "#8e5bd0"
COLOURS = {
    State.OFF: "#d32f2f",       # red: the microphone is off and nothing will respond
    State.ASLEEP: "#e0a020",    # orange: asleep, but "wake up" will wake it
    State.AWAKE: "#2e9d4f",     # green: awake
    State.HEARING: "#2e9d4f",   # still green while you talk; the level bar shows it hearing
    State.THINKING: "#62b96f",  # a lighter green while it works out what you said
}


def make_loading_icon() -> QIcon:
    """Three dots on a purple disc: the speech models are still loading."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(LOADING_COLOUR))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.setBrush(QColor("white"))
    for x in (16, 32, 48):
        p.drawEllipse(QPointF(x, 32), 5.5, 5.5)
    p.end()
    return QIcon(pixmap)


TOO_LOUD = "#e53935"  # the meter's colour when the microphone is distorting


def make_icon(state: State, level: int = 0, pixels: int = 64, meter: bool = True,
              loud: bool = False) -> QIcon:
    """A microphone on a coloured disc, a slash when off, and a level bar when on."""
    return QIcon(make_pixmap(state, level, pixels, meter, loud))


def make_pixmap(state: State, level: int = 0, pixels: int = 64, meter: bool = True,
                loud: bool = False) -> QPixmap:
    size = 64  # drawn on a 64-unit grid, scaled to `pixels`
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(pixels / size, pixels / size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(COLOURS[state]))
    p.drawEllipse(2, 2, size - 4, size - 4)
    white = QColor("white")
    p.setBrush(white)
    p.drawRoundedRect(QRectF(25, 12, 14, 26), 7, 7)  # the mic body
    pen = QPen(white, 4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(18, 16, 28, 28), 180 * 16, 180 * 16)  # the cradle
    p.drawLine(QPointF(32, 44), QPointF(32, 52))
    p.drawLine(QPointF(24, 52), QPointF(40, 52))
    if state is State.OFF:
        slash = QPen(white, 6)
        slash.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(slash)
        p.drawLine(QPointF(14, 50), QPointF(50, 14))
    elif meter:
        # Level meter along the bottom: dark track, bright fill.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 200))
        p.drawRoundedRect(QRectF(2, 50, 60, 13), 4, 4)
        if loud:  # a full red bar: too loud
            p.setBrush(QColor(TOO_LOUD))
            p.drawRoundedRect(QRectF(4, 52, 56, 9), 3, 3)
        elif level:
            p.setBrush(QColor("#ffe45c"))
            p.drawRoundedRect(QRectF(4, 52, 56 * level / config.LEVEL_STEPS, 9), 3, 3)
    p.end()
    return pixmap


def write_app_icon(path: str, pixels: int = 256) -> None:
    """Save the green microphone as a picture, for the application menu. A name ending
    in .ico gives a Windows icon."""
    kind = "ICO" if path.lower().endswith(".ico") else "PNG"
    make_pixmap(State.AWAKE, pixels=pixels, meter=False).save(path, kind)


class Bridge(QObject):
    changed = pyqtSignal()
    level = pyqtSignal()
    event = pyqtSignal(str)
    numbers = pyqtSignal(list)  # numbered matches to show over another program's window
    hotkey = pyqtSignal()       # the key that switches dictation off and on was pressed


class OwnIdentity(QObject):
    """Windows: gives each of this program's windows its own name and icon on the taskbar.

    A program can normally say once who it is. But Python from the Microsoft Store runs
    as part of a Store package, and Windows then shows the package's name and icon,
    "Python", whatever the program says. What still works is to say it window by window.
    """

    def __init__(self, icon_path: str):
        super().__init__()
        self.icon_path = icon_path
        self.done = set()

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == QEvent.Type.Show and isinstance(watched, QWidget)
                and watched.isWindow()
                and watched.windowType() not in (Qt.WindowType.ToolTip, Qt.WindowType.Popup)):
            self.mark(watched)
        return False

    def mark(self, window) -> None:
        handle = int(window.winId())
        if handle in self.done:
            return
        self.done.add(handle)
        try:
            from win32com.propsys import propsys, pscon
            store = propsys.SHGetPropertyStoreForWindow(handle, propsys.IID_IPropertyStore)
            for key, value in (
                    (pscon.PKEY_AppUserModel_ID, "jontio.LinuxSpeaking.window"),
                    (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, APP_NAME),
                    (pscon.PKEY_AppUserModel_RelaunchIconResource, self.icon_path + ",0"),
                    # Pinned, it would have nothing to start: the Start menu has the entry.
                    (pscon.PKEY_AppUserModel_PreventPinning, True)):
                store.SetValue(key, propsys.PROPVARIANTType(value))
            store.Commit()
        except Exception as e:
            print(f"the taskbar will show Python's icon for a window: {e}", flush=True)


class Notice(QWidget):
    """Windows: a small notice in the corner by the clock, such as "Awake".

    Windows' own notices carry the name and icon of the program that sent them, which
    for Python from the Microsoft Store is "Python". They also pile up in its
    notification centre, one for every time dictation wakes or sleeps.
    """

    WIDEST = 360  # of the message, in pixels, before it wraps

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = self.card = QWidget()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: #2b2b2b; border: 1px solid #555; border-radius: 8px; }"
            "QLabel { color: #f2f2f2; font: 10pt 'Segoe UI', sans-serif; }"
            "#title { font-weight: bold; }")
        outer.addWidget(card)
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 16, 10)
        row.setSpacing(12)
        self.picture = QLabel()
        row.addWidget(self.picture)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.message = QLabel()
        self.message.setWordWrap(True)
        words.addWidget(self.title)
        words.addWidget(self.message)
        row.addLayout(words)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def say(self, title: str, message: str, icon: QIcon, milliseconds: int) -> None:
        self.title.setText(title)
        self.message.setText(message)
        self.picture.setPixmap(icon.pixmap(32, 32))
        # A label that wraps doesn't say how wide it would like to be: work it out.
        wanted = self.message.fontMetrics().horizontalAdvance(message) + 6
        self.message.setFixedWidth(min(self.WIDEST, wanted))
        for each in (self.card.layout(), self.layout()):
            each.invalidate()
            each.activate()
        self.resize(self.sizeHint())
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()  # leaves out the taskbar
            self.move(area.right() - self.width() - 16, area.bottom() - self.height() - 16)
        self.show()
        self.timer.start(max(1500, milliseconds))


class Numbers:
    """Small numbers shown over another program's window, one over each match for
    "select ...". Used where the program itself has nowhere to show them (Word, Outlook)."""

    def __init__(self):
        self.labels = []

    def show(self, places: list) -> None:
        """`places` is [(number, left, top, width, height), ...] in screen pixels, or []."""
        while len(self.labels) < len(places):
            label = QLabel()
            label.setWindowFlags(
                Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                | Qt.WindowType.WindowDoesNotAcceptFocus)
            label.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background: #ffe066; color: #1b1b1b; border: 1px solid #8a6d00;"
                "border-radius: 3px; padding: 0px 3px; font: bold 9pt 'Segoe UI', sans-serif;")
            self.labels.append(label)
        for label, (number, left, top, _width, _height) in zip(self.labels, places):
            label.setText(str(number))
            label.adjustSize()
            x, y = from_screen_pixels(left, top)
            label.move(x, max(0, y - label.height() + 2))  # just above the first letter
            label.show()
        for label in self.labels[len(places):]:
            label.hide()


def from_screen_pixels(x: int, y: int) -> tuple:
    """A point in real screen pixels, as Qt counts it on a scaled display."""
    for screen in QApplication.screens():
        area, scale = screen.geometry(), screen.devicePixelRatio()
        if (area.x() <= x < area.x() + area.width() * scale
                and area.y() <= y < area.y() + area.height() * scale):
            return (round(area.x() + (x - area.x()) / scale),
                    round(area.y() + (y - area.y()) / scale))
    return x, y


def look_of(window) -> str:
    """The look chosen in Settings for this app's windows: Windows' own, anywhere else."""
    return window.engine.settings.look if config.WINDOWS else ""


def dress(window, size=None, **how) -> None:
    """Give one of the app's windows the look chosen in Settings, as its last step in
    being made. With `size`, it is made that wide and high, the look's frame added on."""
    frame = looks.dress(window, look_of(window), **how)
    if size is not None:
        window.resize(size[0] + frame.width(), size[1] + frame.height())


def tell(window, text: str, kind: str = "warning") -> None:
    """Say something that has to be read, in a window of the chosen look."""
    if looks.known(look_of(window)):
        looks.message(window, look_of(window), window.windowTitle(), text, kind)
    elif kind == "information":
        QMessageBox.information(window, window.windowTitle(), text)
    else:
        QMessageBox.warning(window, window.windowTitle(), text)


def ask(window, text: str) -> bool:
    """Ask a yes or no question, in a window of the chosen look."""
    if looks.known(look_of(window)):
        return looks.message(window, look_of(window), window.windowTitle(), text, "question",
                             ("Yes", "No")) == "Yes"
    return QMessageBox.question(window, window.windowTitle(), text) == QMessageBox.StandardButton.Yes


class VolumeBar(QWidget):
    """How loud the voice is, as one smooth bar with no steps in it. Its length is the
    loudness and its colour is the verdict: grey too quiet, blue a little quiet, green a
    good level, yellow and orange getting too loud, red too loud. It rises with the
    voice at once and falls back gently, and a thin mark stays for a moment at the loudest
    it has been.
    See reading.level_colour for what is measured."""

    FALL = 3.0     # how far it falls back at each step, out of 100
    HOLD = 1.2     # seconds the mark stays, and seconds red stays after an overload

    def __init__(self):
        super().__init__()
        self.setFixedHeight(14)
        self.setMinimumWidth(190)
        self.setToolTip(
            "How loud your voice is. Green is a good level. Grey or blue is too quiet for "
            "the room: speak up, or move closer to the microphone. Yellow and orange are "
            "close to the most the microphone can take, and red is past it: move back, or "
            "turn the microphone down.")
        self.clear()
        self.steps = QTimer(self)
        self.steps.timeout.connect(self.step)

    def clear(self) -> None:
        self.place = self.above = self.mark = 0.0  # as they are drawn: all three fall back
        self.now = (0.0, 0.0)                      # as they were last heard: (place, above)
        self.mark_colour = reading.GREY
        self.marked = self.loud = 0.0              # when the mark was set, and when it was too loud
        if hasattr(self, "steps"):
            self.steps.stop()
        self.update()

    def hear(self, above: float, peak: float) -> None:
        """The newest level: how far the voice stands above the room (0 to 100), and the
        highest the sound went (1.0 is the most the microphone can carry)."""
        now = time.monotonic()
        place = reading.level_place(peak)
        self.now = (place, above)
        self.place, self.above = max(self.place, place), max(self.above, above)
        if place >= self.mark:
            self.mark, self.marked = place, now
            self.mark_colour = reading.level_colour(above, peak)
        if peak >= config.CLIP_LEVEL:
            self.loud = now
        if not self.steps.isActive():
            self.steps.start(33)
        self.update()

    def step(self) -> None:
        now = time.monotonic()
        self.place = max(self.now[0], self.place - self.FALL)
        self.above = max(self.now[1], self.above - self.FALL)
        if now - self.marked > self.HOLD:
            self.mark = max(self.place, self.mark - self.FALL)
        if self.place <= 0 and self.mark <= 0 and now - self.loud > self.HOLD:
            self.steps.stop()
        self.update()

    def paintEvent(self, event) -> None:
        too_loud = time.monotonic() - self.loud < self.HOLD
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        track = QRectF(0, 0, self.width(), self.height())
        radius = self.height() / 2
        p.setBrush(self.palette().color(self.palette().ColorRole.Midlight))
        p.drawRoundedRect(track, radius, radius)
        place = 100.0 if too_loud else min(self.place, 100.0)
        if place > 0:
            # The colour goes by where the bar is drawn, so it changes as smoothly as it moves.
            peak = 10 ** ((1.0 - place / 100.0) * reading.LOWEST_DB / 20.0)
            colour = reading.RED if too_loud else reading.level_colour(self.above, peak)
            p.save()
            p.setClipRect(QRectF(0, 0, self.width() * place / 100, self.height()))
            p.setBrush(QColor(*colour))
            p.drawRoundedRect(track, radius, radius)
            p.restore()
        if self.mark > 1 and not too_loud:
            x = min(self.width() - 2.0, self.width() * min(self.mark, 100.0) / 100)
            p.setBrush(QColor(*self.mark_colour))
            p.drawRect(QRectF(x - 1, 1, 2, self.height() - 2))
        p.end()


class MeterBridge(QObject):
    level = pyqtSignal(int, int, float, bool)  # which opening of the microphone it is
    #                              from, then as ReadBridge.level: how far the voice stands
    #                              above the room, the highest the sound went, and whether
    #                              somebody is speaking
    ended = pyqtSignal(int, str)  # that opening is over; what went wrong, or ""


class MeterWindow(QWidget):
    """How loud the voice is at the microphone, as it is spoken, with the bar and the
    colours of the reading window.

    Opening the window opens the microphone: nothing has to be pressed. Dictation is
    switched off for as long as it is open, so that what is said to try the level isn't
    typed anywhere, and comes back as it was when the window is closed or minimised."""

    SPOKEN = 6          # readings of the level, about a third of a second, before a phrase is judged
    QUIET_SECONDS = 6   # with nothing heard for this long, it says where to choose the microphone
    RETRY_SECONDS = 2   # a microphone that failed or stopped is tried again after this long
    WAITING = ("Speak as you do when you dictate. The bar shows how loud your voice is: "
               "green is a good level.")

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Microphone level")
        self.setMinimumWidth(400)
        self.listening = False   # the window is open, and has dictation held
        self.opening = 0         # goes up each time the microphone is opened or let go:
        #                          news from an earlier opening is old news
        self.stop = threading.Event()
        self.thread = None       # the one at the microphone
        self.microphone = ""     # the one it was opened on
        self.opened = 0.0        # when
        self.failed = 0.0        # when it failed or stopped; 0 while it is working
        self.measured = False    # the room has been measured: the bar is live
        self.heard = False       # somebody has spoken since it was opened
        self.hinted = False      # it has been said where to choose the microphone
        self.speaking = False
        self.reached, self.loudest, self.spoken = 0, 0.0, 0  # of the phrase being spoken
        self.bridge = MeterBridge()
        self.bridge.level.connect(self.on_level)
        self.bridge.ended.connect(self.on_ended)
        layout = QVBoxLayout(self)
        self.verdict = QLabel()  # the last phrase as a whole, in words
        layout.addWidget(self.verdict)
        self.bar = VolumeBar()   # the voice as it goes
        self.bar.setFixedHeight(22)
        layout.addWidget(self.bar)
        self.advice = QLabel()
        self.advice.setWordWrap(True)
        # Room for two lines always, so the window doesn't jump when the advice changes.
        self.advice.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.advice.setFixedHeight(2 * self.advice.fontMetrics().lineSpacing() + 2)
        layout.addWidget(self.advice)
        note = QLabel("Dictation is off while this window is open, and comes back as it "
                      "was when you close it.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.check)
        self.say("Opening the microphone\u2026", reading.GREY, "")
        dress(self)

    def say(self, words: str, colour: tuple, advice: str) -> None:
        self.verdict.setText(words)
        self.verdict.setStyleSheet(
            "font-size: 16pt; font-weight: bold; color: rgb(%d, %d, %d);" % colour)
        self.advice.setText(advice)

    # ---- the microphone is open while the window is ------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.isMinimized():
            self.listen()

    def hideEvent(self, event) -> None:
        self.let_go()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        """Minimised, it is as good as closed: dictation is not kept off by a window that
        can't be seen."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.let_go()
            elif self.isVisible():
                self.listen()

    def listen(self) -> None:
        if self.listening:
            return
        self.listening = True
        self.engine.hold()
        self.open_microphone()
        self.watch.start(500)

    def let_go(self, restore: bool = True) -> None:
        """Close the microphone and give dictation back as it was. Without `restore`,
        dictation is left alone: the program is closing."""
        if not self.listening:
            return
        self.listening = False
        self.watch.stop()
        self.close_microphone()
        self.bar.clear()
        self.say("Opening the microphone\u2026", reading.GREY, "")  # for the next time it is shown
        if restore:
            self.engine.unhold()

    def open_microphone(self) -> None:
        self.opening += 1
        self.stop = threading.Event()  # its own, so that an old thread can't be woken by it
        self.microphone = self.engine.settings.microphone
        self.opened, self.failed = time.monotonic(), 0.0
        self.measured = self.heard = self.hinted = self.speaking = False
        self.reached, self.loudest, self.spoken = 0, 0.0, 0
        self.thread = threading.Thread(
            target=self.work, args=(self.stop, self.opening, self.microphone), daemon=True)
        self.thread.start()

    def close_microphone(self) -> None:
        """Have the thread at the microphone close it, and wait for that: the microphone
        is not opened again, here or for dictation, while it is still being closed."""
        self.opening += 1
        self.stop.set()
        if self.thread is not None:
            self.thread.join(1.5)  # a frame's worth, as a rule: but never held up by a stuck device
            self.thread = None

    def check(self) -> None:
        """Twice a second, while the window is open."""
        now = time.monotonic()
        if self.failed:
            if now - self.failed >= self.RETRY_SECONDS:
                self.close_microphone()
                self.open_microphone()  # it may have been plugged back in
        elif self.microphone != self.engine.settings.microphone:
            self.close_microphone()     # another was chosen in Settings: the bar follows
            self.bar.clear()
            self.say("Opening the microphone\u2026", reading.GREY, "")
            self.open_microphone()
        elif not (self.heard or self.hinted) and now - self.opened >= self.QUIET_SECONDS:
            self.hinted = True
            self.advice.setText(
                "Nothing heard yet. If the bar doesn't move when you talk, "
                + ("choose another microphone in Settings." if config.WINDOWS else
                   "choose the microphone in your desktop's sound settings."))

    def work(self, stop, opening: int, microphone: str) -> None:
        import numpy as np
        try:
            recorder = audio.open_microphone(microphone)
        except Exception as e:
            self.bridge.ended.emit(opening, f"The microphone could not be opened: {e}")
            return
        problem = ""
        try:
            ear = reading.Ear(self.engine.boost)
            nbytes, loudest, peak, count = config.FRAME * 2, 0.0, 0, 0
            while not stop.is_set():
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    problem = "The microphone stopped."
                    break
                frame = np.frombuffer(data, dtype=np.int16)
                loudest = max(loudest, ear.feed(frame))
                peak = max(peak, int(np.max(np.abs(frame.astype(np.int32)))))
                count += 1
                if count == 3:  # some sixteen times a second: the bar moves as the voice does
                    if ear.ready:
                        self.bridge.level.emit(opening, meter_value(loudest, ear.room)[0],
                                               peak / 32767, ear.speaking)
                    loudest, peak, count = 0.0, 0, 0
        except Exception as e:  # whatever goes wrong, the window hears of it
            print(f"level meter: stopped by an error: {type(e).__name__}: {e}", flush=True)
            problem = f"The microphone could not be followed: {e}"
        finally:
            recorder.close()
        self.bridge.ended.emit(opening, problem)

    def on_level(self, opening: int, above: int, peak: float, speaking: bool) -> None:
        """The bar follows the voice as it goes. The words above it judge each phrase as a
        whole, by the most it has come to, once enough of it has been said: they don't
        change with every syllable, nor go blank between phrases."""
        if opening != self.opening or not self.listening:
            return
        if not self.measured:
            self.measured = True
            self.say("Say something", reading.GREY, self.WAITING)
        self.bar.hear(above, peak)
        if speaking and not self.speaking:
            self.reached, self.loudest, self.spoken = 0, 0.0, 0  # a new phrase
        self.speaking = speaking
        if speaking:
            self.spoken += 1
            self.reached, self.loudest = max(self.reached, above), max(self.loudest, peak)
            if self.spoken >= self.SPOKEN:
                self.heard = True
                words, colour = reading.level_verdict(self.reached, self.loudest)
                if words != self.verdict.text():
                    self.say(words, colour, reading.ADVICE[words])

    def on_ended(self, opening: int, problem: str) -> None:
        """The microphone could not be opened, or stopped by itself. It is tried again
        shortly, for as long as the window is open: see check()."""
        if opening != self.opening or not self.listening:
            return
        self.failed = time.monotonic()
        self.bar.clear()
        self.say("No microphone", reading.RED,
                 (problem or "The microphone stopped.") + " Trying again\u2026")


class SettingsWindow(QWidget):
    """Tick boxes for every voice command and punctuation word. Changes apply at once."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.on_setting = lambda key: None  # the tray's own reaction to a changed tick box
        self.setWindowTitle("Dictation settings")
        outer = QVBoxLayout(self)
        note = QLabel(
            "Untick anything you don't want acted on. It will be typed as ordinary "
            "words instead. \"Wake up\" and \"go to sleep\" are always on."
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        self.banner = QLabel(
            "An update is waiting. Until you close LibreOffice for a few seconds and "
            "reopen it, some of these won't take effect."
        )
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background: #e0a020; color: black; padding: 6px; border-radius: 4px;"
        )
        self.banner.setVisible(False)
        outer.addWidget(self.banner)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(self.model_box())
        if audio.microphones():
            layout.addWidget(self.microphone_box())
        layout.addWidget(self.words_box())
        layout.addWidget(self.remote_box())
        groups = {}
        self.ticks = {}  # by setting: those that do nothing as things stand are greyed
        for item in ITEMS:
            if item.key in WINDOWS_ONLY and not config.WINDOWS:
                continue
            if item.group not in groups:
                box = QGroupBox(item.group)
                box.setLayout(QVBoxLayout())
                layout.addWidget(box)
                groups[item.group] = box
            label = item.label
            if item.key == "other_apps" and config.WINDOWS:
                label = ("Dictate into other programs' text boxes, such as a chat box  "
                         "(typed in as keystrokes)")
            tick = QCheckBox(label)
            tick.setChecked(engine.settings.enabled(item.key))
            tick.toggled.connect(lambda on, key=item.key: (
                engine.settings.set(key, on), engine.setting_changed(key),
                self.on_setting(key)))
            groups[item.group].layout().addWidget(tick)
            self.ticks[item.key] = tick
        self.fit_ticks()
        if config.WINDOWS:
            layout.addWidget(self.look_box())
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        outer.addWidget(close)
        # Wide enough for the longest line, with room for the scroll bar.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The look that was chosen, if it isn't Windows' own: its sizes are other sizes.
        frame = looks.dress(self, look_of(self))
        self.ensurePolished()
        margins = outer.contentsMargins()
        width = (inner.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width()
                 + 2 * scroll.frameWidth() + margins.left() + margins.right() + 8)
        self.resize(max(420, width) + frame.width(), 640 + frame.height())

    def model_box(self) -> QGroupBox:
        """A chooser for the speech recognition model."""
        box = QGroupBox("Speech recognition model")
        layout = QVBoxLayout(box)
        self.models = QComboBox()
        self.refill_models()
        self.models.activated.connect(
            lambda index: (self.engine.set_model(self.models.itemData(index)), self.fit_ticks()))
        layout.addWidget(self.models)
        self.models_window = None
        more = QPushButton("Install or remove models…")
        more.clicked.connect(self.on_show_models)
        self.voice_window = None
        voice = QPushButton("Test them on my voice…")
        voice.clicked.connect(self.on_show_voice_test)
        self.read_window = None
        read = QPushButton("Read aloud for training…")
        read.clicked.connect(self.on_show_reading)
        self.train_window = None
        train = QPushButton("Train on my voice…")
        train.clicked.connect(self.on_show_training)
        row = QHBoxLayout()
        row.addWidget(more)
        row.addWidget(voice)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(read)
        row.addWidget(train)
        row.addStretch()
        layout.addLayout(row)
        note = QLabel("Bigger models make fewer mistakes but take longer after each phrase. "
                      "The change takes a few seconds to load. \"Wake up\" always uses "
                      "the recommended model.")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def look_box(self) -> QGroupBox:
        """A chooser for the look of the app's windows and of the tray icon's menu
        (Windows)."""
        box = QGroupBox("Appearance")
        row = QHBoxLayout(box)
        row.addWidget(QLabel("The look of the app's windows and the tray icon's menu:"))
        chooser = QComboBox()
        for key, label in looks.LOOKS:
            chooser.addItem(label, key)
        chooser.setCurrentIndex(max(0, chooser.findData(self.engine.settings.look)))
        chooser.activated.connect(lambda index: self.on_look(chooser.itemData(index)))
        row.addWidget(chooser)
        row.addStretch()
        return box

    def on_look(self, key: str) -> None:
        if key != self.engine.settings.look:
            self.engine.settings.set_look(key)
            self.on_setting("look")  # the tray makes this window again, in the new look

    def refill_models(self) -> None:
        """List the models that are installed, with the one in use chosen."""
        current = self.engine.settings.model or config.AWAKE_MODEL
        self.models.clear()
        for name, label in available_models(config.MODEL_DIR):
            self.models.addItem(label, name)
        at = self.models.findData(current)
        if at >= 0:
            self.models.setCurrentIndex(at)
        self.fit_ticks()

    QUICK_NOTE = ("For Whisper models. With a Parakeet model in use it only quickens what "
                  "Whisper still hears: spelling, source code and second opinions.")

    def fit_ticks(self) -> None:
        """Grey out the tick boxes that would do nothing with the model in use, and say
        why when the mouse rests on one. Their ticks are kept for when they do."""
        ticks = getattr(self, "ticks", {})  # the model chooser is made before the tick boxes
        idle = without_effect(self.engine.settings.model or config.AWAKE_MODEL,
                              self.engine.settings.remote, config.MODEL_DIR)
        for key, tick in ticks.items():
            tick.setEnabled(key not in idle)
            tick.setToolTip(idle.get(key, self.QUICK_NOTE if key == "quick_listening" else ""))

    def on_show_training(self) -> None:
        if self.train_window is None:
            self.train_window = TrainWindow(self.engine, self.refill_models)
        self.train_window.show()
        self.train_window.raise_()
        self.train_window.activateWindow()

    def on_show_voice_test(self) -> None:
        if self.voice_window is None:
            self.voice_window = VoiceTestWindow(self.engine)
        self.voice_window.show()
        self.voice_window.raise_()
        self.voice_window.activateWindow()

    def on_show_reading(self) -> None:
        if self.read_window is None:
            self.read_window = ReadWindow(self.engine)
        self.read_window.show()
        self.read_window.raise_()
        self.read_window.activateWindow()

    def on_show_models(self) -> None:
        if self.models_window is None:
            self.models_window = ModelsWindow(self.engine, self.refill_models)
        self.models_window.show()
        self.models_window.raise_()
        self.models_window.activateWindow()

    # ---- another computer doing the recognising ---------------------------------------
    def remote_box(self) -> QGroupBox:
        """Using another computer's recogniser, and letting others use this one's."""
        box = QGroupBox("Another computer")
        layout = QVBoxLayout(box)
        note = QLabel("A faster computer on your network can do the recognising. Tick the "
                      "lower box on that computer, then the upper one here with its address "
                      "and key. When it can't be reached, this computer does the work as "
                      "usual. The sound isn't encrypted on the way: keep to your own "
                      "network, or a VPN.")
        note.setWordWrap(True)
        layout.addWidget(note)
        chosen = self.engine.settings.remote
        self.remote_on = QCheckBox("Use another computer for speech recognition")
        self.remote_on.setChecked(chosen["on"])
        layout.addWidget(self.remote_on)
        form = QGridLayout()
        form.setContentsMargins(22, 0, 0, 0)
        self.remote_address = QLineEdit(chosen["address"])
        self.remote_address.setPlaceholderText("its name or address on the network")
        self.remote_key = QLineEdit(chosen["key"])
        self.remote_key.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.remote_key.setPlaceholderText("the key shown on that computer")
        self.remote_model = QComboBox()
        self.fill_remote_models([])
        connect = QPushButton("Connect")
        for row, (label, widget) in enumerate((("Address", self.remote_address),
                                               ("Key", self.remote_key),
                                               ("Model there", self.remote_model))):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        form.addWidget(connect, 0, 2)
        self.remote_wake = QCheckBox("Listen for \"wake up\" there too  (then everything it "
                                     "hears while asleep is sent)")
        self.remote_wake.setChecked(chosen["wake"])
        form.addWidget(self.remote_wake, 3, 0, 1, 3)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        self.remote_note = QLabel()
        self.remote_note.setWordWrap(True)
        layout.addWidget(self.remote_note)
        self.remote_bridge = RemoteBridge()
        self.remote_bridge.checked.connect(self.on_remote_checked)
        connect.clicked.connect(self.apply_remote)
        self.remote_on.clicked.connect(self.apply_remote)
        self.remote_wake.clicked.connect(self.apply_remote)
        self.remote_model.activated.connect(self.apply_remote)
        self.remote_address.returnPressed.connect(self.apply_remote)
        self.remote_key.returnPressed.connect(self.apply_remote)

        self.share_on = QCheckBox("Let other computers use this one for speech recognition")
        self.share_on.setChecked(self.engine.settings.share["on"])
        self.share_on.clicked.connect(self.apply_sharing)
        layout.addWidget(self.share_on)
        row = QHBoxLayout()
        row.setContentsMargins(22, 0, 0, 0)
        self.share_note = QLabel()
        self.share_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.share_copy = QPushButton("Copy key")
        self.share_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.engine.settings.share["key"]))
        row.addWidget(self.share_note, 1)
        row.addWidget(self.share_copy)
        layout.addLayout(row)
        self.refresh_sharing()
        return box

    def fill_remote_models(self, models: list) -> None:
        """The choice of model on the other computer: `models` is what it says it has."""
        chosen = self.engine.settings.remote["model"]
        self.remote_model.clear()
        self.remote_model.addItem("The same as on this computer, if it has it", "")
        for name, label in models:
            self.remote_model.addItem(label, name)
        if chosen and self.remote_model.findData(chosen) < 0:
            self.remote_model.addItem(chosen, chosen)  # not checked yet, or gone from there
        self.remote_model.setCurrentIndex(max(0, self.remote_model.findData(chosen)))

    def apply_remote(self, *_) -> None:
        """Save what is in the boxes and see whether the other computer answers."""
        self.engine.set_remote(
            self.remote_on.isChecked(), self.remote_address.text(), self.remote_key.text(),
            self.remote_model.currentData() or "", self.remote_wake.isChecked())
        self.check_remote()
        self.fit_ticks()

    def check_remote(self) -> None:
        chosen = self.engine.settings.remote
        if not chosen["address"] and not chosen["key"]:
            self.remote_note.setText("")
            return
        self.remote_note.setText("Asking the other computer\u2026")
        threading.Thread(
            target=lambda: self.remote_bridge.checked.emit(self.engine.check_remote()),
            daemon=True).start()

    def on_remote_checked(self, answer: dict) -> None:
        on = self.engine.settings.remote["on"]
        if answer.get("ok"):
            self.fill_remote_models(answer.get("models", []))
            self.remote_note.setText(
                "Connected. Recognition is done on the other computer." if on
                else "The other computer answers. Tick the box above to use it.")
        else:
            self.remote_note.setText(
                answer.get("why", "") + (" Recognition is being done on this computer." if on else ""))

    def apply_sharing(self, *_) -> None:
        self.engine.set_sharing(self.share_on.isChecked())
        self.refresh_sharing()
        if self.engine.share_problem:  # give a retry a moment, then say how it stands
            QTimer.singleShot(1500, self.refresh_sharing)

    def refresh_sharing(self) -> None:
        share = self.engine.settings.share
        on = share["on"] and bool(share["key"])
        self.share_copy.setVisible(on)
        if not on:
            self.share_note.setText("")
        elif self.engine.share_problem:
            self.share_note.setText(f"Not working yet: {self.engine.share_problem}")
        else:
            name = config.SHARE_ADDRESS or socket.gethostname()
            port = "" if config.SHARE_PORT == config.DEFAULT_SHARE_PORT else f":{config.SHARE_PORT}"
            self.share_note.setText(f"Address: {name}{port}\nKey: {share['key']}")

    def showEvent(self, event) -> None:
        self.refresh_sharing()
        if self.engine.settings.remote["on"]:
            self.check_remote()
        super().showEvent(event)

    def words_box(self) -> QGroupBox:
        """A list of the person's own names and terms."""
        box = QGroupBox("My words")
        layout = QVBoxLayout(box)
        note = QLabel("Names and unusual words that get misheard, one to a line, spelled "
                      "the way you want them typed. They are used where they fit: a name "
                      "after \"Cheers,\" but still the ordinary word in an ordinary "
                      "sentence. Keep the list short.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.words = QPlainTextEdit()
        self.words.setPlainText("\n".join(self.engine.settings.words))
        self.words.setTabChangesFocus(True)
        self.words.setFixedHeight(self.words.fontMetrics().lineSpacing() * 5 + 16)
        layout.addWidget(self.words)
        self.words_timer = QTimer(self)  # saved a moment after the typing stops
        self.words_timer.setSingleShot(True)
        self.words_timer.setInterval(700)
        self.words_timer.timeout.connect(self.save_words)
        self.words.textChanged.connect(self.words_timer.start)
        return box

    def save_words(self) -> None:
        self.words_timer.stop()
        self.engine.set_words(self.words.toPlainText())

    def hideEvent(self, event) -> None:
        self.save_words()
        super().hideEvent(event)

    def microphone_box(self) -> QGroupBox:
        """A chooser for the recording device, where the desktop has no good one itself."""
        box = QGroupBox("Microphone")
        layout = QVBoxLayout(box)
        self.microphones = QComboBox()
        self.microphones.addItem("Windows' default recording device", "")
        for name in audio.microphones():
            self.microphones.addItem(name, name)
        at = self.microphones.findData(self.engine.settings.microphone)
        if at >= 0:
            self.microphones.setCurrentIndex(at)
        self.microphones.activated.connect(
            lambda index: self.engine.set_microphone(self.microphones.itemData(index)))
        layout.addWidget(self.microphones)
        note = QLabel("Open \"Show level meter\" from the tray icon and talk: the bar should "
                      "move. If it doesn't, try another microphone here: the bar follows.")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box


class RemoteBridge(QObject):
    checked = pyqtSignal(dict)  # what the other computer said when asked what it offers


class ModelsBridge(QObject):
    progress = pyqtSignal(str, object, object)  # name, bytes so far, bytes in all
    finished = pyqtSignal(str, str)             # name, and what went wrong or ""


class ModelsWindow(QWidget):
    """Install and remove speech models. A download carries on with the window closed."""

    def __init__(self, engine: Engine, changed):
        super().__init__()
        self.engine = engine
        self.changed = changed  # called when a model has been added or removed
        self.fetching = None    # (name, models.Download) while one is being fetched
        self.told_at = 0.0
        self.bridge = ModelsBridge()
        self.bridge.progress.connect(self.on_progress)
        self.bridge.finished.connect(self.on_finished)
        self.setWindowTitle("Speech models")
        layout = QVBoxLayout(self)
        note = QLabel("Bigger models make fewer mistakes but take longer after each phrase. "
                      "They are downloaded from huggingface.co and kept on this computer. "
                      "Parakeet is a different kind of recogniser from the rest, which are "
                      "all Whisper: quicker, English only, and it can't be shown the text "
                      "before the cursor.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(0, 1)
        self.grid.setHorizontalSpacing(14)
        self.grid.setColumnMinimumWidth(2, 270)  # room for "Downloading: 40% (650 MB of 1.6 GB)"
        layout.addLayout(self.grid)
        self.space = QLabel()
        layout.addWidget(self.space)
        layout.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.status = {}  # name -> the label that says "Installed", "Downloading: 40%"...
        self.refresh()
        dress(self)

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def names(self) -> list:
        """The models that can be fetched, then any others that are here."""
        known = [k.name for k in models.KNOWN]
        return known + [n for n, _ in available_models(config.MODEL_DIR) if n not in known]

    def in_use(self, name: str) -> str:
        """Why a model can't be removed, or "" if it can."""
        if name == (self.engine.settings.model or config.AWAKE_MODEL):
            return "in use for dictation"
        if name == config.WAKE_MODEL:
            return "used to hear \"wake up\""
        return ""

    def refresh(self) -> None:
        """Draw the list again from what is on the disk."""
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)  # gone from view now, not a moment later
                widget.deleteLater()
        self.status = {}
        fetching = self.fetching[0] if self.fetching else ""
        for at, name in enumerate(self.names()):
            known = models.BY_NAME.get(name)
            installed = models.is_installed(config.MODEL_DIR, name)
            part = models.part_size(config.MODEL_DIR, name)
            path = os.path.join(config.MODEL_DIR, name)
            size = (models.folder_size(path) if installed
                    else known.megabytes * 1e6 if known else 0)
            self.grid.addWidget(QLabel(model_label(name)[1]), at, 0)
            self.grid.addWidget(QLabel(models.size_text(size)), at, 1,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            status, button, second = QLabel(), QPushButton(), None
            if name == fetching:
                status.setText("Downloading…")
                button.setText("Cancel")
                button.clicked.connect(self.on_cancel)
            elif installed:
                why = self.in_use(name)
                missing = (models.kind(config.MODEL_DIR, name) == "transducer"
                           and not models.transducers_usable())
                status.setText("Installed, but the sherpa-onnx library it needs isn't" if missing
                               else "Installed" + (f", {why}" if why else ""))
                button.setText("Remove")
                button.setEnabled(not why)
                button.clicked.connect(lambda _=False, name=name: self.on_remove(name))
            else:
                needs = (known is not None and known.marker in models.TRANSDUCERS
                         and not models.transducers_usable())
                status.setText("Needs the sherpa-onnx library: run the installer again" if needs
                               else f"Partly downloaded ({models.size_text(part)})" if part else "")
                button.setText("Carry on" if part else "Install")
                button.setEnabled(not fetching and not needs)
                button.clicked.connect(lambda _=False, name=name: self.on_install(name))
                if part:
                    second = QPushButton("Discard")
                    second.setEnabled(not fetching)
                    second.clicked.connect(lambda _=False, name=name: self.on_discard(name))
            self.status[name] = status
            self.grid.addWidget(status, at, 2)
            self.grid.addWidget(button, at, 3)
            if second is not None:
                self.grid.addWidget(second, at, 4)
        self.space.setText(
            f"Free disk space: {models.size_text(models.free_space(config.MODEL_DIR))}")

    def on_install(self, name: str) -> None:
        if self.fetching:
            return
        def tell(done, total):  # a few times a second is plenty for the window
            now = time.monotonic()
            if done >= total or now - self.told_at > 0.25:
                self.told_at = now
                self.bridge.progress.emit(name, done, total)

        download = models.Download(models.BY_NAME[name], config.MODEL_DIR, progress=tell)
        self.fetching = (name, download)

        def work():
            try:
                download.run()
                problem = ""
            except models.Cancelled:
                problem = "cancelled"
            except models.Failed as e:
                problem = str(e)
            except Exception as e:  # never leave the window saying "Downloading" for ever
                problem = f"Something went wrong: {e}"
            self.bridge.finished.emit(name, problem)

        threading.Thread(target=work, daemon=True).start()
        print(f"model {name}: download started", flush=True)
        self.refresh()

    def on_cancel(self) -> None:
        if self.fetching:
            self.fetching[1].cancel()
            self.status[self.fetching[0]].setText("Stopping…")

    def on_progress(self, name: str, done, total) -> None:
        label = self.status.get(name)
        if label is None or not total or not self.fetching or self.fetching[1].cancelled:
            return
        if done >= total:
            label.setText("Checking…")
        else:
            label.setText(f"Downloading: {int(100 * done / total)}%  "
                          f"({models.size_text(done)} of {models.size_text(total)})")

    def on_finished(self, name: str, problem: str) -> None:
        self.fetching = None
        print(f"model {name}: " + (problem or "installed"), flush=True)
        if problem == "cancelled":
            try:  # stopped on purpose, so nothing of it is wanted
                models.discard_part(config.MODEL_DIR, name)
            except OSError:
                pass
        self.refresh()
        self.changed()
        if problem and problem != "cancelled":
            tell(self, problem)

    def on_remove(self, name: str) -> None:
        label = model_label(name)[1]
        sure = ask(self, f"Remove this model?\n\n{label}\n\n"
                   + ("It can be installed again from here." if name in models.BY_NAME
                      else "It can't be installed again from here."))
        if not sure or self.in_use(name):
            return
        try:
            models.remove(config.MODEL_DIR, name)
            print(f"model {name}: removed", flush=True)
        except OSError as e:
            tell(self, f"It could not be removed: {e}")
        self.refresh()
        self.changed()

    def on_discard(self, name: str) -> None:
        try:
            models.discard_part(config.MODEL_DIR, name)
        except OSError as e:
            tell(self, f"It could not be removed: {e}")
        self.refresh()


class VoiceBridge(QObject):
    level = pyqtSignal(float, int)   # while recording: how loud, and seconds so far
    recorded = pyqtSignal(str)       # the recording is done; what went wrong, or ""
    listed = pyqtSignal(list)        # the recognisers that can be tried
    doing = pyqtSignal(str)          # what the test is busy with
    result = pyqtSignal(object)      # one recogniser's result
    finished = pyqtSignal(bool)      # the test is over; whether it ran to the end


class VoiceTestWindow(QWidget):
    """Read a passage aloud once, and see how each recogniser does on your own voice.
    See voicetest.py.

    Three tabs, one for each step, so that each has the whole window: the text to read,
    the recognisers to try, and how they did."""

    READING, CHOOSING, RESULTS = range(3)

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Test the recognisers on my voice")
        self.samples = voicetest.load_recording()
        self.results = []
        self.candidates = []
        self.tickers = []    # the "Tick all" and "Untick all" buttons
        self.ended = ""      # how the last test ended, if not well
        self.shared = []     # the slips every recogniser made alike: the reader's
        self.pressed = None  # the row the mouse went down on, and whether it was ticked
        self.recording = False
        self.running = False
        self.stop = threading.Event()
        self.bridge = VoiceBridge()
        self.bridge.level.connect(self.on_level)
        self.bridge.recorded.connect(self.on_recorded)
        self.bridge.listed.connect(self.on_listed)
        self.bridge.doing.connect(lambda text: self.progress.setText(text))
        self.bridge.result.connect(self.on_result)
        self.bridge.finished.connect(self.on_finished)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # 1. Reading it. All of the text in view at once: nobody can scroll and read aloud
        # at the same time.
        page = QWidget()
        inner = QVBoxLayout(page)
        note = QLabel("Read the text below aloud, the way you dictate, with a short pause "
                      "after each sentence. Say the punctuation or leave it out, as you "
                      "like: it isn't counted either way. The second half is full of words "
                      "that are easily taken for others, which is where recognisers differ. "
                      "Dictation is switched off while you record.")
        note.setWordWrap(True)
        inner.addWidget(note)
        passage = QLabel(" ".join(voicetest.PASSAGE))
        passage.setWordWrap(True)
        passage.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        passage.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        passage.setStyleSheet("font-size: 12pt; padding: 8px; border: 1px solid palette(mid);"
                              "border-radius: 4px; background: palette(base);")
        inner.addWidget(passage, 1)
        row = QHBoxLayout()
        self.record = QPushButton("Start recording")
        self.record.clicked.connect(self.on_record)
        self.recorded_note = QLabel()
        row.addWidget(self.record)
        row.addWidget(self.recorded_note, 1)
        inner.addLayout(row)
        self.tabs.addTab(page, "1. Read aloud")

        # 2. Which recognisers. The list has the whole tab, so all of them can be seen.
        page = QWidget()
        inner = QVBoxLayout(page)
        note = QLabel("Every recogniser ticked here hears that one recording, one after the "
                      "other. The more that are ticked, the longer the test takes.")
        note.setWordWrap(True)
        inner.addWidget(note)
        self.choices = QListWidget()
        self.choices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.choices.itemChanged.connect(lambda _: self.refresh())
        self.choices.itemPressed.connect(self.on_choice_pressed)
        self.choices.itemClicked.connect(self.on_choice_clicked)
        inner.addWidget(self.choices, 1)
        row = QHBoxLayout()
        for text, ticked in (("Tick all", True), ("Untick all", False)):
            button = QPushButton(text)
            button.clicked.connect(lambda _, ticked=ticked: self.tick_all(ticked))
            row.addWidget(button)
            self.tickers.append(button)
        self.ticked_note = QLabel()
        row.addWidget(self.ticked_note, 1)
        inner.addLayout(row)
        self.both = QCheckBox("Try Whisper both ways, with \"quicker recognition\" and without  "
                              "(takes a good deal longer)")
        self.both.clicked.connect(self.list_candidates)
        inner.addWidget(self.both)
        self.tabs.addTab(page, "2. What to try")

        # 3. How each one did.
        page = QWidget()
        inner = QVBoxLayout(page)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Recogniser", "Words wrong", "Near misses", "Time for a phrase"])
        self.table.horizontalHeaderItem(2).setToolTip(
            "Words it got right, but was less than 90% sure of: the ones that could as "
            "easily have come out wrong. Compare them between forms of the same "
            "recogniser, not between different ones: each measures its own sureness in "
            "its own way.")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self.show_slips)
        inner.addWidget(self.table, 3)
        self.advice = QLabel()
        self.advice.setWordWrap(True)
        inner.addWidget(self.advice)
        self.slips = QPlainTextEdit()
        self.slips.setReadOnly(True)
        self.slips.setPlaceholderText("Click a row to see the words it got wrong.")
        inner.addWidget(self.slips, 1)
        self.tabs.addTab(page, "3. Results")

        # Under the tabs, so the test can be started, watched and stopped from any of them.
        row = QHBoxLayout()
        self.run = QPushButton("Run the test")
        self.run.clicked.connect(self.on_run)
        self.progress = QLabel()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(self.run)
        row.addWidget(self.progress, 1)
        row.addWidget(close)
        layout.addLayout(row)
        dress(self, (760, 600))
        when, results = voicetest.load_results()
        if results:
            self.results = results
            self.fill_table(f"From the test on {when}.")
        # It opens at the step that comes next: reading, choosing, or the last results.
        self.tabs.setCurrentIndex(self.RESULTS if results else
                                  self.CHOOSING if self.samples is not None else self.READING)
        self.refresh()

    # ---- what can be pressed, and what the notes say ------------------------------------
    def ticked(self) -> int:
        return sum(self.choices.item(n).checkState() == Qt.CheckState.Checked
                   for n in range(self.choices.count()))

    def refresh(self) -> None:
        ticked, listed = self.ticked(), self.choices.count()
        ready = self.samples is not None and ticked > 0
        self.record.setText("Stop recording" if self.recording else
                            "Record again" if self.samples is not None else "Start recording")
        self.record.setEnabled(not self.running)
        self.run.setText("Cancel" if self.running else "Run the test")
        self.run.setEnabled(not self.recording and (self.running or ready))
        self.both.setEnabled(not self.running)
        self.choices.setEnabled(not self.running)
        for button in self.tickers:
            button.setEnabled(not self.running)
        self.ticked_note.setText(f"{ticked} of {listed} ticked." if listed else "")
        if not self.recording:
            seconds = 0 if self.samples is None else len(self.samples) // config.RATE
            self.recorded_note.setText(
                f"Recording kept: {seconds // 60} min {seconds % 60} s." if seconds
                else "The text has changed since you recorded, so it needs reading again."
                if voicetest.recording_is_old() else "Nothing recorded yet.")
        if not self.running:
            # Why the test can't be run yet, if it can't; else how the last one ended.
            why = ("" if self.recording or ready or not listed else
                   "First record the text, on the first tab." if self.samples is None else
                   "Nothing is ticked on the second tab.")
            self.progress.setText(why or self.ended)
        if not self.results and not self.running:
            self.advice.setText("No test has been run yet.")

    # A click anywhere on a row ticks or unticks it, not only a click on the little box.
    def on_choice_pressed(self, item) -> None:
        self.pressed = (self.choices.row(item), item.checkState())

    def on_choice_clicked(self, item) -> None:
        pressed, self.pressed = self.pressed, None
        if pressed == (self.choices.row(item), item.checkState()):  # the box didn't take it
            item.setCheckState(Qt.CheckState.Unchecked if pressed[1] == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)

    def tick_all(self, ticked: bool) -> None:
        state = Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked
        self.choices.blockSignals(True)
        for n in range(self.choices.count()):
            self.choices.item(n).setCheckState(state)
        self.choices.blockSignals(False)
        self.refresh()

    def showEvent(self, event) -> None:
        self.list_candidates()
        super().showEvent(event)

    def closeEvent(self, event) -> None:
        self.stop.set()  # ends a recording, or a test, that is under way
        super().closeEvent(event)

    # ---- which recognisers ---------------------------------------------------------------
    def list_candidates(self, *_) -> None:
        both = self.both.isChecked()
        threading.Thread(
            target=lambda: self.bridge.listed.emit(self.engine.test_candidates(both)),
            daemon=True).start()

    def on_listed(self, candidates: list) -> None:
        if self.running:
            return
        unticked = {self.choices.item(n).text() for n in range(self.choices.count())
                    if self.choices.item(n).checkState() != Qt.CheckState.Checked}
        self.candidates = candidates
        self.choices.blockSignals(True)  # one refresh at the end, not one for each
        self.choices.clear()
        for candidate in candidates:
            item = QListWidgetItem(candidate.title())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if candidate.title() in unticked
                               else Qt.CheckState.Checked)
            self.choices.addItem(item)
        self.choices.blockSignals(False)
        self.refresh()

    # ---- recording -------------------------------------------------------------------------
    def on_record(self) -> None:
        if self.recording:
            self.stop.set()
            return
        self.stop.clear()
        self.recording = True
        self.engine.hold()
        self.recorded_note.setText("Recording\u2026 read the text, then press Stop.")
        self.refresh()
        threading.Thread(target=self.record_work, daemon=True).start()

    def record_work(self) -> None:
        import numpy as np
        try:
            recorder = audio.open_microphone(self.engine.settings.microphone)
        except Exception as e:
            self.bridge.recorded.emit(f"The microphone could not be opened: {e}")
            return
        frames, nbytes, started = [], config.FRAME * 2, time.monotonic()
        loudest, count = 0.0, 0
        try:
            while not self.stop.is_set() and time.monotonic() - started < voicetest.LONGEST_SECONDS:
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    break
                frame = np.frombuffer(data, dtype=np.int16)
                frames.append(frame)
                loudest = max(loudest, float(np.max(np.abs(frame.astype(np.int32)))) / 32768)
                count += 1
                if count == 10:  # five times a second
                    self.bridge.level.emit(loudest, int(time.monotonic() - started))
                    loudest, count = 0.0, 0
        finally:
            recorder.close()
        if len(frames) < 5 * config.RATE // config.FRAME:
            self.bridge.recorded.emit("That was too short to test with. Read the whole text.")
            return
        samples = np.concatenate(frames)
        try:
            voicetest.save_recording(samples)
        except OSError as e:
            self.bridge.recorded.emit(f"The recording could not be kept: {e}")
            return
        self.samples = samples
        self.bridge.recorded.emit("")

    def on_level(self, loudest: float, seconds: int) -> None:
        if self.recording:
            bar = "\u2588" * min(12, round(loudest * 24))
            self.recorded_note.setText(f"Recording\u2026 {seconds // 60}:{seconds % 60:02d}   {bar}")

    def on_recorded(self, problem: str) -> None:
        self.recording = False
        self.engine.unhold()
        self.refresh()
        if problem:
            tell(self, problem)

    # ---- the test ----------------------------------------------------------------------------
    def on_run(self) -> None:
        if self.running:
            self.stop.set()
            self.progress.setText("Stopping\u2026")
            return
        chosen = [candidate for n, candidate in enumerate(self.candidates)
                  if self.choices.item(n).checkState() == Qt.CheckState.Checked]
        if not chosen or self.samples is None:
            return
        self.stop.clear()
        self.running = True
        self.ended = ""
        self.results = []
        self.table.setRowCount(0)
        self.advice.setText("")
        self.slips.setPlainText("")
        self.tabs.setCurrentIndex(self.RESULTS)  # they are shown as they come in
        self.refresh()
        threading.Thread(target=self.run_work, args=(chosen, self.samples), daemon=True).start()

    def run_work(self, chosen: list, samples) -> None:
        self.bridge.doing.emit("Cutting the recording into phrases\u2026")
        sounds = voicetest.phrases(samples, self.engine.boost)
        said = voicetest.words(" ".join(voicetest.PASSAGE))
        print(f"voice test: {len(sounds)} phrases, {len(chosen)} recognisers", flush=True)
        finished = bool(sounds)
        for at, candidate in enumerate(chosen, start=1):
            title = f"{candidate.title()}  ({at} of {len(chosen)})"
            self.bridge.doing.emit(f"{title}: loading\u2026")
            result = voicetest.try_one(
                candidate, sounds, said, self.engine.test_hear,
                progress=lambda done: self.bridge.doing.emit(
                    f"{title}: phrase {done} of {len(sounds)}"),
                cancelled=self.stop.is_set)
            self.engine.test_done(candidate)
            if result is None:
                finished = False
                break
            self.bridge.result.emit(result)
        self.bridge.finished.emit(finished)

    def on_result(self, result) -> None:
        self.results.append(result)
        self.fill_table("")

    def on_finished(self, finished: bool) -> None:
        self.running = False
        self.ended = "" if finished else "Stopped before the end."
        if self.results:
            try:
                voicetest.save_results(self.results)
            except OSError:
                pass
            self.fill_table("")
        self.refresh()

    def fill_table(self, note: str) -> None:
        """Show the results, best first: fewest words wrong, then quickest.

        Slips that every recogniser made alike were in the reading, and are left out of
        each one's count."""
        self.shared = voicetest.shared_slips(self.results)
        own = lambda result: voicetest.own_wrong(result, self.shared)
        self.results.sort(key=lambda r: (bool(r.problem), own(r), r.seconds))
        self.table.setRowCount(len(self.results))
        for row, result in enumerate(self.results):
            if result.problem:
                cells = (result.title, "couldn't be tried", "", result.problem)
            else:
                wrong = own(result)
                percent = 100.0 * wrong / result.total if result.total else 0.0
                cells = (result.title, f"{wrong} of {result.total}  ({percent:.1f}%)",
                         str(result.near) if result.near >= 0 else "\u2014",
                         f"{result.seconds:.1f} s")
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        for column in (1, 2, 3):
            self.table.resizeColumnToContents(column)
        pick = voicetest.suggestion(self.results)
        advice = [note] if note else []
        if pick and not self.running:
            advice.append(f"Suggested: {pick}. It is the quickest of those about as accurate "
                          "as the best.")
        if any(result.where == "team" for result in self.results):
            advice.append("To dictate with a recogniser checked by others, tick \"Second "
                          "opinions\" in Settings: it is a trial.")
        if any(result.near >= 0 for result in self.results):
            advice.append("A near miss is a word that came out right, but that the recogniser "
                          "was less than 90% sure of. The numbers compare between forms of the "
                          "same recogniser, not between different ones.")
        if self.shared:
            words = sum(voicetest.score(voicetest.words(said), voicetest.words(heard))[0]
                        for said, heard in self.shared)
            advice.append(
                f"Not counted: {words} word{'s' if words != 1 else ''} that every recogniser "
                "wrote the same way, so most likely read differently from the text: "
                + ", ".join(self.slip_text(said, heard, " \u2192 ")
                            for said, heard in self.shared[:6]) + ".")
        self.advice.setText(" ".join(advice))
        self.show_slips()

    @staticmethod
    def slip_text(said: str, heard: str, arrow: str = "  \u2192  ") -> str:
        return f"{said or '(nothing)'}{arrow}{heard or '(left out)'}"

    def show_slips(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self.results):
            return
        result = self.results[rows[0].row()]
        if result.problem:
            self.slips.setPlainText(result.problem)
            return
        shared = set(map(tuple, self.shared))
        mine = [pair for pair in result.slips if tuple(pair) not in shared]
        read = [pair for pair in result.slips if tuple(pair) in shared]
        lines = [self.slip_text(said, heard) for said, heard in mine] or ["Every word right."]
        if result.note:
            lines = [result.note, ""] + lines
        if result.shaky:
            lines += ["", "Right, but less than 90% sure (near misses):",
                      ",  ".join(f"{word} {percent}%" for word, percent in result.shaky)]
        elif result.near == 0:
            lines += ["", "No near misses: it was at least 90% sure of every word it got right."]
        if read:
            lines += ["", "In the reading, and not counted:"]
            lines += [self.slip_text(said, heard) for said, heard in read]
        self.slips.setPlainText("\n".join(lines))


class ReadBridge(QObject):
    level = pyqtSignal(int, float, bool)  # many times a second: how far the voice stands
    #                              above the room (0 to 100), the highest the sound went
    #                              (1.0 is the most there can be), and whether the reader
    #                              is speaking
    ready = pyqtSignal()         # the room has been measured: reading can begin
    taken = pyqtSignal(object)   # one sentence's sound is complete: a reading.Take
    heard = pyqtSignal(int, int, object)  # at a pause: which sentence's sound it was, the
    #                              mark to end it at, and what a recogniser heard (None: it couldn't)
    ended = pyqtSignal(str)      # the microphone is closed; what went wrong, or ""


class ReadWindow(QWidget):
    """Read sentences aloud, one at a time. Each one's sound is kept beside its text,
    which is what a recogniser could be retrained on. See reading.py.

    Half an hour of reading is a long sitting. So nothing has to be pressed: it moves on
    when a recogniser has heard the sentence to its end. It can be paused for a rest,
    pauses by itself when the reader goes away, and always says how far there is to go.

    One button starts, pauses and carries on. Paused, nothing is held: the microphone is
    closed and dictation is back, so closing the window is all the stopping there is."""

    BUILT_IN, OWN = range(2)
    IDLE_SECONDS = 60  # with nothing read or pressed for this long, it pauses by itself

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Read aloud for training")
        self.kept = reading.Kept()
        self.reading = False     # the microphone is open, or being opened or closed
        self.listening = False   # it is open and the room has been measured
        self.pausing = False     # it is being closed
        self.paused = False      # it is closed for a rest, with the place kept
        self.idled = False       # it is being closed because the reader went away
        self.leaving = False     # it is being closed because the window was
        self.current = ""        # the sentence on the screen
        self.upcoming = []       # those after it
        self.passed = []         # this sitting's sentences so far: (text, whether it was kept)
        self.awaiting = []       # sentences read, whose sound hasn't come back yet
        self.count, self.seconds, self.there_are = 0, 0.0, 0
        self.acted = 0.0         # when the reader last pressed anything, or a sentence was kept
        self.shown = 0.0         # when the sentence on the screen came up, or was begun again
        self.hinted = False      # it has been said that this sentence seems to be waiting
        self.reached = 0         # the furthest above the room this sentence has been,
        self.loudest = 0.0       # the highest its sound has gone,
        self.spoken = 0          # and for how many readings of the level it has been spoken
        self.orders = queue.Queue()  # for the thread at the microphone: see order()
        self.epoch = 0           # goes up with every order, so that old news can be told
        self.auto = True         # move on when the sentence has been heard to its end
        self.stop = threading.Event()
        self.cutter = None       # cuts the sitting's sound into sentences: see reading.py
        self.bridge = ReadBridge()
        self.bridge.level.connect(self.on_level)
        self.bridge.ready.connect(self.on_ready)
        self.bridge.taken.connect(self.on_taken)
        self.bridge.heard.connect(self.on_heard)
        self.bridge.ended.connect(self.on_ended)
        layout = QVBoxLayout(self)
        note = QLabel("Read each sentence aloud, the way you dictate. It moves on by itself "
                      "when it has heard you reach the end. The space bar moves on at once, "
                      "or passes over a sentence you haven't read. If you stumble, start the "
                      "sentence again. Pause for a rest whenever you like: your place is "
                      "kept, today and for another day. Each sentence's sound is kept on "
                      "this computer beside its text, as material for retraining a "
                      "recogniser to your voice. Dictation is switched off while you read.")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(QLabel("Read from:"))
        self.source = QComboBox()
        self.source.addItem("The sentences that come with it")
        self.source.addItem("A text of my own")
        self.source.activated.connect(self.on_source)
        self.choose = QPushButton("Choose my text\u2026")
        self.choose.clicked.connect(self.on_choose)
        for chooser in (self.source, self.choose):
            chooser.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the space bar is never theirs
        row.addWidget(self.source)
        row.addWidget(self.choose)
        row.addStretch()
        self.by_itself = QCheckBox("Move on by itself")
        self.by_itself.setChecked(True)
        self.by_itself.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.by_itself.setToolTip(
            "At each pause, the recogniser you dictate with hears the sentence so far. When "
            "it has heard it to the end, the sound is kept and the next sentence comes up. "
            "Unticked, each sentence waits for Next or the space bar.")
        self.by_itself.toggled.connect(self.on_by_itself)
        row.addWidget(self.by_itself)
        layout.addLayout(row)
        # One sentence, large: it is read from a little way off, with the eyes on nothing else.
        self.sentence = QLabel()
        self.sentence.setWordWrap(True)
        self.sentence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sentence.setMinimumHeight(170)
        layout.addWidget(self.sentence, 1)
        self.bar = QProgressBar()  # how far through the text
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)
        row = QHBoxLayout()
        self.volume = VolumeBar()  # the voice against the room, as it is spoken
        self.volume.setFixedWidth(190)
        self.volume_note = QLabel()  # and in words, for the sentence as a whole
        self.volume_note.setFixedWidth(112)
        self.said = QLabel()
        self.said.setWordWrap(True)
        row.addWidget(self.volume)
        row.addWidget(self.volume_note)
        row.addWidget(self.said, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.next = QPushButton("Next  (space bar)")
        self.next.clicked.connect(self.on_next)
        self.again = QPushButton("Start this one again  (A)")
        self.again.clicked.connect(self.on_again)
        self.back = QPushButton("Go back one  (backspace)")
        self.back.clicked.connect(self.on_back)
        self.go = QPushButton()  # starts, pauses and carries on
        self.go.clicked.connect(self.on_go)
        self.once_more = QPushButton("Read them all again")  # there when a text has been read
        self.once_more.clicked.connect(self.on_once_more)
        # Back on the left and on to the right, as they are everywhere else.
        for button in (self.back, self.again, self.next, None, self.once_more, self.go):
            if button is None:
                row.addStretch()  # the sentence on the left, the sitting on the right
                continue
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the space bar is never a button's
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.totals = QLabel()
        folder = QPushButton("Open the folder")
        folder.clicked.connect(self.on_folder)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(self.totals, 1)
        row.addWidget(folder)
        row.addWidget(close)
        layout.addLayout(row)
        for key, action in ((Qt.Key.Key_Space, self.on_next), (Qt.Key.Key_Return, self.on_next),
                            (Qt.Key.Key_Enter, self.on_next), (Qt.Key.Key_Backspace, self.on_back),
                            (Qt.Key.Key_A, self.on_again), (Qt.Key.Key_P, self.on_pause_key)):
            QShortcut(QKeySequence(key), self).activated.connect(action)
        self.idle = QTimer(self)
        self.idle.timeout.connect(self.check_idle)
        self.idle.start(1000)
        dress(self, (760, 480))
        if (not reading.unread(SENTENCES, self.kept, self.kept.rounds(self.NAMES[self.BUILT_IN]))
                and reading.own_text()[0]):
            self.source.setCurrentIndex(self.OWN)  # the ones that come with it are all read
        self.fill()
        self.refresh()

    # ---- what there is to read -------------------------------------------------------------
    def fill(self) -> None:
        """List the sentences of the chosen text that are still to be read."""
        sentences = self.text()
        self.there_are = len(sentences)
        self.rounds = self.kept.rounds(self.NAMES[self.source.currentIndex()])
        self.upcoming = reading.unread(sentences, self.kept, self.rounds)
        self.count, self.seconds = self.kept.totals()

    NAMES = ("the sentences that come with it", "a text of my own")  # in rounds.json

    def text(self) -> list:
        """The sentences of the chosen text, read or not."""
        own = self.source.currentIndex() == self.OWN
        return reading.own_text()[0] if own else list(SENTENCES)

    def on_once_more(self) -> None:
        """The text has been read to its end: go through it again from the top. What was
        read before is kept, and the new readings beside it."""
        sentences = self.text()
        if sentences and not self.reading and not self.upcoming:
            self.kept.set_rounds(self.NAMES[self.source.currentIndex()],
                                 reading.read_through(sentences, self.kept) + 1)
            self.fill()
            self.refresh()

    def on_source(self, index: int) -> None:
        if index == self.OWN and not reading.own_text()[0]:
            self.on_choose()  # none has been chosen yet
            return
        self.fill()
        self.refresh()

    def on_choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "A text to read aloud", "",
                                              "Plain text (*.txt);;All files (*)")
        if path:
            try:
                found, left_out = reading.choose_own_text(path)
            except OSError as e:
                found, left_out = [], 0
                tell(self, f"That file could not be read: {e.strerror or e}")
            else:
                if not found:
                    tell(self, "No sentences that can be read for training were found in "
                               "that file. It needs to be plain text, in whole sentences.")
                else:
                    plural = "s" if len(found) != 1 else ""
                    tell(self, f"{len(found)} sentence{plural} can be read."
                         + (f" {left_out} were left out: any with figures or unusual marks "
                            "in them, which a recogniser may write another way, and any that "
                            "are very short or very long." if left_out else ""), "information")
        self.source.setCurrentIndex(self.OWN if reading.own_text()[0] else self.BUILT_IN)
        self.fill()
        self.refresh()

    # ---- what can be pressed, and what the notes say ------------------------------------
    def refresh(self) -> None:
        live = self.reading and self.listening
        self.go.setText("Pause  (P)" if self.reading else "Carry on  (space bar)"
                        if self.paused else "Start reading  (space bar)")
        self.go.setEnabled(not self.pausing and (self.reading or bool(self.upcoming)))
        self.next.setEnabled(live and bool(self.current))
        self.again.setEnabled(live and bool(self.current))
        self.back.setEnabled(live and bool(self.passed) and not self.awaiting)
        self.source.setEnabled(not self.reading)
        self.choose.setEnabled(not self.reading)
        self.once_more.setVisible(not self.reading and not self.paused and not self.upcoming
                                  and self.there_are > 0)
        if live and self.current:
            text, size, shade = self.current, 18, "palette(text)"
        else:
            size, shade = 11, "palette(mid)"
            text = ("Getting ready\u2026" if self.reading and not self.listening
                    and not self.pausing else
                    "" if self.reading else
                    "You have read every sentence of this text"
                    + ("" if getattr(self, "rounds", 1) < 2 else f", {self.rounds} times over")
                    + ". Choose a text of your own to go on, or read these all again: what "
                    "you read before is kept, and the new readings beside it."
                    if not self.upcoming else
                    "Paused. Press the space bar when you are ready, and read when the "
                    "sentence is back.\n\n"
                    "The microphone is closed, and dictation is back as it was."
                    if self.paused else
                    "Press the space bar, or \"Start reading\", and the first sentence "
                    "comes up here.")
        self.sentence.setText(text)
        self.sentence.setStyleSheet(
            f"font-size: {size}pt; color: {shade}; padding: 16px; border-radius: 4px;"
            "border: 1px solid palette(mid); background: palette(base);")
        if not live:
            self.volume.clear()
            self.volume_note.setText("")
        left = len(self.upcoming) + bool(self.current)
        self.bar.setRange(0, max(1, self.there_are))
        self.bar.setValue(max(0, self.there_are - left))
        plural = "s" if self.count != 1 else ""
        now = sum(1 for _, was_kept in self.passed if was_kept)
        self.totals.setText(
            f"Kept so far: {self.count} sentence{plural}, {reading.time_text(self.seconds)}"
            + (f" ({now} this sitting)" if self.reading or self.paused else "")
            + f".  {left} of {self.there_are} still to read here.")

    def on_by_itself(self, on: bool) -> None:
        self.auto = on
        self.fresh()

    def order(self, name: str, *more) -> None:
        """Tell the thread at the microphone that the sentence's sound ends ("next", or
        "accept" and a mark) or begins afresh ("again")."""
        self.epoch += 1
        self.fresh()
        self.orders.put((name, self.epoch, *more))

    def fresh(self) -> None:
        """A sentence has just come up, or is being read afresh."""
        self.shown, self.hinted = time.monotonic(), False
        self.reached, self.loudest, self.spoken = 0, 0.0, 0

    SPOKEN = 6  # readings of the level, about a third of a second, before a sentence is judged

    def on_level(self, above: int, peak: float, speaking: bool) -> None:
        """The bar follows the voice as it goes. The words beside it judge the sentence
        as a whole, by the most it has come to, once enough of it has been said: they
        don't change with every syllable, nor go blank between sentences."""
        if not (self.reading and self.listening):
            return
        self.volume.hear(above, peak)
        if speaking:
            self.spoken += 1
            self.reached, self.loudest = max(self.reached, above), max(self.loudest, peak)
        if self.spoken >= self.SPOKEN:
            words, colour = reading.level_verdict(self.reached, self.loudest)
            self.volume_note.setText(words)
            self.volume_note.setStyleSheet("color: rgb(%d, %d, %d); font-weight: bold;" % colour)

    def on_folder(self) -> None:
        try:
            os.makedirs(reading.FOLDER, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(reading.FOLDER))

    def closeEvent(self, event) -> None:
        if self.reading:
            self.leaving = True  # on_ended sees to the rest, once the microphone is closed
            self.pausing = False
            self.close_microphone()
        else:
            self.forget()
        super().closeEvent(event)

    # ---- a sitting: starting, resting, carrying on ------------------------------------------
    def on_go(self) -> None:
        """The one button: start, pause for a rest, carry on."""
        if self.reading:
            self.close_microphone()
        else:
            self.begin()

    def on_pause_key(self) -> None:
        if self.reading or self.paused:
            self.on_go()

    def begin(self) -> None:
        """Open the microphone, to start a sitting or to carry on after a rest."""
        if not self.paused or self.cutter is None or self.kept.day != time.strftime("%Y-%m-%d"):
            self.kept = reading.Kept()  # a new sitting, under today's date
            self.passed = []
            self.fill()
            self.cutter = reading.Cutter(self.engine.boost)
        else:
            self.cutter.reopened()  # the room it measured still stands: no wait before reading
        self.paused = False
        if not self.upcoming:
            self.refresh()
            return
        self.current, self.awaiting = "", []
        self.reading = True
        self.listening = self.pausing = self.idled = False
        self.engine.hold()
        self.said.setText("")
        self.setFocus()
        while not self.orders.empty():
            self.orders.get_nowait()
        self.epoch += 1  # anything still on its way from before is old news
        self.stop = threading.Event()  # its own, so that an old thread can't be woken by it
        self.acted = time.monotonic()
        self.refresh()
        threading.Thread(target=self.work, args=(self.stop, self.cutter, self.epoch),
                         daemon=True).start()

    def close_microphone(self, idle: bool = False) -> None:
        """Have the thread at the microphone close it, for a rest or for good. on_ended
        carries on from there."""
        if self.reading and not self.pausing:
            self.pausing, self.idled = True, idle
            self.stop.set()
            self.said.setText("")
            self.refresh()

    def check_idle(self) -> None:
        """Once a second. Someone who has gone away doesn't leave the microphone open, and
        someone waiting for it to move on is told what to do."""
        if not (self.reading and self.listening) or self.pausing:
            return
        now = time.monotonic()
        if now - self.acted > self.IDLE_SECONDS:
            self.close_microphone(idle=True)
        elif (self.auto and self.current and not self.hinted
              and now - self.shown > reading.long_enough(self.current)):
            self.hinted = True
            self.said.setText("Still listening for the end of this sentence. If you have "
                              "read it, press the space bar to keep it and move on.")

    def on_ended(self, problem: str) -> None:
        """The thread at the microphone has closed it. Dictation comes back as it was: but
        asleep, if this is because the reader went away, so that it doesn't write down
        what it overhears."""
        if not self.reading:
            return
        # Whatever was on the screen, or read but not yet kept, comes round again.
        self.upcoming[0:0] = self.awaiting + ([self.current] if self.current else [])
        self.current, self.awaiting = "", []
        self.reading = self.listening = self.pausing = False
        put_to_sleep = self.engine.unhold(asleep=self.idled)
        if self.leaving or not self.upcoming:
            self.forget()  # the window was closed, or the text has been read to its end
        else:
            self.paused = True
            if self.idled:
                self.said.setText(
                    "Paused, because nothing was read for a minute."
                    + (f" Dictation is asleep: say \"{self.engine.settings.wake_words()[0]}\" "
                       "to use it." if put_to_sleep else ""))
            self.refresh()
        if problem:
            tell(self, problem)

    def forget(self) -> None:
        """The sitting is over. The next begins at the first sentence not yet read."""
        self.leaving = self.paused = False
        self.passed = []
        self.fill()
        self.refresh()

    def work(self, stop, cutter, epoch: int) -> None:
        import numpy as np
        try:
            recorder = audio.open_microphone(self.engine.settings.microphone)
        except Exception as e:
            self.bridge.ended.emit(f"The microphone could not be opened: {e}")
            return
        nbytes, loudest, peak, count, told = config.FRAME * 2, 0.0, 0, 0, False
        checking = threading.Event()  # a recogniser is hearing the sentence so far
        problem = ""
        try:
            while not stop.is_set():
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    problem = "The microphone stopped."
                    break
                frame = np.frombuffer(data, dtype=np.int16)
                while not self.orders.empty():
                    name, epoch, *more = self.orders.get_nowait()
                    if name == "accept":
                        if not cutter.accept(*more):  # each order ends one sentence's sound,
                            self.bridge.taken.emit(   # come what may: the window counts on it
                                reading.Take(problem=reading.NOTHING_HEARD))
                    else:
                        (cutter.next if name == "next" else cutter.again)()
                for take in cutter.feed(frame):
                    self.bridge.taken.emit(take)
                if self.auto and cutter.due and not checking.is_set():
                    checking.set()
                    threading.Thread(target=self.check, daemon=True,
                                     args=(epoch, *cutter.checkpoint(), checking)).start()
                if cutter.ready and not told:
                    told = True
                    self.bridge.ready.emit()
                loudest = max(loudest, cutter.loudness(frame))
                peak = max(peak, int(np.max(np.abs(frame.astype(np.int32)))))
                count += 1
                if count == 3:  # some sixteen times a second: the bar moves as the voice does
                    self.bridge.level.emit(meter_value(loudest, cutter.room)[0], peak / 32767,
                                           cutter.speaking)
                    loudest, peak, count = 0.0, 0, 0
        except Exception as e:  # whatever goes wrong, the window hears of it and lets go
            print(f"reading: stopped by an error: {type(e).__name__}: {e}", flush=True)
            problem = f"The reading had to stop: {e}"
        finally:
            recorder.close()
        self.bridge.ended.emit(problem)

    def check(self, epoch: int, mark: int, sound, checking) -> None:
        """Have the recogniser in use hear the sentence so far. On a thread of its own:
        the microphone is not kept waiting."""
        import numpy as np
        try:
            heard = self.engine.hear_reading(sound.astype(np.float32) / 32768.0)
        except Exception as e:
            print(f"reading: the recogniser could not check a sentence: {e}", flush=True)
            heard = None
        checking.clear()
        self.bridge.heard.emit(epoch, mark, heard)

    # ---- reading ---------------------------------------------------------------------------
    def on_heard(self, epoch: int, mark: int, heard) -> None:
        """A recogniser has heard the sentence so far, at a pause. Is it done?"""
        if epoch != self.epoch or not (self.reading and self.listening and self.current):
            return  # that was of a sentence since ended or started again
        if heard is None:
            self.said.setText("The recogniser couldn't check that. Press the space bar when "
                              "you have read the sentence.")
            return
        outcome = reading.verdict(self.current, heard)
        if outcome == reading.DONE:
            self.acted = time.monotonic()
            self.awaiting.append(self.current)
            self.order("accept", mark)
            self.advance()
            self.refresh()
        elif outcome == reading.ASTRAY:
            self.order("again")
            self.said.setText("That didn't sound like this sentence, so it wasn't kept. Read "
                              "it again, or press the space bar to pass over it.")

    def on_ready(self) -> None:
        if not self.reading or self.pausing:
            return
        self.listening = True
        self.acted = time.monotonic()
        self.fresh()
        self.advance()
        if not self.current:
            self.close_microphone()  # nothing was left to read
        self.refresh()

    def advance(self) -> None:
        self.current = self.upcoming.pop(0) if self.upcoming else ""

    def on_next(self) -> None:
        if not self.reading:
            self.on_go()  # the space bar starts a sitting, and ends a rest
            return
        if not (self.listening and self.current) or self.pausing:
            return
        self.acted = time.monotonic()
        self.awaiting.append(self.current)
        self.order("next")
        self.advance()  # with none left, the reading ends when the last one's sound is in
        self.refresh()

    def on_again(self) -> None:
        if self.reading and self.listening and self.current:
            self.acted = time.monotonic()
            self.order("again")
            self.said.setText("Read it again from the start.")

    def on_back(self) -> None:
        if not (self.reading and self.listening and self.passed) or self.awaiting:
            return
        self.acted = time.monotonic()
        text, was_kept = self.passed.pop()
        if was_kept:
            self.kept.take_back()
            self.count, self.seconds = self.kept.totals()
        if self.current:
            self.upcoming.insert(0, self.current)
        self.current = text
        self.order("again")
        self.said.setText("Read this one again.")
        self.refresh()

    def on_taken(self, take) -> None:
        if not self.awaiting:
            return
        text = self.awaiting.pop(0)
        if take.samples is None:
            self.passed.append((text, False))
            self.said.setText(
                "The last one went on too long to be one sentence, so it wasn't kept."
                if take.problem == reading.TOO_LONG else
                "The last one was begun before the microphone was listening, so it wasn't "
                "kept. It will come round again." if take.problem == reading.MISSED_START else
                "Nothing was heard for the last one, so it wasn't kept.")
        else:
            try:
                self.kept.keep(take.samples, text)
            except OSError as e:
                self.close_microphone()
                tell(self, f"The recording could not be kept: {e.strerror or e}")
                return
            self.passed.append((text, True))
            self.count += 1
            self.seconds += take.seconds
            self.said.setText(f"Kept the last one: {take.seconds:.1f} s.")
        if not self.current and not self.awaiting:
            self.close_microphone()  # that was the last sentence there is
        self.refresh()


class TrainWindow(QWidget):
    """Retrain a recogniser to one voice, from sentences read aloud: which folder of them,
    which model to start from, and what the result is to be called. See training.py.

    It takes an hour or more, so the work is not tied to this window. It runs by itself,
    at low priority, and goes on if the window or the app is closed; opened again, the
    window shows how far it has come. It can be stopped, and carried on later from the
    last pass it finished."""

    def __init__(self, engine: Engine, refill=lambda: None):
        super().__init__()
        self.engine = engine
        self.refill = refill          # the list of models in Settings gains the new one
        self.setWindowTitle("Train on my voice")
        self.job = training.latest()  # a run that is going, or the last there was
        self.install = training.Install()  # the fetching of the training tools
        self.folder = reading.FOLDER
        self.counted = (0, 0.0)       # sentences and seconds of sound in the folder
        self.was = ""                 # the state last shown, to notice a run finishing
        self.asked_to_stop = False
        layout = QVBoxLayout(self)
        note = QLabel(
            "Retrains a speech model on the sentences you have read aloud, so that it knows "
            "your voice. It takes half an hour or more and a good deal of memory, and it runs by "
            "itself: you can close this window, and dictation goes on working, a little "
            "slower. The new model then appears among the speech models under the name you "
            "give it. One sentence in six is kept out of the training, to test the result on.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QGridLayout()
        form.addWidget(QLabel("Sentences:"), 0, 0)
        self.where = QLineEdit()
        self.where.setReadOnly(True)
        form.addWidget(self.where, 0, 1)
        self.choose = QPushButton("Choose a folder\u2026")
        self.choose.clicked.connect(self.on_choose)
        form.addWidget(self.choose, 0, 2)
        self.there = QLabel()
        form.addWidget(self.there, 1, 1, 1, 2)
        form.addWidget(QLabel("Start from:"), 2, 0)
        self.bases = QComboBox()
        for base in training.BASES:
            self.bases.addItem(base.label, base.key)
        form.addWidget(self.bases, 2, 1, 1, 2)
        form.addWidget(QLabel("Name:"), 3, 0)
        self.name = QLineEdit("My voice")
        self.name.setMaxLength(40)
        self.name.textChanged.connect(lambda _: self.refresh())
        form.addWidget(self.name, 3, 1, 1, 2)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        layout.addWidget(self.bar)
        self.headline = QLabel()
        self.headline.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.headline)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        # Room for four lines always, so the window doesn't jump as the words change.
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail.setFixedHeight(4 * self.detail.fontMetrics().lineSpacing() + 2)
        layout.addWidget(self.detail)
        layout.addStretch()
        row = QHBoxLayout()
        self.go = QPushButton()  # starts, stops and carries on
        self.go.clicked.connect(self.on_go)
        self.use = QPushButton("Use it for dictation")
        self.use.clicked.connect(self.on_use)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(self.go)
        row.addWidget(self.use)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        said = self.job.status() if self.job else {}
        if said:  # the form says what the last run was of, so that it is that run's news shown
            self.folder = said.get("data") or self.folder
            self.name.setText(said.get("name") or self.name.text())
            self.bases.setCurrentIndex(max(0, self.bases.findData(said.get("base"))))
            self.was = said.get("state", "")
        self.count()
        self.refresh()
        dress(self, (640, 350))

    def showEvent(self, event) -> None:
        self.count()
        self.refresh()
        self.timer.start(1000)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.timer.stop()  # the run goes on by itself
        super().hideEvent(event)

    def count(self) -> None:
        self.counted = training.found(self.folder)

    def base(self) -> training.Base:
        return training.BY_KEY[self.bases.currentData()]

    def current(self) -> training.Job:
        """The run the window is about: one that is going, whatever the form says, or
        else the one of the name in the form."""
        if self.job is not None and self.job.running():
            return self.job
        return training.job_for(self.base(), self.name.text().strip() or "-")

    def not_ready(self) -> str:
        """Why a run can't be started as things are, or ""."""
        if self.counted[0] < training.LEAST:
            return (f"At least {training.LEAST} sentences are wanted. Read some with \"Read "
                    "aloud for training\", or choose the folder they are in.")
        return training.name_problem(self.name.text())

    def refresh_tools(self) -> bool:
        """What the window says while the training tools are not there: that they can be
        fetched, are being fetched, or could not be. False once they are there."""
        if training.python() and self.install.state() != "installing":
            self.bar.setRange(0, 1000)
            return False
        fetching = self.install.state()
        for part in (self.choose, self.bases, self.name):
            part.setEnabled(False)
        self.where.setText(self.folder)
        self.there.setText("")
        self.use.setVisible(False)
        self.bar.setRange(0, 0 if fetching == "installing" else 1000)  # busy, while it is
        self.bar.setValue(0)
        self.go.setEnabled(fetching != "installing")
        if fetching == "installing":
            self.headline.setText("Installing the training tools\u2026")
            self.detail.setText((self.install.last_line() or "Starting.")
                                + "\nIt goes on if this window is closed.")
            self.go.setText("Installing\u2026")
        elif fetching == "failed":
            self.headline.setText("The training tools could not be installed.")
            self.detail.setText(f"{self.install.last_line()}\nMore is in {self.install.log}")
            self.go.setText("Try the install again")
        else:
            self.headline.setText("The training tools are not installed on this computer.")
            self.detail.setText(
                "They are a Python of their own with PyTorch and NeMo, about "
                f"{training.TOOLS_GB:g} GB, kept in a folder beside the app: removing that "
                "folder removes them. A run then wants about "
                f"{training.MEMORY_GB} GB of free memory.")
            self.go.setText(f"Install the training tools  ({training.TOOLS_GB:g} GB)")
        return True

    def on_install(self) -> None:
        problem = training.room_problem()
        if problem:
            tell(self, problem)
        elif ask(self, f"This fetches about {training.TOOLS_GB:g} GB from the internet and may "
                       "take a quarter of an hour or more. It can go on while you do other "
                       "things. Install the training tools?"):
            try:
                self.install.start()
            except OSError as e:
                tell(self, f"The install could not be started: {e}")
            self.refresh()

    def refresh(self) -> None:
        if self.refresh_tools() or self.refresh_fetching():
            return
        job = self.current()
        said = job.status()
        state = said.get("state", "")
        active = state in training.ACTIVE
        if not active:
            self.asked_to_stop = False
        for part in (self.choose, self.bases, self.name):
            part.setEnabled(not active)
        self.where.setText(self.folder)
        count, seconds = self.counted
        self.there.setText(f"{count} sentence{'s' if count != 1 else ''}, "
                           f"{reading.time_text(seconds)} of sound" if count else
                           "No sentences read aloud were found there.")
        headline, detail = training.describe(said)
        problem = "" if active else self.not_ready()
        if self.asked_to_stop:
            headline, detail = "Stopping\u2026", "It stops at the next few sentences, and keeps the passes it has finished."
        elif problem and state != "done":
            headline, detail = (headline if state else ""), problem
        elif not state:
            detail = ("Ready. Half an hour of reading takes about an hour to train on, on a "
                      "quick computer.")
        if not active and not problem and not models.kind(config.MODEL_DIR, training.CUTTER):
            # Said before a run, not after it: without this model a run does little good.
            detail = ("Parakeet v2 is not installed. It is what finds where each word of a "
                      "sentence is, so that single words can be learned from too, and it is "
                      "those that teach a model your voice. \"Install or remove models\" has it.")
        self.headline.setText(headline)
        self.detail.setText(detail)
        self.bar.setValue(round(1000 * training.fraction(said)))
        carry_on = state in ("stopped", "failed") and said.get("data") == self.folder
        self.go.setText("Stop" if active else "Carry on" if carry_on else "Start training")
        self.go.setEnabled(not self.asked_to_stop and (active or not problem))
        made = said.get("folder", "") if state == "done" else ""
        in_use = made == (self.engine.settings.model or config.AWAKE_MODEL)
        self.use.setVisible(bool(made) and models.kind(config.MODEL_DIR, made) != "")
        self.use.setEnabled(not in_use)
        self.use.setText("In use for dictation" if in_use else "Use it for dictation")
        if state == "done" and self.was in training.ACTIVE:
            self.refill()
        self.was = state

    def on_choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "The folder of sentences read aloud",
                                                  self.folder)
        if folder:
            self.folder = folder
            self.count()
            self.refresh()

    def on_go(self) -> None:
        if not training.python() or self.install.state() == "installing":
            if self.install.state() != "installing":
                self.on_install()
            return
        job = self.current()
        said = job.status()
        state = said.get("state", "")
        if state in training.ACTIVE:
            job.stop()
            self.asked_to_stop = True
            self.refresh()
            return
        problem = self.not_ready() or training.memory_problem()
        if problem:
            tell(self, problem)
            return
        base, name = self.base(), self.name.text().strip()
        carry_on = state in ("stopped", "failed") and said.get("data") == self.folder
        made = training.model_folder(base, name)
        if not carry_on and made == (self.engine.settings.model or config.AWAKE_MODEL):
            tell(self, f"\u201c{name}\u201d is the model in use for dictation, and a new one "
                       "can't be put in its place while it is. Give the new model another "
                       "name, or choose another model for dictation first.")
            return
        if not carry_on and models.kind(config.MODEL_DIR, made) \
                and not ask(self, f"There is already a model called \u201c{name}\u201d. Train "
                                  "it afresh, and put the new one in its place?"):
            return
        cutter = models.BY_NAME.get(training.CUTTER)
        if (not models.kind(config.MODEL_DIR, training.CUTTER) and cutter is not None
                and ask(self, "Parakeet v2 is not installed. It is what finds where each word "
                              "of a sentence is, so that single words can be learned from "
                              "too: and it is those that teach a model your voice. Fetch it "
                              f"first ({models.size_text(cutter.megabytes * 1e6)})? "
                              "Without it, only the sentences are learned from.")):
            self.fetch_cutter(cutter, carry_on)
            return
        self.start_run(carry_on)

    def start_run(self, carry_on: bool) -> None:
        base, name = self.base(), self.name.text().strip()
        job = training.job_for(base, name)
        try:
            job.start(self.folder, base, name, resume=carry_on)
        except OSError as e:
            tell(self, f"The training could not be started: {e}")
            return
        self.job, self.was = job, "starting"
        self.refresh()

    def fetch_cutter(self, known, carry_on: bool) -> None:
        """Fetch the model that finds where the words are, then start the run. On a thread
        of its own: the window goes on showing how far it has come."""
        self.fetching = {"done": 0, "total": 0, "error": "", "over": False, "carry_on": carry_on}

        def work():
            def progress(done, total):
                self.fetching.update(done=done, total=total)
            try:
                models.Download(known, config.MODEL_DIR, progress=progress).run()
            except Exception as e:
                self.fetching["error"] = str(e) or type(e).__name__
            self.fetching["over"] = True

        threading.Thread(target=work, daemon=True).start()
        self.refresh()

    def refresh_fetching(self) -> bool:
        """What the window says while Parakeet v2 is being fetched. False when it isn't."""
        fetching = getattr(self, "fetching", None)
        if fetching is None:
            return False
        if fetching["over"]:
            self.fetching = None
            self.refill()
            if fetching["error"]:
                tell(self, f"Parakeet v2 could not be fetched: {fetching['error']}")
                return False
            self.start_run(fetching["carry_on"])
            return True
        for part in (self.choose, self.bases, self.name, self.go):
            part.setEnabled(False)
        self.headline.setText("Fetching Parakeet v2, which finds where each word is\u2026")
        total = fetching["total"]
        self.detail.setText(f"{models.size_text(fetching['done'])} of {models.size_text(total)}"
                            if total else "Starting.")
        self.bar.setRange(0, 1000)
        self.bar.setValue(round(1000 * fetching["done"] / total) if total else 0)
        return True

    def on_use(self) -> None:
        made = self.current().status().get("folder", "")
        if made and models.kind(config.MODEL_DIR, made):
            self.engine.set_model(made)
            self.refill()
            self.refresh()


class AboutWindow(QWidget):
    """What this is, which version, and what it is using."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        picture = QLabel()
        picture.setPixmap(make_pixmap(State.AWAKE, pixels=72, meter=False))
        top.addWidget(picture)
        title = QLabel(f"<div style='font-size:18pt; font-weight:bold'>{APP_NAME}</div>"
                       f"<div>Version {__version__}</div>")
        top.addWidget(title, 1)
        layout.addLayout(top)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.body)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        dress(self, minimise=False)

    def showEvent(self, event) -> None:
        self.body.setText(self.text())
        # A wrapped label doesn't tell the window how tall it needs to be, so work it
        # out for the width in use and size the window to fit.
        width = 520
        self.body.setMinimumSize(width, self.body.heightForWidth(width) + 8)
        self.adjustSize()
        super().showEvent(event)

    def text(self) -> str:
        model = self.engine.settings.model or config.AWAKE_MODEL
        target = self.engine.status.target or "nothing in front right now"
        chosen = self.engine.settings.remote
        if chosen["on"] and chosen["address"]:
            where = ("What you say while awake is sent to the computer you chose in Settings "
                     f"({chosen['address']}) to be recognised, and nowhere else.")
        else:
            where = "Everything runs on this computer: nothing you say is sent anywhere."
        return (
            "<p>Voice dictation for Linux. Say <b>wake up</b> and talk; say <b>go to sleep</b> "
            "to stop. Your words are fitted to the text around the cursor, and commands "
            "such as <b>scratch that</b>, <b>select</b> and <b>spell that</b> edit by voice.</p>"
            "<p>Works in LibreOffice Writer, Thunderbird messages, Kate, KWrite and "
            "Visual Studio Code. "
            f"{where}</p>"
            f"<p><b>Speech model:</b> {model}<br>"
            f"<b>Typing into:</b> {target}<br>"
            f"<b>Installed in:</b> {config.INSTALL_DIR}<br>"
            f"<b>Settings file:</b> {self.engine.settings.path or 'not saved'}</p>"
            "<p>By Jonti Olds. Speech recognition is OpenAI's Whisper, run by "
            "faster-whisper and CTranslate2. The window and tray icon use Qt.</p>"
            f"<p>Free software under the GNU General Public License, version 3 or later. "
            f"It comes with no warranty.<br>{HOMEPAGE}</p>"
        )


class SpellWindow(QWidget):
    """Shows the word being spelled aloud. It asks not to take the keyboard, though some
    desktops give it anyway; the engine waits for the document to be in front again
    before typing the word."""

    HELP = ("Say one letter at a time, or a few together. \"Capital J\" for a capital.\n"
            "\"Space\", \"hyphen\", \"double L\", \"backspace\", \"start again\".\n"
            "Say \"done\" to put the word in, or \"cancel\".")

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Dictation spelling")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Spelling"))
        self.word = QLabel()
        self.word.setMinimumHeight(54)
        self.word.setStyleSheet(
            "font: bold 26pt monospace; padding: 6px 10px; border: 1px solid palette(mid);"
            "border-radius: 4px; background: palette(base); color: palette(text);"
        )
        layout.addWidget(self.word)
        self.heard = QLabel()
        layout.addWidget(self.heard)
        help_text = QLabel(self.HELP)
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        buttons = QHBoxLayout()
        insert = QPushButton("Done")
        insert.clicked.connect(lambda: engine.run_soon(lambda: engine.finish_spelling(True)))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: engine.run_soon(lambda: engine.finish_spelling(False)))
        buttons.addStretch()
        buttons.addWidget(insert)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dress(self, minimise=False)

    def refresh(self) -> None:
        status = self.engine.status
        if status.spelling:
            # A visible mark for each space, and a cursor at the end.
            self.word.setText(status.spelled.replace(" ", "\u2423") + "\u258f")
            self.heard.setText(f"Heard: {status.last_heard}" if status.last_heard else "")
            if not self.isVisible():
                self.show()
        elif self.isVisible():
            self.hide()

    def closeEvent(self, event) -> None:  # closing the box cancels the spelling
        if self.engine.status.spelling:
            self.engine.run_soon(lambda: self.engine.finish_spelling(False))
        super().closeEvent(event)


def install_pending_extension() -> str:
    """Install a staged Writer extension update. LibreOffice must be closed."""
    pending = config.PENDING_EXTENSION
    subprocess.run(["unopkg", "remove", "io.github.jontio.linuxspeaking"],
                   capture_output=True, timeout=120)
    done = subprocess.run(["unopkg", "add", pending], capture_output=True, text=True, timeout=120)
    if done.returncode == 0:
        os.remove(pending)
        return "Writer extension updated"
    return "Writer extension update failed: " + (done.stderr or done.stdout).strip()[-200:]


class Tray:
    def __init__(self, app: QApplication):
        self.app = app
        self.bridge = Bridge()
        self.icons = {
            (state, level): make_icon(state, level)
            for state in State for level in range(config.LEVEL_STEPS + 1)
        }
        self.loud_icons = {state: make_icon(state, loud=True) for state in State}
        self.loading_icon = make_loading_icon()
        self.tray = QSystemTrayIcon(self.loading_icon)
        self.menu = QMenu()
        self.toggle = QAction("Turn on")
        self.toggle.triggered.connect(self.on_toggle)
        self.wake = QAction("Wake up")
        self.wake.triggered.connect(self.on_wake)
        self.quit = QAction("Quit")
        self.quit.triggered.connect(self.on_quit)
        self.show_meter = QAction("Show level meter")
        self.show_meter.triggered.connect(self.on_show_meter)
        self.show_settings = QAction("Settings\u2026")
        self.show_settings.triggered.connect(self.on_show_settings)
        self.show_about = QAction("About")
        self.show_about.triggered.connect(self.on_show_about)
        for action in (self.toggle, self.wake, self.show_meter, self.show_settings,
                       self.show_about):
            self.menu.addAction(action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_click)

        first_time = not os.path.exists(config.STATE_FILE)  # the engine writes it once on
        self.engine = Engine(on_change=self.bridge.changed.emit)
        self.engine.on_event = self.bridge.event.emit
        self.engine.on_level = self.bridge.level.emit
        self.numbers = Numbers()
        self.notice = Notice() if config.WINDOWS else None
        self.bridge.numbers.connect(self.numbers.show)
        if self.engine.targets.office is not None:
            # Called from the thread that talks to Word; the signal brings it to this one.
            self.engine.targets.office.show_numbers = self.bridge.numbers.emit
        self.meter = MeterWindow(self.engine)
        self.settings_window = SettingsWindow(self.engine)
        self.settings_window.on_setting = self.on_setting
        self.style_menu()
        self.hotkey = None
        if config.WINDOWS:
            from .hotkey import Hotkey
            self.bridge.hotkey.connect(self.switch)
            self.hotkey = Hotkey(self.bridge.hotkey.emit)  # pressed on its thread, acted on here
            self.on_setting("numpad_plus")
        self.spell_window = SpellWindow(self.engine)
        self.about_window = AboutWindow(self.engine)
        self.updating = False
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.check_update)
        self.update_timer.timeout.connect(self.check_training)
        self.update_timer.start(5000)
        self.training_was = ""  # the state of the last training run, as last looked at
        self.show_timer = QTimer()
        self.show_timer.timeout.connect(self.check_show_request)
        self.show_timer.start(1000)
        self.bridge.changed.connect(self.refresh)
        self.bridge.level.connect(self.refresh_icon)
        self.bridge.event.connect(self.notify)
        self.refresh()
        self.tray.show()
        if first_time:  # something to see the first time: after that, the icon
            self.on_show_settings()
        if saved_on():
            self.engine.turn_on()

    def refresh(self) -> None:
        status = self.engine.status
        self.refresh_icon()
        self.tray.setToolTip(status.tooltip())
        self.toggle.setText(status.menu_toggle_label())
        self.wake.setText("Go to sleep" if status.awake else "Wake up")
        self.spell_window.refresh()

    def refresh_icon(self) -> None:
        status = self.engine.status
        level = 0 if status.state is State.OFF else status.level
        if not status.ready:
            self.tray.setIcon(self.loading_icon)
        elif status.loud and status.state is not State.OFF:
            self.tray.setIcon(self.loud_icons[status.state])
        else:
            self.tray.setIcon(self.icons[status.state, level])

    def on_show_settings(self) -> None:
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def on_show_about(self) -> None:
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()

    def check_show_request(self) -> None:
        """Show Settings when the program was started again while it was running: the
        application menu's entry was clicked."""
        if os.path.exists(config.SHOW_FILE):
            try:
                os.remove(config.SHOW_FILE)
            except OSError:
                return
            self.on_show_settings()

    def check_training(self) -> None:
        """Say when a training run has ended, whether or not its window is open: it
        takes an hour or more, and nobody watches it."""
        job = training.latest()
        said = job.status() if job else {}
        state = said.get("state", "")
        if self.training_was in training.ACTIVE and state in training.ENDED:
            headline, detail = training.describe(said)
            self.say("Training on your voice", f"{headline} {detail}".strip(),
                     self.icons[State.ASLEEP, 0], 10000)
            self.settings_window.refill_models()
        self.training_was = state

    def check_update(self) -> None:
        """Install a waiting extension update once LibreOffice is closed."""
        waiting = os.path.exists(config.PENDING_EXTENSION)
        if waiting != self.engine.status.update_waiting:
            self.engine.status.update_waiting = waiting
            self.refresh()
            self.settings_window.banner.setVisible(waiting)
            if waiting:
                self.say(
                    "Dictation update waiting",
                    "Save your work, close LibreOffice for a few seconds, then reopen it. "
                    "Some commands and settings won't work until then.",
                    self.loading_icon, 8000,
                )
        if not waiting or self.updating:
            return
        if subprocess.run(["pgrep", "-x", "soffice.bin"], capture_output=True).returncode == 0:
            return
        self.updating = True

        def work():
            try:
                print(install_pending_extension(), flush=True)
            except Exception as e:
                print(f"Writer extension update failed: {e}", flush=True)
            self.updating = False

        threading.Thread(target=work, daemon=True).start()

    def on_show_meter(self) -> None:
        self.meter.showNormal()  # opens the microphone, and holds dictation off: see MeterWindow
        self.meter.raise_()
        self.meter.activateWindow()

    def make_way(self) -> None:
        """Dictation was asked for by hand while the level meter had it held off: the
        meter closes, which gives dictation back as it was, and the asking is done on that."""
        if self.meter.listening:
            self.meter.close()

    def say(self, title: str, message: str, icon: QIcon, milliseconds: int) -> None:
        """A passing notice: the desktop's own, or on Windows one of ours (see Notice)."""
        if self.notice is not None:
            self.notice.say(title, message, icon, milliseconds)
        else:
            self.tray.showMessage(title, message, icon, milliseconds)

    def notify(self, name: str) -> None:
        if name == "ready" and self.engine.status.state is not State.OFF:
            self.say("Dictation", f"Ready. Say \"{self.engine.settings.wake_words()[0]}\" to start.",
                     self.icons[State.ASLEEP, 0], 2500)
        if not config.NOTIFY:
            return
        if name == "wake":
            self.say("Dictation", "Awake", self.icons[State.AWAKE, 0], 1500)
        elif name == "sleep":
            self.say("Dictation", "Asleep", self.icons[State.ASLEEP, 0], 1500)
        elif name == "off":
            self.say("Dictation", "Off", self.icons[State.OFF, 0], 1500)

    def on_toggle(self) -> None:
        if self.engine.status.state is State.OFF:
            self.make_way()
            self.engine.turn_on()  # nothing to do, if that brought it back on
        else:
            self.engine.turn_off()

    def on_wake(self) -> None:
        if self.engine.status.awake:
            self.engine.sleep()
        else:
            self.make_way()
            self.engine.wake()

    def on_click(self, reason) -> None:
        """A click switches off, or from off straight to awake: someone who clicks the icon
        wants to talk now, not to say "wake up" first."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.switch()

    def switch(self) -> None:
        """Off, or from off straight to awake. For a click on the icon and the hotkey."""
        if self.engine.status.state is State.OFF:
            self.make_way()
            self.engine.wake()
        else:
            self.engine.turn_off()

    def on_setting(self, key: str) -> None:
        if key == "look":
            QTimer.singleShot(0, self.restyle)  # not from inside the window that is to go
        if key != "numpad_plus" or self.hotkey is None:
            return
        if not self.engine.settings.enabled(key):
            self.hotkey.stop()
        elif not self.hotkey.start():
            print("the number pad + key could not be taken: another program has it",
                  flush=True)

    def restyle(self) -> None:
        """The look was changed in Settings: make every window again in the new one, each
        where it stood if it was open, and dress the menu to match."""
        old = self.settings_window
        for child in (old.models_window, old.voice_window, old.read_window, old.train_window):
            if child is not None:
                child.close()  # a reading or a test under way is ended properly
        self.settings_window = SettingsWindow(self.engine)
        self.settings_window.on_setting = self.on_setting
        self.settings_window.banner.setVisible(old.banner.isVisible())
        self.style_menu()
        if old.isVisible():
            self.settings_window.move(old.pos())
            self.settings_window.show()
            self.settings_window.activateWindow()
        old.close()
        old.deleteLater()
        # The new one is shown before the old one is closed: an open level meter holds
        # dictation off, and this way it is not let go and taken again in between.
        for name, make in (("meter", MeterWindow), ("about_window", AboutWindow),
                           ("spell_window", SpellWindow)):
            was = getattr(self, name)
            shown, place = was.isVisible() and not was.isMinimized(), was.pos()
            now = make(self.engine)
            setattr(self, name, now)
            if shown and name != "spell_window":  # the spelling box shows itself: see refresh()
                now.move(place)
                now.show()
            was.close()
            was.deleteLater()
        self.refresh()

    def style_menu(self) -> None:
        self.menu.setStyleSheet(looks.menu(self.engine.settings.look) if config.WINDOWS else "")

    def on_quit(self) -> None:
        self.meter.let_go(restore=False)  # its microphone is closed; dictation isn't started for it
        self.engine.quit()
        self.app.quit()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--write-icon":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no desktop needed for this
        app = QApplication(sys.argv[:1])
        write_app_icon(sys.argv[2])
        return 0
    if config.WINDOWS:
        import ctypes
        # Only one may run: two would both type what is said. A second start asks the
        # first to show its Settings window, then leaves.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, "Local\\LinuxSpeaking")
        if ctypes.get_last_error() == 183:  # it already exists
            write_text(config.SHOW_FILE, "")
            return 0
        if sys.stdout is None:  # started without a console: keep a log file instead
            os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
            fresh = (not os.path.exists(config.LOG_FILE)
                     or os.path.getsize(config.LOG_FILE) > 1_000_000)
            sys.stdout = sys.stderr = open(
                config.LOG_FILE, "w" if fresh else "a", buffering=1, encoding="utf-8")
        # Its own taskbar identity, so its windows show its icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("jontio.LinuxSpeaking")
    app = QApplication(sys.argv)
    app.setApplicationName("Linux Speaking")
    app.setApplicationDisplayName(APP_NAME)
    # LS_WINDOW_ICON=0 leaves the windows with the desktop's default icon, for comparison.
    if os.environ.get("LS_WINDOW_ICON", "1") == "1":
        app.setWindowIcon(make_icon(State.AWAKE, pixels=128, meter=False))
        if config.WINDOWS:
            # The taskbar wants the icon as a file. The installer wrote one; make it if not.
            icon_file = os.path.join(config.INSTALL_DIR, "linux-speaking.ico")
            try:
                if not os.path.exists(icon_file):
                    write_app_icon(icon_file)
                identity = OwnIdentity(icon_file)  # kept alive by the name
                app.installEventFilter(identity)
            except Exception as e:
                print(f"the taskbar will show Python's icon: {e}", flush=True)
    app.setQuitOnLastWindowClosed(False)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    tray = Tray(app)  # keep a reference until the app exits

    def stop(*_):
        # Stop directly: Qt may not hand control back to Python for app.quit().
        tray.engine.quit()
        sys.stdout.flush()
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    # For troubleshooting: "systemctl --user kill -s USR1 linux-speaking" writes to the log
    # what each program's link answers when asked whether it is in front.
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, lambda *_: tray.engine.run_soon(
            lambda: print("in front? " + tray.engine.targets.describe(), flush=True)))
    code = app.exec()
    tray.engine.quit()
    tray.tray.hide()
    # Leave at once: unwinding Qt and Whisper's threads at exit has crashed.
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
