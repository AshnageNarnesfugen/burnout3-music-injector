#!/usr/bin/env python3
# RE tool: find the EA-TRAX track-count cap (66) + the levers to raise it. See memory eatrax-expansion-project.
import struct, sys

ELF = "/home/dreadashes/Downloads/SLUS_210.50"
TARGETS = {0x4A5A24: "COUNT", 0x4A5A6C: "BASEPTR", 0x4A5600: "META_ARRAY"}

data = open(ELF, "rb").read()
# --- parse ELF32 LE program headers -> VA<->offset segments ---
assert data[:4] == b"\x7fELF"
e_phoff = struct.unpack_from("<I", data, 0x1C)[0]
e_phentsize = struct.unpack_from("<H", data, 0x2A)[0]
e_phnum = struct.unpack_from("<H", data, 0x2C)[0]
segs = []
for i in range(e_phnum):
    off = e_phoff + i*e_phentsize
    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz = struct.unpack_from("<IIIIII", data, off)
    if p_type == 1 and p_filesz:  # PT_LOAD
        segs.append((p_vaddr, p_offset, p_filesz))
def va2off(va):
    for v, o, sz in segs:
        if v <= va < v+sz:
            return o + (va - v)
    return None
def off2va(o):
    for v, off, sz in segs:
        if off <= o < off+sz:
            return v + (o - off)
    return None

REG = ["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7",
       "s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra"]
def s16(x): return x-0x10000 if x & 0x8000 else x

