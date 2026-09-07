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


def status_of_post(url, payload) -> int:
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


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


def _first_built(base_url: str) -> dict:
    """
    A part that actually has geometry behind it.

    NOT parts[0]. The library is newest-first and it lists DRAFTS too - a run
    that failed hands off a spec.draft.yaml with no mesh, which is right, it
    is something you started. So the newest entry is whatever was attempted
    last, and taking it on faith made this test pass or fail depending on
    what had been generated that afternoon. It failed the first time a failed
    generate happened to be the most recent thing in the library.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    built = [p for p in parts if p.get("built") is not False]
    assert built, "the library has no built part to ask about"
    return built[0]


def test_a_part_carries_its_spec_and_its_measured_size(base_url):
    data = get_json("%s/api/part/%s" % (base_url, _first_built(base_url)["name"]))

    # load_spec returns (PartSpec, base_dir). Handing the tuple to the
    # serialiser produced "{}" and a Spec tab that looked empty.
    assert data.get("spec"), "the spec came back empty"
    assert data["spec"].get("name"), "the spec has no name in it"
    assert data.get("size_mm"), "no size"


def test_a_draft_says_it_has_no_mesh_rather_than_looking_broken(base_url):
    """
    The other half of the same fact, and a real bug on the phone: the app
    asked a draft for a render, got a guaranteed 404, and showed a broken
    card. The library payload has always said `built`, so a client never has
    to guess - and a draft must not claim an STL it does not have.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    drafts = [p for p in parts if p.get("built") is False]
    if not drafts:
        pytest.skip("no draft in the library to check")

    data = get_json("%s/api/part/%s" % (base_url, drafts[0]["name"]))
    assert data.get("has_stl") is not True, (
        "a draft reported an STL; a client will ask for a render and get a 404"
    )


def test_a_stored_part_claims_no_verdict(base_url):
    """
    Nothing on disk records the verdict, and re-verifying costs as much as
    rebuilding. Inventing a PASS because the files exist is precisely the
    failure this program is built to avoid.
    """
    data = get_json("%s/api/part/%s" % (base_url, _first_built(base_url)["name"]))
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
# the 3D viewer, and the cache that once served a white silhouette for a week
# ---------------------------------------------------------------------------


def test_the_viewer_page_is_served_with_its_renderer_beside_it(base_url):
    """
    ONE VIEWER PAGE, USED BY BOTH CLIENTS. The phone loads this in a WebView
    and the browser loads the same URL, which is the only way the two show a
    part the same way rather than nearly the same way.

    The script is vendored rather than fetched from a CDN because bpcad works
    with the cable out - a viewer that needs unpkg is a viewer that fails in a
    workshop with no signal. So the test is that the page is there AND that
    nothing in it points off this machine.
    """
    with get("%s/static/viewer.html" % base_url) as response:
        assert response.status == 200
        page = response.read().decode("utf-8")

    assert "<model-viewer" in page
    assert "/static/vendor/model-viewer.min.js" in page
    assert "//unpkg.com" not in page and "//cdn." not in page, (
        "the viewer fetches its renderer off this machine"
    )

    with get("%s/static/vendor/model-viewer.min.js" % base_url) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/javascript"
        assert len(response.read()) > 100_000, "that is not the renderer"

    # Apache-2.0 requires the licence to travel with the code.
    assert status_of("%s/static/vendor/model-viewer-LICENSE.txt"
                     % base_url) == 200


def test_the_glb_carries_a_material_so_it_is_not_a_white_silhouette(base_url):
    """
    A mesh exported straight out of CadQuery has no material, so every glTF
    viewer applies its own default - which is white, and a white part under a
    neutral environment is a silhouette with no readable form. That is what
    the first working viewer showed, and it looked enough like a bug in the
    viewer to send the search in the wrong direction.
    """
    built = a_built_part(base_url)
    with get("%s/api/part/%s/glb" % (base_url, built["name"])) as response:
        assert response.status == 200
        data = response.read()

    assert data[:4] == b"glTF", "that is not a GLB"

    # glTF's rule for a primitive with NO material is not "pick something
    # sensible": it is white, metallicFactor 1.0 - a mirror. So the check is
    # that a material exists and that it is not metallic, which is the part
    # that actually made the difference on screen.
    import struct

    length, = struct.unpack("<I", data[12:16])
    doc = json.loads(data[20:20 + length])

    materials = doc.get("materials")
    assert materials, "the GLB declares no material - glTF defaults to a mirror"
    pbr = materials[0]["pbrMetallicRoughness"]
    assert pbr["metallicFactor"] == 0.0, "printed plastic is not metal"
    assert 0.3 <= pbr["roughnessFactor"] <= 0.8, (
        "a mirror or a chalkboard; neither shows form"
    )

    # The grey the turntable frames and the desktop viewport already use. The
    # same part must not look like two objects depending on the view.
    red, green, blue, alpha = pbr["baseColorFactor"]
    assert [round(c * 255) for c in (red, green, blue)] == [158, 168, 184]
    assert alpha == 1.0

    # COLOR_0 as well, for a viewer that ignores materials.
    attributes = doc["meshes"][0]["primitives"][0]["attributes"]
    assert "COLOR_0" in attributes


