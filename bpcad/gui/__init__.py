"""
The bpcad desktop application. Qt 6 via PySide6, with VTK for interactive 3D.

Two rules hold this package together:

  1. THE GUI OWNS NO PIPELINE LOGIC. Everything goes through bpcad.api, the
     same module the CLI uses. When a GUI grows its own copy of a workflow the
     two drift, and eventually they disagree about what a part is.

  2. NOTHING SLOW RUNS ON THE UI THREAD. A generate takes ninety seconds on
     this hardware and a build takes four. Both go to a worker thread, and the
     window stays live and cancellable throughout.
"""
