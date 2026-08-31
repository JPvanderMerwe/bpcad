"""
bpcad over HTTP: the same program, reachable from a browser and a phone.

WHY STDLIB AND NOT A FRAMEWORK
-------------------------------
FastAPI is installed here and there is no ASGI server to run it on, and adding
one to reach the eight routes below would be a dependency bought for nothing.
`ThreadingHTTPServer` serves them, streams progress over Server-Sent Events,
and has no install step on any machine this ever runs on - which matters more
than usual, because the point of this layer is to be reachable from a phone
that has no Python on it at all.

WHY THE 3D VIEW IS PICTURES AND NOT WEBGL
------------------------------------------
The obvious thing is three.js and a mesh in the browser. That means either a
CDN - which does not work offline and is a third-party dependency in a program
whose whole argument is that it has none - or vendoring a megabyte of
someone else's JavaScript. And it means every phone that opens this has to be
able to run WebGL well enough to shade a 40 000-triangle mesh.

There is already a renderer. It is the CPU z-buffer rasteriser that draws every
other picture this program produces, it is verified against a deliberately
asymmetric part, and it runs on the machine that already has the geometry
loaded. So the viewer asks it for the part at a series of angles and lets you
drag between them. It is a turntable, not a free camera - you cannot fly around
it - but it works identically on a ten-year-old phone and a workstation, it
needs no JavaScript library at all, and what you see is the same rasteriser
that draws the height maps, so the two cannot disagree.

RUNNING WORK IS NOT KEPT IN THE REQUEST
----------------------------------------
A generation takes a minute or two on this hardware. Doing it inside the POST
means a phone that locks its screen loses the part. So a POST starts a job,
returns its id immediately, and the browser follows it on a separate SSE
stream that it can drop and reopen without the work noticing.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

STATIC_DIR = Path(__file__).parent / "static"

# How many angles the turntable has. 24 is 15 degrees apart, which reads as
# continuous when you drag it and is cheap enough to render on demand.
TURNTABLE_STEPS = 24

# Renders are cached by (part, step, size) and never invalidated, because a
# built part's geometry does not change - a refinement writes a NEW part.
_RENDER_CACHE: dict[tuple, bytes] = {}
_RENDER_LOCK = threading.Lock()

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


class HttpError(Exception):
    """A response the client should see, with its status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """
    One generation or refinement, running on its own thread.

    `events` is a list and not just a queue on purpose: a phone that locks its
    screen drops the SSE connection, and when it comes back it needs the whole
    story so far, not only what happened after it reconnected.
    """

    id: str
    kind: str
    request: str
    events: list[dict] = field(default_factory=list)
    subscribers: list[queue.Queue] = field(default_factory=list)
    done: bool = False
    result: dict | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, **payload) -> None:
        event = {"kind": kind, "at": round(time.time(), 3), **payload}
        with self.lock:
            self.events.append(event)
            subscribers = list(self.subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=512)
        with self.lock:
            backlog = list(self.events)
            self.subscribers.append(q)
        return backlog, q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _start_job(kind: str, request: str, work) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, request=request)
    with JOBS_LOCK:
        JOBS[job.id] = job

    def run():
        try:
            job.emit("started", request=request)
            result = work(job)
            job.result = result
            job.emit("done", **result)
        except Exception as exc:
            # The message a person can act on, not the traceback. The traceback
            # goes to the console where whoever is running the server can see it.
            traceback.print_exc()
            job.result = {"ok": False, "message": str(exc).split("\n")[0][:400]}
            job.emit("failed", message=job.result["message"])
        finally:
            job.done = True
            job.emit("closed")

    threading.Thread(target=run, daemon=True, name="job-%s" % job.id).start()
    return job


# ---------------------------------------------------------------------------
# the work itself
# ---------------------------------------------------------------------------


def _part_payload(part) -> dict:
    """Everything the browser needs about one built part, and nothing heavy."""
    report = part.report
    spec = part.spec
    mesh = getattr(report, "mesh", None)
    size = None
    if mesh is not None and getattr(mesh, "bbox_mm", None):
        size = [round(float(v), 1) for v in mesh.bbox_mm]

    return {
        "name": part.name,
        "verdict": report.verdict,
        "ok": bool(report.ok),
        "size_mm": size,
        "volume_cm3": round(float(getattr(mesh, "volume_mm3", 0.0)) / 1000.0, 1)
        if mesh is not None else None,
        "bodies": int(getattr(mesh, "body_count", 0)) if mesh is not None else None,
        "watertight": bool(getattr(mesh, "watertight", False)) if mesh is not None else None,
        "level": getattr(spec, "level", None),
        "template": getattr(spec, "template", None),
        "material": getattr(spec, "material", None),
        "problems": [str(p) for p in getattr(report, "problems", [])],
        "warnings": [str(w) for w in getattr(report, "warnings", [])],
        "notes": [str(n) for n in getattr(report, "notes", [])],
        "assumptions": [str(a) for a in getattr(report, "assumptions", [])],
        "report_md": report.markdown() if hasattr(report, "markdown") else "",
        "spec": _spec_dict(spec),
    }