def decode(w, addr):
    op = w >> 26
    rs = (w>>21)&31; rt=(w>>16)&31; rd=(w>>11)&31; sa=(w>>6)&31
    imm = w & 0xFFFF; simm = s16(imm)
    funct = w & 0x3F
    tgt = (addr+4 & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
    if w == 0: return ("nop","")
    if op == 0:
        F = {0x20:"add",0x21:"addu",0x22:"sub",0x23:"subu",0x24:"and",0x25:"or",0x26:"xor",
             0x27:"nor",0x2a:"slt",0x2b:"sltu",0x00:"sll",0x02:"srl",0x03:"sra",
             0x04:"sllv",0x06:"srlv",0x07:"srav",0x08:"jr",0x09:"jalr",0x10:"mfhi",
             0x12:"mflo",0x18:"mult",0x19:"multu",0x1a:"div",0x1b:"divu"}
        m = F.get(funct, "r?%02x"%funct)
        if m in ("sll","srl","sra"): return (m, f"{REG[rd]},{REG[rt]},{sa}")
        if m == "jr": return (m, REG[rs])
        if m in ("mult","multu","div","divu"): return (m, f"{REG[rs]},{REG[rt]}")
        if m in ("mfhi","mflo"): return (m, REG[rd])
        return (m, f"{REG[rd]},{REG[rs]},{REG[rt]}")
    OPS = {0x08:"addi",0x09:"addiu",0x0a:"slti",0x0b:"sltiu",0x0c:"andi",0x0d:"ori",
           0x0e:"xori",0x0f:"lui",0x23:"lw",0x21:"lh",0x25:"lhu",0x20:"lb",0x24:"lbu",
           0x2b:"sw",0x29:"sh",0x28:"sb",0x04:"beq",0x05:"bne",0x06:"blez",0x07:"bgtz",
           0x01:"regimm",0x02:"j",0x03:"jal"}
    m = OPS.get(op, "op?%02x"%op)
    if m == "lui": return (m, f"{REG[rt]},0x{imm:x}")
    if m in ("addi","addiu","slti","sltiu","andi","ori","xori"):
        return (m, f"{REG[rt]},{REG[rs]},{simm if m in('addi','addiu','slti') else imm}")
    if m in ("lw","lh","lhu","lb","lbu","sw","sh","sb"):
        return (m, f"{REG[rt]},{simm}({REG[rs]})", rs, simm, rt)
    if m in ("beq","bne"): return (m, f"{REG[rs]},{REG[rt]},0x{addr+4+(simm<<2)&0xffffffff:x}")
    if m in ("blez","bgtz"): return (m, f"{REG[rs]},0x{addr+4+(simm<<2)&0xffffffff:x}")
    if m == "regimm":
        sub={0:"bltz",1:"bgez",16:"bltzal",17:"bgezal"}.get(rt,"ri?")
        return (sub, f"{REG[rs]},0x{addr+4+(simm<<2)&0xffffffff:x}")
    if m in ("j","jal"): return (m, f"0x{tgt:x}")
    return (m, "")

# --- scan code segs, track lui regs, find loads/stores of TARGETS ---
hits = []  # (va_of_access, target_name)
for v, o, sz in segs:
    if v > 0x600000: continue
    luihi = {}  # reg -> hi value set by lui
    base = v
    avail = max(0, min(sz, len(data)-o))
    words = avail // 4
    for i in range(words):
        addr = v + i*4
        w = struct.unpack_from("<I", data, o + i*4)[0]
        op = w >> 26; rt=(w>>16)&31; rs=(w>>21)&31; imm=w&0xFFFF
        if op == 0x0f:  # lui
            luihi[rt] = imm << 16
            continue
        d = decode(w, addr)
        if len(d) >= 5 and d[0] in ("lw","lh","lhu","lb","lbu","sw","sh","sb"):
            _, _, brs, boff, _ = d
            if brs in luihi:
                ea = (luihi[brs] + boff) & 0xFFFFFFFF
                if ea in TARGETS:
                    hits.append((addr, TARGETS[ea], d[0]))
        # addiu computing full addr (reg = lui_reg + imm) keeps tracking
        if d[0] == "addiu" and rs in luihi:
            ea = (luihi[rs] + s16(imm)) & 0xFFFFFFFF
            if ea in TARGETS:
                hits.append((addr, TARGETS[ea]+"(addr)", d[0]))
            luihi[rt] = ea  # propagate computed pointer base
        elif op != 0x0f and rt < 32 and d[0] in ("add","addu","sub","subu","and","or","xor","slt","sltu","lw","lhu","lbu","lh","lb","andi","ori","xori","sltiu","slti"):
            luihi.pop(rt, None)  # reg clobbered, forget lui
        if d[0] in ("jal","j","jr","jalr"):
            luihi.clear()

print(f"segments: {[(hex(v),hex(o),hex(sz)) for v,o,sz in segs]}")
print(f"\n=== {len(hits)} accesses to COUNT/BASEPTR/META ===")
for addr, name, mn in hits:
    print(f"  0x{addr:08x}  {mn:4} -> {name}")

# --- dump disasm window around each COUNT/BASEPTR access ---
def dump(center, before=14, after=30):
    o = va2off(center)
    print(f"\n----- context @0x{center:08x} -----")
    for k in range(-before, after):
        a = center + k*4
        oo = va2off(a)
        if oo is None: continue
        w = struct.unpack_from("<I", data, oo)[0]
        d = decode(w, a)
        mark = " <==" if a == center else ""
        flag = ""
        if d[0] in ("slti","sltiu","slt","sltu","addiu","andi","li"):
            flag = "   *imm*"
        print(f"  0x{a:08x}: {w:08x}  {d[0]:7} {d[1]}{flag}{mark}")

seen=set()
for addr, name, mn in hits:
    if name.startswith("META"): continue
    if addr in seen: continue
    seen.add(addr)
    dump(addr)

# --- region-wide: constants 44..256 + all comparisons, in the EATRAX code 0x3f0000..0x400000 ---
print("\n\n############ EATRAX region scan 0x3f0000-0x400000 ############")
lo, hi = 0x3f0000, 0x400000
o0 = va2off(lo)
luihi = {}
for i in range((hi-lo)//4):
    a = lo + i*4
    oo = va2off(a)
    if oo is None: continue
    w = struct.unpack_from("<I", data, oo)[0]
    d = decode(w, a)
    op = w>>26; rt=(w>>16)&31; imm=w&0xFFFF
    note=""
    if d[0] == "addiu" and ((w>>21)&31)==0 and 44 <= s16(imm) <= 256:
        note = f"   <<<< CONST {s16(imm)}"
    if d[0] in ("slti","sltiu") and 44 <= (s16(imm) if d[0]=='slti' else imm) <= 256:
        note = f"   <<<< CMP imm={s16(imm) if d[0]=='slti' else imm}"
    if d[0] in ("andi",) and imm in (0x3f,0x7f,0xff): note=f"   (mask {imm:#x})"
    if note:
        print(f"  0x{a:08x}: {w:08x}  {d[0]:7} {d[1]}{note}")
