"""Core (non-GUI) logic for the Burnout 3 music injector.

Pure logic with no Qt dependency — importable headless and shared by the GUI
(`ui/`) and the research tools:

  constants     — ISO/RWS knowledge, the EA Trax track list, audio-pipeline constants
  psx_adpcm     — the PS-ADPCM encoder (C-accelerated, with a pure-Python fallback)
  audio         — the ffmpeg/ffprobe loudness + resample pipeline
  rws           — RenderWare Stream (.RWS) + ISO9660 parsing helpers
  eatrax        — EA-TRAX RWS building + GLOBALUS string-table rebuild/overwrite
  portable_iso  — the self-contained portable-ISO builder
"""
