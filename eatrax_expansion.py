#!/usr/bin/env python3
"""
EA TRAX expansion engine (HostFS) — add N full-length custom tracks beyond the
original 44, with unlimited custom (romanized) names. Consolidates everything proven
in research/: digit=track/22 hook, metadata-array relocation to the code cave,
GLOBALUS string-table relocation, full-length RWS building, romanization.

The GUI calls build_expansion(); nothing here touches the ISO — all output lands in
the HostFS folder (the extracted disc) + a PCSX2 .pnach.

In PCSX2 the user enables: [HostFS] + [ELF Code Cave] + [EATRAX expansion] (this pnach). The metadata
array lives in Nahelam's code cave (0x16B4F0) — big + validated, so it handles high track counts.
"""
import os, struct, subprocess, tempfile, shutil, importlib.util

# ---- constants (all verified) ----
SEG_VA, SEG_FO = 0x00100000, 0x100
HOOK_VAS = [0x003FBCD0, 0x003FC38C]                  # the digit block in both Prepare funcs
HOOK = [0x8E0200D8, 0x24010016, 0x0041001B, 0x00001012, 0xAE0200E0,
        0x00024040, 0x3C01004D, 0x2421EA78, 0x00284021]   # digit = track/22 ; &digit[track/22]
DIGITS_VA = 0x004CEA78
DIGITS = b''.join(bytes([0x30 + d, 0]) for d in range(10))  # "0".."9" null-term, stride 2 (digits 0-9 => up to 10 files)
COUNT_VA = 0x004A5A24
BASEPTR_VA = 0x004A5A6C
META_VA = 0x004A5600
CAVE = 0x0016B4F0                                    # Nahelam code cave (legacy; needed [ELF Code Cave])
META_NEW_VA = 0x00485894                             # free ELF zero-run (~6996B = 291 entries) -> NO cheat

# [HostFS] patch — redirects the game's cdrom0: file I/O to a host folder (the gtfs*.irx modules it
# uses are Criterion's, already present in every retail ISO). Patch authored by Nahelam
# (https://github.com/Nahelam/PCSX2-HostFS-Patches); written out so users don't fetch it manually.
HOSTFS_PNACH = """gametitle=Burnout 3: Takedown (SLUS-21050) [NTSC-U/C]

[HostFS]
author=Nehalem
description=Load game files directly from a folder

// jal to stub in _sceSifLoadModule
patch=0,EE,20113DB8,extended,0C047C88

// jal to stub in sceSifRebootIop
patch=0,EE,20114574,extended,0060202D
patch=0,EE,20114578,extended,0C047C88
patch=0,EE,2011457C,extended,0200282D
patch=0,EE,20114580,extended,10000005

// Make room in sceCdInit
patch=0,EE,2011F218,extended,03E00008
patch=0,EE,2011F21C,extended,00000000

// Path patching stub (cdrom -> host)
patch=0,EE,2011F220,extended,3C021797
patch=0,EE,2011F224,extended,8CAD000C
patch=0,EE,2011F228,extended,3442979D
patch=0,EE,2011F22C,extended,00021478
patch=0,EE,2011F230,extended,64427473
patch=0,EE,2011F234,extended,00021438
patch=0,EE,2011F238,extended,64426F68
patch=0,EE,2011F23C,extended,FC820000
patch=0,EE,2011F240,extended,80A30008
patch=0,EE,2011F244,extended,1060001F
patch=0,EE,2011F248,extended,00000000
patch=0,EE,2011F24C,extended,3C0C5346
patch=0,EE,2011F250,extended,24020008
patch=0,EE,2011F254,extended,24090010
patch=0,EE,2011F258,extended,258C5447
patch=0,EE,2011F25C,extended,240A003B
patch=0,EE,2011F260,extended,1000000B
patch=0,EE,2011F264,extended,240B005C
patch=0,EE,2011F268,extended,106A0017
patch=0,EE,2011F26C,extended,24420001
patch=0,EE,2011F270,extended,146B0002
patch=0,EE,2011F274,extended,00A24021
patch=0,EE,2011F278,extended,2403002F
patch=0,EE,2011F27C,extended,A0E30000
patch=0,EE,2011F280,extended,00403025
patch=0,EE,2011F284,extended,81030000
patch=0,EE,2011F288,extended,1060000F
patch=0,EE,2011F28C,extended,00000000
patch=0,EE,2011F290,extended,00823821
patch=0,EE,2011F294,extended,1449FFF4
patch=0,EE,2011F298,extended,00403025
patch=0,EE,2011F29C,extended,15ACFFF2
patch=0,EE,2011F2A0,extended,00000000
patch=0,EE,2011F2A4,extended,3C022C29
patch=0,EE,2011F2A8,extended,64422497
patch=0,EE,2011F2AC,extended,00021478
patch=0,EE,2011F2B0,extended,64425453
patch=0,EE,2011F2B4,extended,00021438
patch=0,EE,2011F2B8,extended,64424F48
patch=0,EE,2011F2BC,extended,03E00008
patch=0,EE,2011F2C0,extended,FC820010
patch=0,EE,2011F2C4,extended,24060008
patch=0,EE,2011F2C8,extended,00862021
patch=0,EE,2011F2CC,extended,03E00008
patch=0,EE,2011F2D0,extended,A0800000
"""
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

