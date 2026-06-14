#!/usr/bin/env python3
"""Build a PORTABLE Burnout 3 ISO with custom music baked in (no cheats, no HostFS).

Burnout 3 reads its loose disc files by FIXED LBA — re-authoring the whole ISO
(xorriso/genisoimage) moves every file and black-screens. EXCEPT: the EA-TRAX RWS
files are opened BY PATH (proven in PCSX2 — relocating _EATRAX0 to the disc end and
zeroing the old copy still plays tracks 1-22). So the trick is:

  keep EVERY original file byte-identical at its original LBA, and surgically
  relocate ONLY the (enlarged) EATRAX files to the end of the disc, patching just
  their ISO9660 directory records (extent LBA + size, LE & BE) and the PVD size.

Result: full-length custom tracks in a self-contained ISO that boots anywhere
(PCSX2, Android AetherSX2/NetherSX2, real PS2) with ZERO cheats.
"""
import os, sys, struct, importlib.util, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))

def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); sys.modules[name] = m; s.loader.exec_module(m)
    return m

def find_record(buf, path):
    """Return (record_offset, extent_lba, size) of an ISO9660 path like /TRACKS/_EATRAX0.RWS."""
    parts = [p for p in path.strip("/").split("/")]
    pvd = 16 * 2048; rec = pvd + 156
    lba = struct.unpack_from("<I", buf, rec + 2)[0]; size = struct.unpack_from("<I", buf, rec + 10)[0]
    off_rec = None
    for name in parts:
        target = name.upper(); base = lba * 2048; end = base + size; off = base; found = None
        while off < end:
            rl = buf[off]
            if rl == 0:                                   # padding -> next sector
                off = ((off // 2048) + 1) * 2048; continue
            idlen = buf[off + 32]
            ident = buf[off + 33:off + 33 + idlen].decode("ascii", "replace")
            if ident.split(";")[0].upper() == target:
                found = off; break
            off += rl
        if found is None:
            raise RuntimeError("path not found: " + name)
        off_rec = found
        lba = struct.unpack_from("<I", buf, found + 2)[0]; size = struct.unpack_from("<I", buf, found + 10)[0]
    return off_rec, lba, size

def relocate(buf, rec_off, new_data, log=print):
    """Zero the file's old extent, append new_data at disc end, patch record (LBA+size, LE&BE) + PVD."""
    old_lba = struct.unpack_from("<I", buf, rec_off + 2)[0]
    old_sz = struct.unpack_from("<I", buf, rec_off + 10)[0]
    o = old_lba * 2048
    buf[o:o + old_sz] = b"\x00" * old_sz                  # orphan the old copy
    if len(buf) % 2048:
        buf += b"\x00" * (2048 - len(buf) % 2048)
    new_lba = len(buf) // 2048
    buf += new_data
    if len(buf) % 2048:
        buf += b"\x00" * (2048 - len(buf) % 2048)
    struct.pack_into("<I", buf, rec_off + 2, new_lba);  struct.pack_into(">I", buf, rec_off + 6, new_lba)
    struct.pack_into("<I", buf, rec_off + 10, len(new_data)); struct.pack_into(">I", buf, rec_off + 14, len(new_data))
    pvd = 16 * 2048; tot = len(buf) // 2048
    struct.pack_into("<I", buf, pvd + 80, tot); struct.pack_into(">I", buf, pvd + 84, tot)
    log(f"  relocated LBA {old_lba}->{new_lba}, size {old_sz}->{len(new_data)} ; volume now {tot} sectors")
    return new_lba

TRACKS_PER_FILE = 22
META_FO = 0x100 + (0x004A5600 - 0x00100000)   # file offset of the 24-byte metadata array inside SLUS
META_NEW_VA = 0x00485894   # 6996-byte zero-run in the loaded ELF (~291 entries) -> relocate the array here
                           # for +tracks WITHOUT Nahelam's code cave (= no [ELF Code Cave] cheat needed)

def append_data(buf, data):
    """Append data at the disc end (sector-aligned), bump PVD volume size, return its LBA."""
    if len(buf) % 2048: buf += b"\x00" * (2048 - len(buf) % 2048)
    lba = len(buf) // 2048
    buf += data
    if len(buf) % 2048: buf += b"\x00" * (2048 - len(buf) % 2048)
    pvd = 16 * 2048; tot = len(buf) // 2048
    struct.pack_into("<I", buf, pvd + 80, tot); struct.pack_into(">I", buf, pvd + 84, tot)
    return lba

def add_dir_record(buf, dir_path, fname_ver, file_lba, file_size, log=print):
    """Insert a NEW file's ISO9660 directory record in SORTED position (the game's lookup needs
    records ordered by identifier) and re-emit the extent respecting sector boundaries. In-place
    (no extent growth) — fits while the result stays within the directory's allocated sectors."""
    drec, dlba, dsize = find_record(buf, dir_path)
    base = dlba * 2048
    alloc = ((dsize + 2047) // 2048) * 2048
    # read existing records in order
    recs = []; off = base; end = base + dsize
    while off < end:
        rl = buf[off]
        if rl == 0: off = ((off // 2048) + 1) * 2048; continue
        recs.append(bytes(buf[off:off + rl])); off += rl
    # build the new record
    name = fname_ver.encode("ascii")
    rl = 33 + len(name)
    if rl % 2: rl += 1
    rec = bytearray(rl); rec[0] = rl
    struct.pack_into("<I", rec, 2, file_lba); struct.pack_into(">I", rec, 6, file_lba)
    struct.pack_into("<I", rec, 10, file_size); struct.pack_into(">I", rec, 14, file_size)
    rec[18:25] = buf[drec + 18:drec + 25]
    rec[25] = 0
    struct.pack_into("<H", rec, 28, 1); struct.pack_into(">H", rec, 30, 1)
    rec[32] = len(name); rec[33:33 + len(name)] = name
    new_rec = bytes(rec)
    # keep '.' and '..' first; insert the new record among the (already sorted) others by identifier
    dots, others = recs[:2], recs[2:]
    newkey = new_rec[33:33 + new_rec[32]]
    ins = len(others)
    for i, r in enumerate(others):
        if r[33:33 + r[32]] > newkey: ins = i; break
    others.insert(ins, new_rec)
    ordered = dots + others
    # re-emit with sector-boundary padding (a record may not span a 2048 boundary)
    out = bytearray()
    for r in ordered:
        if (len(out) % 2048) + len(r) > 2048:
            out += b"\x00" * (2048 - len(out) % 2048)
        out += r
    newsize = len(out)
    if newsize > alloc:
        raise RuntimeError(f"{dir_path}: needs {newsize} > allocated {alloc}; directory growth not implemented")
    buf[base:base + alloc] = bytes(out) + b"\x00" * (alloc - newsize)
    struct.pack_into("<I", buf, drec + 10, newsize); struct.pack_into(">I", buf, drec + 14, newsize)
    struct.pack_into("<I", buf, base + 10, newsize); struct.pack_into(">I", buf, base + 14, newsize)
    log(f"  + /{dir_path.strip('/')}/{fname_ver} @LBA{file_lba} ({file_size}B), sorted pos {ins+2}/{len(ordered)}; dir {dsize}->{newsize}")

def build_portable_iso(clean_iso, out_iso, slots, log=print, progress=None):
    """Bake a portable Burnout 3 ISO (no cheats) from up to 44 slots.

    slots[g] = None (keep original game track) or {'song','title','artist','album'} (custom,
    full-length). Custom AUDIO -> rebuild+relocate the enlarged _EATRAXf.RWS; custom NAMES ->
    relocate an enlarged GLOBALUS.BIN + repoint that track's metadata in SLUS (in-place).
    Everything else stays byte-identical at its original LBA, so the disc still boots."""
    b3 = _load("burnout3_gui", os.path.join(HERE, "..", "burnout3_gui.py"))
    ee = _load("eatrax_expansion", os.path.join(HERE, "..", "eatrax_expansion.py"))
    slots = list(slots)
    N = len(slots)
    custom = [g for g, s in enumerate(slots) if s and s.get("song")]
    if not custom:
        raise RuntimeError("Assign at least one song (every slot is still the original)")
    has_exp = max(custom) >= 44                          # any track beyond the original 44 -> expansion mode
    log(f"reading clean ISO ({os.path.getsize(clean_iso)} bytes)... {N} slots, {len(custom)} custom"
        + (" (EXPANSION: +tracks)" if has_exp else ""))
    if progress: progress("Reading ISO...")
    buf = bytearray(open(clean_iso, "rb").read())

    # 1) AUDIO — group custom songs per _EATRAXf
    files = {}
    for g in custom:
        files.setdefault(g // TRACKS_PER_FILE, {})[g % TRACKS_PER_FILE] = slots[g]["song"]
    tmp = tempfile.mkdtemp(prefix="piso_")
    try:
        for f in sorted(files):                          # existing files 0/1: rebuild full-length + relocate
            if f >= 2: continue
            if progress: progress(f"Encoding _EATRAX{f}.RWS...")
            rec, lba, sz = find_record(buf, f"/TRACKS/_EATRAX{f}.RWS")
            base = bytes(buf[lba * 2048:lba * 2048 + sz])
            log(f"_EATRAX{f}.RWS: base {sz} B, replacing locals {sorted(files[f])}")
            relocate(buf, rec, ee._build_eatrax_file(b3, base, files[f], tmp, log), log)
        for f in sorted(files):                          # new files >=2: build from _EATRAX1 template + add record
            if f < 2: continue
            if progress: progress(f"Encoding _EATRAX{f}.RWS (new)...")
            _, l1, s1 = find_record(buf, "/TRACKS/_EATRAX1.RWS")
            base1 = bytes(buf[l1 * 2048:l1 * 2048 + s1])
            new = ee._build_eatrax_file(b3, base1, files[f], tmp, log)
            lba = append_data(buf, new)
            add_dir_record(buf, "/TRACKS", f"_EATRAX{f}.RWS;1", lba, len(new), log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) NAMES — enlarged globalus (3 romanized strings per custom track)
    if progress: progress("Rebuilding names (GLOBALUS)...")
    grec, glba, gsz = find_record(buf, "/DATA/GLOBALUS.BIN")
    gtmp = tempfile.mktemp(prefix="glob_", suffix=".bin")
    open(gtmp, "wb").write(bytes(buf[glba * 2048:glba * 2048 + gsz]))
    if os.path.exists(gtmp + ".orig"): os.remove(gtmp + ".orig")
    strings = []
    for g in custom:
        s = slots[g]
        strings += [ee.romanize(s.get("title", "")), ee.romanize(s.get("album", "")), ee.romanize(s.get("artist", ""))]
    base_id = ee._rebuild_globalus(gtmp, strings, log)
    new_glob = open(gtmp, "rb").read(); os.remove(gtmp)
    if os.path.exists(gtmp + ".orig"): os.remove(gtmp + ".orig")
    relocate(buf, grec, new_glob, log)

    # 3) METADATA in SLUS (in-place; ELF stays at its original LBA)
    srec, slba, ssz = find_record(buf, "/SLUS_210.50")
    eoff = slba * 2048
    if not has_exp:
        # simple: repoint the existing 0..43 entries to the new name ids (no count/hook change, no cheats)
        for ci, g in enumerate(custom):
            b = base_id + ci * 3; ent = eoff + META_FO + g * 24
            struct.pack_into("<I", buf, ent + 8, b); struct.pack_into("<I", buf, ent + 12, b + 1)
            struct.pack_into("<I", buf, ent + 16, b + 2)
        log(f"  repointed {len(custom)} name(s) in place")
    else:
        # expansion: bake digit hook + count + digit strings + relocate the metadata array to the
        # free ELF zero-run (META_NEW_VA) -> NO code cave, NO cheats
        for vbase in ee.HOOK_VAS:
            for k, wv in enumerate(ee.HOOK):
                struct.pack_into("<I", buf, eoff + ee._fo(vbase + k * 4), wv)
        buf[eoff + ee._fo(ee.DIGITS_VA):eoff + ee._fo(ee.DIGITS_VA) + len(ee.DIGITS)] = ee.DIGITS
        struct.pack_into("<I", buf, eoff + ee._fo(ee.COUNT_VA), N)
        struct.pack_into("<I", buf, eoff + ee._fo(ee.BASEPTR_VA), META_NEW_VA)
        orig = [list(struct.unpack_from("<IIIIII", buf, eoff + ee._fo(ee.META_VA + i * 24))) for i in range(44)]
        ci = 0
        for g in range(N):
            ent = eoff + ee._fo(META_NEW_VA) + g * 24
            if slots[g] and slots[g].get("song"):
                b = base_id + ci * 3; ci += 1
                struct.pack_into("<IIIIII", buf, ent, g, 0, b, b + 1, b + 2, 0x0F)
            else:
                e = orig[g]; struct.pack_into("<IIIIII", buf, ent, g, 0, e[2], e[3], e[4], 0x0F)
        log(f"  baked hook + count={N} + relocated metadata array -> VA 0x{META_NEW_VA:X} (no cheats)")

    if progress: progress("Writing ISO...")
    open(out_iso, "wb").write(buf)
    log(f"wrote {out_iso} ({len(buf)} bytes, {N} tracks, {len(custom)} custom)")
    return {"out": out_iso, "custom": len(custom), "files": sorted(files), "size": len(buf), "count": N, "expansion": has_exp}

if __name__ == "__main__":
    # CLI test: clean.iso out.iso  slot:song.flac[:Title:Artist:Album] ...
    clean, out = sys.argv[1], sys.argv[2]
    slots = [None] * 44
    for spec in sys.argv[3:]:
        parts = spec.split(":")
        idx = int(parts[0]); song = parts[1]
        ti = parts[2] if len(parts) > 2 else os.path.splitext(os.path.basename(song))[0]
        ar = parts[3] if len(parts) > 3 else ""
        al = parts[4] if len(parts) > 4 else ""
        slots[idx] = {"song": song, "title": ti, "artist": ar, "album": al}
    build_portable_iso(clean, out, slots)
