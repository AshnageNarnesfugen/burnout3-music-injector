#!/usr/bin/env python3
"""Build a PORTABLE Burnout 3 ISO with custom music baked in (self-contained).

Burnout 3 reads its loose disc files by FIXED LBA — re-authoring the whole ISO
(xorriso/genisoimage) moves every file and black-screens. EXCEPT: the EA-TRAX RWS
files are opened BY PATH (proven in PCSX2 — relocating _EATRAX0 to the disc end and
zeroing the old copy still plays tracks 1-22). So the trick is:

  keep EVERY original file byte-identical at its original LBA, and surgically
  relocate ONLY the (enlarged) EATRAX files to the end of the disc, patching just
  their ISO9660 directory records (extent LBA + size, LE & BE) and the PVD size.

Result: full-length custom tracks in a self-contained ISO that boots anywhere
(PCSX2, Android AetherSX2/NetherSX2, real PS2) with no cheats.
"""
import os, sys, struct, tempfile, shutil

from core import eatrax as ee

HERE = os.path.dirname(os.path.abspath(__file__))            # core/
ROOT = os.path.dirname(HERE)                                 # repo root
# In a PyInstaller build the bundled data root is sys._MEIPASS; research/ is bundled there.
_DATA = getattr(sys, "_MEIPASS", ROOT)


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
CAVE = 0x0016B4F0          # Nahelam code cave (frees ~188KB at the SAME VA on NTSC and PAL); metadata lives here.
ORDER_OFF = 0x208          # relocate the per-track play-ORDER array obj[13] -> obj+0x208 (a free gap in the obj)
PLOC_CAVE_OFF = 0x1160     # NTSC PLOC copy lives at CAVE+0x1160

# ─── Per-disc expansion profiles ─────────────────────────────────────────
# The EATRAX construct copies the global baseptr into obj[0xB4]; the game RESETS that global at runtime, so
# the >44 path patches the construct itself to force obj[0xB4]=CAVE. The cave is at the same VA on both discs;
# the EATRAX metadata (DATA) shifted +0x310 and the menu/construct CODE shifted ~+0x420 on PAL. PAL needs ONLY
# the order-array relocation — the extra NTSC play-loc patches (PLOC reloc + nav-count + 0x3FBB00) aren't needed
# there, and leaving PLOC alone keeps the radio DJ playing. (See memory: burnout-pal-iso, eatrax-dj-playloc-tradeoff.)
DISC_PROFILES = {
    "SLUS_210.50": {   # NTSC-U (USA), game CRC BEBF8793
        "region": "NTSC-U", "elf": "/SLUS_210.50", "globalus": ["/DATA/GLOBALUS.BIN"], "crc": 0xBEBF8793,
        "cave_pnach": os.path.join("research", "elf_code_cave.pnach"),
        "meta_va": 0x4A5600, "count_va": 0x4A5A24, "baseptr_va": 0x4A5A6C,
        "hook_vas": [0x3FBCD0, 0x3FC38C], "digits_va": 0x4CEA78,
        "construct_lui": 0x3FCDC8, "construct_ori": 0x3FCDD0,
        "order_accessors": [0x3F3A0C, 0x3FB8DC, 0x3FB914, 0x3FB968, 0x3FB978, 0x3FB97C, 0x3FB980,
                            0x3FBED0, 0x3FBF7C, 0x3FBFD0, 0x3FBFE0, 0x3FBFE4, 0x3FBFE8],
        "ploc": {   # the full NTSC menu fix (PLOC reloc + 0x3FBB00 metadata-base rework + nav-count)
            "formB": [(0x3FCA34, 0x3FCA3C), (0x4218E0, 0x4218E8), (0x421B2C, 0x421B34),
                      (0x45C198, 0x45C1A0), (0x45C70C, 0x45C714)],
            "formA": [(0x3FCC2C, 0x3FCC38), (0x431480, 0x431484), (0x431524, 0x43152C)],
            "bb00": (0x3FBB10, 0x3FBB14, 0x3FBB1C, 0x3FBB20),
            "navcount": [0x431194, 0x431684],
        },
    },
    "SLES_525.85": {   # PAL (Europe, Fr/De/It), game CRC CE49B0DE
        "region": "PAL (Fr/De/It)", "elf": "/SLES_525.85",
        "globalus": ["/DATA/GLOBALFR.BIN", "/DATA/GLOBALGE.BIN", "/DATA/GLOBALIT.BIN"], "crc": 0xCE49B0DE,
        "cave_pnach": os.path.join("research", "pal", "SLES-52585_elf_code_cave.pnach"),
        "meta_va": 0x4A5910, "count_va": 0x4A5D34, "baseptr_va": 0x4A5D7C,
        "hook_vas": [0x3FC0F0, 0x3FC7AC], "digits_va": CAVE + 0x1800,   # digit table in the cave (0x16CCF0)
        "construct_lui": 0x3FD1E8, "construct_ori": 0x3FD1F0,
        "order_accessors": [0x3F3D7C, 0x3FBC60, 0x3FBC98, 0x3FBCEC, 0x3FBCFC, 0x3FBD00, 0x3FBD04,
                            0x3FC2F0, 0x3FC39C, 0x3FC3F0, 0x3FC400, 0x3FC404, 0x3FC408],
        "ploc": None,   # PAL: the order-array relocation alone suffices (and keeps the DJ)
    },
}

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

