# 🏎️ Burnout 3: Takedown — Custom Music Injector

**Inject your own music into Burnout 3: Takedown (PS2) for PCSX2**

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![PySide6](https://img.shields.io/badge/GUI-PySide6%2FQt6-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)

Replace the EA Trax soundtrack with your own music. Supports MP3, FLAC, M4A, OGG, WAV, OPUS, and more. Features a full GUI with drag & drop, automatic PS-ADPCM encoding, and in-place ISO patching.

## ✨ Features

- **44 track slots** — Replace any or all songs in the EA Trax playlist
- **Any audio format** — MP3, FLAC, M4A, OGG, WAV, OPUS, WMA, AAC
- **PS-ADPCM encoder** — C-accelerated encoder with optimal filter/shift search (25 combos per block)
- **LLRR stereo layout** — Correct super-block format discovered through reverse engineering
- **Smart truncation** — Automatic fade out (3s) when songs exceed slot duration
- **In-place ISO patching** — No ISO rebuild needed, fast and safe
- **Drag & drop GUI** — PySide6/Qt6 interface with dark theme
- **Auto-detect** — Parses ISO9660 + RWS headers to find all tracks

## 🔧 Installation

### Arch Linux
```bash
sudo pacman -S ffmpeg p7zip gcc python-pyside6
```

### Ubuntu / Debian
```bash
sudo apt install ffmpeg p7zip-full gcc python3-pip
pip install PySide6
```

### Run
```bash
python3 burnout3_gui.py
```

The C encoder (`psxadpcm.c`) auto-compiles on first run via `gcc`. If `gcc` is not available, a Python fallback is used (slower).

## 📖 How to Use

1. **Load ISO** — Drag your Burnout 3: Takedown ISO (NTSC-U, SLUS-21050) to the ISO tab
2. **Assign Music** — Drag audio files to the track table, or use auto-assign
3. **Inject** — Click "INYECTAR" in the Process tab
4. **Play** — Load the `_custom.iso` in PCSX2

## 🎵 Audio Format Details

| Property | Value |
|----------|-------|
| Codec | PS-ADPCM (PlayStation 2 native) |
| Sample Rate | 32,000 Hz |
| Channels | Stereo |
| Layout | LLRR (8192-byte super-blocks) |
| Block | L[2048] L[2048] R[2048] R[2048] |
| Nibble Order | First sample = LOW nibble, Second = HIGH |
| Compression | 3.5:1 (56 bytes PCM → 16 bytes ADPCM) |
| Encoder | 5 filters × 5 shifts = 25 combos per block |

## 🔬 Technical Notes

### RWS Container Format
The music is stored in `TRACKS/_EATRAX0.RWS` (tracks 1-22) and `TRACKS/_EATRAX1.RWS` (tracks 23-44) inside the ISO.

```
RWS Container (0x080D) {
  Audio Header (0x080E) {
    Track table: 32-byte entries
    [size_field @ +24, offset_field @ +28]
  }
  Audio Data (0x080F) {
    PS-ADPCM blocks in LLRR super-block layout
  }
}
```

### LLRR Layout Discovery
Through extensive reverse engineering, we discovered Burnout 3 uses an unusual stereo interleave:
- **Not** standard L[2048] R[2048] alternating
- **Actual**: L[2048] L[2048] R[2048] R[2048] in 8192-byte super-blocks
- Confirmed by decoding original tracks with vgmstream and comparing energy patterns

### Nibble Packing
PS-ADPCM stores two 4-bit samples per byte:
- First sample → **LOW nibble** (bits 0-3)
- Second sample → **HIGH nibble** (bits 4-7)

This was verified by byte-comparison against decoded/re-encoded original tracks.

## 📋 Known Limitations

- **Slot size is fixed** — Each track slot has a fixed size (~3-4 minutes). Songs longer than the slot are truncated with a fade out.
- **NTSC-U only** — Currently supports the US version (SLUS-21050). PAL/JP versions have different offsets.
- **Song names in-game** — The EA Trax UI still shows original song/artist names. Modifying these requires further reverse engineering of the game's data files.

## 🤝 Contributing

Contributions welcome! Areas that need help:

- **HostFS integration** — [Nahelam's HostFS patch](https://github.com/Nahelam/PCSX2-HostFS-Patches) could enable larger EATRAX files for full-length songs
- **Song metadata** — Finding where artist/title strings are stored to allow custom names in the EA Trax UI
- **PAL/JP support** — Adding support for European and Japanese ISO versions
- **Cross-platform** — Windows/Mac support (PySide6 is cross-platform, C encoder needs platform builds)
- **EATRAX expansion** — Reverse engineering the game executable to allow dynamic track sizes

## 🙏 Credits & Acknowledgments

- **[Nahelam](https://github.com/Nahelam)** — [PS2-Game-Mods](https://github.com/Nahelam/PS2-Game-Mods) for Burnout 3 modding research and HostFS patches
- **vgmstream** — For confirming the audio codec and sample rate
- **EA / Criterion Games** — For making Burnout 3: Takedown, one of the greatest racing games ever

## 📄 License

MIT License

---

*This tool is for personal use with legally owned copies of Burnout 3: Takedown. No copyrighted game data is included.*
