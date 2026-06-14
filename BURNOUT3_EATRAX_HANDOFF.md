# Burnout 3 EA TRAX Expansion — Project Handoff

> Paste this whole document into Claude Code when resuming. It contains the full
> state, everything tried, what works, what doesn't, and the next concrete steps.

## Goal

Add **N new music tracks** (20+, full-length, arbitrary size) to **Burnout 3:
Takedown** (PS2). The game ships with 44 EA TRAX tracks; we want to extend that.

## Target / Environment

- Game: **Burnout 3: Takedown, NTSC-U (USA)**, ELF name `SLUS_210.50`, **CRC `BEBF8793`**
  (PCSX2 CRC = XOR of all u32 words in the ELF, verified = BEBF8793)
- ISO: **`~/burnout isos/Burnout 3 - Takedown (USA).iso`** (2.87 GB) — moved out of ~/Downloads.
  Same folder has `Burnout3_eatrax2_test.iso` (Phase 3 test, hangs at loading) and
  `Burnout3_crashbreaker.iso`.
- Emulator: **PCSX2 (Flatpak)** — `net.pcsx2.PCSX2`
  - save states: `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/sstates/`
  - cheats/pnach: `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/cheats/`
- Shell: **fish** (no bash heredocs; user prefers one-liners or .py files)
- Patching language: **Python 3** (all ISO/ELF patching done in Python)
- Analysis: **Ghidra** (static), **PCSX2 debugger** (runtime), `eeMemory.bin` RAM dumps
- Repo: `~/Downloads/burnout3-music-injector` — GitHub `burnout3-music-injector`
  - Main tool: `burnout3_gui.py` (handles ADPCM encode, RWS creation, GLOBALUS.BIN
    string patching, ISO injection for the existing 44 tracks)

## RWS file format (fully reverse-engineered)

EA TRAX audio lives in `tracks/_EATrax0.rws` and `tracks/_EATrax1.rws` inside the
ISO (note: directory listing shows uppercase `_EATRAX0.RWS`). Each holds 22 tracks
(22 + 22 = 44 total).

RWS header layout (offsets from start of file):
```
0x0000  Container chunk: type=0x0000080D, size(u32 @0x04), ver=0x1C020009
0x000C  Header chunk:    type=0x0000080E, size=0x7DC, ver=0x1C020009
0x0018  Header payload:
        0x0018: sub_header_size = 0x069C
        0x0020: field = 0x10
        0x0038: tracks_per_file = 22 (0x16)   <- number of tracks in THIS file
        0x0058..0x0067: 16-byte per-file hash/ID (DIFFERENT per file, unknown algo)
        0x0068: "EATrax0\0" name string (16 bytes, 8-aligned)
0x0090  Track table: 22 entries, stride 0x20 (32 bytes) each:
        +0x00: size (u32)        <- bytes of audio for this track
        +0x04: offset (u32)      <- cumulative offset into audio data
        +0x08..0x1F: 24 bytes of runtime pointers (game fills these at load;
                     DIFFERENT per file, appear to be RAM addresses scaled to
                     file size)
0x07F4  Audio data chunk: type=0x0000080F, size(u32), ver=0x1C020009
        then the interleaved PS-ADPCM audio
```

Audio format: **PS-ADPCM, 32000 Hz, stereo**, interleaved in 2048-byte L/R blocks
(`L[2048] R[2048] L[2048] R[2048] ...`). PS-ADPCM frame = 16 bytes (1 byte
predictor/shift, 1 byte flags, 14 bytes = 28 nibble samples). Silence = all-zero
frames with flag=0x01 on the last frame of each channel.

Container size field (offset 0x04) = `(12 + header_size) + (12 + audio_data_size)`.
Verified: for EATRAX0, `(12+0x7DC)+(12+0x09528000) = 0x095287F4` ✓.

## ELF metadata layout (verified against eeMemory.bin RAM dump)

Song metadata array at RAM VA `0x004A5600`, **24-byte entries**:
```
+0x00: track_index (u32, 0-based)
+0x04: padding (u32, always 0 for real entries)
+0x08: string_id_title  (u32)
+0x0C: string_id_album  (u32)
+0x10: string_id_artist (u32)
+0x14: flags (u32) = 0x0F (enabled in all modes)
```

Entries 0-43 exist (44 tracks). Entry i is at `0x004A5600 + i*24`.
- Entries 0-39 use string IDs `477..596` (sequential, `477 + i*3`)
- Entries 40-43 use string IDs `3276..3287` (sequential, second region)

**Right after entry 43 (which ends at 0x004A5A20):**
```
0x004A5A20: 00 00 00 00          <- gap
0x004A5A24: 2C 00 00 00          <- MASTER TRACK COUNT = 44 (0x2C). THE key value.
0x004A5A28: 00 00 00 00
0x004A5A2C: "EATrax" UTF-16LE     <- "E\0A\0T\0r\0a\0x\0\0\0"
```

**CRITICAL OVERLAP:** The "master track count" at 0x004A5A24 is physically at
`entry_44_position + 4` (the padding slot of a hypothetical entry 44). Writing 46
there (via permanent ELF patch) made the UI show 46 tracks. Entry 44 metadata at
0x004A5A20 OVERWRITES part of the "EATrax" UTF-16 string (accepted tradeoff).
Entry 46 at 0x004A5A50 COLLIDES with a live data structure at 0x004A5A60, so only
2 new metadata slots are safely writable this way (tracks 45, 46).

ELF vaddr→file-offset: parse ELF32 program headers (PT_LOAD), then
`file_offset = p_offset + (vaddr - p_vaddr)`. (Standard; helper in scripts below.)

## File loader — the path-building string pool (KEY FINDING)

The game builds EA TRAX file paths from a **pointer table at VA `0x004E1F08`**:
```
VA 0x004E1F08 -> "tracks\"      (path prefix; backslash)
VA 0x004E1F0C -> "_EATrax"      (file stem)
VA 0x004E1F10 -> "EATraxD"      (separate; DJ/preview related?)
VA 0x004E1F14 -> "0"            (digit string, 8-byte aligned, at VA 0x004CEA78)
VA 0x004E1F18 -> "1"            (digit string, 8-byte aligned, at VA 0x004CEA80)
VA 0x004E1F1C -> ".rws"
VA 0x004E1F20 -> "BASLUS-21050" (save id)
VA 0x004E1F24 -> "view.ico"
VA 0x004E1F28 -> "Burnout 3"
```
Format string `"%s%s%s%s"` lives at VA 0x004CEA90. Path = prefix + stem + digit +
ext = `tracks\_EATrax0.rws`. There is NO "2" digit string — only "0" and "1".