def test_the_glb_url_can_be_versioned_so_the_hard_cache_stays_correct(base_url):
    """
    THE REGRESSION. The GLB is served `immutable, max-age=604800` on the
    argument that it is the mesh and not a picture of it. That argument broke
    the moment the part's grey was baked in: every file's content changed and
    no file's URL did, so a client that had already fetched the colourless one
    kept drawing white for a week with no way to ask for the new bytes.

    The fix is the frames' fix one layer down - the version goes in the query
    string, so a bump is a new URL. The server ignores the parameter on
    purpose: it exists to make the URL different, and the response must not
    depend on reading it.
    """
    assert web.MESH_VERSION >= 2, (
        "MESH_VERSION was not bumped when the GLB gained a baked colour"
    )

    built = a_built_part(base_url)
    plain = "%s/api/part/%s/glb" % (base_url, built["name"])
    versioned = "%s?mv=%d" % (plain, web.MESH_VERSION)

    with get(plain) as response:
        without = response.read()
        cache = response.headers["Cache-Control"]
    with get(versioned) as response:
        with_version = response.read()

    assert with_version == without, "the version changed the response"
    assert "immutable" in cache, (
        "the hard cache was given up instead of being versioned"
    )

    # An unknown parameter must not 404 or 500 the mesh - the whole point is
    # that a future client can bump the number unilaterally.
    assert status_of("%s?mv=99" % plain) == 200


def test_no_response_carries_two_cache_control_headers(base_url):
    """
    A SILENT BUG, WHICH IS WHY IT GETS ITS OWN TEST.

    _send emitted its own Cache-Control and then the caller's, so the GLB went
    out carrying `no-cache` AND `public, max-age=604800, immutable`. A client
    reads a repeated header as one comma-joined list, no-cache wins it, and the
    mesh was refetched on every single look while the code said it was cached
    for a week. Nothing failed, nothing logged, it was just slow - and the
    header the source claimed was being sent was not the header in force.
    """
    built = a_built_part(base_url)
    for path in ("/", "/static/app.css", "/api/health", "/api/parts",
                 "/api/part/%s" % built["name"],
                 "/api/part/%s/glb" % built["name"],
                 "/api/part/%s/frame/1?w=240" % built["name"]):
        with get(base_url + path) as response:
            values = response.headers.get_all("Cache-Control") or []
        assert len(values) <= 1, (
            "%s sends %d Cache-Control headers: %s" % (path, len(values), values)
        )


def test_the_mesh_is_cached_hard_because_its_url_is_versioned(base_url):
    """
    The other half: having stopped sending two, the one that is sent has to be
    the immutable one. A 40 000-face bowl is nearly two megabytes and the
    server walks the mesh to build it, so a second look at the same part must
    cost nothing.
    """
    built = a_built_part(base_url)
    with get("%s/api/part/%s/glb" % (base_url, built["name"])) as response:
        cache = response.headers["Cache-Control"]
    assert "immutable" in cache, cache
    assert "no-cache" not in cache, cache


def test_the_health_reports_the_mesh_version_so_no_client_repeats_it(base_url):
    """
    The viewer page reads this rather than carrying the constant, because a
    number written in Python and again in JavaScript is a number that drifts -
    and the drift here is silent: the page keeps asking for a URL that was
    correct last month.
    """
    state = get_json("%s/api/health" % base_url)
    assert state["mesh_version"] == web.MESH_VERSION
    # Separate from the frames' version on purpose: a new camera angle must
    # not throw away every cached mesh, and a new baked colour must not throw
    # away every cached frame.
    assert "render_version" in state


# ---------------------------------------------------------------------------
# the command line and the parameter schema, which the workspace is built on
# ---------------------------------------------------------------------------


