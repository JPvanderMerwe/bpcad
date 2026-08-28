"""`python -m bpcad.gui`"""
from bpcad.gui import platform as _platform

_platform.bootstrap()

from bpcad.gui.app import main

raise SystemExit(main())
