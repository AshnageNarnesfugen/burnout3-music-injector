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
META_NEW_VA = 0x00485894   # free ELF zero-run — DON'T use for the metadata: it's the game's runtime data
                           # (zero at load, clobbered during play). Kept only as a CRC-comp scratch idea.
CAVE = 0x0016B4F0          # Nahelam code cave; freed by baking the [ELF Code Cave] patches -> metadata lives here
# The EATRAX construct @0x3FCD20 copies the global baseptr [0x4A5A6C] into obj[0xB4] (the base used for
# indexing entries). The game RESETS that global from ~28 sites at runtime, reverting any baked value, so we
# patch the construct itself to force obj[0xB4]=CAVE (instead of reading the reverted global):
CONSTRUCT_LUI_VA = 0x003FCDC8   # was: lui $v0,0x4A   -> lui $v0,(CAVE>>16)
CONSTRUCT_ORI_VA = 0x003FCDD0   # was: lw $a1,0x5A6C($v0) -> ori $a1,$v0,(CAVE&0xFFFF)  => obj[0xB4]=CAVE

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

def build_portable_iso(clean_iso, out_iso, slots, log=print, progress=None, cave_pnach=None):
    """Bake a portable Burnout 3 ISO (no cheats, no HostFS) — up to 176 tracks.

    slots[g] = None (keep original game track) or {'song','title','artist','album'} (custom, full-length).
    <=44: rename in place via globalus only (ELF untouched, CRC preserved).
    >44 : bake the whole EA-TRAX expansion into the ELF (cave + hook + count + metadata + construct patch)
          and XOR-compensate so the game CRC stays 0xBEBF8793. Needs cave_pnach (the [ELF Code Cave] pnach).
    Everything else stays byte-identical at its original LBA, so the disc still boots."""
    b3 = _load("burnout3_gui", os.path.join(HERE, "..", "burnout3_gui.py"))
    ee = _load("eatrax_expansion", os.path.join(HERE, "..", "eatrax_expansion.py"))
    if cave_pnach is None:
        cave_pnach = os.path.join(HERE, "elf_code_cave.pnach")    # bundled with the tool (no separate download)
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

    # 2+3) NAMES + METADATA
    srec, slba, ssz = find_record(buf, "/SLUS_210.50")
    eoff = slba * 2048
    grec, glba, gsz = find_record(buf, "/DATA/GLOBALUS.BIN")
    orig_glob = bytes(buf[glba * 2048:glba * 2048 + gsz])
    if progress: progress("Rebuilding names (GLOBALUS)...")
    if not has_exp:
        # Rename WITHOUT touching the ELF: overwrite each custom track's ORIGINAL globalus string ids
        # in place (the unmodified ELF metadata keeps pointing at them). PCSX2 computes the game CRC by
        # XOR-ing every ELF word, so baking new ids into the ELF would change the CRC and PCSX2 would drop
        # its Burnout-3 graphics fixes/CRC-hacks (black sky / over-bloom). Keeping the ELF byte-identical
        # preserves CRC BEBF8793 -> the in-game visuals stay correct.
        overrides = {}
        for g in custom:
            tid, aid, rid = struct.unpack_from("<III", buf, eoff + META_FO + g * 24 + 8)  # title, album, artist ids
            s = slots[g]
            overrides[tid] = ee.romanize(s.get("title", ""))
            overrides[aid] = ee.romanize(s.get("album", ""))
            overrides[rid] = ee.romanize(s.get("artist", ""))
        relocate(buf, grec, ee.globalus_overwrite(orig_glob, overrides, log), log)
        log(f"  renamed {len(custom)} track(s) via globalus only — ELF untouched, CRC preserved")
    else:
        # >44, NO cheats: bake the whole EA-TRAX expansion into the ISO's ELF. The metadata must live where
        # the game won't clobber it, and the construct must be forced to use it (the game resets the baseptr
        # global at runtime). Recipe (all baked, then CRC-neutralised so PCSX2 keeps the BEBF8793 graphics fixes).
        if not (cave_pnach and os.path.isfile(cave_pnach)):
            raise RuntimeError("A +44 portable ISO needs the [ELF Code Cave] pnach "
                               "(BEBF8793_elf_code_cave.pnach) — it frees the region the metadata lives in. "
                               "Put it in your PCSX2 cheats folder (or build <=44 for a cheatless ISO).")
        # NAMES: append romanized strings to globalus
        gtmp = tempfile.mktemp(prefix="glob_", suffix=".bin")
        open(gtmp, "wb").write(orig_glob)
        if os.path.exists(gtmp + ".orig"): os.remove(gtmp + ".orig")
        strings = []
        for g in custom:
            s = slots[g]
            strings += [ee.romanize(s.get("title", "")), ee.romanize(s.get("album", "")), ee.romanize(s.get("artist", ""))]
        base_id = ee._rebuild_globalus(gtmp, strings, log)
        new_glob = open(gtmp, "rb").read()
        for p in (gtmp, gtmp + ".orig"):
            if os.path.exists(p): os.remove(p)
        relocate(buf, grec, new_glob, log)
        # (a) bake the [ELF Code Cave] relocation -> frees 0x16B4F0 for the metadata array
        import re as _re, array, functools, operator
        nc = 0
        for line in open(cave_pnach):
            m = _re.match(r'patch=[01],EE,([0-9A-Fa-f]{8}),extended,([0-9A-Fa-f]{8})', line)
            if m:
                struct.pack_into("<I", buf, eoff + ee._fo(int(m.group(1), 16) & 0x0FFFFFFF), int(m.group(2), 16)); nc += 1
        log(f"  baked {nc} [ELF Code Cave] patches (frees 0x{CAVE:X})")
        # (b) digit hook
        for vbase in ee.HOOK_VAS:
            for k, wv in enumerate(ee.HOOK):
                struct.pack_into("<I", buf, eoff + ee._fo(vbase + k * 4), wv)
        # (c) digit chars 0..num_files-1 — must NOT reach DIGITS_VA+16 (the ".rws" string lives there)
        num_files = (N - 1) // TRACKS_PER_FILE + 1
        n_words = (num_files + 1) // 2
        if n_words > 4:
            raise RuntimeError(f"{N} tracks needs {num_files} _eatrax files; the digit table caps at 8 files (176)")
        digs = b"".join(bytes([0x30 + d, 0]) for d in range(n_words * 2))
        buf[eoff + ee._fo(ee.DIGITS_VA):eoff + ee._fo(ee.DIGITS_VA) + len(digs)] = digs
        # (d) count + baseptr + metadata array @ CAVE
        struct.pack_into("<I", buf, eoff + ee._fo(ee.COUNT_VA), N)
        struct.pack_into("<I", buf, eoff + ee._fo(ee.BASEPTR_VA), CAVE)
        orig = [list(struct.unpack_from("<IIIIII", buf, eoff + ee._fo(ee.META_VA + i * 24))) for i in range(44)]
        ci = 0
        for g in range(N):
            ent = eoff + ee._fo(CAVE) + g * 24
            if slots[g] and slots[g].get("song"):
                b = base_id + ci * 3; ci += 1
                struct.pack_into("<IIIIII", buf, ent, g, 0, b, b + 1, b + 2, 0x0F)
            else:
                e = orig[g]; struct.pack_into("<IIIIII", buf, ent, g, 0, e[2], e[3], e[4], 0x0F)
        # (e) patch the EA-TRAX construct so obj[0xB4]=CAVE (bypass the runtime-reverted baseptr global)
        struct.pack_into("<I", buf, eoff + ee._fo(CONSTRUCT_LUI_VA), 0x3C020000 | (CAVE >> 16))      # lui $v0,hi
        struct.pack_into("<I", buf, eoff + ee._fo(CONSTRUCT_ORI_VA), 0x34450000 | (CAVE & 0xFFFF))   # ori $a1,$v0,lo
        log(f"  baked hook + count={N} + metadata @0x{CAVE:X} + construct patch (obj[0xB4]->CAVE)")
        # (f) CRC-NEUTRAL: keep the ELF XOR-CRC at 0xBEBF8793 so PCSX2 keeps Burnout 3's graphics fixes.
        n4 = ssz - (ssz % 4)
        words = array.array("I"); words.frombytes(bytes(buf[eoff:eoff + n4]))   # host is little-endian (x86)
        cur = functools.reduce(operator.xor, words, 0) & 0xFFFFFFFF
        comp = eoff + ee._fo(CAVE) + N * 24 + 0x40                              # free word in the freed cave hole
        struct.pack_into("<I", buf, comp,
                         struct.unpack_from("<I", buf, comp)[0] ^ (cur ^ 0xBEBF8793))
        log(f"  CRC-neutral: ELF XOR-CRC {cur:08X} -> BEBF8793 (graphics fixes survive)")

    if progress: progress("Writing ISO...")
    open(out_iso, "wb").write(buf)
    log(f"wrote {out_iso} ({len(buf)} bytes, {N} tracks, {len(custom)} custom)")
    return {"out": out_iso, "custom": len(custom), "files": sorted(files), "size": len(buf), "count": N, "expansion": has_exp}

if __name__ == "__main__":
    # CLI test: clean.iso out.iso  slot:song.flac[:Title:Artist:Album] ...   (>44 needs CAVE_PNACH env)
    clean, out = sys.argv[1], sys.argv[2]
    slots = [None] * 44
    for spec in sys.argv[3:]:
        parts = spec.split(":")
        idx = int(parts[0]); song = parts[1]
        ti = parts[2] if len(parts) > 2 else os.path.splitext(os.path.basename(song))[0]
        ar = parts[3] if len(parts) > 3 else ""
        al = parts[4] if len(parts) > 4 else ""
        while len(slots) <= idx: slots.append(None)        # grow for +tracks
        slots[idx] = {"song": song, "title": ti, "artist": ar, "album": al}
    build_portable_iso(clean, out, slots, cave_pnach=os.environ.get("CAVE_PNACH"))
