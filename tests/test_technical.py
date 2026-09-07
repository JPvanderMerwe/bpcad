"""
The technical view. Design handoff section 5.

This is the design's viewport rendered on the CPU, and it is what both clients
show by default - so the things worth testing are the ones that would make it
stop being the design: the wrong colours, no edges, no floor, or a curved
surface covered in facet lines.

Nothing here checks a pixel against a stored image. A golden-image test on a
renderer that is meant to be tuned would fail on every improvement and teach
everybody to regenerate it without looking, which is worse than no test.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from bpcad.render import technical

ROOT = Path(__file__).resolve().parent.parent


def tokens() -> dict:
    return json.loads((ROOT / "design" / "tokens.json").read_text())


def as_float(hex_value: str) -> tuple[float, float, float]:
    raw = hex_value.lstrip("#")
    return tuple(int(raw[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


# ---------------------------------------------------------------------------
# the colours are the design's, and they cannot drift
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,token,section", [
    ("CASE", "case", "core"),
    ("BEZEL", "bezel", "core"),
    ("SOLID", "solid", "pen"),
    ("PEN_DIM", "dim", "pen"),
    ("PHOSPHOR", "phosphor", "core"),
])
def test_every_colour_matches_the_token_source(name, token, section):
    """
    The renderer cannot import a stylesheet, so it carries the five values it
    needs as floats. That is a second copy, and this is the gate that keeps it
    honest: a token retuned in design/tokens.json and not here would give a
    viewport that quietly disagrees with the interface drawn around it.
    """
    mine = getattr(technical, name)
    theirs = as_float(tokens()[section][token]["hex"])
    assert mine == pytest.approx(theirs, abs=1e-9)


def test_the_edge_threshold_is_three_js_own():
    """
    20 degrees, which is what `EdgesGeometry(geom, 20)` uses in the prototype.
    Arrived at from the other end and it has to stay the same number, or a
    cylinder either grows facet lines or loses its silhouette detail.
    """
    assert technical.EDGE_ANGLE_DEG == 20.0


def test_the_graticule_is_the_handoffs_own_grid():
    """"180-unit, 18-division grid in pen-dim at 50%"." """
    assert technical.GRID_SPAN_MM == 180.0
    assert technical.GRID_DIVISIONS == 18
    assert technical.GRID_ALPHA == 0.5


# ---------------------------------------------------------------------------
# what it draws
# ---------------------------------------------------------------------------

def a_box() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A 20mm cube standing on z=0, as vertices, faces and face normals."""
    import trimesh

    mesh = trimesh.creation.box(extents=(20, 20, 20))
    mesh.apply_translation([0, 0, 10])
    return (np.asarray(mesh.vertices), np.asarray(mesh.faces),
            np.asarray(mesh.face_normals))


def a_cylinder() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A smooth-sided cylinder: the shape that breaks a naive edge finder."""
    import trimesh

    mesh = trimesh.creation.cylinder(radius=10, height=30, sections=96)
    mesh.apply_translation([0, 0, 15])
    return (np.asarray(mesh.vertices), np.asarray(mesh.faces),
            np.asarray(mesh.face_normals))


def counts(image: np.ndarray) -> dict[tuple, int]:
    rgb = image[:, :, :3].reshape(-1, 3)
    values, totals = np.unique(rgb, axis=0, return_counts=True)
    return {tuple(int(c) for c in value): int(total)
            for value, total in zip(values, totals)}


def as_bytes(colour: tuple[float, float, float]) -> tuple[int, int, int]:
    return tuple(int(round(c * 255)) for c in colour)


def test_faces_are_flat_bezel_with_no_shading():
    """
    The design's faces are MeshBasicMaterial: unlit, ONE value. Shading them
    would put a gradient under the lines, and the whole point of this view is
    that the lines carry the form.

    A Lambert render of a cube produces three greys for its three visible
    sides. This must produce one.
    """
    vertices, faces, normals = a_box()
    image = technical.render_technical(
        vertices, faces, normals, width=200, height=200, alpha=False,
        graticule=False)

    found = counts(image)
    bezel = as_bytes(technical.BEZEL)
    assert found.get(bezel, 0) > 500, "the faces are not bezel"

    # Exactly three values on screen: the ground, the faces, the edges. A
    # fourth means something is being shaded or blended.
    assert len(found) == 3, "more than three values: %s" % sorted(found)


