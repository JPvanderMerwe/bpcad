"""
Proof that the deterministic side of bpcad never reaches for a model.

The brief's design requirement is that measure/, spec/, build/, verify/ and
render/ are pure CPU with no network and no model. This test imports every one
of them with httpx sabotaged, so any accidental network call at import time
fails loudly rather than silently working on a connected machine.
"""

import importlib

import pytest

DETERMINISTIC_MODULES = [
    "bpcad.measure.segment",
    "bpcad.measure.contour",
    "bpcad.measure.fit",
    "bpcad.measure.profile",
    "bpcad.spec.schema",
    "bpcad.spec.registry",
    "bpcad.spec.dsl",
    "bpcad.build.helpers",
    "bpcad.build.compile",
    "bpcad.build.templates.keyring_device",
    "bpcad.build.templates.louvre_vent",
    "bpcad.verify.mesh",
    "bpcad.verify.features",
    "bpcad.verify.probe",
    "bpcad.verify.overhang",
    "bpcad.verify.regression",
    "bpcad.verify.report",
    "bpcad.render.raster",
    "bpcad.render.views",
]


DETERMINISTIC_ENTRY_POINTS = [
    ("bpcad.verify.mesh", "check_mesh"),
    ("bpcad.verify.probe", "surface_heights"),
    ("bpcad.verify.probe", "height_map"),
    ("bpcad.verify.overhang", "overhang_report"),
    ("bpcad.verify.features", "check_features"),
    ("bpcad.render.raster", "render"),
    ("bpcad.render.views", "standard_views"),
]


@pytest.mark.parametrize("name", DETERMINISTIC_MODULES)
def test_imports_without_network(name, monkeypatch):
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError(
            "%s tried to make an HTTP request. The deterministic side of bpcad "
            "must work with the network cable out." % name
        )

    monkeypatch.setattr(httpx, "get", explode, raising=False)
    monkeypatch.setattr(httpx, "post", explode, raising=False)
    monkeypatch.setattr(httpx, "Client", explode, raising=False)

    importlib.import_module(name)


def test_cli_imports_without_network(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("no network"))
    importlib.import_module("bpcad.cli")


@pytest.mark.parametrize("module,attr", DETERMINISTIC_ENTRY_POINTS)
def test_phase_one_entry_points_exist(module, attr):
    """
    Everything Phase 1 promises is reachable with no model and no spec. If one
    of these disappears, the zero-model guarantee has quietly been broken.
    """
    assert hasattr(importlib.import_module(module), attr)


def test_the_whole_verify_path_runs_with_sockets_dead(monkeypatch, tmp_path):
    """
    The real proof, not an import check: run a complete verify and render on the
    reference part with socket creation sabotaged.
    """
    import socket
    from pathlib import Path

    real_socket = socket.socket

    class Blocked(real_socket):
        def __init__(self, *a, **k):
            raise AssertionError("verify/render must work with the cable out")

    monkeypatch.setattr(socket, "socket", Blocked)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("no network"))

    from bpcad.render import views
    from bpcad.verify.mesh import check_mesh, load_mesh
    from bpcad.verify.overhang import overhang_report
    from bpcad.verify.probe import surface_levels

    stl = Path(__file__).resolve().parent.parent / "reference" / "loop_keyring.stl"
    report = check_mesh(stl)
    mesh = load_mesh(stl)

    assert report.watertight and report.body_count == 1
    assert len(surface_levels(mesh)) == 6
    assert not overhang_report(mesh).supports_needed
    assert views.height_map_image(mesh, tmp_path / "h.png", nx=120, ny=120).is_file()