def _spec_dict(spec) -> dict:
    try:
        return json.loads(spec.model_dump_json(exclude_none=True))
    except Exception:
        try:
            return dict(spec)
        except Exception:
            return {}


def _generate_work(request: str, material: str, image_path: str | None):
    def work(job: Job) -> dict:
        from bpcad import api

        def on_event(kind: str, payload: Any) -> None:
            # Translate the engine's events into something a person reads. The
            # engine's payloads are objects; putting them on the wire raw would
            # send megabytes and say nothing.
            if kind == "profile":
                job.emit("note", text="using %s on %s"
                         % (payload.model_primary, payload.name))
            elif kind == "attempt":
                job.emit("note", text="attempt %s" % getattr(payload, "index", "?"))
            elif kind == "escalate":
                job.emit("note", text="no template fits - composing from primitives")
            elif kind == "building":
                job.emit("note", text="building geometry")
            else:
                job.emit("note", text=str(kind))

        measurement = None
        if image_path:
            job.emit("note", text="measuring the image")
            try:
                measurement = api.measure_image(image_path)
            except Exception as exc:
                job.emit("note", text="could not measure the image: %s" % exc)

        result = api.generate(
            request,
            material=material,
            on_event=on_event,
            measurement=measurement,
            render=True,
        )
        if not result.ok or result.part is None:
            return {"ok": False,
                    "message": result.message or "the model could not produce a "
                                                 "part that passes verification",
                    "attempts": result.attempt_count}
        payload = _part_payload(result.part)
        payload["ok"] = True
        payload["elapsed_s"] = round(result.elapsed_s, 1)
        payload["attempts"] = result.attempt_count
        return payload

    return work


def _refine_work(name: str, instruction: str):
    def work(job: Job) -> dict:
        from bpcad import api

        job.emit("note", text="reading %s" % name)
        result = api.refine(name, instruction,
                            on_event=lambda k, p: job.emit("note", text=str(k)))
        if not result.ok or result.part is None:
            return {"ok": False,
                    "message": result.message or "could not apply that change"}
        payload = _part_payload(result.part)
        payload["ok"] = True
        payload["note"] = result.note
        payload["changes"] = list(result.changes)
        return payload

    return work


# ---------------------------------------------------------------------------
# rendering for the turntable
# ---------------------------------------------------------------------------


def _resolve_part(name: str) -> tuple[Path, Path | None]:
    """
    Find a part by any of the names it goes by, and its STL.

    THE SAME PART HAS TWO NAMES. `parts()` calls it by its DIRECTORY - "keyring"
    - and `library()` calls it by its SPEC name - "loop_keyring". Both are
    shown to people, both get linked, and looking a part up by only one of them
    means every link built from the other returns a 404. The STL is a third
    thing again: it is under out/ and named after the spec, not the directory.
    """
    from bpcad import api

    wanted = name.strip()
    for entry in api.parts():
        stl = Path(entry.stl) if entry.stl else None
        names = {entry.name}
        if stl is not None:
            names.add(stl.stem)
        if wanted in names:
            return Path(entry.directory), stl

    # A library entry knows its directory; map back onto the same list.
    for entry in api.library():
        if entry.name == wanted and getattr(entry, "directory", None):
            directory = Path(entry.directory)
            stl = next(iter(sorted(directory.glob("out/*.stl"))), None)
            return directory, stl

    raise HttpError(404, "no part called %r" % name)


def _find_part_dir(name: str) -> Path:
    return _resolve_part(name)[0]


