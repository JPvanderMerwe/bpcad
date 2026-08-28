"""
Views, the height map and the cutaway.

The height map is the primary verification visual, so it gets the most checks.
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from bpcad.render import views as V
from bpcad.verify.mesh import load_mesh
from bpcad.verify.probe import surface_levels

REFERENCE_STL = Path(__file__).resolve().parent.parent / "reference" / "loop_keyring.stl"


@pytest.fixture(scope="module")
def keyring():
    return load_mesh(REFERENCE_STL)


def test_standard_views_write_files(keyring, tmp_path):
    paths = V.standard_views(keyring, tmp_path, width=160, height=140)
    assert set(paths) == set(V.DEFAULT_VIEWS)
    for p in paths.values():
        assert p.is_file()
        assert Image.open(p).size == (160, 140)


def test_unknown_view_is_rejected(keyring):
    with pytest.raises(ValueError) as exc:
        V.render_view(keyring, "sideways")
    assert "sideways" in str(exc.value)


def test_height_map_image_is_written_and_matches_the_part_aspect(keyring, tmp_path):
    out = V.height_map_image(keyring, tmp_path / "h.png", nx=300, ny=300, scale_bar=False)
    assert out.is_file()
    w, h = Image.open(out).size
    ext = keyring.bounds[1] - keyring.bounds[0]
    assert (w / h) == pytest.approx(ext[0] / ext[1], rel=0.02)


def test_height_map_image_carries_a_scale_bar(keyring, tmp_path):
    plain = V.height_map_image(keyring, tmp_path / "a.png", nx=200, ny=200, scale_bar=False)
    barred = V.height_map_image(keyring, tmp_path / "b.png", nx=200, ny=200, scale_bar=True)
    assert Image.open(barred).size[0] > Image.open(plain).size[0]


def test_height_map_shows_every_level_as_a_different_colour(keyring, tmp_path):
    """
    The point of the height map. A flat-shaded render cannot show a recess whose
    floor shares a normal with the surface around it; distinct colours can.
    """
    out = V.height_map_image(keyring, tmp_path / "h.png", nx=600, ny=600, scale_bar=False)
    img = np.asarray(Image.open(out).convert("RGB")).reshape(-1, 3)
    colours = {tuple(c) for c in img}
    assert len(colours) >= len(surface_levels(keyring, axis="z"))


def test_colourise_marks_misses_as_background():
    hmap = np.array([[1.0, np.nan], [np.nan, 2.0]])
    img = V.colourise(hmap, background=(1.0, 0.0, 1.0))    # magenta, unmistakable
    # colourise flips vertically, so old row 1 becomes row 0.
    assert tuple(img[0, 0]) == (255, 0, 255)               # was hmap[1, 0] = nan
    assert tuple(img[1, 1]) == (255, 0, 255)               # was hmap[0, 1] = nan
    assert tuple(img[0, 1]) != (255, 0, 255)               # was 2.0, a real height
    assert tuple(img[1, 0]) != (255, 0, 255)               # was 1.0, a real height


def test_cutaway_discards_the_half_nearest_the_camera():
    """
    The rule that is easy to get backwards. "front" puts the camera on -Y, so
    the -Y half is what has to go. Keeping it instead renders the outside of
    the part again, which looks exactly like a cutaway that did nothing.
    """
    box = trimesh.creation.box(extents=(20, 20, 20))
    centres = box.triangles_center[:, 1]

    mask = V.cutaway_mask(box, axis="y", view="front")
    assert (centres[mask] >= 0).all(), "the near half must be discarded"

    mask = V.cutaway_mask(box, axis="y", view="back")   # camera on +Y instead
    assert (centres[mask] <= 0).all()


def test_cutaway_keep_overrides_the_camera():
    box = trimesh.creation.box(extents=(20, 20, 20))
    centres = box.triangles_center[:, 1]
    assert (centres[V.cutaway_mask(box, axis="y", view="front", keep="low")] <= 0).all()
    assert (centres[V.cutaway_mask(box, axis="y", view="front", keep="high")] >= 0).all()


def test_cutaway_rejects_a_bad_keep():
    box = trimesh.creation.box(extents=(10, 10, 10))
    with pytest.raises(ValueError):
        V.cutaway_mask(box, keep="middle")


def test_section_exposes_an_interior_surface(tmp_path):
    """
    A hollow shell renders as a solid block from outside. Cut it and the nearest
    visible surface has to move deeper into the part.
    """
    from bpcad.render import raster as R

    outer = trimesh.creation.box(extents=(20, 20, 20))
    inner = trimesh.creation.box(extents=(10, 10, 10))
    shell = trimesh.util.concatenate([outer, inner])

    def nearest_depth(faces):
        tu, tv, tw = R.project_camera(
            shell.vertices, faces, *R.view_basis(*V.VIEWS["front"])
        )
        depth, _ = R.zbuffer(tu, tv, tw, 41, 41, R.fit_bounds(tu, tv, 41, 41))
        return depth[20, 20]

    whole = nearest_depth(shell.faces)
    mask = V.cutaway_mask(shell, axis="y", view="front")
    cut = nearest_depth(shell.faces[mask])

    assert whole == pytest.approx(10.0)   # the outer front wall at y = -10
    assert cut == pytest.approx(-5.0)     # the inner box's far wall at y = +5
    assert cut < whole, "the cutaway did not expose anything new"

    assert V.section(shell, tmp_path / "s.png", axis="y", view="front",
                     width=80, height=80).is_file()


def test_section_off_the_part_raises_with_the_range(tmp_path):
    box = trimesh.creation.box(extents=(10, 10, 10))
    with pytest.raises(ValueError) as exc:
        V.section(box, tmp_path / "s.png", axis="y", position=-99.0, keep="low")
    assert "-5.000 to 5.000" in str(exc.value)


def test_level_summary_lines_match_the_levels(keyring):
    assert len(V.level_summary(keyring)) == len(surface_levels(keyring))
