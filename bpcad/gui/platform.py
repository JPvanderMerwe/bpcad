"""
Getting Qt and VTK to agree about which display server they are on.

THE PROBLEM, STATED PLAINLY
---------------------------
Qt 6 runs natively on Wayland. VTK's OpenGL render window does not - it opens
an X11/GLX context. On a Wayland session the two disagree, and the result is
not a clean error: you get `BadWindow (invalid Window parameter)` from Xlib, or
a shader that silently fails to compile and a part that renders as nothing.
Neither looks like a display-server problem, which is what makes it expensive.

The fix is to put BOTH on XWayland by asking Qt for the xcb platform. That
needs libxcb-cursor, which Qt 6.5 and later require for xcb and which is not
installed on a default Ubuntu desktop. It ships in the conda environment, but
the dynamic loader will not find it unless LD_LIBRARY_PATH points at the
environment's lib directory - and LD_LIBRARY_PATH is read by the loader at
process start, so setting it from inside Python is too late.

Hence the re-exec below. It happens once, before Qt is imported, and only when
it is actually needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Set on the child so it cannot loop, however the environment is mangled.
GUARD = "BPCAD_GUI_BOOTSTRAPPED"


def env_lib_dir() -> Path | None:
    """The lib directory of the environment this interpreter lives in."""
    prefix = Path(sys.prefix)
    lib = prefix / "lib"
    return lib if lib.is_dir() else None


def has_xcb_cursor() -> bool:
    """Whether libxcb-cursor can be found, system-wide or in the environment."""
    import ctypes.util

    if ctypes.util.find_library("xcb-cursor"):
        return True
    lib = env_lib_dir()
    return bool(lib and list(lib.glob("libxcb-cursor.so*")))


def wants_xcb() -> bool:
    """
    True when we are on Wayland and should move to XWayland for VTK's sake.

    An explicit QT_QPA_PLATFORM is always respected - if someone has set it,
    they mean it.
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return False
    if not os.environ.get("WAYLAND_DISPLAY"):
        return False
    if not os.environ.get("DISPLAY"):
        return False          # no XWayland to move to
    return has_xcb_cursor()


def can_reexec() -> bool:
    """
    Whether this process can be restarted from its own argv.

    `python -c "..."` cannot: sys.argv is just ["-c"] and the code itself is
    nowhere in it, so re-execing produces `python -c` with nothing to run. The
    console script and `python -m bpcad.gui` both carry a real path and are
    fine. Getting this wrong turns a working launch into "Argument expected for
    the -c option", which says nothing about the actual cause.
    """
    if not sys.argv or sys.argv[0] in ("", "-c"):
        return False
    return Path(sys.argv[0]).exists()


def bootstrap() -> None:
    """
    Put the process on a display stack Qt and VTK can share, re-execing once if
    that means changing LD_LIBRARY_PATH.

    Call this BEFORE importing PySide6. It is a no-op when nothing needs doing,
    which includes every non-Wayland session.
    """
    if os.environ.get(GUARD):
        return
    if not wants_xcb():
        os.environ.setdefault(GUARD, "1")
        return

    if not can_reexec():
        # Set what can be set in-process. LD_LIBRARY_PATH is read by the loader
        # at start-up so it will not take effect, and if libxcb-cursor is only
        # in the environment's lib directory Qt will fall back to Wayland. Say
        # so rather than failing mysteriously.
        os.environ[GUARD] = "1"
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
        return

    env = dict(os.environ)
    env[GUARD] = "1"
    env["QT_QPA_PLATFORM"] = "xcb"

    lib = env_lib_dir()
    if lib is not None:
        existing = env.get("LD_LIBRARY_PATH", "")
        if str(lib) not in existing.split(":"):
            env["LD_LIBRARY_PATH"] = (
                "%s:%s" % (lib, existing) if existing else str(lib)
            )

    try:
        os.execve(sys.executable, [sys.executable] + sys.argv, env)
    except OSError:
        # If the re-exec fails, carry on in-process. Qt will fall back to
        # Wayland and the 3D view may be degraded, but the rendered images and
        # the height map are produced on the CPU and are unaffected.
        os.environ[GUARD] = "1"


def describe() -> str:
    """One line for the About box and the status bar."""
    platform = os.environ.get("QT_QPA_PLATFORM") or "default"
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    return "session %s, Qt platform %s" % (session, platform)