Each digit string is accessed ONLY through this pointer table (verified: exactly
1 reference each, no `lui/addiu` direct loads anywhere in the ELF). The strings
"0" and "1" are at VA 0x004CEA78 and 0x004CEA80 respectively, each occupying 8
bytes (1 char + 7 null padding).

**LBAs are NOT hardcoded in the ELF** — searched for EATRAX0/1 LBAs (723121 /
799490) as u32, zero matches. Files are resolved via ISO9660 (cached at boot).

## What WORKS (verified in-game)

A one-liner pipeline produces an ISO where **tracks 45 and 46 appear in the EA
TRAX UI** without breaking anything else (intro video plays, tracks 1-44 play
audio). The pipeline:
1. Generate `_EATRAX2.RWS` (silence) by cloning EATRAX0's header, renaming
   internal "EATrax0"->"EATrax2", setting tracks_per_file, fixing sizes/offsets.
2. Inject it into the NFSUNDER demo-data zone (sacrificable space).
3. Rename the `NFSUNDER.ELF` directory entry IN-PLACE to `_EATRAX2.RWS;1`
   (both names are 14 chars => rec_len=48, so NO byte shifting needed).
4. Patch ELF: write metadata entries 44 & 45 (clone string IDs from entries
   40 & 41), set master track count = 46 at 0x004A5A24.

(See "Working one-liner" section at the bottom.)

## What does NOT work (dead ends — don't repeat these)

1. **Adding ISO9660 directory records by shifting bytes / writing into sector
   padding CORRUPTS THE GAME** (breaks intro video + ALL audio). The fix that
   works: only rename an EXISTING record in-place keeping rec_len identical.
   `NFSUNDER.ELF;1` and `_EATRAX2.RWS;1` are both 14 chars => safe swap.

2. **Overwriting NFSUNDER files `IOPRP280.IMG`, `IRX281A.BUN`, `IRX281B.BUN`
   breaks the game** — they're IOP modules loaded at boot. Sacrificable NFSUNDER
   files: `NFSUNDER.ELF`, `ZDIR.BIN`, `ZZDATA0.BIN`..`ZZDATA3.BIN`. Protect the
   three IOP modules.

3. **The "digit hack"** (changing the "1" string at VA 0x004CEA80 to "2" so the
   game builds `_EATrax2.rws` instead of `_EATrax1.rws`) **does NOT produce
   working audio** — even when `_EATRAX2.RWS` is a BYTE-EXACT clone of
   `_EATRAX1.RWS`. Symptom: boot OK, menu OK, tracks 1-22 play, but as soon as
   you scroll to track 23+ (the ones that should stream from the redirected file)
   ALL audio streaming dies permanently (no crash, just silence, doesn't recover
   even going back to tracks 1-22 or re-entering the menu). The audio subsystem
   enters a dead state. ROOT CAUSE STILL UNKNOWN — the engine does more than just
   open-file-by-path when loading an EA TRAX RWS, and that "more" is what breaks.