def _render_turntable_frame(name: str, step: int, width: int, height: int) -> bytes:
    key = (name, step, width, height)
    with _RENDER_LOCK:
        hit = _RENDER_CACHE.get(key)
    if hit is not None:
        return hit

    import io

    import numpy as np
    import trimesh
    from PIL import Image

    from bpcad.gui import theme
    from bpcad.render.raster import render

    _part_dir, stl = _resolve_part(name)
    if stl is None or not Path(stl).is_file():
        raise HttpError(404, "part %r has no STL yet" % name)

    mesh = trimesh.load(stl)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(list(mesh.geometry.values()))

    azim = 360.0 * (step % TURNTABLE_STEPS) / TURNTABLE_STEPS
    img = render(
        np.asarray(mesh.vertices, dtype=float),
        np.asarray(mesh.faces),
        np.asarray(mesh.face_normals, dtype=float),
        width=width, height=height, elev_deg=26.0, azim_deg=azim,
        background=theme.VIEWPORT_BG,
    )
    arr = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr[:, :, :3]).save(buf, format="PNG", optimize=False)
    data = buf.getvalue()

    with _RENDER_LOCK:
        _RENDER_CACHE[key] = data
    return data


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _library_payload() -> list[dict]:
    from bpcad import api

    out = []
    for entry in api.library():
        out.append({
            "name": entry.name,
            "dir": Path(entry.directory).name if getattr(entry, "directory", None) else entry.name,
            "template": getattr(entry, "template", None),
            "prompt": getattr(entry, "prompt", None),
            "makes": list(getattr(entry, "makes", []) or []),
            # envelope_mm, NOT bbox_mm. The library reads its sizes out of the
            # stored regression rather than loading every mesh on disk, and it
            # calls the field something different. Getting the name wrong shows
            # no size at all and looks exactly like a part that has none.
            "size_mm": [round(float(v), 1) for v in getattr(entry, "envelope_mm", [])]
            if getattr(entry, "envelope_mm", None) else None,
            "volume_cm3": getattr(entry, "volume_cm3", None),
            "material": getattr(entry, "material", None),
            "level": getattr(entry, "level", None),
            "when": str(getattr(entry, "when", "") or ""),
            "built": bool(getattr(entry, "built", True)),
        })
    return out


