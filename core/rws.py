"""RenderWare Stream (.RWS) parsing for Burnout 3's EATRAX audio containers."""
import struct


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
