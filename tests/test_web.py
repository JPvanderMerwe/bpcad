"""
The HTTP layer, tested against a real server on a real socket.

NOT against the handler class with a mocked request. The bugs this layer
actually produced were all in the plumbing rather than the logic: a name that
resolved in one route and 404'd in another, an STL glob that looked in the
wrong directory, and a Cache-Control header that made every future upgrade
serve the old interface for an hour. None of those are visible if the socket is
faked away, so the socket is real.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from bpcad.web import server as web


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(url, **kw):
    return urllib.request.urlopen(url, timeout=60, **kw)


def get_json(url):
    with get(url) as response:
        return json.loads(response.read())


def status_of(url) -> int:
    try:
        with get(url) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ---------------------------------------------------------------------------
# the page itself
# ---------------------------------------------------------------------------


def test_the_page_and_its_assets_are_served(base_url):
    for path in ("/", "/static/app.css", "/static/app.js"):
        with get(base_url + path) as response:
            assert response.status == 200
            assert len(response.read()) > 200, "%s came back empty" % path


def test_the_interface_is_not_cached_but_the_renders_are(base_url):
    """
    The upgrade bug. Caching app.js for an hour means someone who updates
    bpcad keeps being served the old interface, with nothing to tell them
    that is what is happening. Renders may be cached hard - a built part's
    geometry never changes, because a refinement writes a new part.
    """
    with get(base_url + "/static/app.js") as response:
        assert "no-cache" in response.headers.get("Cache-Control", "")
    with get(base_url + "/") as response:
        assert "no-cache" in response.headers.get("Cache-Control", "")


def test_health_reports_the_pinned_printer(base_url):
    data = get_json(base_url + "/api/health")
    assert data["printer"]["name"] == "Creality i7"
    assert data["bed"]["height_mm"] == 255.0, "the bed is not a cube - 255, not 260"
    assert "petg" in data["materials"]


# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------


def test_the_library_lists_parts_with_their_sizes(base_url):
    data = get_json(base_url + "/api/parts")
    parts = data["parts"]
    assert parts, "no parts listed at all"
    sized = [p for p in parts if p.get("size_mm")]
    assert sized, (
        "every part came back with no size. The library calls this field "
        "envelope_mm, not bbox_mm, and reading the wrong one looks exactly "
        "like a part that has never been built."
    )


def test_a_part_resolves_by_both_of_its_names(base_url):
    """
    THE SAME PART HAS TWO NAMES. parts() calls it by its directory - "keyring" -
    and library() calls it by its spec name - "loop_keyring". Both get shown to
    people and both get linked, so both have to work.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    entry = next((p for p in parts if p.get("dir") and p["dir"] != p["name"]), None)
    if entry is None:
        pytest.skip("no part in this library whose two names differ")

    for name in (entry["name"], entry["dir"]):
        assert status_of("%s/api/part/%s" % (base_url, name)) == 200, \
            "%r did not resolve" % name


def test_a_part_carries_its_spec_and_its_measured_size(base_url):
    parts = get_json(base_url + "/api/parts")["parts"]
    data = get_json("%s/api/part/%s" % (base_url, parts[0]["name"]))

    # load_spec returns (PartSpec, base_dir). Handing the tuple to the
    # serialiser produced "{}" and a Spec tab that looked empty.
    assert data.get("spec"), "the spec came back empty"
    assert data["spec"].get("name"), "the spec has no name in it"
    assert data.get("size_mm"), "no size"


