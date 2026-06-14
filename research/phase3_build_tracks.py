#!/usr/bin/env python3
"""
Phase 3 build, CORRECT injection: _EATRAX2.RWS goes into /TRACKS (where the game
looks: "tracks\\_EATrax2.rws"), via a proper xorriso rebuild instead of ISO9660
byte-surgery (which corrupts — handoff dead-end #1) or the NFSUNDER rename (wrong
directory — that's why the previous test hung at loading).

Steps: patch SLUS (hook + count + metadata 44/45) -> build silence _EATRAX2.RWS ->
xorriso: replace /SLUS_210.50 + add /TRACKS/_EATRAX2.RWS -> verify structurally.

Usage: python3 research/phase3_build_tracks.py IN.iso OUT.iso
"""
import sys, os, struct, subprocess, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
b3spec = importlib.util.spec_from_file_location("b3", os.path.join(HERE, "..", "burnout3_gui.py"))
b3 = importlib.util.module_from_spec(b3spec); b3spec.loader.exec_module(b3)
p3spec = importlib.util.spec_from_file_location("p3", os.path.join(HERE, "phase3_build.py"))
p3 = importlib.util.module_from_spec(p3spec); p3spec.loader.exec_module(p3)
W = b3.InjectionWorker.__new__(b3.InjectionWorker)

SEG_VA, SEG_FO = 0x00100000, 0x100
def fo(va): return SEG_FO + (va - SEG_VA)   # VA -> offset inside the standalone ELF

def patch_slus(elf):
    e = bytearray(elf)
    for base in p3.HOOK_VAS:
        for k, w in enumerate(p3.HOOK):
            struct.pack_into("<I", e, fo(base + k*4), w)
    e[fo(p3.DIGITS_VA):fo(p3.DIGITS_VA)+len(p3.DIGITS)] = p3.DIGITS
    struct.pack_into("<I", e, fo(p3.COUNT_VA), p3.NEW_COUNT)
    def clone(dst, src):
        s = fo(p3.META_BASE_VA + src*24)
        tid, aid, arid = struct.unpack_from("<III", e, s+8)
        struct.pack_into("<IIIIII", e, fo(p3.META_BASE_VA + dst*24),
                         dst, p3.NEW_COUNT if dst == 44 else 0, tid, aid, arid, 0xF)
    clone(44, 41); clone(45, 42)
    return bytes(e)

def main():
    src, dst = sys.argv[1], sys.argv[2]
    iso = open(src, "rb").read()
    eoff, esz = W._find_file_offset_iso9660(iso, "SLUS_210.50")
    open("/tmp/SLUS_210.50", "wb").write(patch_slus(iso[eoff:eoff+esz]))
    rws = p3.build_eatrax2(iso)
    open("/tmp/_EATRAX2.RWS", "wb").write(rws)
    print(f"patched SLUS ({esz}B) + built _EATRAX2.RWS ({len(rws)}B)")

    # xorriso: clone the ISO, replace SLUS, add the file into /TRACKS (plain ISO9660)
    if os.path.exists(dst): os.remove(dst)
    cmd = ["xorriso", "-indev", src, "-outdev", dst,
           "-volid", "SLUS_21050", "-joliet", "off", "-rockridge", "off",
           "-map", "/tmp/SLUS_210.50", "/SLUS_210.50",
           "-map", "/tmp/_EATRAX2.RWS", "/TRACKS/_EATRAX2.RWS",
           "-commit"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("xorriso rc:", r.returncode)
    if r.returncode != 0:
        print(r.stderr[-2000:]); sys.exit("xorriso failed")

    # CRITICAL: xorriso zeroes the first 16 sectors (the PS2 license/boot "system
    # area", the 0xD5... data). The PS2 BIOS needs it or the disc black-screens.
    # Splice the original system area back in (the ISO9660 filesystem starts at
    # sector 16, so this does not touch xorriso's layout).
    SYSTEM_AREA = 16 * 2048
    sa = open(src, "rb").read(SYSTEM_AREA)
    with open(dst, "r+b") as f:
        f.seek(0); f.write(sa)
    print("  ✓ restored PS2 system area (first 16 sectors)")

    # ---------- VERIFY ----------
    print("\n=== VERIFY ===")
    data = open(dst, "rb").read()
    ok = True
    for nm in ("SYSTEM.CNF", "SLUS_210.50", "_EATRAX0.RWS", "_EATRAX1.RWS", "_EATRAX2.RWS", "GLOBALUS.BIN"):
        o, s = W._find_file_offset_iso9660(data, nm)
        print(f"  {nm:14s}: {'@0x%X (%d B)'%(o,s) if o else 'MISSING'}"); ok &= bool(o)
    # SLUS patched?
    eoff2, _ = W._find_file_offset_iso9660(data, "SLUS_210.50")
    base_iso = eoff2 + fo(p3.HOOK_VAS[0])
    good = all(struct.unpack_from("<I", data, base_iso + k*4)[0] == p3.HOOK[k] for k in range(len(p3.HOOK)))
    cnt = struct.unpack_from("<I", data, eoff2 + fo(p3.COUNT_VA))[0]
    print(f"  SLUS hook: {'OK' if good else 'FAIL'}; count={cnt} {'OK' if cnt==p3.NEW_COUNT else 'FAIL'}")
    ok &= good and cnt == p3.NEW_COUNT
    # _EATRAX2 parses + in /TRACKS?
    o2, s2 = W._find_file_offset_iso9660(data, "_EATRAX2.RWS")
    t2, sr2, _ = W._parse_rws_tracks(bytes(data[o2:o2+s2]))
    print(f"  _EATRAX2 parses: {len(t2)} tracks sizes={[s for _,s in t2]} {'OK' if len(t2)==p3.N_NEW else 'FAIL'}")
    ok &= len(t2) == p3.N_NEW
    # path check: confirm _EATRAX2.RWS is under TRACKS (xorriso -find)
    fr = subprocess.run(["xorriso","-indev",dst,"-find","/TRACKS/_EATRAX2.RWS"], capture_output=True, text=True)
    in_tracks = "/TRACKS/_EATRAX2.RWS" in fr.stdout
    print(f"  _EATRAX2.RWS under /TRACKS: {in_tracks}"); ok &= in_tracks
    for nm in ("_EATRAX0.RWS","_EATRAX1.RWS"):
        o1,s1=W._find_file_offset_iso9660(data,nm); tt,_,_=W._parse_rws_tracks(bytes(data[o1:o1+s1]))
        print(f"  {nm}: {len(tt)} tracks {'OK' if len(tt)==22 else 'FAIL'}"); ok &= len(tt)==22
    print("\n=== RESULT:", "✓ PASSED" if ok else "✗ FAILED", "===")
    os.remove("/tmp/SLUS_210.50"); os.remove("/tmp/_EATRAX2.RWS")

if __name__ == "__main__":
    main()
