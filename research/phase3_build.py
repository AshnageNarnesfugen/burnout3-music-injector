#!/usr/bin/env python3
"""
Phase 3 INTEGRATION — produce a testable ISO with playable tracks in _EATrax2.rws.

Combines ONLY proven techniques + the new (verified) digit/index hook:
  1. digit/index hook (digit = track/22) patched into the ELF      [Phase 3, verified]
  2. a silence _EATrax2.rws (2 tracks) built by cloning EATRAX0     [RWS format, verified]
  3. injected via the NFSUNDER.ELF in-place rename trick            [handoff, proven]
  4. master count = 46 + metadata entries 44/45 (in-place exploit)  [handoff, proven]

Result: UI tracks 45/46 (= internal 44/45) map to _EATrax2 local 0/1 and — thanks to the
hook — build the right path and a valid local index, so they should PLAY (silence) instead
of killing audio (dead-end #3). Names are cloned from tracks 41/42 (real GLOBALUS strings).

Usage: python3 research/phase3_build.py IN.iso OUT.iso
Verifies the output structurally (cannot test actual playback — that needs PCSX2).
"""
import sys, os, struct, shutil, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("b3", os.path.join(HERE, "..", "burnout3_gui.py"))
b3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b3)
W = b3.InjectionWorker.__new__(b3.InjectionWorker)

SECTOR = 2048
SEG_VA, SEG_FO = 0x00100000, 0x100
# Phase 3 hook (from phase3_hook.py, verified)
HOOK = [0x8E0200D8,0x24010016,0x0041001B,0x00001012,0xAE0200E0,
        0x00024040,0x3C01004D,0x2421EA78,0x00284021]  # lui 0x4D (sign-ext fix) -> 0x4CEA78
HOOK_VAS = [0x003FBCD0, 0x003FC38C]
DIGITS_VA, DIGITS = 0x004CEA78, b'0\x001\x002\x003\x00'
COUNT_VA = 0x004A5A24
META_BASE_VA = 0x004A5600
N_NEW = 2                      # tracks 44, 45
NEW_COUNT = 44 + N_NEW         # 46
SIL_TRACK = 8192 * 128         # 1 MB silence each (~28s, >500KB so the parser validates)

def find(iso, name):
    off, size = W._find_file_offset_iso9660(iso, name)
    return off, size