def _hook_words(digits_va):
    """The 9 digit-hook instructions, with the digit-table address baked into words 6,7 (lui at,hi; addiu at,lo)."""
    h = list(ee.HOOK)
    h[6] = 0x3C010000 | (((digits_va + 0x8000) >> 16) & 0xFFFF)   # lui  at,hi
    h[7] = 0x24210000 | (digits_va & 0xFFFF)                      # addiu at,at,lo  -> at = digits_va
    return h


def _detect_profile(buf):
    """Identify the disc (NTSC-U / PAL) by which game ELF its filesystem contains."""
    for key, prof in DISC_PROFILES.items():
        try:
            find_record(buf, prof["elf"]); return key, prof
        except RuntimeError:
            pass
    raise RuntimeError("Unrecognized Burnout 3 disc — expected NTSC-U (SLUS_210.50) or PAL (SLES_525.85). "
                       "PAL/JP variants other than SLES-52585 aren't profiled yet.")


def build_portable_iso(clean_iso, out_iso, slots, log=print, progress=None, cave_pnach=None):
    """Bake a portable Burnout 3 ISO (self-contained) — up to 176 tracks. Auto-detects NTSC-U vs PAL.

    slots[g] = None (keep original game track) or {'song','title','artist','album'} (custom, full-length).
    <=44: rename in place via globalus only (ELF untouched, the disc's game CRC preserved).
    >44 : bake the whole EA-TRAX expansion into the ELF (cave + hook + count + metadata + construct + the
          order-array relocation) and XOR-compensate so the game CRC stays the disc's original. Needs the
          disc's [ELF Code Cave] pnach (bundled per region).
    Everything else stays byte-identical at its original LBA, so the disc still boots."""
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
    disc, prof = _detect_profile(buf)
    log(f"  disc: {disc} — {prof['region']}")
    if cave_pnach is None:
        cave_pnach = os.path.join(_DATA, prof["cave_pnach"])   # bundled with the tool (no separate download)

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
            relocate(buf, rec, ee._build_eatrax_file(base, files[f], tmp, log), log)
        for f in sorted(files):                          # new files >=2: build from _EATRAX1 template + add record
            if f < 2: continue
            if progress: progress(f"Encoding _EATRAX{f}.RWS (new)...")
            _, l1, s1 = find_record(buf, "/TRACKS/_EATRAX1.RWS")
            base1 = bytes(buf[l1 * 2048:l1 * 2048 + s1])
            new = ee._build_eatrax_file(base1, files[f], tmp, log)
            lba = append_data(buf, new)
            add_dir_record(buf, "/TRACKS", f"_EATRAX{f}.RWS;1", lba, len(new), log)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2+3) NAMES + METADATA
    srec, slba, ssz = find_record(buf, prof["elf"])
    eoff = slba * 2048
    meta_fo = ee._fo(prof["meta_va"])
    if progress: progress("Rebuilding names (GLOBALUS)...")
    if not has_exp:
        # Rename WITHOUT touching the ELF: overwrite each custom track's ORIGINAL globalus string ids in
        # place (the unmodified ELF metadata keeps pointing at them). PCSX2 computes the game CRC by XOR-ing
        # every ELF word, so baking new ids into the ELF would change the CRC and PCSX2 would drop Burnout 3's
        # graphics fixes (black sky / over-bloom). Keeping the ELF byte-identical preserves the disc's CRC ->
        # visuals stay correct. PAL keeps one name table per language, so apply the same overrides to all.
        overrides = {}
        for g in custom:
            tid, aid, rid = struct.unpack_from("<III", buf, eoff + meta_fo + g * 24 + 8)  # title, album, artist ids
            s = slots[g]
            overrides[tid] = ee.romanize(s.get("title", ""))
            overrides[aid] = ee.romanize(s.get("album", ""))
            overrides[rid] = ee.romanize(s.get("artist", ""))
        for gpath in prof["globalus"]:
            grec, glba, gsz = find_record(buf, gpath)
            orig_glob = bytes(buf[glba * 2048:glba * 2048 + gsz])
            relocate(buf, grec, ee.globalus_overwrite(orig_glob, overrides, log), log)
        log(f"  renamed {len(custom)} track(s) via {len(prof['globalus'])} globalus table(s) — ELF untouched, CRC preserved")
    else:
        # >44: bake the EA-TRAX expansion into the ISO's ELF. The metadata lives in the freed cave (the game
        # reverts the baseptr global at runtime, so the construct is patched to force obj[0xB4]=CAVE). All
        # baked, then CRC-neutralised so PCSX2 keeps the disc's graphics fixes.
        if not (cave_pnach and os.path.isfile(cave_pnach)):
            raise RuntimeError(f"A +44 portable ISO needs this disc's [ELF Code Cave] pnach "
                               f"({os.path.basename(prof['cave_pnach'])}) — it frees the region the metadata "
                               f"lives in. Expected (bundled) at: {cave_pnach}")
        # NAMES: append the romanized strings to every (per-language) globalus table
        strings = []
        for g in custom:
            s = slots[g]
            strings += [ee.romanize(s.get("title", "")), ee.romanize(s.get("album", "")), ee.romanize(s.get("artist", ""))]
        base_id = None
        for gpath in prof["globalus"]:
            grec, glba, gsz = find_record(buf, gpath)
            orig_glob = bytes(buf[glba * 2048:glba * 2048 + gsz])
            gtmp = tempfile.mktemp(prefix="glob_", suffix=".bin")
            open(gtmp, "wb").write(orig_glob)
            if os.path.exists(gtmp + ".orig"): os.remove(gtmp + ".orig")
            base_id = ee._rebuild_globalus(gtmp, strings, log)     # same count across langs -> same base_id
            new_glob = open(gtmp, "rb").read()
            for p in (gtmp, gtmp + ".orig"):
                if os.path.exists(p): os.remove(p)
            relocate(buf, grec, new_glob, log)
        # (a) bake the [ELF Code Cave] relocation -> frees CAVE for the metadata array
        import re as _re, array, functools, operator
        nc = 0
        for line in open(cave_pnach):
            m = _re.match(r'patch=[01],EE,([0-9A-Fa-f]{8}),extended,([0-9A-Fa-f]{8})', line)
            if m:
                struct.pack_into("<I", buf, eoff + ee._fo(int(m.group(1), 16) & 0x0FFFFFFF), int(m.group(2), 16)); nc += 1
        log(f"  baked {nc} [ELF Code Cave] patches (frees 0x{CAVE:X})")
        # (b) digit hook — the digit-table address is baked into the hook words per profile
        hook = _hook_words(prof["digits_va"])
        for vbase in prof["hook_vas"]:
            for k, wv in enumerate(hook):
                struct.pack_into("<I", buf, eoff + ee._fo(vbase + k * 4), wv)
        # (c) digit chars 0..num_files-1 (NTSC: must not reach the ".rws" string; PAL: in the cave, no collision)
        num_files = (N - 1) // TRACKS_PER_FILE + 1
        n_words = (num_files + 1) // 2
        if n_words > 4:
            raise RuntimeError(f"{N} tracks needs {num_files} _eatrax files; the digit table caps at 8 files (176)")
        digs = b"".join(bytes([0x30 + d, 0]) for d in range(n_words * 2))
        dv = prof["digits_va"]
        buf[eoff + ee._fo(dv):eoff + ee._fo(dv) + len(digs)] = digs
        # (d) count + baseptr + metadata array @ CAVE
        struct.pack_into("<I", buf, eoff + ee._fo(prof["count_va"]), N)
        struct.pack_into("<I", buf, eoff + ee._fo(prof["baseptr_va"]), CAVE)
        orig = [list(struct.unpack_from("<IIIIII", buf, eoff + ee._fo(prof["meta_va"] + i * 24))) for i in range(44)]
        ci = 0
        for g in range(N):
            ent = eoff + ee._fo(CAVE) + g * 24
            if slots[g] and slots[g].get("song"):
                b = base_id + ci * 3; ci += 1
                struct.pack_into("<IIIIII", buf, ent, g, 0, b, b + 1, b + 2, 0x0F)
            else:
                e = orig[g]; struct.pack_into("<IIIIII", buf, ent, g, 0, e[2], e[3], e[4], 0x0F)
        # (e) patch the EA-TRAX construct so obj[0xB4]=CAVE (bypass the runtime-reverted baseptr global)
        struct.pack_into("<I", buf, eoff + ee._fo(prof["construct_lui"]), 0x3C020000 | (CAVE >> 16))    # lui $v0,hi
        struct.pack_into("<I", buf, eoff + ee._fo(prof["construct_ori"]), 0x34450000 | (CAVE & 0xFFFF))  # ori $a1,$v0,lo
        log(f"  baked hook + count={N} + metadata @0x{CAVE:X} + construct patch (obj[0xB4]->CAVE)")
        # (e2) PER-TRACK PLAY-LOCATION / anti-crash fixes. The EATRAX obj is laid out for 44 tracks: the per-track
        # play-ORDER array at obj[13] (1 byte/track) OVERFLOWS, for >44 tracks, into the obj's other state — a
        # word-array @obj[88] whose elements include obj[104]/obj[108] (the menu control block + its row count).
        # The obj is built at INIT, so that clobber corrupts state at boot -> loading hang (and the menu crash /
        # infinite list / gameplay crash on a music-change event). The clean root fix: relocate the ORDER ARRAY
        # itself to a free gap in the obj (obj+0x208), so nothing else is touched. (See eatrax-menu-list-playloc.)
        def _patchw(va, word): struct.pack_into("<I", buf, eoff + ee._fo(va), word & 0xFFFFFFFF)
        def _getw(va): return struct.unpack_from("<I", buf, eoff + ee._fo(va))[0]
        for va in prof["order_accessors"]:                       # the 13 obj[13] accessors (init/shuffle/search/play)
            w = _getw(va); assert (w & 0xFFFF) == 13, f"0x{va:X} not an obj[13] accessor"
            _patchw(va, (w & 0xFFFF0000) | ORDER_OFF)
        # The remaining NTSC menu patches (PLOC reloc + 0x3FBB00 metadata-base rework + nav-count hardcode) are
        # NOT needed on PAL — relocating the order array alone keeps obj[88..108] intact there. Leaving PLOC
        # alone also keeps the radio DJ playing. (See eatrax-dj-playloc-tradeoff.)
        if prof["ploc"]:
            p = prof["ploc"]
            # PLOC (per-track play-loc setting array @0x4F5040, BSS sized for 44): relocate every accessor to a
            # cave-resident copy sized for N and bake it 0x0F (=ALL). form-B accessors load 0x4F5040 directly;
            # form-A load 0x4EE040 then +0x7000.
            PLOC = CAVE + PLOC_CAVE_OFF
            def _reloc_addr(lui_va, lo_va, addr):                # rewrite a lui/addiu address pair, keep regs
                _patchw(lui_va, (_getw(lui_va) & 0xFFFF0000) | (((addr + 0x8000) >> 16) & 0xFFFF))
                _patchw(lo_va,  (_getw(lo_va)  & 0xFFFF0000) | (addr & 0xFFFF))
            for lui_va, lo_va in p["formB"]: _reloc_addr(lui_va, lo_va, PLOC)            # form-B: base = PLOC
            for lui_va, lo_va in p["formA"]: _reloc_addr(lui_va, lo_va, PLOC - 0x7000)   # form-A: base+0x7000 = PLOC
            for i in range(N): buf[eoff + ee._fo(PLOC) + i] = 0x0F                       # bake PLOC = ALL
            # 0x3FBB00 (list per-track metadata copy) reads ctrl[76], reverted to the 44-entry table at runtime
            # -> garbage for extras. Rework so a1 = CAVE + track*24.
            bb = p["bb00"]
            _patchw(bb[0], 0x3C020000 | (CAVE >> 16))            # lui $v0,hi   (was nop)
            _patchw(bb[1], 0x00051840)                           # sll $v1,$a1,1
            _patchw(bb[2], 0x00651821)                           # addu $v1,$v1,$a1
            _patchw(bb[3], 0x34420000 | (CAVE & 0xFFFF))         # ori $v0,$v0,lo  (was lw $v0,76($a2))
            for va in p["navcount"]:                             # nav row-count = obj[108] -> hardcode to N
                _patchw(va, 0x24030000 | (N & 0xFFFF))           # li $v1,N
            log(f"  per-track fixes: order-array(13) + PLOC reloc+bake + metadata->CAVE + nav-count={N}")
        else:
            log("  per-track fix: order-array(13) relocated (PAL needs no PLOC/nav-count — DJ stays on)")
        # (f) CRC-NEUTRAL: keep the ELF XOR-CRC at the disc's value so PCSX2 keeps Burnout 3's graphics fixes.
        n4 = ssz - (ssz % 4)
        words = array.array("I"); words.frombytes(bytes(buf[eoff:eoff + n4]))   # host is little-endian (x86)
        cur = functools.reduce(operator.xor, words, 0) & 0xFFFFFFFF
        comp = eoff + ee._fo(CAVE) + N * 24 + 0x40                              # free word in the freed cave hole
        struct.pack_into("<I", buf, comp,
                         struct.unpack_from("<I", buf, comp)[0] ^ (cur ^ prof["crc"]))
        log(f"  CRC-neutral: ELF XOR-CRC {cur:08X} -> {prof['crc']:08X} (graphics fixes survive)")

    if progress: progress("Writing ISO...")
    open(out_iso, "wb").write(buf)
    log(f"wrote {out_iso} ({len(buf)} bytes, {N} tracks, {len(custom)} custom)")
    return {"out": out_iso, "custom": len(custom), "files": sorted(files), "size": len(buf), "count": N,
            "expansion": has_exp, "disc": disc, "region": prof["region"]}

if __name__ == "__main__":
    # CLI test (run as a module from the repo root):  python -m core.portable_iso clean.iso out.iso
    #   slot:song.flac[:Title:Artist:Album] ...   (>44 needs CAVE_PNACH env)
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
