"""RenderWare Stream (.RWS) + ISO9660 parsing helpers.

GLOBALUS.BIN note: music strings in DATA/GLOBALUS.BIN are UTF-16LE, null-terminated.
Slots 1-40 live near 0xB700 in groups of 3 (title, album, artist); slots 41-44 live
in a second region near 0x2C004. The game finds each string through a fixed pointer
table (u32 offsets, e.g. at 0x784 for the music block), so strings must be patched IN
PLACE — same offset, same byte length (truncate/null-pad). Moving them would invalidate
the pointers.
"""
import os, struct

from core.constants import RWS_AUDIO_CONTAINER, RWS_AUDIO_HEADER, RWS_AUDIO_DATA


class RWSAudioInfo:
    def __init__(self):
        self.track_count = 0
        self.sample_rate = 0
        self.num_channels = 0
        self.data_offset = 0
        self.total_size = 0


def parse_rws_header(filepath):
    """Parse EATRAX.RWS header. Returns RWSAudioInfo or None on any error.
    Hardened against malformed/truncated files and malicious inputs."""
    info = RWSAudioInfo()
    try:
        file_size = os.path.getsize(filepath)
        if file_size < 36:  # minimum: 2 chunk headers (24) + some payload
            return None
        info.total_size = file_size

        with open(filepath, 'rb') as f:
            # Read a bounded amount — never trust file-declared sizes for the read
            data = f.read(min(65536, file_size))

        buf_len = len(data)
        if buf_len < 36:
            return None

        # audio_container chunk header at offset 0
        ctype, csize, cver = struct.unpack_from('<III', data, 0)
        if ctype != RWS_AUDIO_CONTAINER:
            return None

        # audio_header chunk header at offset 12
        htype, hsize, hver = struct.unpack_from('<III', data, 12)
        if htype != RWS_AUDIO_HEADER:
            return None

        # Sanity-check hsize: must be positive and cannot exceed file size
        if hsize == 0 or hsize > file_size - 24:
            return None

        hdr_start = 24
        # Clamp scan range to what we actually read into memory
        scan_end = min(hdr_start + hsize, buf_len - 4)

        # Track count at hdr_start + 0x20 (big-endian)
        if hdr_start + 0x24 <= buf_len:
            raw_count = struct.unpack_from('>I', data, hdr_start + 0x20)[0]
            # Sanity: track count should be reasonable (1-200)
            info.track_count = raw_count if 0 < raw_count <= 200 else 0

        # Scan for sample rate in header payload
        # EA's RWS variant uses LITTLE-endian for most fields
        VALID_RATES = {22050, 24000, 32000, 44100, 48000}
        for off in range(hdr_start, scan_end, 4):
            if off + 4 > buf_len:
                break
            # Try little-endian first (EA's format)
            val_le = struct.unpack_from('<I', data, off)[0]
            val_be = struct.unpack_from('>I', data, off)[0]
            val = None
            if val_le in VALID_RATES:
                val = val_le
            elif val_be in VALID_RATES:
                val = val_be
            if val:
                info.sample_rate = val
                ch_off = off + 13
                if ch_off < buf_len:
                    ch = data[ch_off]
                    info.num_channels = ch if ch in (1, 2) else 2
                break

        # Safe defaults if detection failed
        if info.sample_rate == 0:
            info.sample_rate = 24000  # EA PS2 standard
        if info.num_channels == 0:
            info.num_channels = 2

        # Locate audio_data chunk
        audio_data_start = 24 + hsize  # end of audio_header payload
        if audio_data_start + 12 <= file_size:
            # Verify the chunk type if we have it in buffer
            if audio_data_start + 12 <= buf_len:
                dtype = struct.unpack_from('<I', data, audio_data_start)[0]
                if dtype == RWS_AUDIO_DATA:
                    info.data_offset = audio_data_start + 12
            else:
                # We didn't read that far — store best guess
                info.data_offset = audio_data_start + 12

    except (OSError, struct.error, OverflowError, ValueError):
        return None
    except Exception:
        return None
    return info


def find_file_offset_iso9660(iso_data, filename_upper):
    """Find a file's (byte_offset, byte_size) inside an ISO9660 image by scanning
    directory records for the filename."""
    target = filename_upper.encode('ascii')
    target_v = target + b';1'  # ISO9660 adds version suffix

    pos = 0
    while pos < len(iso_data):
        idx = iso_data.find(target_v, pos)
        if idx == -1:
            idx = iso_data.find(target, pos)
        if idx == -1:
            return None, None

        entry_start = idx - 33
        if entry_start < 0:
            pos = idx + 1
            continue

        try:
            rec_len = iso_data[entry_start]
            if rec_len < 34 or rec_len > 255:
                pos = idx + 1; continue

            name_len = iso_data[entry_start + 32]
            name_bytes = iso_data[entry_start + 33: entry_start + 33 + name_len]
            if target not in name_bytes:
                pos = idx + 1; continue

            lba = struct.unpack_from('<I', iso_data, entry_start + 2)[0]
            fsize = struct.unpack_from('<I', iso_data, entry_start + 10)[0]
            file_off = lba * 2048

            if lba > 0 and fsize > 0 and file_off + fsize <= len(iso_data):
                return file_off, fsize
        except (struct.error, IndexError):
            pass
        pos = idx + 1

    return None, None


