#!/usr/bin/env python3
"""
BURNOUT 3: TAKEDOWN — Custom Music Injector v11.2
Qt6 GUI (PySide6) — Linux Edition

Features:
  - Drag & drop ISO and audio files
  - Auto-detects 44 tracks in _EATRAX0.RWS & _EATRAX1.RWS
  - PS-ADPCM encoding with C accelerator (gcc auto-compile)
  - LLRR stereo layout, 32kHz, optimized 5×13 filter search
  - Multicore pipeline — convert + encode every song in parallel
  - Two-pass loudness matching to EA Trax's hot masters
  - In-place ISO patching (no rebuild needed)

INSTALL:
  pip install PySide6
  sudo pacman -S ffmpeg gcc  (Arch)
  sudo apt install ffmpeg gcc  (Debian/Ubuntu)

RUN:
  python3 burnout3_gui.py
"""

import sys, os, struct, subprocess, shutil, tempfile, math, html as html_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QProgressBar, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QTabWidget, QFrame, QGroupBox, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QSplitter
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QColor, QPalette

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
    {"id":1,  "artist":"No Motiv",                     "title":"Independence Day"},
    {"id":2,  "artist":"Amber Pacific",                "title":"Always You"},
    {"id":3,  "artist":"The Ordinary Boys",            "title":"Over The Counter Culture"},
    {"id":4,  "artist":"Funeral For A Friend",         "title":"Rookie Of The Year"},
    {"id":5,  "artist":"Chronic Future",               "title":"Time And Time Again"},
    {"id":6,  "artist":"Franz Ferdinand",              "title":"This Fire"},
    {"id":7,  "artist":"The Von Bondies",              "title":"C'mon C'mon"},
    {"id":8,  "artist":"Ramones",                      "title":"I Wanna Be Sedated"},
    {"id":9,  "artist":"Autopilot Off",                "title":"Make A Sound"},
    {"id":10, "artist":"Ash",                          "title":"Orpheus"},
    {"id":11, "artist":"Yellowcard",                   "title":"Breathing"},
    {"id":12, "artist":"Pennywise",                    "title":"Rise Up"},
    {"id":13, "artist":"Fall Out Boy",                 "title":"Reinventing The Wheel..."},
    {"id":14, "artist":"The F-Ups",                    "title":"Lazy Generation"},
    {"id":15, "artist":"The Lot Six",                  "title":"Autobrats"},
    {"id":16, "artist":"Sahara Hotnights",             "title":"Hot Night Crash"},
    {"id":17, "artist":"Eighteen Visions",             "title":"I Let Go"},
    {"id":18, "artist":"Donots",                       "title":"Saccharine Smile"},
    {"id":19, "artist":"From First To Last",           "title":"Populace In Two"},
    {"id":20, "artist":"Sugarcult",                    "title":"Memory"},
    {"id":21, "artist":"Finger Eleven",                "title":"Stay In Shadow"},
    {"id":22, "artist":"Reggie And The Full Effect",   "title":"Congratulations Smack And Katy"},
    {"id":23, "artist":"Local H",                      "title":"Everyone Alive"},
    {"id":24, "artist":"Maxeen",                       "title":"Please"},
    {"id":25, "artist":"New Found Glory",              "title":"At Least I'm Known For Something"},
    {"id":26, "artist":"My Chemical Romance",          "title":"I'm Not Okay (I Promise)"},
    {"id":27, "artist":"Go Betty Go",                  "title":"C'mon"},
    {"id":28, "artist":"Moments In Grace",             "title":"Broken Promises"},
    {"id":29, "artist":"Midtown",                      "title":"Give It Up"},
    {"id":30, "artist":"1208",                         "title":"Fall Apart"},
    {"id":31, "artist":"Motion City Soundtrack",       "title":"My Favorite Accident"},
    {"id":32, "artist":"Rise Against",                 "title":"Paper Wings"},
    {"id":33, "artist":"The Bouncing Souls",           "title":"Sing Along Forever"},
    {"id":34, "artist":"The Matches",                  "title":"Audio Blood"},
    {"id":35, "artist":"Silent Drive",                 "title":"4/16"},
    {"id":36, "artist":"The Explosion",                "title":"Here I Am"},
    {"id":37, "artist":"The D4",                       "title":"Come On!"},
    {"id":38, "artist":"The Mooney Suzuki",            "title":"Shake That Bush Again"},
    {"id":39, "artist":"Mudmen",                       "title":"Animal"},
    {"id":40, "artist":"The Futureheads",              "title":"Decent Days And Nights"},
    {"id":41, "artist":"Burning Brides",               "title":"Heart Full Of Black"},
    {"id":42, "artist":"Atreyu",                       "title":"Right Side Of The Bed"},
    {"id":43, "artist":"Letter Kills",                 "title":"Radio Up"},
    {"id":44, "artist":"Jimmy Eat World",              "title":"Just Tonight..."},
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

import ctypes

_c_lib = None

# Audio processing chain shared by both encode passes.
# Resample to 32 kHz with high-precision soxr, then a gentle 15.5 kHz lowpass
# (just under the 16 kHz Nyquist). 15.5 kHz keeps the brightness the old
# 14 kHz cutoff was throwing away while still taming aliasing.
AUDIO_RESAMPLE_FILTER = "aresample=resampler=soxr:precision=28,lowpass=f=15500"

# Loudness target. EA Trax masters are very hot, so custom music must be brought
# up to a comparable level or it sounds weak next to the original soundtrack and
# the engine SFX. Two-pass loudnorm (measure, then apply a linear gain) at
# ~-10 LUFS / -1 dBFS true peak matches the game without pumping artifacts.
LOUDNORM_TARGET = "I=-10:TP=-1.0:LRA=11"

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
        # Try aggressive flags first, fall back to plain -O3 if the toolchain
        # rejects them (e.g. -march=native unsupported on some cross compilers).
        flag_sets = [
            ["-O3", "-march=native", "-ffast-math", "-funroll-loops"],
            ["-O3"],
        ]
        compiled = False
        for flags in flag_sets:
            try:
                r = subprocess.run(
                    ["gcc", *flags, "-shared", "-fPIC", "-o", so_path, c_path, "-lm"],
                    capture_output=True, text=True, timeout=60
                )
                if r.returncode == 0:
                    compiled = True
                    break
            except Exception:
                continue
        if not compiled:
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


def _encode_python_fallback(pcm_bytes, slot_size):
    """Pure Python encoder — slower but always works, no numpy required."""
    import array, math
    samples = array.array('h')  # signed 16-bit
    samples.frombytes(pcm_bytes[:len(pcm_bytes) - (len(pcm_bytes) % 2)])
    left = samples[0::2]
    right = samples[1::2]

    buf = bytearray(slot_size)
    for i in range(0, slot_size, 16):
        buf[i] = 0x0C; buf[i+1] = 0x02

    _C1, _C2 = 1.796875, -0.8125

    def encode_ch(src, ch_offset):
        idx = 0; p1 = p2 = 0.0
        src_len = len(src)
        for sblock in range(0, slot_size, 8192):
            for sub in range(2):
                for block_i in range(0, 2048, 16):
                    boff = sblock + ch_offset + sub*2048 + block_i
                    if boff+16 > slot_size: return
                    max_d = 0.0; tp1=p1; tp2=p2
                    for i2 in range(8):
                        s = src[idx+i2] if idx+i2 < src_len else 0.0
                        d = abs(s-(tp1*_C1+tp2*_C2))
                        if d>max_d: max_d=d
                        tp2=tp1; tp1=s
                    shift = max(0,min(12, 12-int(math.log2(max(max_d/7.0,1.0)))))
                    scale = float(1<<(12-shift))
                    buf[boff]=(2<<4)|shift; buf[boff+1]=0x02
                    for i2 in range(28):
                        s = src[idx] if idx<src_len else 0.0; idx+=1
                        pred=p1*_C1+p2*_C2
                        raw=(s-pred)/scale if scale else 0.0
                        nib=max(-8,min(7,int(raw+(0.5 if raw>=0 else -0.5))))
                        dec=max(-32768.0,min(32767.0,nib*scale+pred))
                        # Match the integer decoder: it outputs int16 and feeds that back.
                        dec=float(int(dec+0.5) if dec>=0 else int(dec-0.5))
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


def probe_metadata(filepath):
    """Extract title, artist, album from audio file metadata via ffprobe."""
    try:
        import json
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries",
            "format_tags=title,artist,album",
            "-of", "json", filepath
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            tags = data.get("format", {}).get("tags", {})
            title = tags.get("title", tags.get("TITLE", ""))
            artist = tags.get("artist", tags.get("ARTIST", ""))
            album = tags.get("album", tags.get("ALBUM", ""))
            return title, artist, album
    except Exception:
        pass
    return "", "", ""


