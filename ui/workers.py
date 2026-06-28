"""Background QObject workers: in-place ISO injection and the portable-ISO build.

The heavy lifting lives in core/ (rws parsing, the encoder, the audio pipeline and the
portable-ISO builder); these workers just orchestrate it off the GUI thread and stream
progress/log lines back via Qt signals."""
import os, struct, subprocess, shutil, tempfile, html as html_mod
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import Signal, QObject

from core.constants import KNOWN_DISC_IDS, LOUDNORM_TARGET, AUDIO_RESAMPLE_FILTER
from core import rws, portable_iso
from core.audio import _loudnorm_filter, _loudnorm_measure
from core.psx_adpcm import encode_psx_adpcm_sized, adpcm_slot_duration


# ─── In-place injection worker (replace any of the 44 tracks in the ISO) ────
class InjectionWorker(QObject):
    progress = Signal(float, str)
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, iso_path, assignments, output_iso, metadata=None):
        super().__init__()
        self.iso_path = iso_path
        self.assignments = assignments
        self.output_iso = output_iso
        self.metadata = metadata or {}  # slot_id -> (title, artist, album)

    def _patch_globalus_bin(self, output_iso, iso_data, metadata):
        """Patch song names IN PLACE, at fixed byte length.

        The game finds each name through a fixed pointer table (u32 offsets, e.g.
        the music block at 0x784 points at the strings near 0xB700). Repacking the
        strings to different lengths would move them out from under those pointers,
        which is why the old 'dynamic redistribution' showed garbled / mismatched
        names. So every field is written at its ORIGINAL offset, truncated to the
        original byte length and null-padded — offsets never move, pointers stay
        valid. Names longer than the original field are truncated (matches the
        per-field character limits shown in the UI)."""
        offset, size = rws.find_file_offset_iso9660(iso_data, "GLOBALUS.BIN")
        if not offset or not size:
            self.log_line.emit("  ⚠ GLOBALUS.BIN not found, skipping name patching")
            return

        with open(output_iso, 'r+b') as f:
            f.seek(offset)
            gdata = bytearray(f.read(size))

        def parse_strings(d, start, end):
            table = []
            pos = start
            while pos < min(len(d), end):
                while pos < len(d)-1 and d[pos]==0 and d[pos+1]==0:
                    pos += 2
                if pos >= min(len(d), end): break
                s_start = pos
                while pos < len(d)-1:
                    if d[pos]==0 and d[pos+1]==0: break
                    pos += 2
                text = d[s_start:pos].decode('utf-16-le', errors='replace')
                table.append((s_start, text, pos - s_start))
                pos += 2
            return table

        def write_field(s_off, max_bytes, text):
            """Overwrite the field at s_off with text truncated to max_bytes
            (whole UTF-16 code units) and null-padded. The string's offset and the
            terminator after it are never touched."""
            enc = text.encode('utf-16-le')[:max_bytes]
            enc = enc[:len(enc) // 2 * 2]
            gdata[s_off:s_off + len(enc)] = enc
            if len(enc) < max_bytes:
                gdata[s_off + len(enc):s_off + max_bytes] = b'\x00' * (max_bytes - len(enc))

        def patch_slot(st_table, base, slot_id):
            """Patch one slot's (title, album, artist) triple in place.
            On-disk order is title, album, artist; metadata is (title, artist, album)."""
            if base < 0 or base + 2 >= len(st_table):
                return 0
            title, artist, album = metadata[slot_id]
            n = 0
            for field, val in ((0, title), (1, album), (2, artist)):
                if not val:
                    continue
                s_off, _, blen = st_table[base + field]
                write_field(s_off, blen, val)
                n += 1
            return n

        patched = 0

        # ═══ Slots 1-40: main region, strings index 3+, groups of 3 ═══
        st = parse_strings(gdata, 0xB700, 0xD000)
        for slot_id in sorted(s for s in metadata if 1 <= s <= 40):
            patched += patch_slot(st, 3 + (slot_id - 1) * 3, slot_id)  # MUSIC_START=3

        # ═══ Slots 41-44: second region at 0x2C004 ═══
        slots_41_44 = sorted(s for s in metadata if 41 <= s <= 44)
        if slots_41_44:
            st2 = parse_strings(gdata, 0x2C004, 0x2C200)
            for slot_id in slots_41_44:
                patched += patch_slot(st2, (slot_id - 41) * 3, slot_id)

        if patched > 0:
            with open(output_iso, 'r+b') as f:
                f.seek(offset)
                f.write(gdata)
            self.log_line.emit(f"  ✓ Patched {patched} song-name fields (in-place, fixed length)")
        else:
            self.log_line.emit("  ↳ No song names to patch")

    def run(self):
        tmp = None
        try:
            tmp = tempfile.mkdtemp(prefix="burnout3_")

            if not os.path.isfile(self.iso_path):
                raise Exception(f"ISO not found: {self.iso_path}")
            for sid, src in self.assignments.items():
                if not os.path.isfile(src):
                    raise Exception(f"Audio not found: {src}")

            iso_size = os.path.getsize(self.iso_path)
            out_dir = os.path.dirname(os.path.abspath(self.output_iso)) or '.'
            try:
                usage = shutil.disk_usage(out_dir)
                free = usage.free
            except (OSError, AttributeError):
                free = float('inf')
            if free < iso_size + 200*1048576:
                raise Exception(
                    f"Not enough space: {free//1048576} MB free, "
                    f"~{(iso_size+200*1048576)//1048576} MB needed"
                )

            total_steps = len(self.assignments) * 2 + 4
            step = 0

            # ═══ STEP 1: Copy ISO ═══
            self.progress.emit(step/total_steps, "Copying ISO...")
            self.log_line.emit("▶ Copying ISO for in-place patching")
            shutil.copy2(self.iso_path, self.output_iso)
            self.log_line.emit(f"✓ Copy: {os.path.basename(self.output_iso)}")
            step += 1

            # ═══ STEP 2: Parse ISO ═══
            self.progress.emit(step/total_steps, "Analyzing EATRAX...")
            self.log_line.emit("▶ Parsing ISO9660 + RWS containers")

            with open(self.output_iso, 'rb') as f:
                iso_data = bytearray(f.read())

            for did, region in KNOWN_DISC_IDS.items():
                if did.encode() in iso_data:
                    self.log_line.emit(f"✓ Disc ID: {did} — {region}")
                    break

            # Parse both EATRAX files
            eatrax_info = {}
            for rws_name in ["_EATRAX0.RWS", "_EATRAX1.RWS"]:
                offset, size = rws.find_file_offset_iso9660(iso_data, rws_name)
                if offset and size:
                    rws_slice = bytes(iso_data[offset:offset+size])
                    tracks, sr, ch = rws.parse_rws_tracks(rws_slice)
                    hsize = struct.unpack_from('<I', rws_slice, 16)[0]
                    eatrax_info[rws_name] = {
                        'iso_offset': offset,
                        'file_size': size,
                        'tracks': tracks,
                        'hsize': hsize,
                        'data_payload_off': 24 + hsize + 12,  # after header + data chunk hdr
                        'total_audio': sum(s for _, s in tracks),
                    }
                    self.log_line.emit(
                        f"✓ {rws_name} @ 0x{offset:X} ({size/1048576:.1f} MB) "
                        f"— {len(tracks)} tracks"
                    )

            if not eatrax_info:
                raise Exception("No EATRAX found in ISO")

            step += 1

            # ═══ STEP 3: Convert all songs to PCM (parallel, loudness-matched) ═══
            self.log_line.emit("▶ Converting songs to PCM (parallel, loudness-matched)...")

            # Split assignments by EATRAX: slots 1-22 → EATRAX0, 23-44 → EATRAX1
            ea0_assignments = {k: v for k, v in self.assignments.items() if k <= 22}
            ea1_assignments = {k: v for k, v in self.assignments.items() if k > 22}

            n_cores = os.cpu_count() or 4

            def _convert(source, out_raw, loud=None, extra_pre="", duration=None):
                """Loudness-measure (pass 1) + convert → s16le 32k stereo. Thread-safe:
                only spawns ffmpeg subprocesses and touches its own out_raw file."""
                if loud is None:
                    loud = _loudnorm_filter(LOUDNORM_TARGET,
                                            _loudnorm_measure(source, LOUDNORM_TARGET))
                cmd = ["ffmpeg", "-y", "-i", source]
                if duration is not None:
                    cmd += ["-t", str(duration)]
                cmd += ["-af", f"{loud},{extra_pre}{AUDIO_RESAMPLE_FILTER}",
                        "-f", "s16le", "-acodec", "pcm_s16le",
                        "-ar", "32000", "-ac", "2", out_raw]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                ok = r.returncode == 0 and os.path.isfile(out_raw) and os.path.getsize(out_raw) > 0
                return ok, loud

            def _phase_a(item):
                slot_id, source = item
                src_name = os.path.basename(source)
                temp_raw = os.path.join(tmp, f"t{slot_id:02d}.raw")
                ok, loud = _convert(source, temp_raw)
                if not ok:
                    return slot_id, None, loud, src_name
                pcm_size = os.path.getsize(temp_raw)
                n_per_ch = (pcm_size // 2) // 2  # s16le stereo
                n_superblocks = (n_per_ch + 7167) // 7168
                adpcm_size = n_superblocks * 8192
                return (slot_id, (temp_raw, adpcm_size, src_name, adpcm_slot_duration(adpcm_size)),
                        loud, src_name)

            encoded = {}            # slot_id -> (temp_raw, adpcm_size, src_name, duration)
            loud_filter_by_slot = {}
            n_assign = len(self.assignments)
            with ThreadPoolExecutor(max_workers=max(1, min(n_cores, n_assign))) as ex:
                for fut in as_completed([ex.submit(_phase_a, it) for it in self.assignments.items()]):
                    slot_id, data, loud, src_name = fut.result()
                    loud_filter_by_slot[slot_id] = loud
                    if data:
                        encoded[slot_id] = data
                        self.log_line.emit(
                            f"  ✓ Slot {slot_id:02d}: {src_name} → {data[1]//1024}KB ({data[3]:.0f}s)"
                        )
                    else:
                        self.log_line.emit(f"✗ Slot {slot_id:02d}: ffmpeg error")
                    step += 1
                    self.progress.emit(step/total_steps, f"Converting ({len(encoded)}/{n_assign})...")

            if not encoded:
                raise Exception("No tracks were converted")

            # ═══ STEP 4: Plan track layout + proportional scaling (per EATRAX) ═══
            self.progress.emit(step/total_steps, "Planning track layout...")
            self.log_line.emit("▶ Planning layout and scaling")

            plans = {}        # eatrax_name -> (new_track_sizes, new_track_data)
            trunc_jobs = []   # scaled tracks that need an ffmpeg re-encode (fade-out + trim)

            for eatrax_name, assignments, slot_start in [
                ("_EATRAX0.RWS", ea0_assignments, 1),
                ("_EATRAX1.RWS", ea1_assignments, 23),
            ]:
                if eatrax_name not in eatrax_info or not assignments:
                    continue

                ea = eatrax_info[eatrax_name]
                orig_tracks = ea['tracks']
                n_orig = len(orig_tracks)
                available_audio = ea['total_audio']

                assigned_need = {sid: encoded[sid][1] for sid in assignments if sid in encoded}
                total_needed = sum(assigned_need.values())

                total_unassigned = sum(orig_tracks[i][1] for i in range(n_orig)
                                       if (slot_start + i) not in assignments)
                space_for_custom = available_audio - total_unassigned
                self.log_line.emit(
                    f"  {eatrax_name}: {space_for_custom//1024}KB available for "
                    f"{len(assigned_need)} custom tracks (need {total_needed//1024}KB)"
                )

                # If songs exceed the fixed space, scale all proportionally with fade-out
                if total_needed > space_for_custom:
                    overflow = total_needed - space_for_custom
                    self.log_line.emit(
                        f"  ⚠ Songs exceed space by {overflow//1024}KB, scaling down proportionally"
                    )
                    scale = space_for_custom / total_needed
                    for sid in assigned_need:
                        ns = (int(assigned_need[sid] * scale) // 8192) * 8192  # align super-block
                        assigned_need[sid] = max(8192, ns)
                    # Fine-tune: if still over, trim the largest one super-block at a time
                    total_needed = sum(assigned_need.values())
                    while total_needed > space_for_custom:
                        biggest = max(assigned_need, key=assigned_need.get)
                        assigned_need[biggest] = max(8192, assigned_need[biggest] - 8192)
                        total_needed = sum(assigned_need.values())

                    # Queue the truncated tracks for a parallel fade-out re-encode
                    for sid in sorted(assigned_need):
                        _, orig_adpcm_size, src_name, _ = encoded[sid]
                        new_size = assigned_need[sid]
                        if new_size >= orig_adpcm_size:
                            continue  # no truncation needed
                        new_dur = adpcm_slot_duration(new_size)
                        fade_dur = 3
                        trunc_jobs.append({
                            'sid': sid, 'source': self.assignments[sid],
                            'raw': os.path.join(tmp, f"t{sid:02d}_trunc.raw"),
                            'size': new_size, 'dur': new_dur, 'src_name': src_name,
                            'fade_start': max(0, new_dur - fade_dur), 'fade_dur': fade_dur,
                            'loud': loud_filter_by_slot.get(sid) or f"loudnorm={LOUDNORM_TARGET}",
                        })

                new_track_sizes, new_track_data = [], []
                for i in range(n_orig):
                    sid = slot_start + i
                    if sid in assigned_need:
                        new_track_sizes.append(assigned_need[sid]); new_track_data.append((sid, True))
                    else:
                        new_track_sizes.append(orig_tracks[i][1]); new_track_data.append((sid, False))
                plans[eatrax_name] = (new_track_sizes, new_track_data)

            # Re-encode scaled tracks in parallel (fade-out + trim)
            if trunc_jobs:
                self.log_line.emit(f"▶ Re-encoding {len(trunc_jobs)} scaled tracks (parallel)...")

                def _do_trunc(job):
                    fade = f"afade=t=out:st={job['fade_start']:.1f}:d={job['fade_dur']},"
                    ok, _ = _convert(job['source'], job['raw'], loud=job['loud'],
                                     extra_pre=fade, duration=job['dur'])
                    return job, ok

                with ThreadPoolExecutor(max_workers=max(1, min(n_cores, len(trunc_jobs)))) as ex:
                    for fut in as_completed([ex.submit(_do_trunc, j) for j in trunc_jobs]):
                        job, ok = fut.result()
                        if ok:
                            encoded[job['sid']] = (job['raw'], job['size'], job['src_name'], job['dur'])
                            self.log_line.emit(
                                f"  ↳ Slot {job['sid']:02d}: {job['src_name']} scaled to "
                                f"{job['dur']:.0f}s ({job['size']//1024}KB)"
                            )

            # ═══ STEP 5: Encode all custom tracks to PS-ADPCM in parallel ═══
            self.progress.emit(step/total_steps, "Encoding PS-ADPCM...")
            self.log_line.emit("▶ Encoding PS-ADPCM (parallel — all cores)")

            encode_targets = {}  # slot_id -> target byte size
            for sizes, data in plans.values():
                for (sid, is_custom), sz in zip(data, sizes):
                    if is_custom and sid in encoded:
                        encode_targets[sid] = sz

            adpcm_by_slot = {}

            def _encode_one(sid):
                with open(encoded[sid][0], 'rb') as af:
                    pcm = af.read()
                return sid, encode_psx_adpcm_sized(pcm, encode_targets[sid])

            if encode_targets:
                done_enc = 0
                with ThreadPoolExecutor(max_workers=max(1, min(n_cores, len(encode_targets)))) as ex:
                    for fut in as_completed([ex.submit(_encode_one, sid) for sid in encode_targets]):
                        sid, audio = fut.result()
                        adpcm_by_slot[sid] = audio
                        done_enc += 1
                        self.progress.emit(step/total_steps,
                                           f"Encoding ({done_enc}/{len(encode_targets)})...")
            step += 1

            # ═══ STEP 6: Write patched ISO (sequential, in-order) ═══
            self.log_line.emit("▶ Writing patched EATRAX containers")
            replaced = 0
            with open(self.output_iso, 'r+b') as iso_out:
                for eatrax_name, assignments, slot_start in [
                    ("_EATRAX0.RWS", ea0_assignments, 1),
                    ("_EATRAX1.RWS", ea1_assignments, 23),
                ]:
                    if eatrax_name not in plans:
                        continue

                    ea = eatrax_info[eatrax_name]
                    orig_tracks = ea['tracks']
                    n_orig = len(orig_tracks)
                    new_track_sizes, new_track_data = plans[eatrax_name]

                    # Find the track table in the RWS header to patch it
                    iso_out.seek(ea['iso_offset'])
                    rws_header = bytearray(iso_out.read(24 + ea['hsize']))

                    header_end = len(rws_header)
                    ENTRY_SIZE = 32
                    SIZE_WITHIN = 24
                    OFF_WITHIN = 28

                    found_table = None
                    for scan in range(24, header_end - 32, 4):
                        cs = struct.unpack_from('<I', rws_header, scan)[0]
                        co = struct.unpack_from('<I', rws_header, scan + 4)[0]
                        if co == 0 and 500000 < cs < 50000000:
                            entry0_start = scan - SIZE_WITHIN
                            if entry0_start < 24: continue
                            e1s = struct.unpack_from('<I', rws_header, entry0_start + ENTRY_SIZE + SIZE_WITHIN)[0]
                            e1o = struct.unpack_from('<I', rws_header, entry0_start + ENTRY_SIZE + OFF_WITHIN)[0]
                            if e1o == cs and 500000 < e1s < 50000000:
                                found_table = entry0_start
                                break

                    if found_table is None:
                        self.log_line.emit(f"✗ {eatrax_name}: track table not found")
                        continue

                    # Patch track table with new sizes and offsets
                    cumulative = 0
                    for i in range(n_orig):
                        entry_off = found_table + i * ENTRY_SIZE
                        if entry_off + ENTRY_SIZE > header_end: break
                        struct.pack_into('<I', rws_header, entry_off + SIZE_WITHIN, new_track_sizes[i])
                        struct.pack_into('<I', rws_header, entry_off + OFF_WITHIN, cumulative)
                        cumulative += new_track_sizes[i]

                    # Update container size field
                    new_total_audio = sum(new_track_sizes)
                    new_container_payload = ea['hsize'] + 12 + new_total_audio
                    struct.pack_into('<I', rws_header, 4, new_container_payload)

                    # Pre-read ALL original track data before we overwrite anything
                    orig_track_data = {}
                    for i, (sid, is_custom) in enumerate(new_track_data):
                        if not is_custom:
                            orig_off, orig_size = orig_tracks[i]
                            iso_out.seek(ea['iso_offset'] + orig_off)
                            orig_track_data[i] = iso_out.read(orig_size)

                    # Write patched header
                    iso_out.seek(ea['iso_offset'])
                    iso_out.write(rws_header)

                    # Write audio data chunk header with new size
                    iso_out.write(struct.pack('<III', 0x080F, new_total_audio, 0x1C020009))

                    # Write track audio data in order (custom = pre-encoded, else original)
                    for i, (sid, is_custom) in enumerate(new_track_data):
                        self.progress.emit(step/total_steps, f"Writing track {sid}...")

                        if is_custom:
                            audio = adpcm_by_slot.get(sid)
                            if audio is None:
                                # Defensive fallback: encode synchronously
                                with open(encoded[sid][0], 'rb') as af:
                                    audio = encode_psx_adpcm_sized(af.read(), new_track_sizes[i])
                            iso_out.write(audio)
                            self.log_line.emit(
                                f"✓ Slot {sid:02d}: {html_mod.escape(encoded[sid][2])} → "
                                f"{new_track_sizes[i]//1024}KB ({adpcm_slot_duration(new_track_sizes[i]):.0f}s)"
                            )
                            replaced += 1
                        else:
                            # Write pre-read original track data
                            iso_out.write(orig_track_data[i])

                    # Zero-pad any remaining space
                    actual_file_size = 24 + ea['hsize'] + 12 + new_total_audio
                    if actual_file_size < ea['file_size']:
                        remaining = ea['file_size'] - actual_file_size
                        zero_chunk = b'\x00' * min(1048576, remaining)
                        w = 0
                        while w < remaining:
                            to_write = min(len(zero_chunk), remaining - w)
                            iso_out.write(zero_chunk[:to_write])
                            w += to_write

                    self.log_line.emit(
                        f"✓ {eatrax_name}: {len(assignments)} custom tracks, "
                        f"{new_total_audio/1048576:.1f}MB used of {ea['total_audio']/1048576:.1f}MB"
                    )

            if replaced == 0:
                if os.path.isfile(self.output_iso):
                    os.remove(self.output_iso)
                raise Exception("No tracks were patched")

            # ═══ STEP 5: Patch song names in GLOBALUS.BIN ═══
            if self.metadata:
                self.log_line.emit("▶ Patching song names in GLOBALUS.BIN...")
                self._patch_globalus_bin(self.output_iso, iso_data, self.metadata)

            self.progress.emit(1.0, "Completed!")
            self.log_line.emit(f"✓ {replaced} tracks patched!")
            self.log_line.emit(f"✓ {self.output_iso}")
            self.finished.emit(True, f"Done! {replaced} tracks.\n{self.output_iso}")

        except subprocess.TimeoutExpired:
            self.finished.emit(False, "Timeout: ffmpeg took too long.")
        except OSError as e:
            self.finished.emit(False, f"I/O Error: {e}")
        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            if tmp and os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)


# ─── Portable ISO Worker — bake the whole soundtrack into a self-contained disc ──
class PortableIsoWorker(QObject):
    """Bake a self-contained ISO: ≤44 renames via globalus only; 45..176 bakes the EA-TRAX
    expansion (cave + hook + count + metadata + construct patch) into the ELF, CRC-neutralised."""
    log_line = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, clean_iso, out_iso, slots, cave_pnach=None):
        super().__init__()
        self.clean_iso = clean_iso; self.out_iso = out_iso; self.slots = slots; self.cave_pnach = cave_pnach

    def run(self):
        try:
            res = portable_iso.build_portable_iso(self.clean_iso, self.out_iso, self.slots,
                                                  log=self.log_line.emit, progress=self.log_line.emit,
                                                  cave_pnach=self.cave_pnach)
            mb = res["size"] // (1024 * 1024)
            files = ", ".join(f"_eatrax{f}.rws" for f in res["files"])
            msg = (f"Portable ISO built — {res['count']} tracks ({res['custom']} custom, {mb} MB).\n"
                   f"{self.out_iso}\n\n"
                   "Self-contained — boots in PCSX2, Android (AetherSX2/NetherSX2) and real PS2: "
                   "just load this ISO. Everything is baked into the disc.")
            self.log_line.emit("✓ Done.")
            self.finished.emit(True, msg)
        except Exception as e:
            import traceback
            self.finished.emit(False, f"{e}\n{traceback.format_exc()[-600:]}")
