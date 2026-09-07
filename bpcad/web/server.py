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

# mimetypes does not know these, and a manifest served as
# application/octet-stream is ignored by every browser - silently, so the app
# simply is not installable and nothing says why.
EXTRA_TYPES = {
    ".webmanifest": "application/manifest+json",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
}

# How many angles the turntable has. 24 is 15 degrees apart, which reads as
# continuous when you drag it and is cheap enough to render on demand.
TURNTABLE_STEPS = 24

# RENDER VERSION, AND WHY AN IMMUTABLE CACHE NEEDS ONE.
#
# Frames are served `immutable, max-age=604800` because a built part's geometry
# never changes - a refinement writes a new part. That is true of the GEOMETRY
# and not of the PICTURE. Changing the renderer changes every frame's content
# without changing any frame's URL, so every browser that has been here keeps
# showing the old ones for a week and no amount of reloading helps.
#
# It bit immediately: the renderer went from opaque RGB to transparent RGBA and
# the page kept drawing the old flat-backed frames, which was the exact
# rectangle-around-the-part the change was meant to remove.
#
# BUMP THIS whenever the renderer's output changes - background, alpha,
# shading, camera, size. The client appends it to every frame URL.
RENDER_VERSION = 2

# Renders are cached by (part, step, size) and never invalidated, because a
# built part's geometry does not change - a refinement writes a NEW part.
_RENDER_CACHE: dict[tuple, bytes] = {}

# GLB, for the front ends that render on their own GPU rather than being sent
# pictures. Cached by part for the same reason the frames are: a built part's
# geometry does not change, a refinement writes a NEW part. The conversion is
# a mesh walk and costs real time on a 40 000-face bowl.
_GLB_CACHE: dict[str, bytes] = {}
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
        "files": sorted({
            f.suffix.lstrip(".").lower()
            for f in (Path(part.part_dir) / "out").glob("*")
            if f.suffix.lstrip(".").lower() in ("stl", "step", "3mf")
        }),
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

        # OPTIONS, FROM ONE MODEL CALL. The variants come from walking the
        # template's own axes in Python, so four of them cost seconds rather
        # than four more trips through a model that takes minutes and would
        # mostly repeat itself anyway. They are EMITTED as they build, so the
        # grid fills in rather than sitting empty until the last one lands.
        job.emit("note", text="building options")
        options = [{"name": payload["name"], "label": "as asked",
                    "verdict": payload["verdict"],
                    "volume_cm3": payload.get("volume_cm3"),
                    "envelope_mm": payload.get("size_mm")}]
        job.emit("option", **options[0])
        try:
            from bpcad.agent.variations import build_variants

            def relay(kind, data):
                if kind == "variant_built":
                    job.emit("option", **data)
                elif kind == "variant_dropped":
                    job.emit("note", text="dropped %s - %s"
                             % (data.get("label"), data.get("why", "")[:80]))

            for variant in build_variants(result.spec, api.config(), count=4,
                                          out_root="parts", on_event=relay):
                if variant.name == payload["name"]:
                    continue
                options.append({
                    "name": variant.name, "label": variant.label,
                    "verdict": variant.verdict,
                    "volume_cm3": variant.volume_cm3,
                    "envelope_mm": list(variant.envelope_mm),
                })
        except Exception as exc:
            # Options are a bonus. Losing them must not lose the part.
            job.emit("note", text="could not build options: %s" % str(exc)[:120])

        payload["options"] = options
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


def _assembled_mesh(name: str):
    """
    The part AS IT IS, not as it prints.

    The STL on disk is the PRINT layout - a birdhouse is a box with its roof
    lying flat on the bed beside it, because that is how it prints without
    support. Showing that in the viewer is why the answer to "make me a
    birdhouse" looked like an open box with a slab next to it. It was a
    birdhouse the whole time, in two pieces, seen from the wrong side of the
    process.

    Templates keep the two orientations as separate functions on purpose, so
    the assembled one is there to be asked for. It costs a rebuild, which is
    seconds and happens once because the rendered frames are cached.

    An imported mesh has no spec and no assembled form; it is what it is, and
    the STL is returned.
    """
    from bpcad import api

    part_dir, stl = _resolve_part(name)
    spec_path = Path(part_dir) / "spec.yaml"
    if spec_path.is_file():
        try:
            loaded = api.load_spec(spec_path)
            spec = loaded[0] if isinstance(loaded, tuple) else loaded
            built = api.build(spec=spec, out_dir=None, render=False)
            from bpcad.verify.fit import mesh_of_solid

            return mesh_of_solid(built.build.solid)
        except Exception:
            pass                        # fall back to what is on disk

    import trimesh

    if stl is None or not Path(stl).is_file():
        raise HttpError(404, "part %r has no STL yet" % name)
    mesh = trimesh.load(stl)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
    return mesh


