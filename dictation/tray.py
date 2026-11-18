"""The tray icon. Run with: python -m dictation.tray"""
from __future__ import annotations

import collections
import os
import queue
import signal
import socket
import subprocess
import threading
import sys
import time

from PyQt6 import sip
from PyQt6.QtCore import (
    QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap,
    QPolygonF, QShortcut, QTextCursor,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSystemTrayIcon, QTableWidget,
    QTableWidgetItem,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QToolTip,
)

from . import (APP_NAME, HOMEPAGE, __version__, actions, audio, autostart, config, control, hotkey,
               looks, models, reading, settings as settings_module, speech, training, voicetest)
from .engine import Engine, brief, meter_value, saved_on
from .formatting import LINE, PARAGRAPH
from .reading_text import SENTENCES
from .settings import (ITEMS, WINDOWS_ONLY, available_models, help_for, model_label,
                       without_effect)
from .status import State

# The model to suggest to somebody new: settings.py says which, once it knows.
RECOMMENDED = getattr(settings_module, "RECOMMENDED", "parakeet-unified-en-0.6b")

LOADING_COLOUR = "#8e5bd0"
FAILED_COLOUR = "#5a5a5a"
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


def make_failed_icon(pixels: int = 64) -> QIcon:
    """An exclamation mark on a dark grey disc: no speech model could be loaded, so
    nothing can be recognised until that is put right. A shape and a colour of its own,
    like none of the others."""
    size = 64
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(pixels / size, pixels / size)
    p.setPen(QPen(QColor("#d0d0d0"), 3))  # a pale rim, so that it shows on a dark panel too
    p.setBrush(QColor(FAILED_COLOUR))
    p.drawEllipse(QRectF(3.5, 3.5, size - 7, size - 7))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#ffd54a"))
    p.drawRoundedRect(QRectF(27, 11, 10, 30), 5, 5)
    p.drawEllipse(QPointF(32, 50), 6, 6)
    p.end()
    return QIcon(pixmap)


TOO_LOUD = "#e53935"  # the meter's colour when the microphone is distorting


def make_icon(state: State, level: int = 0, pixels: int = 64, meter: bool = True,
              loud: bool = False, commands: bool = False) -> QIcon:
    """A microphone on a coloured disc, with a slash when off, a "z" when asleep, a "C"
    when only commands are acted on, and a level bar when on. Each state has a shape of its own as well
    as a colour, for anyone who can't tell the colours apart."""
    return QIcon(make_pixmap(state, level, pixels, meter, loud, commands))


def make_pixmap(state: State, level: int = 0, pixels: int = 64, meter: bool = True,
                loud: bool = False, commands: bool = False) -> QPixmap:
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
    if state is State.ASLEEP and meter:
        # Asleep: a "z" at the top right, dark-edged so that it stands clear of the disc.
        # Without it, asleep and awake differed only in being orange or green.
        shape = [QPointF(41, 5), QPointF(59, 5), QPointF(41, 25), QPointF(59, 25)]
        for colour, width in ((QColor(0, 0, 0, 215), 9.5), (white, 5.0)):
            stroke = QPen(colour, width)
            stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QPolygonF(shape))
    elif commands and state not in (State.OFF, State.ASLEEP) and meter:
        # Commands only (a choice in Settings): a "C" in the same corner, drawn the same
        # way. Nothing is typed while it shows, which nobody should have to find out by
        # dictating.
        for colour, width in ((QColor(0, 0, 0, 215), 9.5), (white, 5.0)):
            stroke = QPen(colour, width)
            stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(stroke)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(41, 4, 19, 21), 50 * 16, 260 * 16)
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
    notice = pyqtSignal(str, str)  # something the engine wants said: the words, and
    #                                "info" or "problem"
    numbers = pyqtSignal(list)  # numbered matches to show over another program's window
    hotkey = pyqtSignal()       # the key that switches dictation off and on was pressed
    extension = pyqtSignal(str)  # the Writer extension was put in; what went wrong, or ""


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
        size = 10 * looks.text_scale()  # bigger, where Windows has been asked for big text
        card.setStyleSheet(
            "#card { background: #2b2b2b; border: 1px solid #555; border-radius: 8px; }"
            f"QLabel {{ color: #f2f2f2; font: {size:.1f}pt 'Segoe UI', sans-serif; }}"
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
            size = 9 * looks.text_scale()  # bigger, where Windows has been asked for big text
            label.setStyleSheet(
                "background: #ffe066; color: #1b1b1b; border: 1px solid #8a6d00;"
                f"border-radius: 3px; padding: 0px 3px; font: bold {size:.1f}pt 'Segoe UI', "
                "sans-serif;")
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


def tip(*parts: str) -> str:
    """What is shown when the mouse rests on something: the parts that aren't empty, each
    a paragraph, written so that it wraps to a width that can be read."""
    import html
    said = [html.escape(part) for part in parts if part]
    return "<qt>" + "".join(f"<p style='white-space: normal'>{part}</p>" for part in said) + "</qt>" \
        if said else ""


def ask(window, text: str, careful: bool = False) -> bool:
    """Ask a yes or no question, in a window of the chosen look. `careful` is for a "Yes"
    that deletes something: Enter then answers "No", so that a slip of the hand on the
    keyboard removes nothing."""
    if looks.known(look_of(window)):
        return looks.message(window, look_of(window), window.windowTitle(), text, "question",
                             ("Yes", "No"), default="No" if careful else "Yes") == "Yes"
    yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
    return QMessageBox.question(window, window.windowTitle(), text, yes | no,
                                no if careful else yes) == yes


def points(window, times: float = 1.0) -> float:
    """A size for text, in points: `times` the size of the window's ordinary text. Large
    and small text is sized this way, never at a fixed number of points, so that it
    follows the size the person has set for the system, or the chosen look's."""
    base = looks.points(look_of(window))
    if not base:
        font = QApplication.font()
        base = font.pointSizeF()
        if base <= 0:  # a font given in pixels
            base = font.pixelSize() * 72.0 / 96.0 if font.pixelSize() > 0 else 10.0
    return round(base * times, 1)


def grown(window) -> float:
    """How many times its usual size a window's text is: 1.0, or more where the person
    has set the system, or Windows for the chosen look, to larger text."""
    if looks.known(look_of(window)):
        return max(1.0, looks.text_scale())
    return max(1.0, points(window) / 10.0)


def roomy(window, width: int, height: int) -> tuple:
    """A size for a window, given as it suits text of the usual size: made larger in step
    with larger text, so that what is in it still fits, and never larger than the screen."""
    scale = grown(window)
    width, height = round(width * scale), round(height * scale)
    screen = QApplication.primaryScreen()
    if screen is not None:
        room = screen.availableGeometry()
        width, height = min(width, room.width() - 24), min(height, room.height() - 72)
    return width, height


def explain(widget, *parts: str) -> None:
    """Say what something is for: as its tip, shown when the mouse rests on it and, in
    Settings, when it is tabbed to (see TipsByKeyboard), and to a screen reader as its
    description. The parts that aren't empty, each a paragraph."""
    said = [part for part in parts if part]
    widget.setToolTip(tip(*said))
    widget.setAccessibleDescription(" ".join(said))
    widget.setProperty("explained", "\n".join(said))


def short_name(label: str) -> str:
    """A model's name in a word or two, from its line in the lists: "Medium" from
    "Medium: accurate, slow  (medium.en)"."""
    return label.split(":")[0].split("  (")[0].strip() or label


def microphone_trouble(error) -> str:
    """Why the microphone couldn't be opened, in words for the person. The audio side
    says it in such words itself where it can; anything else is kept to the log."""
    if isinstance(error, getattr(audio, "MicrophoneError", ())):
        return str(error)
    print(f"the microphone could not be opened: {type(error).__name__}: {error}", flush=True)
    if isinstance(error, FileNotFoundError):
        return ("The program that records from the microphone isn't installed. It comes "
                "with the desktop's sound system.")
    return "The microphone can't be opened. Check that it is plugged in and switched on."


def stopped_why(recorder) -> str:
    """What to say when a microphone that was open stopped by itself."""
    why = getattr(recorder, "why", None)
    try:
        said = why() if callable(why) else ""
    except Exception:
        said = ""
    return "The microphone stopped." + (f" {said}" if said else "")


class Hub:
    """What a window may ask of the rest of the app: to open another window, to change
    the key, to say something in a notice. The tray fills these in. Left as they are,
    they do nothing, so that a window can be made and tried by itself."""

    def show_settings(self) -> None: pass
    def show_help(self) -> None: pass
    def show_log(self) -> None: pass
    def wake(self) -> None: pass

    def changed(self) -> None:
        """A setting, or the model in use, was changed outside Settings: it follows."""

    def announce(self, text: str, kind: str = "info") -> None:
        """A passing notice. `kind` is "info" or "problem", which stays longer."""

    def set_hotkey(self, name: str) -> str:
        """Windows: take the key called `name` ("" for none). Returns why it couldn't be
        taken, in words for beside the chooser, or ""."""
        return ""

    def hotkey_problem(self) -> str:
        """Why the chosen key isn't working, or ""."""
        return ""


class Window(QWidget):
    """What the app's own windows share, so that each can be worked from the keyboard
    and by voice: Escape closes it, Enter presses the button that has the keyboard (which
    outside a dialog only the space bar did), and the engine is told how many of them are
    showing, which is how it knows whether "close that window" is meant for one of them."""

    showing = []    # the app's windows that can be seen now, the last one shown last
    counts = True   # whether "close that window" may close it

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            at = self.focusWidget()
            if isinstance(at, QPushButton) and at.isEnabled():
                at.click()
                return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.note_shown(not self.isMinimized())

    def hideEvent(self, event) -> None:
        self.note_shown(False)
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isVisible():
            self.note_shown(not self.isMinimized())

    def note_shown(self, shown: bool) -> None:
        if not self.counts:
            return
        if self in Window.showing:
            Window.showing.remove(self)
        if shown:
            Window.showing.append(self)
        engine = getattr(self, "engine", None)
        if engine is not None:
            engine.status.own_windows = len(Window.showing)

    @staticmethod
    def in_front():
        """The one of the app's windows that "close that window" means: the one that has
        the keyboard, or else the one opened last. None if none is showing."""
        Window.showing[:] = [window for window in Window.showing if alive(window)]
        active = QApplication.activeWindow()
        if active in Window.showing:
            return active
        return Window.showing[-1] if Window.showing else None


def alive(thing) -> bool:
    """Whether a Qt object is still there to be used: one that has been deleted raises
    at the first touch."""
    try:
        return not sip.isdeleted(thing)
    except TypeError:
        return False


def bring(window) -> None:
    """Show one of the app's windows and put it in front, with the keyboard."""
    if window.isMinimized():
        window.showNormal()
    else:
        window.show()
    window.raise_()
    window.activateWindow()


class Chooser(QComboBox):
    """A list to choose from that changes only when something is chosen in it.

    Qt's own changes with the mouse wheel and with the arrow keys, at every notch and
    every press. In a page that scrolls, that changed the speech model, and loaded it,
    when all that was meant was to scroll past. Here the wheel is left to the page, and
    the arrow keys open the list, where a choice is made with Enter."""

    OPENERS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
               Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Return, Qt.Key.Key_Enter)

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # not by the wheel

    def wheelEvent(self, event) -> None:
        event.ignore()  # the page it is in scrolls instead

    def keyPressEvent(self, event) -> None:
        if event.key() in self.OPENERS and not self.view().isVisible():
            self.showPopup()
            return
        super().keyPressEvent(event)


class TipsByKeyboard(QObject):
    """Shows a thing's tip when it is reached with the keyboard, as resting the mouse on
    it does: for somebody who has no mouse to rest on things. The tip goes when the
    keyboard moves on.

    Every part of the window that was given words with explain() is watched. (This took
    the place of a strip at the foot of the window that showed the same words: with a
    mouse both it and the tip showed at once, and it took room from a small screen.)"""

    SHOWN = 20000   # thousandths of a second a tip stays, if the keyboard doesn't move on
    BY_KEYBOARD = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                   Qt.FocusReason.ShortcutFocusReason)

    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.watched = set()
        self.showing = None  # what a tip is up for, put there by this

    def watch_all(self) -> None:
        """Watch everything in the window that has been given help so far."""
        for widget in self.owner.findChildren(QWidget):
            if widget.property("explained") and widget not in self.watched:
                self.watched.add(widget)
                widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        kind = event.type()
        if kind == QEvent.Type.FocusIn and event.reason() in self.BY_KEYBOARD:
            self.show_for(watched)
        elif kind == QEvent.Type.FocusOut and self.showing is watched:
            self.showing = None
            QToolTip.hideText()
        return False

    def show_for(self, widget) -> None:
        """Put the tip of `widget` up beside it, just under its left end."""
        text = widget.toolTip()
        if not text:
            return
        self.showing = widget
        at = widget.mapToGlobal(QPoint(12, widget.height() + 2))
        QToolTip.showText(at, text, widget, QRect(), self.SHOWN)


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
        # A picture only: what it shows is always said in words beside it as well, and a
        # screen reader is told what the picture is.
        self.setAccessibleName("Microphone level")
        explain(self,
                "How loud your voice is. Green is a good level. Grey or blue is too quiet for "
                "the room: speak up, or move closer to the microphone. Yellow and orange are "
                "close to the most the microphone can take, and red is past it: move back, or "
                "turn the microphone down. The words beside the bar say the same.")
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


class MeterWindow(Window):
    """How loud the voice is at the microphone, as it is spoken, with the bar and the
    colours of the reading window.

    Opening the window opens the microphone: nothing has to be pressed. Dictation is
    switched off for as long as it is open, so that what is said to try the level isn't
    typed anywhere, and comes back as it was when the window is closed or minimised.

    With dictation off, nothing said can close it. So it closes by itself when nothing
    has been heard for a minute, and says beforehand that it will: somebody working by
    voice alone gets dictation back without touching anything."""

    SPOKEN = 6          # readings of the level, about a third of a second, before a phrase is judged
    QUIET_SECONDS = 6   # with nothing heard for this long, it says where to choose the microphone
    RETRY_SECONDS = 2   # a microphone that failed or stopped is tried again after this long
    CLOSE_SECONDS = 60  # with nothing heard for this long, the window closes itself
    WARN_SECONDS = 15   # and for this long before that, it counts down
    WAITING = ("Speak as you do when you dictate. The bar shows how loud your voice is: "
               "green is a good level.")

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Microphone level")
        self.setMinimumWidth(round(400 * grown(self)))
        self.last_sound = 0.0    # when somebody last spoke, or the window was opened
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
        self.closing = QLabel(self.STAYS)  # that it closes by itself, and when
        self.closing.setWordWrap(True)
        layout.addWidget(self.closing)
        row = QHBoxLayout()
        close = QPushButton("&Close")
        close.clicked.connect(self.close)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.watch = QTimer(self)
        self.watch.timeout.connect(self.check)
        self.say("Opening the microphone\u2026", reading.GREY, "")
        dress(self)

    STAYS = "It closes by itself when nothing has been heard for a minute."

    def say(self, words: str, colour: tuple, advice: str) -> None:
        self.verdict.setText(words)
        self.verdict.setStyleSheet(
            f"font-size: {points(self, 1.6)}pt; font-weight: bold; "
            "color: rgb(%d, %d, %d);" % colour)
        self.advice.setText(advice)
        # The bar is a picture: what it comes to is said in words, here and to a screen reader.
        self.bar.setAccessibleDescription(f"{words}. {advice}".strip())

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
        self.last_sound = time.monotonic()
        self.closing.setText(self.STAYS)
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
        left = self.CLOSE_SECONDS - (now - self.last_sound)
        if left <= 0:
            self.close()  # nobody is here: dictation comes back as it was
            return
        self.closing.setText(
            self.STAYS if left > self.WARN_SECONDS else
            f"Nothing has been heard for a while. Closing in {int(left) + 1} seconds: "
            "say something to keep it open.")
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
                + ("choose another microphone in Settings, and see that Windows lets "
                   "desktop apps use the microphone (its Settings, Privacy, Microphone)."
                   if config.WINDOWS else
                   "choose the microphone in your desktop's sound settings."))

    def work(self, stop, opening: int, microphone: str) -> None:
        import numpy as np
        try:
            recorder = audio.open_microphone(microphone)
        except Exception as e:
            self.bridge.ended.emit(opening, microphone_trouble(e))
            return
        problem = ""
        try:
            ear = reading.Ear(self.engine.boost)
            nbytes, loudest, peak, count = config.FRAME * 2, 0.0, 0, 0
            while not stop.is_set():
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    problem = stopped_why(recorder)
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
            problem = "The microphone could not be followed. The log says why."
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
            self.last_sound = time.monotonic()  # somebody is here: it stays open
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


class Letters:
    """Hands out the Alt-letters of one window, each letter once: for its buttons, for
    the labels of its boxes, and for the titles of its groups, which Alt and the letter
    then jump to. The first letter of a word is taken where one is still free."""

    def __init__(self):
        self.used = set()

    def __call__(self, text: str) -> str:
        starts = [at for at, c in enumerate(text)
                  if c.isalpha() and (at == 0 or not text[at - 1].isalpha())]
        others = [at for at, c in enumerate(text) if c.isalpha() and at not in starts]
        for at in starts + others:
            if text[at].lower() not in self.used:
                self.used.add(text[at].lower())
                return text[:at].replace("&", "&&") + "&" + text[at:].replace("&", "&&")
        return text.replace("&", "&&")


LONGEST_TICK = 64  # characters: a tick box's line longer than this loses its brackets


def tick_words(label: str) -> tuple:
    """A tick box's line as it is shown, and what of it is said in its help instead. A
    long line can't wrap, and made Settings wider than a small screen: so what it says in
    brackets after its first words is moved to the help, which has the room."""
    head, gap, more = label.partition("  (")
    if gap and more.endswith(")") and len(label) > LONGEST_TICK:
        more = more[:-1].strip()
        return head.strip(), more[:1].upper() + more[1:] + ("" if more.endswith(".") else ".")
    return label, ""


def hotkey_of(settings) -> str:
    """Windows: the name of the key that switches dictation on and off, "" for none.
    Read with care: settings from before there was a choice of key kept a tick box for
    the number pad's + instead."""
    name = getattr(settings, "hotkey", None)
    if name is None:
        try:
            name = hotkey.NUMPAD_PLUS if settings.enabled("numpad_plus") else ""
        except KeyError:
            name = ""
    return hotkey.chosen(name)


class KeyChooser(QWidget):
    """Windows: the choice of a key that switches dictation between off and awake,
    whichever program is in front. Under it, in words: what the chosen key costs, or
    that Windows wouldn't give it."""

    ABOUT = ("A key that does what a click on the tray icon does, whichever program is in "
             "front: from asleep or off straight to awake, and from awake to off. Windows "
             "hands the key to this program alone while it is chosen, so choose one you "
             "don't otherwise use. None, to begin with.")

    def __init__(self, engine: Engine, hub: Hub, alt=lambda text: text):
        super().__init__()
        self.engine, self.hub = engine, hub
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        label = QLabel(alt("Key that switches dictation on and off:"))
        self.keys = Chooser()
        self.keys.addItem("None", "")
        for name in hotkey.KEYS:
            self.keys.addItem(name, name)
        label.setBuddy(self.keys)
        self.keys.setAccessibleName("Key that switches dictation on and off")
        self.keys.activated.connect(self.on_choice)
        explain(self.keys, self.ABOUT)
        row.addWidget(label)
        row.addWidget(self.keys)
        row.addStretch()
        layout.addLayout(row)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.refresh()

    def on_choice(self, index: int) -> None:
        self.hub.set_hotkey(self.keys.itemData(index))
        self.refresh()

    def refresh(self) -> None:
        name = hotkey_of(self.engine.settings)
        self.keys.setCurrentIndex(max(0, self.keys.findData(name)))
        problem = self.hub.hotkey_problem()
        self.note.setText(problem or hotkey.COSTS.get(name, ""))
        self.note.setVisible(bool(self.note.text()))