def _health() -> dict:
    from bpcad import api

    try:
        status = api.model_status()
    except Exception as exc:
        status = {"ok": False, "message": str(exc)}
    cfg = api.config()
    return {
        "model": status,
        "printer": cfg.data.get("printer", {}),
        "bed": cfg.data.get("bed", {}),
        "materials": list(cfg.material_names),
        "templates": api.templates(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "bpcad"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):    # quieter than the default
        if self.path.startswith("/api/"):
            print("  %s %s" % (self.command, self.path))

    # Only the RENDERS may be cached hard. A built part's geometry never
    # changes - a refinement writes a new part - so frame 7 of a given part at
    # a given size is the same bytes forever. The HTML, CSS and JS must
    # revalidate: caching them for an hour means anyone who updates bpcad keeps
    # being served the old interface until the hour is up, with no way to tell
    # that is what is happening. That is not a development annoyance, it is a
    # broken upgrade.
    IMMUTABLE = ("image/png", "model/stl")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if ctype in self.IMMUTABLE:
            self.send_header("Cache-Control", "public, max-age=604800, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200):
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _error(self, status: int, message: str):
        self._json({"error": message}, status=status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "application/json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HttpError(400, "body is not valid JSON: %s" % exc)
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}

    # -- dispatch ----------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get()
        except HttpError as exc:
            self._error(exc.status, exc.message)
        except BrokenPipeError:
            pass                                   # the phone went away, fine
        except Exception as exc:
            traceback.print_exc()
            self._error(500, str(exc).split("\n")[0][:300])

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self._route_post()
        except HttpError as exc:
            self._error(exc.status, exc.message)
        except BrokenPipeError:
            pass
        except Exception as exc:
            traceback.print_exc()
            self._error(500, str(exc).split("\n")[0][:300])

    def _route_get(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)

        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path == "/api/health":
            return self._json(_health())
        if path == "/api/parts":
            return self._json({"parts": _library_payload()})

        m = re.fullmatch(r"/api/part/([^/]+)", path)
        if m:
            return self._json(self._one_part(m.group(1)))

        m = re.fullmatch(r"/api/part/([^/]+)/stl", path)
        if m:
            return self._send_stl(m.group(1))

        m = re.fullmatch(r"/api/part/([^/]+)/frame/(\d+)", path)
        if m:
            name, step = m.group(1), int(m.group(2))
            self._check_name(name)
            size = int((query.get("w") or ["640"])[0])
            size = max(160, min(1200, size))
            data = _render_turntable_frame(name, step, size, int(size * 0.78))
            return self._send(200, data, "image/png")

        m = re.fullmatch(r"/api/job/([0-9a-f]+)/events", path)
        if m:
            return self._sse(m.group(1))

        m = re.fullmatch(r"/api/job/([0-9a-f]+)", path)
        if m:
            job = JOBS.get(m.group(1))
            if job is None:
                raise HttpError(404, "no such job")
            return self._json({"id": job.id, "done": job.done,
                               "result": job.result, "events": job.events})

        raise HttpError(404, "no route for %s" % path)

    def _route_post(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/generate":
            request = (body.get("request") or "").strip()
            if not request:
                raise HttpError(400, "say what you want made")
            material = (body.get("material") or "petg").strip().lower()
            image = body.get("image_path") or None
            job = _start_job("generate", request,
                             _generate_work(request, material, image))
            return self._json({"job": job.id})

        if path == "/api/refine":
            name = (body.get("name") or "").strip()
            instruction = (body.get("instruction") or "").strip()
            self._check_name(name)
            if not instruction:
                raise HttpError(400, "say what to change")
            job = _start_job("refine", instruction, _refine_work(name, instruction))
            return self._json({"job": job.id})

        raise HttpError(404, "no route for %s" % path)

    # -- helpers -----------------------------------------------------------

    def _check_name(self, name: str):
        # Part names reach the filesystem. Anything that is not a plain name is
        # refused outright rather than sanitised - sanitising is where path
        # traversal bugs live.
        if not SAFE_NAME.fullmatch(name or ""):
            raise HttpError(400, "%r is not a valid part name" % name)

    def _static(self, rel: str):
        if ".." in rel or rel.startswith("/"):
            raise HttpError(400, "bad path")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            raise HttpError(400, "bad path")
        if not target.is_file():
            raise HttpError(404, "no file %r" % rel)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)

    def _one_part(self, name: str) -> dict:
        self._check_name(name)
        from bpcad import api

        part_dir, stl = _resolve_part(name)
        payload: dict[str, Any] = {"name": name, "frames": TURNTABLE_STEPS}

        spec_path = part_dir / "spec.yaml"
        if spec_path.is_file():
            # load_spec returns (PartSpec, base_dir), not a PartSpec. Passing
            # the tuple straight to the serialiser produced "{}" and an empty
            # Spec tab that looked like a part with no spec.
            loaded = api.load_spec(spec_path)
            spec_obj = loaded[0] if isinstance(loaded, tuple) else loaded
            payload["spec"] = _spec_dict(spec_obj)
            payload["level"] = getattr(spec_obj, "level", None)
            payload["template"] = getattr(spec_obj, "template", None)
            payload["material"] = getattr(spec_obj, "material", None)

        report_md = part_dir / "report.md"
        if report_md.is_file():
            payload["report_md"] = report_md.read_text()

        # Sizes come from the stored regression, which is what the library
        # reads too, so the card and the opened part cannot disagree.
        regression = part_dir / "regression.json"
        if regression.is_file():
            try:
                data = json.loads(regression.read_text())
                if data.get("bbox_mm"):
                    payload["size_mm"] = [round(float(v), 1) for v in data["bbox_mm"]]
                if data.get("volume_cm3") is not None:
                    payload["volume_cm3"] = round(float(data["volume_cm3"]), 1)
            except Exception:
                pass

        # NO VERDICT. A part on disk has no stored verdict, and the only honest
        # answers are to re-verify it - which takes as long as building it - or
        # to say nothing. Inventing a PASS because the file exists is exactly
        # the failure this program is built to avoid.
        payload["has_stl"] = stl is not None and Path(stl).is_file()
        return payload

    def _send_stl(self, name: str):
        self._check_name(name)
        _part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(404, "part %r has no STL" % name)
        self._send(200, Path(stl).read_bytes(), "model/stl",
                   {"Content-Disposition": 'attachment; filename="%s.stl"' % name})

    def _sse(self, job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            raise HttpError(404, "no such job")

        backlog, q = job.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def write(event: dict) -> bool:
            try:
                self.wfile.write(("data: %s\n\n" % json.dumps(event)).encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        try:
            for event in backlog:
                if not write(event):
                    return
            if job.done:
                return
            while True:
                try:
                    event = q.get(timeout=15.0)
                except queue.Empty:
                    # A comment frame, so a proxy or a sleeping phone does not
                    # decide the connection is dead.
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    continue
                if not write(event):
                    return
                if event.get("kind") == "closed":
                    return
        finally:
            job.unsubscribe(q)
            self.close_connection = True


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Run the server until interrupted.

    The default binds to loopback, so nothing is exposed by accident. Pass
    0.0.0.0 to reach it from a phone on the same network - that is a deliberate
    act and it prints what it did, because a CAD tool quietly listening on
    every interface is not something anyone should discover later.
    """
    httpd = ThreadingHTTPServer((host, port), Handler)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("bpcad is listening on ALL interfaces (%s:%d)." % (host, port))
        print("Anyone on this network can reach it. There is no password.")
        for addr in _local_addresses():
            print("  on your phone:  http://%s:%d" % (addr, port))
    else:
        print("bpcad web:  http://%s:%d" % (host, port))
        print("  (loopback only - use --host 0.0.0.0 to reach it from a phone)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def _local_addresses() -> list[str]:
    """This machine's LAN addresses, so the phone URL can be printed."""
    import socket

    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 1))          # TEST-NET-1, never actually routed
        out.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return out or ["<this machine's IP>"]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Serve bpcad to a browser.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    serve(args.host, args.port)
