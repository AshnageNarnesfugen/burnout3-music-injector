#!/usr/bin/env python3
"""
Phase 2 — SLUS_210.50 EA TRAX static analysis (reproducible).

Extracts the SLUS_210.50 ELF from a Burnout 3 (USA) ISO, validates the song
metadata array, scans MIPS code for references to the known EA TRAX data
addresses, and disassembles the path-builder / loader functions.

Usage:
    python3 research/phase2_elf_analysis.py "/path/to/Burnout 3 - Takedown (USA).iso"

Findings are documented in BURNOUT3_EATRAX_HANDOFF.md (PHASE 2 RESULTS section).
"""
import sys, os, struct, array

SECTOR = 2048
SEG_VA, SEG_FO, SEG_FSZ = 0x00100000, 0x100, 0x3E2680   # SLUS_210.50 single PT_LOAD
GP = 0x004E8670                                          # discovered $gp value

def find_slus_in_iso(iso):
    """Locate SLUS_210.50 via ISO9660 directory scan."""
    po = 16 * SECTOR
    rlba = struct.unpack_from("<I", iso, po + 158)[0]
    rsz  = struct.unpack_from("<I", iso, po + 166)[0]
    base, end, p = rlba * SECTOR, rlba * SECTOR + rsz, rlba * SECTOR
    while p < end:
        ln = iso[p]
        if ln == 0:
            p = ((p // SECTOR) + 1) * SECTOR; continue
        nl = iso[p + 32]
        name = bytes(iso[p + 33:p + 33 + nl]).split(b";")[0]
        if name == b"SLUS_210.50":
            lba = struct.unpack_from("<I", iso, p + 2)[0]
            sz  = struct.unpack_from("<I", iso, p + 10)[0]
            return lba * SECTOR, sz
        p += ln
    raise SystemExit("SLUS_210.50 not found in ISO")

REG = ["$zero","$at","$v0","$v1","$a0","$a1","$a2","$a3","$t0","$t1","$t2","$t3",
       "$t4","$t5","$t6","$t7","$s0","$s1","$s2","$s3","$s4","$s5","$s6","$s7",
       "$t8","$t9","$k0","$k1","$gp","$sp","$fp","$ra"]
RT = {0:"sll",2:"srl",3:"sra",4:"sllv",6:"srlv",7:"srav",8:"jr",9:"jalr",16:"mfhi",
      18:"mflo",24:"mult",25:"multu",26:"div",27:"divu",32:"add",33:"addu",34:"sub",
      35:"subu",36:"and",37:"or",38:"xor",39:"nor",42:"slt",43:"sltu",10:"movz",
      11:"movn",45:"daddu",0x2D:"daddu"}
IT = {4:"beq",5:"bne",6:"blez",7:"bgtz",8:"addi",9:"addiu",10:"slti",11:"sltiu",
      12:"andi",13:"ori",14:"xori",15:"lui",32:"lb",33:"lh",34:"lwl",35:"lw",36:"lbu",
      37:"lhu",38:"lwr",40:"sb",41:"sh",43:"sw",49:"lwc1",57:"swc1",53:"ldc1",61:"sdc1",
      0x1E:"lq",0x1F:"sq",55:"ld",63:"sd",25:"daddiu"}

class Elf:
    def __init__(self, data): self.d = data
    def va2fo(self, va): return SEG_FO + (va - SEG_VA)
    def inseg(self, va): return SEG_VA <= va < SEG_VA + SEG_FSZ
    def r32(self, va): return struct.unpack_from("<I", self.d, self.va2fo(va))[0]
    def r8(self, va): return self.d[self.va2fo(va)]
    def cstr(self, va, enc="ascii"):
        fo = self.va2fo(va); out = bytearray()
        while fo < len(self.d) and self.d[fo] != 0 and len(out) < 48:
            out.append(self.d[fo]); fo += 1
        return out.decode(enc, "replace")

    def disasm(self, start, max_ins=120):
        d = self.d; luihi = {}; va = start; printed = 0
        print(f"\n===== func @ 0x{start:08X} =====")
        while printed < max_ins and self.inseg(va):
            w = self.r32(va); op = w >> 26
            line = f"0x{va:08X}: {w:08X}  "; ann = ""; ended = False
            if op == 0:
                fn = w & 0x3F; rs = (w>>21)&0x1F; rt = (w>>16)&0x1F; rd = (w>>11)&0x1F; sh = (w>>6)&0x1F
                mn = RT.get(fn, ".word")
                if w == 0: line += "nop"
                elif fn in (0,2,3): line += f"{mn} {REG[rd]},{REG[rt]},{sh}"
                elif fn == 8: line += f"{mn} {REG[rs]}"; ended = (rs == 31)
                elif fn == 9: line += f"{mn} {REG[rd]},{REG[rs]}"
                elif fn in (16,18): line += f"{mn} {REG[rd]}"
                elif fn in (24,25,26,27): line += f"{mn} {REG[rs]},{REG[rt]}"
                else: line += f"{mn} {REG[rd]},{REG[rs]},{REG[rt]}"
            elif op in (2,3):
                tgt = ((va+4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
                line += f"{'j' if op==2 else 'jal'} 0x{tgt:08X}"
            elif op == 1:
                rs = (w>>21)&0x1F; rt = (w>>16)&0x1F; imm = w & 0xFFFF
                t = va+4 + ((imm-0x10000 if imm&0x8000 else imm) << 2)
                line += f"{ {0:'bltz',1:'bgez',16:'bltzal',17:'bgezal'}.get(rt,'regimm') } {REG[rs]},0x{t:08X}"
            else:
                rs = (w>>21)&0x1F; rt = (w>>16)&0x1F; imm = w & 0xFFFF
                mn = IT.get(op, f".word_{op:02x}"); simm = imm-0x10000 if imm&0x8000 else imm
                if op == 15:
                    line += f"lui {REG[rt]},0x{imm:04X}"; luihi[rt] = imm
                elif op in (4,5):
                    line += f"{mn} {REG[rs]},{REG[rt]},0x{va+4+(simm<<2):08X}"
                elif op in (6,7):
                    line += f"{mn} {REG[rs]},0x{va+4+(simm<<2):08X}"
                elif op in (8,9,10,11,12,13,14,25):
                    line += f"{mn} {REG[rt]},{REG[rs]},{simm}"
                    if rs in luihi and op in (9,13,25):
                        addr = ((luihi[rs]<<16)+simm)&0xFFFFFFFF if op != 13 else (luihi[rs]<<16)|imm
                        ann = f"  ; =0x{addr:08X}"
                        if self.inseg(addr):
                            st = self.cstr(addr)
                            if st and all(32 <= ord(c) < 127 for c in st[:3]): ann += f'  "{st}"'
                else:
                    line += f"{mn} {REG[rt]},{simm}({REG[rs]})"
                    if rs in luihi:
                        addr = ((luihi[rs]<<16)+simm)&0xFFFFFFFF; ann = f"  ; =0x{addr:08X}"
                        if self.inseg(addr):
                            st = self.cstr(addr)
                            if st and all(32 <= ord(c) < 127 for c in st[:3]): ann += f'  "{st}"'
            print(line + ann); printed += 1; va += 4
            if ended:
                print(f"0x{va:08X}: {self.r32(va):08X}  (delay slot)"); break

def main():
    iso_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Downloads/Burnout 3 - Takedown (USA).iso")
    iso = open(iso_path, "rb").read()
    off, size = find_slus_in_iso(iso)
    print(f"SLUS_210.50 @ ISO 0x{off:X} (LBA {off//SECTOR}), size={size}")
    e = Elf(iso[off:off+size])

    print("\n=== metadata array @ 0x4A5600 (24-byte entries) ===")
    for i in (0, 1, 40, 43):
        idx, _, tid, aid, arid, fl = struct.unpack_from("<IIIIII", e.d, e.va2fo(0x4A5600 + i*24))
        print(f"  entry {i:2d}: track={idx} title_id={tid} album_id={aid} artist_id={arid} flags=0x{fl:X}")
    print(f"  master count @0x4A5A24 = {e.r32(0x4A5A24)}")
    print(f"  array base ptr @0x4A5A6C -> 0x{e.r32(0x4A5A6C):08X}")
    print(f"\n=== path pointer table @0x4E1F08 (read via $gp=0x{GP:08X}) ===")
    for k in range(6):
        p = e.r32(0x4E1F08 + k*4)
        print(f"  [{k}] -> 0x{p:08X}  \"{e.cstr(p)}\"")

    # Key functions: path builders, construct, state machine, string resolver
    for fn in (0x003FBC20, 0x003FC2E0, 0x003FCD20, 0x003FC700):
        e.disasm(fn, 90)

if __name__ == "__main__":
    main()