4. Pointing `_EATRAX2.RWS` at the SAME LBA as `_EATRAX1.RWS` (shared data, alias)
   + digit hack: with byte-exact clone the boot hung at "loading" forever when
   the header internal name was "EATrax2"; with internal name kept as "EATrax1"
   it boots but tracks 23+ still break (same as #3).

5. Preserving vs. zeroing the per-entry runtime pointer slots (0x08..0x1F) in the
   track table made NO difference to the broken-audio symptom.

## THE BREAKTHROUGH — Nahelam's ELF Code Cave (changes everything)

Repo: **https://github.com/Nahelam/PS2-Game-Mods** , folder `Burnout 3 Takedown`.
Clone: `git clone --depth=1 https://github.com/Nahelam/PS2-Game-Mods.git`

Key discoveries from that repo:

### 1. 188 KB ELF code cave is available
`ELF Code Cave/README.md`: a compiler inline-explosion bug bloated three
functions (`CB3TrafficVehicle::StartCrashing/Remove/Update`). Nahelam's pnach
relocates them, freeing **`0x0016B4F0`..`0x001996D0` = 188896 bytes** of
contiguous-ish code cave in the SLUS ELF.
- pnach: `ELF Code Cave/SLUS-21050_BEBF8793_elf_code_cave.pnach`

### 2. The overlay region 0x003Fxxxx IS patchable (we previously thought NOT)
Nahelam's `single_event_dj.pnach` for SLUS patches `0x003FA044`, `0x003F9A38`,
`0x003F8CAC` with `patch=0,EE` (write every frame) and it WORKS. So our earlier
conclusion that the 0x003Fxxxx overlay can't be patched was WRONG. That overlay
likely contains the EA TRAX file-loader code we need.

### 3. The generic file loader function name + signature
From `Research/SLES_525.85.txt` (PAL addresses — must be translated to SLUS):
- `CB3AsyncDataLoader::QueueLoadRequest(char const*, bool*, void*, uint)` @ SLES 0x0013CFB0
- `CB3AsyncDataLoader::Construct` @ SLES 0x0013D4E0
- `CB3AsyncDataLoader::Abort(uint)` @ SLES 0x0013CE30
- `CB3DriverDetailsEATraxState::Action(...)` @ SLES 0x00432400  (EA TRAX menu handler)
- `CB3EATraxDisplay::Render/Update/Construct` @ SLES 0x00439220 / 0x004392A0 / 0x00439570
- `CB3EATrax2dObject::Prepare(void)` @ SLES 0x00439400  (likely where path is built)
- `CGtSoundStream::Play(bool)` @ SLES 0x003865F0 , `::IsPlaying` @ 0x00386370
- `CGtSoundBankManager::LoadBank(char const*, ...)` @ SLES 0x00384420

NOTE: these are **SLES_525.85 (PAL)** addresses. For our **SLUS_210.50 (NTSC-U)**
build they differ. Must find SLUS equivalents (byte-pattern search or PCSX2
debugger). `Research/README.md` says addresses come from the B3 prototype map
file + Burnout Revenge prototype debug symbols, "may be inaccurate."

### 4. Distribution pattern
Nahelam ships big mods as **`.xdelta`** (binary ISO diffs, apply with xdelta3 /
Delta Patcher) plus a small activation cheat. Toggleable patches stay as pnach.
The `Crash Breaker Expansion` mod is the reference for "embed custom code in the
cave + hook the engine + ship as xdelta."

## Pre-reqs validation status (IN PROGRESS when handed off)

We copied two pnach into PCSX2 cheats dir to validate the code cave works on this
machine:
- `BEBF8793_elf_code_cave.pnach` (135 KB)
- `BEBF8793_crashbreaker_expansion.pnach` (15 KB)
**NOT YET CONFIRMED in-game.** Next step was: enable both cheats in PCSX2, boot
the clean ISO, verify (A) game boots, (B) Crash Breaker works in a normal Race
(Single Event -> Race, not Crash mode). If that works, the cave approach is
validated for this setup.

## Recommended plan (fastest path to N full-length tracks)

**Phase 1 — Validate the code cave on this PCSX2 setup.**
Enable Nahelam's ELF Code Cave + Crash Breaker Expansion pnach, boot clean ISO,
confirm boot + Crash Breaker in a normal Race. (~30 min.)

**Phase 2 — Locate EA TRAX file-loading code in SLUS.**
Translate the SLES function addresses to SLUS_210.50 (byte-pattern search in
Ghidra, or breakpoints in PCSX2 debugger). Specifically find:
- where `CB3EATrax2dObject::Prepare` builds the path using the 0x004E1F08 table
- where/how it calls `CB3AsyncDataLoader::QueueLoadRequest`
- what ELSE happens on RWS load that breaks when we redirect (the unknown from
  dead-end #3 — this is the crux; use the debugger to single-step a working
  track-23 load vs. a redirected one and diff the behavior).

**Phase 3 — Minimal hook: make `_EATRAX2.RWS` load & play.**
Inject MIPS into the code cave that fixes path-building for file_idx>=2 (and
whatever else Phase 2 reveals is needed). Hook the call site. Success = track 45
plays silence WITHOUT killing audio. Ship/test via pnach first, xdelta later.

**Phase 4 — Scale to N tracks + full sizes + strings.**
Extend metadata (entries beyond 44 — may need to relocate the whole metadata
array into the code cave to avoid the 0x004A5A60 collision and the "EATrax"
string overlap), dynamic string IDs, and a real `_EATRAX2.RWS` with N
full-length tracks (arbitrary sizes; track table already supports per-track
size/offset). Update GLOBALUS.BIN strings (burnout3_gui.py already does in-place
string replacement; adding NEW strings needs more RE — or relocate strings too).

## Useful constants / helpers (copy into scripts)

```python
import struct
SECTOR = 2048
# Known SLUS_210.50 facts:
RAM_METADATA_ARRAY = 0x004A5600   # 24-byte entries
RAM_TRACK_COUNT    = 0x004A5A24   # u32 master count (44 stock)
PATH_PTR_TABLE     = 0x004E1F08   # tracks\ / _EATrax / EATraxD / 0 / 1 / .rws ...
DIGIT0_STR_VA      = 0x004CEA78
DIGIT1_STR_VA      = 0x004CEA80
CODE_CAVE_START    = 0x0016B4F0   # after applying Nahelam's ELF Code Cave pnach
CODE_CAVE_END      = 0x001996D0   # 188896 bytes
PROTECTED_NFSUNDER = {"IOPRP280.IMG", "IRX281A.BUN", "IRX281B.BUN"}

def elf_vaddr_to_fo(elf, va):
    assert elf[:4] == b"\x7fELF"
    phoff = struct.unpack_from("<I", elf, 28)[0]
    phentsize = struct.unpack_from("<H", elf, 42)[0]
    phnum = struct.unpack_from("<H", elf, 44)[0]
    for i in range(phnum):
        h = phoff + i*phentsize
        if struct.unpack_from("<I", elf, h)[0] != 1:  # PT_LOAD
            continue
        p_off  = struct.unpack_from("<I", elf, h+4)[0]
        p_vad  = struct.unpack_from("<I", elf, h+8)[0]
        p_fsz  = struct.unpack_from("<I", elf, h+16)[0]
        if p_vad <= va < p_vad + p_fsz:
            return p_off + (va - p_vad)
    raise ValueError(f"vaddr 0x{va:X} not in any PT_LOAD segment")

def iso_find_files(iso_bytes):
    """Returns list of (path, lba, size, dir_record_offset)."""
    d = iso_bytes
    po = 16*SECTOR
    rlba = struct.unpack_from("<I", d, po+158)[0]
    rsz  = struct.unpack_from("<I", d, po+166)[0]
    def scan(lba, sz, pre=""):
        out = []; base = lba*SECTOR; end = base+sz; p = base
        while p < end:
            if p >= len(d): break
            ln = d[p]
            if ln == 0:
                p = ((p//SECTOR)+1)*SECTOR; continue
            if p+ln > len(d): break
            fl = struct.unpack_from("<I", d, p+2)[0]
            fs = struct.unpack_from("<I", d, p+10)[0]
            fg = d[p+25]; nl = d[p+32]
            if nl > 0 and p+33+nl <= len(d):
                n = bytes(d[p+33:p+33+nl]).decode("ascii","replace").split(";")[0]
                if not (nl == 1 and d[p+33] in (0,1)):
                    fp = f"{pre}/{n}" if pre else n
                    if fg & 2: out += scan(fl, fs, fp)
                    else: out.append((fp, fl, fs, p))
            p += ln
        return out
    return scan(rlba, rsz)
```

## ISO file map (key offsets, from the clean USA ISO)

```
DATA/GLOBALUS.BIN      LBA 8846    (214850 bytes)   <- UTF-16LE string table
SLUS_210.50            LBA 1229    (4073816 bytes)  <- the ELF
NFSUNDER/IOPRP280.IMG  LBA 17386   PROTECTED (IOP modules)
NFSUNDER/IRX281A.BUN   LBA 17518   PROTECTED
NFSUNDER/IRX281B.BUN   LBA 17543   PROTECTED
NFSUNDER/NFSUNDER.ELF  LBA 17602   sacrificable (renamed to _EATRAX2.RWS in pipeline)
NFSUNDER/ZDIR.BIN      LBA 19343   sacrificable
NFSUNDER/ZZDATA0..3    LBA 19347+  sacrificable (~275 MB total usable)
TRACKS/_EATRAX0.RWS    LBA 723121  (156403712 bytes) 22 tracks
TRACKS/_EATRAX1.RWS    LBA 799490  (157263872 bytes) 22 tracks
```

## GLOBALUS.BIN strings

UTF-16LE, null-terminated. burnout3_gui.py constant `GLOBALUS_STRINGS_START =
0xB800`. Music strings come in groups of 3 (title, album, artist):
- Region 1 ~0xB700: 120 strings = 40 slots (tracks 1-40), parser skips first 3.
- Region 2 ~0x2C004: 12 strings = 4 slots (tracks 41-44).
Real song title examples found in region 2: "Heart Full Of Black" / "Burning
Brides" (track 41), "Radio Up" / "Letter Kills" (43), "Just Tonight..." / "Jimmy
Eat World" (44). Note: the string INDEX a naive parser computes != the string ID
the ELF metadata uses (ELF uses IDs 3276.., naive parse put those songs at index
4322..). The ELF metadata string IDs are the source of truth; the game's own
string-id→string resolver is the real mapping (not yet fully reversed).

## Working one-liner (produces ISO with tracks 45/46 in UI, no audio yet)

This is the last known-good builder. It does NOT make track 45/46 audio work
(that's the open problem), but it cleanly adds them to the UI without breaking
anything. Use it as the baseline. Run in fish:

```fish
python3 ~/Downloads/eatrax2.py "~/Downloads/Burnout 3 - Takedown (USA).iso" ~/Downloads/Burnout3_out.iso
```

The Python (save as ~/Downloads/eatrax2.py) — core steps: copy ISO; find
_EATRAX0/SLUS/NFSUNDER.ELF; gen silence RWS from EATRAX0 header (rename internal
name to EATrax2, set tracks_per_file=3, fix first-3 sizes/offsets, fix container
size); inject into sacrificable NFSUNDER zone (protect the 3 IOP modules);
in-place rename NFSUNDER.ELF dir record -> _EATRAX2.RWS;1 (same rec_len=48); patch
ELF metadata entries 44 & 45 (clone string IDs from entries 40 & 41) and set
master track count = 46 at 0x004A5A24. (Full source is reconstructable from the
facts above; the metadata-entry stride is 24 bytes, track-count overlaps entry-44
padding, and only 2 new UI slots are safe before the 0x004A5A60 collision.)

## SET UP & READY TO TEST: HostFS + ciopfs (2026-06-13)
ciopfs built from canonical source (repo.or.cz/ciopfs.git, GPLv2 by Marc Andre Tanner +
Miklos Szeredi; audited: no system/exec/socket/dlopen; uses glibc sys/xattr.h + fuse2 + glib
— all already present, NO AUR/brew/pacman install). Binary: `~/.local/bin/ciopfs`.
Setup done:
- `~/burnout3_hostfs/` lowercased (835 entries; ciopfs needs lowercase backing) incl. the
  added `tracks/_eatrax2.rws`.
- `~/burnout3_hostfs/burnout3.iso` = full clean original (boot iso; xorriso/minimal black-screen).
- ciopfs mount: `~/burnout3_hostfs` -> `~/burnout3_ci` (case-insensitive). Remount after reboot
  with `~/mount_burnout_hostfs.sh`.
- cheats: `SLUS-21050_BEBF8793_hostfs.pnach` (Nahelam) + `BEBF8793_eatrax_phase3.pnach` (mine).
PCSX2: scan `~/burnout3_ci` (the MOUNT, not the backing), boot burnout3.iso, enable Host
Filesystem + both cheats. Verified case-insensitive lookups work via the mount.
AWAITING in-game result: do tracks 45/46 (=_eatrax2 local 0/1) play silence without killing audio?

## (history) CONFIRMED: ISO surgery is dead; HostFS+ciopfs is the path (Linux)
Tested in PCSX2:
- NFSUNDER rename ISO -> hangs at loading (wrong dir).
- xorriso rebuild ISO (file in /TRACKS) -> BLACK SCREEN even after splicing the PS2 system
  area back. xorriso's full relayout breaks PS2 boot (some structure dependency). Dead end.
- byte-surgery dir-record add -> handoff dead-end #1 (corrupts). Dead end.
So adding a file via ISO modification does NOT work for this game.

HostFS works but has a **Linux case-sensitivity** blocker: the game requests paths in mixed
case (`Data/GlobalUs.bin`, `Tracks/tlist.bin` AND `tracks\Alpine1.m2v` — same dir, both
cases!) while the extracted folder is uppercase. On case-sensitive Linux, IOP modules
(uppercase, e.g. `cdrom0:\IOP\B3ROUTE.IRX`) load fine (bar reaches ~70%) then the mixed-case
`Data/...` reads fail -> stall. Can't fix by renaming (inconsistent case for the same dir).
**Fix: ciopfs** (case-insensitive FUSE; needs lowercase backing). Plan: lowercase
`~/burnout3_hostfs/`, mount via ciopfs, use the ORIGINAL clean iso as boot iso (xorriso boot
iso would also black-screen), hook/count/metadata via `BEBF8793_eatrax_phase3.pnach`.

## HostFS path details (per Nahelam) — superseded notes below kept for reference
Both ISO-modification attempts failed: NFSUNDER rename -> hang at loading (wrong dir: game
opens `tracks\_EATrax2.rws` in TRACKS, not NFSUNDER); xorriso rebuild -> black screen
(xorriso zeroes the first 16 sectors = the PS2 license/"system area" `D5 D5...`; splice the
original 0x8000 bytes back to fix boot, but the relayout is still risky). So use **HostFS**:
- User has `~/burnout3_hostfs/` (full extracted disc) + `~/Downloads/PCSX2-HostFS-Patches`
  (Nahelam). The Burnout 3 USA patch is `Criterion Games/Burnout 3 - Takedown/
  SLUS-21050_BEBF8793_hostfs.pnach` (loads GTFSHOST.IRX instead of GTFSCDVD.IRX -> all file
  reads go to the host folder; only SYSTEM.CNF + ELF come from the boot iso).
- Phase 3 test setup (built, in place):
  - `_EATRAX2.RWS` (2 silence tracks) -> `~/burnout3_hostfs/TRACKS/`
  - `~/burnout3_hostfs/boot.iso` = minimal iso (SYSTEM.CNF + SLUS_210.50 + spliced PS2 system area)
  - cheats: `SLUS-21050_BEBF8793_hostfs.pnach` (Nahelam) + `BEBF8793_eatrax_phase3.pnach`
    (mine: hook patch=1 + digit strings "0..3" + count=46 + metadata 44/45 cloned from 41/42).
- PCSX2: scan `~/burnout3_hostfs/`, enable Host Filesystem + both cheats, boot. Tracks 45/46
  (= internal 44/45 -> _EATrax2 local 0/1) should play silence if the hook + by-path open work.
- The hook is a pnach here because with HostFS the ELF is still read from the boot iso; the EE
  code at 0x3Fxxxx is RESIDENT (verified: appears once in the ISO), so patch=1 sticks.

## Immediate next action when resuming

1. `cd ~/Downloads && test -d PS2-Game-Mods || git clone --depth=1 https://github.com/Nahelam/PS2-Game-Mods.git`
2. Confirm the two pnach are in `~/.var/app/net.pcsx2.PCSX2/config/PCSX2/cheats/`
   (`BEBF8793_elf_code_cave.pnach`, `BEBF8793_crashbreaker_expansion.pnach`).
3. In PCSX2: enable both cheats, boot clean ISO, verify boot + Crash Breaker in a
   normal Race. Report result.
4. If OK → Phase 2: find SLUS equivalents of the EA TRAX functions and, crucially,
   use the PCSX2 debugger to figure out WHY redirecting the RWS load kills audio
   (single-step a working load vs. a redirected one). That unknown is the crux.
```

---

# PHASE 2 RESULTS — SLUS_210.50 static analysis (DONE)

Reverse-engineered directly from the SLUS ELF (no PAL translation needed). Method:
extract `SLUS_210.50` from the ISO (LBA 1229, 4073816 B), one PT_LOAD segment
`vaddr 0x00100000 -> file 0x100, fsz 0x3E2680` (so `fo = 0x100 + va - 0x100000`),
then scan MIPS `lui`+`addiu`/`lw` that materialize the KNOWN data addresses, and
disassemble the hits. Reproducible script (extract + validate + scan + disasm):
`research/phase2_elf_analysis.py` — run with the ISO path as arg.

## $gp value (KEY — explains the "0 refs to 0x4E1F08" mystery)
**`$gp = 0x004E8670`.** The path pointer table at `0x004E1F08` is NOT loaded with
lui/addiu — it is read `$gp`-relative. Map: `table[k] = lw (0x4E1F08 - 0x4E8670 + k*4)($gp)`.
- `lw -26472($gp)` = table[0] = "tracks\"   (VA 0x4CEA60)
- `lw -26468($gp)` = table[1] = "_EATrax"   (VA 0x4CEA68)
- `lw -26460($gp)` = table[3] = "0"         (VA 0x4CEA78)
- `lw -26456($gp)` = table[4] = "1"         (VA 0x4CEA80)
- `lw -26452($gp)` = table[5] = ".rws"      (VA 0x4CEA88)

## EA TRAX functions located (all in the 0x003Fxxxx overlay — patchable, per breakthrough #2)
| SLUS VA | What it is |
|---|---|
| `0x003FBC20` | **Path builder #1** — `sprintf(s0+72, "%s%s%s%s", "tracks\", "_EATrax", digit, ".rws")` |
| `0x003FC2E0` | **Path builder #2** — same sprintf, different state path |
| `0x003FCD20` | **State Construct** — reads master count `0x4A5A24`→s0+108, array base ptr `0x4A5A6C`→s0+180, copies "EATrax" UTF-16 from 0x4A5A2C |
| `0x003FC700` | **State machine / Update** (states 1-5 @ s0+208); resolves the 3 string IDs |
| `0x00271A00` | **string-ID → string resolver** (ctx a0=0x51BA44); called with entry+8/+0xC/+0x10 (title/album/artist IDs) |
| `0x00126B40` | sprintf-style formatter (used by both path builders) |
| `0x00386010` | sound "is ready/playing?" (returns bool); `0x386240`/`0x3863C0`/`0x386A60` = sound stream stop/abort |
| `0x0042B580`, `0x0042B500` | **EMPTY STUBS** (`jr $ra` only) — dead lead, NOT the loader |

## The digit-selection logic (THE lever for file_idx >= 2)
In BOTH path builders, identical:
```
lw   $v0, 216($s0)     ; track index (stored earlier: sw $a1,216($s0))
slti $at, $v0, 22      ; track < 22 ?
beq  $at,$zero, ELSE   ;   track >= 22 -> digit = table[4] "1", s0+224 = 1
  digit = table[3] "0" ;   track <  22 -> digit = table[3] "0", s0+224 = 0
```
Hardcoded threshold **22**; only "0" and "1" digit strings exist. Confirmed there is
**NO `_EATrax2` / "2" string anywhere in the ELF** (searched, 0 hits). To add file 2:
hook this to emit "2" (and a new digit string) when track >= 44.

Metadata entry address is computed `entry = [s0+180] + track*24` (confirms 24-byte
stride). **`s0+180` comes from the POINTER at `0x4A5A6C`** (verified `[0x4A5A6C] = 0x4A5600`).

## Corrections / additions to earlier sections of this doc
- **Metadata array base is a POINTER at `0x004A5A6C` (= 0x4A5600), not hardcoded.**
  => Phase 4 can relocate the whole metadata array into the code cave by repointing
  `0x4A5A6C` + setting count at `0x4A5A24`. This SIDESTEPS the 0x4A5A60 collision and
  the "EATrax"-string overlap that previously capped us at 2 new slots.
- **GLOBALUS string resolver formula (was "not fully reversed"):** the string for a
  given metadata string-id is found via a pointer table inside GLOBALUS.BIN at
  `glob_base + 0x10 + id*4` -> u32 byte offset of the UTF-16LE string. Verified:
  title_id 477 (track 0) -> ptr @0x784 (`0x10 + 477*4`), 478->0x788, 479->0x78C.
  So adding NEW song strings = add new pointer-table entries + string bytes.
- **`GLOBALUS_STRINGS_START` constant is wrong/removed:** real region-1 start is
  `0xB700` (not 0xB800). The repo tool now patches names IN PLACE at fixed byte length
  (offsets must not move — see the 0x784 pointer table); the old "dynamic
  redistribution" was a bug that garbled names.
- ISO size is **2.87 GB** (the LBAs 723121/799490 still match; the "~4.3 GB" note was stale).

## Crux still open (needs PCSX2 runtime — can't do statically)
WHY redirecting the RWS load kills audio (dead-end #3). Now we have exact breakpoint
targets: set EE execution BPs at the two path builders (`0x003FBC20`, `0x003FC2E0`),
the Construct (`0x003FCD20`), and the sound funcs (`0x00386010`/`0x00386240`). Single-step
a working track-23 load vs. a redirected one and diff. The path string is built into
`object+72`; trace what consumes it (the real async file-open) from there.

## Ghidra headless IS usable (decompiler output, no GUI needed)
Ghidra 12.1.2 installed (`/opt/ghidra/support/analyzeHeadless`), runs fine under JDK 26.
**PS2 EE processor: use `-processor r5900:LE:32:default`** (the bundled
`ghidra-emotionengine-reloaded` extension — the plain `MIPS:LE:32:default` chokes on the
R5900 `lq`/`sq` 128-bit ops and decompiles the overlay funcs as `halt_baddata()`).
Reproduce:
```
/opt/ghidra/support/analyzeHeadless /tmp/proj b3 -import SLUS_210.50.elf \
  -processor r5900:LE:32:default -scriptPath research/ghidra \
  -postScript DumpEATrax.java -deleteProject
```
Artifacts: `research/ghidra/DumpEATrax.java` (decompile script),
`research/ghidra/eatrax_decompiled.txt` (captured C pseudocode).

### What the decompiler confirmed (the EA TRAX 2d object, this=iVar6)
- `obj+0xb4`(180) = metadata array base (from ptr `[0x4A5A6C]`);
  `obj+0xc4`(196) = current entry = `base + track*0x18`.
- `obj+0xc0`(192) = **active sound-stream handle**; `obj+0x48`(72) = built path string;
  `obj+0xd8`(216) = track index; `obj+0xd0`(208) & `obj+0xc8`(200) = state vars.
- **Path builders `0x3FBC20`/`0x3FC2E0` (`Prepare`)**: stop current stream
  (`0x386240`/`0x3863C0`/`0x386A60` on `obj+0xc0`), then if track<0x16 digit="0" else "1",
  then `sprintf(obj+0x48,"%s%s%s%s","tracks\","_EATrax",digit,".rws")`. They do NOT open
  the file — they only build the path + reset the stream.
- `0x3FC700` = per-frame **display** state machine (syncs title/artist/album scroll to
  playback pos via `0x386080`; resolves the 3 string ids via `0x271A00`).
- `0x271A00` = string-id resolver: `return *(*(ctx)+0xc) + id*4)` (a pointer table).
- **`0x42B500`/`0x42B580`/`0x42B5E0`/`0x42B570` are STUBS** (empty / `*p=0`). Dead leads.
- `0x386010` = `stream->state==6` (is-playing); `0x386080` = stream position (ms).

### NEXT TARGET to crack the crux (the real file-open)
Nothing in `Prepare` opens the file; it only writes the path to `obj+0x48` and CLEARS the
stream handle `obj+0xc0`. So a *different* method reads `obj+0x48` and CREATES the stream
into `obj+0xc0` (the real `CGtSoundStream::Open/Play(path)` ~ `0x386xxx`). Find it by:
locating the function that WRITES `obj+0xc0` (stream handle) and/or READS `obj+0x48`.
The path builders appear to be called via vtable (no direct xrefs), so this is a C++
object — find its vtable / the owner that ticks it. That stream-create is where redirect
to `_EATrax2` breaks; decompile it next with the same headless setup.

## FULL LOADER CHAIN MAPPED (Ghidra, SLUS_210.50) — the crux is now narrowed
Call chain for playing an EA TRAX track (this = EA TRAX 2d object):
```
menu handler 0x4313e0 (CB3..EATraxState::Action)
  -> 0x3FBC20 / 0x3FC2E0  Prepare(this, trackIdx): stop old stream, compute
       entry = [this+0xb4] + trackIdx*0x18, digit = trackIdx<22?"0":"1",
       sprintf(this+0x48, "%s%s%s%s","tracks\","_EATrax",digit,".rws")
  -> 0x3FC8C0  Play state machine (switch on this+0xc8):
       state0: this+0xc0 = FUN_00386b30(sndMgr=0x1e774e0, 0|1)   // ALLOCATE a voice (pool 0/1, not a file)
       state1: ok = FUN_003865a0(handle, this+0x48 /*PATH*/, 0, this+0xd4,
                                 trackIdx - digit*22 /*LOCAL index in file*/, flags)
       state2: start playback (0x386290 / 0x386300 vol / 0x385eb0)
       state4: 0x385fe0 done? -> next track via 0x3FBDB0 + Prepare
```
Key functions:
- `0x00386B30` = **allocate a stream voice** from a pool (arg2 = 0 or 1 selects pool); returns handle. NOT a file open.
- `0x003865A0` = **stream/seek**: seeks to the track by consuming per-track sizes
  (`for(; cum <= localIdx; localIdx -= n)` using `[this+0x138]/[this+0x13c]`). On first
  load (flag `this+0x1f4==0`) it calls the opener `0x00386790`.
- `0x00386790` = **the real OPEN, BY PATH STRING**: `strncpy(stream, path, 0x100)`, '/'→'\',
  fills a request struct with path + streaming offset/size (`+0x130/0x134/0x138`), submits
  via `FUN_002A2D00(voice@+0x1cc, request@+0x100)`. **Requires voice state==9 (idle)** or it
  returns false without opening.
- `0x003FBDB0` = next-track / shuffle; iterates `this+0x6c` = **the master track count
  copied from `0x4A5A24`** (so patching the count really does extend the playlist).
- File I/O is **by path** (no hardcoded LBA): strings `cdrom0:`@0x3B43A0, `.rws`@0x3B5612.

### THE digit + local-index bug (explains dead-end #3 for ADDED tracks 44+)
`localIdx = trackIdx - digit*22`. Digit is only ever 0 or 1, so for trackIdx>=44 the local
index exceeds the file's 0..21 track table -> `0x3865A0` seeks past the table -> garbage
offset/size -> the streaming DMA reads garbage and the voice never reaches a good state ->
audio dies permanently (no recovery == voice stuck off state 9). **Unified fix** (Phase 3
code-cave hook): replace `digit = trackIdx<22?0:1` with `digit = trackIdx/22` and add digit
strings "2","3",... — then the EXISTING `localIdx = trackIdx - digit*22` is already correct
for every file. Each `_EATraxN.rws` needs its own valid <=22-entry track table.

### Crux for the REDIRECT case (byte-exact clone still broke) — needs PCSX2 runtime
Since the open is by-path, the remaining unknown is inside `FUN_002A2D00` (IOP stream/file
submit) or the voice state gate (`state==9`). Set an EE breakpoint at **0x00386790**: check
(a) is it reached for the redirected track, (b) the `path` arg string, (c) the voice state
`lVar1` (must be 9), (d) the return of `FUN_002A2D00`. Compare working track-23 vs redirected.
If `_EATrax2.rws` open fails there, the IOP CDVD path-resolve doesn't see the renamed file
(directory-record rename may not be enough for the IOP file cache) — try a real added file /
HostFS instead of the NFSUNDER rename.

# PHASE 3 RESULTS — N-file digit/index hook (DONE, in-place, no code cave)

The hardcoded 2-file logic `digit = track<22 ? "0" : "1"` is the ONLY thing stopping
file_idx>=2. It lives as an identical 9-instruction block in both Prepare functions:
`0x003FBCD0..0x003FBCF4` and `0x003FC38C..0x003FC3B0` (same registers/offsets). Replace it
IN PLACE (same 0x24 bytes — no cave needed for up to 4 files) with:
```
lw    v0,0xd8(s0)     8E0200D8   ; track index
addiu at,zero,22      24010016
divu  v0,at           0041001B   ; lo = track/22
mflo  v0              00001012   ; digit
sw    v0,0xe0(s0)     AE0200E0   ; this+0xe0 = digit  (localIdx = track-digit*22 already uses this)
sll   t0,v0,1         00024040   ; digit*2
lui   at,0x004C       3C01004C
addiu at,at,-0x1588   2421EA78   ; at = 0x4CEA78  (digit-string table)
addu  t0,at,t0        00284021   ; t0 = &digitstr[digit]  (sprintf arg 5)
```
After the block `$t0` = digit-string ptr (survives untouched to the sprintf at +0x3C),
and `this+0xe0` = digit. The local index `track - digit*22` (computed at 0x3FC8C0) and the
metadata entry `[this+0xb4] + track*24` already generalize — no other code change.

Digit-string table: reuse the now-unused "0"/"1" area. Write 8 bytes at **0x4CEA78**:
`30 00 31 00 32 00 33 00` ("0","1","2","3"). Verified bytes 0x4CEA7A..0x4CEA7F are free
padding, and after the hook nothing else reads the old path-table digit ptrs ([3]/[4]).

Artifacts (verified by re-disassembly against the real ELF):
- `research/phase3_hook.py` — assembles/verifies the hook, patches an ELF, emits the pnach.
- `research/BEBF8793_eatrax_nfiles.pnach` — testable cheat. Code in the 0x3Fxxxx overlay uses
  `patch=0,EE` (every frame, like Nahelam's overlay patches); digit strings + count use `patch=1`.

## Still needed for end-to-end playback of tracks 44+ (Phase 3 integration / Phase 4)
1. **Master count** `0x4A5A24` -> e.g. 66 (3 files). (pnach already includes count=0x42.)
2. **Metadata entries** for tracks 44+. Array base is the pointer at `0x4A5A6C` -> relocate the
   whole 24-byte-entry array into free space / code cave (bigger array), set count, repoint
   `0x4A5A6C`. Clone string ids from existing entries for a first test.
3. **`_EATrax2.rws`** with a valid <=22-entry track table (the burnout3_gui RWS builder already
   makes these; generate a silence file first).
4. **GLOBALUS strings** for the new song names: add entries to the in-file pointer table at
   `glob_base + 0x10 + id*4` plus the UTF-16 bytes.

## Test plan (user, in PCSX2 — I can't drive the emulator)
A) Quick hook smoke test: drop `BEBF8793_eatrax_nfiles.pnach` in the cheats dir, enable it,
   boot the CLEAN ISO. Tracks 1-44 must still play (the hook is behavior-identical for
   track<44: digit=track/22 gives 0 for 0-21 and 1 for 22-43, same as before). If 1-44 still
   work, the patch location/format is correct.
B) Then combine with the existing "working one-liner" that creates `_EATrax2.rws` (silence) +
   renames NFSUNDER.ELF, bump count to 66, add 2 metadata entries. With the hook, track 45
   should now build path `tracks\_EATrax2.rws` and local index 0 (=44-2*22). Breakpoint
   `0x386790` to confirm the path + that the open succeeds (vs. dead-end #3).

# PHASE 3 INTEGRATION — testable ISO built (structurally verified)

`research/phase3_build.py IN.iso OUT.iso` produces a ready-to-test ISO combining ONLY proven
techniques + the verified hook. Built+verified output: `~/Downloads/Burnout3_eatrax2_test.iso`.
What it does (all confirmed by re-parsing the output):
- patches the digit/index **hook** into the ELF (both Prepare funcs + digit strings) ✓
- builds a silence **`_EATrax2.rws`** (2 tracks x 1 MB) by cloning the EATRAX0 header ✓ (parses as 2 tracks)
- injects it via the **NFSUNDER.ELF in-place rename** (writes RWS at LBA 17602, renames record
  `NFSUNDER.ELF;1`->`_EATRAX2.RWS;1`, both-endian LBA/size) ✓
- sets master **count=46** and writes **metadata entries 44/45** (cloned string ids from 41/42,
  in-place exploit: entry44.pad == the count) ✓
- originals intact: `_EATRAX0/1` still 22 tracks each, disc id present ✓

This is exactly the experiment that resolves dead-end #3. Boot it in PCSX2:
- **Tracks 1-44 must still play** (hook is behavior-identical there: track/22 = 0 or 1).
- **UI tracks 45/46** (= internal 44/45 = `_EATrax2` local 0/1) should now play **silence**
  WITHOUT killing audio. Scroll back to 1-44 to confirm audio still works.
  - If silence plays + audio survives -> **by-path open of `_EATrax2` WORKS, crux solved**;
    proceed to Phase 4 (real audio, more files, relocated metadata, GLOBALUS names).
  - If audio dies -> the IOP CDVD path-resolve doesn't see the renamed file. Breakpoint
    `0x386790` (check it's reached, the `path` arg, voice state==9, return of `FUN_002A2D00`).
    Fallback: real added ISO file (not a rename) or Nahelam's HostFS.

Notes / known tradeoffs: the in-place metadata exploit clobbers the "EATrax" UTF-16 menu
string at 0x4A5A2C (cosmetic) and caps at 2 new tracks; UI tracks 45/46 show tracks 42/43's
names (cloned ids). Phase 4 replaces this with a relocated metadata array — but NOTE the
scavenged zero-runs in the ELF data segment are NOT free (e.g. 0x485894 has pointer + code
refs); relocation must use Nahelam's code cave or a verified-unused region.

# ============================================================================
# *** FULLY SOLVED (2026-06-14) — all four final-vision goals working in PCSX2 ***
# ============================================================================
The complete EA TRAX expansion works end to end (verified in-game):
custom full-length tracks + N tracks + unlimited custom names (romanized).

WORKING PIPELINE (HostFS, no ISO modification):
 - ciopfs case-insensitive mount of ~/burnout3_hostfs -> ~/burnout3_ci (binary built from
   source at ~/.local/bin/ciopfs; systemd user unit burnout3-ciopfs.service auto-mounts).
   PCSX2 boots ~/burnout3_ci/burnout3.iso (host root must be the case-insensitive mount).
 - Cheats (all addresses are 32-bit "extended" writes => prefix 0x20000000!):
     [HostFS]  (Nahelam SLUS-21050_BEBF8793_hostfs.pnach)  -> files load from the folder
     [ELF Code Cave] (Nahelam)                             -> frees 0x16B4F0..0x1996D0
     [EATRAX +N tracks] = research/BEBF8793_eatrax_reloc.pnach:
        * digit hook (digit=track/22) at Prepare 0x3FBCD0 & 0x3FC38C + digit strings 0x4CEA78
        * master count @0x4A5A24 = 44+N
        * relocated 24-byte metadata array @0x16B4F0 (code cave); base ptr @0x4A5A6C -> 0x16B4F0
   (crashbreaker OFF — it also uses the cave.)
 - _eatraxN.rws files in ~/burnout3_hostfs/tracks/ (lowercased): built by
   research/build_eatrax_hostfs.py from a real EATRAX base, per-track slots resized to the
   FULL song (no truncation). digit=track/22 => track 44-65 -> _eatrax2 local 0-21, etc.
 - Custom unlimited names: data/globalus.bin rebuilt — RELOCATE its pointer table by appending
   a bigger table at EOF and updating the header: count@+0x08, table_offset@+0x0C. New string
   ids (count..) point to appended UTF-16LE strings. No hash check (in-place edits already work).
   Metadata entries' title/album/artist ids -> the new ids.
 - Romanizer: research/romanize.py (ICU/uconv any-language + pykakasi venv for Japanese).

REMAINING = production polish only (no unknowns left): fill every new slot with real songs +
names, scale to more _eatraxN files for >22 new tracks, and wrap it all in one script/GUI mode.

================================================================================
PORTABLE ISO (no cheats, no HostFS) — 2026-06-14 update
================================================================================
Goal: bake everything into ONE self-contained ISO that boots on PCSX2, Android
(AetherSX2/NetherSX2) and real PS2 with zero cheats/folders. Engine:
`research/build_portable_iso.py` -> build_portable_iso(clean_iso, out_iso, slots).
GUI: `SOUNDTRACK` tab -> `BUILD PORTABLE ISO` button. All verified in PCSX2.

KEY FACT: Burnout 3 reads its loose disc files by FIXED LBA. A full ISO re-author
(xorriso/genisoimage moves every file) BLACK-SCREENS. EXCEPT the `_EATRAX*.RWS` and
`DATA/GLOBALUS.BIN`, which are opened BY PATH (proven: relocate _EATRAX0 to the disc
end + zero the old copy -> tracks still play). So the portable builder keeps EVERY
original file byte-identical at its LBA and surgically relocates ONLY the (enlarged)
EATRAX/GLOBALUS files to the disc end, patching just their ISO9660 directory records
(extent LBA + size, LE & BE) and the PVD volume size (LE@80/BE@84). find_record()
walks ISO9660; relocate() = zero-old / append-end / patch-record + PVD.

WORKS (portable, no cheats):
 - 44 full-length tracks: enlarge _EATRAX0/1 (reuse the proven track-resize) + relocate.
 - Unlimited names: enlarge GLOBALUS (relocate its string table) + relocate it + repoint
   each track's metadata IN THE ELF in-place (title_id@ent+8, album@+12, artist@+16;
   metadata file-offset = 0x100 + (0x4A5600-0x100000) = 0x3A5700; entry stride 24).
   Editing the ELF changes its CRC so PCSX2 won't auto-apply BEBF8793 cheats — desired.
 - Found a free ELF zero-run at VA 0x485894 (file 0x385994, ~6996 bytes = 291 entries):
   relocate the metadata array there (base_ptr@0x4A5A6C -> 0x485894) for count>44 WITHOUT
   Nahelam's code cave / [ELF Code Cave] cheat. SAFE (verified at count=44 in PCSX2).

+TRACKS PORTABLE (beyond 44) — BLOCKED, two walls (diagnosed via PCSX2 emulog DvdRead
sector trace + isolation builds):
 1. ADD a new `_EATRAX2.RWS` to the ISO (sorted dir record; valid per xorriso extract):
    the game NEVER reads it (0 reads to its sectors) and CPU-hangs. The IOP/CD path won't
    serve a newly-added file (HostFS works because it bypasses the disc filesystem).
 2. EXTEND an existing `_EATRAX1.RWS` track table to >22 entries (clone entry struct,
    bump count@0x38 + chunk sizes): the game reads the extended header then hangs in
    RenderWare relocation (FUN_002AD8E0). Per-entry internal pointers (+0/+4 grow ~0x240/
    0x190 per track, +0xc grows 4) reference per-track RW structures SIZED BY AUDIO LENGTH;
    cloning is inconsistent (same class as the old silence-RWS TLB crash).
 NOTE: the game does NOT bounds-check the local index (count=46 no-hook reached the menu;
 only froze when PLAYING track 45 -> _EATRAX1 local 23 = garbage in a 22-entry table). So
 the concept (extend _EATRAX1) is sound; the blocker is purely the RWS-audio relocation
 internals. Ghidra of the EE ELF can't help (stripped; file open is delegated to the IOP
 CD/stream layer via 0x2a2xxx primitives + RPC). Cracking portable +tracks = a research
 project (model RWS per-track relocation, or reverse the IOP CD lookup). +tracks works
 today via HostFS (non-portable). Shipped: portable 44 full-length + unlimited names.