def post(url, payload):
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def test_the_command_line_parses_server_side(base_url):
    """
    ONE PARSER, AND THIS ROUTE IS WHY IT CAN BE ONE. The handoff says the
    command line must genuinely parse and must share the composer's
    vocabulary. Parsed in each client, `wall 3` would mean one thing in the
    browser and another on the phone - the same class of bug as a colour that
    differs between clients, except this one changes geometry.
    """
    parsed = post("%s/api/command" % base_url, {"line": "wall 3"})
    assert parsed["kind"] == "set"
    assert parsed["parameter"] == "wall_mm"
    assert parsed["value"] == 3.0
    # The echo uses the panel's own words, both directions - brief 6.4.
    assert parsed["echo"] == "wall thickness \u2192 3.0 mm"
    # And it carries the sentence that applies the change, so a slider and a
    # typed command cannot ask for different things.
    assert parsed["refine"] == "set wall thickness to 3.0 mm"


def test_a_question_is_answered_from_the_real_profile(base_url):
    """
    `clearance ?` reads this machine's configuration - and says where the
    number came from. Brief 4.3 forbids stating a clearance as if it were
    calibrated when it is a conservative default, because a maker who
    believes a number is measured designs to it.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "clearance ?", "material": "petg"})
    assert parsed["kind"] == "ask"
    assert "0.30 mm" in parsed["echo"]
    assert "not from a calibration strip" in parsed["echo"], (
        "a default clearance was reported as though it were measured"
    )


def test_an_unmeasured_clearance_says_so_rather_than_inventing_one(base_url):
    """
    TPU's clearance is deliberately UNSET because nothing measured it, and
    reading an UNSET value raises rather than substituting a guess. The
    command line has to survive that and answer honestly.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "clearance ?", "material": "tpu"})
    assert "no measured source" in parsed["echo"]


