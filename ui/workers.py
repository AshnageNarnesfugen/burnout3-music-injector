"""Background QObject worker for the portable-ISO build.

The heavy lifting lives in core/ (the encoder, the audio pipeline and the portable-ISO
builder); this worker just runs it off the GUI thread and streams progress/log lines
back via Qt signals."""
from PySide6.QtCore import Signal, QObject

from core import portable_iso


# ─── Portable ISO Worker — bake the whole soundtrack into a self-contained disc ──
class PortableIsoWorker(QObject):
    """Bake a self-contained ISO: ≤44 renames via globalus only; 45..176 bakes the EA-TRAX
    expansion (cave + hook + count + metadata + construct patch) into the ELF, CRC-neutralised."""
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, clean_iso, out_iso, slots, cave_pnach=None):
        super().__init__()
        self.clean_iso = clean_iso; self.out_iso = out_iso; self.slots = slots; self.cave_pnach = cave_pnach

    def run(self):
        try:
            res = portable_iso.build_portable_iso(self.clean_iso, self.out_iso, self.slots,
                                                  log=self.log_line.emit, progress=self.log_line.emit,
                                                  cave_pnach=self.cave_pnach)
            mb = res["size"] // (1024 * 1024)
            files = ", ".join(f"_eatrax{f}.rws" for f in res["files"])
            msg = (f"Portable ISO built — {res['count']} tracks ({res['custom']} custom, {mb} MB).\n"
                   f"{self.out_iso}\n\n"
                   "Self-contained — boots in PCSX2, Android (AetherSX2/NetherSX2) and real PS2: "
                   "just load this ISO. Everything is baked into the disc.")
            self.log_line.emit("✓ Done.")
            self.finished.emit(True, msg)
        except Exception as e:
            import traceback
            self.finished.emit(False, f"{e}\n{traceback.format_exc()[-600:]}")
