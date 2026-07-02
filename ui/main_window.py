"""The main application window: ISO tab, SOUNDTRACK tab (the portable-ISO builder)
and the GUIDE tab. Wires the drag-and-drop widgets and the background worker together."""
import os, shutil, html as html_mod

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QTextEdit,
    QTableWidgetItem, QHeaderView, QMessageBox,
    QTabWidget, QGroupBox, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QSplitter, QCheckBox
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QColor, QIcon

from core.constants import ISO_STRUCTURE, EA_TRAX_SONGS, AUDIO_EXTENSIONS
from core.audio import probe_metadata
from ui.resources import _resource_path
from ui.widgets import ISODropZone, TrackTable
from ui.workers import PortableIsoWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Burnout 3: Takedown — Custom Music Injector v11.2")
        self.setWindowIcon(QIcon(_resource_path("bnmex.ico")))
        self.setMinimumSize(1050, 750)
        self.resize(1150, 850)
        self.iso_path = None
        self.output_path = None
        self.worker_thread = None
        self.deps = self._check_deps()
        self._build_ui()

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
        self.tabs.setCurrentIndex(1)

    # ─── SOUNDTRACK tab — full soundtrack: replace any of 44 + add up to 176, then build a portable ISO ──
    def _build_soundtrack_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(16,16,16,16); lay.setSpacing(10)
        note = QLabel("The 44 originals are pre-loaded — assign a song to a slot to replace it, or add new "
                      "ones below (up to 176 total); untouched slots keep the original track. Names "
                      "auto-romanize from any language. Then BUILD PORTABLE ISO — one self-contained disc, "
                      "no cheats, nothing to download, that boots in PCSX2, Android (AetherSX2/NetherSX2) "
                      "and real PS2. Everything is baked into the ISO.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888;font-size:11px;padding:10px;background:rgba(255,140,0,0.05);border:1px solid #222;border-radius:8px")
        lay.addWidget(note)

        tb = QHBoxLayout()
        bl = QPushButton("📁 Add folder"); bl.clicked.connect(self._st_add_folders); tb.addWidget(bl)
        ba = QPushButton("➕ Add songs"); ba.clicked.connect(self._st_add_songs); tb.addWidget(ba)
        br = QPushButton("➖ Remove / reset selected"); br.setObjectName("dangerBtn"); br.clicked.connect(self._st_remove_selected); tb.addWidget(br)
        bz = QPushButton("↺ Reset all"); bz.setObjectName("dangerBtn"); bz.clicked.connect(self._st_reset_all); tb.addWidget(bz)
        self.chk_replace = QCheckBox("Replace originals"); self.chk_replace.setChecked(True)
        self.chk_replace.setToolTip("ON: your songs fill the 44 slots from #1 (EA Trax originals get replaced).\n"
                                    "OFF: keep all 44 originals and add your songs as EXTRA tracks (45, 46, …).")
        tb.addWidget(self.chk_replace)
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

        self.btn_build_iso = QPushButton("💿  BUILD PORTABLE ISO   —   up to 176 full-length tracks · no cheats · PCSX2 / Android / PS2")
        self.btn_build_iso.setObjectName("primaryBtn"); self.btn_build_iso.setMinimumHeight(46)
        self.btn_build_iso.clicked.connect(self._st_build_portable)
        lay.addWidget(self.btn_build_iso)
        self.exp_log = QTextEdit(); self.exp_log.setReadOnly(True); self.exp_log.setMaximumHeight(120); lay.addWidget(self.exp_log)
        self._st_reset_all()
        return w

    def _st_romanizer(self):
        try:
            from core import eatrax; return eatrax.romanize
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

    def _st_folder_audio(self, d):
        """All audio files in a folder (sorted), recursing into subfolders."""
        out = []
        for root, _dirs, files in os.walk(d):
            out += [os.path.join(root, f) for f in sorted(files)
                    if os.path.splitext(f)[1].lower() in AUDIO_EXTENSIONS]
        return out

    def _st_add_folders(self):
        """Add ONE folder's audio (recursing). For several folders at once, drag them onto the table
        (Qt's directory dialog can't reliably multi-select)."""
        d = QFileDialog.getExistingDirectory(self, "Add a folder of songs  (tip: drag several folders onto the list)")
        if not d:
            return
        files = self._st_folder_audio(d)
        if not files:
            QMessageBox.warning(self, "No audio", "No audio files found in that folder."); return
        self._st_add_songs_paths(files)

    def _st_add_songs(self):
        exts = " *.".join(e.strip(".") for e in AUDIO_EXTENSIONS)
        fs, _ = QFileDialog.getOpenFileNames(self, "Add songs (append as new tracks)", "", f"Audio (*.{exts})")
        if fs: self._st_add_songs_paths(sorted(fs))

    def _st_first_default_slot(self):
        """First of the 44 slots still holding the original game track (not yet replaced), or None."""
        for r in range(min(len(EA_TRAX_SONGS), self.exp_table.rowCount())):
            it = self.exp_table.item(r, 1)
            if it and it.data(Qt.ItemDataRole.UserRole) is None:
                return r
        return None

    def _st_add_songs_paths(self, files):
        # "Replace originals" ON  -> fill the 44 default slots from #1, then extend past 44.
        # "Replace originals" OFF -> keep all 44 originals, add everything as extra tracks (45+).
        replace = getattr(self, "chk_replace", None) is None or self.chk_replace.isChecked()
        for fp in files:
            slot = self._st_first_default_slot() if replace else None
            if slot is not None:
                self._st_set_custom(slot, fp)
            else:
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
        msg = f"{n} tracks · {custom} custom · {n - custom} original"
        # Hard ceiling = 176 (8 _eatrax files x 22): beyond it the digit table would clobber the ".rws"
        # string at 0x4CEA88. 45..66 is proven; 67..176 also routes fine but needs the audio-cap raise
        # (RE-derived CAP_VAS patches) — works but flagged experimental until you boot-test your count.
        HARD_MAX = 176
        over_max = n > HARD_MAX
        if over_max:
            msg += f"  ⛔ {n} > {HARD_MAX} — past the file-routing limit (remove {n-HARD_MAX} to build)"
            self.lbl_expcount.setStyleSheet("color:#ff4444;font-weight:bold")
        else:
            self.lbl_expcount.setStyleSheet("color:#ff8c00;font-weight:bold")
        self.lbl_expcount.setText(msg)
        # The portable ISO handles the FULL range: ≤44 cheatless, 45..176 bakes the expansion into the ELF.
        if hasattr(self, "btn_build_iso"):
            self.btn_build_iso.setEnabled(not over_max)
            self.btn_build_iso.setToolTip(
                f"Disabled: {n} > {HARD_MAX} tracks (8 _eatrax files x 22). Remove some." if over_max else "")

    def _st_log_line(self, s):
        c = "#69f0ae" if s.startswith("✓") else "#ff5252" if s.startswith("✗") else "#aaa"
        self.exp_log.append(f'<span style="color:{c}">{html_mod.escape(s)}</span>')

    def _st_build_portable(self):
        n = self.exp_table.rowCount()
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
                              "artist": cell(3), "album": cell(4)}); custom += 1
            else:
                slots.append(None)
        if custom == 0:
            QMessageBox.warning(self, "", "Assign at least one song."); return
        for g, s in enumerate(slots):                    # the >44 path can't leave gaps past the originals
            if s is None and g >= 44:
                QMessageBox.critical(self, "", f"Slot {g+1} is empty — slots beyond 44 must have a song."); return
        # >44 bakes the full expansion (digit hook + relocated metadata + the bundled code-cave) into the
        # ELF, CRC-neutralised so graphics stay correct. The code-cave is shipped with the tool — no download.
        if len(slots) > 44:
            if QMessageBox.question(self, "Portable ISO (+tracks)",
                    f"Bake {len(slots)} tracks into a self-contained ISO (no cheats, nothing to "
                    "download)?\n\nIt boots in PCSX2 / Android (AetherSX2/NetherSX2) / real PS2 — "
                    "everything is baked into the disc."
                    ) != QMessageBox.StandardButton.Yes:
                return
        # Reuse the ISO already loaded in the ISO tab; only ask if none is loaded.
        clean = self.iso_path if (self.iso_path and os.path.isfile(self.iso_path)) else None
        if not clean:
            clean, _ = QFileDialog.getOpenFileName(self, "Select the CLEAN Burnout 3 ISO (source)", "", "ISO (*.iso)")
            if not clean: return
        default_out = (os.path.splitext(self.iso_path)[0] + "_custom.iso") if self.iso_path \
            else os.path.expanduser("~/Burnout3_custom.iso")
        out, _ = QFileDialog.getSaveFileName(self, "Save portable ISO as...", default_out, "ISO (*.iso)")
        if not out: return
        if os.path.abspath(out) == os.path.abspath(clean):
            QMessageBox.critical(self, "", "Output must be different from the source ISO."); return
        self.btn_build_iso.setEnabled(False); self.btn_build_iso.setText("⏳  BUILDING ISO..."); self.exp_log.clear()
        self.worker_thread = QThread()
        self.iso_worker = PortableIsoWorker(clean, out, slots)  # cave_pnach=None -> use the bundled elf_code_cave.pnach
        self.iso_worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.iso_worker.run)
        self.iso_worker.log_line.connect(self._st_log_line)
        self.iso_worker.finished.connect(self._st_iso_done)
        self.iso_worker.finished.connect(self.worker_thread.quit)
        self.iso_worker.finished.connect(lambda: setattr(self, "_prev_iso_worker", self.iso_worker))
        self.worker_thread.start()

    def _st_iso_done(self, ok, msg):
        self.btn_build_iso.setEnabled(True)
        self.btn_build_iso.setText("💿  BUILD PORTABLE ISO   —   up to 176 full-length tracks · no cheats · PCSX2 / Android / PS2")
        if ok:
            QMessageBox.information(self, "Portable ISO built!", msg)
        else:
            QMessageBox.critical(self, "Error", msg)

    def _build_info_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(24,24,24,24)
        i = QTextEdit(); i.setReadOnly(True)
        i.setHtml("""<div style="font-family:monospace;color:#ccc;line-height:1.8">
        <h2 style="color:#ff4500">📖 Guide — v12.2</h2>
        <h3 style="color:#ff8c00">How to Use</h3>
        <p style="color:#aaa">1. Drag your Burnout 3 ISO (NTSC-U or PAL: SLUS-21050 / SLES-52585 / SLES-52584) to the ISO tab — region auto-detected<br>
        2. Go to SOUNDTRACK — the 44 originals are pre-loaded. Replace any slot, or add new<br>
        &nbsp;&nbsp;&nbsp;ones (up to 176 total). Title/Artist/Album auto-fill + romanize from any language.<br>
        3. Click 💿 <b>BUILD PORTABLE ISO</b> — one self-contained disc, no cheats,<br>
        &nbsp;&nbsp;&nbsp;nothing to download:<br>
        &nbsp;&nbsp;•&nbsp;≤44 tracks → ELF untouched, game CRC preserved<br>
        &nbsp;&nbsp;•&nbsp;45–176 tracks → bakes the EA-TRAX expansion + the bundled code-cave into the ELF,<br>
        &nbsp;&nbsp;&nbsp;&nbsp;CRC-neutralised so graphics stay correct<br>
        4. Load the ISO in PCSX2 / AetherSX2 / NetherSX2 / real PS2 — everything is baked in.<br><br>
        Supported formats: MP3, M4A, FLAC, OGG, WAV, OPUS, WMA, AAC</p>
        <h3 style="color:#ff8c00">Song Names</h3>
        <p style="color:#aaa">
        Names go into DATA/GLOBALUS.BIN (UTF-16) and show in the in-game EA Trax list.<br>
        Any script (Japanese, Korean, Cyrillic, Greek, …) is auto-romanized to the<br>
        Latin font the game uses. Full names are kept — very long titles just wrap.</p>
        <h3 style="color:#ff8c00">Audio</h3>
        <p style="color:#aaa">
        Codec: <b style="color:#4fc3f7">PS-ADPCM 4-bit</b> (PlayStation 2)<br>
        Sample rate: <b>32000 Hz</b> · Channels: <b>Stereo</b><br>
        Layout: <b>LLRR</b> in 8192-byte super-blocks<br>
        &nbsp;&nbsp;L[2048] L[2048] R[2048] R[2048]<br>
        Nibbles: first sample = LOW, second = HIGH<br>
        Encoder: <b style="color:#69f0ae">Optimized C</b> — 65 combos/block (full search)<br>
        Pre-filter: lowpass 15.5kHz · soxr 28-bit resampler<br>
        Loudness: <b style="color:#4fc3f7">2-pass loudnorm ~-10 LUFS</b> (matches EA Trax)<br>
        Compression: 3.5:1 (56 bytes PCM → 16 bytes ADPCM)</p>
        <h3 style="color:#ff8c00">Tracks &amp; Space</h3>
        <p style="color:#aaa">
        Each <b>_EATRAXn.RWS</b> holds 22 <b>full-length</b> tracks. The portable build relocates them to the<br>
        disc end (no fixed-size cap, no scaling) and adds files as needed — the ISO just grows.<br>
        Hard limit: <b>176 tracks</b> (8 files × 22) — the game's filename routing tops out there.</p>
        <h3 style="color:#ff8c00">ISO Structure</h3>
        <p style="color:#aaa"><code style="color:#69f0ae">
        SLUS_210.50 / SLES_525.85 → Executable (game CRC preserved)<br>
        DATA/GLOBALUS.BIN → Song names (UTF-16)<br>
        <b>TRACKS/_EATRAX0..7.RWS → Music (22 tracks each)</b><br>
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