def test_an_unknown_line_is_a_new_part_and_not_an_error(base_url):
    """
    A command line that only accepts commands is a worse command line: the
    thing a maker most wants to type is a description of a part.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "a hinged clamp for a 32 mm pipe"})
    assert parsed["kind"] == "prompt"
    assert parsed["text"] == "a hinged clamp for a 32 mm pipe"


def test_a_command_without_a_line_is_refused_rather_than_guessed(base_url):
    assert status_of_post("%s/api/command" % base_url, {}) == 400
    assert status_of_post("%s/api/command" % base_url, {"line": 7}) == 400
    # Longer than any command line, which is a paste accident rather than a
    # command, and it must not become a two-minute generation.
    assert status_of_post("%s/api/command" % base_url,
                          {"line": "x" * 500}) == 400


def test_refine_reaches_the_agent_instead_of_dying_on_a_type(base_url):
    """
    THE REGRESSION. api.refine takes a loaded PartSpec; this route passed the
    part NAME straight through, so every refine died inside the agent on
    `'str' object has no attribute 'level'`.

    It had never worked. Nothing exercised it until the phone's command line
    ran `wall 3` against a real part - and the web client's refine box had
    been broken in the same way for as long as it had existed.

    THIS TEST DOES NOT RUN A REFINE. A real one calls the model and takes
    minutes on a CPU. What it checks is the boundary that was wrong: a valid
    name is accepted and gets a job, and an unknown one is refused with a
    sentence rather than a type error - which is enough to catch a name being
    handed to something that wants a spec.
    """
    built = a_built_part(base_url)

    accepted = post("%s/api/refine" % base_url,
                    {"name": built["name"], "instruction": "make it taller"})
    assert accepted.get("job"), "a valid part did not start a refine"

    # And the job must not have died immediately on a type error. The work
    # runs on a thread, so this reads the job back rather than the response.
    import time
    for _ in range(20):
        state = get_json("%s/api/job/%s" % (base_url, accepted["job"]))
        message = str((state.get("result") or {}).get("message", ""))
        assert "has no attribute" not in message, (
            "the refine route is still handing a name to something that "
            "wants a spec: %s" % message
        )
        if state.get("done"):
            break
        time.sleep(0.25)


def test_refining_a_part_that_is_not_there_says_so(base_url):
    """A missing part is a sentence, not a traceback."""
    answer = post("%s/api/refine" % base_url,
                  {"name": "not_a_part", "instruction": "make it taller"})
    job = answer.get("job")
    assert job, "the route refused before it could even look"

    import time
    for _ in range(20):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            result = state.get("result") or {}
            assert result.get("ok") is False
            assert "no part called" in str(result.get("message", ""))
            return
        time.sleep(0.25)
    raise AssertionError("the job never finished")


def test_the_template_schema_carries_real_bounds_for_the_sliders(base_url):
    """
    THIS IS WHERE THE SLIDERS' MIN AND MAX COME FROM, and the reason the route
    exists rather than the clients holding a table. The bounds are the
    Pydantic schema's own, so a slider cannot offer a value the builder will
    reject - and a client inventing its own range would be guessing at a
    dimension, which is the one thing this project does not do.
    """
    schema = get_json("%s/api/template/louvre_vent" % base_url)
    params = {p["name"]: p for p in schema["params"]}

    frame = params["frame_w_mm"]
    assert frame["units"] == "mm"
    assert frame["bounds"]["gt"] == 10.0
    assert frame["bounds"]["le"] == 400.0
    assert frame["description"]

    # An INTEGER parameter is typed as one, which is what stops a blade count
    # rendering as "4.0" and sliding to 4.3.
    assert params["n_blades"]["type"] == "int"
    assert params["n_blades"]["bounds"] == {"ge": 2, "le": 24}


def test_every_template_the_health_lists_can_be_read(base_url):
    """
    The workspace builds its parameter form from whatever the registry knows,
    with no per-template code. A template that is listed but cannot be
    described is a panel that fails to open for exactly one part.
    """
    for name in get_json("%s/api/health" % base_url)["templates"]:
        schema = get_json("%s/api/template/%s" % (base_url, name))
        assert schema["name"] == name
        assert isinstance(schema.get("params"), list)


def test_an_unknown_template_is_a_404_and_not_a_500(base_url):
    assert status_of("%s/api/template/not_a_template" % base_url) == 404


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


# ---------------------------------------------------------------------------
# one UI, and it has to be installable on a phone
# ---------------------------------------------------------------------------


def test_the_desktop_entry_point_reaches_the_web_ui():
    """
    THE BUG THAT WASTED A SESSION, PINNED.

    A console script shim records the import path it was generated with. An
    editable install updates the modules and NOT the shim, so repointing
    `bpcad-gui` in pyproject.toml changes nothing until somebody reinstalls -
    and the symptom is launching the old interface and concluding the work was
    never done. Both paths must land on the shell.
    """
    # READ THE SOURCE, DO NOT IMPORT IT. bpcad.gui.app pulls in PySide6 at
    # module scope, and importing Qt inside a pytest process that is already
    # running an HTTP server hangs indefinitely - the test suite stopped dead
    # at this point with no output. The fact under test is textual anyway.
    from pathlib import Path

    src = Path("bpcad/gui/app.py").read_text()
    assert "def classic_main(" in src, "--classic has nothing to reach"
    forward = src[src.index("def main("):]
    assert "shell_main" in forward, (
        "bpcad.gui.app.main no longer forwards to the shell, so a stale "
        "console script shim will launch the old Qt app"
    )


def test_the_shell_serves_the_same_files_the_phone_gets():
    """One UI means one set of files, not a desktop port of them."""
    from pathlib import Path

    from bpcad.web import server as web_server

    # Same reason as above: gui.shell is read, not imported.
    src = Path("bpcad/gui/shell.py").read_text()
    assert "from bpcad.web.server import Handler" in src, (
        "the desktop shell no longer serves the web app's own handler, so the "
        "two front ends can diverge again"
    )
    assert web_server.STATIC_DIR.is_dir()
    for name in ("index.html", "app.css", "app.js"):
        assert (web_server.STATIC_DIR / name).is_file()


def test_the_manifest_is_served_as_a_manifest(base_url):
    """
    Served as application/octet-stream a manifest is ignored by every browser,
    silently, and the app simply is not installable with nothing to say why.
    """
    with get(base_url + "/static/manifest.webmanifest") as response:
        assert response.headers.get("Content-Type") == "application/manifest+json"
        manifest = json.loads(response.read())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes, "Android needs 192 and 512"
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"]), (
        "without a maskable icon Android crops the mark inside a white circle"
    )


def test_every_icon_the_manifest_promises_exists(base_url):
    manifest = get_json(base_url + "/static/manifest.webmanifest")
    for icon in manifest["icons"]:
        assert status_of(base_url + icon["src"]) == 200, "missing %s" % icon["src"]
    assert status_of(base_url + "/static/icons/apple-touch-icon.png") == 200


def test_the_service_worker_may_control_the_whole_app(base_url):
    """
    A worker served from /static/ can only control /static/ unless the response
    says otherwise. Without the header it registers, reports success, and
    controls nothing.
    """
    with get(base_url + "/static/sw.js") as response:
        assert response.headers.get("Service-Worker-Allowed") == "/"
        assert response.headers.get("Content-Type") == "text/javascript"
        body = response.read().decode()
    assert "/api/" in body, "the worker does not mention the API at all"


def test_the_service_worker_never_caches_the_api(base_url):
    """
    A cached /api/parts is a library missing what you made this morning, and a
    cached STL is somebody printing yesterday's geometry. The whole claim of
    this program is that the numbers shown are the numbers measured.
    """
    with get(base_url + "/static/sw.js") as response:
        body = response.read().decode()

    # Check the GUARD, not the prose. The first "/api/" in the file is in the
    # explanatory comment at the top, so searching for the first occurrence and
    # looking nearby for "return" was reading documentation and calling it a
    # test - it failed while the actual guard was right there and correct.
    assert "if (url.pathname.startsWith('/api/')) return;" in body, (
        "the service worker does not bail out of /api/ before its caching "
        "logic, so a part list or an STL can be served stale"
    )
    fetch_body = body[body.index("addEventListener('fetch'"):]
    assert fetch_body.index("startsWith('/api/')") < fetch_body.index("respondWith"), (
        "the /api/ guard comes AFTER respondWith, so it does not guard anything"
    )


def test_the_page_declares_itself_installable(base_url):
    with get(base_url + "/") as response:
        html = response.read().decode()
    for tag in ('rel="manifest"',
                'apple-mobile-web-app-capable',
                'apple-touch-icon'):
        assert tag in html, "missing %s - iOS will not install it" % tag


# ---------------------------------------------------------------------------
# saying what the machine can do, honestly
# ---------------------------------------------------------------------------


def test_health_says_what_this_machine_can_do(base_url):
    data = get_json(base_url + "/api/health")
    cap = data.get("capability")
    assert cap, "health does not report capability at all"
    assert cap["tier"] in ("gpu", "cpu", "no-model", "unknown")
    assert cap["headline"], "no headline for a person to read"


def test_no_gpu_is_reported_as_slow_and_never_as_broken():
    """
    A machine with no GPU is not unsupported. Every template, every fitter,
    every import and every export works identically on it - only the prompt
    step is slow. Telling somebody their working machine is broken is worse
    than telling them nothing.
    """
    from bpcad.capability import Capability

    cap = Capability(gpu=False, model_available=True, model_name="qwen2.5-coder:7b")
    headline = cap.headline().lower()
    assert "cpu" in headline
    assert "minute" in headline, "the wait is not stated, so it reads as a hang"
    for word in ("unsupported", "error", "failed", "cannot", "required"):
        assert word not in headline, "%r makes a working machine sound broken" % word


def test_the_wait_is_stated_before_it_is_endured():
    from bpcad.capability import Capability

    cpu = Capability(gpu=False, model_available=True, model_name="m")
    gpu = Capability(gpu=True, model_on_gpu=True, model_available=True, model_name="m")
    assert cpu.prompt_seconds > gpu.prompt_seconds * 3, (
        "if CPU and GPU are quoted the same, the number is decorative"
    )
    assert str(round(cpu.prompt_seconds / 60)) in cpu.headline()


def test_no_model_still_offers_the_rest_of_the_program():
    """
    `spec.yaml` is the durable artifact and none of it needs a model. The
    message has to say so, or somebody with no Ollama concludes the app is
    useless to them.
    """
    from bpcad.capability import Capability

    cap = Capability(model_available=False)
    assert cap.tier == "no-model"
    text = cap.headline().lower()
    assert "rebuild" in text or "works" in text


def test_requiring_a_gpu_explains_what_still_works():
    """
    A refusal that only says "GPU required" leaves somebody thinking the whole
    program needs one. It does not - almost none of it does.
    """
    import pytest as _pytest

    from bpcad.capability import Capability, require_gpu

    with _pytest.raises(RuntimeError) as exc:
        require_gpu("Generating a mesh", Capability(gpu=False))
    message = str(exc.value)
    assert "Everything else" in message
    assert "export" in message

    # And it must not refuse on a machine that HAS one.
    require_gpu("Generating a mesh", Capability(gpu=True))


def test_nothing_in_the_program_currently_requires_a_gpu():
    """
    A slow answer is an answer. If require_gpu ever gets called on a path that
    merely runs slowly, a working program disappears for everyone without a
    graphics card.
    """
    import subprocess

    out = subprocess.run(
        ["grep", "-rn", "require_gpu", "bpcad/"],
        capture_output=True, text=True,
    )
    callers = [line for line in out.stdout.splitlines()
               if "capability.py" not in line]
    assert not callers, "require_gpu is called from: %s" % callers