# ---- pnach ----
def _gen_pnach(entries, count, log):
    # HostFS uses Nahelam's code cave (0x16B4F0, ~205 KB, validated) for the metadata array — it has
    # room for many tracks and is known-safe. (The free zero-run 0x485894 is only proven for the <=44 of
    # the portable build; it's too small/risky for big HostFS counts.) HostFS already uses cheats, so the
    # extra [ELF Code Cave] is fine.
    def w(addr, val): return f"patch=1,EE,{0x20000000 | addr:08X},extended,{val:08X}"
    L = ["gametitle=Burnout 3: Takedown (SLUS-21050) [NTSC-U/C]", "",
         "[EATRAX expansion]", "author=burnout3_gui",
         "description=N custom full-length tracks (digit hook + relocated metadata + GLOBALUS) - REQUIRES [ELF Code Cave]", ""]
    for base in HOOK_VAS:
        L.append(f"// digit hook @0x{base:08X}")
        L += [w(base + i * 4, x) for i, x in enumerate(HOOK)]
    L.append("// digit strings 0-9 @0x4CEA78")
    for k in range(0, len(DIGITS), 4):
        L.append(w(DIGITS_VA + k, struct.unpack_from("<I", DIGITS, k)[0]))
    L.append("// master count + metadata base pointer -> Nahelam code cave (needs [ELF Code Cave])")
    L += [w(COUNT_VA, count), w(BASEPTR_VA, CAVE)]
    L.append(f"// metadata array ({len(entries)} entries) @0x{CAVE:X}")
    flat = [v for e in entries for v in e]
    L += [w(CAVE + k * 4, v) for k, v in enumerate(flat)]
    return "\n".join(L) + "\n"