def _render_turntable_frame(name: str, step: int, width: int, height: int,
                            layout: str = "assembled") -> bytes:
    key = (name, step, width, height, layout)
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

    if layout == "print":
        _part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(404, "part %r has no STL yet" % name)
        mesh = trimesh.load(stl)
        if isinstance(mesh, trimesh.Scene):
            mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
    else:
        mesh = _assembled_mesh(name)

    azim = 360.0 * (step % TURNTABLE_STEPS) / TURNTABLE_STEPS
    # TRANSPARENT. The page draws a build-plate grid (brief 11.1) and a flat
    # backed render dropped on top of it reads as a hard rectangle around the
    # part, because the grid stops where the picture starts. With alpha the
    # part sits ON the plate.
    img = render(
        np.asarray(mesh.vertices, dtype=float),
        np.asarray(mesh.faces),
        np.asarray(mesh.face_normals, dtype=float),
        width=width, height=height, elev_deg=26.0, azim_deg=azim,
        background=theme.VIEWPORT_BG, alpha=True,
    )
    arr = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG", optimize=False)
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


def _part_glb(name: str) -> bytes:
    """
    The part as GLB, for a real 3D viewer.

    WHY GLB AND NOT THE STL IT ALREADY HAS. Both front ends want to orbit a
    part with their own GPU - a phone especially, where a server round trip per
    frame is the difference between turning a part and waiting for one. STL
    carries triangles and nothing else: no units, no orientation convention,
    no material, and every viewer guesses differently. glTF/GLB is the format
    those viewers actually take, one binary file, and trimesh already writes
    it - no new dependency for something this central.
    """
    cached = _GLB_CACHE.get(name)
    if cached is not None:
        return cached

    mesh = _assembled_mesh(name)
    data = mesh.export(file_type="glb")
    if isinstance(data, str):
        data = data.encode("utf-8")

    with _RENDER_LOCK:
        _GLB_CACHE[name] = data
    return data


