#!/usr/bin/env python3
"""
PS-ADPCM round-trip diagnostic for Burnout 3.

    python3 research/adpcm_roundtrip.py <song> [out_dir]

Runs the EXACT GUI pipeline (loudnorm + soxr resample -> 32 kHz s16le stereo),
encodes to PS-ADPCM (the real psxadpcm.c encoder), decodes it back (psxdec.c,
bit-faithful to the PS2 SPU), and compares. It tells you whether an audible
"stutter / eaten chunk" comes from the ENCODER (round-trip already glitches) or
the GAME/streaming (round-trip is clean but it stutters in-game).

Outputs in <out_dir> (default ./adpcm_debug):
  - orig.wav            the encoder's INPUT (post loudnorm+resample)
  - decoded.wav         encode -> decode (predictor carried = standard)
  - decoded_reset_sb.wav     decode resetting the predictor per super-block
  - decoded_reset_2048.wav   decode resetting per 2048-byte sub-block
  - *_spec.png          spectrograms (ffmpeg showspectrumpic), if ffmpeg has it
  - a printed report of overall error + the worst-diverging time windows

Listen to decoded.wav: if it stutters like in-game -> the encoder is the bug
(the report points at the worst windows). If decoded.wav is clean but the game
stutters, compare decoded_reset_*.wav — a match there means the game resets the
predictor at that boundary (so the encoder must reset there too); otherwise the
in-game stutter is streaming/IO (disc can't keep up), not the audio data.
"""
import os, sys, ctypes, subprocess, tempfile, wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import numpy as np
import burnout3_gui as b3          # exact encoder + loudnorm + resample pipeline

SR = 32000


def _compile_decoder():
    so = os.path.join(HERE, "libpsxdec.so")
    c  = os.path.join(HERE, "psxdec.c")
    if (not os.path.exists(so)) or os.path.getmtime(c) > os.path.getmtime(so):
        subprocess.run(["gcc", "-O3", "-shared", "-fPIC", "-o", so, c, "-lm"], check=True)
    lib = ctypes.CDLL(so)
    lib.decode_llrr.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_short), ctypes.c_int]
    lib.decode_llrr.restype = ctypes.c_int
    return lib


def pipeline_pcm(song):
    """song -> the encoder's input PCM (post loudnorm+resample), exactly like the GUI."""
    loud = b3._loudnorm_filter(b3.LOUDNORM_TARGET, b3._loudnorm_measure(song, b3.LOUDNORM_TARGET))
    raw = tempfile.mktemp(suffix=".raw")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", song,
                    "-af", f"{loud},{b3.AUDIO_RESAMPLE_FILTER}",
                    "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(SR), "-ac", "2", raw],
                   check=True)
    pcm = open(raw, "rb").read(); os.remove(raw)
    return pcm[: len(pcm) - (len(pcm) % 4)]          # whole stereo frames


def decode(lib, slot, mode):
    nsb = len(slot) // 8192
    out = (ctypes.c_short * (nsb * 7168 * 2))()
    lib.decode_llrr(slot, len(slot), out, mode)
    return np.frombuffer(out, dtype=np.int16)


def write_wav(path, pcm_i16):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm_i16.astype("<i2").tobytes())


def spectrogram(wav, png):
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav,
                        "-lavfi", "showspectrumpic=s=1400x520:legend=1:gain=3", png],
                       check=True, timeout=120)
        return os.path.exists(png)
    except Exception:
        return False


def report(orig, dec, name):
    """Per-channel error + the worst-diverging 20 ms windows."""
    n = min(len(orig), len(dec)); n -= n % 2
    o = orig[:n].astype(np.float64); d = dec[:n].astype(np.float64)
    diff = o - d
    rms_o = np.sqrt(np.mean(o * o)) or 1.0
    rms_e = np.sqrt(np.mean(diff * diff))
    peak  = np.max(np.abs(diff))
    snr = 20 * np.log10(rms_o / rms_e) if rms_e > 0 else float("inf")
    print(f"\n=== {name} vs orig ===")
    print(f"  samples: {n//2}/ch  RMS error: {rms_e:.1f}  peak error: {peak:.0f}  SNR: {snr:.1f} dB")
    # window analysis (per stereo frame -> mono mix for locating)
    fo = o.reshape(-1, 2).mean(1); fe = diff.reshape(-1, 2).mean(1)
    win = int(0.020 * SR)
    nb = len(fo) // win
    if nb:
        eo = fo[:nb * win].reshape(nb, win); ee = fe[:nb * win].reshape(nb, win)
        we = np.sqrt((ee ** 2).mean(1)); wo = np.sqrt((eo ** 2).mean(1)) + 1.0
        ratio = we / wo                                   # local error relative to signal
        worst = np.argsort(ratio)[::-1][:8]
        print("  worst-diverging windows (likely the audible glitches):")
        for w in sorted(worst):
            t = w * win / SR
            print(f"    t={t:6.2f}s  err/sig={ratio[w]:5.2f}  err_rms={we[w]:6.0f}  sig_rms={wo[w]:6.0f}")
    return snr


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    song = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.getcwd(), "adpcm_debug")
    os.makedirs(out, exist_ok=True)
    lib = _compile_decoder()

    print(f"[1/4] pipeline (loudnorm + resample) on {os.path.basename(song)} ...")
    pcm = pipeline_pcm(song)
    orig = np.frombuffer(pcm, dtype=np.int16)
    n_per_ch = len(orig) // 2
    size = ((n_per_ch + 7167) // 7168) * 8192
    print(f"      {n_per_ch} samples/ch ({n_per_ch/SR:.1f}s) -> slot {size} B ({size//8192} super-blocks)")

    print("[2/4] encode (psxadpcm.c) ...")
    slot = b3.encode_psx_adpcm_sized(pcm, size)

    print("[3/4] decode (psxdec.c) ...")
    dec_carry = decode(lib, slot, 0)[: len(orig)]
    dec_sb    = decode(lib, slot, 1)[: len(orig)]
    dec_2048  = decode(lib, slot, 2)[: len(orig)]

    print("[4/4] write WAVs + spectrograms ...")
    write_wav(os.path.join(out, "orig.wav"), orig)
    write_wav(os.path.join(out, "decoded.wav"), dec_carry)
    write_wav(os.path.join(out, "decoded_reset_sb.wav"), dec_sb)
    write_wav(os.path.join(out, "decoded_reset_2048.wav"), dec_2048)
    specs = []
    for w in ("orig", "decoded", "decoded_reset_sb", "decoded_reset_2048"):
        if spectrogram(os.path.join(out, w + ".wav"), os.path.join(out, w + "_spec.png")):
            specs.append(w + "_spec.png")

    snr = report(orig, dec_carry, "decoded (carry)")
    report(orig, dec_sb,   "decoded (reset/super-block)")
    report(orig, dec_2048, "decoded (reset/2048)")

    print(f"\nfiles in {out}: orig.wav, decoded*.wav" + (", " + ", ".join(specs) if specs else ""))
    print("\nverdict guide:")
    if snr >= 55:
        print("  decoded(carry) SNR is high -> the ENCODER is clean; an in-game stutter is")
        print("  streaming/IO (disc seek) or the game resetting the predictor — check the")
        print("  decoded_reset_*.wav: if one of them reproduces the in-game stutter, that is")
        print("  the boundary the game resets at (encoder must reset there too).")
    else:
        print("  decoded(carry) SNR is LOW -> the encoder itself diverges; the worst windows")
        print("  above are where it eats/garbles audio. That's the bug to fix in psxadpcm.c.")


if __name__ == "__main__":
    main()