# ---- orchestrator ----
def build_expansion(hostfs_dir, new_tracks, cheats_dir=None, log=print, progress=None):
    """new_tracks = [{'song':path,'title':str,'artist':str,'album':str}, ...]
    Builds _eatraxN.rws (full-length) + rebuilt globalus.bin into hostfs_dir, writes the pnach."""
    import burnout3_gui as b3
    tracks_dir = os.path.join(hostfs_dir, "tracks")
    base_path = os.path.join(tracks_dir, "_eatrax1.rws")
    elf_path = os.path.join(hostfs_dir, "slus_210.50")
    glob_path = os.path.join(hostfs_dir, "data", "globalus.bin")
    for p in (base_path, elf_path, glob_path):
        if not os.path.isfile(p):
            raise RuntimeError(f"HostFS folder missing {p} — point to the extracted-disc folder")
    N = len(new_tracks)
    if N == 0:
        raise RuntimeError("No new tracks to add")
    log(f"Adding {N} track(s): internal 44..{43+N} (UI 45..{45+N-1})")

    base = open(base_path, "rb").read()
    elf = open(elf_path, "rb").read()
    orig = [list(struct.unpack_from("<IIIIII", elf, _fo(META_VA + i * 24))) for i in range(44)]

    # group into files (22/file) and build each full-length
    files = {}
    for i, t in enumerate(new_tracks):
        gi = 44 + i; files.setdefault(gi // TRACKS_PER_FILE, {})[gi % TRACKS_PER_FILE] = t["song"]
    tmp = tempfile.mkdtemp(prefix="eatrax_")
    try:
        for fidx, songs in sorted(files.items()):
            log(f"building _eatrax{fidx}.rws ({len(songs)} custom)...")
            if progress: progress(f"Encoding _eatrax{fidx}...")
            out = _build_eatrax_file(b3, base, songs, tmp, log)
            open(os.path.join(tracks_dir, f"_eatrax{fidx}.rws"), "wb").write(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # GLOBALUS names (romanized), 3 per track: title, album, artist (the on-disk order)
    if progress: progress("Rebuilding names (GLOBALUS)...")
    strings = []
    for t in new_tracks:
        strings += [romanize(t.get("title", "")), romanize(t.get("album", "")), romanize(t.get("artist", ""))]
    base_id = _rebuild_globalus(glob_path, strings, log)

    # metadata array: 44 originals (flags 0xF) + new entries -> the new string ids
    entries = [[e[0], 0, e[2], e[3], e[4], 0x0F] for e in orig]
    for i in range(N):
        b = base_id + i * 3
        entries.append([44 + i, 0, b, b + 1, b + 2, 0x0F])
    pnach = _gen_pnach(entries, 44 + N, log)
    out_pnach = None
    if cheats_dir and os.path.isdir(cheats_dir):
        out_pnach = os.path.join(cheats_dir, "BEBF8793_eatrax_expansion.pnach")
        open(out_pnach, "w").write(pnach)
        log(f"  pnach -> {out_pnach}")
    return {"pnach": pnach, "pnach_path": out_pnach, "count": 44 + N,
            "files": sorted(files), "first_id": base_id}


# ---- unified orchestrator: the WHOLE soundtrack (replace any of 44 + add beyond) ----
def _pristine(path, log):
    """Return the pristine bytes of an _eatrax file, backing it up to .orig on first use."""
    o = path + ".orig"
    if not os.path.exists(o):
        shutil.copy2(path, o); log(f"  backed up {os.path.basename(path)} -> .orig (pristine)")
    return open(o, "rb").read()

def build_soundtrack(hostfs_dir, slots, cheats_dir=None, log=print, progress=None):
    """slots[g] = None (keep original game track, g<44 only) OR
                  {'song':path,'title','artist','album'} (custom, full-length).
    Builds the COMPLETE soundtrack: replace any of the 44 + add beyond, all full-length via
    HostFS. Always rebuilds from pristine .orig backups, so it's idempotent across runs."""
    import burnout3_gui as b3
    tracks_dir = os.path.join(hostfs_dir, "tracks")
    elf_path = os.path.join(hostfs_dir, "slus_210.50")
    glob_path = os.path.join(hostfs_dir, "data", "globalus.bin")
    for p in (tracks_dir, elf_path, glob_path):
        if not os.path.exists(p):
            raise RuntimeError(f"HostFS folder missing {p} — point to the extracted-disc folder")
    N = len(slots)
    if N == 0:
        raise RuntimeError("No tracks")
    custom = [g for g, s in enumerate(slots) if s]
    if not custom:
        raise RuntimeError("Assign at least one song (every slot is still the original)")
    for g, s in enumerate(slots):
        if s is None and g >= 44:
            raise RuntimeError(f"Slot {g+1} is empty — slots beyond 44 must have a song")

    elf = open(elf_path, "rb").read()
    orig = [list(struct.unpack_from("<IIIIII", elf, _fo(META_VA + i * 24))) for i in range(44)]
    log(f"Soundtrack: {N} slots, {len(custom)} custom ({N-len(custom)} original kept)")

    # group custom slots by file
    files = {}
    for g in custom:
        files.setdefault(g // TRACKS_PER_FILE, {})[g % TRACKS_PER_FILE] = slots[g]["song"]

    max_file = (N - 1) // TRACKS_PER_FILE
    tmp = tempfile.mkdtemp(prefix="eatrax_")
    try:
        for f in range(max_file + 1):
            songs = files.get(f, {})
            if f < 2 and not songs:
                continue                                  # file 0/1 untouched -> leave original on disk
            if progress: progress(f"Building _eatrax{f}.rws...")
            log(f"building _eatrax{f}.rws ({len(songs)} custom)...")
            base = _pristine(os.path.join(tracks_dir, f"_eatrax{f}.rws"), log) if f < 2 \
                   else _pristine(os.path.join(tracks_dir, "_eatrax1.rws"), log)   # template for new files
            out = _build_eatrax_file(b3, base, songs, tmp, log)
            open(os.path.join(tracks_dir, f"_eatrax{f}.rws"), "wb").write(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # GLOBALUS: 3 romanized strings per custom slot (title, album, artist = on-disk order)
    if progress: progress("Rebuilding names (GLOBALUS)...")
    strings = []
    for g in custom:
        s = slots[g]
        strings += [romanize(s.get("title", "")), romanize(s.get("album", "")), romanize(s.get("artist", ""))]
    base_id = _rebuild_globalus(glob_path, strings, log)

    # metadata array (N entries): custom -> new ids, keep -> original ids
    entries = []; ci = 0
    for g in range(N):
        if slots[g]:
            b = base_id + ci * 3; ci += 1
            entries.append([g, 0, b, b + 1, b + 2, 0x0F])
        else:
            e = orig[g]; entries.append([g, 0, e[2], e[3], e[4], 0x0F])
    pnach = _gen_pnach(entries, N, log)
    out_pnach = hostfs_pnach = None
    if cheats_dir and os.path.isdir(cheats_dir):
        out_pnach = os.path.join(cheats_dir, "BEBF8793_eatrax_expansion.pnach")
        open(out_pnach, "w").write(pnach)
        log(f"  pnach -> {out_pnach}")
        hostfs_pnach = os.path.join(cheats_dir, "BEBF8793_hostfs.pnach")   # the [HostFS] loader (Nahelam)
        open(hostfs_pnach, "w").write(HOSTFS_PNACH)
        log(f"  pnach -> {hostfs_pnach}")
    return {"pnach": pnach, "pnach_path": out_pnach, "hostfs_pnach_path": hostfs_pnach, "count": N,
            "files": sorted(files), "custom": len(custom), "first_id": base_id}
