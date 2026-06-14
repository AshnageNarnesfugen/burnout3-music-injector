#!/usr/bin/env python3
"""
Phase 3 — EA TRAX file-index hook for SLUS_210.50 (NTSC-U, CRC BEBF8793).

Generalizes the hardcoded 2-file digit logic ("track<22?'0':'1'") to N files:
    digit      = track / 22          (0,1,2,3,...)
    localIndex = track - digit*22    (already done at 0x3FC8C0, unchanged)
    pathDigit  = digitstring[digit]  (new table at 0x4CEA78)

This unblocks _EATrax2.rws (tracks 44-65), _EATrax3.rws (66-87), etc. The 9-instruction
digit block in BOTH Prepare functions is replaced IN PLACE (same size, same registers),
so no code cave is needed for up to ~4 files.

Still required for full playback (not done here): bump master count at 0x4A5A24,
metadata entries for the new tracks (relocate array via ptr 0x4A5A6C), and a real
_EATraxN.rws with a valid <=22-entry track table.

Usage:
    python3 research/phase3_hook.py                 # verify + emit pnach
    python3 research/phase3_hook.py --iso IN.iso    # also read the real ELF and verify against it
"""
import struct, sys, os

# --- the 9 replacement instructions (assembled, verified below) ---
HOOK_WORDS = [
    0x8E0200D8,  # lw    v0, 0xd8(s0)      ; track
    0x24010016,  # addiu at, zero, 22
    0x0041001B,  # divu  zero, v0, at      ; lo = track/22
    0x00001012,  # mflo  v0                ; digit
    0xAE0200E0,  # sw    v0, 0xe0(s0)      ; this+0xe0 = digit
    0x00024040,  # sll   t0, v0, 1         ; digit*2
    0x3C01004D,  # lui   at, 0x004D        ; (0x4D, not 0x4C: low half 0xEA78 sign-extends)
    0x2421EA78,  # addiu at, at, -0x1588   ; at = 0x4D0000 - 0x1588 = 0x4CEA78
    0x00284021,  # addu  t0, at, t0        ; t0 = &digitstr[digit]
]
PREPARE_PATCH_VAS = [0x003FBCD0, 0x003FC38C]   # start of the digit block in each Prepare
DIGITS_VA   = 0x004CEA78
DIGITS_DATA = b'0\x001\x002\x003\x00'          # "0","1","2","3" null-terminated, 8 bytes
SEG_VA, SEG_FO = 0x00100000, 0x100
def va2fo(va): return SEG_FO + (va - SEG_VA)

# ---- tiny disassembler (just enough to verify the hook) ----
REG=["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7",
     "s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra"]
def dis(w):
    op=w>>26; rs=(w>>21)&0x1F; rt=(w>>16)&0x1F; rd=(w>>11)&0x1F; sh=(w>>6)&0x1F; fn=w&0x3F
    imm=w&0xFFFF; si=imm-0x10000 if imm&0x8000 else imm
    if w==0: return "nop"
    if op==0:
        m={0:"sll",0x21:"addu",0x1b:"divu",0x12:"mflo"}.get(fn,f"r{fn:02x}")
        if fn==0: return f"sll {REG[rd]},{REG[rt]},{sh}"
        if fn==0x12: return f"mflo {REG[rd]}"
        if fn==0x1b: return f"divu {REG[rs]},{REG[rt]}"
        return f"{m} {REG[rd]},{REG[rs]},{REG[rt]}"
    if op==0x0f: return f"lui {REG[rt]},0x{imm:04X}"
    if op==0x09: return f"addiu {REG[rt]},{REG[rs]},{si}"
    if op==0x23: return f"lw {REG[rt]},{si}({REG[rs]})"
    if op==0x2b: return f"sw {REG[rt]},{si}({REG[rs]})"
    return f"op{op:02x}"

