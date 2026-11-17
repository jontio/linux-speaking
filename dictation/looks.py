"""Looks for a window and a menu, on Windows: those of Windows 10, Windows 7 and Windows XP.

A window is dressed: its own frame is taken off, and it is given the title bar and border
of the look, its background, and its buttons, tick boxes, boxes to type in and scroll
bars. It is done with a Qt style sheet and a handful of small pictures (the tick, the
arrows, the grip on a scroll bar), which are drawn here the first time they are wanted
and kept beside the app's other files. Nothing of Windows' own is used.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBitmap, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QDialog, QHBoxLayout, QLabel, QPushButton, QStyle, QVBoxLayout, QWidget,
)

from . import config

# What can be chosen: (how it is kept in the settings, how it is named to the person).
LOOKS = (("", "As Windows has it"), ("10", "Windows 10"), ("7", "Windows 7"),
         ("7blue", "Windows 7, blue"), ("xp", "Windows XP"))


# ---- drawing the small pictures -------------------------------------------------------------
def _picture(folder: str, name: str, width: int, height: int, draw) -> None:
    """Draw one picture, at its own size and at twice that for sharp screens."""
    for scale, ending in ((1, ""), (2, "@2x")):
        image = QImage(width * scale, height * scale, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.scale(scale, scale)
        draw(p)
        p.end()
        image.save(os.path.join(folder, f"{name}{ending}.png"))


def _slope(across: bool, *stops) -> str:
    """A style sheet's gradient, down or across, through `stops`: colours, each with or
    without the place (0 to 1) it comes at."""
    placed = [stop if isinstance(stop, tuple) else (at / (len(stops) - 1), stop)
              for at, stop in enumerate(stops)]
    end = "x2:1, y2:0" if across else "x2:0, y2:1"
    return (f"qlineargradient(x1:0, y1:0, {end}, "
            + ", ".join(f"stop:{at} {colour}" for at, colour in placed) + ")")


class _Look:
    """What the two looks share. Each says its own sizes, colours and style sheet."""
    key = ""
    frame = 4            # the border, either side and underneath
    top = 0              # and above the title bar, where the bar doesn't reach the edge itself
    bar = 30             # the title bar
    radius = 8           # of the window's corners: 0 for square ones
    round_bottom = False
    version = 1          # goes up when the pictures change, so that they are drawn again

    @property
    def folder(self) -> str:
        return os.path.join(os.path.dirname(config.STATE_FILE), f"look-{self.key}-{self.version}")

    def pictures(self) -> str:
        """The folder of pictures, made if it isn't there, with / in its name as style
        sheets want."""
        marker = os.path.join(self.folder, "done")
        if not os.path.exists(marker):
            os.makedirs(self.folder, exist_ok=True)
            self.draw_pictures()
            with open(marker, "w") as f:
                f.write("made by dictation/looks.py\n")
        return self.folder.replace("\\", "/")

    def scroll_bars(self, at: str, track: str, handle, over, down, lines: str, arrows: str,
                    grip: str) -> str:
        """The style of scroll bars, upright and flat. `handle`, `over` and `down` give
        the handle's fill, by whether it runs across, as it is, under the mouse and held;
        `lines` styles the arrow buttons."""
        parts = []
        for upright in (True, False):
            way, size, least = ("vertical", "width", "min-height") if upright else ("horizontal", "height", "min-width")
            margin = "17px 0 17px 0" if upright else "0 17px 0 17px"
            first, last = ("top", "bottom") if upright else ("left", "right")
            a, b = ("up", "down") if upright else ("left", "right")
            long = "height" if upright else "width"
            parts.append(f"""
QScrollBar:{way} {{ {size}: 17px; margin: {margin}; border: none; background: {track if upright else track.replace("x2:1, y2:0", "x2:0, y2:1")}; }}
QScrollBar::handle:{way} {{ {least}: 24px; {handle(upright)} {f'image: url({at}/{grip}-{"upright" if upright else "flat"}.png);' if grip else ''} }}
QScrollBar::handle:{way}:hover {{ {over(upright)} }}
QScrollBar::handle:{way}:pressed {{ {down(upright)} }}
QScrollBar::sub-line:{way}, QScrollBar::add-line:{way} {{ {long}: 17px; subcontrol-origin: margin; {lines.replace("ACROSS", "x2:1, y2:0" if upright else "x2:0, y2:1")} }}
QScrollBar::sub-line:{way} {{ subcontrol-position: {first}; }}
QScrollBar::add-line:{way} {{ subcontrol-position: {last}; }}
QScrollBar::{a}-arrow:{way} {{ image: url({at}/{arrows}-{a}.png); }}
QScrollBar::{b}-arrow:{way} {{ image: url({at}/{arrows}-{b}.png); }}
QScrollBar::add-page:{way}, QScrollBar::sub-page:{way} {{ background: none; }}""")
        return "".join(parts)

    def more(self, at: str, pane: str, page: str, tab: str, chosen: str, over: str,
             header: str, progress: str, chunk: str) -> str:
        """The style of what the other windows hold: tabs, a table's headings, ticks in a
        list, a progress bar."""
        return f"""
