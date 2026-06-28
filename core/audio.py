"""ffmpeg/ffprobe audio pipeline: duration/metadata probing and the two-pass
loudnorm helpers used to bring custom music up to EA Trax's hot master level."""
import json, math, subprocess


def probe_duration_seconds(filepath):
    """Use ffprobe to get audio duration in seconds. Returns None on failure."""
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", filepath
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def probe_metadata(filepath):
    """Extract title, artist, album from audio file metadata via ffprobe."""
    try:
        r = subprocess.run([
            "ffprobe", "-v", "quiet", "-show_entries",
            "format_tags=title,artist,album",
            "-of", "json", filepath
        ], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            tags = data.get("format", {}).get("tags", {})
            title = tags.get("title", tags.get("TITLE", ""))
            artist = tags.get("artist", tags.get("ARTIST", ""))
            album = tags.get("album", tags.get("ALBUM", ""))
            return title, artist, album
    except Exception:
        pass
    return "", "", ""


def _loudnorm_measure(source, target):
    """Pass 1 of two-pass loudnorm: analyze the source and return the measured
    loudness stats as a dict, or None on failure. No audio is produced."""
    try:
        r = subprocess.run([
            "ffmpeg", "-hide_banner", "-i", source,
            "-af", f"loudnorm={target}:print_format=json",
            "-f", "null", "-"
        ], capture_output=True, text=True, timeout=300)
        # The JSON report is printed as the last {...} block on stderr.
        err = r.stderr or ""
        start = err.rfind("{")
        end = err.rfind("}")
        if start != -1 and end > start:
            return json.loads(err[start:end + 1])
    except Exception:
        pass
    return None


def _loudnorm_filter(target, measured):
    """Build the loudnorm filter for the conversion pass. With valid pass-1
    stats this is a precise linear normalization; otherwise it falls back to
    single-pass dynamic loudnorm (still normalizes, just less precise)."""
    if measured:
        try:
            i  = float(measured["input_i"])
            tp = float(measured["input_tp"])
            lra = float(measured["input_lra"])
            th = float(measured["input_thresh"])
            off = float(measured["target_offset"])
            if all(math.isfinite(v) for v in (i, tp, lra, th, off)):
                return (f"loudnorm={target}"
                        f":measured_I={i}:measured_TP={tp}:measured_LRA={lra}"
                        f":measured_thresh={th}:offset={off}:linear=true")
        except (KeyError, ValueError, TypeError):
            pass
    return f"loudnorm={target}"
