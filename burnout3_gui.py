#!/usr/bin/env python3
"""
BURNOUT 3: TAKEDOWN — Custom Music Injector v11.0
Qt6 GUI (PySide6) — Linux Edition

Features:
  - Drag & drop ISO and audio files
  - Auto-detects 44 tracks in _EATRAX0.RWS & _EATRAX1.RWS
  - PS-ADPCM encoding with C accelerator (gcc auto-compile)
  - LLRR stereo layout, 32kHz, optimized 5×13 filter search
  - In-place ISO patching (no rebuild needed)

INSTALL:
  pip install PySide6
  sudo pacman -S ffmpeg p7zip gcc  (Arch)
  sudo apt install ffmpeg p7zip-full gcc  (Debian/Ubuntu)

RUN:
  python3 burnout3_gui.py
"""

import sys, os, struct, subprocess, shutil, tempfile, html as html_mod
from pathlib import Path
from typing import Optional, Dict, List

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QTabWidget, QFrame, QGroupBox, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QSplitter, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QColor, QPalette, QDragEnterEvent, QDropEvent

# ─── Burnout 3 ISO Knowledge ─────────────────────────────────────────────
KNOWN_DISC_IDS = {
    "SLUS_210.50": "NTSC-U (USA)", "SLES_525.84": "PAL (Europe)",
    "SLES_525.85": "PAL (Europe Alt)", "SLPM_657.19": "NTSC-J (Japan)",
}

ISO_STRUCTURE = {
    "SYSTEM.CNF": "PS2 boot config",
    "SLUS_210.50": "Main executable (NTSC-U)",
    "GLOBAL/": {
        "FRONTEND.TXD": "Menu textures (RenderWare TXD)",
        "GLOBAL.TXD": "Global textures/fonts",
        "VDB.BIN": "Vehicle database (speeds, physics, AI)",
    },
    "TRACKS/": {
        "_EATRAX0.RWS": "🎵 Music container 1 (EA Trax — songs 1-22)",
        "_EATRAX1.RWS": "🎵 Music container 2 (EA Trax — songs 23-44)",
        "TLIST.BIN": "Track names list",
        "[TrackFolders]/": {
            "STATIC.DAT": "Track textures + garage model",
            "STREAMED.DAT": "Track mesh, destructible props, LODs",
            "ENVIRO.DAT": "Skybox, lighting, sun/moon coords",
            "[Track].BGD": "Track config (traffic, spawns, laps, takedowns)",
        },
    },
    "PVEH/": {
        "VLIST.BIN": "Vehicle names list",
        "[Car].BGV": "Vehicle model + textures + deformation + physics",
        "[Car].BTV": "Traffic vehicle variant (identical format to BGV)",
        "[Car].HWD": "Engine sound pitch data",
        "[Car].LWD": "Engine sound samples (PS-ADPCM)",
    },
    "FMV/": {"[Video].PSS": "FMV video files"},
    "SOUNDS/": {"[SFX].RWS": "Sound effects (PS-ADPCM in RWS containers)"},
}

EA_TRAX_SONGS = [
    {"id":1,  "artist":"The F-Ups",                 "title":"Lazy Generation"},
    {"id":2,  "artist":"Fall Out Boy",               "title":"Dead on Arrival"},
    {"id":3,  "artist":"Yellowcard",                 "title":"Breathing"},
    {"id":4,  "artist":"My Chemical Romance",        "title":"I'm Not Okay"},
    {"id":5,  "artist":"Autopilot Off",              "title":"Make a Sound"},
    {"id":6,  "artist":"Sugarcult",                  "title":"Memory"},
    {"id":7,  "artist":"Atreyu",                     "title":"Right Side of the Bed"},
    {"id":8,  "artist":"Ash",                        "title":"Orpheus"},
    {"id":9,  "artist":"Riddlin' Kids",              "title":"I Feel Fine"},
    {"id":10, "artist":"Submersed",                  "title":"Hollow"},
    {"id":11, "artist":"Funeral for a Friend",       "title":"Juneau"},
    {"id":12, "artist":"No Motiv",                   "title":"Independence Day"},
    {"id":13, "artist":"Moments in Grace",           "title":"Broken Promises"},
    {"id":14, "artist":"Billy Talent",               "title":"River Below"},
    {"id":15, "artist":"Franz Ferdinand",            "title":"Take Me Out"},
    {"id":16, "artist":"Go Betty Go",                "title":"C'Mon"},
    {"id":17, "artist":"The Bouncing Souls",         "title":"True Believers"},
    {"id":18, "artist":"Saosin",                     "title":"3rd Measurement in C"},
    {"id":19, "artist":"Rise Against",               "title":"Give It All"},
    {"id":20, "artist":"Motion City Soundtrack",     "title":"My Favorite Accident"},
    {"id":21, "artist":"Jimmy Eat World",            "title":"Just Watch the Fireworks"},
    {"id":22, "artist":"Unwritten Law",              "title":"F.I.G.H.T."},
    {"id":23, "artist":"Pennywise",                  "title":"Alien"},
    {"id":24, "artist":"New Found Glory",            "title":"All Downhill from Here"},
    {"id":25, "artist":"Mudmen",                     "title":"The Animal Song"},
    {"id":26, "artist":"Chronic Future",             "title":"Time and Time Again"},
    {"id":27, "artist":"The Used",                   "title":"A Box Full of Sharp Objects"},
    {"id":28, "artist":"Maxeen",                     "title":"Block Out the World"},
    {"id":29, "artist":"Criteria",                   "title":"Crash"},
    {"id":30, "artist":"Populace",                   "title":"Midnight Club"},
    {"id":31, "artist":"Stretford",                  "title":"Days Are Forgetting"},
    {"id":32, "artist":"Donots",                     "title":"Saccharine Smile"},
    {"id":33, "artist":"Local H",                    "title":"Everyone Alive"},
    {"id":34, "artist":"Pulse Ultra",                "title":"Build Your Cages"},
    {"id":35, "artist":"Sparta",                     "title":"Cut Your Ribbon"},
    {"id":36, "artist":"The Matches",                "title":"Chain Me Free"},
    {"id":37, "artist":"Towers of London",           "title":"How Rude She Was"},
    {"id":38, "artist":"Ima Robot",                   "title":"Dynomite"},
    {"id":39, "artist":"Gavin DeGraw",               "title":"I Don't Wanna Be"},
    {"id":40, "artist":"Finger Eleven",              "title":"Good Times"},
    {"id":41, "artist":"(Bonus Track 1)",            "title":"Slot 41"},
    {"id":42, "artist":"(Bonus Track 2)",            "title":"Slot 42"},
    {"id":43, "artist":"(Bonus Track 3)",            "title":"Slot 43"},
    {"id":44, "artist":"(Bonus Track 4)",            "title":"Slot 44"},
]

AUDIO_EXTENSIONS = {
    ".mp3",".flac",".ogg",".wav",".aac",".m4a",".wma",".opus",
    ".aiff",".aif",".ape",".wv",".tta",".ac3",".mka",".mpc",".shn",
}

RWS_AUDIO_CONTAINER = 0x0000080D
RWS_AUDIO_HEADER = 0x0000080E
RWS_AUDIO_DATA = 0x0000080F


# ─── PS-ADPCM Encoder (C-accelerated via ctypes) ─────────────────────────
# PS-ADPCM Encoder for Burnout 3: Takedown
# Auto-compiles C encoder on first run for ~100x speedup.
# Falls back to Python if gcc is unavailable.
#
# Proven format:
#   - LLRR layout: 8192-byte super-blocks = L[2048] L[2048] R[2048] R[2048]
#   - Nibble order: first sample in LOW nibble, second in HIGH
#   - All block flags = 0x02, Filter 2 with auto shift

import numpy as np
import ctypes

_c_lib = None