def _loudnorm_measure(source, target):
    """Pass 1 of two-pass loudnorm: analyze the source and return the measured
    loudness stats as a dict, or None on failure. No audio is produced."""
    try:
        import json
        r = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", source,
            "-af", f"loudnorm={target}:print_format=json",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=300)
        # The JSON report is printed as the last {...} block on stderr.
        err = r.stderr or ""
        start = err.rfind("{")
        end = err.rfind("}")
        if start != -1 and end > start:
            return json.loads(err[start:end + 1])
    except Exception:
        pass
    return None


def _loudnorm_filter(target, measured):
    """Build the loudnorm filter for the conversion pass. With valid pass-1
    stats this is a precise linear normalization; otherwise it falls back to
    single-pass dynamic loudnorm (still normalizes, just less precise)."""
    if measured:
        try:
            i  = float(measured["input_i"])
            tp = float(measured["input_tp"])
            lra = float(measured["input_lra"])
            th = float(measured["input_thresh"])
            off = float(measured["target_offset"])
            if all(math.isfinite(v) for v in (i, tp, lra, th, off)):
                return (f"loudnorm={target}"
                        f":measured_I={i}:measured_TP={tp}:measured_LRA={lra}"
                        f":measured_thresh={th}:offset={off}:linear=true")
        except (KeyError, ValueError, TypeError):
            pass
    return f"loudnorm={target}"