def test_a_cube_gets_its_edges_drawn():
    vertices, faces, normals = a_box()
    image = technical.render_technical(
        vertices, faces, normals, width=200, height=200, alpha=False,
        graticule=False)

    found = counts(image)
    assert found.get(as_bytes(technical.SOLID), 0) > 100, (
        "no edges were drawn"
    )


def test_a_cylinders_curved_side_is_not_covered_in_facet_lines():
    """
    THE RULE THE THRESHOLD EXISTS FOR. A cylinder is 96 facets and every
    boundary between them is a face-index change, so an edge finder that
    stops at "the index changed" fills the curved surface with lines and the
    part reads as a mesh rather than a solid.

    Checked as a ratio rather than a count, because the honest answer depends
    on the framing: the silhouette and the two end circles are legitimately
    edges, and they are a small fraction of the covered pixels.
    """
    vertices, faces, normals = a_cylinder()
    image = technical.render_technical(
        vertices, faces, normals, width=240, height=240, alpha=False,
        graticule=False)

    found = counts(image)
    edge = found.get(as_bytes(technical.SOLID), 0)
    face = found.get(as_bytes(technical.BEZEL), 0)
    assert face > 0, "the cylinder did not render"
    assert edge / (edge + face) < 0.30, (
        "the curved side is covered in facet lines: %d edge to %d face"
        % (edge, face)
    )


def test_the_silhouette_survives_even_on_a_smooth_shape():
    """
    The counterpart to the test above. A threshold high enough to clear the
    facet lines must not also lose the outline - and the outline is the one
    line that can never be missing, because without it the part has no shape
    at all against the ground.
    """
    vertices, faces, normals = a_cylinder()
    image = technical.render_technical(
        vertices, faces, normals, width=240, height=240, alpha=False,
        graticule=False)

    edge = np.all(image[:, :, :3] == as_bytes(technical.SOLID), axis=2)
    face = np.all(image[:, :, :3] == as_bytes(technical.BEZEL), axis=2)

    # Every row that has any part in it must have an edge pixel on both
    # sides of it: that is what an outline IS.
    rows = np.nonzero(face.any(axis=1))[0]
    assert len(rows) > 20
    for row in rows[len(rows) // 4: 3 * len(rows) // 4]:
        painted = np.nonzero(face[row] | edge[row])[0]
        assert edge[row, painted.min()] or edge[row, painted.min() + 1], (
            "row %d has no left outline" % row
        )
        assert edge[row, painted.max()] or edge[row, painted.max() - 1], (
            "row %d has no right outline" % row
        )


def test_the_floor_and_the_axes_are_drawn_under_the_part():
    vertices, faces, normals = a_box()
    with_floor = technical.render_technical(
        vertices, faces, normals, width=240, height=240, alpha=False)
    without = technical.render_technical(
        vertices, faces, normals, width=240, height=240, alpha=False,
        graticule=False)

    floor = counts(with_floor)
    bare = counts(without)

    # The grid's own tone: pen-dim at 50% over case, which is a value that
    # appears nowhere else.
    assert len(floor) > len(bare), "the graticule drew nothing"
    assert floor.get(as_bytes(technical.PHOSPHOR), 0) > 10, (
        "no amber axis lines"
    )


def test_the_background_is_transparent_by_default():
    """
    Both clients draw their own build plate, and a flat-backed render dropped
    on top of one reads as a hard rectangle around the part because the grid
    stops where the picture starts.
    """
    vertices, faces, normals = a_box()
    image = technical.render_technical(
        vertices, faces, normals, width=120, height=120, graticule=False)

    assert image.shape[2] == 4
    assert image[0, 0, 3] == 0, "the corner is not transparent"
    # And what IS drawn is opaque - a half-transparent part over a plate grid
    # would show the grid through the solid.
    assert (image[:, :, 3] == 255).any()


def test_it_renders_a_real_part_without_raising():
    """
    The synthetic shapes above are convex and closed. A real bpcad part has
    two bodies, fillets, a through bore and coincident faces, and it is the
    one that finds an index arithmetic mistake.
    """
    stl = ROOT / "parts" / "hinge_pip" / "out" / "hinge_pip.stl"
    if not stl.is_file():
        pytest.skip("hinge_pip has not been built in this tree")

    import trimesh

    mesh = trimesh.load(stl, force="mesh")
    image = technical.render_technical(
        np.asarray(mesh.vertices), np.asarray(mesh.faces),
        np.asarray(mesh.face_normals), width=300, height=240)

    assert image.shape == (240, 300, 4)
    assert (image[:, :, 3] == 255).sum() > 1000, "the part did not render"