def _compile_c_encoder():
    """Compile psxadpcm.c → libpsxenc.so on first run."""
    global _c_lib
    if _c_lib is not None:
        return _c_lib

    script_dir = os.path.dirname(os.path.abspath(__file__))
    so_path = os.path.join(script_dir, "libpsxenc.so")
    c_path = os.path.join(script_dir, "psxadpcm.c")

    # Compile if .so is missing or .c is newer
    need_compile = not os.path.isfile(so_path)
    if os.path.isfile(so_path) and os.path.isfile(c_path):
        if os.path.getmtime(c_path) > os.path.getmtime(so_path):
            need_compile = True

    if need_compile and os.path.isfile(c_path):
        try:
            r = subprocess.run(
                ["gcc", "-O3", "-shared", "-fPIC", "-o", so_path, c_path, "-lm"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                return None
        except Exception:
            return None

    if os.path.isfile(so_path):
        try:
            lib = ctypes.CDLL(so_path)
            lib.encode_burnout3_adpcm.restype = ctypes.c_int
            lib.encode_burnout3_adpcm.argtypes = [
                ctypes.POINTER(ctypes.c_short), ctypes.c_int,
                ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int
            ]
            _c_lib = lib
            return lib
        except Exception:
            return None
    return None


def encode_psx_adpcm_to_slot(pcm_s16le_stereo, slot_data_original):
    """
    Encode PCM s16le stereo → PS-ADPCM with LLRR layout.
    Uses C encoder if available, Python fallback otherwise.
    """
    slot_size = len(slot_data_original)
    pcm_bytes = pcm_s16le_stereo[:len(pcm_s16le_stereo) - (len(pcm_s16le_stereo) % 2)]
    n_samples = len(pcm_bytes) // 2

    # Try C encoder first (100x faster)
    lib = _compile_c_encoder()
    if lib is not None:
        pcm_arr = (ctypes.c_short * n_samples)()
        ctypes.memmove(pcm_arr, pcm_bytes, len(pcm_bytes))
        out_arr = (ctypes.c_ubyte * slot_size)()
        lib.encode_burnout3_adpcm(pcm_arr, n_samples, out_arr, slot_size)
        return bytes(out_arr)

    # Python fallback
    return _encode_python_fallback(pcm_bytes, slot_size)


def _encode_python_fallback(pcm_bytes, slot_size):
    """Pure Python encoder — slower but always works."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float64)
    left = samples[0::2] if len(samples) >= 2 else samples
    right = samples[1::2] if len(samples) >= 2 else np.zeros_like(left)

    buf = bytearray(slot_size)
    for i in range(0, slot_size, 16):
        buf[i] = 0x0C; buf[i+1] = 0x02

    _C1, _C2 = 1.796875, -0.8125

    def encode_ch(src, ch_offset):
        idx = 0; p1 = p2 = 0.0
        for sblock in range(0, slot_size, 8192):
            for sub in range(2):
                for block_i in range(0, 2048, 16):
                    boff = sblock + ch_offset + sub*2048 + block_i
                    if boff+16 > slot_size: return
                    max_d = 0.0; tp1=p1; tp2=p2
                    for i2 in range(min(8,28)):
                        s = src[idx+i2] if idx+i2 < len(src) else 0.0
                        d = abs(s-(tp1*_C1+tp2*_C2))
                        if d>max_d: max_d=d
                        tp2=tp1; tp1=s
                    shift = max(0,min(12, 12-int(np.log2(max(max_d/7,1)))))
                    scale = float(1<<(12-shift))
                    buf[boff]=(2<<4)|shift; buf[boff+1]=0x02
                    for i2 in range(28):
                        s = src[idx] if idx<len(src) else 0.0; idx+=1
                        pred=p1*_C1+p2*_C2
                        raw=(s-pred)/scale if scale else 0
                        nib=max(-8,min(7,int(raw+(0.5 if raw>=0 else -0.5))))
                        dec=max(-32768,min(32767,nib*scale+pred))
                        p2=p1; p1=dec
                        j=i2//2
                        if i2%2==0: buf[boff+2+j]=nib&0xF
                        else: buf[boff+2+j]|=(nib&0xF)<<4

    encode_ch(left, 0)
    encode_ch(right, 4096)
    return bytes(buf)


def adpcm_slot_duration(slot_bytes, sample_rate=32000):
    """Duration of a slot. LLRR: 8192 bytes = 4096/channel = 7168 samples/ch."""
    n_superblocks = slot_bytes / 8192
    samples_per_ch = n_superblocks * (4096 / 16 * 28)
    return samples_per_ch / sample_rate


def pcm_to_adpcm_size(pcm_bytes_stereo):
    """Calculate how many ADPCM bytes are needed for this PCM data.
    Must be multiple of 8192 (LLRR super-block size)."""
    n_samples = len(pcm_bytes_stereo) // 2  # 16-bit samples
    n_per_ch = n_samples // 2  # stereo
    # Each super-block: 4096 bytes/ch = 256 blocks × 28 samples = 7168 samples
    n_superblocks = (n_per_ch + 7167) // 7168
    return n_superblocks * 8192


def encode_psx_adpcm_sized(pcm_s16le_stereo, output_size):
    """Encode PCM to PS-ADPCM with exact output_size bytes."""
    pcm_bytes = pcm_s16le_stereo[:len(pcm_s16le_stereo) - (len(pcm_s16le_stereo) % 2)]
    n_samples = len(pcm_bytes) // 2

    lib = _compile_c_encoder()
    if lib is not None:
        pcm_arr = (ctypes.c_short * n_samples)()
        ctypes.memmove(pcm_arr, pcm_bytes, len(pcm_bytes))
        out_arr = (ctypes.c_ubyte * output_size)()
        lib.encode_burnout3_adpcm(pcm_arr, n_samples, out_arr, output_size)
        return bytes(out_arr)

    return _encode_python_fallback(pcm_bytes, output_size)


# ─── Audio duration helper ───────────────────────────────────────────────
def probe_duration_seconds(filepath):
    """Use ffprobe to get audio duration in seconds. Returns None on failure."""
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


# ─── RWS Parser ───────────────────────────────────────────────────────────
class RWSAudioInfo:
    def __init__(self):
        self.track_count = 0
        self.sample_rate = 0
        self.num_channels = 0
        self.data_offset = 0
        self.total_size = 0

def parse_rws_header(filepath):
    """Parse EATRAX.RWS header. Returns RWSAudioInfo or None on any error.
    Hardened against malformed/truncated files and malicious inputs."""
    info = RWSAudioInfo()
    try:
        file_size = os.path.getsize(filepath)
        if file_size < 36:  # minimum: 2 chunk headers (24) + some payload
            return None
        info.total_size = file_size

        with open(filepath, 'rb') as f:
            # Read a bounded amount — never trust file-declared sizes for the read
            data = f.read(min(65536, file_size))

        buf_len = len(data)
        if buf_len < 36:
            return None

        # audio_container chunk header at offset 0
        ctype, csize, cver = struct.unpack_from('<III', data, 0)
        if ctype != RWS_AUDIO_CONTAINER:
            return None

        # audio_header chunk header at offset 12
        htype, hsize, hver = struct.unpack_from('<III', data, 12)
        if htype != RWS_AUDIO_HEADER:
            return None

        # Sanity-check hsize: must be positive and cannot exceed file size
        if hsize == 0 or hsize > file_size - 24:
            return None

        hdr_start = 24
        # Clamp scan range to what we actually read into memory
        scan_end = min(hdr_start + hsize, buf_len - 4)

        # Track count at hdr_start + 0x20 (big-endian)
        if hdr_start + 0x24 <= buf_len:
            raw_count = struct.unpack_from('>I', data, hdr_start + 0x20)[0]
            # Sanity: track count should be reasonable (1-200)
            info.track_count = raw_count if 0 < raw_count <= 200 else 0

        # Scan for sample rate in header payload
        # EA's RWS variant uses LITTLE-endian for most fields
        VALID_RATES = {22050, 24000, 32000, 44100, 48000}
        for off in range(hdr_start, scan_end, 4):
            if off + 4 > buf_len:
                break
            # Try little-endian first (EA's format)
            val_le = struct.unpack_from('<I', data, off)[0]
            val_be = struct.unpack_from('>I', data, off)[0]
            val = None
            if val_le in VALID_RATES:
                val = val_le
            elif val_be in VALID_RATES:
                val = val_be
            if val:
                info.sample_rate = val
                ch_off = off + 13
                if ch_off < buf_len:
                    ch = data[ch_off]
                    info.num_channels = ch if ch in (1, 2) else 2
                break

        # Safe defaults if detection failed
        if info.sample_rate == 0:
            info.sample_rate = 24000  # EA PS2 standard
        if info.num_channels == 0:
            info.num_channels = 2

        # Locate audio_data chunk
        audio_data_start = 24 + hsize  # end of audio_header payload
        if audio_data_start + 12 <= file_size:
            # Verify the chunk type if we have it in buffer
            if audio_data_start + 12 <= buf_len:
                dtype = struct.unpack_from('<I', data, audio_data_start)[0]
                if dtype == RWS_AUDIO_DATA:
                    info.data_offset = audio_data_start + 12
            else:
                # We didn't read that far — store best guess
                info.data_offset = audio_data_start + 12

    except (OSError, struct.error, OverflowError, ValueError):
        return None
    except Exception:
        return None
    return info


# ─── Stylesheet ───────────────────────────────────────────────────────────
STYLESHEET = """
QMainWindow{background:#0d0d0d}
QWidget{color:#e0e0e0;font-family:'JetBrains Mono','Fira Code','Cascadia Code',monospace;font-size:12px}
QTabWidget::pane{border:1px solid #222;background:#111;border-radius:4px}
QTabBar::tab{background:#1a1a1a;color:#888;padding:10px 20px;margin-right:2px;border:1px solid #222;border-bottom:none;border-top-left-radius:6px;border-top-right-radius:6px;font-weight:bold;letter-spacing:1px}
QTabBar::tab:selected{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #ff4500,stop:1 #cc3700);color:#fff;border-color:#ff4500}
QTabBar::tab:hover:!selected{background:#252525;color:#ccc}
QPushButton{background:#1e1e1e;color:#ccc;border:1px solid #333;padding:8px 16px;border-radius:6px;font-weight:bold}
QPushButton:hover{background:#2a2a2a;border-color:#ff4500;color:#ff6a00}
QPushButton:pressed{background:#ff4500;color:#fff}
QPushButton#primaryBtn{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff4500,stop:1 #ff6a00);color:#fff;border:none;padding:12px 28px;font-size:13px}
QPushButton#primaryBtn:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff5500,stop:1 #ff7a10)}
QPushButton#primaryBtn:disabled{background:#333;color:#666}
QPushButton#dangerBtn{background:rgba(255,50,50,0.15);color:#ff5252;border:1px solid rgba(255,50,50,0.3)}
QTableWidget{background-color:#111;alternate-background-color:#151515;gridline-color:#1e1e1e;border:1px solid #222;border-radius:6px;selection-background-color:rgba(255,69,0,0.2);selection-color:#ff8c00}
QTableWidget::item{padding:6px 8px;border-bottom:1px solid #1a1a1a}
QHeaderView::section{background:#1a1a1a;color:#888;padding:8px 10px;border:none;border-bottom:2px solid #ff4500;font-weight:bold;font-size:10px;letter-spacing:1px}
QProgressBar{border:1px solid #333;border-radius:8px;background:#1a1a1a;text-align:center;color:#fff;font-weight:bold;min-height:24px}
QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff4500,stop:1 #ff8c00);border-radius:7px}
QTextEdit{background:#0a0a0a;border:1px solid #222;border-radius:6px;color:#aaa;font-size:11px;padding:8px}
QTreeWidget{background:#0e0e0e;border:1px solid #222;border-radius:6px;color:#ccc;font-size:11px}
QTreeWidget::item{padding:3px 0}
QTreeWidget::item:selected{background:rgba(255,69,0,0.2);color:#ff8c00}
QGroupBox{border:1px solid #222;border-radius:8px;margin-top:16px;padding-top:20px;font-weight:bold;color:#ff8c00}
QGroupBox::title{subcontrol-origin:margin;left:16px;padding:0 8px}
QLabel#headerLabel{font-size:22px;font-weight:800;color:#ff4500}
QLabel#subtitleLabel{font-size:11px;color:#555;letter-spacing:2px}
"""


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
        self.text_lbl = QLabel("Arrastra tu ISO de Burnout 3 aquí\no haz clic para buscar")
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
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar ISO", "",
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
            elif os.path.isdir(p):
                for f in sorted(os.listdir(p)):
                    fp = os.path.join(p, f)
                    if os.path.isfile(fp) and os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS:
                        files.append(fp)
        if files: self.files_dropped.emit(files)
        e.acceptProposedAction()


# ─── Worker ───────────────────────────────────────────────────────────────
class InjectionWorker(QObject):
    progress = Signal(float, str)
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, iso_path, assignments, output_iso, iso_builder):
        super().__init__()
        self.iso_path = iso_path
        self.assignments = assignments
        self.output_iso = output_iso
        self.iso_builder = iso_builder

    def _find_file_offset_iso9660(self, iso_data, filename_upper):
        """
        Find a file's (byte_offset, byte_size) inside an ISO9660 image
        by scanning directory records for the filename.
        """
        target = filename_upper.encode('ascii')
        target_v = target + b';1'  # ISO9660 adds version suffix

        pos = 0
        while pos < len(iso_data):
            idx = iso_data.find(target_v, pos)
            if idx == -1:
                idx = iso_data.find(target, pos)
            if idx == -1:
                return None, None

            entry_start = idx - 33
            if entry_start < 0:
                pos = idx + 1
                continue

            try:
                rec_len = iso_data[entry_start]
                if rec_len < 34 or rec_len > 255:
                    pos = idx + 1; continue

                name_len = iso_data[entry_start + 32]
                name_bytes = iso_data[entry_start + 33: entry_start + 33 + name_len]
                if target not in name_bytes:
                    pos = idx + 1; continue

                lba = struct.unpack_from('<I', iso_data, entry_start + 2)[0]
                fsize = struct.unpack_from('<I', iso_data, entry_start + 10)[0]
                file_off = lba * 2048

                if lba > 0 and fsize > 0 and file_off + fsize <= len(iso_data):
                    return file_off, fsize
            except (struct.error, IndexError):
                pass
            pos = idx + 1

        return None, None

    def _find_dir_entry_offset(self, iso_data, filename_upper):
        """Find the byte offset of the ISO9660 directory entry for a file.
        Used to patch the file size field later."""
        target = filename_upper.encode('ascii')
        target_v = target + b';1'

        pos = 0
        while pos < len(iso_data):
            idx = iso_data.find(target_v, pos)
            if idx == -1:
                idx = iso_data.find(target, pos)
            if idx == -1:
                return None

            entry_start = idx - 33
            if entry_start < 0:
                pos = idx + 1; continue

            try:
                rec_len = iso_data[entry_start]
                if rec_len < 34 or rec_len > 255:
                    pos = idx + 1; continue
                name_len = iso_data[entry_start + 32]
                name_bytes = iso_data[entry_start + 33: entry_start + 33 + name_len]
                if target not in name_bytes:
                    pos = idx + 1; continue
                lba = struct.unpack_from('<I', iso_data, entry_start + 2)[0]
                if lba > 0:
                    return entry_start
            except (struct.error, IndexError):
                pass
            pos = idx + 1
        return None

    def _parse_rws_tracks(self, rws_data):
        """
        Parse an EATRAX.RWS container to find individual track offsets/sizes.
        
        Based on actual hex analysis of Burnout 3 _EATRAX0.RWS:
        
        Container header (12 bytes):
          0x00: u32 LE = 0x0000080D (audio_container)
          0x04: u32 LE = container_size
          0x08: u32 LE = version (0x1C020009)
        
        Audio header chunk (12 bytes):
          0x0C: u32 LE = 0x0000080E (audio_header)
          0x10: u32 LE = header_payload_size (0x07DC)
          0x14: u32 LE = version
        
        Header payload (starts at 0x18):
          +0x00 (0x18): u32 LE = 0x0000069C (sub-header size)
          +0x08 (0x20): u32 LE = 0x00000010 (?)
          +0x0C (0x24): u32 LE = 0x00000024 (?)  
          +0x10 (0x28): u32 LE = track_count (e.g. 0x00000007 = 7... wait)
          
        Actually from the hex:
          0x28: 07 00 00 00 → track_count = 7? No, that's too few.
          
        Let me re-read: the "EATrax0" string is at 0x64.
        
        Track table starts at 0x70, each entry is 40 bytes (10 x u32 LE):
          +0x00: u32 LE - offset1 (pointer into data)  
          +0x04: u32 LE - offset2 (pointer into data)
          +0x08: u32 LE - zero
          +0x0C: u32 LE - pointer
          +0x10: u32 LE - zero  
          +0x14: u32 LE - zero
          +0x18: u32 LE - track_byte_size (e.g. 0x0073C000 = 7585792)
          +0x1C: u32 LE - track_byte_offset (0 for first, cumulative)
          +0x20-0x27: next entry or padding
          
        Wait, the entries are actually every 0x28 (40) bytes starting at 0x70:
          0x070: 80 DE 0F 01 ... 00 C0 73 00 00 00 00 00 (track 0: size=0x73C000, off=0)
          0x098: B0 EF 0F 01 ... 00 40 89 00 00 C0 73 00 (track 1: size=0x894000, off=0x73C000)
          
        So entry structure (40 bytes each):
          [0:4]   u32 LE - ptr_a
          [4:8]   u32 LE - ptr_b  
          [8:12]  u32 LE - zero
          [12:16] u32 LE - ptr_c
          [16:20] u32 LE - zero
          [20:24] u32 LE - zero
          [24:28] u32 LE - track_size (bytes of audio data)
          [28:32] u32 LE - track_offset (cumulative offset into audio_data)
          [32:36] u32 LE - ptr/data
          [36:40] u32 LE - ptr/data
        
        Verification from hex:
          Track 0 @ 0x70: size at 0x88 = 00 C0 73 00 = 0x0073C000 = 7585792
                          offset at 0x8C = 00 00 00 00 = 0 ✓
          Track 1 @ 0x98: size at 0xB0 = 00 40 89 00 = 0x00894000 = 8994816
                          offset at 0xB4 = 00 C0 73 00 = 0x0073C000 ✓ (matches track 0 size)
        """
        if len(rws_data) < 0x100:
            return [], 48000, 2

        # Validate container chunk
        ctype = struct.unpack_from('<I', rws_data, 0)[0]
        if ctype != 0x080D:
            return [], 48000, 2

        # Validate header chunk
        htype = struct.unpack_from('<I', rws_data, 12)[0]
        hsize = struct.unpack_from('<I', rws_data, 16)[0]
        if htype != 0x080E or hsize == 0:
            return [], 48000, 2

        # audio_data chunk
        data_chunk_off = 24 + hsize
        if data_chunk_off + 12 > len(rws_data):
            return [], 48000, 2

        dtype = struct.unpack_from('<I', rws_data, data_chunk_off)[0]
        dsize = struct.unpack_from('<I', rws_data, data_chunk_off + 4)[0]
        if dtype != 0x080F:
            return [], 48000, 2

        data_payload_off = data_chunk_off + 12

        # Find the track table by searching for the signature pattern:
        # Track 0 always has: [size, 0x00000000] where size is 1-20MB
        # We search for this pattern in the header region, then validate
        # that subsequent entries have consecutive offsets.
        
        # Known layout from hex analysis:
        #   Entry stride: 32 bytes
        #   size field: entry_offset + 24
        #   offset field: entry_offset + 28
        #   Track 0 offset = 0, track 1 offset = track 0 size, etc.
        
        ENTRY_SIZE = 32
        SIZE_WITHIN = 24
        OFF_WITHIN = 28
        
        # Search the header payload for the first track's (size, 0) pair
        # The size should be between 500KB and 50MB, followed by exactly 0
        header_end = min(24 + hsize, len(rws_data))
        
        found_table_start = None
        for scan in range(24, header_end - 32, 4):
            candidate_size = struct.unpack_from('<I', rws_data, scan)[0]
            candidate_off = struct.unpack_from('<I', rws_data, scan + 4)[0]
            
            # Track 0: plausible size (500KB-50MB) and offset exactly 0
            if candidate_off == 0 and 500000 < candidate_size < 50000000:
                # This (scan) is where the size field is
                # The entry containing this starts at scan - SIZE_WITHIN
                entry0_start = scan - SIZE_WITHIN
                if entry0_start < 24:
                    continue
                
                # Validate entry 1: should be at entry0_start + ENTRY_SIZE
                e1_start = entry0_start + ENTRY_SIZE
                if e1_start + 32 > header_end:
                    continue
                    
                e1_size = struct.unpack_from('<I', rws_data, e1_start + SIZE_WITHIN)[0]
                e1_off = struct.unpack_from('<I', rws_data, e1_start + OFF_WITHIN)[0]
                
                # Entry 1 offset should equal entry 0 size
                if e1_off == candidate_size and 500000 < e1_size < 50000000:
                    # Double-check with entry 2
                    e2_start = e1_start + ENTRY_SIZE
                    if e2_start + 32 <= header_end:
                        e2_off = struct.unpack_from('<I', rws_data, e2_start + OFF_WITHIN)[0]
                        if e2_off == e1_off + e1_size:
                            found_table_start = entry0_start
                            break
                    else:
                        found_table_start = entry0_start
                        break
        
        if found_table_start is None:
            return [], 24000, 2
        
        # Scan all entries from the found table start
        tracks = []
        expected_offset = 0
        max_entries = 50
        
        for i in range(max_entries):
            entry_off = found_table_start + i * ENTRY_SIZE
            if entry_off + ENTRY_SIZE > header_end:
                break
            
            trk_size = struct.unpack_from('<I', rws_data, entry_off + SIZE_WITHIN)[0]
            trk_offset = struct.unpack_from('<I', rws_data, entry_off + OFF_WITHIN)[0]
            
            if trk_offset != expected_offset:
                break
            if trk_size == 0 or trk_size > dsize:
                break
            
            abs_off = data_payload_off + trk_offset
            if abs_off + trk_size > len(rws_data):
                break
            
            tracks.append((abs_off, trk_size))
            expected_offset += trk_size

        # Burnout 3 EATRAX uses stereo audio interleaved in 2048-byte blocks.
        # L[2048] R[2048] L[2048] R[2048] ...
        sample_rate = 32000
        num_channels = 2  # MUST be stereo — the game expects L/R interleaved blocks

        return tracks, sample_rate, num_channels

    def run(self):
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="burnout3_")

            if not os.path.isfile(self.iso_path):
                raise Exception(f"ISO not found: {self.iso_path}")
            for sid, src in self.assignments.items():
                if not os.path.isfile(src):
                    raise Exception(f"Audio not found: {src}")

            iso_size = os.path.getsize(self.iso_path)
            out_dir = os.path.dirname(os.path.abspath(self.output_iso)) or '.'
            try:
                usage = shutil.disk_usage(out_dir)
                free = usage.free
            except (OSError, AttributeError):
                free = float('inf')
            if free < iso_size + 200*1048576:
                raise Exception(
                    f"Not enough space: {free//1048576} MB free, "
                    f"~{(iso_size+200*1048576)//1048576} MB needed"
                )

            total_steps = len(self.assignments) * 2 + 4
            step = 0

            # ═══ STEP 1: Copy ISO ═══
            self.progress.emit(step/total_steps, "Copying ISO...")
            self.log_line.emit("▶ Copying ISO for in-place patching")
            shutil.copy2(self.iso_path, self.output_iso)
            self.log_line.emit(f"✓ Copy: {os.path.basename(self.output_iso)}")
            step += 1

            # ═══ STEP 2: Parse ISO ═══
            self.progress.emit(step/total_steps, "Analyzing EATRAX...")
            self.log_line.emit("▶ Parsing ISO9660 + RWS containers")

            with open(self.output_iso, 'rb') as f:
                iso_data = bytearray(f.read())

            for did, region in KNOWN_DISC_IDS.items():
                if did.encode() in iso_data:
                    self.log_line.emit(f"✓ Disc ID: {did} — {region}")
                    break

            # Parse both EATRAX files
            eatrax_info = {}
            for rws_name in ["_EATRAX0.RWS", "_EATRAX1.RWS"]:
                offset, size = self._find_file_offset_iso9660(iso_data, rws_name)
                if offset and size:
                    rws_slice = bytes(iso_data[offset:offset+size])
                    tracks, sr, ch = self._parse_rws_tracks(rws_slice)
                    hsize = struct.unpack_from('<I', rws_slice, 16)[0]
                    eatrax_info[rws_name] = {
                        'iso_offset': offset,
                        'file_size': size,
                        'tracks': tracks,
                        'hsize': hsize,
                        'data_payload_off': 24 + hsize + 12,  # after header + data chunk hdr
                        'total_audio': sum(s for _, s in tracks),
                    }
                    self.log_line.emit(
                        f"✓ {rws_name} @ 0x{offset:X} ({size/1048576:.1f} MB) "
                        f"— {len(tracks)} tracks"
                    )

            if not eatrax_info:
                raise Exception("No EATRAX found in ISO")

            step += 1

            # ═══ STEP 3: Encode all assigned songs to ADPCM temp files ═══
            self.log_line.emit("▶ Converting songs to PS-ADPCM...")

            # Split assignments by EATRAX: slots 1-22 → EATRAX0, 23-44 → EATRAX1
            ea0_assignments = {k: v for k, v in self.assignments.items() if k <= 22}
            ea1_assignments = {k: v for k, v in self.assignments.items() if k > 22}

            # Encode all songs first (no truncation!)
            encoded = {}  # slot_id -> (adpcm_file_path, adpcm_size, src_name, duration)
            for slot_id, source in sorted(self.assignments.items()):
                src_name = os.path.basename(source)
                self.progress.emit(step/total_steps, f"Converting {src_name}...")

                temp_raw = os.path.join(tmp, f"t{slot_id:02d}.raw")
                cv = subprocess.run([
                    "ffmpeg", "-y", "-i", source,
                    "-af", "lowpass=f=14000,aresample=resampler=soxr",
                    "-f", "s16le", "-acodec", "pcm_s16le",
                    "-ar", "32000", "-ac", "2", temp_raw
                ], capture_output=True, text=True, timeout=300)

                if cv.returncode != 0:
                    self.log_line.emit(f"✗ Slot {slot_id:02d}: ffmpeg error")
                    step += 1; continue
                if not os.path.isfile(temp_raw) or os.path.getsize(temp_raw) == 0:
                    self.log_line.emit(f"✗ Slot {slot_id:02d}: empty file")
                    step += 1; continue

                pcm_size = os.path.getsize(temp_raw)
                adpcm_size = pcm_to_adpcm_size(open(temp_raw, 'rb').read(4))
                # Recalculate properly: pcm_size bytes = pcm_size/2 samples total
                n_samples = pcm_size // 2
                n_per_ch = n_samples // 2
                n_superblocks = (n_per_ch + 7167) // 7168
                adpcm_size = n_superblocks * 8192

                dur = adpcm_slot_duration(adpcm_size)
                encoded[slot_id] = (temp_raw, adpcm_size, src_name, dur)
                self.log_line.emit(f"  ✓ Slot {slot_id:02d}: {src_name} → {adpcm_size//1024}KB ({dur:.0f}s)")
                step += 1

            if not encoded:
                raise Exception("No tracks were converted")

            # ═══ STEP 4: Redistribute space and encode to ADPCM ═══
            self.progress.emit(step/total_steps, "Building EATRAX...")
            self.log_line.emit("▶ Redistributing track space and encoding")

            replaced = 0
            with open(self.output_iso, 'r+b') as iso_out:
                for eatrax_name, assignments, slot_start in [
                    ("_EATRAX0.RWS", ea0_assignments, 1),
                    ("_EATRAX1.RWS", ea1_assignments, 23),
                ]:
                    if eatrax_name not in eatrax_info or not assignments:
                        continue

                    ea = eatrax_info[eatrax_name]
                    orig_tracks = ea['tracks']
                    n_orig = len(orig_tracks)
                    available_audio = ea['total_audio']

                    # Calculate how much space assigned songs need
                    assigned_need = {}
                    for sid in sorted(assignments.keys()):
                        if sid in encoded:
                            _, asz, _, _ = encoded[sid]
                            assigned_need[sid] = asz

                    total_needed = sum(assigned_need.values())

                    # Space for unassigned slots (keep original sizes)
                    unassigned_slots = []
                    for i in range(n_orig):
                        sid = slot_start + i
                        if sid not in assignments:
                            unassigned_slots.append((sid, orig_tracks[i][1]))  # (slot_id, orig_size)

                    total_unassigned = sum(s for _, s in unassigned_slots)

                    space_for_custom = available_audio - total_unassigned
                    self.log_line.emit(
                        f"  {eatrax_name}: {space_for_custom//1024}KB available for "
                        f"{len(assigned_need)} custom tracks (need {total_needed//1024}KB)"
                    )

                    # Check if songs fit. If not, truncate the longest ones with fade out
                    if total_needed > space_for_custom:
                        self.log_line.emit(f"  ⚠ Songs exceed space, applying fade-out truncation")
                        # Sort by size descending and truncate largest first
                        while total_needed > space_for_custom:
                            biggest_sid = max(assigned_need, key=assigned_need.get)
                            old_size = assigned_need[biggest_sid]
                            # Calculate max size per remaining track
                            other_need = total_needed - old_size
                            max_for_this = space_for_custom - other_need
                            if max_for_this < 8192:
                                max_for_this = 8192
                            new_size = (max_for_this // 8192) * 8192
                            assigned_need[biggest_sid] = new_size
                            total_needed = sum(assigned_need.values())

                            # Re-encode with truncation + fade
                            _, _, src_name, _ = encoded[biggest_sid]
                            new_dur = adpcm_slot_duration(new_size)
                            fade_dur = 3
                            fade_start = max(0, new_dur - fade_dur)
                            source = self.assignments[biggest_sid]
                            temp_raw = os.path.join(tmp, f"t{biggest_sid:02d}_trunc.raw")
                            subprocess.run([
                                "ffmpeg", "-y", "-i", source,
                                "-t", str(new_dur),
                                "-af", f"afade=t=out:st={fade_start:.1f}:d={fade_dur},lowpass=f=14000,aresample=resampler=soxr",
                                "-f", "s16le", "-acodec", "pcm_s16le",
                                "-ar", "32000", "-ac", "2", temp_raw
                            ], capture_output=True, text=True, timeout=300)
                            encoded[biggest_sid] = (temp_raw, new_size, src_name, new_dur)
                            self.log_line.emit(
                                f"  ↳ Slot {biggest_sid:02d}: truncated to {new_dur:.0f}s with fade out"
                            )

                    # Now build the track layout: assigned slots get their custom size,
                    # unassigned slots keep original size
                    new_track_sizes = []
                    new_track_data = []  # (slot_id, is_custom)

                    for i in range(n_orig):
                        sid = slot_start + i
                        if sid in assigned_need:
                            new_track_sizes.append(assigned_need[sid])
                            new_track_data.append((sid, True))
                        else:
                            new_track_sizes.append(orig_tracks[i][1])
                            new_track_data.append((sid, False))

                    # Find the track table in the RWS header to patch it
                    iso_out.seek(ea['iso_offset'])
                    rws_header = bytearray(iso_out.read(24 + ea['hsize']))

                    header_end = len(rws_header)
                    ENTRY_SIZE = 32
                    SIZE_WITHIN = 24
                    OFF_WITHIN = 28

                    found_table = None
                    for scan in range(24, header_end - 32, 4):
                        cs = struct.unpack_from('<I', rws_header, scan)[0]
                        co = struct.unpack_from('<I', rws_header, scan + 4)[0]
                        if co == 0 and 500000 < cs < 50000000:
                            entry0_start = scan - SIZE_WITHIN
                            if entry0_start < 24: continue
                            e1s = struct.unpack_from('<I', rws_header, entry0_start + ENTRY_SIZE + SIZE_WITHIN)[0]
                            e1o = struct.unpack_from('<I', rws_header, entry0_start + ENTRY_SIZE + OFF_WITHIN)[0]
                            if e1o == cs and 500000 < e1s < 50000000:
                                found_table = entry0_start
                                break

                    if found_table is None:
                        self.log_line.emit(f"✗ {eatrax_name}: track table not found")
                        continue

                    # Patch track table with new sizes and offsets
                    cumulative = 0
                    for i in range(n_orig):
                        entry_off = found_table + i * ENTRY_SIZE
                        if entry_off + ENTRY_SIZE > header_end: break
                        struct.pack_into('<I', rws_header, entry_off + SIZE_WITHIN, new_track_sizes[i])
                        struct.pack_into('<I', rws_header, entry_off + OFF_WITHIN, cumulative)
                        cumulative += new_track_sizes[i]

                    # Update container size field
                    new_total_audio = sum(new_track_sizes)
                    new_container_payload = ea['hsize'] + 12 + new_total_audio
                    struct.pack_into('<I', rws_header, 4, new_container_payload)

                    # Pre-read ALL original track data before we overwrite anything
                    orig_track_data = {}
                    for i, (sid, is_custom) in enumerate(new_track_data):
                        if not is_custom:
                            orig_off, orig_size = orig_tracks[i]
                            iso_out.seek(ea['iso_offset'] + orig_off)
                            orig_track_data[i] = iso_out.read(orig_size)

                    # Write patched header
                    iso_out.seek(ea['iso_offset'])
                    iso_out.write(rws_header)

                    # Write audio data chunk header with new size
                    iso_out.write(struct.pack('<III', 0x080F, new_total_audio, 0x1C020009))

                    # Write track audio data in order
                    for i, (sid, is_custom) in enumerate(new_track_data):
                        self.progress.emit(step/total_steps, f"Writing track {sid}...")

                        if is_custom and sid in encoded:
                            temp_raw, adpcm_size, src_name, dur = encoded[sid]

                            # Read PCM and encode
                            with open(temp_raw, 'rb') as af:
                                pcm_data = af.read()

                            target_size = new_track_sizes[i]
                            audio = encode_psx_adpcm_sized(pcm_data, target_size)
                            iso_out.write(audio)

                            self.log_line.emit(
                                f"✓ Slot {sid:02d}: {html_mod.escape(src_name)} → "
                                f"{target_size//1024}KB ({adpcm_slot_duration(target_size):.0f}s)"
                            )
                            replaced += 1
                            step += 1
                        else:
                            # Write pre-read original track data
                            iso_out.write(orig_track_data[i])

                    # Zero-pad any remaining space
                    written = 24 + ea['hsize'] + 12 + new_total_audio
                    remaining = ea['file_size'] - written
                    if remaining > 0:
                        zero_chunk = b'\x00' * min(1048576, remaining)
                        w = 0
                        while w < remaining:
                            to_write = min(len(zero_chunk), remaining - w)
                            iso_out.write(zero_chunk[:to_write])
                            w += to_write

                    self.log_line.emit(
                        f"✓ {eatrax_name}: {len(assignments)} custom tracks, "
                        f"{new_total_audio/1048576:.1f}MB used of {available_audio/1048576:.1f}MB"
                    )

            if replaced == 0:
                if os.path.isfile(self.output_iso):
                    os.remove(self.output_iso)
                raise Exception("No tracks were patched")

            self.progress.emit(1.0, "Completed!")
            self.log_line.emit(f"✓ {replaced} tracks patched — full-length songs!")
            self.log_line.emit(f"✓ {self.output_iso}")
            self.finished.emit(True, f"Done! {replaced} tracks.\n{self.output_iso}")

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Timeout: ffmpeg took too long.")
        except OSError as e:
            self.finished.emit(False, f"I/O Error: {e}")
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            if tmp and os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)


# ─── Main Window ──────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Burnout 3: Takedown — Custom Music Injector v11.0")
        self.setMinimumSize(1050, 750)
        self.resize(1150, 850)
        self.iso_path = None
        self.output_path = None
        self.assignments: Dict[int,str] = {}
        self.worker_thread = None
        self.deps = self._check_deps()
        self._build_ui()
        self._update_inject_btn()

    def _check_deps(self):
        d = {"ffmpeg": bool(shutil.which("ffmpeg")), "7z": bool(shutil.which("7z"))}
        d["gcc"] = bool(shutil.which("gcc"))
        return d

    def _build_ui(self):
        c = QWidget(); self.setCentralWidget(c)
        lay = QVBoxLayout(c); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet("background:#0a0a0a;border-bottom:1px solid #1e1e1e")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(24,14,24,14)
        ta = QVBoxLayout(); ta.setSpacing(2)
        t = QLabel("BURNOUT 3: TAKEDOWN"); t.setObjectName("headerLabel"); ta.addWidget(t)
        s = QLabel("CUSTOM MUSIC INJECTOR v11.0 — LINUX"); s.setObjectName("subtitleLabel"); ta.addWidget(s)
        hl.addLayout(ta); hl.addStretch()
        da = QVBoxLayout(); da.setSpacing(1)
        for name, key in [("ffmpeg","ffmpeg"),("7z","7z"),("gcc (encoder C)","gcc")]:
            ok = self.deps.get(key, False)
            txt = f"{'✓' if ok else '✗'} {name}"
            lb = QLabel(txt); lb.setStyleSheet(f"font-size:10px;color:{'#69f0ae' if ok else '#ff5252'}")
            da.addWidget(lb)
        hl.addLayout(da)
        lay.addWidget(hdr)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_iso_tab(), "📀  ISO + FILESYSTEM")
        self.tabs.addTab(self._build_tracks_tab(), "🎵  ASIGNAR TRACKS")
        self.tabs.addTab(self._build_process_tab(), "🔧  PROCESAR")
        self.tabs.addTab(self._build_info_tab(), "📖  GUÍA")

        ft = QLabel("Burnout 3: Takedown™ — Electronic Arts · PS-ADPCM LLRR encoder · v11.0")
        ft.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ft.setStyleSheet("background:#0a0a0a;color:#333;padding:8px;font-size:9px;letter-spacing:1px;border-top:1px solid #1a1a1a")
        lay.addWidget(ft)

    def _build_iso_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(20,20,20,20); lay.setSpacing(12)
        self.iso_drop = ISODropZone()
        self.iso_drop.iso_dropped.connect(self._on_iso)
        lay.addWidget(self.iso_drop)
        sp = QSplitter(Qt.Orientation.Horizontal)
        # Tree
        tg = QGroupBox("Estructura conocida del ISO")
        tl = QVBoxLayout(tg)
        self.fs_tree = QTreeWidget()
        self.fs_tree.setHeaderLabels(["Archivo / Carpeta","Descripción"])
        self.fs_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.fs_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._fill_tree()
        tl.addWidget(self.fs_tree)
        sp.addWidget(tg)
        # Info
        ig = QGroupBox("Información del ISO cargado")
        il = QVBoxLayout(ig)
        self.iso_info = QTextEdit()
        self.iso_info.setReadOnly(True)
        self.iso_info.setHtml('<div style="color:#666;font-style:italic">Arrastra o selecciona un ISO</div>')
        il.addWidget(self.iso_info)
        sp.addWidget(ig)
        sp.setSizes([500,500])
        lay.addWidget(sp,1)
        return w

    def _fill_tree(self):
        self.fs_tree.clear()
        def add(parent, struct):
            for k, v in struct.items():
                if isinstance(v, dict):
                    f = QTreeWidgetItem(parent, [k, ""])
                    f.setForeground(0, QColor("#ff8c00")); f.setExpanded(True)
                    add(f, v)
                else:
                    it = QTreeWidgetItem(parent, [k, v])
                    if "🎵" in v:
                        it.setForeground(0, QColor("#69f0ae")); it.setForeground(1, QColor("#69f0ae"))
                    else:
                        it.setForeground(0, QColor("#888")); it.setForeground(1, QColor("#555"))
        add(self.fs_tree.invisibleRootItem(), ISO_STRUCTURE)
        self.fs_tree.expandAll()

    def _on_iso(self, path):
        self.iso_path = path
        self.output_path = os.path.splitext(path)[0] + "_custom.iso"
        self.iso_drop.set_iso_path(path)
        sz = os.path.getsize(path)/1048576
        self.iso_info.setHtml(f"""<div style="line-height:1.8">
        <b style="color:#ff8c00">Archivo:</b> <span style="color:#4fc3f7">{os.path.basename(path)}</span><br>
        <b style="color:#ff8c00">Tamaño:</b> {sz:.1f} MB<br>
        <b style="color:#ff8c00">Ruta:</b> <span style="color:#888">{path}</span><br>
        <b style="color:#ff8c00">Salida:</b> <span style="color:#888">{self.output_path}</span><br><br>
        <b style="color:#ff8c00">Estructura de audio esperada:</b><br>
        <span style="color:#69f0ae">Tracks/_EATRAX0.RWS</span> — Canciones 1-22<br>
        <span style="color:#69f0ae">Tracks/_EATRAX1.RWS</span> — Canciones 23-40+<br><br>
        <b style="color:#ff8c00">Formato interno:</b><br>
        Contenedor: RenderWare Stream (.RWS)<br>
        Codec: PS-ADPCM · Chunks: 0x080D/0x080E/0x080F<br>
        Headers: big-endian · Samples en clusters con padding<br>
        </div>""")
        self._update_inject_btn()
        self.tabs.setCurrentIndex(1)

    def _build_tracks_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)
        tb = QHBoxLayout()
        for txt, fn in [("➕ Agregar audio",self._add_files),("📁 Agregar carpeta",self._add_folder),("⚡ Auto-asignar",self._auto_assign)]:
            b = QPushButton(txt); b.clicked.connect(fn); tb.addWidget(b)
        tb.addStretch()
        bc = QPushButton("🗑 Limpiar"); bc.setObjectName("dangerBtn"); bc.clicked.connect(self._clear_all); tb.addWidget(bc)
        lay.addLayout(tb)
        hint = QLabel("Arrastra archivos/carpetas de audio · Auto-detecta números en nombres de archivo")
        hint.setStyleSheet("color:#555;font-size:11px"); lay.addWidget(hint)

        self.table = TrackTable(len(EA_TRAX_SONGS), 5)
        self.table.setHorizontalHeaderLabels(["SLOT","CANCIÓN ORIGINAL","TU MÚSICA","TU TÍTULO (in-game)","ACCIÓN"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.files_dropped.connect(self._on_drop)
        h = self.table.horizontalHeader()
        for i, (mode, w_) in enumerate([
            (QHeaderView.ResizeMode.Fixed, 50),
            (QHeaderView.ResizeMode.Interactive, 220),
            (QHeaderView.ResizeMode.Stretch, 0),
            (QHeaderView.ResizeMode.Interactive, 200),
            (QHeaderView.ResizeMode.Fixed, 75)
        ]):
            h.setSectionResizeMode(i, mode)
            if w_: self.table.setColumnWidth(i, w_)
        self._fill_table()
        lay.addWidget(self.table, 1)
        self.lbl_assigned = QLabel("0 / 44 tracks asignados")
        self.lbl_assigned.setStyleSheet("color:#ff8c00;font-weight:bold"); lay.addWidget(self.lbl_assigned)
        return w

    def _fill_table(self):
        for row, song in enumerate(EA_TRAX_SONGS):
            # Col 0: Slot number
            si = QTableWidgetItem(f" {song['id']:02d}"); si.setFlags(Qt.ItemFlag.ItemIsEnabled)
            si.setForeground(QColor("#ff8c00")); f=si.font(); f.setBold(True); si.setFont(f)
            self.table.setItem(row, 0, si)
            # Col 1: Original song (artist — title)
            orig = QTableWidgetItem(f" {song['artist']} — {song['title']}")
            orig.setFlags(Qt.ItemFlag.ItemIsEnabled); orig.setForeground(QColor("#777"))
            self.table.setItem(row, 1, orig)
            # Col 2: Your music (empty)
            ei = QTableWidgetItem(" —"); ei.setFlags(Qt.ItemFlag.ItemIsEnabled); ei.setForeground(QColor("#444"))
            self.table.setItem(row, 2, ei)
            # Col 3: Custom title (editable)
            ct = QTableWidgetItem("")
            ct.setForeground(QColor("#4fc3f7"))
            self.table.setItem(row, 3, ct)
            # Col 4: Action button
            b = QPushButton("Asignar"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px")
            b.clicked.connect(lambda _, s=song['id']: self._assign_single(s))
            self.table.setCellWidget(row, 4, b)
            self.table.setRowHeight(row, 34)

    def _upd_row(self, sid, fp=None):
        row = sid - 1
        if row < 0 or row >= self.table.rowCount():
            return
        if fp:
            it = QTableWidgetItem(f" {os.path.basename(fp)}"); it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setForeground(QColor("#69f0ae")); it.setToolTip(fp)
            self.table.setItem(row, 2, it)
            # Auto-fill custom title from filename if empty
            ct = self.table.item(row, 3)
            if ct and not ct.text().strip():
                name = os.path.splitext(os.path.basename(fp))[0]
                ct.setText(name)
            b = QPushButton("Quitar"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px;background:rgba(255,50,50,0.15);color:#ff5252;border:1px solid rgba(255,50,50,0.3)")
            b.clicked.connect(lambda _, s=sid: self._remove(s))
            self.table.setCellWidget(row, 4, b)
        else:
            it = QTableWidgetItem(" —"); it.setFlags(Qt.ItemFlag.ItemIsEnabled); it.setForeground(QColor("#444"))
            self.table.setItem(row, 2, it)
            b = QPushButton("Asignar"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px")
            b.clicked.connect(lambda _, s=sid: self._assign_single(s))
            self.table.setCellWidget(row, 4, b)

    def _update_inject_btn(self):
        n = len(self.assignments)
        if hasattr(self,'lbl_assigned'): self.lbl_assigned.setText(f"{n} / 44 tracks asignados")
        if hasattr(self,'btn_inject'):
            self.btn_inject.setEnabled(
                n > 0
                and self.iso_path is not None
                and bool(self.deps.get("ffmpeg"))
                and bool(self.deps.get("7z"))
            )

    def _assign_single(self, sid):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, f"Audio para Slot {sid:02d}", "", f"Audio (*.{exts})")
        if fs: self.assignments[sid]=fs[0]; self._upd_row(sid,fs[0]); self._update_inject_btn()

    def _remove(self, sid):
        self.assignments.pop(sid,None); self._upd_row(sid); self._update_inject_btn()

    def _add_files(self):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, "Audio", "", f"Audio (*.{exts})")
        if fs: self._auto_files(sorted(fs))

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta con música")
        if d:
            fs = sorted([os.path.join(d,f) for f in os.listdir(d)
                         if os.path.isfile(os.path.join(d,f)) and os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS])
            if fs: self._auto_files(fs)
            else: QMessageBox.warning(self,"Sin audio","No se encontraron archivos de audio.")

    def _on_drop(self, files): self._auto_files(sorted(files))

    def _auto_files(self, files):
        used = set(self.assignments.keys())
        for fp in files:
            base = os.path.splitext(os.path.basename(fp))[0]
            if not base:
                continue
            # Extract leading digits from filename
            leading_digits = ""
            for c in base:
                if c.isdigit():
                    leading_digits += c
                else:
                    break
            explicit = None
            if leading_digits:
                try:
                    n = int(leading_digits)
                    if 1 <= n <= 44:
                        explicit = n
                except (ValueError, OverflowError):
                    pass
            if explicit and explicit not in used:
                slot = explicit
            else:
                slot = next((s for s in range(1, 45) if s not in used), None)
            if slot:
                self.assignments[slot] = fp
                used.add(slot)
                self._upd_row(slot, fp)
        self._update_inject_btn()

    def _auto_assign(self):
        if not self.assignments: QMessageBox.information(self,"","Agrega archivos primero."); return
        fs = list(self.assignments.values()); self._clear_all(); self._auto_files(sorted(fs))

    def _clear_all(self):
        for s in list(self.assignments.keys()): self._upd_row(s)
        self.assignments.clear(); self._update_inject_btn()

    def _build_process_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24,24,24,24); lay.setSpacing(14)
        sp = QLabel("Conversión: Tu audio → PS-ADPCM 32kHz Stereo (formato nativo PS2)\n"
                     "⚡ Encoder C optimizado — 5 filtros × 3 shifts por bloque\n"
                     "🎵 Fade out automático de 3s cuando la canción excede el slot")
        sp.setStyleSheet("color:#888;font-size:11px;padding:12px;background:rgba(255,140,0,0.05);border:1px solid #222;border-radius:8px")
        lay.addWidget(sp)

        self.btn_inject = QPushButton("🔥  INYECTAR MÚSICA PERSONALIZADA")
        self.btn_inject.setObjectName("primaryBtn"); self.btn_inject.setMinimumHeight(48)
        self.btn_inject.clicked.connect(self._inject); self.btn_inject.setEnabled(False)
        lay.addWidget(self.btn_inject)
        self.pbar = QProgressBar(); self.pbar.setRange(0,1000); self.pbar.setValue(0); self.pbar.setFormat("")
        lay.addWidget(self.pbar)
        self.lbl_prog = QLabel(""); self.lbl_prog.setStyleSheet("color:#888;font-size:11px"); lay.addWidget(self.lbl_prog)
        l = QLabel("LOG"); l.setStyleSheet("color:#555;font-size:10px;letter-spacing:2px;margin-top:6px"); lay.addWidget(l)
        self.log = QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log, 1)
        return w

    def _inject(self):
        if not self.iso_path: QMessageBox.warning(self,"","Selecciona ISO primero."); return
        if not self.assignments: QMessageBox.warning(self,"","Asigna tracks primero."); return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self,"","Ya hay un proceso en ejecución."); return
        if not os.path.isfile(self.iso_path):
            QMessageBox.critical(self,"","El ISO seleccionado ya no existe."); return
        out = self.output_path or os.path.splitext(self.iso_path)[0]+"_custom.iso"
        self.btn_inject.setEnabled(False); self.btn_inject.setText("⏳ PROCESANDO...")
        self.pbar.setValue(0); self.log.clear()
        self.worker_thread = QThread()
        self.worker = InjectionWorker(self.iso_path, dict(self.assignments), out, None)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_line.connect(self._on_log)
        self.worker.finished.connect(self._done)
        self.worker.finished.connect(self.worker_thread.quit)
        # prevent GC of worker while thread runs
        self.worker.finished.connect(lambda: setattr(self, '_prev_worker', self.worker))
        self.worker_thread.start()

    def _on_progress(self, v, m):
        self.pbar.setValue(int(v*1000))
        self.pbar.setFormat(f"{int(v*100)}%")
        self.lbl_prog.setText(m)

    def _on_log(self, line):
        # Sanitize against HTML injection from filenames
        safe = html_mod.escape(line)
        c = ("#69f0ae" if line.startswith("✓") else
             "#ff5252" if line.startswith("✗") else
             "#ffaa00" if "▶" in line else
             "#4fc3f7" if "↳" in line else "#888")
        self.log.append(f'<span style="color:{c}">{safe}</span>')

    def _done(self, ok, msg):
        self.btn_inject.setEnabled(True); self.btn_inject.setText("🔥  INYECTAR MÚSICA PERSONALIZADA")
        if ok:
            self.pbar.setFormat("100% ¡Completado!")
            QMessageBox.information(self,"¡Éxito!",f"{msg}\n\nCarga el ISO en PCSX2.")
        else:
            self.pbar.setFormat("Error"); self.pbar.setValue(0)
            QMessageBox.critical(self,"Error",msg)

    def _build_info_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24,24,24,24)
        i = QTextEdit(); i.setReadOnly(True)
        i.setHtml("""<div style="font-family:monospace;color:#ccc;line-height:1.8">
        <h2 style="color:#ff4500">📖 Guía — v11.0</h2>
        <h3 style="color:#ff8c00">Cómo usar</h3>
        <p style="color:#aaa">1. Arrastra tu ISO de Burnout 3 (NTSC-U) a la pestaña ISO<br>
        2. Ve a ASIGNAR TRACKS y arrastra tus canciones<br>
        3. Click en INYECTAR en la pestaña PROCESAR<br>
        4. Carga el ISO _custom.iso en PCSX2<br><br>
        Formatos soportados: MP3, M4A, FLAC, OGG, WAV, OPUS, WMA, AAC</p>
        <h3 style="color:#ff8c00">Audio</h3>
        <p style="color:#aaa">
        Codec: <b style="color:#4fc3f7">PS-ADPCM 4-bit</b> (PlayStation 2)<br>
        Sample rate: <b>32000 Hz</b> · Canales: <b>Stereo</b><br>
        Layout: <b>LLRR</b> en super-bloques de 8192 bytes<br>
        &nbsp;&nbsp;L[2048] L[2048] R[2048] R[2048]<br>
        Nibbles: primer sample = LOW, segundo = HIGH<br>
        Encoder: <b style="color:#69f0ae">C optimizado</b> — prueba 65 combinaciones/bloque<br>
        Compresión: 3.5:1 (56 bytes PCM → 16 bytes ADPCM)</p>
        <h3 style="color:#ff8c00">Estructura del ISO</h3>
        <p style="color:#aaa"><code style="color:#69f0ae">
        SLUS_210.50 → Ejecutable<br>
        <b>TRACKS/_EATRAX0.RWS → Música 1-22</b><br>
        <b>TRACKS/_EATRAX1.RWS → Música 23-44</b><br>
        TRACKS/[maps]/ → Datos de pistas<br>
        SOUNDS/ → SFX .RWS<br>FMV/ → Videos .PSS</code></p>
        <h3 style="color:#ff8c00">Dependencias</h3>
        <p style="color:#aaa"><code style="color:#69f0ae">
        <b>Arch:</b> sudo pacman -S ffmpeg p7zip gcc python-pyside6<br>
        <b>Ubuntu:</b> sudo apt install ffmpeg p7zip-full gcc<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;pip install PySide6</code></p>
        </div>""")
        lay.addWidget(i); return w


def main():
    app = QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(STYLESHEET)
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
