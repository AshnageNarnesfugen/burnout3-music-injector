#!/usr/bin/env python3
"""
Build a custom _eatraxN.rws for HostFS by taking a real EATRAX file as the base
(valid RenderWare structure) and REPLACING chosen local-track slots with custom
music, FULL-LENGTH (each slot resized to fit the whole song, no truncation/fade).

Why this works: the RW relocation (FUN_002AD8E0) lays out the header sub-structures
(+0xc/+0x10/+0x14), which we leave intact; only the per-track audio size/offset (+24/+28)
and the audio data change — exactly what burnout3_gui already does to the 44 tracks, proven
to keep the file loadable. HostFS means the file lives on disk, so size is unbounded.

Usage: python3 build_eatrax_hostfs.py BASE.rws OUT.rws  song0.ext[,song1.ext,...]
  (songN goes to local track N; unlisted tracks keep the base's audio)
"""
import sys, os, struct, subprocess, tempfile, importlib.util, math

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("b3", os.path.join(HERE, "..", "burnout3_gui.py"))
b3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(b3)
W = b3.InjectionWorker.__new__(b3.InjectionWorker)

ENTRY, SW, OW = 32, 24, 28

def find_table(hdr, hsize):
    he = 24 + hsize
    for scan in range(24, he - 32, 4):
        cs = struct.unpack_from("<I", hdr, scan)[0]; co = struct.unpack_from("<I", hdr, scan + 4)[0]
        if co == 0 and 500000 < cs < 50000000:
            e0 = scan - SW
            if e0 < 24: continue
            e1s = struct.unpack_from("<I", hdr, e0 + ENTRY + SW)[0]
            e1o = struct.unpack_from("<I", hdr, e0 + ENTRY + OW)[0]
            if e1o == cs and 500000 < e1s < 50000000:
                return e0
    raise RuntimeError("track table not found")

def encode_full(song, tmp, idx):
    """Convert a whole song -> PS-ADPCM, sized to the FULL song (no -t, no fade)."""
    raw = os.path.join(tmp, f"f{idx}.raw")
    loud = b3._loudnorm_filter(b3.LOUDNORM_TARGET, b3._loudnorm_measure(song, b3.LOUDNORM_TARGET))
    subprocess.run(["ffmpeg", "-y", "-i", song, "-af", f"{loud},{b3.AUDIO_RESAMPLE_FILTER}",
                    "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "32000", "-ac", "2", raw],
                   capture_output=True)
    pcm = open(raw, "rb").read()
    n_per_ch = (len(pcm) // 2) // 2
    size = ((n_per_ch + 7167) // 7168) * 8192          # exact superblock-aligned full size
    return b3.encode_psx_adpcm_sized(pcm, size), size

def main():
    base, out, songs = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    raw = open(base, "rb").read()
    hsize = struct.unpack_from("<I", raw, 16)[0]
    tracks, sr, ch = W._parse_rws_tracks(raw)
    n = len(tracks)
    hdr = bytearray(raw[:24 + hsize])
    ft = find_table(hdr, hsize)
    data_off = 24 + hsize + 12                          # start of audio data
    tmp = tempfile.mkdtemp()

    # gather new audio per track (custom = encoded full song; else keep base audio)
    new_audio = []
    for i in range(n):
        if i < len(songs) and songs[i]:
            adpcm, size = encode_full(songs[i], tmp, i)
            print(f"  local track {i}: {os.path.basename(songs[i])} -> {size//1024}KB "
                  f"(~{b3.adpcm_slot_duration(size):.0f}s, FULL)")
            new_audio.append(adpcm)
        else:
            off, size = tracks[i]
            new_audio.append(raw[off:off + size])      # base audio (abs offset within file)

    # patch track table (size@+24, off@+28 cumulative) + container/data-chunk sizes
    cum = 0
    for i in range(n):
        eo = ft + i * ENTRY
        struct.pack_into("<I", hdr, eo + SW, len(new_audio[i]))
        struct.pack_into("<I", hdr, eo + OW, cum)
        cum += len(new_audio[i])
    total = cum
    struct.pack_into("<I", hdr, 4, hsize + 12 + 12 + total)        # container payload size

    blob = bytearray(hdr)
    blob += struct.pack("<III", 0x080F, total, 0x1C020009)         # audio_data chunk header
    for a in new_audio:
        blob += a
    open(out, "wb").write(blob)
    print(f"\n  wrote {out}: {len(blob)} bytes, {n} tracks, audio {total//1024}KB")

    # verify it re-parses (structure consistent)
    t2, _, _ = W._parse_rws_tracks(open(out, "rb").read())
    print(f"  re-parse: {len(t2)} tracks, sizes[0:2]={[s for _,s in t2[:2]]}")
    import shutil; shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