def verify():
    print("=== assembled hook (verify by disassembly) ===")
    for i,w in enumerate(HOOK_WORDS):
        print(f"  +{i*4:02d}  0x{w:08X}  {dis(w)}")
    # sanity: digit string table
    print(f"\n=== digit table @0x{DIGITS_VA:08X}: {DIGITS_DATA!r} ===")
    for d in range(4):
        off = d*2
        s = DIGITS_DATA[off:DIGITS_DATA.index(b'\x00',off)]
        print(f"  digit {d} -> 0x{DIGITS_VA+off:08X} = \"{s.decode()}\"")

def make_pnach(count=None):
    """PCSX2 cheat. IMPORTANT: 'extended' patches use the address's top nibble as the
    write-size command — 2 = 32-bit word write. A bare 0x00xxxxxx address means command 0
    = BYTE write (only the low byte lands!), which silently corrupts instructions. So every
    address must be ORed with 0x20000000 (matches Nahelam's working `20113DB8` form)."""
    def line(addr, val, place=1):
        return f"patch={place},EE,{0x20000000|addr:08X},extended,{val:08X}"
    L=["gametitle=Burnout 3: Takedown (USA) SLUS-21050",
       "comment=EA TRAX N-file hook (digit=track/22) - Phase 3",""]
    for base in PREPARE_PATCH_VAS:
        L.append(f"// Prepare digit block @0x{base:08X}")
        for i,w in enumerate(HOOK_WORDS):
            L.append(line(base+i*4, w))
    w0,w1 = struct.unpack("<II", DIGITS_DATA)
    L.append(f"// digit strings @0x{DIGITS_VA:08X}")
    L.append(line(DIGITS_VA, w0)); L.append(line(DIGITS_VA+4, w1))
    if count is not None:
        L.append(f"// master track count @0x004A5A24")
        L.append(line(0x004A5A24, count))
    return "\n".join(L)+"\n"

def patch_elf(elf):
    elf=bytearray(elf)
    for base in PREPARE_PATCH_VAS:
        for i,w in enumerate(HOOK_WORDS):
            struct.pack_into("<I", elf, va2fo(base+i*4), w)
    elf[va2fo(DIGITS_VA):va2fo(DIGITS_VA)+len(DIGITS_DATA)] = DIGITS_DATA
    return bytes(elf)

def check_against_elf(elf):
    print("\n=== sanity-check vs the real ELF ===")
    # confirm the original digit block matches what we expect (so addresses are right)
    orig = struct.unpack_from("<I", elf, va2fo(0x3FBCD0))[0]
    print(f"  0x3FBCD0 original = 0x{orig:08X} ({dis(orig)})  expect 'lw v0,216(s0)' (8E0200D8): "
          + ("OK" if orig==0x8E0200D8 else "MISMATCH!"))
    digbytes = elf[va2fo(DIGITS_VA):va2fo(DIGITS_VA)+8]
    free = digbytes[2:] == bytes(6)   # bytes 2..7 must be padding (free for "1","2","3")
    print(f"  0x4CEA78 region currently = {digbytes!r} "
          + f"(bytes 2-7 free for digits: {'OK' if free else 'CHECK'})")

if __name__=="__main__":
    verify()
    iso=None
    if "--iso" in sys.argv:
        iso=sys.argv[sys.argv.index("--iso")+1]
    if iso:
        data=open(iso,"rb").read()
        # locate SLUS ELF
        po=16*2048; rlba=struct.unpack_from("<I",data,po+158)[0]; rsz=struct.unpack_from("<I",data,po+166)[0]
        p=rlba*2048; end=p+rsz
        while p<end:
            ln=data[p]
            if ln==0: p=((p//2048)+1)*2048; continue
            nl=data[p+32]
            if bytes(data[p+33:p+33+nl]).split(b";")[0]==b"SLUS_210.50":
                lba=struct.unpack_from("<I",data,p+2)[0]; sz=struct.unpack_from("<I",data,p+10)[0]
                check_against_elf(data[lba*2048:lba*2048+sz]); break
            p+=ln
    out=os.path.join(os.path.dirname(os.path.abspath(__file__)), "BEBF8793_eatrax_nfiles.pnach")
    open(out,"w").write(make_pnach(count=66))
    print(f"\nWrote pnach -> {out}")
