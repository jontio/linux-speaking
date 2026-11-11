"""A small window with three text boxes, for scripts/test-form.sh to dictate into."""
import sys

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QTextEdit, QVBoxLayout, QWidget

app = QApplication(sys.argv)
app.setApplicationName("ls-test-form")
window = QWidget()
window.setWindowTitle("Linux Speaking test form")
layout = QVBoxLayout(window)
line = QLineEdit()
line.setAccessibleName("line")
editor = QTextEdit()
editor.setAccessibleName("editor")
secret = QLineEdit()
secret.setEchoMode(QLineEdit.EchoMode.Password)
secret.setAccessibleName("secret")
for label, widget in (("One line", line), ("Several lines", editor), ("Password", secret)):
    layout.addWidget(QLabel(label))
    layout.addWidget(widget)
window.resize(420, 320)
window.show()
sys.exit(app.exec())
