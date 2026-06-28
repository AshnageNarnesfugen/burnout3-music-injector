#!/usr/bin/env python3
"""BURNOUT 3: TAKEDOWN — Custom Music Injector — entry point.

The code is split into two packages:
  core/  — pure logic (no Qt): the PS-ADPCM encoder, the audio pipeline, RWS/ISO
           parsing, and the EA-TRAX / portable-ISO builders.
  ui/    — the PySide6/Qt6 presentation layer (widgets, workers, the main window).

This launcher just wires up the QApplication and shows the window.

INSTALL:  pip install PySide6   ·   ffmpeg + gcc (Arch: sudo pacman -S ffmpeg gcc)
RUN:      python3 burnout3_gui.py
"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QPalette, QIcon

from ui.style import STYLESHEET
from ui.resources import _resource_path
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(QIcon(_resource_path("bnmex.ico")))
    p = QPalette()
    for role, color in [(QPalette.ColorRole.Window,"#0d0d0d"),(QPalette.ColorRole.WindowText,"#e0e0e0"),
        (QPalette.ColorRole.Base,"#111"),(QPalette.ColorRole.Text,"#e0e0e0"),
        (QPalette.ColorRole.Button,"#1e1e1e"),(QPalette.ColorRole.ButtonText,"#ccc"),
        (QPalette.ColorRole.Highlight,"#ff4500"),(QPalette.ColorRole.HighlightedText,"#fff")]:
        p.setColor(role, QColor(color))
    app.setPalette(p)
    w = MainWindow(); w.show(); sys.exit(app.exec())


if __name__ == "__main__":
    main()
