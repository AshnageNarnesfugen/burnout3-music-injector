# 🏎️ Burnout 3: Takedown — Custom Music Injector

**Inject your own music into Burnout 3: Takedown (PS2) for PCSX2**

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![PySide6](https://img.shields.io/badge/GUI-PySide6%2FQt6-green)
![License](https://img.shields.io/badge/License-MIT-yellow)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-orange)

Replace the EA Trax soundtrack with your own music. Supports MP3, FLAC, M4A, OGG, WAV, OPUS, and more. Features a full GUI with drag & drop, automatic PS-ADPCM encoding, in-place ISO patching, and custom song name display.

## 🎬 Demo

[![Burnout 3 Custom Music Demo](https://img.youtube.com/vi/bScxPc_APYo/maxresdefault.jpg)](https://www.youtube.com/watch?v=bScxPc_APYo)

*Click to watch gameplay with custom music injected*

## 📸 Screenshots

### ISO + Filesystem
![ISO Tab](screenshots/iso-injection.png)

### Track Assignment
![Track Assignment](screenshots/assign-tracks.png)

### Processing
![Processing](screenshots/processing.png)

## ✨ Features

- **44 track slots** — Replace any or all songs in the EA Trax playlist
- **Custom song names** — Title, Artist, and Album display in-game via GLOBALUS.BIN patching (UTF-16LE)
- **Auto metadata** — Title/Artist/Album auto-fill from audio file tags (ID3, Vorbis, etc.)
- **Any audio format** — MP3, FLAC, M4A, OGG, WAV, OPUS, WMA, AAC
- **PS-ADPCM encoder** — C-accelerated encoder with optimal filter/shift search (25 combos per block)
- **LLRR stereo layout** — Correct super-block format verified through reverse engineering
- **Dynamic RWS patching** — Track sizes in the RWS header are updated to match actual audio length
- **Proportional scaling** — When songs exceed available space, all are scaled evenly with fade-out
- **Character limit display** — Shows max characters per field with color coding (cyan = fits, orange = will truncate)
- **Output folder selector** — Choose where to save the custom ISO
- **In-place ISO patching** — No ISO rebuild needed, fast and safe
- **Drag & drop GUI** — PySide6/Qt6 interface with dark theme
- **Cross-platform** — Linux and Windows support

## 🔧 Installation

### Arch Linux
```bash
sudo pacman -S ffmpeg gcc python-pyside6
```

### Ubuntu / Debian
```bash
sudo apt install ffmpeg gcc python3-pip
pip install PySide6
```

### Windows
Install [Python](https://python.org), [ffmpeg](https://ffmpeg.org/download.html) and [MinGW](https://www.mingw-w64.org/) (for gcc). Then:
```bash
pip install PySide6
```

### Run
```bash
python3 burnout3_gui.py
```

The C encoder (`psxadpcm.c`) auto-compiles on first run via `gcc`. If `gcc` is not available, a Python fallback is used (slower).

## 📖 How to Use

1. **Load ISO** — Drag your Burnout 3: Takedown ISO (NTSC-U, SLUS-21050) to the ISO tab
2. **Assign Music** — Go to ASSIGN TRACKS and drag audio files or folders
3. **Edit Names** — Title, Artist, and Album columns auto-fill from file metadata. Edit as needed. Fields that exceed the character limit show in orange.
4. **Inject** — Click "INJECT CUSTOM MUSIC" in the PROCESS tab
5. **Play** — Load the `_custom.iso` in PCSX2

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
| Pre-filter | Lowpass 14kHz for cleaner ADPCM encoding |

## 📊 Space & Scaling

| EATRAX | Slots | Fixed Size | Avg Duration/Slot |
|--------|-------|------------|-------------------|
| EATRAX0 | 1–22 | 149 MB | ~3.2 min |
| EATRAX1 | 23–44 | 150 MB | ~3.3 min |

- **Fewer songs = more space per song.** With 10 songs per EATRAX, most fit completely.
- **44 songs of ~5 min each**: scaled to ~74% (~3.5 min each) with automatic fade-out.
- The tool distributes space proportionally — no song gets silenced.

## 🏷️ Song Names

Custom song names are patched into `DATA/GLOBALUS.BIN` inside the ISO:

- **Slots 1–40**: Strings stored at offset `0xB700` in groups of 3 (title, album, artist)
- **Slots 41–44**: Strings stored separately at offset `0x2C004`
- **Character limit**: Each field has a fixed byte length inherited from the original string. Names longer than the limit are truncated.
- **Encoding**: UTF-16LE. Latin characters work perfectly. Japanese/CJK characters encode correctly but the NTSC-U font doesn't include those glyphs (shows as squares). Use romaji for Japanese song names.

## 🔬 Technical Notes

### RWS Container Format
The music is stored in `TRACKS/_EATRAX0.RWS` (tracks 1-22) and `TRACKS/_EATRAX1.RWS` (tracks 23-44) inside the ISO.

```
RWS Container (0x080D) {
  Audio Header (0x080E) {
    Track table @ 0x78: 32-byte entries
      [+0x18] track_size    — controls playback duration at runtime
      [+0x1C] track_offset  — cumulative byte offset into audio data
  }
  Audio Data (0x080F) {
    PS-ADPCM blocks in LLRR super-block layout
  }
}
```

Song duration is determined **at runtime** from the track size field in the RWS header — no executable patching required. This was confirmed by the Burnout modding community.

### LLRR Layout
Burnout 3 uses an unusual stereo interleave:
- **Not** standard L[2048] R[2048] alternating
- **Actual**: L[2048] L[2048] R[2048] R[2048] in 8192-byte super-blocks
- Confirmed by decoding original tracks with vgmstream and comparing energy patterns

### Nibble Packing
PS-ADPCM stores two 4-bit samples per byte:
- First sample → **LOW nibble** (bits 0-3)
- Second sample → **HIGH nibble** (bits 4-7)

Verified by byte-comparison against decoded/re-encoded original tracks.

## 📋 Known Limitations

- **EATRAX space is fixed** — 149 MB + 150 MB total. Songs are scaled proportionally when they exceed available space.
- **NTSC-U only** — Currently supports the US version (SLUS-21050). PAL/JP versions have different offsets.
- **Character limits** — Custom song names are limited to the byte length of the original string they replace.
- **No CJK fonts** — The NTSC-U version doesn't include Japanese/Chinese/Korean font glyphs. Use romaji instead.

## 🤝 Contributing

Contributions welcome! Areas that need help:

- **EATRAX expansion** — Finding a way to expand the EATRAX files beyond their fixed sizes for truly full-length songs
- **HostFS integration** — [Nahelam's HostFS patch](https://github.com/Nahelam/PCSX2-HostFS-Patches) could bypass fixed file sizes entirely
- **PAL/JP support** — Adding support for European and Japanese ISO versions
- **Song name limits** — Researching ways to extend string lengths in GLOBALUS.BIN

## 🙏 Credits & Acknowledgments

- **[Nahelam](https://github.com/Nahelam)** — [PS2-Game-Mods](https://github.com/Nahelam/PS2-Game-Mods) for Burnout 3 modding research, HostFS patches, and community support
- **burninrubber0** — RWS format documentation, song metadata research, and invaluable guidance from the [Burnout Wiki](https://burnout.wiki)
- **[AcuteSyntax](https://gist.github.com/AcuteSyntax/536a2d62ab1b3fde5c14f70d268b14c0)** — Burnout modding format documentation
- **vgmstream** — For confirming the audio codec and sample rate
- **EA / Criterion Games** — For making Burnout 3: Takedown, one of the greatest racing games ever

## 📄 License

MIT License

---

*This tool was developed with the assistance of AI (Claude by Anthropic) as a coding partner. The reverse engineering, testing, and verification were performed iteratively on real hardware/emulator setups.*

*This tool is for personal use with legally owned copies of Burnout 3: Takedown. No copyrighted game data is included.*