QTabWidget::pane {{ {pane} top: -1px; }}
QStackedWidget > QWidget {{ background: {page}; }}
QTabBar::tab {{ {tab} }}
QTabBar::tab:selected {{ {chosen} }}
QTabBar::tab:hover:!selected {{ {over} }}
QHeaderView::section {{ {header} }}
QTableWidget {{ gridline-color: #E5E5E5; }}
QListView::indicator, QTableView::indicator {{ width: 13px; height: 13px; image: url({at}/box.png); }}
QListView::indicator:checked, QTableView::indicator:checked {{ image: url({at}/box-on.png); }}
QProgressBar {{ {progress} text-align: center; }}
QProgressBar::chunk {{ {chunk} }}"""

    def tick_boxes(self, at: str, greyed: str) -> str:
        return f"""
QCheckBox {{ spacing: 5px; background: transparent; }}
QCheckBox::indicator {{ width: 13px; height: 13px; image: url({at}/box.png); }}
QCheckBox::indicator:checked {{ image: url({at}/box-on.png); }}
QCheckBox::indicator:hover {{ image: url({at}/box-over.png); }}
QCheckBox::indicator:checked:hover {{ image: url({at}/box-on-over.png); }}
QCheckBox::indicator:disabled {{ image: url({at}/box-off.png); }}
QCheckBox::indicator:checked:disabled {{ image: url({at}/box-on-off.png); }}
QCheckBox:disabled {{ color: {greyed}; }}"""


# ---- Windows XP, in its blue "Luna" ---------------------------------------------------------
class _XP(_Look):
    key = "xp"
    frame, bar, radius, round_bottom = 4, 30, 8, False
    SAND = "#ECE9D8"
    window = "background: #0054E3;"
    button_size = (21, 21)
    bar_margins = (0, 0, 6, 0)
    bar_spacing = 2
    menu = """
QMenu { background: #FFFFFF; border: 1px solid #ACA899; padding: 2px; font-family: Tahoma;
        font-size: 8pt; color: #000000; }
QMenu::item { padding: 3px 28px 3px 22px; background: transparent; }
QMenu::item:selected { background: #316AC5; color: #FFFFFF; }
QMenu::item:disabled { color: #ACA899; }
QMenu::separator { height: 1px; background: #ACA899; margin: 3px 2px 3px 2px; }
"""

    def draw_pictures(self) -> None:
        def box(p, ticked, edge, glow=False, tick="#21A121"):
            p.fillRect(QRectF(0, 0, 13, 13), QColor(edge))
            inside = QLinearGradient(1, 1, 12, 12)
            inside.setColorAt(0, QColor("#DCDCD7"))
            inside.setColorAt(1, QColor("#FFFFFF"))
            p.fillRect(QRectF(1, 1, 11, 11), inside)
            if glow:  # the orange rim XP gives a box the mouse is over
                rim = QLinearGradient(1, 1, 12, 12)
                rim.setColorAt(0, QColor("#FFF0CF"))
                rim.setColorAt(1, QColor("#F8B330"))
                p.fillRect(QRectF(1, 1, 11, 11), rim)
                p.fillRect(QRectF(3, 3, 7, 7), inside)
            if ticked:  # XP's tick, dot for dot
                for x, y in ((3, 5), (4, 6), (5, 7), (6, 6), (7, 5), (8, 4), (9, 3)):
                    p.fillRect(QRectF(x, y, 1, 3), QColor(tick))

        def arrow(p, way):
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#4D6185"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                          Qt.PenJoinStyle.MiterJoin))
            points = {"up": ((1, 6), (4.5, 2.5), (8, 6)), "down": ((1, 3), (4.5, 6.5), (8, 3)),
                      "left": ((6, 1), (2.5, 4.5), (6, 8)), "right": ((3, 1), (6.5, 4.5), (3, 8))}[way]
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

        def grip(p, upright):
            for at in range(0, 8, 2):
                for colour, shift in (("#EEF4FE", 0), ("#8CB0F8", 1)):
                    p.fillRect(QRectF(0, at + shift, 6, 1) if upright else QRectF(at + shift, 0, 1, 6),
                               QColor(colour))

        for name, ticked, edge, glow, tick in (
                ("box", False, "#1C5180", False, ""), ("box-on", True, "#1C5180", False, "#21A121"),
                ("box-over", False, "#1C5180", True, ""), ("box-on-over", True, "#1C5180", True, "#21A121"),
                ("box-off", False, "#CAC8BB", False, ""), ("box-on-off", True, "#CAC8BB", False, "#CAC8BB")):
            _picture(self.folder, name, 13, 13,
                     lambda p, t=ticked, e=edge, g=glow, c=tick: box(p, t, e, g, c or "#21A121"))
        for way in ("up", "down", "left", "right"):
            _picture(self.folder, f"arrow-{way}", 9, 9, lambda p, w=way: arrow(p, w))
        _picture(self.folder, "grip-upright", 6, 8, lambda p: grip(p, True))
        _picture(self.folder, "grip-flat", 8, 6, lambda p: grip(p, False))

    def sheet(self) -> str:
        at, sand = self.pictures(), self.SAND
        button = _slope(False, "#FFFFFF", (0.8, "#EFEEE8"), "#D8D2C4")
        pressed = _slope(False, "#D5D0C3", (0.2, "#E6E4DB"), "#F2F1EC")
        blue = lambda upright, light="#C9D8FC", dark="#AEC2F1": _slope(upright, light, dark)
        edge = lambda upright: "margin: 0 1px 0 1px;" if upright else "margin: 1px 0 1px 0;"
        handle = lambda upright: f"{edge(upright)} border: 1px solid #FFFFFF; border-radius: 3px; background: {blue(upright)};"
        return f"""
QWidget {{ font-family: Tahoma; font-size: 8pt; color: #000000; }}
QWidget#lookInside, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {sand}; }}
QScrollArea {{ border: none; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: #FFFFE1; color: #000000; border: 1px solid #000000; }}

QGroupBox {{ border: 1px solid #D0D0BF; border-radius: 4px; margin-top: 7px; padding-top: 8px;
            background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 8px;
                   padding: 0 3px; color: #0046D5; background: {sand}; }}

QPushButton {{ min-height: 19px; min-width: 60px; padding: 1px 10px; border: 1px solid #003C74;
              border-radius: 3px; background: {button}; }}
QPushButton:hover {{ border: 2px solid #F0A622; padding: 0px 9px; }}
QPushButton:focus {{ border: 2px solid #8BB0EA; padding: 0px 9px; }}
QPushButton:pressed {{ border: 1px solid #003C74; padding: 1px 10px; background: {pressed}; }}
QPushButton:disabled {{ color: #ACA899; border: 1px solid #C9C7BA; background: #F5F4EA; }}
{self.tick_boxes(at, "#ACA899")}

QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    border: 1px solid #7F9DB9; background: #FFFFFF; selection-background-color: #316AC5;
    selection-color: #FFFFFF; }}
QLineEdit {{ min-height: 17px; padding: 1px 2px; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {sand}; color: #ACA899; border: 1px solid #C9C7BA; }}

QComboBox {{ min-height: 19px; padding: 0px 3px; border: 1px solid #7F9DB9; background: #FFFFFF; }}
QComboBox:disabled {{ color: #ACA899; border: 1px solid #C9C7BA; background: {sand}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 15px;
                       margin: 1px; border: 1px solid #B7C6F0; border-radius: 2px;
                       background: {_slope(False, "#CAD9FD", "#A9BEEF")}; }}
QComboBox::drop-down:hover {{ background: {_slope(False, "#E0EAFF", "#C3D3FB")}; }}
QComboBox::down-arrow {{ image: url({at}/arrow-down.png); width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{ border: 1px solid #000000; background: #FFFFFF; outline: 0;
                              selection-background-color: #316AC5; selection-color: #FFFFFF; }}
""" + self.scroll_bars(
            at, "#F6F5EF", handle,
            lambda upright: f"background: {blue(upright, '#DCE7FF', '#C5D5FB')};",
            lambda upright: f"background: {blue(upright, '#A8BDF4', '#C0D0F8')};",
            "margin: 0px; border: 1px solid #FFFFFF; border-radius: 3px; "
            "background: qlineargradient(x1:0, y1:0, ACROSS, stop:0 #C9D8FC, stop:1 #AEC2F1);",
            "arrow", "grip") + self.more(
            at, "border: 1px solid #919B9C; background: #FCFCFE;", "#FCFCFE",
            "padding: 3px 9px; margin-top: 2px; margin-right: 1px; border: 1px solid #919B9C; "
            "border-bottom: none; border-top-left-radius: 3px; border-top-right-radius: 3px; "
            f"background: {_slope(False, '#FFFFFF', '#ECEBE6')};",
            "margin-top: 0px; background: #FCFCFE; border-top: 2px solid #E68B2C;",
            "border-top: 2px solid #FFC73C;",
            "padding: 3px 6px; border: none; border-right: 1px solid #C5C2B2; "
            "border-bottom: 2px solid #D6D2C2; background: #EBEADB;",
            "border: 1px solid #686868; border-radius: 3px; background: #FFFFFF;",
            f"margin: 1px; background: {_slope(False, '#B4F0B0', (0.5, '#34D043'), '#1FA82E')};")

    def paint_bar(self, p: QPainter, bar: QWidget) -> None:
        shade = QLinearGradient(0, 0, 0, bar.height())
        for at, colour in ((0.0, "#0058EE"), (0.05, "#3A93FF"), (0.12, "#288EFF"), (0.2, "#127DFF"),
                           (0.3, "#036FFC"), (0.45, "#0262EE"), (0.7, "#0057E5"), (0.88, "#0054E3"),
                           (0.96, "#0055EB"), (1.0, "#003DD7")):
            shade.setColorAt(at, QColor(colour))
        p.fillRect(bar.rect(), shade)
        left = _icon(p, bar, 7)
        font = QFont("Trebuchet MS", 10)
        font.setBold(True)
        p.setFont(font)
        room = QRect(left, 0, bar.width() - left - 56, bar.height())
        title = p.fontMetrics().elidedText(bar.window().windowTitle(), Qt.TextElideMode.ElideRight, room.width())
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        p.setPen(QColor("#0A1883"))  # its shadow
        p.drawText(room.translated(1, 1), flags, title)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(room, flags, title)

    def paint_button(self, p: QPainter, button) -> None:
        over, down = button.underMouse(), button.isDown()
        if button.kind == "close":
            top, bottom = ("#F0876F", "#C33A1C") if not over else ("#FF9F86", "#DC4B2A")
        else:
            top, bottom = ("#4B91F8", "#2459D9") if not over else ("#6BA9FF", "#3A72EE")
        if down:
            top, bottom = bottom, top
        fill = QLinearGradient(0, 0, 21, 21)
        fill.setColorAt(0, QColor(top))
        fill.setColorAt(1, QColor(bottom))
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0.5, 0.5, 20, 20), 3, 3)
        if button.kind == "close":
            p.setPen(QPen(QColor("#FFFFFF"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(6.5, 6.5), QPointF(14.5, 14.5))
            p.drawLine(QPointF(14.5, 6.5), QPointF(6.5, 14.5))
        else:
            p.setPen(QPen(QColor("#FFFFFF"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(QPointF(5.5, 14.5), QPointF(12, 14.5))


# ---- Windows 7, in its "Aero" glass -----------------------------------------------------------
class _Seven(_Look):
    key = "7"
    frame, bar, radius, round_bottom = 8, 30, 7, True
    FACE = "#F0F0F0"
    EDGE = "#8E9DB4"  # the line between the glass and what is inside
    # The glass can't be seen through here, so it is given the look of sky in it.
    window = ("border: 1px solid #55708F; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
              "stop:0 #B5CEEC, stop:0.18 #D6E5F7, stop:0.34 #BAD1EE, stop:0.55 #CFE0F5, "
              "stop:0.76 #B4CDEB, stop:1 #C7DBF2);")
    button_size = {"minimise": (29, 19), "close": (47, 19)}
    bar_margins = (0, 1, 7, 0)
    bar_spacing = 0
    menu = """
QMenu { background: #F0F0F0; border: 1px solid #979797; padding: 2px; font-family: "Segoe UI";
        font-size: 9pt; color: #000000; }
QMenu::item { padding: 4px 30px 4px 28px; margin: 0px 1px; border: 1px solid transparent;
              border-radius: 3px; background: transparent; }
QMenu::item:selected { border: 1px solid #AECFF7; color: #000000;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F3F9FE, stop:1 #D8ECFC); }
QMenu::item:disabled { color: #6D6D6D; }
QMenu::separator { height: 1px; background: #D7D7D7; margin: 3px 2px 3px 26px; }
"""

    def draw_pictures(self) -> None:
        def box(p, ticked, edge, face, inner_edge, light, dark, tick="#2E3B6E"):
            p.fillRect(QRectF(0, 0, 13, 13), QColor(edge))
            p.fillRect(QRectF(1, 1, 11, 11), QColor(face))
            p.fillRect(QRectF(2, 2, 9, 9), QColor(inner_edge))
            inside = QLinearGradient(3, 3, 10, 10)
            inside.setColorAt(0, QColor(dark))
            inside.setColorAt(1, QColor(light))
            p.fillRect(QRectF(3, 3, 7, 7), inside)
            if ticked:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(QColor(tick), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline(QPolygonF([QPointF(3.4, 6.6), QPointF(5.6, 9.2), QPointF(9.8, 3.4)]))

        def triangle(p, way, colour="#404040"):
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(colour))
            points = {"up": ((0.5, 6.5), (4.5, 2.5), (8.5, 6.5)), "down": ((0.5, 2.5), (4.5, 6.5), (8.5, 2.5)),
                      "left": ((6.5, 0.5), (2.5, 4.5), (6.5, 8.5)), "right": ((2.5, 0.5), (6.5, 4.5), (2.5, 8.5))}[way]
            p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))

        def grip(p, upright):
            for at in (0, 3, 6):
                for colour, shift in (("#8C8C8C", 0), ("#FFFFFF", 1)):
                    p.fillRect(QRectF(0, at + shift, 7, 1) if upright else QRectF(at + shift, 0, 1, 7),
                               QColor(colour))

        plain = ("#8E8F8F", "#F4F4F4", "#AEB3B9", "#FFFFFF", "#CFD3D8")
        over = ("#5586A3", "#DEF9FA", "#79C6F9", "#E9F7FE", "#B1DFFD")
        off = ("#B1B1B1", "#FBFBFB", "#D9D9D9", "#FFFFFF", "#EEEEEE")
        for name, ticked, colours, tick in (
                ("box", False, plain, ""), ("box-on", True, plain, "#2E3B6E"),
                ("box-over", False, over, ""), ("box-on-over", True, over, "#1F2F66"),
                ("box-off", False, off, ""), ("box-on-off", True, off, "#B1B1B1")):
            _picture(self.folder, name, 13, 13,
                     lambda p, t=ticked, c=colours, k=tick: box(p, t, *c, tick=k or "#2E3B6E"))
        for way in ("up", "down", "left", "right"):
            _picture(self.folder, f"arrow-{way}", 9, 9, lambda p, w=way: triangle(p, w))
        _picture(self.folder, "grip-upright", 7, 8, lambda p: grip(p, True))
        _picture(self.folder, "grip-flat", 8, 7, lambda p: grip(p, False))

    def sheet(self) -> str:
        at, face = self.pictures(), self.FACE
        button = _slope(False, "#F2F2F2", (0.5, "#EBEBEB"), (0.51, "#DDDDDD"), "#CFCFCF")
        over = _slope(False, "#EAF6FD", (0.5, "#D9F0FC"), (0.51, "#BEE6FD"), "#A7D9F5")
        down = _slope(False, "#E5F4FC", (0.5, "#C4E5F6"), (0.51, "#98D1EF"), "#68B3DB")
        return f"""
QWidget {{ font-family: "Segoe UI"; font-size: 9pt; color: #000000; }}
QWidget#lookInside {{ background: {face}; border: 1px solid {self.EDGE}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {face}; }}
QScrollArea {{ border: none; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: #FFFFFF; color: #575757; border: 1px solid #767676; }}

QGroupBox {{ border: 1px solid #D5DFE5; border-radius: 3px; margin-top: 9px; padding-top: 9px;
            background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 8px;
                   padding: 0 3px; color: #000000; background: {face}; }}

QPushButton {{ min-height: 21px; min-width: 62px; padding: 1px 12px; border: 1px solid #707070;
              border-radius: 3px; background: {button}; }}
QPushButton:hover {{ border: 1px solid #3C7FB1; background: {over}; }}
QPushButton:focus {{ border: 1px solid #3C7FB1; }}
QPushButton:pressed {{ border: 1px solid #2C628B; background: {down}; }}
QPushButton:disabled {{ color: #838383; border: 1px solid #ADB2B5; background: #F4F4F4; }}
{self.tick_boxes(at, "#838383")}

QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    border: 1px solid #ABADB3; background: #FFFFFF; selection-background-color: #3399FF;
    selection-color: #FFFFFF; }}
QLineEdit {{ min-height: 19px; padding: 1px 2px; }}
QLineEdit:hover, QPlainTextEdit:hover {{ border: 1px solid #5794BF; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid #3D7BAD; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {face}; color: #838383; border: 1px solid #D9D9D9; }}

QComboBox {{ min-height: 21px; padding: 0px 6px; border: 1px solid #707070; border-radius: 3px;
            background: {button}; }}
QComboBox:hover {{ border: 1px solid #3C7FB1; background: {over}; }}
QComboBox:disabled {{ color: #838383; border: 1px solid #ADB2B5; background: #F4F4F4; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 18px;
                       border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url({at}/arrow-down.png); width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{ border: 1px solid #828790; background: #FFFFFF; outline: 0;
                              selection-background-color: #3399FF; selection-color: #FFFFFF; }}
""" + self.scroll_bars(
            at, _slope(True, "#E3E3E3", (0.35, "#EEEEEE"), "#F4F4F4"),
            lambda upright: ("border: 1px solid #979797; border-radius: 2px; background: "
                             + _slope(upright, "#F5F5F5", (0.5, "#E9E9E9"), (0.51, "#D9D9D9"), "#C6C6C6") + ";"),
            lambda upright: ("border: 1px solid #3C7FB1; background: "
                             + _slope(upright, "#E3F4FC", (0.5, "#D6EEFB"), (0.51, "#A9DBF6"), "#9CCAE7") + ";"),
            lambda upright: ("border: 1px solid #15598A; background: "
                             + _slope(upright, "#CAECF9", (0.5, "#AFE1F7"), (0.51, "#6FCAF0"), "#66BAE0") + ";"),
            "border: 1px solid transparent; border-radius: 2px; background: transparent;",
            "arrow", "grip") + f"""
QScrollBar::sub-line:hover, QScrollBar::add-line:hover {{ border: 1px solid #3C7FB1;
    background: {_slope(True, "#E3F4FC", (0.5, "#D6EEFB"), (0.51, "#A9DBF6"), "#9CCAE7")}; }}
""" + self.more(
            at, "border: 1px solid #898C95; background: #FFFFFF;", "#FFFFFF",
            f"padding: 3px 10px; margin-top: 2px; border: 1px solid #898C95; border-bottom: none; background: {button};",
            "margin-top: 0px; background: #FFFFFF;",
            f"border: 1px solid #3C7FB1; border-bottom: none; background: {over};",
            "padding: 4px 6px; border: none; border-right: 1px solid #E0E5EE; "
            f"border-bottom: 1px solid #D5D5D5; background: {_slope(False, '#FFFFFF', '#F2F3F5')};",
            "border: 1px solid #B2B2B2; border-radius: 2px; background: #E6E6E6;",
            f"background: {_slope(False, '#C5F5CD', (0.5, '#36D455'), (0.51, '#0CB82F'), '#3BD95F')};")

    def paint_bar(self, p: QPainter, bar: QWidget) -> None:
        left = _icon(p, bar, 8)
        p.setFont(QFont("Segoe UI", 9))
        room = QRect(left, 0, bar.width() - left - 96, bar.height())
        title = p.fontMetrics().elidedText(bar.window().windowTitle(), Qt.TextElideMode.ElideRight, room.width())
        flags = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        p.setPen(QColor(255, 255, 255, 46))  # the white glow Windows 7 puts behind a title
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy <= 10:
                    p.drawText(room.translated(dx, dy), flags, title)
        p.setPen(QColor("#000000"))
        p.drawText(room, flags, title)

    def paint_button(self, p: QPainter, button) -> None:
        """One of the glass buttons that hang from the top edge: the wide red one closes."""
        w, h = button.width(), button.height()
        over, down, close = button.underMouse(), button.isDown(), button.kind == "close"
        shape = QPainterPath()  # square above; rounded below, on its outer side only
        left_round, right_round = (0, 4) if close else (4, 0)
        shape.moveTo(0.5, 0)
        shape.lineTo(0.5, h - 0.5 - left_round)
        shape.quadTo(0.5, h - 0.5, 0.5 + left_round, h - 0.5)
        shape.lineTo(w - 0.5 - right_round, h - 0.5)
        shape.quadTo(w - 0.5, h - 0.5, w - 0.5, h - 0.5 - right_round)
        shape.lineTo(w - 0.5, 0)
        fill = QLinearGradient(0, 0, 0, h)
        if close:
            stops = (("#F0B5A8", "#DE7565", "#C83320", "#D9685A") if not over else
                     ("#FCC6B9", "#F27C6A", "#E0301A", "#F59079"))
            if down:
                stops = ("#D8A294", "#C25C4C", "#A32413", "#B94E40")
        elif down:
            stops = ("#9FC6E6", "#74A9D6", "#3C7EB8", "#63A6D4")
        elif over:
            stops = ("#D6ECFB", "#A6D3F3", "#5FAEE4", "#8FD3F5")
        else:
            stops = (QColor(255, 255, 255, 150), QColor(255, 255, 255, 95),
                     QColor(255, 255, 255, 35), QColor(255, 255, 255, 80))
        for at, colour in zip((0.0, 0.48, 0.5, 1.0), stops):
            fill.setColorAt(at, QColor(colour))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(60, 82, 112, 215), 1))
        p.setBrush(fill)
        p.drawPath(shape)
        p.setPen(QPen(QColor(255, 255, 255, 110), 1))  # the glint just inside the edge
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(1.5, 0.5), QPointF(1.5, h - 4))
        p.drawLine(QPointF(w - 1.5, 0.5), QPointF(w - 1.5, h - 4))
        cx, cy = w / 2, h / 2
        if close:
            for colour, width in ((QColor(70, 20, 12, 150), 4.2), (QColor("#FFFFFF"), 2.2)):
                p.setPen(QPen(colour, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx - 4, cy - 3.5), QPointF(cx + 4, cy + 3.5))
                p.drawLine(QPointF(cx + 4, cy - 3.5), QPointF(cx - 4, cy + 3.5))
        else:
            p.setPen(QPen(QColor(40, 55, 80, 200), 1))
            p.setBrush(QColor("#FFFFFF"))
            p.drawRoundedRect(QRectF(cx - 5.5, cy + 1.5, 11, 4), 1, 1)


class _SevenBlue(_Seven):
    """Windows 7 as it looked with its blue wallpaper behind the glass: the same window,
    with the frame the bright sky blue that showed through. The colours are taken from a
    picture of one."""
    key = "7blue"
    EDGE = "#7092A2"
    window = ("border: 1px solid #3B5F65; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
              "stop:0 #D8EFF9, stop:0.16 #BDE7F7, stop:0.3 #CFEEFA, stop:0.46 #A6E0F5, "
              "stop:0.62 #B8E7F8, stop:0.8 #8FD8F0, stop:1 #7CD2EA);")


# ---- Windows 10: flat, square and plain ---------------------------------------------------------
class _Ten(_Look):
    key = "10"
    frame, top, bar, radius, round_bottom = 1, 1, 31, 0, False
    FACE = "#F0F0F0"
    window = "background: #8A8A8A;"  # the hairline round the window
    button_size = (46, 30)
    bar_margins = (0, 0, 0, 1)
    bar_spacing = 0
    menu = """
QMenu { background: #F2F2F2; border: 1px solid #CCCCCC; padding: 3px 0px; font-family: "Segoe UI";
        font-size: 9pt; color: #000000; }
QMenu::item { padding: 5px 36px 5px 32px; background: transparent; }
QMenu::item:selected { background: #DADADA; color: #000000; }
QMenu::item:disabled { color: #6D6D6D; }
QMenu::separator { height: 1px; background: #D7D7D7; margin: 4px 0px 4px 0px; }
"""

    def draw_pictures(self) -> None:
        def box(p, ticked, edge, tick="#000000", face="#FFFFFF"):
            p.fillRect(QRectF(0, 0, 13, 13), QColor(edge))
            p.fillRect(QRectF(1, 1, 11, 11), QColor(face))
            if ticked:
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setPen(QPen(QColor(tick), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap,
                              Qt.PenJoinStyle.MiterJoin))
                p.drawPolyline(QPolygonF([QPointF(3.0, 6.6), QPointF(5.3, 9.0), QPointF(10.0, 3.8)]))

        def chevron(p, way, colour="#606060"):
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor(colour), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap,
                          Qt.PenJoinStyle.MiterJoin))
            points = {"up": ((1.5, 6), (4.5, 3), (7.5, 6)), "down": ((1.5, 3), (4.5, 6), (7.5, 3)),
                      "left": ((6, 1.5), (3, 4.5), (6, 7.5)), "right": ((3, 1.5), (6, 4.5), (3, 7.5))}[way]
            p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))

        for name, ticked, edge, tick, face in (
                ("box", False, "#333333", "", "#FFFFFF"), ("box-on", True, "#333333", "#000000", "#FFFFFF"),
                ("box-over", False, "#0078D7", "", "#FFFFFF"), ("box-on-over", True, "#0078D7", "#0078D7", "#FFFFFF"),
                ("box-off", False, "#CCCCCC", "", "#E6E6E6"), ("box-on-off", True, "#CCCCCC", "#A0A0A0", "#E6E6E6")):
            _picture(self.folder, name, 13, 13,
                     lambda p, t=ticked, e=edge, k=tick, f=face: box(p, t, e, k or "#000000", f))
        for way in ("up", "down", "left", "right"):
            _picture(self.folder, f"arrow-{way}", 9, 9, lambda p, w=way: chevron(p, w))
        _picture(self.folder, "drop", 9, 9, lambda p: chevron(p, "down", "#000000"))

    def sheet(self) -> str:
        at, face = self.pictures(), self.FACE
        flat = lambda colour: lambda upright: f"border: none; margin: 0px; background: {colour};"
        return f"""
QWidget {{ font-family: "Segoe UI"; font-size: 9pt; color: #000000; }}
QWidget#lookInside, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {face}; }}
QScrollArea {{ border: none; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: #FFFFFF; color: #575757; border: 1px solid #767676; }}

QGroupBox {{ border: 1px solid #DCDCDC; margin-top: 9px; padding-top: 9px; background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 8px;
                   padding: 0 3px; color: #000000; background: {face}; }}

QPushButton {{ min-height: 21px; min-width: 62px; padding: 1px 12px; border: 1px solid #ADADAD;
              background: #E1E1E1; }}
QPushButton:focus {{ border: 2px solid #0078D7; padding: 0px 11px; }}
QPushButton:hover {{ border: 1px solid #0078D7; padding: 1px 12px; background: #E5F1FB; }}
QPushButton:pressed {{ border: 1px solid #005499; padding: 1px 12px; background: #CCE4F7; }}
QPushButton:disabled {{ color: #838383; border: 1px solid #BFBFBF; background: #CCCCCC; }}
{self.tick_boxes(at, "#838383")}

QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    border: 1px solid #7A7A7A; background: #FFFFFF; selection-background-color: #0078D7;
    selection-color: #FFFFFF; }}
QLineEdit {{ min-height: 19px; padding: 1px 2px; }}
QLineEdit:hover, QPlainTextEdit:hover {{ border: 1px solid #171717; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid #0078D7; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ background: {face}; color: #838383; border: 1px solid #CCCCCC; }}

QComboBox {{ min-height: 21px; padding: 0px 6px; border: 1px solid #ADADAD; background: #E1E1E1; }}
QComboBox:hover {{ border: 1px solid #0078D7; background: #E5F1FB; }}
QComboBox:disabled {{ color: #838383; border: 1px solid #BFBFBF; background: #CCCCCC; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 20px;
                       border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url({at}/drop.png); width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{ border: 1px solid #999999; background: #FFFFFF; outline: 0;
                              selection-background-color: #0078D7; selection-color: #FFFFFF; }}
""" + self.scroll_bars(at, face, flat("#CDCDCD"), flat("#A6A6A6"), flat("#606060"),
                         f"border: none; background: {face};", "arrow", "") + """
QScrollBar::sub-line:hover, QScrollBar::add-line:hover { background: #DADADA; }
QScrollBar::sub-line:pressed, QScrollBar::add-line:pressed { background: #A6A6A6; }
""" + self.more(
            at, "border: 1px solid #D9D9D9; background: #FFFFFF;", "#FFFFFF",
            "padding: 4px 10px; margin-top: 2px; border: 1px solid #D9D9D9; border-bottom: none; background: #F0F0F0;",
            "margin-top: 0px; background: #FFFFFF;", "background: #D8EAF9;",
            "padding: 4px 6px; border: none; border-right: 1px solid #E5E5E5; "
            "border-bottom: 1px solid #E5E5E5; background: #FFFFFF;",
            "border: 1px solid #BCBCBC; background: #E6E6E6;", "background: #06B025;")

    def paint_bar(self, p: QPainter, bar: QWidget) -> None:
        p.fillRect(bar.rect(), QColor("#FFFFFF"))
        left = _icon(p, bar, 8)
        p.setFont(QFont("Segoe UI", 9))
        room = QRect(left, 0, bar.width() - left - 100, bar.height())
        title = p.fontMetrics().elidedText(bar.window().windowTitle(), Qt.TextElideMode.ElideRight, room.width())
        p.setPen(QColor("#000000"))
        p.drawText(room, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)

    def paint_button(self, p: QPainter, button) -> None:
        """A flat button with a thin sign on it: grey under the mouse, and red for close."""
        over, down, close = button.underMouse(), button.isDown(), button.kind == "close"
        if over or down:
            p.fillRect(button.rect(), QColor(("#F1707A" if down else "#E81123") if close else
                                             ("#CCCCCC" if down else "#E5E5E5")))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, close)
        p.setPen(QPen(QColor("#FFFFFF" if close and (over or down) else "#000000"), 1))
        cx, cy = button.width() // 2, button.height() // 2
        if close:
            p.drawLine(QPointF(cx - 4.5, cy - 4.5), QPointF(cx + 5.5, cy + 5.5))
            p.drawLine(QPointF(cx + 5.5, cy - 4.5), QPointF(cx - 4.5, cy + 5.5))
        else:
            p.drawLine(QPointF(cx - 5, cy + 0.5), QPointF(cx + 5, cy + 0.5))


_LOOKS = {look.key: look for look in (_Ten(), _Seven(), _SevenBlue(), _XP())}


def _icon(p: QPainter, bar: QWidget, left: int) -> int:
    """Draw the window's icon at `left`, if it has one. Returns where the title goes."""
    icon = bar.window().windowIcon()
    if icon.isNull():
        return left
    icon.paint(p, QRect(left, (bar.height() - 16) // 2, 16, 16))
    return left + 21


def menu(key: str) -> str:
    """The style sheet that gives a menu the look `key`: nothing, for Windows' own."""
    return _LOOKS[key].menu if key in _LOOKS else ""


# ---- the title bar --------------------------------------------------------------------------
class _BarButton(QAbstractButton):
    """A button at the right of a title bar: "close" or "minimise"."""

    def __init__(self, kind: str, parent, look: _Look):
        super().__init__(parent)
        self.kind, self.look = kind, look
        size = look.button_size
        self.setFixedSize(*(size[kind] if isinstance(size, dict) else size))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Close" if kind == "close" else "Minimise")

    def enterEvent(self, event) -> None:
        self.update()

    def leaveEvent(self, event) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.look.paint_button(p, self)
        p.end()


class TitleBar(QWidget):
    """The look's title bar: the window's icon and name, and buttons to minimise and
    close. It is what the window is moved by."""

    def __init__(self, window: QWidget, look: _Look, minimise: bool = True):
        super().__init__(window)
        self.look = look
        self.setFixedHeight(look.bar)
        row = QHBoxLayout(self)
        row.setContentsMargins(*look.bar_margins)
        row.setSpacing(look.bar_spacing)
        row.addStretch()
        top = look.bar_margins[1] > 0  # hung from the top edge, or set in the middle
        for kind, action in (("minimise", window.showMinimized), ("close", window.close)):
            if kind == "minimise" and not minimise:
                continue
            button = _BarButton(kind, self, look)
            button.clicked.connect(action)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.look.paint_bar(p, self)
        p.end()


# ---- dressing a window ------------------------------------------------------------------------
class _Grip(QWidget):
    """A strip along an edge of a dressed window, or a square at a bottom corner, by which
    the window is resized. It can't be seen. The sizing arrow belongs to the strip and to
    nothing else, so the pointer has it only while it is over the edge."""

    def __init__(self, window: QWidget, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemResize(self.edges)


class _Frame(QObject):
    """Does for a dressed window what its own frame did: lets it be resized by its edges,
    and keeps the look's rounded corners cut out."""

    REACH = 5    # how far in from the edge the window can be taken hold of, at the least
    CORNER = 14  # and how far along from a bottom corner counts as the corner

    def __init__(self, window: QWidget, look: _Look, resizable: bool = True):
        super().__init__(window)
        self.window, self.look = window, look
        left, right, bottom = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.BottomEdge
        self.grips = [_Grip(window, edges, cursor) for edges, cursor in (
            (left, Qt.CursorShape.SizeHorCursor), (right, Qt.CursorShape.SizeHorCursor),
            (bottom, Qt.CursorShape.SizeVerCursor),
            (bottom | left, Qt.CursorShape.SizeBDiagCursor),
            (bottom | right, Qt.CursorShape.SizeFDiagCursor))] if resizable else []
        window.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.cut_corners()
            self.place_grips()
        return False

    def place_grips(self) -> None:
        w, h = self.window.width(), self.window.height()
        reach, corner = max(self.look.frame, self.REACH), self.CORNER
        top = self.look.top + self.look.bar  # beside the title bar the window is moved, not sized
        for grip, place in zip(self.grips, (
                (0, top, reach, h - top - corner), (w - reach, top, reach, h - top - corner),
                (corner, h - reach, w - 2 * corner, reach),
                (0, h - corner, corner, corner), (w - corner, h - corner, corner, corner))):
            grip.setGeometry(*place)
            grip.raise_()

    def cut_corners(self) -> None:
        size, radius = self.window.size(), self.look.radius
        if not radius:
            self.window.clearMask()
            return
        shape = QBitmap(size)
        shape.fill(Qt.GlobalColor.color0)
        p = QPainter(shape)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        if self.look.round_bottom:
            p.drawRoundedRect(QRectF(0, 0, size.width(), size.height()), radius, radius)
        else:
            # Two shapes drawn one over the other: a rounded top, and all under it square.
            # (As one path they cancelled where they overlapped, and only a strip showed.)
            p.drawRoundedRect(QRectF(0, 0, size.width(), min(size.height(), 40)), radius, radius)
            if size.height() > 16:
                p.drawRect(QRectF(0, 16, size.width(), size.height() - 16))
        p.end()
        self.window.setMask(shape)


def known(key: str) -> bool:
    """Whether `key` is a look this dresses windows in: not Windows' own."""
    return key in _LOOKS


def dress(window: QWidget, key: str, minimise: bool = True, resizable: bool = True) -> QSize:
    """Give `window`, which has a layout and hasn't been shown yet, the look `key`.
    Returns how much bigger its frame makes it than what is inside: nothing, if `key`
    is Windows' own look and the window is left as it is. What kind of window it is
    (one that stays on top, a dialog) is kept."""
    look = _LOOKS.get(key)
    if look is None:
        return QSize(0, 0)
    inside = QWidget(window)
    inside.setObjectName("lookInside")
    inside.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    inside.setLayout(window.layout())  # what the window held is now held by `inside`
    outer = QVBoxLayout(window)
    outer.setContentsMargins(look.frame, look.top, look.frame, look.frame)
    outer.setSpacing(0)
    outer.addWidget(TitleBar(window, look, minimise))
    outer.addWidget(inside, 1)
    window.setWindowFlags(window.windowFlags() | Qt.WindowType.FramelessWindowHint
                          | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint)
    window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    window.setObjectName("lookWindow")
    window.setStyleSheet(f"QWidget#lookWindow {{ {look.window} }}" + look.sheet())
    window.look_frame = _Frame(window, look, resizable)  # kept alive with the window
    return QSize(2 * look.frame, look.top + look.bar + look.frame)


def message(parent: QWidget, key: str, title: str, text: str, kind: str = "warning",
            buttons=("OK",)) -> str:
    """Say something in a small window of the look `key`, and wait for an answer. Returns
    the button that was pressed, or "" if the window was closed. `kind` is "warning",
    "information" or "question", for the picture beside the words."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 10)
    layout.setSpacing(14)
    row = QHBoxLayout()
    row.setSpacing(12)
    picture = QLabel()
    icon = {"information": QStyle.StandardPixmap.SP_MessageBoxInformation,
            "question": QStyle.StandardPixmap.SP_MessageBoxQuestion}.get(
                kind, QStyle.StandardPixmap.SP_MessageBoxWarning)
    picture.setPixmap(dialog.style().standardIcon(icon).pixmap(32, 32))
    row.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop)
    words = QLabel(text)
    words.setWordWrap(True)
    words.setMinimumWidth(280)
    words.setMaximumWidth(460)
    row.addWidget(words, 1)
    layout.addLayout(row)
    answer = [""]
    foot = QHBoxLayout()
    foot.addStretch()
    for at, name in enumerate(buttons):
        button = QPushButton(name)
        button.setDefault(at == 0)
        button.clicked.connect(lambda _=False, name=name: (answer.__setitem__(0, name), dialog.accept()))
        foot.addWidget(button)
    layout.addLayout(foot)
    dress(dialog, key, minimise=False, resizable=False)
    dialog.exec()
    return answer[0]