# ─── GLOBALUS.BIN String Table ──────────────────────────────────────────
# Music strings in DATA/GLOBALUS.BIN are UTF-16LE, null-terminated.
# Slots 1-40 live near 0xB700 in groups of 3 (title, album, artist); slots
# 41-44 live in a second region near 0x2C004. The game finds each string
# through a fixed pointer table (u32 offsets, e.g. at 0x784 for the music
# block), so strings must be patched IN PLACE — same offset, same byte length
# (truncate/null-pad). Moving them would invalidate the pointers.


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

    def __init__(self, iso_path, assignments, output_iso, metadata=None):
        super().__init__()
        self.iso_path = iso_path
        self.assignments = assignments
        self.output_iso = output_iso
        self.metadata = metadata or {}  # slot_id -> (title, artist, album)

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

    def _patch_globalus_bin(self, output_iso, iso_data, metadata):
        """Patch song names IN PLACE, at fixed byte length.

        The game finds each name through a fixed pointer table (u32 offsets, e.g.
        the music block at 0x784 points at the strings near 0xB700). Repacking the
        strings to different lengths would move them out from under those pointers,
        which is why the old 'dynamic redistribution' showed garbled / mismatched
        names. So every field is written at its ORIGINAL offset, truncated to the
        original byte length and null-padded — offsets never move, pointers stay
        valid. Names longer than the original field are truncated (matches the
        per-field character limits shown in the UI)."""
        offset, size = self._find_file_offset_iso9660(iso_data, "GLOBALUS.BIN")
        if not offset or not size:
            self.log_line.emit("  ⚠ GLOBALUS.BIN not found, skipping name patching")
            return

        with open(output_iso, 'r+b') as f:
            f.seek(offset)
            gdata = bytearray(f.read(size))

        def parse_strings(d, start, end):
            table = []
            pos = start
            while pos < min(len(d), end):
                while pos < len(d)-1 and d[pos]==0 and d[pos+1]==0:
                    pos += 2
                if pos >= min(len(d), end): break
                s_start = pos
                while pos < len(d)-1:
                    if d[pos]==0 and d[pos+1]==0: break
                    pos += 2
                text = d[s_start:pos].decode('utf-16-le', errors='replace')
                table.append((s_start, text, pos - s_start))
                pos += 2
            return table

        def write_field(s_off, max_bytes, text):
            """Overwrite the field at s_off with text truncated to max_bytes
            (whole UTF-16 code units) and null-padded. The string's offset and the
            terminator after it are never touched."""
            enc = text.encode('utf-16-le')[:max_bytes]
            enc = enc[:len(enc) // 2 * 2]
            gdata[s_off:s_off + len(enc)] = enc
            if len(enc) < max_bytes:
                gdata[s_off + len(enc):s_off + max_bytes] = b'\x00' * (max_bytes - len(enc))

        def patch_slot(st_table, base, slot_id):
            """Patch one slot's (title, album, artist) triple in place.
            On-disk order is title, album, artist; metadata is (title, artist, album)."""
            if base < 0 or base + 2 >= len(st_table):
                return 0
            title, artist, album = metadata[slot_id]
            n = 0
            for field, val in ((0, title), (1, album), (2, artist)):
                if not val:
                    continue
                s_off, _, blen = st_table[base + field]
                write_field(s_off, blen, val)
                n += 1
            return n

        patched = 0

        # ═══ Slots 1-40: main region, strings index 3+, groups of 3 ═══
        st = parse_strings(gdata, 0xB700, 0xD000)
        for slot_id in sorted(s for s in metadata if 1 <= s <= 40):
            patched += patch_slot(st, 3 + (slot_id - 1) * 3, slot_id)  # MUSIC_START=3

        # ═══ Slots 41-44: second region at 0x2C004 ═══
        slots_41_44 = sorted(s for s in metadata if 41 <= s <= 44)
        if slots_41_44:
            st2 = parse_strings(gdata, 0x2C004, 0x2C200)
            for slot_id in slots_41_44:
                patched += patch_slot(st2, (slot_id - 41) * 3, slot_id)

        if patched > 0:
            with open(output_iso, 'r+b') as f:
                f.seek(offset)
                f.write(gdata)
            self.log_line.emit(f"  ✓ Patched {patched} song-name fields (in-place, fixed length)")
        else:
            self.log_line.emit("  ↳ No song names to patch")

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

            # ═══ STEP 3: Convert all songs to PCM (parallel, loudness-matched) ═══
            self.log_line.emit("▶ Converting songs to PCM (parallel, loudness-matched)...")

            # Split assignments by EATRAX: slots 1-22 → EATRAX0, 23-44 → EATRAX1
            ea0_assignments = {k: v for k, v in self.assignments.items() if k <= 22}
            ea1_assignments = {k: v for k, v in self.assignments.items() if k > 22}

            n_cores = os.cpu_count() or 4

            def _convert(source, out_raw, loud=None, extra_pre="", duration=None):
                """Loudness-measure (pass 1) + convert → s16le 32k stereo. Thread-safe:
                only spawns ffmpeg subprocesses and touches its own out_raw file."""
                if loud is None:
                    loud = _loudnorm_filter(LOUDNORM_TARGET,
                                            _loudnorm_measure(source, LOUDNORM_TARGET))
                cmd = ["ffmpeg", "-y", "-i", source]
                if duration is not None:
                    cmd += ["-t", str(duration)]
                cmd += ["-af", f"{loud},{extra_pre}{AUDIO_RESAMPLE_FILTER}",
                        "-f", "s16le", "-acodec", "pcm_s16le",
                        "-ar", "32000", "-ac", "2", out_raw]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                ok = r.returncode == 0 and os.path.isfile(out_raw) and os.path.getsize(out_raw) > 0
                return ok, loud

            def _phase_a(item):
                slot_id, source = item
                src_name = os.path.basename(source)
                temp_raw = os.path.join(tmp, f"t{slot_id:02d}.raw")
                ok, loud = _convert(source, temp_raw)
                if not ok:
                    return slot_id, None, loud, src_name
                pcm_size = os.path.getsize(temp_raw)
                n_per_ch = (pcm_size // 2) // 2  # s16le stereo
                n_superblocks = (n_per_ch + 7167) // 7168
                adpcm_size = n_superblocks * 8192
                return (slot_id, (temp_raw, adpcm_size, src_name, adpcm_slot_duration(adpcm_size)),
                        loud, src_name)

            encoded = {}            # slot_id -> (temp_raw, adpcm_size, src_name, duration)
            loud_filter_by_slot = {}
            n_assign = len(self.assignments)
            with ThreadPoolExecutor(max_workers=max(1, min(n_cores, n_assign))) as ex:
                for fut in as_completed([ex.submit(_phase_a, it) for it in self.assignments.items()]):
                    slot_id, data, loud, src_name = fut.result()
                    loud_filter_by_slot[slot_id] = loud
                    if data:
                        encoded[slot_id] = data
                        self.log_line.emit(
                            f"  ✓ Slot {slot_id:02d}: {src_name} → {data[1]//1024}KB ({data[3]:.0f}s)"
                        )
                    else:
                        self.log_line.emit(f"✗ Slot {slot_id:02d}: ffmpeg error")
                    step += 1
                    self.progress.emit(step/total_steps, f"Converting ({len(encoded)}/{n_assign})...")

            if not encoded:
                raise Exception("No tracks were converted")

            # ═══ STEP 4: Plan track layout + proportional scaling (per EATRAX) ═══
            self.progress.emit(step/total_steps, "Planning track layout...")
            self.log_line.emit("▶ Planning layout and scaling")

            plans = {}        # eatrax_name -> (new_track_sizes, new_track_data)
            trunc_jobs = []   # scaled tracks that need an ffmpeg re-encode (fade-out + trim)

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

                assigned_need = {sid: encoded[sid][1] for sid in assignments if sid in encoded}
                total_needed = sum(assigned_need.values())

                total_unassigned = sum(orig_tracks[i][1] for i in range(n_orig)
                                       if (slot_start + i) not in assignments)
                space_for_custom = available_audio - total_unassigned
                self.log_line.emit(
                    f"  {eatrax_name}: {space_for_custom//1024}KB available for "
                    f"{len(assigned_need)} custom tracks (need {total_needed//1024}KB)"
                )

                # If songs exceed the fixed space, scale all proportionally with fade-out
                if total_needed > space_for_custom:
                    overflow = total_needed - space_for_custom
                    self.log_line.emit(
                        f"  ⚠ Songs exceed space by {overflow//1024}KB, scaling down proportionally"
                    )
                    scale = space_for_custom / total_needed
                    for sid in assigned_need:
                        ns = (int(assigned_need[sid] * scale) // 8192) * 8192  # align super-block
                        assigned_need[sid] = max(8192, ns)
                    # Fine-tune: if still over, trim the largest one super-block at a time
                    total_needed = sum(assigned_need.values())
                    while total_needed > space_for_custom:
                        biggest = max(assigned_need, key=assigned_need.get)
                        assigned_need[biggest] = max(8192, assigned_need[biggest] - 8192)
                        total_needed = sum(assigned_need.values())

                    # Queue the truncated tracks for a parallel fade-out re-encode
                    for sid in sorted(assigned_need):
                        _, orig_adpcm_size, src_name, _ = encoded[sid]
                        new_size = assigned_need[sid]
                        if new_size >= orig_adpcm_size:
                            continue  # no truncation needed
                        new_dur = adpcm_slot_duration(new_size)
                        fade_dur = 3
                        trunc_jobs.append({
                            'sid': sid, 'source': self.assignments[sid],
                            'raw': os.path.join(tmp, f"t{sid:02d}_trunc.raw"),
                            'size': new_size, 'dur': new_dur, 'src_name': src_name,
                            'fade_start': max(0, new_dur - fade_dur), 'fade_dur': fade_dur,
                            'loud': loud_filter_by_slot.get(sid) or f"loudnorm={LOUDNORM_TARGET}",
                        })

                new_track_sizes, new_track_data = [], []
                for i in range(n_orig):
                    sid = slot_start + i
                    if sid in assigned_need:
                        new_track_sizes.append(assigned_need[sid]); new_track_data.append((sid, True))
                    else:
                        new_track_sizes.append(orig_tracks[i][1]); new_track_data.append((sid, False))
                plans[eatrax_name] = (new_track_sizes, new_track_data)

            # Re-encode scaled tracks in parallel (fade-out + trim)
            if trunc_jobs:
                self.log_line.emit(f"▶ Re-encoding {len(trunc_jobs)} scaled tracks (parallel)...")

                def _do_trunc(job):
                    fade = f"afade=t=out:st={job['fade_start']:.1f}:d={job['fade_dur']},"
                    ok, _ = _convert(job['source'], job['raw'], loud=job['loud'],
                                     extra_pre=fade, duration=job['dur'])
                    return job, ok

                with ThreadPoolExecutor(max_workers=max(1, min(n_cores, len(trunc_jobs)))) as ex:
                    for fut in as_completed([ex.submit(_do_trunc, j) for j in trunc_jobs]):
                        job, ok = fut.result()
                        if ok:
                            encoded[job['sid']] = (job['raw'], job['size'], job['src_name'], job['dur'])
                            self.log_line.emit(
                                f"  ↳ Slot {job['sid']:02d}: {job['src_name']} scaled to "
                                f"{job['dur']:.0f}s ({job['size']//1024}KB)"
                            )

            # ═══ STEP 5: Encode all custom tracks to PS-ADPCM in parallel ═══
            self.progress.emit(step/total_steps, "Encoding PS-ADPCM...")
            self.log_line.emit("▶ Encoding PS-ADPCM (parallel — all cores)")

            encode_targets = {}  # slot_id -> target byte size
            for sizes, data in plans.values():
                for (sid, is_custom), sz in zip(data, sizes):
                    if is_custom and sid in encoded:
                        encode_targets[sid] = sz

            adpcm_by_slot = {}

            def _encode_one(sid):
                with open(encoded[sid][0], 'rb') as af:
                    pcm = af.read()
                return sid, encode_psx_adpcm_sized(pcm, encode_targets[sid])

            if encode_targets:
                done_enc = 0
                with ThreadPoolExecutor(max_workers=max(1, min(n_cores, len(encode_targets)))) as ex:
                    for fut in as_completed([ex.submit(_encode_one, sid) for sid in encode_targets]):
                        sid, audio = fut.result()
                        adpcm_by_slot[sid] = audio
                        done_enc += 1
                        self.progress.emit(step/total_steps,
                                           f"Encoding ({done_enc}/{len(encode_targets)})...")
            step += 1

            # ═══ STEP 6: Write patched ISO (sequential, in-order) ═══
            self.log_line.emit("▶ Writing patched EATRAX containers")
            replaced = 0
            with open(self.output_iso, 'r+b') as iso_out:
                for eatrax_name, assignments, slot_start in [
                    ("_EATRAX0.RWS", ea0_assignments, 1),
                    ("_EATRAX1.RWS", ea1_assignments, 23),
                ]:
                    if eatrax_name not in plans:
                        continue

                    ea = eatrax_info[eatrax_name]
                    orig_tracks = ea['tracks']
                    n_orig = len(orig_tracks)
                    new_track_sizes, new_track_data = plans[eatrax_name]

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

                    # Write track audio data in order (custom = pre-encoded, else original)
                    for i, (sid, is_custom) in enumerate(new_track_data):
                        self.progress.emit(step/total_steps, f"Writing track {sid}...")

                        if is_custom:
                            audio = adpcm_by_slot.get(sid)
                            if audio is None:
                                # Defensive fallback: encode synchronously
                                with open(encoded[sid][0], 'rb') as af:
                                    audio = encode_psx_adpcm_sized(af.read(), new_track_sizes[i])
                            iso_out.write(audio)
                            self.log_line.emit(
                                f"✓ Slot {sid:02d}: {html_mod.escape(encoded[sid][2])} → "
                                f"{new_track_sizes[i]//1024}KB ({adpcm_slot_duration(new_track_sizes[i]):.0f}s)"
                            )
                            replaced += 1
                        else:
                            # Write pre-read original track data
                            iso_out.write(orig_track_data[i])

                    # Zero-pad any remaining space
                    actual_file_size = 24 + ea['hsize'] + 12 + new_total_audio
                    if actual_file_size < ea['file_size']:
                        remaining = ea['file_size'] - actual_file_size
                        zero_chunk = b'\x00' * min(1048576, remaining)
                        w = 0
                        while w < remaining:
                            to_write = min(len(zero_chunk), remaining - w)
                            iso_out.write(zero_chunk[:to_write])
                            w += to_write

                    self.log_line.emit(
                        f"✓ {eatrax_name}: {len(assignments)} custom tracks, "
                        f"{new_total_audio/1048576:.1f}MB used of {ea['total_audio']/1048576:.1f}MB"
                    )

            if replaced == 0:
                if os.path.isfile(self.output_iso):
                    os.remove(self.output_iso)
                raise Exception("No tracks were patched")

            # ═══ STEP 5: Patch song names in GLOBALUS.BIN ═══
            if self.metadata:
                self.log_line.emit("▶ Patching song names in GLOBALUS.BIN...")
                self._patch_globalus_bin(self.output_iso, iso_data, self.metadata)

            self.progress.emit(1.0, "Completed!")
            self.log_line.emit(f"✓ {replaced} tracks patched!")
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


# ─── Expansion Worker (HostFS — add NEW tracks beyond 44) ──────────────────
class ExpansionWorker(QObject):
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, hostfs_dir, slots, cheats_dir):
        super().__init__()
        self.hostfs_dir = hostfs_dir
        self.slots = slots          # list: None (keep original) or {song,title,artist,album}
        self.cheats_dir = cheats_dir

    def run(self):
        try:
            import eatrax_expansion as ee
            res = ee.build_soundtrack(self.hostfs_dir, self.slots,
                                      cheats_dir=self.cheats_dir, log=self.log_line.emit,
                                      progress=self.log_line.emit)
            n = res["count"]; custom = res["custom"]
            files = ", ".join(f"_eatrax{f}.rws" for f in res["files"]) or "(originals untouched)"
            msg = (f"Soundtrack built: {n} track(s) total — {custom} custom, {n-custom} original.\n"
                   f"Rebuilt: {files}\n"
                   f"Names + GLOBALUS rebuilt; pnach: {res.get('pnach_path') or '(no PCSX2 cheats dir found — pnach not written)'}\n\n"
                   "In PCSX2 enable cheats: [HostFS] + [ELF Code Cave] + [EATRAX expansion], "
                   "then boot the ISO from the HostFS (ciopfs) mount.")
            self.log_line.emit("✓ Done.")
            self.finished.emit(True, msg)
        except Exception as e:
            self.finished.emit(False, str(e))


class PortableIsoWorker(QObject):
    """Bake a self-contained ISO (no cheats, no HostFS) via surgical EATRAX/globalus relocation."""
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, clean_iso, out_iso, slots):
        super().__init__()
        self.clean_iso = clean_iso; self.out_iso = out_iso; self.slots = slots

    def run(self):
        try:
            import importlib.util
            here = os.path.dirname(os.path.abspath(__file__))
            spec = importlib.util.spec_from_file_location(
                "build_portable_iso", os.path.join(here, "research", "build_portable_iso.py"))
            bp = importlib.util.module_from_spec(spec); spec.loader.exec_module(bp)
            res = bp.build_portable_iso(self.clean_iso, self.out_iso, self.slots,
                                        log=self.log_line.emit, progress=self.log_line.emit)
            mb = res["size"] // (1024 * 1024)
            files = ", ".join(f"_eatrax{f}.rws" for f in res["files"])
            msg = (f"Portable ISO built — {res['custom']} full-length custom track(s) ({mb} MB).\n"
                   f"Rebuilt: {files}\n{self.out_iso}\n\n"
                   "Self-contained: NO cheats, NO HostFS. Boots in PCSX2, Android "
                   "(AetherSX2/NetherSX2) and real PS2 — just load this ISO.")
            self.log_line.emit("✓ Done.")
            self.finished.emit(True, msg)
        except Exception as e:
            import traceback
            self.finished.emit(False, f"{e}\n{traceback.format_exc()[-600:]}")


# ─── Main Window ──────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Burnout 3: Takedown — Custom Music Injector v11.2")
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
        d = {"ffmpeg": bool(shutil.which("ffmpeg"))}
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
        s = QLabel("CUSTOM MUSIC INJECTOR v11.2"); s.setObjectName("subtitleLabel"); ta.addWidget(s)
        hl.addLayout(ta); hl.addStretch()
        da = QVBoxLayout(); da.setSpacing(1)
        for name, key in [("ffmpeg","ffmpeg"),("gcc (C encoder)","gcc")]:
            ok = self.deps.get(key, False)
            txt = f"{'✓' if ok else '✗'} {name}"
            lb = QLabel(txt); lb.setStyleSheet(f"font-size:10px;color:{'#69f0ae' if ok else '#ff5252'}")
            da.addWidget(lb)
        hl.addLayout(da)
        lay.addWidget(hdr)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_iso_tab(), "📀  ISO + FILESYSTEM")
        # Legacy ASSIGN TRACKS + PROCESS merged into SOUNDTRACK; widgets still built (they back the
        # in-place injection engine + ISO-load wiring) but their tabs are hidden to avoid duplication.
        self._legacy_tracks_w = self._build_tracks_tab()
        self._legacy_process_w = self._build_process_tab()
        self.tabs.addTab(self._build_soundtrack_tab(), "🎶  SOUNDTRACK")
        self.tabs.addTab(self._build_info_tab(), "📖  GUIDE")

        ft = QLabel("Burnout 3: Takedown™ — Electronic Arts · PS-ADPCM LLRR encoder · v11.2")
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
        tg = QGroupBox("Known ISO Structure")
        tl = QVBoxLayout(tg)
        self.fs_tree = QTreeWidget()
        self.fs_tree.setHeaderLabels(["File / Folder","Description"])
        self.fs_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.fs_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._fill_tree()
        tl.addWidget(self.fs_tree)
        sp.addWidget(tg)
        # Info
        ig = QGroupBox("Loaded ISO Information")
        il = QVBoxLayout(ig)
        self.iso_info = QTextEdit()
        self.iso_info.setReadOnly(True)
        self.iso_info.setHtml('<div style="color:#666;font-style:italic">Drag or select an ISO</div>')
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
        <b style="color:#ff8c00">File:</b> <span style="color:#4fc3f7">{os.path.basename(path)}</span><br>
        <b style="color:#ff8c00">Size:</b> {sz:.1f} MB<br>
        <b style="color:#ff8c00">Path:</b> <span style="color:#888">{path}</span><br>
        <b style="color:#ff8c00">Output:</b> <span style="color:#888">{self.output_path}</span><br><br>
        <b style="color:#ff8c00">Expected audio structure:</b><br>
        <span style="color:#69f0ae">TRACKS/_EATRAX0.RWS</span> — Songs 1-22<br>
        <span style="color:#69f0ae">TRACKS/_EATRAX1.RWS</span> — Songs 23-44<br><br>
        <b style="color:#ff8c00">Internal format:</b><br>
        Container: RenderWare Stream (.RWS)<br>
        Codec: PS-ADPCM · Chunks: 0x080D/0x080E/0x080F<br>
        Layout: LLRR stereo · 32kHz · 4-bit ADPCM<br>
        </div>""")

        # Parse GLOBALUS.BIN to get string limits per slot
        self._parse_globalus_limits(path)

        self._update_inject_btn()
        self.tabs.setCurrentIndex(1)

    def _parse_globalus_limits(self, iso_path):
        """Parse GLOBALUS.BIN from ISO to find char limits and original names for each slot."""
        self.slot_char_limits = {}  # slot_id -> (title_max_chars, album_max_chars, artist_max_chars)
        self.slot_original_names = {}  # slot_id -> (title, album, artist)

        try:
            with open(iso_path, 'rb') as f:
                iso_data = f.read()

            # Find GLOBALUS.BIN
            worker = InjectionWorker.__new__(InjectionWorker)
            offset, size = InjectionWorker._find_file_offset_iso9660(worker, iso_data, "GLOBALUS.BIN")
            if not offset or not size:
                return

            gdata = iso_data[offset:offset+size]

            # Parse strings from 0xB700
            string_table = []
            pos = 0xB700
            while pos < min(len(gdata), 0xD000):
                while pos < len(gdata) - 1 and gdata[pos] == 0 and gdata[pos+1] == 0:
                    pos += 2
                if pos >= min(len(gdata), 0xD000):
                    break
                start = pos
                while pos < len(gdata) - 1:
                    if gdata[pos] == 0 and gdata[pos+1] == 0:
                        break
                    pos += 2
                text = gdata[start:pos].decode('utf-16-le', errors='replace')
                byte_len = pos - start
                if len(text) > 0:
                    string_table.append((start, text, byte_len))
                pos += 2

            # Music strings start at index 3, groups of 3: (title, album, artist)
            MUSIC_START = 3
            for slot_id in range(1, 41):  # Slots 1-40 have sequential 3-per-song strings
                base = MUSIC_START + (slot_id - 1) * 3
                if base + 2 >= len(string_table):
                    break
                _, title_text, title_bytes = string_table[base]
                _, album_text, album_bytes = string_table[base + 1]
                _, artist_text, artist_bytes = string_table[base + 2]
                self.slot_char_limits[slot_id] = (
                    title_bytes // 2,
                    album_bytes // 2,
                    artist_bytes // 2
                )
                self.slot_original_names[slot_id] = (title_text, album_text, artist_text)

            # Slots 41-44: second region at 0x2C004
            string_table_2 = []
            pos2 = 0x2C004
            while pos2 < min(len(gdata), 0x2C200):
                while pos2 < len(gdata) - 1 and gdata[pos2] == 0 and gdata[pos2+1] == 0:
                    pos2 += 2
                if pos2 >= 0x2C200: break
                start2 = pos2
                while pos2 < len(gdata) - 1:
                    if gdata[pos2] == 0 and gdata[pos2+1] == 0: break
                    pos2 += 2
                text2 = gdata[start2:pos2].decode('utf-16-le', errors='replace')
                blen2 = pos2 - start2
                if len(text2) > 0:
                    string_table_2.append((start2, text2, blen2))
                pos2 += 2

            for slot_id in range(41, 45):
                base2 = (slot_id - 41) * 3
                if base2 + 2 >= len(string_table_2):
                    break
                _, title_text, title_bytes = string_table_2[base2]
                _, album_text, album_bytes = string_table_2[base2 + 1]
                _, artist_text, artist_bytes = string_table_2[base2 + 2]
                self.slot_char_limits[slot_id] = (
                    title_bytes // 2,
                    album_bytes // 2,
                    artist_bytes // 2
                )
                self.slot_original_names[slot_id] = (title_text, album_text, artist_text)

            # Update table with char limits as placeholder text
            self._update_table_limits()

        except Exception:
            pass

    def _update_table_limits(self):
        """Update table cells with placeholder text showing char limits."""
        for slot_id, (title_max, album_max, artist_max) in self.slot_char_limits.items():
            row = slot_id - 1
            if row >= self.table.rowCount():
                break

            # Update original song column with real names from GLOBALUS.BIN
            if slot_id in self.slot_original_names:
                orig_title, orig_album, orig_artist = self.slot_original_names[slot_id]
                orig_item = QTableWidgetItem(f" {orig_artist} — {orig_title}")
                orig_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                orig_item.setForeground(QColor("#777"))
                orig_item.setToolTip(f"Title: {orig_title}\nAlbum: {orig_album}\nArtist: {orig_artist}")
                self.table.setItem(row, 1, orig_item)

            # Set placeholder text showing max chars for Title/Artist/Album
            for col, max_chars in [(3, title_max), (4, artist_max), (5, album_max)]:
                item = self.table.item(row, col)
                if item and not item.text().strip():
                    item.setToolTip(f"Max {max_chars} characters")
                    # Use setData to store the limit
                    item.setData(Qt.ItemDataRole.UserRole, max_chars)

    def _build_tracks_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)
        tb = QHBoxLayout()
        for txt, fn in [("➕ Add audio",self._add_files),("📁 Add folder",self._add_folder),("⚡ Auto-assign",self._auto_assign)]:
            b = QPushButton(txt); b.clicked.connect(fn); tb.addWidget(b)
        tb.addStretch()
        bc = QPushButton("🗑 Clear"); bc.setObjectName("dangerBtn"); bc.clicked.connect(self._clear_all); tb.addWidget(bc)
        lay.addLayout(tb)
        hint = QLabel("Drag audio files/folders · Metadata (title/artist/album) auto-fills from file tags")
        hint.setStyleSheet("color:#555;font-size:11px"); lay.addWidget(hint)

        self.table = TrackTable(len(EA_TRAX_SONGS), 7)
        self.table.setHorizontalHeaderLabels(["SLOT","ORIGINAL SONG","YOUR MUSIC","TITLE","ARTIST","ALBUM","ACTION"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.files_dropped.connect(self._on_drop)
        h = self.table.horizontalHeader()
        for i, (mode, w_) in enumerate([
            (QHeaderView.ResizeMode.Fixed, 40),
            (QHeaderView.ResizeMode.Interactive, 180),
            (QHeaderView.ResizeMode.Interactive, 180),
            (QHeaderView.ResizeMode.Stretch, 0),
            (QHeaderView.ResizeMode.Interactive, 140),
            (QHeaderView.ResizeMode.Interactive, 120),
            (QHeaderView.ResizeMode.Fixed, 65)
        ]):
            h.setSectionResizeMode(i, mode)
            if w_: self.table.setColumnWidth(i, w_)
        self._fill_table()
        lay.addWidget(self.table, 1)
        self.lbl_assigned = QLabel("0 / 44 tracks assigned")
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
            # Col 3: Title (editable)
            ct = QTableWidgetItem(""); ct.setForeground(QColor("#4fc3f7"))
            self.table.setItem(row, 3, ct)
            # Col 4: Artist (editable)
            ca = QTableWidgetItem(""); ca.setForeground(QColor("#4fc3f7"))
            self.table.setItem(row, 4, ca)
            # Col 5: Album (editable)
            cb = QTableWidgetItem(""); cb.setForeground(QColor("#4fc3f7"))
            self.table.setItem(row, 5, cb)
            # Col 6: Action button
            b = QPushButton("Assign"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px")
            b.clicked.connect(lambda _, s=song['id']: self._assign_single(s))
            self.table.setCellWidget(row, 6, b)
            self.table.setRowHeight(row, 34)

    def _upd_row(self, sid, fp=None):
        row = sid - 1
        if row < 0 or row >= self.table.rowCount():
            return
        if fp:
            it = QTableWidgetItem(f" {os.path.basename(fp)}"); it.setFlags(Qt.ItemFlag.ItemIsEnabled)
            it.setForeground(QColor("#69f0ae")); it.setToolTip(fp)
            self.table.setItem(row, 2, it)
            # Auto-fill title/artist/album from metadata if columns are empty
            title_item = self.table.item(row, 3)
            artist_item = self.table.item(row, 4)
            album_item = self.table.item(row, 5)
            if (not title_item or not title_item.text().strip()) or \
               (not artist_item or not artist_item.text().strip()):
                meta_title, meta_artist, meta_album = probe_metadata(fp)
                if not meta_title:
                    meta_title = os.path.splitext(os.path.basename(fp))[0]

                # Get char limits for this slot
                limits = getattr(self, 'slot_char_limits', {}).get(sid, (99, 99, 99))
                title_max, album_max, artist_max = limits

                # Set title with limit info
                if title_item and not title_item.text().strip():
                    self._set_limited_text(row, 3, meta_title, title_max)
                elif not title_item:
                    self._set_limited_text(row, 3, meta_title, title_max)

                if meta_artist and (not artist_item or not artist_item.text().strip()):
                    self._set_limited_text(row, 4, meta_artist, artist_max)

                if meta_album and (not album_item or not album_item.text().strip()):
                    self._set_limited_text(row, 5, meta_album, album_max)

            b = QPushButton("Remove"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px;background:rgba(255,50,50,0.15);color:#ff5252;border:1px solid rgba(255,50,50,0.3)")
            b.clicked.connect(lambda _, s=sid: self._remove(s))
            self.table.setCellWidget(row, 6, b)
        else:
            it = QTableWidgetItem(" —"); it.setFlags(Qt.ItemFlag.ItemIsEnabled); it.setForeground(QColor("#444"))
            self.table.setItem(row, 2, it)
            # Clear metadata columns
            for col in [3, 4, 5]:
                self.table.setItem(row, col, QTableWidgetItem(""))
            b = QPushButton("Assign"); b.setFixedHeight(26)
            b.setStyleSheet("font-size:10px;padding:2px 8px;border-radius:4px")
            b.clicked.connect(lambda _, s=sid: self._assign_single(s))
            self.table.setCellWidget(row, 6, b)

    def _set_limited_text(self, row, col, text, max_chars):
        """Set cell text with color-coding. The limit is HARD: names are written
        in place at the original field's byte length, so anything longer than
        max_chars is truncated in-game."""
        item = QTableWidgetItem(text)
        if len(text) > max_chars:
            # Exceeds the original field length — will be truncated in-game
            item.setForeground(QColor("#ffaa00"))
            item.setToolTip(f"⚠ Too long ({len(text)}/{max_chars} chars) — will be truncated to {max_chars}")
        else:
            item.setForeground(QColor("#4fc3f7"))
            item.setToolTip(f"✓ Fits ({len(text)}/{max_chars} chars)")
        self.table.setItem(row, col, item)

    def _update_inject_btn(self):
        n = len(self.assignments)
        if hasattr(self,'lbl_assigned'): self.lbl_assigned.setText(f"{n} / 44 tracks assigned")
        if hasattr(self,'btn_inject'):
            self.btn_inject.setEnabled(
                n > 0
                and self.iso_path is not None
                and bool(self.deps.get("ffmpeg"))
            )

    def _assign_single(self, sid):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, f"Audio for Slot {sid:02d}", "", f"Audio (*.{exts})")
        if fs: self.assignments[sid]=fs[0]; self._upd_row(sid,fs[0]); self._update_inject_btn()

    def _remove(self, sid):
        self.assignments.pop(sid,None); self._upd_row(sid); self._update_inject_btn()

    def _add_files(self):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, "Select audio files", "", f"Audio (*.{exts})")
        if fs: self._auto_files(sorted(fs))

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select music folder")
        if d:
            fs = sorted([os.path.join(d,f) for f in os.listdir(d)
                         if os.path.isfile(os.path.join(d,f)) and os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS])
            if fs: self._auto_files(fs)
            else: QMessageBox.warning(self,"No audio","No audio files found in this folder.")

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
        if not self.assignments: QMessageBox.information(self,"","Add files first."); return
        fs = list(self.assignments.values()); self._clear_all(); self._auto_files(sorted(fs))

    def _clear_all(self):
        for s in list(self.assignments.keys()): self._upd_row(s)
        self.assignments.clear(); self._update_inject_btn()

    # ─── SOUNDTRACK tab (HostFS — full soundtrack: replace any of 44 + add beyond) ──
    def _build_soundtrack_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)
        note = QLabel("The 44 originals are pre-loaded — assign a song to a slot to replace it, or add new "
                      "ones below; untouched slots keep the original track. Names auto-romanize from any "
                      "language. Then pick a build:\n"
                      "  💿 PORTABLE ISO — 44 full-length + unlimited names, self-contained, no cheats (PCSX2/Android/PS2).\n"
                      "  📀 IN-PLACE ISO — replaces the 44 in the same-size ISO (scaled to fit, original-length names, "
                      "preserves CRC). Needs an ISO loaded in the ISO tab.\n"
                      "  🛠 HostFS — adds N tracks beyond 44 (full-length); needs cheats [HostFS]+[ELF Code Cave]+[EATRAX expansion].")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;font-size:11px;padding:10px;background:rgba(255,140,0,0.05);border:1px solid #222;border-radius:8px")
        lay.addWidget(note)

        self.exp_folder = os.path.expanduser("~/burnout3_hostfs")
        fr = QHBoxLayout()
        self.lbl_expfolder = QLabel(f"HostFS folder: {self.exp_folder}")
        self.lbl_expfolder.setStyleSheet("color:#4fc3f7;font-size:11px")
        fr.addWidget(self.lbl_expfolder, 1)
        bf = QPushButton("📂 HostFS folder"); bf.clicked.connect(self._st_choose_folder); fr.addWidget(bf)
        lay.addLayout(fr)

        tb = QHBoxLayout()
        bl = QPushButton("📁 Load folder (replace from #1)"); bl.clicked.connect(self._st_load_folder); tb.addWidget(bl)
        ba = QPushButton("➕ Add songs (append)"); ba.clicked.connect(self._st_add_songs); tb.addWidget(ba)
        br = QPushButton("➖ Remove / reset selected"); br.setObjectName("dangerBtn"); br.clicked.connect(self._st_remove_selected); tb.addWidget(br)
        bz = QPushButton("↺ Reset all"); bz.setObjectName("dangerBtn"); bz.clicked.connect(self._st_reset_all); tb.addWidget(bz)
        tb.addStretch()
        self.lbl_expcount = QLabel(""); self.lbl_expcount.setStyleSheet("color:#ff8c00;font-weight:bold"); tb.addWidget(self.lbl_expcount)
        lay.addLayout(tb)

        self.exp_table = TrackTable(0, 6)
        self.exp_table.setHorizontalHeaderLabels(["#","SONG","TITLE","ARTIST","ALBUM","⟳"])
        self.exp_table.setAlternatingRowColors(True)
        self.exp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.exp_table.verticalHeader().setVisible(False)
        self.exp_table.files_dropped.connect(self._st_add_songs_paths)
        h = self.exp_table.horizontalHeader()
        for i,(m,wd) in enumerate([(QHeaderView.ResizeMode.Fixed,44),(QHeaderView.ResizeMode.Stretch,0),
            (QHeaderView.ResizeMode.Interactive,160),(QHeaderView.ResizeMode.Interactive,150),
            (QHeaderView.ResizeMode.Interactive,130),(QHeaderView.ResizeMode.Fixed,40)]):
            h.setSectionResizeMode(i,m)
            if wd: self.exp_table.setColumnWidth(i,wd)
        lay.addWidget(self.exp_table, 1)

        self.btn_build_iso = QPushButton("💿  BUILD PORTABLE ISO   —   full-length + unlimited names · no cheats · PCSX2/Android/PS2")
        self.btn_build_iso.setObjectName("primaryBtn"); self.btn_build_iso.setMinimumHeight(46)
        self.btn_build_iso.clicked.connect(self._st_build_portable)
        lay.addWidget(self.btn_build_iso)
        self.btn_build_inplace = QPushButton("📀  BUILD IN-PLACE ISO   —   same size · preserves CRC · scaled to fit (44 only)")
        self.btn_build_inplace.setMinimumHeight(38)
        self.btn_build_inplace.clicked.connect(self._st_build_inplace)
        lay.addWidget(self.btn_build_inplace)
        self.btn_build_exp = QPushButton("🛠  BUILD HostFS folder   —   +tracks beyond 44 · needs PCSX2 cheats")
        self.btn_build_exp.setMinimumHeight(38)
        self.btn_build_exp.clicked.connect(self._st_build)
        lay.addWidget(self.btn_build_exp)
        self.exp_log = QTextEdit(); self.exp_log.setReadOnly(True); self.exp_log.setMaximumHeight(120); lay.addWidget(self.exp_log)
        self._st_reset_all()
        return w

    def _st_choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select HostFS folder (extracted disc)", self.exp_folder)
        if d:
            self.exp_folder = d; self.lbl_expfolder.setText(f"HostFS folder: {d}")

    def _st_romanizer(self):
        try:
            import eatrax_expansion as ee; return ee.romanize
        except Exception:
            return lambda x: x

    def _st_row_of(self, widget):
        for r in range(self.exp_table.rowCount()):
            if self.exp_table.cellWidget(r, 5) is widget: return r
        return -1

    def _st_insert_row(self, r):
        self.exp_table.insertRow(r)
        num = QTableWidgetItem(str(r + 1)); num.setFlags(Qt.ItemFlag.ItemIsEnabled)
        num.setForeground(QColor("#666")); num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.exp_table.setItem(r, 0, num)
        b = QPushButton("📁"); b.setFixedHeight(24); b.setToolTip("Replace this slot's song")
        b.setStyleSheet("font-size:11px;padding:1px;border-radius:4px")
        b.clicked.connect(lambda _, btn=b: self._st_replace_row(self._st_row_of(btn)))
        self.exp_table.setCellWidget(r, 5, b)
        self.exp_table.setRowHeight(r, 30)

    def _st_set_keep(self, r, slot_idx):
        s = EA_TRAX_SONGS[slot_idx] if slot_idx < len(EA_TRAX_SONGS) else {"artist": "", "title": ""}
        song = QTableWidgetItem(f"♪ {s['artist']} — {s['title']}  (original)")
        song.setFlags(Qt.ItemFlag.ItemIsEnabled); song.setForeground(QColor("#777"))
        song.setData(Qt.ItemDataRole.UserRole, None)
        self.exp_table.setItem(r, 1, song)
        for col, val in [(2, s["title"]), (3, s["artist"]), (4, "")]:
            it = QTableWidgetItem(val); it.setFlags(Qt.ItemFlag.ItemIsEnabled); it.setForeground(QColor("#666"))
            self.exp_table.setItem(r, col, it)

    def _st_set_custom(self, r, path):
        rom = self._st_romanizer()
        ti, ar, al = probe_metadata(path)
        if not ti: ti = os.path.splitext(os.path.basename(path))[0]
        ti, ar, al = rom(ti), rom(ar), rom(al)
        song = QTableWidgetItem("▶ " + os.path.basename(path))
        song.setFlags(Qt.ItemFlag.ItemIsEnabled); song.setForeground(QColor("#69f0ae"))
        song.setToolTip(path); song.setData(Qt.ItemDataRole.UserRole, path)
        self.exp_table.setItem(r, 1, song)
        for col, val in [(2, ti), (3, ar), (4, al)]:
            it = QTableWidgetItem(val); it.setForeground(QColor("#4fc3f7")); self.exp_table.setItem(r, col, it)

    def _st_replace_row(self, r):
        if r < 0: return
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fp, _ = QFileDialog.getOpenFileName(self, f"Pick a song for slot #{r+1}", "", f"Audio (*.{exts})")
        if fp:
            self._st_set_custom(r, fp); self._st_update_count()

    def _st_load_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select a folder of songs (replaces from slot #1)")
        if not d: return
        fs = sorted(os.path.join(d, f) for f in os.listdir(d)
                    if os.path.isfile(os.path.join(d, f)) and os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS)
        if not fs:
            QMessageBox.warning(self, "No audio", "No audio files found in that folder."); return
        for i, fp in enumerate(fs):
            if i >= self.exp_table.rowCount(): self._st_insert_row(self.exp_table.rowCount())
            self._st_set_custom(i, fp)
        self._st_renumber(); self._st_update_count()

    def _st_add_songs(self):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, "Add songs (append as new tracks)", "", f"Audio (*.{exts})")
        if fs: self._st_add_songs_paths(sorted(fs))

    def _st_add_songs_paths(self, files):
        for fp in files:
            r = self.exp_table.rowCount(); self._st_insert_row(r); self._st_set_custom(r, fp)
        self._st_renumber(); self._st_update_count()

    def _st_remove_selected(self):
        rows = sorted({i.row() for i in self.exp_table.selectedIndexes()}, reverse=True)
        for r in rows:
            if r >= len(EA_TRAX_SONGS): self.exp_table.removeRow(r)       # added track -> remove
            else: self._st_set_keep(r, r)                                  # original slot -> reset
        self._st_renumber(); self._st_update_count()

    def _st_reset_all(self):
        self.exp_table.setRowCount(0)
        for i in range(len(EA_TRAX_SONGS)):
            self._st_insert_row(i); self._st_set_keep(i, i)
        self._st_update_count()

    def _st_renumber(self):
        for r in range(self.exp_table.rowCount()):
            it = self.exp_table.item(r, 0)
            if it: it.setText(str(r + 1))

    def _st_update_count(self):
        n = self.exp_table.rowCount()
        custom = sum(1 for r in range(n)
                     if self.exp_table.item(r, 1) and self.exp_table.item(r, 1).data(Qt.ItemDataRole.UserRole))
        self.lbl_expcount.setText(f"{n} tracks · {custom} custom · {n - custom} original")

    def _st_build(self):
        n = self.exp_table.rowCount()
        if not os.path.isdir(self.exp_folder):
            QMessageBox.critical(self, "", "HostFS folder not found. Pick the extracted-disc folder."); return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "", "Already processing."); return
        if not self.deps.get("ffmpeg"):
            QMessageBox.critical(self, "", "ffmpeg not found."); return
        slots = []; custom = 0
        for r in range(n):
            si = self.exp_table.item(r, 1); fp = si.data(Qt.ItemDataRole.UserRole) if si else None
            if fp and os.path.isfile(fp):
                def cell(c): it = self.exp_table.item(r, c); return (it.text().strip() if it else "")
                slots.append({"song": fp, "title": cell(2) or os.path.splitext(os.path.basename(fp))[0],
                              "artist": cell(3), "album": cell(4)})
                custom += 1
            else:
                slots.append(None)
        if custom == 0:
            QMessageBox.warning(self, "", "Assign at least one song (replace a slot or add new ones)."); return
        cheats = os.path.expanduser("~/.var/app/net.pcsx2.PCSX2/config/PCSX2/cheats")
        cheats = cheats if os.path.isdir(cheats) else None
        self.btn_build_exp.setEnabled(False); self.btn_build_exp.setText("⏳ BUILDING..."); self.exp_log.clear()
        self.worker_thread = QThread()
        self.exp_worker = ExpansionWorker(self.exp_folder, slots, cheats)
        self.exp_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.exp_worker.run)
        self.exp_worker.log_line.connect(self._st_log_line)
        self.exp_worker.finished.connect(self._st_done)
        self.exp_worker.finished.connect(self.worker_thread.quit)
        self.exp_worker.finished.connect(lambda: setattr(self, "_prev_exp_worker", self.exp_worker))
        self.worker_thread.start()

    def _st_log_line(self, s):
        c = "#69f0ae" if s.startswith("✓") else "#ff5252" if s.startswith("✗") else "#aaa"
        self.exp_log.append(f'<span style="color:{c}">{html_mod.escape(s)}</span>')

    def _st_done(self, ok, msg):
        self.btn_build_exp.setEnabled(True)
        self.btn_build_exp.setText("🛠  BUILD HostFS folder   —   +tracks beyond 44 · needs PCSX2 cheats")
        if ok:
            QMessageBox.information(self, "Soundtrack built!", msg)
        else:
            QMessageBox.critical(self, "Error", msg)

    def _st_build_portable(self):
        n = self.exp_table.rowCount()
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "", "Already processing."); return
        if not self.deps.get("ffmpeg"):
            QMessageBox.critical(self, "", "ffmpeg not found."); return
        slots = []; custom = 0; beyond = 0
        for r in range(n):
            si = self.exp_table.item(r, 1); fp = si.data(Qt.ItemDataRole.UserRole) if si else None
            if r >= 44:
                if fp: beyond += 1
                continue
            if fp and os.path.isfile(fp):
                def cell(c): it = self.exp_table.item(r, c); return (it.text().strip() if it else "")
                slots.append({"song": fp, "title": cell(2) or os.path.splitext(os.path.basename(fp))[0],
                              "artist": cell(3), "album": cell(4)}); custom += 1
            else:
                slots.append(None)
        if custom == 0:
            QMessageBox.warning(self, "", "Assign at least one song to one of the 44 slots."); return
        if beyond > 0:
            QMessageBox.information(self, "Portable ISO",
                f"A portable ISO supports the 44 original slots only (for now).\nThe {beyond} track(s) "
                "beyond slot 44 will be skipped — use BUILD HostFS for those.")
        clean, _ = QFileDialog.getOpenFileName(self, "Select the CLEAN Burnout 3 ISO (source)", "", "ISO (*.iso)")
        if not clean: return
        out, _ = QFileDialog.getSaveFileName(self, "Save portable ISO as...",
                                             os.path.expanduser("~/Burnout3_custom.iso"), "ISO (*.iso)")
        if not out: return
        if os.path.abspath(out) == os.path.abspath(clean):
            QMessageBox.critical(self, "", "Output must be different from the source ISO."); return
        self.btn_build_iso.setEnabled(False); self.btn_build_iso.setText("⏳  BUILDING ISO..."); self.exp_log.clear()
        self.worker_thread = QThread()
        self.iso_worker = PortableIsoWorker(clean, out, slots)
        self.iso_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.iso_worker.run)
        self.iso_worker.log_line.connect(self._st_log_line)
        self.iso_worker.finished.connect(self._st_iso_done)
        self.iso_worker.finished.connect(self.worker_thread.quit)
        self.iso_worker.finished.connect(lambda: setattr(self, "_prev_iso_worker", self.iso_worker))
        self.worker_thread.start()

    def _st_iso_done(self, ok, msg):
        self.btn_build_iso.setEnabled(True)
        self.btn_build_iso.setText("💿  BUILD PORTABLE ISO   —   full-length + unlimited names · no cheats · PCSX2/Android/PS2")
        if ok:
            QMessageBox.information(self, "Portable ISO built!", msg)
        else:
            QMessageBox.critical(self, "Error", msg)

    _INPLACE_LABEL = "📀  BUILD IN-PLACE ISO   —   same size · preserves CRC · scaled to fit (44 only)"

    def _st_build_inplace(self):
        """Classic in-place injection (same-size ISO, scaled-to-slot, original-length names) driven
        from the SOUNDTRACK slots. Reuses InjectionWorker."""
        n = self.exp_table.rowCount()
        if not self.iso_path or not os.path.isfile(self.iso_path):
            QMessageBox.critical(self, "", "Load a Burnout 3 ISO in the ISO + FILESYSTEM tab first."); return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self, "", "Already processing."); return
        if not self.deps.get("ffmpeg"):
            QMessageBox.critical(self, "", "ffmpeg not found."); return
        assignments = {}; metadata = {}
        for r in range(min(44, n)):
            si = self.exp_table.item(r, 1); fp = si.data(Qt.ItemDataRole.UserRole) if si else None
            if fp and os.path.isfile(fp):
                def cell(c): it = self.exp_table.item(r, c); return (it.text().strip() if it else "")
                assignments[r + 1] = fp
                t, a, al = cell(2), cell(3), cell(4)
                if t or a or al: metadata[r + 1] = (t, a, al)
        if not assignments:
            QMessageBox.warning(self, "", "Assign at least one song to one of the 44 slots."); return
        beyond = sum(1 for r in range(44, n)
                     if self.exp_table.item(r, 1) and self.exp_table.item(r, 1).data(Qt.ItemDataRole.UserRole))
        if beyond:
            QMessageBox.information(self, "In-place ISO",
                f"In-place mode replaces the 44 slots only; the {beyond} track(s) beyond 44 are skipped "
                "(use PORTABLE ISO or HostFS for those).")
        out, _ = QFileDialog.getSaveFileName(self, "Save ISO as...",
                                             os.path.splitext(self.iso_path)[0] + "_custom.iso", "ISO (*.iso)")
        if not out: return
        self.btn_build_inplace.setEnabled(False); self.btn_build_inplace.setText("⏳ BUILDING..."); self.exp_log.clear()
        self.worker_thread = QThread()
        self.worker = InjectionWorker(self.iso_path, assignments, out, metadata)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._st_inplace_progress)
        self.worker.log_line.connect(self._st_log_line)
        self.worker.finished.connect(self._st_inplace_done)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(lambda: setattr(self, "_prev_worker", self.worker))
        self.worker_thread.start()

    def _st_inplace_progress(self, v, m):
        self.btn_build_inplace.setText(f"⏳ {int(v*100)}%  {m[:42]}")

    def _st_inplace_done(self, ok, msg):
        self.btn_build_inplace.setEnabled(True); self.btn_build_inplace.setText(self._INPLACE_LABEL)
        if ok:
            QMessageBox.information(self, "ISO built!", f"{msg}\n\nLoad it in PCSX2.")
        else:
            QMessageBox.critical(self, "Error", msg)

    def _build_process_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24,24,24,24); lay.setSpacing(14)
        sp = QLabel("Conversion: Your audio → PS-ADPCM 32kHz Stereo (native PS2 format)\n"
                     "⚡ Optimized C encoder — 25 combos per block · multicore (all CPU cores)\n"
                     "🔊 Loudness matched to EA Trax (2-pass loudnorm ~-10 LUFS)\n"
                     "🎵 Proportional scaling when songs exceed available space")
        sp.setStyleSheet("color:#888;font-size:11px;padding:12px;background:rgba(255,140,0,0.05);border:1px solid #222;border-radius:8px")
        lay.addWidget(sp)

        # Output folder selector
        out_row = QHBoxLayout()
        self.lbl_output = QLabel("Output: same folder as source ISO")
        self.lbl_output.setStyleSheet("color:#888;font-size:11px")
        out_row.addWidget(self.lbl_output, 1)
        btn_out = QPushButton("📂 Choose output folder")
        btn_out.clicked.connect(self._choose_output)
        out_row.addWidget(btn_out)
        lay.addLayout(out_row)

        self.btn_inject = QPushButton("🔥  INJECT CUSTOM MUSIC")
        self.btn_inject.setObjectName("primaryBtn"); self.btn_inject.setMinimumHeight(48)
        self.btn_inject.clicked.connect(self._inject); self.btn_inject.setEnabled(False)
        lay.addWidget(self.btn_inject)
        self.pbar = QProgressBar(); self.pbar.setRange(0,1000); self.pbar.setValue(0); self.pbar.setFormat("")
        lay.addWidget(self.pbar)
        self.lbl_prog = QLabel(""); self.lbl_prog.setStyleSheet("color:#888;font-size:11px"); lay.addWidget(self.lbl_prog)
        l = QLabel("LOG"); l.setStyleSheet("color:#555;font-size:10px;letter-spacing:2px;margin-top:6px"); lay.addWidget(l)
        self.log = QTextEdit(); self.log.setReadOnly(True); lay.addWidget(self.log, 1)
        return w

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d:
            self.output_dir = d
            self.lbl_output.setText(f"Output: {d}")
            if self.iso_path:
                base = os.path.splitext(os.path.basename(self.iso_path))[0] + "_custom.iso"
                self.output_path = os.path.join(d, base)

    def _inject(self):
        if not self.iso_path: QMessageBox.warning(self,"","Select ISO first."); return
        if not self.assignments: QMessageBox.warning(self,"","Assign tracks first."); return
        if self.worker_thread and self.worker_thread.isRunning():
            QMessageBox.warning(self,"","Already processing."); return
        if not os.path.isfile(self.iso_path):
            QMessageBox.critical(self,"","Selected ISO no longer exists."); return
        out = self.output_path or os.path.splitext(self.iso_path)[0]+"_custom.iso"

        # Collect metadata from table for GLOBALUS.BIN patching
        metadata = {}  # slot_id -> (title, artist, album)
        for sid in self.assignments:
            row = sid - 1
            title = (self.table.item(row, 3).text() if self.table.item(row, 3) else "").strip()
            artist = (self.table.item(row, 4).text() if self.table.item(row, 4) else "").strip()
            album = (self.table.item(row, 5).text() if self.table.item(row, 5) else "").strip()
            if title or artist or album:
                metadata[sid] = (title, artist, album)

        self.btn_inject.setEnabled(False); self.btn_inject.setText("⏳ PROCESSING...")
        self.pbar.setValue(0); self.log.clear()
        self.worker_thread = QThread()
        self.worker = InjectionWorker(self.iso_path, dict(self.assignments), out, metadata)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.log_line.connect(self._on_log)
        self.worker.finished.connect(self._done)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(lambda: setattr(self, '_prev_worker', self.worker))
        self.worker_thread.start()

    def _on_progress(self, v, m):
        self.pbar.setValue(int(v*1000))
        self.pbar.setFormat(f"{int(v*100)}%")
        self.lbl_prog.setText(m)

    def _on_log(self, line):
        safe = html_mod.escape(line)
        c = ("#69f0ae" if line.startswith("✓") else
             "#ff5252" if line.startswith("✗") else
             "#ffaa00" if "▶" in line else
             "#4fc3f7" if "↳" in line else "#888")
        self.log.append(f'<span style="color:{c}">{safe}</span>')

    def _done(self, ok, msg):
        self.btn_inject.setEnabled(True); self.btn_inject.setText("🔥  INJECT CUSTOM MUSIC")
        if ok:
            self.pbar.setFormat("100% Complete!")
            QMessageBox.information(self,"Success!",f"{msg}\n\nLoad the ISO in PCSX2.")
        else:
            self.pbar.setFormat("Error"); self.pbar.setValue(0)
            QMessageBox.critical(self,"Error",msg)

    def _build_info_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24,24,24,24)
        i = QTextEdit(); i.setReadOnly(True)
        i.setHtml("""<div style="font-family:monospace;color:#ccc;line-height:1.8">
        <h2 style="color:#ff4500">📖 Guide — v11.2</h2>
        <h3 style="color:#ff8c00">How to Use</h3>
        <p style="color:#aaa">1. Drag your Burnout 3 ISO (NTSC-U) to the ISO tab<br>
        2. Go to SOUNDTRACK — the 44 originals are pre-loaded. Assign songs to slots<br>
        &nbsp;&nbsp;&nbsp;(or add new ones). Title/Artist/Album auto-fill + romanize.<br>
        3. Pick a build:<br>
        &nbsp;&nbsp;💿 <b>PORTABLE ISO</b> — 44 full-length + unlimited names, no cheats (Android/PS2/PCSX2)<br>
        &nbsp;&nbsp;📀 <b>IN-PLACE ISO</b> — same-size ISO, scaled to fit, preserves CRC<br>
        &nbsp;&nbsp;🛠 <b>HostFS</b> — add N tracks beyond 44 (needs PCSX2 cheats)<br>
        4. Load the resulting ISO in PCSX2 (or the HostFS folder)<br><br>
        Supported formats: MP3, M4A, FLAC, OGG, WAV, OPUS, WMA, AAC</p>
        <h3 style="color:#ff8c00">Song Names</h3>
        <p style="color:#aaa">
        Custom song names are patched into DATA/GLOBALUS.BIN (UTF-16).<br>
        The Title, Artist, and Album columns in the track table are<br>
        written to the in-game EA Trax display.<br>
        <b style="color:#ffaa00">Note:</b> Names longer than the original are truncated to fit.</p>
        <h3 style="color:#ff8c00">Audio</h3>
        <p style="color:#aaa">
        Codec: <b style="color:#4fc3f7">PS-ADPCM 4-bit</b> (PlayStation 2)<br>
        Sample rate: <b>32000 Hz</b> · Channels: <b>Stereo</b><br>
        Layout: <b>LLRR</b> in 8192-byte super-blocks<br>
        &nbsp;&nbsp;L[2048] L[2048] R[2048] R[2048]<br>
        Nibbles: first sample = LOW, second = HIGH<br>
        Encoder: <b style="color:#69f0ae">Optimized C</b> — 25 combos/block<br>
        Pre-filter: lowpass 15.5kHz · soxr 28-bit resampler<br>
        Loudness: <b style="color:#4fc3f7">2-pass loudnorm ~-10 LUFS</b> (matches EA Trax)<br>
        Compression: 3.5:1 (56 bytes PCM → 16 bytes ADPCM)</p>
        <h3 style="color:#ff8c00">Space &amp; Scaling</h3>
        <p style="color:#aaa">
        EATRAX0 (slots 1-22): <b>149 MB</b> fixed<br>
        EATRAX1 (slots 23-44): <b>150 MB</b> fixed<br>
        When songs exceed available space, all are scaled proportionally.<br>
        Fewer songs = more space per song = less scaling needed.<br>
        With 44 songs of ~5 min each: ~74% of each song fits (~3.5 min).<br>
        With 15 songs: most fit completely without scaling.</p>
        <h3 style="color:#ff8c00">ISO Structure</h3>
        <p style="color:#aaa"><code style="color:#69f0ae">
        SLUS_210.50 → Executable<br>
        DATA/GLOBALUS.BIN → Song names (UTF-16)<br>
        <b>TRACKS/_EATRAX0.RWS → Music 1-22</b><br>
        <b>TRACKS/_EATRAX1.RWS → Music 23-44</b><br>
        TRACKS/[maps]/ → Track data<br>
        SOUND/ → SFX .RWS</code></p>
        <h3 style="color:#ff8c00">Dependencies</h3>
        <p style="color:#aaa"><code style="color:#69f0ae">
        <b>Arch:</b> sudo pacman -S ffmpeg gcc python-pyside6<br>
        <b>Ubuntu:</b> sudo apt install ffmpeg gcc<br>
        &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;pip install PySide6<br>
        <b>Windows:</b> Install Python, ffmpeg, MinGW (gcc)</code></p>
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