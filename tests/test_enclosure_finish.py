"""
The exterior finish on the enclosure.

Both of these tests exist because the thing they check went wrong, silently,
and produced a part that passed everything else.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from bpcad.build.helpers import BuildLog, probe
from bpcad.build.templates.enclosure import EnclosureParams, build_box, derive
from bpcad.verify.fit import mesh_of_solid

FINISHES = ("plain", "board", "slat")


def built(**params):
    p = EnclosureParams(**params)
    return p, build_box(p, derive(p), BuildLog())


@pytest.mark.parametrize("finish", FINISHES)
def test_a_finish_leaves_one_sound_body(finish):
    """
    The board groove's ramp and the land it cuts against have to MEET. Half a
    millimetre of gap between them let the cutter through the wall and the box
    came out as eighteen loose rings - watertight, valid, exportable, and not
    a birdhouse.
    """
    _p, box = built(finish=finish)
    solids = box.val().Solids()
    assert len(solids) == 1, "%s finish split the box into %d pieces" % (
        finish, len(solids)
    )
    assert probe(box), "%s finish produced a solid that fails a real boolean" % finish


@pytest.mark.parametrize("finish", FINISHES)
def test_a_finish_does_not_breach_the_cavity(finish):
    """A groove that reaches through the wall is a hole, not a texture."""
    p, box = built(finish=finish)
    plain_vol = built(finish="plain")[1].val().Volume()
    vol = box.val().Volume()
    # A finish removes material, but only a sliver of it. Losing more than a
    # twentieth means it is cutting into something it should not be.
    assert vol <= plain_vol
    assert vol > plain_vol * 0.95, (
        "%s removed %.1f%% of the box - that is not a surface finish"
        % (finish, 100 * (1 - vol / plain_vol))
    )


def test_the_board_grooves_do_not_add_a_ceiling():
    """
    THE WHOLE POINT OF THE RAMP. A square-cut groove's top face points straight
    down, and forty of them round this box put 4 600 mm2 of unsupported
    overhang on a part that had 480. The first ramp made it worse - 5 606 mm2 -
    because it lofted out to the size of the throwaway cutting slab rather than
    back to the wall face, which is a 26-degree ceiling wearing a ramp's name.

    Measured off the mesh, because both wrong versions looked correct in a
    render and reported PASS.
    """
    def overhang_mm2(finish: str) -> float:
        mesh = mesh_of_solid(built(finish=finish)[1])
        normals, areas = mesh.face_normals, mesh.area_faces
        top_z = mesh.vertices[mesh.faces][:, :, 2].max(axis=1)
        down = -normals[:, 2]
        # Within 45 degrees of pointing straight down, and not the bed face.
        bad = (down > math.cos(math.radians(45))) & (top_z > 0.5)
        return float(np.asarray(areas)[bad].sum())

    plain = overhang_mm2("plain")
    board = overhang_mm2("board")
    assert board < plain * 1.5, (
        "the board finish adds %.0f mm2 of overhang to a part that had %.0f. "
        "The groove ramp is not shallow enough - check it lofts back to the "
        "WALL face and not to the cutting slab." % (board - plain, plain)
    )


def test_a_groove_deeper_than_a_third_of_the_wall_is_refused():
    with pytest.raises(ValueError) as exc:
        EnclosureParams(finish="board", wall_mm=3.0, finish_depth_mm=2.5)
    assert "third" in str(exc.value)


def test_grooves_wider_than_their_spacing_are_refused():
    with pytest.raises(ValueError) as exc:
        EnclosureParams(finish="slat", finish_groove_mm=15.0, finish_pitch_mm=11.0)
    assert "overlap" in str(exc.value)


def test_the_groove_width_is_recorded_so_the_nozzle_check_sees_it():
    """
    A groove finer than the nozzle prints as a smooth face: a wasted print that
    looks exactly like a successful one. Recording it as a feature is what
    makes the existing linter catch that, with no new code.
    """
    from bpcad.build.templates.enclosure import build
    from bpcad.spec.schema import PartSpec

    spec = PartSpec(name="x", level=1, material="petg", nozzle_mm=0.4,
                    layer_mm=0.24, template="enclosure",
                    params={"finish": "board", "finish_groove_mm": 0.3})
    result = build(EnclosureParams(finish="board", finish_groove_mm=0.3), spec)
    assert result.features.get("finish groove") == 0.3


def test_plain_is_still_the_default():
    """Nobody asked for a textured box by default, and the reference parts pin it."""
    assert EnclosureParams().finish == "plain"