def _health() -> dict:
    from bpcad import api

    try:
        status = api.model_status()
    except Exception as exc:
        status = {"ok": False, "message": str(exc)}
    from bpcad import capability

    try:
        cap = capability.detect().to_json()
    except Exception as exc:
        cap = {"tier": "unknown", "headline": "could not read this machine's "
                                              "capability: %s" % str(exc)[:100]}

    cfg = api.config()
    return {
        "model": status,
        "capability": cap,
        "render_version": RENDER_VERSION,
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
        # A service worker may only control paths at or below its own
        # location, so one served from /static/ cannot control "/" unless it
        # says so. Without this the worker registers, reports success, and
        # controls nothing.
        if getattr(self, "_sw", False):
            self.send_header("Service-Worker-Allowed", "/")
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

        m = re.fullmatch(r"/api/part/([^/]+)/glb", path)
        if m:
            return self._send_glb(m.group(1))

        m = re.fullmatch(r"/api/part/([^/]+)/file/([a-z0-9]{1,6})", path)
        if m:
            return self._send_file(m.group(1), m.group(2))

        m = re.fullmatch(r"/api/part/([^/]+)/frame/(\d+)", path)
        if m:
            name, step = m.group(1), int(m.group(2))
            self._check_name(name)
            size = int((query.get("w") or ["640"])[0])
            size = max(160, min(1200, size))
            layout = (query.get("layout") or ["assembled"])[0]
            layout = "print" if layout == "print" else "assembled"
            data = _render_turntable_frame(name, step, size,
                                           int(size * 0.78), layout)
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

    # WHAT MAY BE UPLOADED AS A REFERENCE PHOTO. An allow-list, and checked
    # against the file's own magic bytes rather than its name: an extension is
    # a claim made by whoever named the file.
    IMAGE_MAGIC = {
        b"\xff\xd8\xff": ("jpg", "image/jpeg"),
        b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
        b"RIFF": ("webp", "image/webp"),
    }

    # A phone camera photo is a few megabytes. Ten is generous and stops a
    # mistake - or a stray POST - from filling the disk.
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024

    def _route_post(self):
        path = urlparse(self.path).path

        # BEFORE _body(). An upload is raw bytes, and _body() would try to
        # parse a JPEG as JSON.
        if path == "/api/upload":
            return self._receive_image()

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

    def _receive_image(self):
        """
        Take a reference photo and say where it landed.

        The client posts the raw bytes and gets back a path it can hand to
        /api/generate as `image_path`. That endpoint has always accepted a
        path and there was never a way to put a file at one - so image-to-model
        worked from the command line and nowhere else, which on a phone is the
        one device with a camera.

        THE FILE IS NOT TRUSTED. Its declared name is discarded except for an
        extension check, the real type comes from the magic bytes, and the
        name it is saved under is generated here. A filename that arrives over
        the wire is somebody else's string.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise HttpError(400, "no image in the body")
        if length > self.MAX_UPLOAD_BYTES:
            raise HttpError(
                413, "that image is %.1f MB and the limit is %d MB"
                % (length / 1048576.0, self.MAX_UPLOAD_BYTES // 1048576))

        payload = self.rfile.read(length)
        kind = next(
            ((ext, mime) for magic, (ext, mime) in self.IMAGE_MAGIC.items()
             if payload.startswith(magic)),
            None,
        )
        if kind is None:
            raise HttpError(
                400, "that is not a JPEG, PNG or WebP - the first bytes say "
                     "otherwise, whatever the file is called")
        ext, mime = kind

        from bpcad.imports import IMPORT_ROOT

        target_dir = Path(IMPORT_ROOT) / "uploads"
        target_dir.mkdir(parents=True, exist_ok=True)
        # The name is generated, never taken from the request: a filename off
        # the wire is where path traversal lives.
        name = "ref-%d.%s" % (int(time.time() * 1000), ext)
        target = target_dir / name
        target.write_bytes(payload)

        # Measure it now, so the client can show what was actually read off
        # the picture before spending minutes on a generate. A photo that
        # separated nothing from its background is worth saying so about
        # immediately.
        from bpcad import api

        facts: dict[str, Any] = {}
        note = ""
        try:
            # measure_image returns Box objects for the regions it found, which
            # carry their own repr and do not serialise. Kept as their readable
            # form rather than exploded into four numbers: the client shows
            # them to a person, and "L17 R654 T13 B696 (638 x 684 px)" is what
            # a person wants to read.
            facts = {
                key: (value if isinstance(value, (int, float, str, bool, type(None)))
                      else str(value))
                for key, value in api.measure_image(target).items()
            }
        except Exception as exc:
            note = str(exc)[:200]

        return self._json({
            "path": str(target),
            "name": name,
            "bytes": len(payload),
            "type": mime,
            "measured": facts,
            "note": note,
            # THE HONEST CAVEAT, carried with the measurement rather than left
            # for the UI to remember: every figure above is in PIXELS. Nothing
            # here can become a millimetre without one real dimension from the
            # person holding the object.
            "needs_scale": bool(facts),
        })

    # -- helpers -----------------------------------------------------------

    def _check_name(self, name: str):
        # Part names reach the filesystem. Anything that is not a plain name is
        # refused outright rather than sanitised - sanitising is where path
        # traversal bugs live.
        if not SAFE_NAME.fullmatch(name or ""):
            raise HttpError(400, "%r is not a valid part name" % name)

    def _static(self, rel: str):
        self._sw = rel.endswith("sw.js")
        if ".." in rel or rel.startswith("/"):
            raise HttpError(400, "bad path")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            raise HttpError(400, "bad path")
        if not target.is_file():
            raise HttpError(404, "no file %r" % rel)
        ctype = (EXTRA_TYPES.get(target.suffix.lower())
                 or mimetypes.guess_type(str(target))[0]
                 or "application/octet-stream")
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
                # PIECES. For anything with a moving part this is the fact that
                # decides whether it works: two bodies turn, one body is fused
                # solid. The app had no way to show it for a part opened from
                # the library, which is the only way you ever look at one
                # again.
                if data.get("body_count"):
                    payload["bodies"] = int(data["body_count"])
            except Exception:
                pass

        # NO VERDICT. A part on disk has no stored verdict, and the only honest
        # answers are to re-verify it - which takes as long as building it - or
        # to say nothing. Inventing a PASS because the file exists is exactly
        # the failure this program is built to avoid.
        payload["has_stl"] = stl is not None and Path(stl).is_file()
        payload["files"] = sorted({
            f.suffix.lstrip(".").lower()
            for f in (part_dir / "out").glob("*")
            if f.suffix.lstrip(".").lower() in self.DOWNLOADABLE
        })
        return payload

    def _send_glb(self, name: str):
        """
        The part as one GLB. Marked immutable like the render frames: the
        geometry of a built part never changes, so a viewer may cache it hard.
        RENDER_VERSION is not in this URL because it is not a picture - the
        renderer's colours and camera have nothing to do with the mesh.
        """
        self._check_name(name)
        try:
            data = _part_glb(name)
        except FileNotFoundError as exc:
            raise HttpError(404, str(exc))
        self._send(200, data, "model/gltf-binary", {
            "Cache-Control": "public, max-age=604800, immutable",
            "Content-Disposition": 'inline; filename="%s.glb"' % name,
        })

    def _send_stl(self, name: str):
        self._check_name(name)
        _part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(404, "part %r has no STL" % name)
        self._send(200, Path(stl).read_bytes(), "model/stl",
                   {"Content-Disposition": 'attachment; filename="%s.stl"' % name})

    # What a browser may download, and what to call it on the wire. An
    # allow-list rather than "whatever is in out/": this route takes an
    # extension from the URL, and the one thing it must never do is hand back
    # spec.yaml, model.py or anything else that happens to be sitting there.
    DOWNLOADABLE = {
        "stl": "model/stl",
        "step": "model/step",
        "3mf": "model/3mf",
        "png": "image/png",
    }

    def _send_file(self, name: str, ext: str):
        self._check_name(name)
        ctype = self.DOWNLOADABLE.get(ext)
        if ctype is None:
            raise HttpError(404, "%r is not a downloadable format" % ext)
        part_dir, _stl = _resolve_part(name)
        found = sorted((part_dir / "out").glob("*.%s" % ext))
        if not found:
            raise HttpError(404, "part %r has no %s file" % (name, ext.upper()))
        self._send(200, found[0].read_bytes(), ctype,
                   {"Content-Disposition": 'attachment; filename="%s.%s"' % (name, ext)})

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