def dir_record(iso, name):
    """Return the directory-record offset for a file (scan from root)."""
    po = 16*SECTOR
    rlba = struct.unpack_from("<I", iso, po+158)[0]; rsz = struct.unpack_from("<I", iso, po+166)[0]
    def scan(lba, sz):
        base, end, p = lba*SECTOR, lba*SECTOR+sz, lba*SECTOR
        while p < end:
            ln = iso[p]
            if ln == 0: p = ((p//SECTOR)+1)*SECTOR; continue
            fg = iso[p+25]; nl = iso[p+32]
            nm = bytes(iso[p+33:p+33+nl]).split(b";")[0]
            if not (nl==1 and iso[p+33] in (0,1)):
                if fg & 2:
                    r = scan(struct.unpack_from("<I",iso,p+2)[0], struct.unpack_from("<I",iso,p+10)[0])
                    if r is not None: return r
                elif nm == name:
                    return p
            p += ln
        return None
    return scan(rlba, rsz)

def build_eatrax2(iso):
    """Clone EATRAX0 header -> a silence _EATrax2.rws with N_NEW tracks."""
    off, size = find(iso, "_EATRAX0.RWS")
    rws = bytes(iso[off:off+size])
    hsize = struct.unpack_from("<I", rws, 16)[0]
    hdr = bytearray(rws[:24+hsize])
    # NOTE: do NOT rename the internal "EATrax0" name. Handoff dead-end #4 says an
    # internal name of "EATrax2" hangs the game at "loading"; a clone keeping the
    # original name boots. The filename (_EATRAX2.RWS) is what selects the file.
    # Set the internal track-count field (0x38, big-endian) to the real count so the
    # game's RWS loader doesn't iterate the 20 zeroed table entries.
    struct.pack_into(">I", hdr, 0x38, N_NEW)
    # locate track table (size@+24, off@+28, stride 32 — the working tool's layout)
    ENTRY, SW, OW = 32, 24, 28
    he = 24+hsize; ft = None
    for scan in range(24, he-32, 4):
        cs = struct.unpack_from("<I", hdr, scan)[0]; co = struct.unpack_from("<I", hdr, scan+4)[0]
        if co == 0 and 500000 < cs < 50000000:
            e0 = scan-SW
            if e0 < 24: continue
            e1s = struct.unpack_from("<I", hdr, e0+ENTRY+SW)[0]; e1o = struct.unpack_from("<I", hdr, e0+ENTRY+OW)[0]
            if e1o == cs and 500000 < e1s < 50000000: ft = e0; break
    assert ft is not None, "track table not found"
    cum = 0
    for k in range(22):
        eo = ft + k*ENTRY
        if k < N_NEW:
            struct.pack_into("<I", hdr, eo+SW, SIL_TRACK); struct.pack_into("<I", hdr, eo+OW, cum); cum += SIL_TRACK
        else:
            struct.pack_into("<I", hdr, eo+SW, 0); struct.pack_into("<I", hdr, eo+OW, cum)
    data_total = N_NEW * SIL_TRACK
    out = bytearray(hdr)
    out += struct.pack("<III", 0x080F, data_total, 0x1C020009)
    struct.pack_into("<I", out, 4, hsize + 12 + 12 + data_total)
    out += b3.encode_psx_adpcm_sized(b"", SIL_TRACK) * N_NEW
    return bytes(out)

def elf_iso_off(iso_elf_off, va):
    return iso_elf_off + SEG_FO + (va - SEG_VA)

def main():
    if len(sys.argv) < 3:
        sys.exit("usage: phase3_build.py IN.iso OUT.iso")
    src, dst = sys.argv[1], sys.argv[2]
    print(f"copying {src} -> {dst} ...")
    shutil.copy2(src, dst)
    iso = bytearray(open(dst, "rb").read())

    elf_off, _ = find(iso, "SLUS_210.50")
    print(f"SLUS ELF @ ISO 0x{elf_off:X}")

    # 1) HOOK + digit strings
    for base in HOOK_VAS:
        for k, wd in enumerate(HOOK):
            struct.pack_into("<I", iso, elf_iso_off(elf_off, base + k*4), wd)
    o = elf_iso_off(elf_off, DIGITS_VA); iso[o:o+len(DIGITS)] = DIGITS
    print("  ✓ hook + digit strings patched")

    # 2) build _EATrax2.rws
    rws = build_eatrax2(iso)
    print(f"  ✓ built _EATrax2.rws: {len(rws)} bytes ({N_NEW} tracks)")

    # 3) inject via NFSUNDER.ELF rename (write RWS at NFSUNDER's LBA, rename+resize record)
    rec = dir_record(iso, b"NFSUNDER.ELF")
    lba = struct.unpack_from("<I", iso, rec+2)[0]
    alloc = ((struct.unpack_from("<I", iso, rec+10)[0]) + SECTOR-1)//SECTOR * SECTOR
    assert len(rws) <= alloc, f"RWS {len(rws)} > NFSUNDER alloc {alloc}"
    iso[lba*SECTOR:lba*SECTOR+len(rws)] = rws
    # rename (14 chars, in place) + LBA(keep) + size(both-endian)
    newname = b"_EATRAX2.RWS;1"
    assert iso[rec+32] == len(newname)
    iso[rec+33:rec+33+len(newname)] = newname
    struct.pack_into("<I", iso, rec+10, len(rws)); struct.pack_into(">I", iso, rec+14, len(rws))
    print(f"  ✓ injected at LBA {lba}; renamed NFSUNDER.ELF -> _EATRAX2.RWS (size {len(rws)})")

    # 4) count + metadata entries 44/45 (clone string ids from 41/42), in-place exploit
    struct.pack_into("<I", iso, elf_iso_off(elf_off, COUNT_VA), NEW_COUNT)
    def clone_entry(dst_track, src_track):
        s = elf_iso_off(elf_off, META_BASE_VA + src_track*24)
        d = elf_iso_off(elf_off, META_BASE_VA + dst_track*24)
        tid, aid, arid = struct.unpack_from("<III", iso, s+8)
        struct.pack_into("<IIIIII", iso, d, dst_track, NEW_COUNT if dst_track==44 else 0, tid, aid, arid, 0xF)
        return tid, aid, arid
    clone_entry(44, 41); clone_entry(45, 42)
    print(f"  ✓ count={NEW_COUNT}, metadata 44/45 cloned from 41/42")

    open(dst, "wb").write(iso)
    print(f"  ✓ wrote {dst}")

    # ---------- VERIFY (structural) ----------
    print("\n=== VERIFY output ISO ===")
    data = bytes(iso)
    ok = True
    # disc id intact
    ok &= b"SLUS_210.50" in data
    print(f"  disc id present: {b'SLUS_210.50' in data}")
    # hook bytes
    for base in HOOK_VAS:
        good = all(struct.unpack_from("<I", data, elf_iso_off(elf_off, base+k*4))[0]==HOOK[k] for k in range(len(HOOK)))
        print(f"  hook @0x{base:08X}: {'OK' if good else 'FAIL'}"); ok &= good
    # count
    c = struct.unpack_from("<I", data, elf_iso_off(elf_off, COUNT_VA))[0]
    print(f"  master count = {c}: {'OK' if c==NEW_COUNT else 'FAIL'}"); ok &= (c==NEW_COUNT)
    # metadata 44/45
    for tk in (44,45):
        e = elf_iso_off(elf_off, META_BASE_VA+tk*24)
        idx,pad,tid,aid,arid,fl = struct.unpack_from("<IIIIII", data, e)
        print(f"  meta entry {tk}: idx={idx} title={tid} album={aid} artist={arid} flags=0x{fl:X}")
    # _EATRAX2.RWS present and parses
    off2,sz2 = find(data, "_EATRAX2.RWS")
    print(f"  _EATRAX2.RWS @ ISO 0x{off2:X} size={sz2}")
    t2,sr2,ch2 = W._parse_rws_tracks(bytes(data[off2:off2+sz2]))
    print(f"  _EATRAX2 parses: {len(t2)} tracks sizes={[s for _,s in t2]} sr={sr2}: {'OK' if len(t2)==N_NEW else 'FAIL'}"); ok &= (len(t2)==N_NEW)
    # originals intact
    for nm in ("_EATRAX0.RWS","_EATRAX1.RWS"):
        o1,s1 = find(data, nm); tt,_,_ = W._parse_rws_tracks(bytes(data[o1:o1+s1]))
        print(f"  {nm}: {len(tt)} tracks {'OK' if len(tt)==22 else 'FAIL'}"); ok &= (len(tt)==22)
    print("\n=== RESULT:", "✓ ALL STRUCTURAL CHECKS PASSED" if ok else "✗ FAILED", "===")

if __name__ == "__main__":
    main()