class StartTick(QWidget):
    """A tick box for whether the app starts by itself when the person signs in, with a
    line under it for when that can't be told or couldn't be changed. See autostart.py.

    How things stand is asked each time the window it is in is shown, not when it is
    made: the installer may have changed it since."""

    def __init__(self, alt=lambda text: text):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tick = QCheckBox(alt("Start when I sign in"))
        self.tick.setEnabled(False)  # until it has been asked how things stand
        self.tick.clicked.connect(self.on_click)
        explain(self.tick,
                f"Ticked, {APP_NAME} starts by itself when you sign in to this computer, and "
                "listens for \"wake up\". Unticked, it runs only when you start it from the "
                + ("Start menu." if config.WINDOWS else "application menu."))
        layout.addWidget(self.tick)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        layout.addWidget(self.note)

    def refresh(self, problem: str = "") -> None:
        try:
            state = autostart.state()
        except Exception as e:  # never in the way of the window being shown
            print(f"whether it starts at sign-in could not be told: {e}", flush=True)
            state = None
        self.tick.setEnabled(state is not None)
        self.tick.setChecked(bool(state))
        self.note.setText(problem or (autostart.CANT_TELL if state is None else ""))
        self.note.setVisible(bool(self.note.text()))

    def on_click(self, on: bool) -> None:
        try:
            problem = autostart.switch(on)
        except Exception as e:
            problem = f"That could not be changed: {e}"
        self.refresh(problem)


