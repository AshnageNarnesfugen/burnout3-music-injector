#!/usr/bin/env python3
"""
EA-TRAX helpers shared by the portable ISO builder (research/build_portable_iso.py): the
digit=track/22 hook constants + ELF segment math, romanization, full-length RWS (.RWS) building,
and GLOBALUS string-table rebuild/overwrite.

(The old HostFS path — build_soundtrack + the [HostFS]/[EATRAX expansion] pnach — was removed once
the portable ISO learned to bake the whole expansion into the disc; see build_portable_iso.py.)
"""
import os, struct, subprocess, tempfile, shutil, importlib.util

# ---- constants (all verified) ----
SEG_VA, SEG_FO = 0x00100000, 0x100
HOOK_VAS = [0x003FBCD0, 0x003FC38C]                  # the digit block in both Prepare funcs
HOOK = [0x8E0200D8, 0x24010016, 0x0041001B, 0x00001012, 0xAE0200E0,
        0x00024040, 0x3C01004D, 0x2421EA78, 0x00284021]   # digit = track/22 ; &digit[track/22]
DIGITS_VA = 0x004CEA78
COUNT_VA = 0x004A5A24
BASEPTR_VA = 0x004A5A6C
META_VA = 0x004A5600
TRACKS_PER_FILE = 22

def _fo(va): return SEG_FO + (va - SEG_VA)

# ---- romanization (research/romanize.py) ----
_rz = None
def romanize(text):
    global _rz
    if not text:
        return ""
    if _rz is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research", "romanize.py")
        spec = importlib.util.spec_from_file_location("romanize", p)
        _rz = importlib.util.module_from_spec(spec); spec.loader.exec_module(_rz)
    return _rz.romanize(text)

# ---- RWS helpers ----
_ENTRY, _SW, _OW = 32, 24, 28
def _find_table(hdr, hsize):
    he = 24 + hsize
    for scan in range(24, he - 32, 4):
        cs = struct.unpack_from("<I", hdr, scan)[0]; co = struct.unpack_from("<I", hdr, scan + 4)[0]
        if co == 0 and 500000 < cs < 50000000:
            e0 = scan - _SW
            if e0 < 24: continue
            e1s = struct.unpack_from("<I", hdr, e0 + _ENTRY + _SW)[0]
            e1o = struct.unpack_from("<I", hdr, e0 + _ENTRY + _OW)[0]
            if e1o == cs and 500000 < e1s < 50000000:
                return e0
    raise RuntimeError("RWS track table not found")

def _encode_full(b3, song, tmp, tag, log):
    raw = os.path.join(tmp, f"{tag}.raw")
    loud = b3._loudnorm_filter(b3.LOUDNORM_TARGET, b3._loudnorm_measure(song, b3.LOUDNORM_TARGET))
    r = subprocess.run(["ffmpeg", "-y", "-i", song, "-af", f"{loud},{b3.AUDIO_RESAMPLE_FILTER}",
                        "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "32000", "-ac", "2", raw],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(raw) or os.path.getsize(raw) == 0:
        raise RuntimeError(f"ffmpeg failed for {song}")
    pcm = open(raw, "rb").read()
    n_per_ch = (len(pcm) // 2) // 2
    size = ((n_per_ch + 7167) // 7168) * 8192        # full song, superblock-aligned (no truncation)
    return b3.encode_psx_adpcm_sized(pcm, size), size

def _build_eatrax_file(b3, base, songs_by_local, tmp, log):
    """Return a full-length _eatraxN.rws: base structure, chosen local slots replaced."""
    hsize = struct.unpack_from("<I", base, 16)[0]
    W = b3.InjectionWorker.__new__(b3.InjectionWorker)
    tracks, _, _ = W._parse_rws_tracks(base)
    n = len(tracks)
    hdr = bytearray(base[:24 + hsize])
    ft = _find_table(hdr, hsize)
    audio = []
    for i in range(n):
        if i in songs_by_local:
            a, sz = _encode_full(b3, songs_by_local[i], tmp, f"t{i}", log)
            log(f"    local {i}: {os.path.basename(songs_by_local[i])} -> {sz//1024}KB (~{b3.adpcm_slot_duration(sz):.0f}s, full)")
            audio.append(a)
        else:
            off, sz = tracks[i]; audio.append(base[off:off + sz])
    cum = 0
    for i in range(n):
        eo = ft + i * _ENTRY
        struct.pack_into("<I", hdr, eo + _SW, len(audio[i]))
        struct.pack_into("<I", hdr, eo + _OW, cum); cum += len(audio[i])
    struct.pack_into("<I", hdr, 4, hsize + 12 + 12 + cum)
    out = bytearray(hdr) + struct.pack("<III", 0x080F, cum, 0x1C020009)
    for a in audio:
        out += a
    return bytes(out)

# ---- GLOBALUS string-table relocation ----
def _rebuild_globalus(path, new_strings, log):
    """Append a bigger pointer table + the new strings; update header count/table_offset.
    Idempotent: rebuilds from a pristine backup each call. Returns the first new string id."""
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
    g = bytearray(open(backup, "rb").read())          # always start from pristine
    count = struct.unpack_from("<I", g, 8)[0]
    tbl = struct.unpack_from("<I", g, 0xC)[0]
    new_tbl_off = (len(g) + 3) & ~3
    total = count + len(new_strings)
    new_str_off = new_tbl_off + total * 4
    blob = bytearray(); offs = []
    for s in new_strings:
        offs.append(new_str_off + len(blob))
        blob += s.encode("utf-16-le") + b"\x00\x00"
    table = bytearray()
    for i in range(count):
        table += struct.pack("<I", struct.unpack_from("<I", g, tbl + i * 4)[0])
    for o in offs:
        table += struct.pack("<I", o)
    out = bytearray(g) + b"\x00" * (new_tbl_off - len(g)) + table + blob
    struct.pack_into("<I", out, 8, total)             # count
    struct.pack_into("<I", out, 0xC, new_tbl_off)     # table offset
    open(path, "wb").write(out)
    log(f"  globalus.bin rebuilt: +{len(new_strings)} strings (ids {count}..{total-1}), {len(out)} bytes")
    return count

def globalus_overwrite(g_bytes, overrides, log=print):
    """Return new globalus bytes that REPLACE the text of specific existing string ids (overrides =
    {string_id: text}), keeping the count unchanged. Appends each new string at the end and repoints
    only that id's table entry. Lets the portable ISO rename tracks WITHOUT editing the ELF metadata,
    so the game CRC stays BEBF8793 and PCSX2's per-game graphics fixes still apply."""
    g = bytearray(g_bytes)
    count = struct.unpack_from("<I", g, 8)[0]
    tbl = struct.unpack_from("<I", g, 0xC)[0]
    add = bytearray(); base = len(g)
    for i, t in overrides.items():
        if not (0 <= i < count):
            continue
        struct.pack_into("<I", g, tbl + i * 4, base + len(add))   # repoint id -> appended string
        add += t.encode("utf-16-le") + b"\x00\x00"
    log(f"  globalus: overwrote {len(overrides)} string id(s) in place (count {count} unchanged, ELF untouched)")
    return bytes(g) + bytes(add)
