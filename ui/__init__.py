"""Qt (PySide6) presentation layer for the Burnout 3 music injector.

  resources    — bundled-asset path resolution (icon)
  style        — the dark-theme stylesheet
  widgets      — drag-and-drop widgets (ISODropZone, TrackTable)
  workers      — background QObject workers (InjectionWorker, PortableIsoWorker)
  main_window  — the MainWindow that ties the tabs together

Depends on `core/` for all the non-GUI logic.
"""