class SettingsWindow(Window):
    """Tick boxes for every voice command and punctuation word. Changes apply at once."""

    OWN_GROUP = "My shortcuts and commands"  # the box, and the group of the tick box in it

    def __init__(self, engine: Engine, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.hub = hub or Hub()
        self.on_setting = lambda key: None  # the tray's own reaction to a changed tick box
        self.setWindowTitle("Settings")  # the desktop adds the program's name to each title
        self.extension_problem = ""  # why the Writer extension couldn't be put in, if so
        alt = self.alt = Letters()
        outer = QVBoxLayout(self)
        note = QLabel(
            "Changes take effect at once. What is in quotes is something to say: untick "
            "any you don't want acted on, and it is typed as ordinary words instead. "
            "\"Wake up\" and \"go to sleep\" are always on. Rest the mouse on anything, "
            "or tab to it, for more about it."
        )
        note.setWordWrap(True)
        outer.addWidget(note)
        # What is wrong just now, in words, where there is anything: see refresh_banner().
        self.banner_box = QWidget()
        self.banner_box.setObjectName("banner")
        self.banner_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.banner_box.setStyleSheet(
            "QWidget#banner { background: #e0a020; border-radius: 4px; }"
            "QWidget#banner QLabel { color: black; background: transparent; }")
        row = QHBoxLayout(self.banner_box)
        row.setContentsMargins(8, 6, 8, 6)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner_log = QPushButton(alt("Open the log"))
        self.banner_log.clicked.connect(lambda: self.hub.show_log())
        explain(self.banner_log, "Shows what the program has written down about what it "
                                 "is doing, which is where the reasons for a fault are.")
        row.addWidget(self.banner, 1)
        row.addWidget(self.banner_log, 0, Qt.AlignmentFlag.AlignTop)
        outer.addWidget(self.banner_box)
        close = QPushButton(alt("Close"))  # made first, so that C is its letter
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.addWidget(self.model_box())
        if config.WINDOWS:
            layout.addWidget(self.microphone_box())
        layout.addWidget(self.words_box())
        if hasattr(engine.settings, "set_shortcuts"):
            layout.addWidget(self.shortcuts_box())
        layout.addWidget(self.remote_box())
        groups = dict(getattr(self, "own_groups", {}))   # a box that is there already
        self.ticks = {}  # by setting: those that do nothing as things stand are greyed
        self.tick_text = {}  # by setting: (its line, what of its line is said in its help)
        for item in ITEMS:
            if item.key in WINDOWS_ONLY and not config.WINDOWS:
                continue
            if item.group not in groups:
                box = QGroupBox(alt(item.group))  # Alt and the letter jumps to the group
                box.setLayout(QVBoxLayout())
                layout.addWidget(box)
                groups[item.group] = box
            label = item.label
            if item.key == "other_apps" and config.WINDOWS:
                label = ("Dictate into other programs' text boxes, such as a chat box  "
                         "(typed in as keystrokes)")
            self.tick_text[item.key] = tick_words(label)
            tick = QCheckBox(self.tick_text[item.key][0].replace("&", "&&"))
            tick.setChecked(engine.settings.enabled(item.key))
            tick.toggled.connect(lambda on, key=item.key: (
                engine.settings.set(key, on), engine.setting_changed(key),
                self.on_setting(key)))
            groups[item.group].layout().addWidget(tick)
            self.ticks[item.key] = tick
        if "Hearing" in groups:
            groups["Hearing"].layout().addLayout(self.noises_row())
        layout.addWidget(self.key_box() if config.WINDOWS else self.command_box())
        layout.addWidget(self.start_box())
        if config.WINDOWS:
            layout.addWidget(self.look_box())
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        close.clicked.connect(self.close)
        explain(close, "Closes this window; so does the Escape key. Nothing needs saving: "
                       "each change is kept as you make it.")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        outer.addLayout(row)
        self.fit_ticks()
        self.refresh_banner()
        # The tips are shown for what is tabbed to as well as for what the mouse rests on.
        self.tips = TipsByKeyboard(self)
        self.tips.watch_all()
        # Wide enough for the longest line, with room for the scroll bar: but never wider
        # or taller than the screen, where the page then scrolls sideways too.
        # The look that was chosen, if it isn't Windows' own: its sizes are other sizes.
        frame = looks.dress(self, look_of(self))
        self.ensurePolished()
        margins = outer.contentsMargins()
        width = (inner.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width()
                 + 2 * scroll.frameWidth() + margins.left() + margins.right() + 8)
        width = max(420, width) + frame.width()
        height = round(640 * grown(self)) + frame.height()
        screen = QApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            width, height = min(width, room.width() - 24), min(height, room.height() - 48)
        self.resize(width, height)

    # The windows that are opened from the speech recognition box: the button's words,
    # what opens it, what is said beside it, and more for when the mouse rests on it.
    WINDOWS = (
        ("Install or remove models\u2026", "on_show_models",
         "Download another model from the internet, or remove one you don't use.",
         "Opens the list of models: which are installed, how big each is, and buttons to "
         "install or remove them. A download goes on if the window is closed, and can be "
         "paused. What is installed appears in the list above."),
        ("Test the models on my voice\u2026", "on_show_voice_test",
         "Read a passage aloud once, and see how many words each model gets wrong and how "
         "long it takes.",
         "Opens the voice test. You read a short passage once; each model you tick then "
         "hears that one recording, cut into phrases as dictation would cut it. It shows "
         "the words each got wrong, those it got right without being sure, and how long a "
         "phrase took. Dictation is off while you record."),
        ("Read aloud for training\u2026", "on_show_reading",
         "Record yourself reading sentences. They are what a model is retrained on.",
         "Opens the reading window. One sentence is shown at a time; read it and it moves "
         "on by itself. Each is kept as a sound file with its words, on this computer. "
         "About half an hour's reading comes with it, and you can add a text of your own. "
         "Dictation is off while it is open."),
        ("Train on my voice\u2026", "on_show_training",
         "Retrain a model on those recordings, so that it knows your voice. Experimental: "
         f"about an hour, and {training.MEMORY_GB} GB of memory.",
         "Opens the training window: the folder of recordings, the model to start from and "
         "a name for the result. The work runs by itself and can be stopped and carried "
         "on. The first time, the window offers to install the training tools (about "
         f"{training.TOOLS_GB:g} GB). The new model then appears in the list above."),
    )

    def model_box(self) -> QGroupBox:
        """The model that does the recognising: a chooser, and the windows for installing
        models, trying them, and retraining one."""
        alt = self.alt
        box = QGroupBox("Speech recognition")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        label = QLabel(alt("Model used for dictation:"))
        self.models = Chooser()
        label.setBuddy(self.models)
        self.models.setAccessibleName("Model used for dictation")
        self.models_window = self.voice_window = self.read_window = self.train_window = None
        self.models.activated.connect(self.on_model)
        explain(self.models,
                "The model that turns what you say into words while dictation is awake. "
                "Only those that are installed are listed. Open the list with the space "
                "bar or an arrow key, and choose with Enter.")
        row.addWidget(label)
        row.addWidget(self.models, 1)
        layout.addLayout(row)
        note = QLabel("Parakeet Unified is the best of the models so far, and the one to "
                      "use. A change of model takes a few seconds to load. The model chosen "
                      "here does all the listening, \"wake up\" included.")
        note.setWordWrap(True)
        layout.addWidget(note)
        # Said only while the recommended model isn't here to be chosen.
        self.suggest = QWidget()
        row = QHBoxLayout(self.suggest)
        row.setContentsMargins(0, 0, 0, 0)
        missing = QLabel("Parakeet Unified isn't installed on this computer yet.")
        missing.setWordWrap(True)
        fetch = QPushButton(alt("Get Parakeet Unified\u2026"))
        fetch.clicked.connect(self.on_show_models)
        explain(fetch, "Opens the list of models, where \"Install\" beside Parakeet Unified "
                       "downloads it (about "
                       + (models.size_text(models.BY_NAME[RECOMMENDED].megabytes * 1e6)
                          if RECOMMENDED in models.BY_NAME else "660 MB")
                       + "). Choose it in the list above when it has arrived.")
        row.addWidget(missing, 1)
        row.addWidget(fetch)
        layout.addWidget(self.suggest)
        self.refill_models()
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(12)
        for at, (words, opens, beside, more) in enumerate(self.WINDOWS):
            button = QPushButton(alt(words))
            button.clicked.connect(getattr(self, opens))
            explain(button, more)
            said = QLabel(beside)
            said.setWordWrap(True)
            said.setToolTip(tip(more))
            grid.addWidget(button, at, 0)
            grid.addWidget(said, at, 1)
        layout.addLayout(grid)
        return box

    def on_model(self, index: int) -> None:
        name = self.models.itemData(index)
        if name and name != (self.engine.settings.model or config.AWAKE_MODEL):
            self.engine.set_model(name)
            self.model_changed()

    def model_changed(self) -> None:
        """The model in use has changed, here, in another window or by the engine putting
        a choice back that wouldn't load: what depends on it follows."""
        for key, tick in self.ticks.items():  # another window may have changed one of these
            if tick.isChecked() != self.engine.settings.enabled(key):
                tick.blockSignals(True)
                tick.setChecked(self.engine.settings.enabled(key))
                tick.blockSignals(False)
        self.refill_models()
        if self.models_window is not None:
            self.models_window.refresh()  # which one is "in use", and can't be removed

    def refresh_banner(self) -> None:
        """Say at the top of the window what is wrong just now, each thing a sentence that
        says what to do; and show nothing there when nothing is."""
        status = self.engine.status
        lines = []
        failed = getattr(status, "failed", "")
        if failed:
            lines.append(f"{failed} \"Install or remove models\", below, has the models.")
        lines += [str(problem) for problem in getattr(status, "problems", ())]
        if self.extension_problem:
            lines.append(self.extension_problem)
        elif getattr(status, "update_waiting", False):
            lines.append("The Writer extension is waiting to be put in. Save your work, "
                         "close LibreOffice for a few seconds, then open it again. Until "
                         "then, dictation into Writer may not work as these settings say.")
        key = self.hub.hotkey_problem()
        if key:
            lines.append(key)
        self.banner.setText("\n".join(lines))
        self.banner.setAccessibleName("What is wrong just now")
        self.banner_box.setVisible(bool(lines))

    def noises_row(self) -> QHBoxLayout:
        """What has been kept of the sounds marked "that was a noise", with buttons to
        look at them and to remove them."""
        row = QHBoxLayout()
        self.noises_note = QLabel()
        self.noises_note.setWordWrap(True)
        about = ("Say \"that was a noise\" straight after a rustle or a click has been written "
                 "as words. The words are taken back, and that one sound is kept in a folder on "
                 "this computer, each with a line in list.txt saying what it was written as, how "
                 "long it was, and how sure the model was. Nothing is sent anywhere. The "
                 "last 300 are kept. They are there so that what tells your noises from your "
                 "speech can be worked out from your own noises, not from recordings of other "
                 "people's. Sounds left out without being marked are not kept: the log only "
                 "says that one was, and why.")
        explain(self.noises_note, about)
        self.noises_open = QPushButton("Open the folder")
        self.noises_open.setAccessibleName("Open the folder of sounds marked as noises")
        self.noises_open.clicked.connect(self.on_noises_open)
        explain(self.noises_open,
                "Shows the folder: a sound file for each noise you marked, and list.txt. You can "
                "listen to any of them, or delete any you didn't mean to keep.", about)
        self.noises_clear = QPushButton("Delete them")
        self.noises_clear.setAccessibleName("Delete the sounds marked as noises")
        self.noises_clear.clicked.connect(self.on_noises_clear)
        explain(self.noises_clear,
                "Removes every sound you marked as a noise, and the list. Nothing else is "
                "touched. It asks first.")
        row.addWidget(self.noises_note, 1)
        row.addWidget(self.noises_open)
        row.addWidget(self.noises_clear)
        self.refresh_noises()
        return row

    def refresh_noises(self) -> None:
        count, size = speech.noises_kept(config.NOISE_DIR)
        if count:
            self.noises_note.setText(
                f"Sounds you marked with \"that was a noise\": {count}, "
                f"{models.size_text(size)}, kept on this computer.")
        else:
            self.noises_note.setText("No sounds marked with \"that was a noise\" are kept.")
        self.noises_open.setEnabled(bool(count))
        self.noises_clear.setEnabled(bool(count))

    def on_noises_open(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(config.NOISE_DIR))

    def on_noises_clear(self) -> None:
        count, _ = speech.noises_kept(config.NOISE_DIR)
        if count and ask(self, f"Delete the {count} sound{'s' if count != 1 else ''} you marked "
                               "as noises, and the list of them?", careful=True):
            speech.forget_noises(config.NOISE_DIR)
        self.refresh_noises()

    def key_box(self) -> QGroupBox:
        """Windows: the key that switches dictation on and off."""
        box = QGroupBox(self.alt("Keyboard"))
        layout = QVBoxLayout(box)
        self.key_chooser = KeyChooser(self.engine, self.hub)
        layout.addWidget(self.key_chooser)
        return box

    def command_box(self) -> QGroupBox:
        """Linux: the command that switches dictation as a click on the icon does, for
        the person to bind to a key of their own in the desktop's settings. Desktops
        differ too much in how a program may take a key for the app to take one itself."""
        box = QGroupBox(self.alt("Keyboard"))
        layout = QVBoxLayout(box)
        note = QLabel("To switch dictation with a key, give this command a key of your own "
                      "in your desktop's shortcut settings. It does what a click on the "
                      "icon does: awake if it was asleep or off, off if it was awake.")
        note.setWordWrap(True)
        layout.addWidget(note)
        app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        command = QLineEdit(
            f"sh -c 'cd \"{app}\" && \"{sys.executable}\" -m dictation.control toggle'")
        command.setReadOnly(True)
        command.setCursorPosition(0)
        command.setAccessibleName("The command that switches dictation")
        explain(command,
                "The command to bind to a key. In place of \"toggle\" it also takes \"wake\", "
                "\"sleep\", \"off\" and \"settings\".")
        copy = QPushButton("Copy")
        copy.setAccessibleName("Copy the command that switches dictation")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(command.text()))
        explain(copy, "Copies the command, to paste into the desktop's shortcut settings.")
        row = QHBoxLayout()
        row.addWidget(command, 1)
        row.addWidget(copy)
        layout.addLayout(row)
        return box

    def start_box(self) -> QGroupBox:
        """Whether the app starts when the person signs in."""
        box = QGroupBox(self.alt("Starting"))
        layout = QVBoxLayout(box)
        self.start_tick = StartTick()
        layout.addWidget(self.start_tick)
        return box

    def look_box(self) -> QGroupBox:
        """A chooser for the look of the app's windows and of the tray icon's menu
        (Windows)."""
        box = QGroupBox(self.alt("Appearance"))
        row = QHBoxLayout(box)
        label = QLabel("The look of the app's windows and the tray icon's menu:")
        chooser = Chooser()
        label.setBuddy(chooser)
        chooser.setAccessibleName("The look of the app's windows and the tray icon's menu")
        for key, name in looks.LOOKS:
            chooser.addItem(name, key)
        chooser.setCurrentIndex(max(0, chooser.findData(self.engine.settings.look)))
        chooser.activated.connect(lambda index: self.on_look(chooser.itemData(index)))
        explain(chooser,
                "How this app's own windows and its tray menu are drawn: the title bar, buttons, "
                "tick boxes and scroll bars. Every window is made again in the look you pick.")
        row.addWidget(label)
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
        found = available_models(config.MODEL_DIR)
        self.models.clear()
        for name, label in found:
            self.models.addItem(label, name)
        at = self.models.findData(current)
        if at >= 0:
            self.models.setCurrentIndex(at)
        self.suggest.setVisible(RECOMMENDED not in [name for name, _ in found])
        self.fit_ticks()

    IDLE = "  (no effect at present)"  # added to the line of a tick box that is greyed

    def fit_ticks(self) -> None:
        """Grey the tick boxes that would do nothing with the model in use, and say why,
        first, in their help. Their ticks are kept for when they do.

        They are greyed in colour and in words, but can still be tabbed to: a box that
        can't have the keyboard could never say, to somebody without a mouse, why it is
        grey. Ticking one meanwhile does no harm."""
        ticks = getattr(self, "ticks", {})  # the model chooser is made before the tick boxes
        idle = without_effect(self.engine.settings.model or config.AWAKE_MODEL,
                              self.engine.settings.remote, config.MODEL_DIR)
        grey = looks.greyed(look_of(self)) or self.palette().color(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText).name()
        for key, tick in ticks.items():
            why = idle.get(key, "")
            words, moved = self.tick_text[key]
            tick.setText(words.replace("&", "&&") + (self.IDLE if why else ""))
            tick.setStyleSheet(f"QCheckBox {{ color: {grey}; }}" if why else "")
            about = help_for(key)
            if key == "other_apps":
                about += (" Notepad and its like are handed the words whole; elsewhere they are "
                          "typed in as keystrokes." if config.WINDOWS else
                          " It uses the desktop's accessibility interface, the one screen "
                          "readers use, and switches that on for your session; unticking "
                          "switches it off again.")
            # Why it does nothing as things stand, where that is so, and then what it is for.
            explain(tick, why, moved, about)
        tips = getattr(self, "tips", None)
        if tips is not None and tips.showing is not None:  # the tip that is up may be one of these
            tips.show_for(tips.showing)

    def fresh(self, name: str, make):
        """The window kept as `name`, made if there is none. One that was kept over a
        change of look, to finish a download it had under way, is made again in the new
        look once that is done."""
        window = getattr(self, name)
        if window is not None and getattr(window, "old_look", False) and not window.busy():
            window.close()                # so that it is no longer counted as showing
            window.deleteLater()
            window = None
        if window is None:
            window = make()
            setattr(self, name, window)
        return window

    def on_show_training(self) -> None:
        self.fresh("train_window",
                   lambda: TrainWindow(self.engine, self.refill_models, self.hub))
        bring(self.train_window)

    def on_show_voice_test(self) -> None:
        self.fresh("voice_window",
                   lambda: VoiceTestWindow(self.engine, self.model_changed, self.hub))
        bring(self.voice_window)

    def on_show_reading(self) -> None:
        if self.read_window is None:
            self.read_window = ReadWindow(self.engine)
        bring(self.read_window)

    def on_show_models(self) -> None:
        self.fresh("models_window",
                   lambda: ModelsWindow(self.engine, self.refill_models, self.hub))
        bring(self.models_window)

    # ---- another computer doing the recognising ---------------------------------------
    def remote_box(self) -> QGroupBox:
        """Using another computer's models, and letting others use this one's."""
        alt = self.alt
        box = QGroupBox("Another computer")
        layout = QVBoxLayout(box)
        note = QLabel("A faster computer on your network can do the recognising. On that "
                      "computer tick \"Let other computers use this one\". Here tick \"Use "
                      "another computer\" and enter the address and key it shows.")
        note.setWordWrap(True)
        layout.addWidget(note)
        chosen = self.engine.settings.remote
        self.remote_on = QCheckBox(alt("Use another computer for speech recognition"))
        self.remote_on.setChecked(chosen["on"])
        layout.addWidget(self.remote_on)
        form = QGridLayout()
        form.setContentsMargins(22, 0, 0, 0)
        self.remote_address = QLineEdit(chosen["address"])
        self.remote_address.setPlaceholderText("its name or address on the network")
        self.remote_key = QLineEdit(chosen["key"])
        self.remote_key.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.remote_key.setPlaceholderText("the key shown on that computer")
        self.remote_model = Chooser()
        self.fill_remote_models([])
        connect = QPushButton(alt("Connect"))
        for row, (label, widget) in enumerate((("Address", self.remote_address),
                                               ("Key", self.remote_key),
                                               ("Model there", self.remote_model))):
            # Each box is named for a screen reader by the label beside it, and Alt and
            # the label's letter goes to it.
            named = QLabel(alt(label))
            named.setBuddy(widget)
            widget.setAccessibleName(f"{label}, of the other computer")
            form.addWidget(named, row, 0)
            form.addWidget(widget, row, 1)
        form.addWidget(connect, 0, 2)
        self.remote_wake = QCheckBox("Listen for \"wake up\" there too")
        self.remote_wake.setChecked(chosen["wake"])
        form.addWidget(self.remote_wake, 3, 0, 1, 3)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        self.remote_note = QLabel()
        self.remote_note.setWordWrap(True)
        layout.addWidget(self.remote_note)
        self.remote_note.setVisible(False)  # shown when it has something to say
        explain(self.remote_on,
                "Each phrase is sent to the other computer to be recognised, and the words come "
                "back. If it can't be reached, this computer does the work itself and tries the "
                "other again after a short while.",
                "With the sound go the last words before the cursor, your own words from the "
                "box above and, in a C or C++ file, the names in it, to help the model. All "
                "of it is encrypted on the way, and each computer makes sure of the other by "
                "the key before anything is sent.")
        explain(self.remote_address,
                "The other computer's name or address on your network, as it shows it once "
                "\"Let other computers use this one\" is ticked there. Add :port if it isn't "
                "the usual one.")
        explain(self.remote_key,
                "The key the other computer shows. It is never sent: each computer proves to "
                "the other that it holds it.")
        explain(self.remote_model,
                "Which of the other computer's models to use. Press Connect to see what it has.")
        explain(connect,
                "Saves the address and the key, and asks the other computer whether it answers.")
        explain(self.remote_wake,
                "Unticked, \"wake up\" is listened for on this computer, and nothing is sent "
                "while dictation is asleep. Ticked, the short sounds heard while asleep are sent "
                "too, which wakes it sooner on a slow computer.")
        self.remote_bridge = RemoteBridge()
        self.remote_bridge.checked.connect(self.on_remote_checked)
        connect.clicked.connect(self.apply_remote)
        self.remote_on.clicked.connect(self.apply_remote)
        self.remote_wake.clicked.connect(self.apply_remote)
        self.remote_model.activated.connect(self.apply_remote)
        self.remote_address.returnPressed.connect(self.apply_remote)
        self.remote_key.returnPressed.connect(self.apply_remote)

        self.share_on = QCheckBox(alt("Let other computers use this one for speech recognition"))
        self.share_on.setChecked(self.engine.settings.share["on"])
        self.share_on.clicked.connect(self.apply_sharing)
        layout.addWidget(self.share_on)
        row = QHBoxLayout()
        row.setContentsMargins(22, 0, 0, 0)
        self.share_note = QLabel()
        self.share_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        explain(self.share_on,
                "Other computers that are given this one's address and key can send it phrases "
                "to recognise. It answers on a port of its own (47614 unless set otherwise), "
                "which this computer's firewall has to let through.")
        self.share_copy = QPushButton("Copy key")
        explain(self.share_copy,
                "Copies the key, to paste into Settings on the other computer.")
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
            self.say_remote("")
            return
        self.say_remote("Asking the other computer\u2026")
        threading.Thread(
            target=lambda: self.remote_bridge.checked.emit(self.engine.check_remote()),
            daemon=True).start()

    def on_remote_checked(self, answer: dict) -> None:
        on = self.engine.settings.remote["on"]
        if answer.get("ok"):
            self.fill_remote_models(answer.get("models", []))
            self.say_remote(
                "Connected. Recognition is done on the other computer." if on
                else "The other computer answers. Tick the box above to use it.")
        else:
            self.say_remote(
                answer.get("why", "") + (" Recognition is being done on this computer." if on else ""))

    def say_remote(self, text: str) -> None:
        """What is said under the other computer's address: nothing, and no room for it,
        when there is nothing to say."""
        self.remote_note.setText(text)
        self.remote_note.setVisible(bool(text.strip()))

    def apply_sharing(self, *_) -> None:
        self.engine.set_sharing(self.share_on.isChecked())
        self.refresh_sharing()
        if self.engine.share_problem:  # give a retry a moment, then say how it stands
            QTimer.singleShot(1500, self.refresh_sharing)

    def refresh_sharing(self) -> None:
        share = self.engine.settings.share
        on = share["on"] and bool(share["key"])
        self.share_copy.setVisible(on)
        self.share_note.setVisible(on)   # no empty band under the tick box when it is off
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
        self.refresh_noises()  # one may have been marked since the window was last open
        self.refresh_banner()
        if hasattr(self, "microphones"):
            self.refill_microphones()  # a headset may have been plugged in since
        if hasattr(self, "key_chooser"):
            self.key_chooser.refresh()
        self.start_tick.refresh()
        if self.engine.settings.remote["on"]:
            self.check_remote()
        super().showEvent(event)

    def words_box(self) -> QGroupBox:
        """A list of the person's own names and terms."""
        box = QGroupBox(self.alt("My words"))
        layout = QVBoxLayout(box)
        note = QLabel("Names, unusual words and part numbers that get misheard, one to a "
                      "line, spelled the way you want them typed. They are used where they "
                      "fit: a name after \"Cheers,\" but still the ordinary word in an ordinary "
                      "sentence. A part number such as vLR5340 is put in wherever its letters "
                      "and figures were heard. Keep the list short.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.words = QPlainTextEdit()
        self.words.setPlainText("\n".join(self.engine.settings.words))
        self.words.setTabChangesFocus(True)
        self.words.setFixedHeight(self.words.fontMetrics().lineSpacing() * 5 + 16)
        self.words.setAccessibleName("My words, one to a line")
        explain(self.words,
                "One name or word to a line, spelled as you want it typed. Whisper is told to "
                "expect them; Parakeet finds them by their sound. They are saved a moment after "
                "you stop typing. A few dozen at most.")
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

    def shortcuts_box(self) -> QGroupBox:
        """The person's own shortcuts: a few words said by themselves that type a longer
        text, such as an address. How they are written is settings.py's to say: one to a
        line, and a line that begins with a space carries on the text of the line above."""
        box = QGroupBox(self.alt(self.OWN_GROUP))
        self.own_groups = {self.OWN_GROUP: box}   # its tick box is put in here: see __init__
        layout = QVBoxLayout(box)
        note = QLabel("A few words of your own, said by themselves, that type a longer text "
                      "or do something. Write one to a line: what you say, an equals sign, "
                      "then the text to type, or \"keys:\", \"open:\" or \"run:\" and what "
                      "to press, open or run.\nA line that begins with a space carries on "
                      "the one above: another line of its text, or a further step. For "
                      "example:")
        note.setWordWrap(True)
        layout.addWidget(note)
        example = QLabel("my address = 12 High Street\n    Dunedin 9016\n"
                         "new tab = keys: ctrl+t\n"
                         "my notes = open: ~/notes.txt\n"
                         "build it = run: make -C ~/project")
        example.setStyleSheet("font-family: monospace; padding-left: 16px;")
        example.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(example)
        self.shortcuts = QPlainTextEdit()
        # As it is typed, spaces at the start of a line and all: they mean something here.
        self.shortcuts.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.shortcuts.setPlainText(
            getattr(self.engine.settings, "shortcuts_text", lambda: "")())
        self.shortcuts.setTabChangesFocus(True)
        self.shortcuts.setFixedHeight(self.shortcuts.fontMetrics().lineSpacing() * 5 + 16)
        self.shortcuts.setAccessibleName("My shortcuts and commands, one to a line")
        explain(self.shortcuts,
                "One to a line: what you say, an equals sign, what is typed. Or, in place of "
                "a text, something to do: \"keys: ctrl+shift+t\" presses keys (several, one "
                "after another: \"keys: ctrl+k ctrl+s\"); \"open:\" opens a file, a folder "
                "or a web page; \"run:\" starts a program, once the tick box below allows "
                "it; \"type:\" types a text; \"wait: 2\" waits two seconds. A line that "
                "begins with a space carries on the one above: another line of its text, or "
                "a further step. \"ask first\" as the first step waits for you to say "
                "\"yes\". Empty lines, and lines that begin with #, are passed over. The "
                "words have to be said by themselves, as a phrase of their own. They work "
                "with \"Commands only\" ticked, too. Saved a moment after you stop typing.")
        layout.addWidget(self.shortcuts)
        self.shortcuts_note = QLabel()  # the lines that couldn't be understood
        self.shortcuts_note.setWordWrap(True)
        self.shortcuts_note.setVisible(False)
        layout.addWidget(self.shortcuts_note)
        self.shortcuts_timer = QTimer(self)  # saved a moment after the typing stops
        self.shortcuts_timer.setSingleShot(True)
        self.shortcuts_timer.setInterval(700)
        self.shortcuts_timer.timeout.connect(self.save_shortcuts)
        self.shortcuts.textChanged.connect(self.shortcuts_timer.start)
        return box

    def save_shortcuts(self) -> None:
        if not hasattr(self, "shortcuts"):
            return
        self.shortcuts_timer.stop()
        try:
            unclear = self.engine.settings.set_shortcuts(self.shortcuts.toPlainText())
        except OSError as e:
            unclear = []
            print(f"the shortcuts could not be saved: {e}", flush=True)
        count = len(unclear)
        self.shortcuts_note.setText(
            (f"{count} line{'s' if count != 1 else ''} couldn't be understood, and "
             f"{'were' if count != 1 else 'was'} left out. Each needs what you say, an "
             "equals sign, and what is typed:\n" + "\n".join(str(line) for line in unclear))
            if unclear else "")
        self.shortcuts_note.setVisible(bool(unclear))

    def hideEvent(self, event) -> None:
        self.save_words()
        self.save_shortcuts()
        super().hideEvent(event)

    def microphone_box(self) -> QGroupBox:
        """Windows: a chooser for the recording device. Always there, with or without a
        microphone when the app started: one plugged in later is found when the window is
        next shown."""
        box = QGroupBox(self.alt("Microphone"))
        layout = QVBoxLayout(box)
        self.microphones = Chooser()
        self.microphones.setAccessibleName("Microphone that dictation listens to")
        self.microphones.activated.connect(
            lambda index: self.engine.set_microphone(self.microphones.itemData(index)))
        explain(self.microphones,
                "The microphone that dictation listens to. Windows' own choice isn't always the "
                "one you expect. Listening starts again on the one you pick. For a microphone "
                "plugged in since this program started, press \"Look again\".")
        row = QHBoxLayout()
        row.addWidget(self.microphones, 1)
        self.microphones_again = QPushButton("Look again")
        self.microphones_again.clicked.connect(lambda: self.refill_microphones(letting_go=True))
        explain(self.microphones_again,
                "Reads the list of microphones from Windows again, for one plugged in since "
                "this program started. Windows only gives a fresh list while nothing is "
                "being recorded, so listening stops for a moment while it is read.")
        row.addWidget(self.microphones_again)
        layout.addLayout(row)
        self.microphones_note = QLabel()
        self.microphones_note.setWordWrap(True)
        layout.addWidget(self.microphones_note)
        self.refill_microphones(fresh=False)
        return box

    def refill_microphones(self, fresh: bool = True, letting_go: bool = False) -> None:
        """List the microphones Windows has, with the chosen one chosen. Windows gives a
        fresh list only while nothing is being recorded: `letting_go` has the engine close
        its microphone for the moment that takes, which is only done when it is asked
        for ("Look again"), not every time this window opens."""
        again = getattr(self.engine, "microphones", None) if letting_go else None
        try:
            names = again() if callable(again) else audio.microphones(fresh=fresh)
        except TypeError:  # an audio side from before the list could be read again
            names = audio.microphones()
        chosen = self.engine.settings.microphone
        self.microphones.clear()
        self.microphones.addItem("Windows' default recording device", "")
        for name in names:
            # Shown whole: Windows cuts the name the device is chosen by at 31 letters.
            self.microphones.addItem(audio.whole(name), name)
        if chosen and chosen not in names:
            # Kept in the list and said in words: otherwise the choice would silently
            # read as Windows' default, which is what is listened to meanwhile.
            self.microphones.addItem(f"{chosen}  (not connected now)", chosen)
        self.microphones.setCurrentIndex(max(0, self.microphones.findData(chosen)))
        self.microphones_note.setText(
            "Open \"Microphone level\" from the tray icon's menu and talk: the bar should "
            "move. If it doesn't, try another microphone here: the bar follows."
            if names else
            "Windows lists no microphone. Plug one in, and see that Windows lets desktop "
            "apps use the microphone (its Settings, Privacy, Microphone). Then close this "
            "window and open it again.")


class RemoteBridge(QObject):
    checked = pyqtSignal(dict)  # what the other computer said when asked what it offers


class Downloads(QObject):
    """The downloading of models, for every window that shows it: the models window, the
    welcome window, the training window. One at a time, on a thread of its own, going on
    whichever of those windows are open or closed. Each of them shows how far it has
    come and can pause it, and none can start the same download beside it.

    Paused, what has arrived is kept, and "Carry on" goes on from there."""

    progress = pyqtSignal(str, object, object)  # name, bytes so far, bytes in all
    finished = pyqtSignal(str, str)   # name, and how it ended: "" installed, PAUSED, or
    #                                   what went wrong, in words
    over = pyqtSignal(str, str)       # the same, from the thread that did the work
    PAUSED = "paused"

    def __init__(self):
        super().__init__()
        self.name = ""          # the model being downloaded, or ""
        self.download = None    # its models.Download
        self.done = self.total = 0
        self.told_at = 0.0
        self.announce = lambda text, kind="info": None  # the tray's notices
        self.over.connect(self.on_over)

    def start(self, name: str) -> str:
        """Start downloading a model, or carry on with one that was paused. Returns why
        it can't be started, in words, or ""."""
        known = models.BY_NAME.get(name)
        if known is None:
            return "This model can't be downloaded from here."
        if self.name:
            return ("Another model is being downloaded. This one can be started when that "
                    "is done, or paused.")
        problem = models.room_problem(config.MODEL_DIR, known)
        if problem:
            return problem

        def tell(done, total):  # a few times a second is plenty for the windows
            now = time.monotonic()
            if done >= total or now - self.told_at > 0.25:
                self.told_at = now
                self.done, self.total = done, total
                self.progress.emit(name, done, total)

        download = models.Download(known, config.MODEL_DIR, progress=tell)
        self.name, self.download, self.done, self.total = name, download, 0, 0

        def work():
            try:
                download.run()
                problem = ""
            except models.Cancelled:
                problem = self.PAUSED
            except models.Failed as e:
                problem = str(e)
            except Exception as e:  # never leave a window saying "Downloading" for ever
                problem = f"Something went wrong: {e}"
            self.over.emit(name, problem)

        threading.Thread(target=work, daemon=True).start()
        print(f"model {name}: download started", flush=True)
        return ""

    def pause(self) -> None:
        """Stop the download soon. What has arrived is kept."""
        if self.download is not None:
            self.download.cancel()

    def pausing(self) -> bool:
        return self.download is not None and self.download.cancelled

    def on_over(self, name: str, problem: str) -> None:
        self.name, self.download = "", None
        print(f"model {name}: " + (problem or "installed"), flush=True)
        label = short_name(model_label(name)[1])
        if not problem:
            # Said whether or not a window is open: a long download is not watched.
            self.announce(f"{label} is installed.", "info")
        elif problem != self.PAUSED:
            # Said whichever windows are open: one that shows downloads may be showing
            # another model's, and this one's failure would then be said nowhere.
            self.announce(f"{label} could not be downloaded. {problem}", "problem")
        self.finished.emit(name, problem)


_downloads = None


def downloads() -> Downloads:
    """The one Downloads there is, made when it is first wanted."""
    global _downloads
    if _downloads is None:
        _downloads = Downloads()
    return _downloads


class ModelsWindow(Window):
    """Install and remove models. A download carries on with the window closed."""

    shows_downloads = True  # a download that fails is said here, not in a notice as well

    def __init__(self, engine: Engine, changed, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.hub = hub or Hub()
        self.changed = changed  # called when a model has been added or removed
        self.downloads = downloads()
        self.downloads.progress.connect(self.on_progress)
        self.downloads.finished.connect(self.on_finished)
        self.setWindowTitle("Models")
        alt = Letters()
        layout = QVBoxLayout(self)
        note = QLabel("Parakeet Unified is the best of the models so far, and the one to "
                      "use. Of the others, the bigger make fewer mistakes but take longer "
                      "after each phrase. Models are downloaded from huggingface.co and "
                      "kept on this computer. The Parakeet models are of a different kind "
                      "from the rest, which are all Whisper: quicker, English only, and "
                      "they can't be shown the text before the cursor.")
        note.setWordWrap(True)
        layout.addWidget(note)
        # The list scrolls: there are more models than a small screen has room for.
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setColumnStretch(0, 1)
        self.grid.setHorizontalSpacing(14)
        # Room for "Downloading: 40%  (650 MB of 1.6 GB)", whatever the size of the text.
        self.grid.setColumnMinimumWidth(2, self.fontMetrics().horizontalAdvance(
            "Downloading: 100%  (1000 MB of 1000 MB)") + 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.space = QLabel()
        layout.addWidget(self.space)
        close = QPushButton(alt("Close"))
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.rows = {}    # name -> its label, size, status and two buttons
        self.does = {}    # name -> what its first button does as things stand
        self.status = {}  # name -> the label that says "Installed", "Downloading: 40%"...
        self.refresh()
        self.ensurePolished()
        # Wide enough for the longest name on one line, where the screen is: on a
        # narrower one the names wrap, and the buttons stay in view.
        metrics, gap = self.fontMetrics(), self.grid.horizontalSpacing()
        names = max((metrics.horizontalAdvance(model_label(name)[1]) for name in self.rows),
                    default=200)
        buttons = close.sizeHint().width() * 2 + 40
        width = (names + metrics.horizontalAdvance("1000 MB") + self.grid.columnMinimumWidth(2)
                 + buttons + 4 * gap + scroll.verticalScrollBar().sizeHint().width() + 56)
        row_height = close.sizeHint().height() + max(4, self.grid.verticalSpacing())
        height = len(self.rows) * row_height + note.heightForWidth(width - 40) + 150
        screen = QApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            width, height = min(width, room.width() - 24), min(height, room.height() - 72)
        dress(self, (width, height))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def names(self) -> list:
        """The models that can be downloaded, then any others that are here."""
        known = [k.name for k in models.KNOWN]
        return known + [n for n, _ in available_models(config.MODEL_DIR) if n not in known]

    def in_use(self, name: str) -> str:
        """Why a model can't be removed, or "" if it can."""
        if name == (self.engine.settings.model or config.AWAKE_MODEL):
            return "in use for dictation"
        if name == config.WAKE_MODEL:
            return "kept for the spelling box, beside a Parakeet model"
        return ""

    def build(self, names: list) -> None:
        """Make a row for each model. Done when the window is made, and again only when
        the list of models itself changes: at other times the rows are changed where they
        stand, so that the button with the keyboard is still there after it is pressed."""
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)  # gone from view now, not a moment later
                widget.deleteLater()
        self.rows, self.status = {}, {}
        for at, name in enumerate(names):
            label, size, status = QLabel(model_label(name)[1]), QLabel(), QLabel()
            label.setWordWrap(True)  # on a narrow screen: wrapped, not cut or scrolled away
            label.setMinimumWidth(self.fontMetrics().horizontalAdvance("Distil medium: quicker "))
            status.setWordWrap(True)
            button, second = QPushButton(), QPushButton("Discard")
            button.clicked.connect(lambda _=False, name=name: self.on_button(name))
            second.clicked.connect(lambda _=False, name=name: self.on_discard(name))
            self.grid.addWidget(label, at, 0)
            self.grid.addWidget(size, at, 1,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(status, at, 2)
            self.grid.addWidget(button, at, 3)
            self.grid.addWidget(second, at, 4)
            self.rows[name] = (label, size, status, button, second)
            self.status[name] = status
        self.grid.setRowStretch(len(names), 1)

    def refresh(self) -> None:
        """Say how each model stands, from what is on the disk."""
        names = self.names()
        if names != list(self.rows):
            self.build(names)
        fetching = self.downloads.name
        for name in names:
            label, size, status, button, second = self.rows[name]
            known = models.BY_NAME.get(name)
            installed = models.is_installed(config.MODEL_DIR, name)
            part = models.part_size(config.MODEL_DIR, name)
            path = os.path.join(config.MODEL_DIR, name)
            label.setText(model_label(name)[1])
            size.setText(models.size_text(models.folder_size(path) if installed
                                          else known.megabytes * 1e6 if known else 0))
            discard = False
            if name == fetching:
                if self.downloads.pausing():
                    status.setText("Pausing…")
                elif not status.text().startswith(("Downloading", "Checking")):
                    status.setText("Downloading…")
                does, enabled = "Pause", not self.downloads.pausing()
            elif installed:
                why = self.in_use(name)
                missing = (models.kind(config.MODEL_DIR, name) == "transducer"
                           and not models.transducers_usable())
                status.setText("Can't be used yet: run the installer again to add Parakeet "
                               "support" if missing
                               else "Installed" + (f", {why}" if why else ""))
                does, enabled = "Remove", not why
            else:
                needs = (known is not None and known.marker in models.TRANSDUCERS
                         and not models.transducers_usable())
                status.setText("Can't be used yet: run the installer again to add Parakeet "
                               "support" if needs
                               else f"Paused, partly downloaded ({models.size_text(part)})"
                               if part else "")
                does, enabled = ("Carry on" if part else "Install"), not fetching and not needs
                discard = bool(part)
            self.does[name] = does
            short = short_name(model_label(name)[1])
            button.setText(does)
            button.setEnabled(enabled)
            # Thirteen buttons that all say "Install" are told apart, by a screen reader
            # and by a tool that presses buttons by voice, by the model each is for.
            button.setAccessibleName(f"{does} {short}")
            second.setVisible(discard)
            second.setEnabled(not fetching)
            second.setAccessibleName(f"Discard what was downloaded of {short}")
        self.space.setText(
            f"Free disk space: {models.size_text(models.free_space(config.MODEL_DIR))}")

    def on_button(self, name: str) -> None:
        """A row's first button: what it does is what it says just now."""
        does = self.does.get(name, "")
        if does == "Pause":
            self.downloads.pause()
            self.refresh()
        elif does == "Remove":
            self.on_remove(name)
        elif does in ("Install", "Carry on"):
            self.on_install(name)

    def on_install(self, name: str) -> None:
        problem = self.downloads.start(name)
        self.refresh()
        if problem:
            tell(self, problem)

    def on_progress(self, name: str, done, total) -> None:
        label = self.status.get(name)
        if label is None or not total or self.downloads.name != name or self.downloads.pausing():
            return
        if done >= total:
            label.setText("Checking…")
        else:
            label.setText(f"Downloading: {int(100 * done / total)}%  "
                          f"({models.size_text(done)} of {models.size_text(total)})")

    def busy(self) -> bool:
        """Nothing of this window's own is ever under way: a download goes on in
        Downloads, whichever windows there are."""
        return False

    def on_finished(self, name: str, problem: str) -> None:
        self.refresh()
        self.changed()
        if problem and problem != Downloads.PAUSED and self.isVisible():
            tell(self, problem)

    def on_remove(self, name: str) -> None:
        label = model_label(name)[1]
        sure = ask(self, f"Remove this model?\n\n{label}\n\n"
                   + ("It can be installed again from here." if name in models.BY_NAME
                      else "It can't be installed again from here."), careful=True)
        if not sure or self.in_use(name):
            return
        try:
            models.remove(config.MODEL_DIR, name)
            print(f"model {name}: removed", flush=True)
        except OSError as e:
            tell(self, f"It could not be removed: {e.strerror or e}")
        self.refresh()
        self.changed()

    def on_discard(self, name: str) -> None:
        if not ask(self, "Discard what has been downloaded of this model?\n\n"
                         f"{model_label(name)[1]}\n\nInstalling it later starts from the "
                         "beginning.", careful=True):
            return
        try:
            models.discard_part(config.MODEL_DIR, name)
        except OSError as e:
            tell(self, f"It could not be removed: {e.strerror or e}")
        self.refresh()


class VoiceBridge(QObject):
    level = pyqtSignal(float, int, float)  # while recording: how loud, seconds so far,
    #                                  and how many seconds it has been quiet since the
    #                                  passage could first have been read to its end
    recorded = pyqtSignal(str)       # the recording is done; what went wrong, or ""
    listed = pyqtSignal(list)        # the models that can be tried
    doing = pyqtSignal(str)          # what the test is busy with
    result = pyqtSignal(object)      # one model's result
    finished = pyqtSignal(bool)      # the test is over; whether it ran to the end


class VoiceTestWindow(Window):
    """Read a passage aloud once, and see how each model does on your own voice.
    See voicetest.py.

    Three tabs, one for each step, so that each has the whole window: the text to read,
    the models to try, and how they did.

    A test takes a quarter of an hour or more, so it is not tied to the window: closed,
    the test goes on, and a notice says when it is done. A recording is another matter:
    nobody reads to a closed window, so closing ends it, and what was kept before stays."""

    READING, CHOOSING, RESULTS = range(3)

    def __init__(self, engine: Engine, changed=lambda: None, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.changed = changed  # called when the model for dictation was changed from here
        self.hub = hub or Hub()
        self.setWindowTitle("Test the models on my voice")
        self.samples = voicetest.load_recording()
        self.results = []
        self.candidates = []
        self.tickers = []    # the "Tick all" and "Untick all" buttons
        self.ended = ""      # how the last test ended, if not well
        self.shared = []     # the slips every model made alike: the reader's
        self.pressed = None  # the row the mouse went down on, and whether it was ticked
        self.recording = False
        self.running = False
        self.given_up = False  # the recording under way was closed on, not finished
        self.stop = threading.Event()
        self.bridge = VoiceBridge()
        self.bridge.level.connect(self.on_level)
        self.bridge.recorded.connect(self.on_recorded)
        self.bridge.listed.connect(self.on_listed)
        self.bridge.doing.connect(lambda text: self.progress.setText(text))
        self.bridge.result.connect(self.on_result)
        self.bridge.finished.connect(self.on_finished)
        alt = Letters()
        close = QPushButton(alt("Close"))
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
                      "that are easily taken for others, which is where models differ. "
                      "Dictation is switched off while you record. The recording ends by "
                      "itself a few seconds after you finish reading.")
        note.setWordWrap(True)
        inner.addWidget(note)
        # A page that wraps, and scrolls only if it must, at a large size of text or on a
        # small screen: at the usual size all of it is in view, since nobody can scroll
        # and read aloud at once, and at no size is any of it cut off.
        passage = QTextBrowser()
        passage.setPlainText(" ".join(voicetest.PASSAGE))
        passage.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        passage.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        passage.setAccessibleName("The text to read aloud")
        passage.setStyleSheet(f"font-size: {points(self, 1.2)}pt; padding: 6px;")
        inner.addWidget(passage, 1)
        row = QHBoxLayout()
        self.record = QPushButton()
        self.record.clicked.connect(self.on_record)
        self.recorded_note = QLabel()
        self.recorded_note.setWordWrap(True)
        row.addWidget(self.record)
        row.addWidget(self.recorded_note, 1)
        inner.addLayout(row)
        self.tabs.addTab(page, "1. Read aloud")

        # 2. Which models. The list has the whole tab, so all of them can be seen.
        page = QWidget()
        inner = QVBoxLayout(page)
        note = QLabel("Every model ticked here hears that one recording, one after the "
                      "other. The more that are ticked, the longer the test takes. The "
                      "space bar ticks and unticks the row that has the keyboard.")
        note.setWordWrap(True)
        inner.addWidget(note)
        self.choices = QListWidget()
        self.choices.setAccessibleName("Models to try")
        self.choices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.choices.itemChanged.connect(lambda _: self.refresh())
        self.choices.itemPressed.connect(self.on_choice_pressed)
        self.choices.itemClicked.connect(self.on_choice_clicked)
        inner.addWidget(self.choices, 1)
        row = QHBoxLayout()
        for text, ticked in (("Tick all", True), ("Untick all", False)):
            button = QPushButton(alt(text))
            button.clicked.connect(lambda _, ticked=ticked: self.tick_all(ticked))
            row.addWidget(button)
            self.tickers.append(button)
        self.ticked_note = QLabel()
        row.addWidget(self.ticked_note, 1)
        inner.addLayout(row)
        self.both = QCheckBox(alt("Try Whisper both ways, with \"quicker recognition\" and "
                                  "without  (takes a good deal longer)"))
        self.both.clicked.connect(self.list_candidates)
        inner.addWidget(self.both)
        self.tabs.addTab(page, "2. What to try")

        # 3. How each one did.
        page = QWidget()
        inner = QVBoxLayout(page)
        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName("Results, best first")
        self.table.setHorizontalHeaderLabels(
            ["Model", "Words wrong", "Near misses", "Time for a phrase"])
        self.table.horizontalHeaderItem(2).setToolTip(
            "Words it got right, but was less than 90% sure of: the ones that could as "
            "easily have come out wrong. Compare them between forms of the same "
            "model, not between different ones: each measures its own sureness in "
            "its own way.")
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setTabKeyNavigation(False)  # Tab leaves the table: the arrows move in it
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self.show_slips)
        inner.addWidget(self.table, 3)
        row = QHBoxLayout()
        self.advice = QLabel()
        self.advice.setWordWrap(True)
        self.use = QPushButton()  # puts the suggested model to use
        self.use.clicked.connect(self.on_use)
        self.use.setVisible(False)
        row.addWidget(self.advice, 1)
        row.addWidget(self.use, 0, Qt.AlignmentFlag.AlignTop)
        inner.addLayout(row)
        self.slips = QPlainTextEdit()
        self.slips.setReadOnly(True)
        self.slips.setTabChangesFocus(True)
        self.slips.setAccessibleName("The words the chosen model got wrong")
        self.slips.setPlaceholderText("Choose a row to see the words it got wrong.")
        inner.addWidget(self.slips, 1)
        self.tabs.addTab(page, "3. Results")

        # Under the tabs, so the test can be started, watched and stopped from any of them.
        row = QHBoxLayout()
        self.run = QPushButton()
        self.run.clicked.connect(self.on_run)
        self.progress = QLabel()
        self.progress.setWordWrap(True)
        close.clicked.connect(self.close)
        row.addWidget(self.run)
        row.addWidget(self.progress, 1)
        row.addWidget(close)
        layout.addLayout(row)
        dress(self, roomy(self, 760, 600))
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
        self.run.setText("Stop the test" if self.running else "Run the test")
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
        # Ends a recording that is under way. A recording ended this way was given up,
        # not finished: it is not put in place of the one already kept. A test that is
        # running goes on, as a download does: see on_finished().
        if self.recording:
            self.given_up = True
            self.stop.set()
        super().closeEvent(event)

    def busy(self) -> bool:
        """Whether a test is running: that goes on with the window closed."""
        return self.running

    # ---- which models ----------------------------------------------------------------------
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
        self.given_up = False
        self.engine.hold()
        self.recorded_note.setText("Recording\u2026 read the text, then press \"Stop "
                                   "recording\", or just stop: it ends by itself.")
        self.refresh()
        threading.Thread(target=self.record_work, daemon=True).start()

    def record_work(self) -> None:
        import numpy as np
        try:
            recorder = audio.open_microphone(self.engine.settings.microphone)
        except Exception as e:
            self.bridge.recorded.emit(microphone_trouble(e))
            return
        frames, nbytes, started = [], config.FRAME * 2, time.monotonic()
        loudest, count, stopped = 0.0, 0, ""
        ear = reading.Ear(self.engine.boost)  # tells speech from the room, for the quiet at the end
        spoke, heard = started, False
        try:
            while not self.stop.is_set() and time.monotonic() - started < voicetest.LONGEST_SECONDS:
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    stopped = stopped_why(recorder)
                    break
                frame = np.frombuffer(data, dtype=np.int16)
                frames.append(frame)
                ear.feed(frame)
                now = time.monotonic()
                if ear.ready and ear.speaking:
                    spoke, heard = now, True
                # Somebody who can't reach the button isn't left recording for six
                # minutes: a long quiet, once the text could have been read, is the end.
                # Only if a voice was heard at all, though: one too quiet to be told
                # from the room is not cut off in the middle of its reading.
                if heard and voicetest.read_out(now - started, now - spoke):
                    break
                loudest = max(loudest, float(np.max(np.abs(frame.astype(np.int32)))) / 32768)
                count += 1
                if count == 10:  # five times a second
                    quiet = (now - spoke if heard and now - started >= voicetest.least_seconds()
                             else 0.0)
                    self.bridge.level.emit(loudest, int(now - started), quiet)
                    loudest, count = 0.0, 0
        finally:
            recorder.close()
        if self.given_up:
            self.bridge.recorded.emit("")  # the window was closed on it: what was kept stays
            return
        if stopped:
            # Cut short by the microphone, not finished by the reader: it is not kept in
            # place of a whole one.
            self.bridge.recorded.emit(
                stopped + " The recording was not kept"
                + (": the one from before still is." if self.samples is not None else "."))
            return
        if len(frames) < 5 * config.RATE // config.FRAME:
            self.bridge.recorded.emit("That was too short to test with. Read the whole text.")
            return
        samples = np.concatenate(frames)
        try:
            voicetest.save_recording(samples)
        except OSError as e:
            self.bridge.recorded.emit(f"The recording could not be kept: {e.strerror or e}")
            return
        self.samples = samples
        self.bridge.recorded.emit("")

    def on_level(self, loudest: float, seconds: int, quiet: float = 0.0) -> None:
        if self.recording:
            bar = "\u2588" * min(12, round(loudest * 24))
            left = voicetest.QUIET_END - quiet
            ending = (f"   Ends in {int(left) + 1} s if you have finished." if quiet >= 2.0
                      else "   Ends by itself when you have read it all.")
            self.recorded_note.setText(
                f"Recording\u2026 {seconds // 60}:{seconds % 60:02d}   {bar}{ending}")

    def on_recorded(self, problem: str) -> None:
        self.recording = False
        self.engine.unhold()
        self.refresh()
        if problem and self.isVisible():
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
        print(f"voice test: {len(sounds)} phrases, {len(chosen)} models", flush=True)
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
        if not self.isVisible():
            # It went on with the window closed, so nobody is looking: say that it is done.
            pick = voicetest.suggestion(self.results) if finished else ""
            self.hub.announce(
                ("The voice test has finished." if finished else "The voice test stopped "
                 "before the end.") + (f" Suggested: {pick}." if pick else "")
                + " \"Test the models on my voice\", in Settings, shows how each did.")

    def on_use(self) -> None:
        """Put the suggested model to use for dictation, the way it was tried."""
        pick = voicetest.suggested(self.results)
        if pick is None or pick.where != "here" or not models.kind(config.MODEL_DIR, pick.name):
            return
        settings = self.engine.settings
        if (models.kind(config.MODEL_DIR, pick.name) == "whisper"
                and settings.enabled("quick_listening") != pick.quick):
            settings.set("quick_listening", pick.quick)  # the way of listening it was tried with
            self.engine.setting_changed("quick_listening")
        if pick.name != (settings.model or config.AWAKE_MODEL):
            self.engine.set_model(pick.name)
        self.changed()
        self.fill_table("")

    def fill_table(self, note: str) -> None:
        """Show the results, best first: fewest words wrong, then quickest.

        Slips that every model made alike were in the reading, and are left out of
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
        pick = voicetest.suggested(self.results)
        advice = [note] if note else []
        if pick is not None and not self.running:
            advice.append(f"Suggested: {pick.title}. It is the quickest of those about as "
                          "accurate as the best.")
        # A button that puts the suggestion to use, where it is a model on this computer:
        # otherwise it had to be found again by hand in Settings.
        usable = (pick is not None and not self.running and pick.where == "here"
                  and bool(models.kind(config.MODEL_DIR, pick.name)))
        self.use.setVisible(usable)
        if usable:
            settings = self.engine.settings
            in_use = pick.name == (settings.model or config.AWAKE_MODEL) and (
                models.kind(config.MODEL_DIR, pick.name) != "whisper"
                or settings.enabled("quick_listening") == pick.quick)
            self.use.setEnabled(not in_use)
            self.use.setText("In use for dictation" if in_use else "Use it for dictation")
            self.use.setAccessibleName(
                f"{pick.title}: " + ("in use for dictation" if in_use else "use it for dictation"))
        if any(result.where == "team" for result in self.results):
            advice.append("To dictate with a model checked by others, tick \"Second "
                          "opinions\" in Settings: it is experimental.")
        if any(result.near >= 0 for result in self.results):
            advice.append("A near miss is a word that came out right, but that the model "
                          "was less than 90% sure of. The numbers compare between forms of the "
                          "same model, not between different ones.")
        if self.shared:
            words = sum(voicetest.score(voicetest.words(said), voicetest.words(heard))[0]
                        for said, heard in self.shared)
            advice.append(
                f"Not counted: {words} word{'s' if words != 1 else ''} that every model "
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


class ReadWindow(Window):
    """Read sentences aloud, one at a time. Each one's sound is kept beside its text,
    which is what a model could be retrained on. See reading.py.

    Half an hour of reading is a long sitting. So nothing has to be pressed: it moves on
    when a model has heard the sentence to its end. It can be paused for a rest,
    pauses by itself when the reader goes away, and always says how far there is to go.

    One button starts, pauses and carries on. Paused, nothing is held: the microphone is
    closed and dictation is back, so closing the window is all the stopping there is.

    The space bar is the reader's key. So the buttons that have to do with the sentence
    never take the keyboard, and the rest take it only by the Tab key or their Alt-letter,
    never by a click: then the space bar presses what was tabbed to, as it does anywhere."""

    BUILT_IN, OWN = range(2)
    IDLE_SECONDS = 60  # with nothing read or pressed for this long, it pauses by itself
    ASTRAY_TIMES = 2   # after this many readings that didn't match, keeping it as read is offered

    MORE = ("It moves on by itself when it has heard you reach the end of the sentence. The "
            "space bar moves on at once, or passes over a sentence you haven't read. If you "
            "stumble, start the sentence again: A does that too. Backspace goes back one. "
            "P pauses for a rest: your place is kept, today and for another day, and the "
            "microphone is closed while you rest.\n\nEach sentence's sound is kept on this "
            "computer beside its text, as material for retraining a model to your voice. "
            "Nothing goes to the cloud. {heard} With nothing read for a minute it pauses by "
            "itself.")

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Read aloud for training")
        self.astray = 0          # how many times running this sentence didn't sound like itself
        self.offered = False     # its last reading is held, to be kept as read if wanted
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
        alt = Letters()
        close = QPushButton(alt("Close"))
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        note = QLabel("Read each sentence aloud, the way you dictate, and it moves on by "
                      "itself. Pause for a rest whenever you like: your place is kept. "
                      "Dictation is switched off while you read.")
        note.setWordWrap(True)
        more = QPushButton(alt("How it works"))
        more.clicked.connect(self.on_more)
        row.addWidget(note, 1)
        row.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        # Said when the window opens, not after half an hour's reading: whether this
        # computer has the memory that training on the recordings will want.
        self.memory = QLabel()
        self.memory.setWordWrap(True)
        self.memory.setVisible(False)
        layout.addWidget(self.memory)
        row = QHBoxLayout()
        label = QLabel(alt("Read from:"))
        self.source = Chooser()
        label.setBuddy(self.source)
        self.source.setAccessibleName("Read from")
        self.source.addItem("The sentences that come with it")
        self.source.addItem("A text of my own")
        self.source.activated.connect(self.on_source)
        self.choose = QPushButton(alt("Choose my text\u2026"))
        self.choose.clicked.connect(self.on_choose)
        row.addWidget(label)
        row.addWidget(self.source)
        row.addWidget(self.choose)
        row.addStretch()
        self.by_itself = QCheckBox(alt("Move on by itself"))
        self.by_itself.setChecked(True)
        explain(self.by_itself,
                "At each pause, the model you dictate with hears the sentence so far. When "
                "it has heard it to the end, the sound is kept and the next sentence comes up. "
                "Unticked, each sentence waits for Next or the space bar.")
        self.by_itself.toggled.connect(self.on_by_itself)
        row.addWidget(self.by_itself)
        layout.addLayout(row)
        # One sentence, large: it is read from a little way off, with the eyes on nothing else.
        self.sentence = QLabel()
        self.sentence.setWordWrap(True)
        self.sentence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sentence.setMinimumHeight(round(170 * grown(self)))
        self.sentence.setAccessibleName("The sentence to read")
        layout.addWidget(self.sentence, 1)
        self.bar = QProgressBar()  # how far through the text
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setAccessibleName("How far through the text")
        layout.addWidget(self.bar)
        row = QHBoxLayout()
        self.volume = VolumeBar()  # the voice against the room, as it is spoken
        self.volume.setFixedWidth(190)
        self.volume_note = QLabel()  # and in words, for the sentence as a whole
        # Room for the longest of the verdicts, in bold, at whatever size the text is.
        self.volume_note.setMinimumWidth(max(
            self.volume_note.fontMetrics().horizontalAdvance(words) for words in reading.ADVICE)
            * 115 // 100 + 8)
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
            # Each has a key of its own, said on it, and never takes the keyboard: the
            # space bar is the reader's, wherever the mouse last clicked.
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(button)
        self.once_more.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # it has no key: Tab reaches it
        layout.addLayout(row)
        row = QHBoxLayout()
        self.totals = QLabel()
        self.totals.setWordWrap(True)
        folder = QPushButton(alt("Open the folder"))
        folder.clicked.connect(self.on_folder)
        close.clicked.connect(self.close)
        row.addWidget(self.totals, 1)
        row.addWidget(folder)
        row.addWidget(close)
        layout.addLayout(row)
        # Reached by Tab and by their Alt-letters, but not by a click: a click on one of
        # them doesn't take the space bar away from the reading. The window itself has
        # the keyboard to begin with, and has it back when one of them has been used,
        # or when it is clicked anywhere else.
        for part in (more, self.source, self.choose, self.by_itself, folder, close):
            part.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # The space bar and Enter are seen to in keyPressEvent, so that a button that was
        # tabbed to is pressed by them, and the reading has them the rest of the time.
        for key, action in ((Qt.Key.Key_Backspace, self.on_back),
                            (Qt.Key.Key_A, self.on_again), (Qt.Key.Key_P, self.on_pause_key)):
            QShortcut(QKeySequence(key), self).activated.connect(action)
        self.idle = QTimer(self)  # runs while the window is open: see showEvent()
        self.idle.timeout.connect(self.check_idle)
        dress(self, roomy(self, 760, 480))
        if (not reading.unread(SENTENCES, self.kept, self.kept.rounds(self.NAMES[self.BUILT_IN]))
                and reading.own_text()[0]):
            self.source.setCurrentIndex(self.OWN)  # the ones that come with it are all read
        self.fill()
        self.refresh()

    def keyPressEvent(self, event) -> None:
        """The space bar and Enter move on, start a sitting and end a rest. They come
        here only when nothing that was tabbed to has taken them: a button or a tick box
        that has the keyboard is pressed by them instead, as anywhere else."""
        key, at = event.key(), self.focusWidget()
        if key == Qt.Key.Key_Space or (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                                       and (at is None or at is self)):
            if not event.isAutoRepeat():  # a key held down is one press
                self.on_next()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        self.idle.start(1000)
        self.check_memory()
        super().showEvent(event)
        self.setFocus()  # the space bar starts the reading, whatever would be tabbed to first

    def hideEvent(self, event) -> None:
        self.idle.stop()  # nothing to watch for while the window is closed
        super().hideEvent(event)

    def on_more(self) -> None:
        # Each sentence is heard by whatever does the recognising, to tell when the end
        # has been reached: so with another computer set to do that, it hears them too.
        elsewhere = self.engine.settings.remote
        heard = ("As another computer of yours does your recognising, each sentence is sent "
                 "to it to be heard, encrypted, and is not kept there."
                 if elsewhere.get("on") and elsewhere.get("address") else
                 "It is all done on this computer.")
        tell(self, self.MORE.format(heard=heard), "information")
        self.setFocus()  # the keys are the reader's again

    def check_memory(self) -> None:
        """Say now, in words, if training looks to want more memory than there is: before
        half an hour is spent reading for it."""
        try:
            problem = training.memory_problem()
        except Exception:
            problem = ""
        self.memory.setText(
            f"A word before you read: {problem} You can read now all the same, and train "
            "when there is room, or on another computer." if problem else "")
        self.memory.setVisible(bool(problem))

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
        self.setFocus()  # the keys are the reader's again

    def on_choose(self) -> None:
        self.setFocus()  # when the choosing is over, the keys are the reader's again
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
                    self.kept.set_rounds(self.NAMES[self.OWN], 1)  # a new text: its first reading
                    plural = "s" if len(found) != 1 else ""
                    tell(self, f"{len(found)} sentence{plural} can be read."
                         + (f" {left_out} were left out: any with figures or unusual marks "
                            "in them, which a model may write another way, and any that "
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
        # The sentence to read is large and upright. What is said in its place between
        # sentences is smaller and slanted, in the same full colour: told apart by its
        # shape, never by being faint, which on a dark desktop made it all but invisible.
        if live and self.current:
            text, size, slant = self.current, points(self, 1.8), "normal"
        else:
            size, slant = points(self, 1.15), "italic"
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
            f"font-size: {size}pt; font-style: {slant}; color: palette(text); padding: 16px;"
            "border-radius: 4px; border: 1px solid palette(mid); background: palette(base);")
        if not live:
            self.volume.clear()
            self.volume_note.setText("")
            self.volume.setAccessibleDescription("")
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
        self.setFocus()  # the keys are the reader's again

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
            # Somebody reading is somebody here, whether or not what they read is taken
            # for the sentence: it doesn't pause for want of them while they speak.
            self.acted = time.monotonic()
            self.spoken += 1
            self.reached, self.loudest = max(self.reached, above), max(self.loudest, peak)
        if self.spoken >= self.SPOKEN:
            words, colour = reading.level_verdict(self.reached, self.loudest)
            self.volume_note.setText(words)
            self.volume_note.setStyleSheet("color: rgb(%d, %d, %d); font-weight: bold;" % colour)
            self.volume.setAccessibleDescription(words)

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
        elif (self.auto and self.current and not self.hinted and not self.offered
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
            self.bridge.ended.emit(microphone_trouble(e))
            return
        nbytes, loudest, peak, count, told = config.FRAME * 2, 0.0, 0, 0, False
        checking = threading.Event()  # a model is hearing the sentence so far
        problem = ""
        try:
            while not stop.is_set():
                data = recorder.read(nbytes)
                if len(data) < nbytes:
                    problem = stopped_why(recorder) + " Your place is kept."
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
            problem = "The reading had to stop. Your place is kept, and the log says why."
        finally:
            recorder.close()
        self.bridge.ended.emit(problem)

    def check(self, epoch: int, mark: int, sound, checking) -> None:
        """Have the model in use hear the sentence so far. On a thread of its own:
        the microphone is not kept waiting."""
        import numpy as np
        try:
            heard = self.engine.hear_reading(sound.astype(np.float32) / 32768.0)
        except Exception as e:
            print(f"reading: the model could not check a sentence: {e}", flush=True)
            heard = None
        checking.clear()
        self.bridge.heard.emit(epoch, mark, heard)

    # ---- reading ---------------------------------------------------------------------------
    def on_heard(self, epoch: int, mark: int, heard) -> None:
        """A model has heard the sentence so far, at a pause. Is it done?"""
        if epoch != self.epoch or not (self.reading and self.listening and self.current):
            return  # that was of a sentence since ended or started again
        if heard is None:
            self.said.setText("The model couldn't check that. Press the space bar when "
                              "you have read the sentence.")
            return
        outcome = reading.verdict(self.current, heard)
        if outcome == reading.DONE:
            self.acted = time.monotonic()
            self.awaiting.append(self.current)
            self.order("accept", mark)
            self.advance()
            self.refresh()
        elif outcome == reading.ASTRAY and not self.offered:
            self.astray += 1
            if self.astray < self.ASTRAY_TIMES:
                self.order("again")
                self.said.setText("That didn't sound like this sentence, so it wasn't kept. "
                                  "Read it again, or press the space bar to pass over it.")
            else:
                # The model is what training is to put right: somebody whose speech it
                # takes wrongly would be sent round this sentence for ever. So this
                # reading is held, not thrown away, and the space bar keeps it.
                self.offered = True
                self.said.setText("That didn't sound like this sentence to the model "
                                  "either. If you read it as it is written, press the space "
                                  "bar to keep it as you read it. To read it once more, "
                                  "press A first.")

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
        self.astray, self.offered = 0, False  # a new sentence: nothing is held against it

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
            self.offered = False  # the reading that was held is given up for a new one
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
        self.astray, self.offered = 0, False
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


class TrainWindow(Window):
    """Retrain a model to one voice, from sentences read aloud: which folder of them,
    which model to start from, and what the result is to be called. See training.py.

    It takes an hour or more, so the work is not tied to this window. It runs by itself,
    at low priority, and goes on if the window or the app is closed; opened again, the
    window shows how far it has come. It can be stopped, and carried on later from the
    last pass it finished."""

    shows_downloads = True  # a download that fails is said here, not in a notice as well

    def __init__(self, engine: Engine, refill=lambda: None, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.refill = refill          # the list of models in Settings gains the new one
        self.hub = hub or Hub()
        self.setWindowTitle("Train on my voice")
        self.job = training.latest()  # a run that is going, or the last there was
        self.install = training.Install()  # the installing of the training tools
        self.folder = reading.FOLDER
        self.counted = (0, 0.0)       # sentences and seconds of sound in the folder
        self.was = ""                 # the state last shown, to notice a run finishing
        self.held_at = None           # the state at which the stopped runs were last looked for
        self.asked_to_stop = False
        self.fetching = None          # while Parakeet v2 is downloaded first: see fetch_cutter()
        self.log = ""                 # the log that "Open the log" opens, as things stand
        self.downloads = downloads()
        self.downloads.finished.connect(self.on_downloaded)
        alt = Letters()
        close = QPushButton(alt("Close"))
        layout = QVBoxLayout(self)
        note = QLabel(
            "Retrains a model on the sentences you have read aloud, so that it knows your "
            "voice. Experimental. It takes about an hour and a good deal of memory, and it "
            "runs by itself: you can close this window, and dictation goes on working, a "
            "little slower. The new model then appears among the models under the name you "
            "give it. One sentence in six is kept out of the training, to test the result on.")
        note.setWordWrap(True)
        layout.addWidget(note)
        # Said when the window opens, in words, and not first at "Start": whether there
        # is the memory a run wants.
        self.memory = QLabel()
        self.memory.setWordWrap(True)
        self.memory.setVisible(False)
        layout.addWidget(self.memory)
        form = QGridLayout()
        self.where = QLineEdit()
        self.where.setReadOnly(True)
        self.choose = QPushButton(alt("Choose a folder\u2026"))
        self.choose.clicked.connect(self.on_choose)
        self.there = QLabel()
        self.there.setWordWrap(True)
        self.bases = Chooser()
        for base in training.BASES:
            self.bases.addItem(base.label, base.key)
        self.name = QLineEdit("My voice")
        self.name.setMaxLength(40)
        self.name.textChanged.connect(lambda _: self.refresh())
        # Each box is named by the label beside it, for a screen reader, and Alt and the
        # label's letter goes to it.
        for at, (words, box, named) in enumerate((
                ("Sentences:", self.where, "The folder of sentences read aloud"),
                ("Start from:", self.bases, "The model to start from"),
                ("Name:", self.name, "A name for the new model"))):
            label = QLabel(alt(words))
            label.setBuddy(box)
            box.setAccessibleName(named)
            form.addWidget(label, (0, 2, 3)[at], 0)
        form.addWidget(self.where, 0, 1)
        form.addWidget(self.choose, 0, 2)
        form.addWidget(self.there, 1, 1, 1, 2)
        form.addWidget(self.bases, 2, 1, 1, 2)
        form.addWidget(self.name, 3, 1, 1, 2)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.bar.setAccessibleName("How far the work has come")
        layout.addWidget(self.bar)
        self.headline = QLabel()
        self.headline.setStyleSheet("font-weight: bold;")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        # Room for four lines at the least, so the window doesn't jump as the words
        # change: more when there is more to say. What it says can be selected and
        # copied: it may be the reason a run failed.
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail.setMinimumHeight(4 * self.detail.fontMetrics().lineSpacing() + 2)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                            | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        layout.addWidget(self.detail, 1)
        row = QHBoxLayout()
        self.go = QPushButton()  # starts, stops and carries on
        self.go.clicked.connect(self.on_go)
        self.halt = QPushButton()  # stops the installing of the tools, or a download
        self.halt.clicked.connect(self.on_halt)
        self.use = QPushButton("Use it for dictation")
        self.use.clicked.connect(self.on_use)
        self.clear = QPushButton()  # removes what stopped runs have left on the disk
        self.clear.clicked.connect(self.on_clear)
        self.open_log = QPushButton(alt("Open the log"))
        self.open_log.clicked.connect(self.on_open_log)
        explain(self.open_log, "Opens what the training, or the installing of its tools, "
                               "wrote down as it went: where the reason is, if it failed.")
        self.held = []
        close.clicked.connect(self.close)
        row.addWidget(self.go)
        row.addWidget(self.halt)
        row.addWidget(self.use)
        row.addWidget(self.clear)
        row.addStretch()
        row.addWidget(self.open_log)
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
        dress(self, roomy(self, 680, 400))

    def showEvent(self, event) -> None:
        self.count()
        self.check_memory()
        self.refresh()
        self.timer.start(1000)
        super().showEvent(event)

    def changeEvent(self, event) -> None:
        """Brought to the front again: sentences may have been read since it was last
        looked at, in the reading window beside it, so they are counted again."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.count()
            self.check_memory()
            self.refresh()

    def check_memory(self) -> None:
        try:
            problem = training.memory_problem()
        except Exception:
            problem = ""
        running = self.job is not None and self.job.running()
        self.memory.setText("" if running or not problem else
                            f"{problem} A run started now would most likely stop for want of it.")
        self.memory.setVisible(bool(self.memory.text()))

    def hideEvent(self, event) -> None:
        if not self.busy():
            self.timer.stop()  # the run goes on by itself
        # While Parakeet v2 is being downloaded the window goes on looking, closed or
        # not: the run is still to be started when that is here.
        super().hideEvent(event)

    def busy(self) -> bool:
        """Whether Parakeet v2 is being downloaded, for a run that is to start after it."""
        return self.fetching is not None

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
        if training.ready():
            self.bar.setRange(0, 1000)
            return False
        fetching = self.install.state()
        for part in (self.choose, self.bases, self.name):
            part.setEnabled(False)
        self.where.setText(self.folder)
        self.there.setText("")
        self.use.setVisible(False)
        self.clear.setVisible(False)
        self.bar.setRange(0, 0 if fetching == "installing" else 1000)  # busy, while it is
        self.bar.setValue(0)
        self.go.setEnabled(fetching != "installing")
        # It can be stopped, where training.py offers a way to stop it.
        self.halt.setVisible(fetching == "installing" and self.install_stopper() is not None)
        self.halt.setText("Stop installing")
        self.halt.setEnabled(True)
        self.show_log(getattr(self.install, "log", "")
                      if fetching in ("installing", "failed", "stopped") else "")
        if fetching == "installing":
            self.headline.setText("Installing the training tools\u2026")
            self.detail.setText((self.install.last_line() or "Starting.")
                                + "\nIt goes on if this window is closed.")
            self.go.setText("Installing\u2026")
        elif fetching == "failed":
            self.headline.setText("The training tools could not be installed.")
            self.detail.setText(f"{self.install.last_line()}\n\"Open the log\" shows the rest.")
            self.go.setText("Try the install again")
        elif fetching == "stopped":
            self.headline.setText("Installing the training tools was stopped.")
            self.detail.setText("What had arrived is kept, in the tools' folder beside the "
                                "app: installing again carries on from it, and removing "
                                "that folder removes it.")
            self.go.setText("Carry on installing the training tools")
        else:
            self.headline.setText("The training tools are not installed on this computer.")
            self.detail.setText(
                "They are a Python of their own with PyTorch and NeMo, about "
                f"{training.TOOLS_GB:g} GB, kept in a folder beside the app: removing that "
                "folder removes them. A run then wants about "
                f"{training.MEMORY_GB} GB of free memory.")
            self.go.setText(f"Install the training tools  ({training.TOOLS_GB:g} GB)")
        return True

    def install_stopper(self):
        """The way training.py offers to stop the installing of the tools, if it has one."""
        for name in ("cancel", "stop"):
            way = getattr(self.install, name, None)
            if callable(way):
                return way
        return None

    def show_log(self, path: str) -> None:
        """Which log "Open the log" opens as things stand: its button is there only while
        there is one."""
        self.log = path if path and os.path.exists(path) else ""
        self.open_log.setVisible(bool(self.log))

    def on_open_log(self) -> None:
        if self.log:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.log))

    def on_halt(self) -> None:
        """Stop the installing of the tools, or the download of Parakeet v2."""
        if self.fetching is not None:
            self.downloads.pause()
        elif self.install.state() == "installing":
            stop = self.install_stopper()
            if stop is not None and ask(self, "Stop installing the training tools? What has "
                                              "arrived so far is kept, and installing "
                                              "again carries on from it."):
                try:
                    stop()
                except Exception as e:
                    tell(self, f"The install could not be stopped: {e}")
        self.refresh()

    def on_install(self) -> None:
        problem = training.room_problem()
        memory = training.memory_problem()
        if problem:
            tell(self, problem)
        elif ask(self, f"This downloads about {training.TOOLS_GB:g} GB from the internet and "
                       "may take a quarter of an hour or more. It can go on while you do "
                       "other things. "
                       + (f"A word first: {memory} " if memory else "")
                       + "Install the training tools?"):
            try:
                self.install.start()
            except OSError as e:
                tell(self, f"The install could not be started: {e.strerror or e}")
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
            headline = "Stopping\u2026"
            detail = ("It was still getting ready, so it ends at once and nothing is lost."
                      if state in getattr(training, "EARLY", ()) else
                      "It stops at the next few sentences, and keeps the passes it has finished.")
        elif problem and state != "done":
            headline, detail = (headline if state else ""), problem
        elif not state:
            detail = ("Ready. Half an hour of reading takes about an hour to train on, on a "
                      "quick computer.")
        # What stopped runs still hold: looked at when the window opens and when a run
        # ends, not every second.
        if state != self.held_at:
            self.held_at = state
            self.held = [] if active else training.unfinished()
        size = sum(size for _, size in self.held)
        self.clear.setVisible(bool(self.held) and not active)
        self.clear.setText(f"Clear stopped runs ({models.size_text(size)})")
        if not active and not problem and not models.kind(config.MODEL_DIR, training.CUTTER):
            # Said before a run, not after it: without this model a run does little good.
            detail = ("Parakeet v2 is not installed. It is what finds where each word of a "
                      "sentence is, so that single words can be learned from too, and it is "
                      "those that teach a model your voice. \"Start training\" offers to "
                      "download it first.")
        if state == "failed":
            # Most often it is memory, and the trainer is ended by the system without a
            # word: say what to try, whatever else was or wasn't said.
            detail = (detail + "\n" if detail else "") + (
                "A run that stops without saying why has most likely run out of memory. "
                "Close other programs and press \"Carry on\": the passes it finished are "
                "kept. \"Open the log\" shows what it wrote down.")
        self.headline.setText(headline)
        self.detail.setText(detail)
        self.halt.setVisible(False)
        self.show_log(getattr(job, "log", "") if state else "")
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
        if not training.ready():
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
            tell(self, f"\u201c{name}\u201d is the model in use for dictation. Give the "
                       "new model another name, or choose another model for dictation first.")
            return
        if not carry_on and models.kind(config.MODEL_DIR, made) \
                and not ask(self, f"There is already a model called \u201c{name}\u201d. Train "
                                  "it afresh, and put the new one in its place?", careful=True):
            return
        cutter = models.BY_NAME.get(training.CUTTER)
        if (not models.kind(config.MODEL_DIR, training.CUTTER) and cutter is not None
                and ask(self, "Parakeet v2 is not installed. It is what finds where each word "
                              "of a sentence is, so that single words can be learned from "
                              "too: and it is those that teach a model your voice. Download "
                              f"it first ({models.size_text(cutter.megabytes * 1e6)})? "
                              "Without it, only the sentences are learned from.")):
            self.fetch_cutter(carry_on)
            return
        self.start_run(carry_on)

    def start_run(self, carry_on: bool) -> None:
        base, name = self.base(), self.name.text().strip()
        job = training.job_for(base, name)
        try:
            job.start(self.folder, base, name, resume=carry_on)
        except OSError as e:
            tell(self, f"The training could not be started: {e.strerror or e}")
            return
        self.job, self.was = job, "starting"
        self.refresh()

    def fetch_cutter(self, carry_on: bool) -> None:
        """Download the model that finds where the words are, then start the run. The
        download is one of Downloads', like any other: the window goes on showing how far
        it has come, it can be stopped, and what has arrived is kept."""
        if self.downloads.name != training.CUTTER:  # unless another window has it coming
            problem = self.downloads.start(training.CUTTER)
            if problem:
                tell(self, problem)
                return
        self.fetching = {"carry_on": carry_on}
        self.refresh()

    def on_downloaded(self, name: str, problem: str) -> None:
        """A download is over. If it is the one a run was waiting for, the run starts."""
        if self.fetching is None or name != training.CUTTER:
            return
        fetching, self.fetching = self.fetching, None
        if not self.isVisible():
            self.timer.stop()         # it was kept going only for this
        self.refill()
        if problem == Downloads.PAUSED:
            self.refresh()            # stopped on purpose: the run isn't started either
        elif problem:
            self.refresh()
            if self.isVisible():
                tell(self, f"Parakeet v2 could not be downloaded. {problem}")
        else:
            self.start_run(fetching["carry_on"])

    def refresh_fetching(self) -> bool:
        """What the window says while Parakeet v2 is being downloaded. False when it isn't."""
        if self.fetching is None:
            return False
        for part in (self.choose, self.bases, self.name, self.go):
            part.setEnabled(False)
        self.clear.setVisible(False)
        self.use.setVisible(False)
        self.show_log("")
        self.halt.setVisible(True)
        self.halt.setText("Stop the download")
        self.halt.setEnabled(not self.downloads.pausing())
        self.headline.setText("Downloading Parakeet v2, which finds where each word is\u2026")
        done, total = self.downloads.done, self.downloads.total
        self.detail.setText(
            "Stopping\u2026" if self.downloads.pausing() else
            f"{models.size_text(done)} of {models.size_text(total)}. The training starts "
            "when it has arrived. It goes on if this window is closed." if total else "Starting.")
        self.bar.setRange(0, 1000)
        self.bar.setValue(round(1000 * done / total) if total else 0)
        return True

    def on_clear(self) -> None:
        """Remove what runs that were stopped, or that failed, have left behind."""
        size = models.size_text(sum(size for _, size in self.held))
        names = ", ".join(sorted({job.status().get("name") or os.path.basename(job.folder)
                                  for job, _ in self.held}))
        if not ask(self, f"A run that was stopped keeps the model as far as it had got, so "
                         f"that it can be carried on. Those kept now ({names}) take {size}. "
                         "Remove them? They can't be carried on after that. Finished models "
                         "and your recordings are not touched.", careful=True):
            return
        for job, _ in self.held:
            job.discard()
        self.held_at = None
        self.refresh()

    def on_use(self) -> None:
        made = self.current().status().get("folder", "")
        if made and models.kind(config.MODEL_DIR, made):
            self.engine.set_model(made)
            self.refill()
            self.refresh()


