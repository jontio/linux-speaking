"""The tray icon. Run with: python -m dictation.tray"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import sys

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QMenu, QPushButton,
    QScrollArea, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import APP_NAME, HOMEPAGE, __version__, config
from .engine import Engine, read_number, saved_on, write_text
from .settings import ITEMS, available_models
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
    """Save the green microphone as a picture, for the application menu."""
    make_pixmap(State.AWAKE, pixels=pixels, meter=False).save(path, "PNG")


class Bridge(QObject):
    changed = pyqtSignal()
    level = pyqtSignal()
    event = pyqtSignal(str)


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
        groups = {}
        for item in ITEMS:
            if item.group not in groups:
                box = QGroupBox(item.group)
                box.setLayout(QVBoxLayout())
                layout.addWidget(box)
                groups[item.group] = box
            tick = QCheckBox(item.label)
            tick.setChecked(engine.settings.enabled(item.key))
            tick.toggled.connect(lambda on, key=item.key: (
                engine.settings.set(key, on), engine.setting_changed(key)))
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
        current = self.engine.settings.model or config.AWAKE_MODEL
        for name, label in available_models(config.MODEL_DIR):
            self.models.addItem(label, name)
        at = self.models.findData(current)
        if at >= 0:
            self.models.setCurrentIndex(at)
        self.models.activated.connect(
            lambda index: self.engine.set_model(self.models.itemData(index)))
        layout.addWidget(self.models)
        note = QLabel("Bigger models make fewer mistakes but take longer after each phrase. "
                      "The change takes a few seconds to load. \"Wake up\" always uses "
                      "the recommended model.")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box


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
        return (
            "<p>Voice dictation for Linux. Say <b>wake up</b> and talk; say <b>go to sleep</b> "
            "to stop. Your words are fitted to the text around the cursor, and commands "
            "such as <b>scratch that</b>, <b>select</b> and <b>spell that</b> edit by voice.</p>"
            "<p>Works in LibreOffice Writer, Thunderbird messages, Kate, KWrite and "
            "Visual Studio Code. "
            "Everything runs on this computer: nothing you say is sent anywhere.</p>"
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
        self.meter = MeterWindow(self.engine)
        self.settings_window = SettingsWindow(self.engine)
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
                self.tray.showMessage(
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

    def notify(self, name: str) -> None:
        if name == "ready" and self.engine.status.state is not State.OFF:
            self.tray.showMessage(
                "Dictation", "Ready. Say \"wake up\" to start.", self.icons[State.ASLEEP, 0], 2500
            )
        if not config.NOTIFY:
            return
        if name == "wake":
            self.tray.showMessage("Dictation", "Awake", self.icons[State.AWAKE, 0], 1500)
        elif name == "sleep":
            self.tray.showMessage("Dictation", "Asleep", self.icons[State.ASLEEP, 0], 1500)

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
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.on_toggle()

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
    app = QApplication(sys.argv)
    app.setApplicationName("Linux Speaking")
    app.setApplicationDisplayName(APP_NAME)
    # LS_WINDOW_ICON=0 leaves the windows with the desktop's default icon, for comparison.
    if os.environ.get("LS_WINDOW_ICON", "1") == "1":
        app.setWindowIcon(make_icon(State.AWAKE, pixels=128, meter=False))
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
