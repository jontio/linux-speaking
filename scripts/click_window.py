"""A small window with things to press, for scripts/test-click.sh. Each thing writes a file
when it is pressed, so the test can tell. It closes by itself."""
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QCheckBox, QPushButton, QVBoxLayout, QWidget

made = sys.argv[1]
app = QApplication(sys.argv)
window = QWidget()
window.setWindowTitle("Linux Speaking: a test of clicking")
layout = QVBoxLayout(window)
button = QPushButton("Press &me")
button.clicked.connect(lambda: open(made + ".button", "w").close())
tick = QCheckBox("Remember my choice")
tick.toggled.connect(lambda on: open(made + ".tick", "w").close())
greyed = QPushButton("Not this one")
greyed.setEnabled(False)
greyed.clicked.connect(lambda: open(made + ".greyed", "w").close())
for widget in (button, tick, greyed):
    layout.addWidget(widget)
QTimer.singleShot(25000, app.quit)
window.show()
window.raise_()
window.activateWindow()
sys.exit(app.exec())
