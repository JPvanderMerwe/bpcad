"""
The desktop app, which is now the web app in a native window.

WHY THERE IS ONLY ONE UI NOW
----------------------------
There were two front ends: a Qt desktop app and a web app. They diverged
immediately, as two front ends always do, and the cost landed in one go - a
whole session of interface work went into the web app while `bpcad-gui` was
what was actually being launched, so the answer to "make the UI better" looked
like "nothing has changed". That is not a communication problem to be fixed
with a banner. It is two codebases doing one job.

It also could not survive the next requirement. This has to become an Android
and iOS app, and a Qt desktop app cannot go on a phone at any price. Whatever
the phone runs, the desktop has to run the same thing, or the divergence starts
again on day one.

So the desktop app is a window with a web view in it, pointed at a server
running in-process on loopback. Identical HTML, CSS and JavaScript to what a
phone loads over the network - not a port of it, the same files. A change to
the interface lands on the desktop, the phone and the browser at once, because
there is only one interface.

WHAT IS LOST, HONESTLY
-----------------------
The old Qt app had a VTK viewport with a real trackball camera - free rotation,
zoom, pan. The web viewer is a turntable: you can spin it about one axis and
that is all. That is a genuine regression for anyone who wants to look under a
part, and it is the price of the viewer working identically on a phone with no
WebGL. The old app is still there behind `--classic` until the turntable is
good enough that nobody reaches for it.
"""

from __future__ import annotations

import socket
import sys
import threading
from http.server import ThreadingHTTPServer

# The window is chrome-less on purpose - the web UI draws its own header, and a
# native title bar above an app that already has one looks like a mistake.
WINDOW_TITLE = "bpcad — Bit Primitive"
DEFAULT_SIZE = (1280, 900)


def free_port() -> int:
    """
    A port nobody else is using.

    Asked for rather than hardcoded: the desktop app must not fail to start
    because a `bpcad web` is already running, and it must not silently attach
    to somebody else's server on a well-known port either.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def serve_in_thread(port: int) -> ThreadingHTTPServer:
    """
    Start the web app on loopback, in this process, on a daemon thread.

    LOOPBACK, ALWAYS, from here. The desktop app opening a port on every
    interface because someone double-clicked an icon is not a decision the
    icon gets to make - `bpcad web --lan` is where that choice is stated out
    loud and printed to the terminal.
    """
    from bpcad.web.server import Handler

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True,
                              name="bpcad-web")
    thread.start()
    return httpd


def main(argv: list[str] | None = None) -> int:
    """The desktop app: one native window, the web UI inside it."""
    argv = list(sys.argv if argv is None else argv)

    if "--classic" in argv:
        # The old Qt app, with the VTK trackball viewport. Kept because the
        # turntable cannot yet do everything it could.
        from bpcad.gui.app import classic_main

        return classic_main([a for a in argv if a != "--classic"])

    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("the desktop shell needs PySide6 with QtWebEngine: %s" % exc)
        print("run the web app instead:  bpcad web")
        return 1

    from bpcad.gui import platform as gui_platform

    # The same Wayland/GL handling the old app needed. A web view is a browser
    # engine and it has the identical problem.
    if hasattr(gui_platform, "prepare"):
        try:
            gui_platform.prepare()
        except Exception:
            pass

    port = free_port()
    httpd = serve_in_thread(port)

    app = QApplication([a for a in argv if not a.startswith("--")])
    app.setApplicationName("bpcad")
    app.setOrganizationName("Bit Primitive")

    view = QWebEngineView()
    view.setWindowTitle(WINDOW_TITLE)
    view.resize(*DEFAULT_SIZE)
    view.load(QUrl("http://127.0.0.1:%d/" % port))
    view.show()

    print("bpcad desktop - the web UI at http://127.0.0.1:%d/" % port)
    print("  same interface a phone gets. `bpcad web --lan` to reach it from one.")
    try:
        return app.exec()
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