class AboutWindow(Window):
    """What this is, which version, and what it is using."""

    def __init__(self, engine: Engine, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.hub = hub or Hub()
        self.setWindowTitle(f"About {APP_NAME}")
        self.setMinimumWidth(round(440 * grown(self)))
        alt = Letters()
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        picture = QLabel()
        picture.setPixmap(make_pixmap(State.AWAKE, pixels=72, meter=False))
        top.addWidget(picture)
        title = QLabel(f"<div style='font-size:{points(self, 1.8)}pt; font-weight:bold'>"
                       f"{APP_NAME}</div><div>Version {__version__}</div>")
        top.addWidget(title, 1)
        layout.addLayout(top)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        # The words can be selected and copied, by mouse or keyboard, and the link opened.
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction
                                          | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.body.setOpenExternalLinks(True)
        layout.addWidget(self.body)
        close = QPushButton(alt("Close"))
        close.clicked.connect(self.close)
        log = QPushButton(alt("Open the log"))
        log.clicked.connect(lambda: self.hub.show_log())
        explain(log, "Shows what the program has written down about what it is doing: the "
                     "place to look, and to copy from, when something isn't working.")
        row = QHBoxLayout()
        row.addWidget(log)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        close.setFocus()
        dress(self, minimise=False)

    def showEvent(self, event) -> None:
        self.body.setText(self.text())
        # A wrapped label doesn't tell the window how tall it needs to be, so work it
        # out for the width in use and size the window to fit.
        width = roomy(self, 520, 400)[0]
        self.body.setMinimumSize(width, self.body.heightForWidth(width) + 8)
        self.adjustSize()
        super().showEvent(event)

    @staticmethod
    def known_as(model: str) -> str:
        """A model by the name it goes by in the choosers, with its folder's name after
        it where that says more: "Parakeet Unified (parakeet-unified-en-0.6b)"."""
        try:
            given = training.label(config.MODEL_DIR, model) or short_name(model_label(model)[1])
        except Exception:
            given = ""
        return f"{given}  ({model})" if given and given != model else model

    def text(self) -> str:
        model = self.engine.settings.model or config.AWAKE_MODEL
        status = self.engine.status
        # Where the words will go is only known while awake, when it is looked for.
        target = (status.target or "nothing in front right now"
                  if status.awake and getattr(status, "target_known", True)
                  else "looked for when dictation is awake")
        chosen = self.engine.settings.remote
        # Never the cloud, however it is set: that is said first, and holds either way.
        # Then how it is set now. (It can't say "nothing is sent anywhere" outright any
        # more: another computer of the person's own can be given the recognising.)
        if chosen["on"] and chosen["address"]:
            when = ("what you say while awake, and short sounds while asleep,"
                    if chosen.get("wake") else "what you say while awake")
            where = ("<b>Nothing you say goes to the cloud</b>, or to anybody else: there is "
                     "no account and no service behind this program. As it is set now, "
                     f"{when} is sent to the computer of yours that you chose in Settings "
                     f"({chosen['address']}) to be recognised, with the last words before "
                     "the cursor, your own words and, in a C or C++ file, its names. It is "
                     "encrypted on the way, and goes nowhere else.")
        else:
            where = ("<b>Nothing you say goes to the cloud</b>, or to anybody: there is no "
                     "account and no service behind this program. As it is set now, "
                     "everything is done on this computer. (In Settings you can have "
                     "another computer of your own do the recognising, over an encrypted "
                     "link.)")
        where += (" The internet is used only to fetch what you ask for: a speech model, "
                  "or the tools for training one.")
        if config.WINDOWS:
            what, programs = "Voice dictation.", ("Microsoft Word, messages in classic Outlook "
                                                  "and Visual Studio Code")
        else:
            what, programs = "Voice dictation for Linux.", ("LibreOffice Writer, Thunderbird "
                                                            "messages, Kate, KWrite and Visual "
                                                            "Studio Code")
        return (
            f"<p>{what} Say <b>wake up</b> and talk; say <b>go to sleep</b> "
            "to stop. Your words are fitted to the text around the cursor, and commands "
            "such as <b>scratch that</b>, <b>select</b> and <b>spell that</b> edit by voice.</p>"
            f"<p>Works in {programs}, and in other programs' text boxes if that is ticked "
            "in Settings.</p>"
            f"<p>{where}</p>"
            f"<p><b>Model:</b> {self.known_as(model)}<br>"
            f"<b>Typing into:</b> {target}<br>"
            f"<b>Installed in:</b> {config.INSTALL_DIR}<br>"
            f"<b>Settings file:</b> {self.engine.settings.path or 'not saved'}</p>"
            "<p>By Jonti Olds. Speech recognition is NVIDIA's Parakeet, run by sherpa-onnx, "
            "or OpenAI's Whisper, run by faster-whisper and CTranslate2, whichever model "
            "you choose. Telling speech from other sounds is helped by Silero's voice "
            "detector. The windows and tray icon use Qt.</p>"
            f"<p>Free software under the GNU General Public License, version 3 or later. "
            f"It comes with no warranty.<br><a href=\"{HOMEPAGE}\">{HOMEPAGE}</a></p>"
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
        self.setWindowTitle("Spelling")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMinimumWidth(round(460 * grown(self)))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Spelling"))
        self.word = QLabel()
        self.word.setMinimumHeight(round(54 * grown(self)))
        self.word.setAccessibleName("The word as spelled so far")
        self.word.setStyleSheet(
            f"font: bold {points(self, 2.6)}pt monospace; padding: 6px 10px; "
            "border: 1px solid palette(mid);"
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


class Log:
    """The last things the program wrote to its log, kept so that they can be shown.

    Where there is a systemd journal they are in that too, and on Windows in a file: but
    nobody new should have to know of either to find out why something isn't working.
    This stands in for the program's output: what is written goes on to wherever it was
    going, and the last lines of it are kept, each with the time."""

    LINES = 800

    def __init__(self, onward, beside=None):
        """`beside` is another Log whose lines this one's are kept among: the program
        has two outputs, one for what it says and one for what goes wrong."""
        self.onward = onward
        self.lines = collections.deque(maxlen=self.LINES) if beside is None else beside.lines
        self.lock = threading.Lock() if beside is None else beside.lock
        self.part = ""

    def write(self, text: str) -> int:
        try:
            if self.onward is not None:
                self.onward.write(text)
        except Exception:
            pass
        with self.lock:
            *whole, self.part = (self.part + text).split("\n")
            now = time.strftime("%H:%M:%S")
            self.lines.extend(f"{now}  {line}" for line in whole)
        return len(text)

    def flush(self) -> None:
        try:
            if self.onward is not None:
                self.onward.flush()
        except Exception:
            pass

    def text(self) -> str:
        with self.lock:
            return "\n".join(self.lines)

    def __getattr__(self, name):  # whatever else is asked of an output: its encoding...
        return getattr(self.onward, name)


kept_log = None  # the Log, once main() has put it in place


class LogWindow(Window):
    """What the program has written to its log since it started, to read and to copy:
    for finding out why something isn't working, and for sending with a report of it."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Log")
        alt = Letters()
        layout = QVBoxLayout(self)
        note = QLabel(f"What {APP_NAME} has written down since it was started, the newest "
                      "last. It is kept on this computer. \"Copy all\" takes it, with the "
                      "version and the model in use, for pasting into a report of a fault.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.page = QPlainTextEdit()
        self.page.setReadOnly(True)
        self.page.setTabChangesFocus(True)
        self.page.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.page.setAccessibleName("The log")
        layout.addWidget(self.page, 1)
        row = QHBoxLayout()
        copy = QPushButton(alt("Copy all"))
        copy.clicked.connect(self.on_copy)
        self.copied = QLabel()
        row.addWidget(copy)
        if config.WINDOWS:
            folder = QPushButton(alt("Open the log file"))
            folder.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(config.LOG_FILE)))
            row.addWidget(folder)
        row.addWidget(self.copied, 1)
        close = QPushButton(alt("Close"))
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.shown = ""
        self.timer = QTimer(self)  # it follows the log while it is open
        self.timer.timeout.connect(self.refresh)
        dress(self, roomy(self, 760, 460))

    def details(self) -> str:
        """What a report of a fault wants at its head."""
        import platform
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
        session = os.environ.get("XDG_SESSION_TYPE", "")
        return (f"{APP_NAME} {__version__}\n"
                f"System: {platform.system()} {platform.release()}"
                + (f", {desktop}" if desktop else "") + (f", {session}" if session else "")
                + f"\nPython: {platform.python_version()}\n"
                f"Model: {self.engine.settings.model or config.AWAKE_MODEL}\n")

    def text(self) -> str:
        if kept_log is not None:
            return kept_log.text()
        return "Nothing has been kept: the log is where the program's output goes."

    def refresh(self) -> None:
        text = self.text()
        if text == self.shown:
            return
        self.shown = text
        bar = self.page.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        place = bar.value()
        self.page.setPlainText(text)
        bar.setValue(bar.maximum() if at_end else place)  # it stays where it was being read

    def showEvent(self, event) -> None:
        self.copied.setText("")
        self.refresh()
        self.page.verticalScrollBar().setValue(self.page.verticalScrollBar().maximum())
        self.timer.start(1000)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        super().hideEvent(event)

    def on_copy(self) -> None:
        QApplication.clipboard().setText(self.details() + "\n" + self.text() + "\n")
        self.copied.setText("Copied.")


class HelpWindow(Window):
    """"What can I say?": every spoken command and sign, with what it does, grouped as
    Settings groups them. A box narrows the list as it is typed in, and what is switched
    off in Settings is marked, in words. Opened from the tray menu, from the welcome
    window, and by saying "what can I say"."""

    # Always on, and not among the tick boxes: said first.
    STEP_WORDS = {"keys": "presses keys", "open": "opens a file or a page", "run": "runs a program",
                  "type": "types a text", "wait": "waits", "ask": "asks first"}
    ALWAYS = (
        ("\"Wake up\"", "Wakes dictation: from then on what you say is typed. It is "
                        "listened for while dictation is asleep."),
        ("\"Go to sleep\"", "Sends dictation to sleep: nothing more is typed until you "
                            "say \"wake up\"."),
    )

    def __init__(self, engine: Engine, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.hub = hub or Hub()
        self.setWindowTitle("What can I say?")
        self.shown = []  # the settings whose lines are in the list now
        alt = Letters()
        close = QPushButton(alt("Close"))
        layout = QVBoxLayout(self)
        note = QLabel("Everything that can be said as a command, and the signs that can be "
                      "said by name. Anything else you say is typed. Each of these can be "
                      "switched off in Settings; what is switched off is typed as ordinary "
                      "words.")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        label = QLabel(alt("Find:"))
        self.find = QLineEdit()
        self.find.setClearButtonEnabled(True)
        self.find.setPlaceholderText("Type a word to narrow the list, such as select or comma")
        self.find.setAccessibleName("Find in the list of what can be said")
        label.setBuddy(self.find)
        self.find.textChanged.connect(lambda _: self.fill())
        self.count = QLabel()
        row.addWidget(label)
        row.addWidget(self.find, 1)
        row.addWidget(self.count)
        layout.addLayout(row)
        self.page = QTextBrowser()
        self.page.setOpenLinks(False)
        self.page.setTabChangesFocus(True)
        self.page.setAccessibleName("What can be said")
        layout.addWidget(self.page, 1)
        row = QHBoxLayout()
        settings = QPushButton(alt("Settings…"))
        settings.clicked.connect(lambda: self.hub.show_settings())
        explain(settings, "Opens Settings, where each of these can be switched on or off.")
        close.clicked.connect(self.close)
        row.addWidget(settings)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        self.fill()
        dress(self, roomy(self, 640, 560))

    def entries(self) -> list:
        """(group, setting, its line, what it does, whether it is switched on) for all
        that can be said: the two that are always on, then Settings' own, in its order."""
        found = [("Waking and sleeping", "", label, about, True) for label, about in self.ALWAYS]
        options = getattr(settings_module, "OPTIONS", frozenset())
        for item in ITEMS:
            if item.key in options or (item.key in WINDOWS_ONLY and not config.WINDOWS):
                continue  # a setting, not something to say
            found.append((item.group, item.key, item.label, help_for(item.key),
                          self.engine.settings.enabled(item.key)))
        # And the person's own, from Settings: what each is said as, and what it does.
        for said, written in (getattr(self.engine.settings, "shortcuts", None) or {}).items():
            try:
                steps = actions.parse(written)
            except ValueError:
                continue
            what = ("Types: " + brief(written.replace("\n", " / "), 60) if not steps else
                    "Does: " + ", then ".join(self.STEP_WORDS.get(step[0], step[0]) for step in steps))
            found.append((SettingsWindow.OWN_GROUP, "", f"\"{said.capitalize()}\"", what, True))
        return found

    def fill(self) -> None:
        """Show those whose words, help or group have every word typed in the box."""
        import html
        wanted = self.find.text().lower().split()
        parts, group, self.shown, count = [], None, [], 0
        for heading, key, label, about, on in self.entries():
            if not all(word in f"{heading} {label} {about}".lower() for word in wanted):
                continue
            if heading != group:
                group = heading
                parts.append(f"<h3>{html.escape(heading)}</h3>")
            # Switched off is said in words after the line, and the line is slanted: it
            # is never only a matter of colour.
            head, gap, more = label.partition("  ")  # what to say, then anything about it
            line = f"<b>{html.escape(head)}</b>" + (f" &nbsp;{html.escape(more)}" if more else "")
            if not on:
                line = f"<i>{line}</i><br>Switched off in Settings: it is typed as words."
            parts.append(f"<p style='margin-left: 12px'>{line}"
                         + (f"<br>{html.escape(about)}" if about else "") + "</p>")
            self.shown.append(key)
            count += 1
        if not parts:
            parts.append("<p>Nothing that can be said has those words in it. Clear the box "
                         "to see everything.</p>")
        self.page.setHtml("".join(parts))
        self.count.setText(f"{count} shown" if wanted else f"{count} in all")

    def showEvent(self, event) -> None:
        self.fill()  # one may have been switched on or off since it was last open
        self.find.setFocus()
        self.find.selectAll()
        super().showEvent(event)


class TryBox(QPlainTextEdit):
    """The box in the welcome window to try dictating in. It says when it gains and
    loses the keyboard: dictation goes into it only while it has it."""

    focused = pyqtSignal(bool)

    def sizeHint(self) -> QSize:
        """Five lines' worth: a box to try a few phrases in, not a page to fill."""
        return QSize(320, self.fontMetrics().lineSpacing() * 5 + 16)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focused.emit(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.focused.emit(False)


class OwnTarget(QObject):
    """What the engine types into while the welcome window's box has the keyboard: it
    answers the same requests as every program dictation goes into (see targets.py).

    The engine asks from its worker thread. The box is the window's, so each request is
    handed to the window's thread, and the answer waited for a second at most."""

    name = "the box here"
    asked = pyqtSignal(object)
    WAIT = 1.0
    HISTORY = 20
    AROUND = 2000  # characters of the text before and after the cursor that are told

    def __init__(self, box: QPlainTextEdit):
        super().__init__(box)
        self.box = box
        self.history = []  # what was put in, the last last: (where, the text)
        self.asked.connect(self.on_asked)

    def request(self, message: dict) -> dict:
        if QThread.currentThread() == self.thread():
            return self.answer(message)  # already on the window's thread
        waiting = {"message": message, "done": threading.Event(), "reply": None,
                   "given_up": False}
        try:
            self.asked.emit(waiting)
        except RuntimeError:              # the window has gone, and the box with it
            return {"ok": False, "why": "editor not focused"}
        if not waiting["done"].wait(self.WAIT):
            # Not carried out later either: the engine has been told it wasn't done, and
            # words arriving after that would be words nobody is expecting.
            waiting["given_up"] = True
            return {"ok": False, "why": "the box here did not answer"}
        return waiting["reply"]

    def on_asked(self, waiting: dict) -> None:
        if waiting["given_up"]:
            return
        waiting["reply"] = self.answer(waiting["message"])
        waiting["done"].set()

    def answer(self, message: dict) -> dict:
        """Answer one request. Never raises."""
        try:
            return self.handle(message)
        except Exception as e:
            return {"ok": False, "why": "error", "error": str(e)}

    @staticmethod
    def plain(text: str) -> str:
        return text.replace(" ", "\n").replace(" ", "\n")

    def around(self) -> tuple:
        """(the text before the cursor or the selection, the text after it, what is selected)."""
        cursor = self.box.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        last = self.box.document().characterCount() - 1
        look = QTextCursor(self.box.document())
        look.setPosition(max(0, start - self.AROUND))
        look.setPosition(start, QTextCursor.MoveMode.KeepAnchor)
        before = self.plain(look.selectedText())
        look.setPosition(end)
        look.setPosition(min(last, end + self.AROUND), QTextCursor.MoveMode.KeepAnchor)
        after = self.plain(look.selectedText())
        return before, after, self.plain(cursor.selectedText())

    def handle(self, m: dict) -> dict:
        op = m.get("op")
        if op == "status":
            return {"ok": True, "ready": True}
        if op == "context":
            before, after, selected = self.around()
            return {"ok": True, "before": before, "after": after, "selected": selected}
        if op == "insert":
            return self.insert(str(m.get("text", "")), int(m.get("delete_before", 0) or 0),
                               int(m.get("delete_after", 0) or 0), bool(m.get("capitalise_next")))
        if op == "command":
            name = m.get("name", "")
            if name == "scratch":
                return self.scratch()
            if name == "undo":
                self.box.undo()
                return {"ok": True}
            if name == "new_paragraph":
                return self.insert(PARAGRAPH, 0, 0, False)
            if name == "new_line":
                return self.insert(LINE, 0, 0, False)
            if name == "select_all":
                self.box.selectAll()
                return {"ok": True}
            if name == "cancel_choices":  # sent to every program: there are none here
                return {"ok": True}
            return {"ok": False, "why": "unknown command"}
        return {"ok": False, "why": "unknown request"}

    def insert(self, text: str, delete_before: int, delete_after: int,
               capitalise_next: bool) -> dict:
        """Put text in at the cursor, in place of what is selected, as every program
        dictation goes into does: see editor_target.py."""
        # In plain text a paragraph is set off by a blank line.
        text = text.replace(PARAGRAPH, "\n\n").replace(LINE, "\n")
        if not text and not delete_before and not delete_after:
            return {"ok": True, "text": ""}
        keep, move = QTextCursor.MoveMode.KeepAnchor, QTextCursor.MoveOperation
        cursor = self.box.textCursor()
        cursor.beginEditBlock()  # one step for the box's own Undo
        if cursor.hasSelection():
            cursor.removeSelectedText()
        if delete_before:
            cursor.movePosition(move.Left, keep, delete_before)
            cursor.removeSelectedText()
        if delete_after:
            cursor.movePosition(move.Right, keep, delete_after)
            cursor.removeSelectedText()
        start = cursor.position()
        cursor.insertText(text)
        if capitalise_next:
            look = QTextCursor(cursor)
            look.movePosition(move.EndOfBlock, keep)
            rest = look.selectedText()
            for at, c in enumerate(rest):
                if c.isalpha():
                    if c != c.upper() and len(c.upper()) == 1:
                        look.setPosition(cursor.position() + at)
                        look.movePosition(move.Right, keep, 1)
                        look.insertText(c.upper())
                    break
        cursor.endEditBlock()
        self.box.setTextCursor(cursor)
        self.box.ensureCursorVisible()
        if text:
            self.history.append((start, text))
            del self.history[:-self.HISTORY]
        return {"ok": True, "text": text}

    def scratch(self) -> dict:
        """Take back the last thing put in, if it is still where it was put."""
        if not self.history:
            return {"ok": False, "why": "nothing to scratch"}
        start, text = self.history.pop()
        cursor = QTextCursor(self.box.document())
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor,
                            len(text))
        if self.plain(cursor.selectedText()) != text:
            return {"ok": False, "why": "nothing to scratch"}  # it has been changed since
        cursor.removeSelectedText()
        self.box.setTextCursor(cursor)
        return {"ok": True}


class WelcomeWindow(Window):
    """What a newcomer sees the first time, in place of Settings: what the program does,
    whether the microphone hears them, what to do, and a box to do it in, so that first
    words don't depend on any other program. Then the model to use, and on Windows the
    two things the installer used to decide for them: a key, and starting at sign-in.
    Opened again at any time from the tray menu's "Getting started"."""

    shows_downloads = True
    SPOKEN = 2  # readings of the level with the voice in them before it is judged

    def __init__(self, engine: Engine, hub: Hub | None = None):
        super().__init__()
        self.engine = engine
        self.hub = hub or Hub()
        self.setWindowTitle("Getting started")
        self.wanted = False    # its button asked for the recommended model: use it on arrival
        self.problem = ""      # why that model couldn't be downloaded, if it couldn't
        self.arrived = False   # it has just been put to use from here
        self.reached, self.spoken, self.speaking = 0, 0, False  # of the phrase being spoken
        self.verdict = ""      # the last phrase's level, in words
        self.downloads = downloads()
        self.downloads.progress.connect(self.on_progress)
        self.downloads.finished.connect(self.on_downloaded)
        alt = Letters()
        close = QPushButton(alt("Close"))
        outer = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)

        elsewhere = engine.settings.remote
        own = ("on a computer of your own" if elsewhere.get("on") and elsewhere.get("address")
               else "on this computer")
        what = QLabel(f"{APP_NAME} types what you say, in English, into the program you are "
                      "working in, and takes spoken commands such as \"scratch that\". "
                      f"Nothing you say goes to the cloud: it is all done {own}. "
                      "Nothing here has to be changed before you start.")
        what.setWordWrap(True)
        layout.addWidget(what)

        # Whether the microphone hears them: the bar, and always the same in words.
        box = QGroupBox("Your microphone")
        column = QVBoxLayout(box)
        row = QHBoxLayout()
        self.volume = VolumeBar()
        self.volume.setFixedHeight(18)
        self.level = QLabel()
        self.level.setMinimumWidth(self.level.fontMetrics().horizontalAdvance(
            "A little quiet") * 13 // 10)
        row.addWidget(self.volume, 1)
        row.addWidget(self.level)
        column.addLayout(row)
        self.heard = QLabel()
        self.heard.setWordWrap(True)
        column.addWidget(self.heard)
        row = QHBoxLayout()
        self.turn_on = QPushButton(alt("Turn the microphone on"))  # there while it is off
        # On, and asleep: the next thing this window says to do is to say "wake up", which
        # would make no sense to somebody the button had already woken it for.
        self.turn_on.clicked.connect(lambda: self.engine.turn_on())
        row.addWidget(self.turn_on)
        row.addStretch()
        column.addLayout(row)
        layout.addWidget(box)

        box = QGroupBox("What to do")
        column = QVBoxLayout(box)
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        self.say_steps()
        column.addWidget(self.steps)
        self.other = None
        if "other_apps" in settings_module.BY_KEY:
            # The one setting a newcomer may need at once: without Word or Writer, this
            # is what makes it work in the program they have.
            self.other = QCheckBox(alt("Also dictate into other programs' text boxes, "
                                       "such as a chat box"))
            self.other.setChecked(engine.settings.enabled("other_apps"))
            self.other.clicked.connect(self.on_other)
            explain(self.other, help_for("other_apps"))
            column.addWidget(self.other)
        self.box = TryBox()
        self.box.setPlaceholderText("Click here, say \"wake up\", and talk. Your words appear "
                                    "here.")
        self.box.setTabChangesFocus(True)
        self.box.setAccessibleName("A box to try dictating in")
        self.box.setMinimumHeight(self.box.fontMetrics().lineSpacing() * 4 + 16)
        self.own = OwnTarget(self.box)
        self.box.focused.connect(self.on_box_focus)
        column.addWidget(self.box, 1)
        row = QHBoxLayout()
        self.picture = QLabel()
        self.state = QLabel()
        self.state.setWordWrap(True)
        row.addWidget(self.picture)
        row.addWidget(self.state, 1)
        column.addLayout(row)
        layout.addWidget(box, 1)

        # The model to use: shown until it is the one in use.
        self.model_box = QGroupBox("The model to use")
        column = QVBoxLayout(self.model_box)
        self.model_note = QLabel()
        self.model_note.setWordWrap(True)
        column.addWidget(self.model_note)
        self.model_bar = QProgressBar()
        self.model_bar.setRange(0, 1000)
        self.model_bar.setTextVisible(False)
        self.model_bar.setFixedHeight(10)
        self.model_bar.setAccessibleName("How far the download has come")
        column.addWidget(self.model_bar)
        row = QHBoxLayout()
        self.model_go = QPushButton()
        self.model_go.clicked.connect(self.on_model_go)
        row.addWidget(self.model_go)
        row.addStretch()
        column.addLayout(row)
        layout.addWidget(self.model_box)

        self.key_chooser = self.start_tick = None
        if config.WINDOWS:
            box = QGroupBox("Two choices")
            column = QVBoxLayout(box)
            self.key_chooser = KeyChooser(engine, self.hub, alt)
            column.addWidget(self.key_chooser)
            self.start_tick = StartTick(alt)
            column.addWidget(self.start_tick)
            layout.addWidget(box)

        # It scrolls if it must, on a small screen or at a large size of text.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        row = QHBoxLayout()
        say = QPushButton(alt("What can I say?"))
        say.clicked.connect(lambda: self.hub.show_help())
        settings = QPushButton(alt("Settings…"))
        settings.clicked.connect(lambda: self.hub.show_settings())
        close.clicked.connect(self.close)
        again = QLabel("This window is \"Getting started\" in the icon's menu.")
        again.setWordWrap(True)
        row.addWidget(say)
        row.addWidget(settings)
        row.addWidget(again, 1)
        row.addWidget(close)
        outer.addLayout(row)
        self.timer = QTimer(self)  # follows the microphone and the state while it is open
        self.timer.timeout.connect(self.follow)
        self.follow()
        self.refresh_model()
        frame = looks.dress(self, look_of(self))
        self.ensurePolished()
        # As tall as what is in it needs at this width, with a little more for the box
        # to try it in: but never taller than the screen, where it scrolls instead.
        margins = outer.contentsMargins()
        width = round(720 * grown(self))
        needed = inner.layout().totalHeightForWidth(width - margins.left() - margins.right())
        if needed <= 0:
            needed = inner.sizeHint().height()
        height = (needed + 16 + close.sizeHint().height() + outer.spacing()
                  + margins.top() + margins.bottom())
        width, height = width + frame.width(), height + frame.height()
        screen = QApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            width, height = min(width, room.width() - 24), min(height, room.height() - 48)
        self.resize(width, height)

    def wake_and_sleep(self) -> tuple:
        """What to say to wake dictation and to send it to sleep, as a newcomer is told:
        the words that always work, with the one-word forms beside them where those have
        been switched on in Settings. (Told the short ones alone, somebody who then
        switches them off would be left with words that no longer work.)"""
        if self.engine.settings.enabled("short_wake"):
            return "\"wake up\" (or just \"wake\")", "\"go to sleep\" (or just \"sleep\")"
        return "\"wake up\"", "\"go to sleep\""

    def say_steps(self) -> None:
        wake, sleep = self.wake_and_sleep()
        text = (f"1. Click in the box below, or in a program it works with: {self.programs()}.\n"
                f"2. Say {wake}. The icon by the clock turns green, and the line under the "
                "box says Awake.\n"
                "3. Talk, and pause: your words appear when you pause.\n"
                f"4. Say {sleep} when you have finished.")
        if self.steps.text() != text:
            self.steps.setText(text)

    def programs(self) -> str:
        """The programs dictation goes into on this system without anything being
        ticked: those whose links the engine has, which leaves out any that are switched
        off here or couldn't be set up."""
        targets = getattr(self.engine, "targets", None)
        has = lambda name: getattr(targets, name, True) is not None
        if config.WINDOWS:
            found = (["Microsoft Word", "a message in classic Outlook"] if has("office") else [])
        else:
            found = ["LibreOffice Writer"] + (["a Thunderbird message"] if has("mail") else []) \
                + (["Kate"] if has("editor") else [])
        if has("vscode"):
            found.append("Visual Studio Code")
        if not found:
            return "none is set up on this computer, so tick the box below for other programs"
        return found[0] if len(found) == 1 else ", ".join(found[:-1]) + " or " + found[-1]

    # ---- the box to try it in ------------------------------------------------------------
    def on_box_focus(self, has: bool) -> None:
        """Dictation goes into the box only while it has the keyboard: the engine is told
        of it then, and told it is gone the moment it isn't."""
        targets = getattr(self.engine, "targets", None)
        if targets is None:
            return
        if has and self.isVisible():
            targets.own = self.own
        elif getattr(targets, "own", None) is self.own:
            targets.own = None

    def on_other(self, on: bool) -> None:
        self.engine.settings.set("other_apps", on)
        self.engine.setting_changed("other_apps")
        self.hub.changed()

    def showEvent(self, event) -> None:
        self.arrived = False
        self.follow()
        self.refresh_model()
        if self.other is not None:
            self.other.setChecked(self.engine.settings.enabled("other_apps"))
        if self.key_chooser is not None:
            self.key_chooser.refresh()
        if self.start_tick is not None:
            self.start_tick.refresh()
        self.timer.start(200)
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.timer.stop()
        self.on_box_focus(False)  # nothing is typed into a box that can't be seen
        super().hideEvent(event)

    # ---- the microphone and the state, as they are ------------------------------------------
    def follow(self) -> None:
        """Five times a second while the window is open: the level as the engine hears
        it, with a verdict in words on each phrase, and what dictation is doing."""
        status = self.engine.status
        failed = getattr(status, "failed", "")
        off = status.state is State.OFF
        self.turn_on.setVisible(off and status.ready and not failed)
        if failed:
            self.say_level("No model", reading.RED,
                           f"{failed} \"Settings\", below, has \"Install or remove models\".")
        elif not status.ready:
            self.say_level("Loading…", reading.GREY,
                           "The model is being loaded. That takes a few seconds.")
        elif off:
            self.say_level("Off", reading.RED,
                           "The microphone is off, so nothing is heard. Press \"Turn the "
                           "microphone on\": dictation then waits, asleep, for you to say "
                           "\"wake up\".")
        else:
            self.hear(status.meter, status.loud)
        if off or failed or not status.ready:
            self.volume.clear()
            self.reached, self.spoken, self.speaking, self.verdict = 0, 0, False, ""
        wake, sleep = self.wake_and_sleep()
        words = ("No model could be loaded." if failed else
                 "Loading the model…" if not status.ready else
                 "Off: the microphone is closed." if off else
                 f"Awake: talk, and pause. Say {sleep} to stop." if status.awake else
                 f"Asleep. Say {wake} to dictate.")
        self.say_steps()   # the words for waking follow the setting, if it has been changed
        if self.state.text() != words:
            self.state.setText(words)
            icon = (make_failed_icon() if failed else make_loading_icon() if not status.ready
                    else make_icon(status.state))
            self.picture.setPixmap(icon.pixmap(28, 28))  # the icon by the clock, to know it by

    def hear(self, meter: int, loud: bool) -> None:
        """The level as the engine measures it for dictation: how far the sound stands
        above the room, 0 to 100, and whether the microphone is overloaded."""
        # The bar's length is how far above the room; its colour and the words go by
        # that too, and by `loud`, which is all the engine says of the highest it went.
        place = min(float(meter), 86.0)
        peak = 1.0 if loud else 10 ** ((1.0 - place / 100.0) * reading.LOWEST_DB / 20.0)
        self.volume.hear(meter, peak)
        speaking = meter >= reading.QUIET / 2 or loud
        if speaking and not self.speaking:
            self.reached, self.spoken = 0, 0  # a new phrase
        self.speaking = speaking
        if speaking:
            self.spoken += 1
            self.reached = max(self.reached, meter)
            if self.spoken >= self.SPOKEN:
                self.verdict = reading.level_verdict(
                    self.reached, config.CLIP_LEVEL if loud else 0.0)[0]
        if self.verdict:
            colour = reading.level_verdict(self.reached, config.CLIP_LEVEL if loud else 0.0)[1]
            self.say_level(self.verdict, colour, reading.ADVICE[self.verdict])
        else:
            self.say_level("Say something", reading.GREY,
                           "Speak as you do when you dictate: the bar should move, and "
                           "these words say whether you are loud enough. Nothing is typed "
                           "while dictation is asleep.")

    def say_level(self, words: str, colour: tuple, advice: str) -> None:
        if self.level.text() != words:
            self.level.setText(words)
            self.level.setStyleSheet("font-weight: bold; color: rgb(%d, %d, %d);" % colour)
        if self.heard.text() != advice:
            self.heard.setText(advice)
        self.volume.setAccessibleDescription(f"{words}. {advice}")

    # ---- the model to use ---------------------------------------------------------------------
    def refresh_model(self) -> None:
        """Say how the recommended model stands, and offer the next thing to do about it.
        Once it is the one in use, the box is gone."""
        known = models.BY_NAME.get(RECOMMENDED)
        in_use = (self.engine.settings.model or config.AWAKE_MODEL) == RECOMMENDED
        installed = bool(models.kind(config.MODEL_DIR, RECOMMENDED))
        coming = self.downloads.name == RECOMMENDED
        best = "Parakeet Unified is the best of the models so far, and the one to use."
        self.model_box.setVisible(not in_use or self.arrived)
        self.model_bar.setVisible(coming)
        self.model_go.setVisible(not in_use)
        self.model_go.setEnabled(True)
        if in_use:
            self.model_note.setText("Parakeet Unified is installed, and is now the model in "
                                    "use for dictation.")
        elif installed:
            self.model_note.setText(f"{best} It is installed, but another is in use.")
            self.model_go.setText("Use Parakeet Unified")
        elif not models.transducers_usable() or known is None:
            self.model_note.setText(f"{best} It can't be used on this computer yet: run "
                                    "the installer again to add Parakeet support.")
            self.model_go.setVisible(False)
        elif coming:
            done, total = self.downloads.done, self.downloads.total
            self.model_bar.setValue(round(1000 * done / total) if total else 0)
            self.model_note.setText(
                f"{best} " + ("Pausing…" if self.downloads.pausing() else
                              f"Downloading: {int(100 * done / total)}%  "
                              f"({models.size_text(done)} of {models.size_text(total)}). "
                              "It goes on if this window is closed"
                              + (", and is put to use when it has arrived."
                                 if self.wanted else ". Choose it in Settings when it has "
                                                     "arrived.") if total
                              else "Starting the download…"))
            self.model_go.setText("Pause the download")
            self.model_go.setEnabled(not self.downloads.pausing())
        else:
            part = models.part_size(config.MODEL_DIR, RECOMMENDED)
            size = models.size_text(known.megabytes * 1e6)
            self.model_note.setText(
                f"{best} " + (f"{self.problem} " if self.problem else "")
                + (f"The download is paused, with {models.size_text(part)} of {size} here."
                   if part else
                   f"It is a download of {size}, and is put to use when it has arrived."))
            self.model_go.setText("Carry on with the download" if part
                                  else "Install Parakeet Unified")

    def on_model_go(self) -> None:
        self.problem = ""
        if self.downloads.name == RECOMMENDED:
            self.wanted = False  # paused on purpose: it isn't put to use behind their back
            self.downloads.pause()
        elif models.kind(config.MODEL_DIR, RECOMMENDED):
            self.use_it()
        else:
            self.problem = self.downloads.start(RECOMMENDED)
            self.wanted = not self.problem
        self.refresh_model()

    def on_progress(self, name: str, done, total) -> None:
        if name == RECOMMENDED:
            self.refresh_model()

    def on_downloaded(self, name: str, problem: str) -> None:
        if name != RECOMMENDED:
            return
        if not problem and self.wanted:
            self.use_it()
        elif problem and problem != Downloads.PAUSED:
            self.problem = problem
        self.wanted = False
        self.refresh_model()

    def use_it(self) -> None:
        """Put the recommended model to use for dictation."""
        self.arrived = True  # the box stays for now, to say that it is done
        self.engine.set_model(RECOMMENDED)
        self.hub.changed()
        self.refresh_model()


class StatusWindow(Window):
    """Where the desktop has no system tray, a small window in the icon's place: what
    dictation is doing, in words, and the entries of the icon's menu as buttons, with
    Quit among them. Without it the program ran unseen, with the microphone open and no
    way to switch it off.

    While there is no tray it can't be closed, only minimised: closing it would leave
    nothing on the screen to work the program by."""

    counts = False  # "close that window" is never meant for this one

    def __init__(self, engine: Engine, actions: list):
        super().__init__()
        self.engine = engine
        self.stay = False  # there is no tray: closing only minimises
        self.setWindowTitle(APP_NAME)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.picture = QLabel()
        self.words = QLabel()
        self.words.setWordWrap(True)
        self.words.setStyleSheet(f"font-size: {points(self, 1.5)}pt; font-weight: bold;")
        row.addWidget(self.picture)
        row.addWidget(self.words, 1)
        layout.addLayout(row)
        self.more = QLabel()  # what the icon's tip would say
        self.more.setWordWrap(True)
        self.more.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.more)
        self.notice = QLabel()  # the last notice, which has no tray to be shown by
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.why = QLabel("This desktop has no system tray for the icon to sit in, so this "
                          "window stands in for it. Minimise it to put it out of the way.")
        self.why.setWordWrap(True)
        layout.addWidget(self.why)
        grid = QGridLayout()
        self.buttons = []
        for at, action in enumerate(actions):
            button = QPushButton(action.text())
            button.clicked.connect(action.trigger)
            grid.addWidget(button, at // 2, at % 2)
            self.buttons.append(button)
        # The words on some entries change (wake up, go to sleep): the buttons follow.
        # Joined to a method of this window, so that the joining ends when the window
        # does (a change of look makes it afresh).
        self.actions = list(actions)
        for action in self.actions:
            action.changed.connect(self.follow)
        layout.addLayout(grid)
        layout.addStretch()
        self.setMinimumWidth(round(380 * grown(self)))
        # It appears by itself, some seconds after the start: it must not take the
        # keyboard from the window somebody is typing or dictating into.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        dress(self)

    def follow(self) -> None:
        """An entry of the menu changed its words, or whether it can be used: so does
        its button here."""
        for button, action in zip(self.buttons, self.actions):
            button.setText(action.text())
            button.setEnabled(action.isEnabled())

    def show_state(self, icon: QIcon, tooltip: str) -> None:
        lines = tooltip.split("\n")
        self.picture.setPixmap(icon.pixmap(40, 40))
        self.words.setText(lines[0])
        self.more.setText("\n".join(lines[1:]))
        self.more.setVisible(len(lines) > 1)

    def note(self, message: str) -> None:
        self.notice.setText(message)

    def closeEvent(self, event) -> None:
        if self.stay:
            event.ignore()
            self.showMinimized()
        else:
            super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.stay:
            self.showMinimized()
            return
        super().keyPressEvent(event)


def install_pending_extension() -> str:
    """Put a waiting Writer extension into LibreOffice, which must be closed. Returns
    what went wrong, or "" if it is in."""
    pending = config.PENDING_EXTENSION
    subprocess.run(["unopkg", "remove", "io.github.jontio.linuxspeaking"],
                   capture_output=True, timeout=120)
    done = subprocess.run(["unopkg", "add", pending], capture_output=True, text=True, timeout=120)
    if done.returncode == 0:
        os.remove(pending)
        return ""
    return (done.stderr or done.stdout).strip()[-200:] or "LibreOffice's unopkg gave no reason."


class Tray:
    def __init__(self, app: QApplication):
        self.app = app
        self.bridge = Bridge()
        self.icons = {
            (state, level): make_icon(state, level)
            for state in State for level in range(config.LEVEL_STEPS + 1)
        }
        self.loud_icons = {state: make_icon(state, loud=True) for state in State}
        self.command_icons = {    # awake with only commands acted on: a "C" on each
            (state, level): make_icon(state, level, commands=True)
            for state in (State.AWAKE, State.HEARING, State.THINKING)
            for level in range(config.LEVEL_STEPS + 1)
        }
        self.loading_icon = make_loading_icon()
        self.failed_icon = make_failed_icon()
        self.tray = QSystemTrayIcon(self.loading_icon)
        self.menu = QMenu()
        self.toggle = QAction("Turn microphone on")
        self.toggle.triggered.connect(self.on_toggle)
        self.wake = QAction("Wake up")
        self.wake.triggered.connect(self.on_wake)
        self.quit = QAction("Quit")
        self.quit.triggered.connect(self.on_quit)
        self.show_meter = QAction("Microphone level\u2026")
        self.show_meter.triggered.connect(self.on_show_meter)
        self.show_settings = QAction("Settings\u2026")
        self.show_settings.triggered.connect(self.on_show_settings)
        self.show_help = QAction("What can I say?")
        self.show_help.triggered.connect(self.on_show_help)
        self.show_welcome = QAction("Getting started")
        self.show_welcome.triggered.connect(self.on_show_welcome)
        self.show_log = QAction("Open the log")
        self.show_log.triggered.connect(self.on_show_log)
        self.show_about = QAction("About")
        self.show_about.triggered.connect(self.on_show_about)
        self.actions = [self.toggle, self.wake, self.show_meter, self.show_settings,
                        self.show_help, self.show_welcome, self.show_log, self.show_about]
        for action in self.actions:
            self.menu.addAction(action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_click)

        # The engine starts its own threads as it is made, and may have something to say
        # at once (no speech model, no microphone). What it says comes to this thread by
        # signals, which are joined up here, before it is made: what is sent before the
        # windows are ready then waits its turn, and is not lost.
        self.bridge.event.connect(self.notify)
        self.bridge.notice.connect(self.on_notice)
        self.engine = Engine(on_change=self.bridge.changed.emit)
        self.engine.on_event = self.bridge.event.emit
        self.engine.on_level = self.bridge.level.emit
        # What the engine wants said, from its own threads: brought to this one by a signal.
        self.engine.on_notice = self.bridge.notice.emit
        # The first time is when there were no settings to load, and no sign of an install
        # from before there were any (the engine sees to that: see Engine.__init__).
        first_time = bool(getattr(self.engine.settings, "first_time", False))
        self.numbers = Numbers()
        self.notice = Notice() if config.WINDOWS else None
        self.bridge.numbers.connect(self.numbers.show)
        if self.engine.targets.office is not None:
            # Called from the thread that talks to Word; the signal brings it to this one.
            self.engine.targets.office.show_numbers = self.bridge.numbers.emit
        self.hub = Hub()
        self.hub.show_settings = self.on_show_settings
        self.hub.show_help = self.on_show_help
        self.hub.show_log = self.on_show_log
        self.hub.wake = self.on_wake_up
        self.hub.changed = lambda: self.settings_window.model_changed()
        self.hub.announce = self.announce
        self.hub.set_hotkey = self.set_hotkey
        self.hub.hotkey_problem = lambda: self.hotkey_refused
        downloads().announce = self.announce
        self.hotkey = None
        self.hotkey_refused = ""  # why the chosen key isn't working, in words
        self.extension_failed = False  # the Writer extension couldn't be put in: not tried again
        self.make_windows()
        self.style_menu()
        if config.WINDOWS:
            self.bridge.hotkey.connect(self.switch)
            # Pressed on its own thread, acted on here.
            self.hotkey = hotkey.Hotkey(self.bridge.hotkey.emit)
            self.apply_hotkey()
        self.updating = False
        self.no_tray = 0  # how many times running the desktop has had no tray for the icon
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.check_update)
        self.update_timer.timeout.connect(self.check_training)
        self.update_timer.timeout.connect(self.check_tray)
        self.update_timer.start(5000)
        self.training_was = ""  # the state of the last training run, as last looked at
        self.show_timer = QTimer()
        self.show_timer.timeout.connect(self.check_requests)
        self.show_timer.start(300)  # a key bound to "toggle" is answered without a wait
        self.bridge.changed.connect(self.refresh)
        self.bridge.level.connect(self.refresh_icon)
        self.bridge.extension.connect(self.on_extension)
        self.refresh()
        self.tray.show()
        # What was asked before this start was the menu entry wanting something to see:
        # anything else asked of a program that wasn't running is out of date.
        asked = [word for word in control.taken() if word in (control.SHOW, "settings")]
        if first_time:  # something to see the first time: after that, the icon
            # The settings are kept now, as they are, so that the next start is not a
            # first time too: without this the welcome came back at every start until
            # some setting was changed.
            self.engine.settings.first_time = False
            try:
                self.engine.settings.save()
            except OSError as e:
                print(f"the settings could not be kept: {e}", flush=True)
            self.on_show_welcome()
        elif asked:
            self.on_show_settings()
        if saved_on():
            self.engine.turn_on()

    def make_windows(self) -> None:
        """Make the app's windows, in the look that is chosen. None is shown yet."""
        self.meter = MeterWindow(self.engine)
        self.settings_window = SettingsWindow(self.engine, self.hub)
        self.settings_window.on_setting = self.on_setting
        self.spell_window = SpellWindow(self.engine)
        self.about_window = AboutWindow(self.engine, self.hub)
        self.help_window = HelpWindow(self.engine, self.hub)
        self.welcome_window = WelcomeWindow(self.engine, self.hub)
        self.log_window = LogWindow(self.engine)
        self.status_window = StatusWindow(self.engine, self.actions + [self.quit])

    def refresh(self) -> None:
        status = self.engine.status
        self.refresh_icon()
        self.tray.setToolTip(status.tooltip())
        self.toggle.setText("Turn microphone on" if status.state is State.OFF
                            else "Turn microphone off")
        self.wake.setText("Go to sleep" if status.awake else "Wake up")
        self.spell_window.refresh()
        if self.status_window.isVisible():
            self.status_window.show_state(self.icon_now(), status.tooltip())

    def icon_now(self) -> QIcon:
        """The icon for how things stand. Each state has a shape of its own."""
        status = self.engine.status
        level = 0 if status.state is State.OFF else status.level
        if getattr(status, "failed", ""):
            return self.failed_icon   # no model: nothing can be recognised
        if not status.ready:
            return self.loading_icon
        if status.loud and status.state is not State.OFF:
            return self.loud_icons[status.state]
        if getattr(status, "commands_only", False) and (status.state, level) in self.command_icons:
            return self.command_icons[status.state, level]
        return self.icons[status.state, level]

    def refresh_icon(self) -> None:
        self.tray.setIcon(self.icon_now())

    def on_show_settings(self) -> None:
        bring(self.settings_window)

    def on_show_about(self) -> None:
        bring(self.about_window)

    def on_show_help(self) -> None:
        bring(self.help_window)

    def on_show_welcome(self) -> None:
        bring(self.welcome_window)

    def on_show_log(self) -> None:
        bring(self.log_window)

    def check_requests(self) -> None:
        """Do what was asked from outside: by the application menu's entry or a second
        start, which want the program shown, or by "python -m dictation.control", which
        a key of the person's own may be bound to. See control.py."""
        for word in control.taken():
            if word == control.SHOW:
                if self.status_window.stay:
                    bring(self.status_window)
                self.on_show_settings()
            elif word == "settings":
                self.on_show_settings()
            elif word == "toggle":
                self.switch()
            elif word == "wake":
                self.on_wake_up()
            elif word == "sleep":
                self.engine.sleep()
            elif word == "off":
                self.engine.turn_off()

    NO_TRAY_CHECKS = 3  # times running, five seconds apart, that no tray was found

    def check_tray(self) -> None:
        """Every few seconds: is there a system tray for the icon? A desktop's tray may
        come up a little after the program does, so it is only taken to be missing when
        it has been looked for a few times. Then a small window stands in for the icon."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.no_tray = 0
            if self.status_window.stay:  # the icon has come after all: the window goes
                self.status_window.stay = False
                self.status_window.close()
            return
        self.no_tray += 1
        if self.no_tray == self.NO_TRAY_CHECKS:
            print("this desktop has no system tray: showing a window in the icon's place",
                  flush=True)
            self.status_window.stay = True
            self.status_window.show_state(self.icon_now(), self.engine.status.tooltip())
            self.status_window.show()

    def check_training(self) -> None:
        """Say when a training run has ended, whether or not its window is open: it
        takes an hour or more, and nobody watches it."""
        job = training.latest()
        said = job.status() if job else {}
        state = said.get("state", "")
        if self.training_was in training.ACTIVE and state in training.ENDED:
            headline, detail = training.describe(said)
            self.say(APP_NAME, f"Training on your voice: {headline} {detail}".strip(),
                     self.icons[State.ASLEEP, 0], 10000)
            self.settings_window.refill_models()
            if state == "done" and said.get("folder"):
                self.engine.model_renewed(said["folder"])  # if it is loaded, it is the old one
        self.training_was = state

    def check_update(self) -> None:
        """Put a waiting Writer extension into LibreOffice once that is closed. It waits
        when the installer found LibreOffice open: the first time it is installed, as
        well as when it is updated."""
        waiting = os.path.exists(config.PENDING_EXTENSION)
        if waiting != self.engine.status.update_waiting:
            self.engine.status.update_waiting = waiting
            self.refresh()
            self.settings_window.refresh_banner()
            if waiting and not self.extension_failed:
                self.say(
                    APP_NAME,
                    "The Writer extension is waiting to be put in. Save your work, close "
                    "LibreOffice for a few seconds, then open it again. You will be told "
                    "when Writer is ready.",
                    self.loading_icon, 8000,
                )
        if not waiting or self.updating or self.extension_failed:
            return
        if subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "soffice.bin"],
                          capture_output=True).returncode == 0:  # this person's own, on Linux
            return
        self.updating = True

        def work():
            try:
                problem = install_pending_extension()
            except Exception as e:
                problem = str(e) or type(e).__name__
            self.bridge.extension.emit(problem)  # told on the window's thread

        threading.Thread(target=work, daemon=True).start()

    def on_extension(self, problem: str) -> None:
        """The Writer extension has been put in, or couldn't be. A failure is said, with
        the reason, and not tried again until the program next starts: it used to be
        tried every five seconds for ever, with nothing said."""
        self.updating = False
        if problem:
            self.extension_failed = True
            print(f"the Writer extension could not be put in: {problem}", flush=True)
            self.settings_window.extension_problem = (
                f"The Writer extension could not be put into LibreOffice: {problem} "
                "Dictation into Writer won't work until it is in. Running the installer "
                f"again puts it in; otherwise it is tried again when {APP_NAME} next starts.")
            self.say(APP_NAME, "The Writer extension could not be put into LibreOffice. "
                               "Settings says why, and what to do.", self.failed_icon, 10000)
        else:
            print("the Writer extension is in", flush=True)
            self.say(APP_NAME, "Writer is ready. Open LibreOffice Writer again and you can "
                               "dictate into it.", self.icons[State.AWAKE, 0], 6000)
        self.settings_window.refresh_banner()

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
        """A passing notice: the desktop's own, or on Windows one of ours (see Notice).
        Where there is no tray to show one, the window that stands in for it says it."""
        if self.status_window.isVisible():
            self.status_window.note(message)
        if self.notice is not None:
            self.notice.say(title, message, icon, milliseconds)
        else:
            self.tray.showMessage(title, message, icon, milliseconds)

    def announce(self, text: str, kind: str = "info") -> None:
        """A notice from one of the windows, or from the engine: "info" passes quickly,
        a "problem" stays long enough to be read."""
        problem = kind == "problem"
        self.say(APP_NAME, text, self.failed_icon if problem else self.icon_now(),
                 6000 if problem else 2500)

    def on_notice(self, text: str, kind: str) -> None:
        """Something the engine wants said. It decides when and how often; here it is
        only shown."""
        self.announce(text, kind)

    def notify(self, name: str) -> None:
        status = self.engine.status
        if name == "ready" and status.state is not State.OFF:
            # Said after every change of model too: while awake there is nothing to add.
            self.say(APP_NAME, "Ready." if status.awake else
                     f"Ready. Say \"{self.engine.settings.wake_words()[0]}\" to start.",
                     self.icon_now(), 2500)
        elif name == "failed":
            self.say(APP_NAME, (getattr(status, "failed", "") or "No model could be loaded.")
                     + " Models are installed from Settings: \"Install or remove models\".",
                     self.failed_icon, 10000)
            self.settings_window.refresh_banner()
        elif name == "model":
            self.settings_window.model_changed()  # the choosers follow what is in use
            self.welcome_window.refresh_model()
        elif name == "problems":
            self.settings_window.refresh_banner()
            self.refresh()
        elif name == "app:help":
            self.on_show_help()
        elif name == "app:settings":
            self.on_show_settings()
        elif name == "app:meter":
            self.on_show_meter()
        elif name == "app:close":
            window = Window.in_front()
            if window is not None:
                window.close()
        if name in ("ready", "failed", "model"):
            self.settings_window.refresh_banner()
        if not config.NOTIFY:
            return
        if name == "wake" and status.state is not State.OFF:  # only when it really woke
            self.say(APP_NAME, "Awake", self.icons[State.AWAKE, 0], 1500)
        elif name == "sleep":
            self.say(APP_NAME, "Asleep", self.icons[State.ASLEEP, 0], 1500)
        elif name == "off":
            self.say(APP_NAME, "Off", self.icons[State.OFF, 0], 1500)

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
            self.on_wake_up()

    def on_wake_up(self) -> None:
        if not self.engine.status.awake:
            self.make_way()
            if getattr(self.engine, "_holds", 0):
                # A reading or a voice-test recording has the microphone: waking
                # dictation beside it would have what is read aloud typed somewhere.
                self.announce("Dictation is off while a recording is being made. Pause the "
                              "reading, or stop the recording, first.", "info")
                return
            self.engine.wake()

    def on_click(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.switch()

    def switch(self) -> None:
        """For a click on the icon, the key, and "toggle" asked from outside. From awake,
        off; from asleep or off, awake: someone who clicks the icon while it rests wants
        to talk now, not to say "wake up" first, and certainly not to switch it off."""
        if self.engine.status.awake:
            self.engine.turn_off()
        else:
            self.on_wake_up()

    # ---- the key that switches it, on Windows ------------------------------------------------
    def set_hotkey(self, name: str) -> str:
        """Keep the choice of key and take it. Returns why it couldn't be taken, or ""."""
        name = hotkey.chosen(name)
        keep = getattr(self.engine.settings, "set_hotkey", None)
        if callable(keep):
            keep(name)
        else:  # settings from before there was a choice: it holds for this run
            self.engine.settings.hotkey = name
        return self.apply_hotkey()

    def apply_hotkey(self) -> str:
        """Take the chosen key, or give back the one that was held. When Windows won't
        give it, as when another program has it, that is said beside the chooser and at
        the top of Settings, and stays said: it used to go to the log alone."""
        self.hotkey_refused = ""
        if self.hotkey is not None:
            name = hotkey_of(self.engine.settings)
            if not name:
                self.hotkey.stop()
            elif not self.hotkey.start(name):
                self.hotkey_refused = (
                    f"Windows wouldn't give the key \"{name}\" to {APP_NAME}: another "
                    "program has it. Choose another key, or none.")
                print(f"the key {name} could not be taken: another program has it", flush=True)
        for window in (self.settings_window, self.welcome_window):
            chooser = getattr(window, "key_chooser", None)
            if chooser is not None:
                chooser.refresh()
        self.settings_window.refresh_banner()
        return self.hotkey_refused

    def on_setting(self, key: str) -> None:
        if key == "look":
            QTimer.singleShot(0, self.restyle)  # not from inside the window that is to go
        elif key == "numpad_plus":  # the tick box that was there before the choice of key
            self.apply_hotkey()
        elif key == "other_apps" and self.welcome_window.other is not None:
            self.welcome_window.other.setChecked(self.engine.settings.enabled(key))

    def restyle(self) -> None:
        """The look was changed in Settings: make every window again in the new one, each
        where it stood if it was open, and dress the menu to match."""
        old = self.settings_window
        kept = {}
        for name in ("models_window", "voice_window", "read_window", "train_window"):
            child = getattr(old, name)
            if child is not None:
                child.close()  # a reading under way is ended properly
                if getattr(child, "busy", lambda: False)():
                    kept[name] = child
                else:
                    # Gone in a few seconds, not at once: a reading that was under way
                    # has its microphone to close first, and dictation to give back.
                    QTimer.singleShot(5000, child.deleteLater)
        was = {name: getattr(self, name) for name in (
            "meter", "about_window", "spell_window", "help_window", "welcome_window",
            "log_window", "status_window")}
        places = {name: (window.isVisible() and not window.isMinimized(), window.pos())
                  for name, window in was.items()}
        self.make_windows()
        for name, child in kept.items():
            # A test, or a run waiting for a download, goes on with its window closed.
            # That window is kept, as it looked, and tells the new Settings when it is
            # done: left behind, it would tell the old one, which is gone.
            setattr(self.settings_window, name, child)
            child.old_look = True
            if name == "voice_window":
                child.changed = self.settings_window.model_changed
            else:
                child.refill = self.settings_window.refill_models
            child.hub = self.hub
        self.settings_window.extension_problem = old.extension_problem
        self.settings_window.refresh_banner()
        self.style_menu()
        if old.isVisible():
            self.settings_window.move(old.pos())
            self.settings_window.show()
            self.settings_window.activateWindow()
        old.close()
        old.deleteLater()
        # The new one is shown before the old one is closed: an open level meter holds
        # dictation off, and this way it is not let go and taken again in between.
        for name, window in was.items():
            shown, place = places[name]
            now = getattr(self, name)
            if name == "status_window":
                now.stay = window.stay
                window.stay = False  # so that the old one closes when it is told to
            if name == "welcome_window":
                now.wanted = window.wanted  # a download it asked for is still put to use
                now.box.setPlainText(window.box.toPlainText())
            if shown and name != "spell_window":  # the spelling box shows itself: see refresh()
                now.move(place)
                now.show()
            window.close()
            window.deleteLater()
        self.refresh()

    def style_menu(self) -> None:
        self.menu.setStyleSheet(looks.menu(self.engine.settings.look) if config.WINDOWS else "")

    def on_quit(self) -> None:
        self.meter.let_go(restore=False)  # its microphone is closed; dictation isn't started for it
        if self.hotkey is not None:
            self.hotkey.stop()
        # Qt gives up quitting if a window won't close: so the one that stands in for the
        # icon, which otherwise only minimises, is let go first.
        self.status_window.stay = False
        self.engine.quit()
        self.app.quit()


def unexpected(kind, error, trace) -> None:
    """Something went wrong in a window that nothing was ready for. It is written to the
    log and the app goes on: left to itself, Qt ends the program on the spot."""
    import traceback
    try:
        print("something went wrong:\n"
              + "".join(traceback.format_exception(kind, error, trace)), flush=True)
    except Exception:
        pass


def main() -> int:
    global kept_log
    sys.excepthook = unexpected
    if len(sys.argv) == 3 and sys.argv[1] == "--write-icon":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no desktop needed for this
        app = QApplication(sys.argv[:1])
        write_app_icon(sys.argv[2])
        return 0
    # Only one may run: two would both type what is said. A second start asks the first
    # to show itself, then leaves. On Linux too, so that the menu entry can start the
    # program directly where there is no systemd to see to its running once.
    if not control.only_one():
        try:
            control.ask(control.SHOW)
        except OSError:
            pass
        return 0
    if config.WINDOWS:
        import ctypes
        if sys.stdout is None:  # started without a console: keep a log file instead
            os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
            fresh = (not os.path.exists(config.LOG_FILE)
                     or os.path.getsize(config.LOG_FILE) > 1_000_000)
            sys.stdout = sys.stderr = open(
                config.LOG_FILE, "w" if fresh else "a", buffering=1, encoding="utf-8")
        # Its own taskbar identity, so its windows show its icon.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("jontio.LinuxSpeaking")
    # What is written to the log from here on is also kept, for "Open the log".
    kept_log = Log(sys.stdout)
    sys.stdout, sys.stderr = kept_log, Log(sys.stderr, kept_log)
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
