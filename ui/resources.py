"""Bundled-asset path resolution (works from source and from a PyInstaller build)."""
import os, sys


def _resource_path(name):
    """Resolve a bundled asset (e.g. bnmex.ico). In a PyInstaller --onefile build
    sys._MEIPASS is the extraction root; from source it's the repo root (one level
    up from this ui/ package)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, name)
