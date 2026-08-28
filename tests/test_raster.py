"""
The rasteriser, and above all its z-test direction.

An inverted z-test renders the BACK of the object and looks entirely plausible.
It is not catchable by eye. It is catchable by a deliberately asymmetric scene,
so that is what these do. Rule 26 exists because this exact bug shipped once.
"""

import numpy as np
import pytest
import trimesh

from bpcad.render import raster as R


def quad(size, z):
    v = np.array(
        [[-size, -size, z], [size, -size, z], [size, size, z], [-size, size, z]],
        dtype=float,
    )
    return v, np.array([[0, 1, 2], [0, 2, 3]])


@pytest.fixture
def stacked_quads():
    """A small quad at z=5 floating over a large quad at z=0."""
    vf, ff = quad(10.0, 0.0)
    vn, fn = quad(3.0, 5.0)
    return np.vstack([vf, vn]), np.vstack([ff, fn + 4])


@pytest.fixture
def asymmetric_solid():
    """A box with a boss protruding on the +Z side only, and interpenetrating."""
    box = trimesh.creation.box(extents=(20, 20, 4))          # z -2 .. 2
    boss = trimesh.creation.cylinder(radius=3.0, height=6.0)
    boss.apply_translation((0, 0, 2))                        # z -1 .. 5
    return trimesh.util.concatenate([box, boss])


def buffer_from(vertices, faces, elev, azim, n=101):
    tu, tv, tw = R.project_camera(vertices, faces, *R.view_basis(elev, azim))
    bounds = R.fit_bounds(tu, tv, n, n)
    return R.zbuffer(tu, tv, tw, n, n, bounds)


def test_nearer_surface_wins(stacked_quads):
    """The whole ballgame. 5.0 means near wins; 0.0 means the z-test is inverted."""
    v, f = stacked_quads
    depth, _ = buffer_from(v, f, 90.0, 0.0)
    assert depth[50, 50] == pytest.approx(5.0)


def test_far_surface_still_visible_where_nothing_covers_it(stacked_quads):
    v, f = stacked_quads
    depth, _ = buffer_from(v, f, 90.0, 0.0)
    assert depth[50, 5] == pytest.approx(0.0)


def test_asymmetric_solid_seen_from_the_boss_side(asymmetric_solid):
    m = asymmetric_solid
    depth, _ = buffer_from(m.vertices, m.faces, 90.0, 0.0, n=201)
    assert depth[100, 100] == pytest.approx(5.0), "must see the boss, not through it"


def test_asymmetric_solid_seen_from_the_flat_side(asymmetric_solid):
    """From behind, the boss is hidden by the box. If it is not, we are seeing through."""
    m = asymmetric_solid
    depth, _ = buffer_from(m.vertices, m.faces, -90.0, 0.0, n=201)
    assert depth[100, 100] == pytest.approx(2.0)


def test_interpenetrating_parts_do_not_render_through_each_other(asymmetric_solid):
    """
    The exact failure that made Poly3DCollection unusable: it depth-sorts whole
    polygons, so a shell renders straight through.
    """
    m = asymmetric_solid
    depth, index = buffer_from(m.vertices, m.faces, 25.0, 315.0, n=201)
    hit = index >= 0
    assert hit.any()
    assert np.isfinite(depth[hit]).all()


def test_view_basis_is_orthonormal_and_right_handed():
    for elev, azim in [(0, 0), (25, 315), (90, 270), (-90, 270), (37, 123)]:
        right, up, view = R.view_basis(elev, azim)
        for vec in (right, up, view):
            assert np.linalg.norm(vec) == pytest.approx(1.0)
        assert right @ up == pytest.approx(0.0, abs=1e-12)
        assert right @ view == pytest.approx(0.0, abs=1e-12)
        assert up @ view == pytest.approx(0.0, abs=1e-12)
        assert np.cross(right, up) @ view == pytest.approx(1.0)


def test_view_basis_convention_at_the_origin_view():
    """elev 0, azim 0: camera on +X, screen right is +Y, screen up is +Z."""
    right, up, view = R.view_basis(0.0, 0.0)
    assert view == pytest.approx([1, 0, 0], abs=1e-12)
    assert right == pytest.approx([0, 1, 0], abs=1e-12)
    assert up == pytest.approx([0, 0, 1], abs=1e-12)


def test_empty_pixels_are_marked_not_zero(stacked_quads):
    """-inf, never 0.0. A depth of zero is a real depth and must not mean 'miss'."""
    v, f = stacked_quads
    depth, index = buffer_from(v, f, 25.0, 315.0)
    assert (depth[index < 0] == -np.inf).all()


def test_fit_bounds_preserves_aspect():
    u = np.array([0.0, 10.0])
    v = np.array([0.0, 2.0])
    b = R.fit_bounds(u, v, 400, 200, margin=0.0)
    assert b.width / b.height == pytest.approx(2.0)
    assert b.u0 <= 0.0 and b.u1 >= 10.0
    assert b.v0 <= 0.0 and b.v1 >= 2.0


def test_degenerate_triangles_are_skipped_not_crashed():
    """A triangle projecting to a line has zero area. Dividing by it is the bug."""
    v = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=float)
    f = np.array([[0, 1, 2]])
    depth, index = R.zbuffer(
        v[f][:, :, 0], v[f][:, :, 1], v[f][:, :, 2], 16, 16, R.Bounds(-1, 3, -1, 1)
    )
    assert (index < 0).all()


def test_render_produces_an_image(asymmetric_solid):
    m = asymmetric_solid
    img = R.render(m.vertices, m.faces, m.face_normals, width=64, height=48)
    assert img.shape == (48, 64, 3)
    assert img.dtype == np.uint8
    assert img.max() > img.min(), "the render is a flat colour, nothing was drawn"


def test_shading_never_leaves_a_visible_face_black(asymmetric_solid):
    m = asymmetric_solid
    _, _, view = R.view_basis(25.0, 315.0)
    shade = R.shade_lambert(m.face_normals, np.array([0.3, 0.4, 0.9]), view, ambient=0.32)
    assert shade.min() >= 0.32 - 1e-12
    assert shade.max() <= 1.0 + 1e-12