def test_a_stored_part_claims_no_verdict(base_url):
    """
    Nothing on disk records the verdict, and re-verifying costs as much as
    rebuilding. Inventing a PASS because the files exist is precisely the
    failure this program is built to avoid.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    data = get_json("%s/api/part/%s" % (base_url, parts[0]["name"]))
    assert "verdict" not in data


def a_built_part(base_url) -> dict:
    """
    A part with a mesh on disk, or a skip that says why.

    parts/*/out/ is gitignored deliberately - the meshes rebuild from the spec
    in seconds - so a fresh clone has specs and no STLs, and a test that
    assumed otherwise died with a bare StopIteration that said nothing.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    built = [p for p in parts if p.get("built")]
    if not built:
        pytest.skip("no part has been built yet - run `bpcad build parts/<name>/spec.yaml`")
    return built[0]


def test_the_stl_downloads(base_url):
    built = a_built_part(base_url)
    with get("%s/api/part/%s/stl" % (base_url, built["name"])) as response:
        body = response.read()
    assert len(body) > 1000
    assert "attachment" in response.headers.get("Content-Disposition", "")


def test_a_turntable_frame_renders_and_is_not_blank(base_url):
    built = a_built_part(base_url)
    url = "%s/api/part/%s/frame/3?w=240" % (base_url, built["name"])
    with get(url) as response:
        assert response.status == 200
        data = response.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "that is not a PNG"

    # A render that is entirely background is a render of nothing, and it looks
    # identical to a working viewer pointed at an empty scene.
    import io

    import numpy as np
    from PIL import Image

    pixels = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    lit = int((pixels.max(axis=2) > 30).sum())
    assert lit > 500, "only %d lit pixels - the frame is blank" % lit


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "../../etc/passwd",
    "..%2f..%2fetc",
    "name with spaces",
    "",
    "x" * 200,
])
def test_a_part_name_that_is_not_a_plain_name_is_refused(base_url, name):
    """
    Part names reach the filesystem. Anything that is not a plain name is
    refused outright rather than sanitised - sanitising is where traversal
    bugs live.
    """
    code = status_of("%s/api/part/%s/stl" % (base_url, urllib.parse.quote(name)))
    assert code in (400, 404), "got %d for %r" % (code, name)


def test_static_files_cannot_escape_their_directory(base_url):
    for path in ("/static/../server.py", "/static/..%2fserver.py",
                 "/static/../../config/default.toml"):
        assert status_of(base_url + path) in (400, 404), "escaped with %r" % path


def test_an_unknown_route_is_a_404_not_a_crash(base_url):
    assert status_of(base_url + "/api/nonsense") == 404


def test_generating_with_no_request_is_refused(base_url):
    request = urllib.request.Request(
        base_url + "/api/generate",
        data=json.dumps({"request": "   "}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=30)
    assert exc.value.code == 400


def test_a_body_that_is_not_json_is_refused_with_a_readable_message(base_url):
    request = urllib.request.Request(
        base_url + "/api/generate",
        data=b"{not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=30)
    assert exc.value.code == 400
    assert "JSON" in json.loads(exc.value.read())["error"]


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def test_a_job_replays_everything_that_happened_before_you_connected(base_url):
    """
    A phone that locks its screen drops the SSE connection. When it comes back
    it needs the whole story, not only what happened after it reconnected.
    """
    done = threading.Event()

    def work(job):
        job.emit("note", text="first")
        job.emit("note", text="second")
        done.wait(5)
        return {"ok": True, "name": "nothing"}

    job = web._start_job("test", "a test", work)
    while len(job.events) < 3:                    # started + two notes
        pass
    backlog, queue_ = job.subscribe()
    try:
        texts = [e.get("text") for e in backlog if e["kind"] == "note"]
        assert texts == ["first", "second"], (
            "a client connecting late got %r instead of the whole log" % texts
        )
    finally:
        job.unsubscribe(queue_)
        done.set()


def test_a_job_that_raises_reports_a_readable_message_not_a_traceback(base_url):
    done = threading.Event()

    def work(job):
        raise RuntimeError("the wall is 0.1 mm and the nozzle is 0.4 mm")

    job = web._start_job("test", "a test", work)
    for _ in range(200):
        if job.done:
            break
        done.wait(0.05)
    assert job.done
    assert job.result["ok"] is False
    assert "nozzle" in job.result["message"]
    assert "Traceback" not in job.result["message"]


def test_asking_for_a_job_that_does_not_exist_is_a_404(base_url):
    assert status_of(base_url + "/api/job/deadbeef0000") == 404
