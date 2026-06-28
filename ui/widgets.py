"""Drag-and-drop widgets: the ISO drop zone and the audio drop table."""
import os

from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QFileDialog, QTableWidget, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal

from core.constants import AUDIO_EXTENSIONS


# ─── ISO Drop Zone ────────────────────────────────────────────────────────
class ISODropZone(QFrame):
    iso_dropped = Signal(str)
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self._set_idle_style()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl = QLabel("📀")
        self.icon_lbl.setStyleSheet("font-size:36px;border:none")
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon_lbl)
        self.text_lbl = QLabel("Drag your Burnout 3 ISO here\nor click to browse")
        self.text_lbl.setStyleSheet("color:#666;font-size:13px;border:none;font-weight:bold")
        self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.text_lbl)
        self.path_lbl = QLabel("")
        self.path_lbl.setStyleSheet("color:#4fc3f7;font-size:10px;border:none")
        self.path_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.path_lbl)

    def _set_idle_style(self):
        self.setStyleSheet("QFrame{background:#0e0e0e;border:2px dashed #333;border-radius:12px}")

    def set_iso_path(self, path):
        self.text_lbl.setText(f"📀  {os.path.basename(path)}")
        self.text_lbl.setStyleSheet("color:#69f0ae;font-size:14px;border:none;font-weight:bold")
        self.path_lbl.setText(path)
        self.setStyleSheet("QFrame{background:rgba(255,69,0,0.05);border:2px solid rgba(105,240,174,0.3);border-radius:12px}")

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(self, "Select ISO", "",
            "ISO Files (*.iso *.ISO *.bin *.BIN);;All (*)")
        if path:
            self.iso_dropped.emit(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                local = u.toLocalFile()
                if not local:
                    continue
                if os.path.splitext(local)[1].lower() in ('.iso','.bin'):
                    self.setStyleSheet("QFrame{background:rgba(255,69,0,0.1);border:2px dashed #ff4500;border-radius:12px}")
                    e.acceptProposedAction(); return

    def dragLeaveEvent(self, e):
        self._set_idle_style()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if not p:
                continue
            if os.path.splitext(p)[1].lower() in ('.iso','.bin') and os.path.isfile(p):
                self.iso_dropped.emit(p); e.acceptProposedAction(); return


# ─── Audio Drop Table ─────────────────────────────────────────────────────
class TrackTable(QTableWidget):
    files_dropped = Signal(list)
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        if not e.mimeData().hasUrls(): return
        files = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXTENSIONS:
                files.append(p)
            elif os.path.isdir(p):                       # recurse so album/disc subfolders are included
                for root, _dirs, fs in os.walk(p):
                    for f in sorted(fs):
                        if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS:
                            files.append(os.path.join(root, f))
        if files: self.files_dropped.emit(files)
        e.acceptProposedAction()
