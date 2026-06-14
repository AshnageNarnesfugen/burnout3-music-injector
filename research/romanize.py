#!/usr/bin/env python3
"""
Romanize foreign text (any script) to plain ASCII — for the Burnout 3 EA TRAX
display, whose NTSC-U font only has Latin/ASCII glyphs.

Engines (best available is used automatically):
  - pykakasi   : proper Hepburn for Japanese (kanji+kana). Optional: `pip install pykakasi`.
  - ICU/uconv  : any script -> Latin -> ASCII (Japanese kana, Chinese pinyin, Korean,
                 Cyrillic, Greek, Arabic, ...). Zero-install (Arch `icu` package).

Usage:
  romanize.py "凛として時雨"            -> rin toshite shigure  (pykakasi) / lintoshite... (ICU)
  echo "방탄소년단" | romanize.py        -> bangtansonyeondan
  romanize.py --title "周杰倫"           -> Zhou Jie Lun
"""
import subprocess, sys, re, shutil

_HAS_UCONV = shutil.which("uconv") is not None

def _icu(text: str) -> str:
    if not _HAS_UCONV:
        # last-resort: drop non-ASCII
        return text.encode("ascii", "ignore").decode()
    r = subprocess.run(["uconv", "-x", "Any-Latin; Latin-ASCII"],
                       input=text, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else text

def _ensure_pykakasi_path():
    """pykakasi lives in an isolated venv (Arch blocks system pip). Add it to sys.path."""
    import os, glob, sys
    venv = os.path.expanduser("~/.local/share/burnout-romanize-venv")
    for sp in glob.glob(os.path.join(venv, "lib", "python*", "site-packages")):
        if sp not in sys.path:
            sys.path.append(sp)

def _pykakasi(text: str):
    try:
        import pykakasi
    except Exception:
        _ensure_pykakasi_path()
        try:
            import pykakasi
        except Exception:
            return None
    try:
        conv = pykakasi.kakasi().convert(text)
        return " ".join(seg["hepburn"] for seg in conv)
    except Exception:
        return None

def _has_kana(text: str) -> bool:
    # hiragana/katakana = a strong, unambiguous Japanese signal (Han is shared with Chinese)
    return any('぀' <= c <= 'ヿ' for c in text)

def romanize(text: str, title_case: bool = False, lang: str = None) -> str:
    """Return an ASCII romanization. Already-ASCII text is returned unchanged.
    pykakasi (Japanese Hepburn) is used when kana is present or lang='ja'; otherwise ICU
    handles the script generically (Chinese pinyin, Korean, Cyrillic, Greek, ...)."""
    if not text or all(ord(c) < 128 for c in text):
        out = text
    else:
        out = None
        if lang == "ja" or _has_kana(text):
            out = _pykakasi(text)          # proper Japanese Hepburn, if available
        if out is None:
            out = _icu(text)               # any-language fallback (pinyin/Hangul/etc.)
    out = re.sub(r"\s+", " ", out).strip()
    out = out.encode("ascii", "ignore").decode()   # guarantee pure ASCII
    return out.title() if title_case else out

def engine() -> str:
    try:
        import pykakasi  # noqa
        return "pykakasi + ICU"
    except Exception:
        return "ICU/uconv" if _HAS_UCONV else "ascii-strip (no uconv!)"

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--title"]
    tc = "--title" in sys.argv
    text = " ".join(args) if args else sys.stdin.read()
    sys.stderr.write(f"[engine: {engine()}]\n")
    print(romanize(text, title_case=tc))
