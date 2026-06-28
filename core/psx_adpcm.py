"""PS-ADPCM encoder for Burnout 3: Takedown (C-accelerated via ctypes).

Auto-compiles the C encoder (psxadpcm.c, at the repo root) on first run for a
~100× speedup; falls back to a pure-Python encoder if gcc is unavailable.

Proven format:
  - LLRR layout: 8192-byte super-blocks = L[2048] L[2048] R[2048] R[2048]
  - Nibble order: first sample in LOW nibble, second in HIGH
  - All block flags = 0x02; 5 filters × 13 shifts full search
"""
import os, sys, ctypes, subprocess

_c_lib = None

# psxadpcm.c lives at the repo root (and is bundled there in a PyInstaller build,
# where sys._MEIPASS is the extraction root).
_BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _compile_c_encoder():
    """Compile psxadpcm.c → libpsxenc.so on first run."""
    global _c_lib
    if _c_lib is not None:
        return _c_lib

    so_path = os.path.join(_BASE, "libpsxenc.so")
    c_path = os.path.join(_BASE, "psxadpcm.c")

    # Compile if .so is missing or .c is newer
    need_compile = not os.path.isfile(so_path)
    if os.path.isfile(so_path) and os.path.isfile(c_path):
        if os.path.getmtime(c_path) > os.path.getmtime(so_path):
            need_compile = True

    if need_compile and os.path.isfile(c_path):
        # Try aggressive flags first, fall back to plain -O3 if the toolchain
        # rejects them (e.g. -march=native unsupported on some cross compilers).
        flag_sets = [
            ["-O3", "-march=native", "-ffast-math", "-funroll-loops"],
            ["-O3"],
        ]
        compiled = False
        for flags in flag_sets:
            try:
                r = subprocess.run(
                    ["gcc", *flags, "-shared", "-fPIC", "-o", so_path, c_path, "-lm"],
                    capture_output=True, text=True, timeout=60
                )
                if r.returncode == 0:
                    compiled = True
                    break
            except Exception:
                continue
        if not compiled:
            return None

    if os.path.isfile(so_path):
        try:
            lib = ctypes.CDLL(so_path)
            lib.encode_burnout3_adpcm.restype = ctypes.c_int
            lib.encode_burnout3_adpcm.argtypes = [
                ctypes.POINTER(ctypes.c_short), ctypes.c_int,
                ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int
            ]
            _c_lib = lib
            return lib
        except Exception:
            return None
    return None


def _encode_python_fallback(pcm_bytes, slot_size):
    """Pure Python encoder — slower but always works (no numpy/gcc needed). Mirrors
    psxadpcm.c exactly: a full 5-filter × 13-shift search per block (no heuristic) with
    integer-accurate predictor feedback, so it yields the same quality as the C encoder
    (just much slower — install gcc for the fast path)."""
    import array
    COEFS = ((0.0, 0.0), (0.9375, 0.0), (1.796875, -0.8125),
             (1.53125, -0.859375), (1.90625, -0.9375))
    SCALES = (4096.0, 2048.0, 1024.0, 512.0, 256.0, 128.0, 64.0,
              32.0, 16.0, 8.0, 4.0, 2.0, 1.0)
    samples = array.array('h')  # signed 16-bit
    samples.frombytes(pcm_bytes[:len(pcm_bytes) - (len(pcm_bytes) % 2)])
    left = samples[0::2]
    right = samples[1::2]

    buf = bytearray(slot_size)
    for i in range(0, slot_size, 16):
        buf[i] = 0x0C; buf[i + 1] = 0x02

    def encode_ch(src, ch_offset):
        idx = 0; p1 = 0.0; p2 = 0.0
        src_len = len(src)
        blk = [0.0] * 28
        for sblock in range(0, slot_size, 8192):
            for sub in range(2):
                for block_i in range(0, 2048, 16):
                    boff = sblock + ch_offset + sub * 2048 + block_i
                    if boff + 16 > slot_size:
                        return
                    for i in range(28):
                        blk[i] = src[idx + i] if idx + i < src_len else 0.0
                    idx += 28
                    best_err = 1e30; best_filt = 0; best_shift = 0
                    best_nibs = [0] * 28; best_p1 = p1; best_p2 = p2
                    done = False
                    for filt in range(5):                       # full search (matches the C)
                        c1, c2 = COEFS[filt]
                        for shift in range(13):
                            scale = SCALES[shift]
                            err = 0.0; tp1 = p1; tp2 = p2; nibs = [0] * 28
                            for i in range(28):
                                s = blk[i]
                                pred = tp1 * c1 + tp2 * c2
                                raw = (s - pred) / scale
                                nib = int(raw + (0.5 if raw >= 0 else -0.5))
                                if nib < -8: nib = -8
                                elif nib > 7: nib = 7
                                nibs[i] = nib
                                dec = nib * scale + pred
                                dec = float(int(dec + 0.5) if dec >= 0 else int(dec - 0.5))
                                if dec > 32767.0: dec = 32767.0
                                elif dec < -32768.0: dec = -32768.0
                                err += (s - dec) * (s - dec)
                                tp2 = tp1; tp1 = dec
                            if err < best_err:
                                best_err = err; best_filt = filt; best_shift = shift
                                best_nibs = nibs; best_p1 = tp1; best_p2 = tp2
                                if err < 1.0:                   # near-perfect — early exit
                                    done = True; break
                        if done:
                            break
                    p1 = best_p1; p2 = best_p2
                    buf[boff] = (best_filt << 4) | best_shift; buf[boff + 1] = 0x02
                    for i in range(28):
                        j = i // 2
                        if i % 2 == 0: buf[boff + 2 + j] = best_nibs[i] & 0xF
                        else: buf[boff + 2 + j] |= (best_nibs[i] & 0xF) << 4

    encode_ch(left, 0)
    encode_ch(right, 4096)
    return bytes(buf)


def adpcm_slot_duration(slot_bytes, sample_rate=32000):
    """Duration of a slot. LLRR: 8192 bytes = 4096/channel = 7168 samples/ch."""
    n_superblocks = slot_bytes / 8192
    samples_per_ch = n_superblocks * (4096 / 16 * 28)
    return samples_per_ch / sample_rate


def encode_psx_adpcm_sized(pcm_s16le_stereo, output_size):
    """Encode PCM to PS-ADPCM with exact output_size bytes."""
    pcm_bytes = pcm_s16le_stereo[:len(pcm_s16le_stereo) - (len(pcm_s16le_stereo) % 2)]
    n_samples = len(pcm_bytes) // 2

    lib = _compile_c_encoder()
    if lib is not None:
        pcm_arr = (ctypes.c_short * n_samples)()
        ctypes.memmove(pcm_arr, pcm_bytes, len(pcm_bytes))
        out_arr = (ctypes.c_ubyte * output_size)()
        lib.encode_burnout3_adpcm(pcm_arr, n_samples, out_arr, output_size)
        return bytes(out_arr)

    return _encode_python_fallback(pcm_bytes, output_size)
