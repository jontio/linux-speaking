"""The tray icon. Run with: python -m dictation.tray"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import sys
import time

from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from . import APP_NAME, HOMEPAGE, __version__, audio, config, models, voicetest
from .engine import Engine, read_number, saved_on, write_text
from .settings import ITEMS, WINDOWS_ONLY, available_models, model_label
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


class LevelBar(QWidget):
    """The level meter's bar, drawn here so the desktop's theme can't add anything to it."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(28)
        self.value = 0          # 0 to 100
        self.colour = "#8a8a8a"

    def set(self, value: int, colour: str) -> None:
        if (value, colour) != (self.value, self.colour):
            self.value, self.colour = value, colour
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        track = QRectF(0, 0, self.width(), self.height())
        p.setBrush(self.palette().color(self.palette().ColorRole.Mid))
        p.drawRoundedRect(track, 5, 5)
        if self.value > 0:
            p.setClipRect(QRectF(0, 0, self.width() * min(self.value, 100) / 100, self.height()))
            p.setBrush(QColor(self.colour))
            p.drawRoundedRect(track, 5, 5)
        p.end()


class MeterWindow(QWidget):
    """A small window showing how far the microphone signal is above the background."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Dictation")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self.state = QLabel()
        self.state.setStyleSheet("font-size: 16pt; font-weight: bold;")
        layout.addWidget(self.state)
        layout.addWidget(QLabel("Sound above the background noise. Speech should fill half the bar or more."))
        self.bar = LevelBar()
        layout.addWidget(self.bar)
        self.voice = QLabel()
        self.voice.setWordWrap(True)
        # Room for two lines always, so the window doesn't jump when the message changes.
        self.voice.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.voice.setFixedHeight(2 * self.voice.fontMetrics().lineSpacing() + 2)
        layout.addWidget(self.voice)
        self.heard = QLabel()
        self.heard.setWordWrap(True)
        layout.addWidget(self.heard)

    def refresh(self) -> None:
        status = self.engine.status
        self.state.setText(
            status.label() if status.ready else "Loading\u2026 not ready for dictation yet"
        )
        colour = COLOURS[status.state] if status.ready else LOADING_COLOUR
        self.state.setStyleSheet(f"font-size: 16pt; font-weight: bold; color: {colour};")
        colour = (TOO_LOUD if status.loud else "#2e9d4f" if status.meter >= 60
                  else "#e0a020" if status.meter >= 35 else "#8a8a8a")
        self.bar.set(100 if status.loud else status.meter, colour)
        if status.loud:
            self.voice.setText("Too loud: turn the microphone down, or move it further away.")
        elif status.update_waiting:
            self.voice.setText(
                "An update is waiting. Close LibreOffice for a few seconds, then reopen it.")
        else:
            self.voice.setText(status.voice_line())
        self.heard.setText(f"Heard: {status.last_heard}" if status.last_heard else "")

    def showEvent(self, event) -> None:
        write_text(config.METER_FILE, "1")
        super().showEvent(event)

    def closeEvent(self, event) -> None:
        write_text(config.METER_FILE, "0")
        super().closeEvent(event)


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
        margins = outer.contentsMargins()
        width = (inner.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width()
                 + 2 * scroll.frameWidth() + margins.left() + margins.right() + 8)
        self.resize(max(420, width), 640)

    def model_box(self) -> QGroupBox:
        """A chooser for the speech recognition model."""
        box = QGroupBox("Speech recognition model")
        layout = QVBoxLayout(box)
        self.models = QComboBox()
        self.refill_models()
        self.models.activated.connect(
            lambda index: self.engine.set_model(self.models.itemData(index)))
        layout.addWidget(self.models)
        self.models_window = None
        more = QPushButton("Install or remove models…")
        more.clicked.connect(self.on_show_models)
        self.voice_window = None
        voice = QPushButton("Test them on my voice…")
        voice.clicked.connect(self.on_show_voice_test)
        row = QHBoxLayout()
        row.addWidget(more)
        row.addWidget(voice)
        row.addStretch()
        layout.addLayout(row)
        note = QLabel("Bigger models make fewer mistakes but take longer after each phrase. "
                      "The change takes a few seconds to load. \"Wake up\" always uses "
                      "the recommended model.")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def refill_models(self) -> None:
        """List the models that are installed, with the one in use chosen."""
        current = self.engine.settings.model or config.AWAKE_MODEL
        self.models.clear()
        for name, label in available_models(config.MODEL_DIR):
            self.models.addItem(label, name)
        at = self.models.findData(current)
        if at >= 0:
            self.models.setCurrentIndex(at)

    def on_show_voice_test(self) -> None:
        if self.voice_window is None:
            self.voice_window = VoiceTestWindow(self.engine)
        self.voice_window.show()
        self.voice_window.raise_()
        self.voice_window.activateWindow()

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
                      "move. If it doesn't, try another microphone here.")
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
                needs = (known is not None and known.marker == models.TRANSDUCER
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
            QMessageBox.warning(self, "Speech models", problem)

    def on_remove(self, name: str) -> None:
        label = model_label(name)[1]
        answer = QMessageBox.question(
            self, "Speech models", f"Remove this model?\n\n{label}\n\n"
            + ("It can be installed again from here." if name in models.BY_NAME
               else "It can't be installed again from here."))
        if answer != QMessageBox.StandardButton.Yes or self.in_use(name):
            return
        try:
            models.remove(config.MODEL_DIR, name)
            print(f"model {name}: removed", flush=True)
        except OSError as e:
            QMessageBox.warning(self, "Speech models", f"It could not be removed: {e}")
        self.refresh()
        self.changed()

    def on_discard(self, name: str) -> None:
        try:
            models.discard_part(config.MODEL_DIR, name)
        except OSError as e:
            QMessageBox.warning(self, "Speech models", f"It could not be removed: {e}")
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
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Recogniser", "Words wrong", "Time for a phrase"])
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
        self.resize(760, 600)
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
            QMessageBox.warning(self, self.windowTitle(), problem)

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
                cells = (result.title, "couldn't be tried", result.problem)
            else:
                wrong = own(result)
                percent = 100.0 * wrong / result.total if result.total else 0.0
                cells = (result.title, f"{wrong} of {result.total}  ({percent:.1f}%)",
                         f"{result.seconds:.1f} s")
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        pick = voicetest.suggestion(self.results)
        advice = [note] if note else []
        if pick and not self.running:
            advice.append(f"Suggested: {pick}. It is the quickest of those about as accurate "
                          "as the best.")
        if any(result.where == "team" for result in self.results):
            advice.append("To dictate with a recogniser checked by others, tick \"Second "
                          "opinions\" in Settings: it is a trial.")
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
        if read:
            lines += ["", "In the reading, and not counted:"]
            lines += [self.slip_text(said, heard) for said, heard in read]
        self.slips.setPlainText("\n".join(lines))


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
        self.update_timer.start(5000)
        self.show_timer = QTimer()
        self.show_timer.timeout.connect(self.check_show_request)
        self.show_timer.start(1000)
        self.bridge.changed.connect(self.refresh)
        self.bridge.level.connect(self.refresh_icon)
        self.bridge.event.connect(self.notify)
        self.refresh()
        self.tray.show()
        if read_number(config.METER_FILE, 1) == 1:  # open the first time, then as left
            self.meter.show()
        if saved_on():
            self.engine.turn_on()

    def refresh(self) -> None:
        status = self.engine.status
        self.refresh_icon()
        self.tray.setToolTip(status.tooltip())
        self.toggle.setText(status.menu_toggle_label())
        self.wake.setText("Go to sleep" if status.awake else "Wake up")
        self.meter.refresh()
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
        if self.meter.isVisible():
            self.meter.refresh()

    def on_show_settings(self) -> None:
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def on_show_about(self) -> None:
        self.about_window.show()
        self.about_window.raise_()
        self.about_window.activateWindow()

    def check_show_request(self) -> None:
        """Show the meter window when the menu entry was clicked."""
        if os.path.exists(config.SHOW_FILE):
            try:
                os.remove(config.SHOW_FILE)
            except OSError:
                return
            self.on_show_meter()

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
        self.meter.show()
        self.meter.raise_()

    def say(self, title: str, message: str, icon: QIcon, milliseconds: int) -> None:
        """A passing notice: the desktop's own, or on Windows one of ours (see Notice)."""
        if self.notice is not None:
            self.notice.say(title, message, icon, milliseconds)
        else:
            self.tray.showMessage(title, message, icon, milliseconds)

    def notify(self, name: str) -> None:
        if name == "ready" and self.engine.status.state is not State.OFF:
            self.say("Dictation", "Ready. Say \"wake up\" to start.", self.icons[State.ASLEEP, 0], 2500)
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
            self.engine.turn_on()
        else:
            self.engine.turn_off()

    def on_wake(self) -> None:
        if self.engine.status.awake:
            self.engine.sleep()
        else:
            self.engine.wake()

    def on_click(self, reason) -> None:
        """A click switches off, or from off straight to awake: someone who clicks the icon
        wants to talk now, not to say "wake up" first."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.switch()

    def switch(self) -> None:
        """Off, or from off straight to awake. For a click on the icon and the hotkey."""
        if self.engine.status.state is State.OFF:
            self.engine.wake()
        else:
            self.engine.turn_off()

    def on_setting(self, key: str) -> None:
        if key != "numpad_plus" or self.hotkey is None:
            return
        if not self.engine.settings.enabled(key):
            self.hotkey.stop()
        elif not self.hotkey.start():
            print("the number pad + key could not be taken: another program has it",
                  flush=True)

    def on_quit(self) -> None:
        shown = self.meter.isVisible()
        self.engine.quit()
        write_text(config.METER_FILE, "1" if shown else "0")
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
        # first to show its level meter, then leaves.
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