def find_dir_entry_offset(iso_data, filename_upper):
    """Find the byte offset of the ISO9660 directory entry for a file.
    Used to patch the file size field later."""
    target = filename_upper.encode('ascii')
    target_v = target + b';1'

    pos = 0
    while pos < len(iso_data):
        idx = iso_data.find(target_v, pos)
        if idx == -1:
            idx = iso_data.find(target, pos)
        if idx == -1:
            return None

        entry_start = idx - 33
        if entry_start < 0:
            pos = idx + 1; continue

        try:
            rec_len = iso_data[entry_start]
            if rec_len < 34 or rec_len > 255:
                pos = idx + 1; continue
            name_len = iso_data[entry_start + 32]
            name_bytes = iso_data[entry_start + 33: entry_start + 33 + name_len]
            if target not in name_bytes:
                pos = idx + 1; continue
            lba = struct.unpack_from('<I', iso_data, entry_start + 2)[0]
            if lba > 0:
                return entry_start
        except (struct.error, IndexError):
            pass
        pos = idx + 1
    return None


def parse_rws_tracks(rws_data):
    """Parse an EATRAX.RWS container to find individual track offsets/sizes.

    Track table entries are 32 bytes; the size field is at entry+24 and the
    cumulative data offset at entry+28 (track 0 offset = 0, track 1 offset =
    track 0 size, ...). The table is located by searching the header payload for
    the first (size, 0) pair (size 500KB-50MB) whose following entries chain by
    consecutive offsets. Returns (tracks, sample_rate, num_channels)."""
    if len(rws_data) < 0x100:
        return [], 48000, 2

    # Validate container chunk
    ctype = struct.unpack_from('<I', rws_data, 0)[0]
    if ctype != 0x080D:
        return [], 48000, 2

    # Validate header chunk
    htype = struct.unpack_from('<I', rws_data, 12)[0]
    hsize = struct.unpack_from('<I', rws_data, 16)[0]
    if htype != 0x080E or hsize == 0:
        return [], 48000, 2

    # audio_data chunk
    data_chunk_off = 24 + hsize
    if data_chunk_off + 12 > len(rws_data):
        return [], 48000, 2

    dtype = struct.unpack_from('<I', rws_data, data_chunk_off)[0]
    dsize = struct.unpack_from('<I', rws_data, data_chunk_off + 4)[0]
    if dtype != 0x080F:
        return [], 48000, 2

    data_payload_off = data_chunk_off + 12

    # Known layout from hex analysis:
    #   Entry stride: 32 bytes; size field at entry+24, offset field at entry+28
    #   Track 0 offset = 0, track 1 offset = track 0 size, etc.
    ENTRY_SIZE = 32
    SIZE_WITHIN = 24
    OFF_WITHIN = 28

    # Search the header payload for the first track's (size, 0) pair
    # The size should be between 500KB and 50MB, followed by exactly 0
    header_end = min(24 + hsize, len(rws_data))

    found_table_start = None
    for scan in range(24, header_end - 32, 4):
        candidate_size = struct.unpack_from('<I', rws_data, scan)[0]
        candidate_off = struct.unpack_from('<I', rws_data, scan + 4)[0]

        # Track 0: plausible size (500KB-50MB) and offset exactly 0
        if candidate_off == 0 and 500000 < candidate_size < 50000000:
            # This (scan) is where the size field is
            # The entry containing this starts at scan - SIZE_WITHIN
            entry0_start = scan - SIZE_WITHIN
            if entry0_start < 24:
                continue

            # Validate entry 1: should be at entry0_start + ENTRY_SIZE
            e1_start = entry0_start + ENTRY_SIZE
            if e1_start + 32 > header_end:
                continue

            e1_size = struct.unpack_from('<I', rws_data, e1_start + SIZE_WITHIN)[0]
            e1_off = struct.unpack_from('<I', rws_data, e1_start + OFF_WITHIN)[0]

            # Entry 1 offset should equal entry 0 size
            if e1_off == candidate_size and 500000 < e1_size < 50000000:
                # Double-check with entry 2
                e2_start = e1_start + ENTRY_SIZE
                if e2_start + 32 <= header_end:
                    e2_off = struct.unpack_from('<I', rws_data, e2_start + OFF_WITHIN)[0]
                    if e2_off == e1_off + e1_size:
                        found_table_start = entry0_start
                        break
                else:
                    found_table_start = entry0_start
                    break

    if found_table_start is None:
        return [], 24000, 2

    # Scan all entries from the found table start
    tracks = []
    expected_offset = 0
    max_entries = 50

    for i in range(max_entries):
        entry_off = found_table_start + i * ENTRY_SIZE
        if entry_off + ENTRY_SIZE > header_end:
            break

        trk_size = struct.unpack_from('<I', rws_data, entry_off + SIZE_WITHIN)[0]
        trk_offset = struct.unpack_from('<I', rws_data, entry_off + OFF_WITHIN)[0]

        if trk_offset != expected_offset:
            break
        if trk_size == 0 or trk_size > dsize:
            break

        abs_off = data_payload_off + trk_offset
        if abs_off + trk_size > len(rws_data):
            break

        tracks.append((abs_off, trk_size))
        expected_offset += trk_size

    # Burnout 3 EATRAX uses stereo audio in 2048-byte blocks (LLRR super-blocks).
    sample_rate = 32000
    num_channels = 2  # MUST be stereo — the game expects L/R interleaved blocks

    return tracks, sample_rate, num_channels
