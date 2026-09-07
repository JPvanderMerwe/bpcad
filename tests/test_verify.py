"""
Phase 1 acceptance, plus the checks each verify module owes.

The reference keyring is the fixed point: it is a known-good part with known
numbers, so anything that changes those numbers is a regression in bpcad, not
in the part.
"""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from bpcad.verify.features import MARGINAL, PASS, TOO_FINE, check_features
from bpcad.verify.mesh import check_mesh, load_mesh, report_for
from bpcad.verify.overhang import overhang_report
from bpcad.verify.probe import (
    height_map,
    levels_present_in,
    surface_heights,
    surface_levels,
)
from bpcad.verify.regression import (
    check_regression,
    load_baseline,
    save_baseline,
    signature_of,
)

REFERENCE_STL = Path(__file__).resolve().parent.parent / "reference" / "loop_keyring.stl"


@pytest.fixture(scope="module")
def keyring():
    return load_mesh(REFERENCE_STL)


@pytest.fixture(scope="module")
def keyring_report():
    return check_mesh(REFERENCE_STL)


# -- Phase 1 acceptance -----------------------------------------------------


def test_acceptance_watertight(keyring_report):
    assert keyring_report.watertight
    assert keyring_report.is_volume


def test_acceptance_single_body(keyring_report):
    assert keyring_report.body_count == 1


def test_acceptance_volume_in_range(keyring_report):
    """The brief's number: 6.5 to 6.6 cm3."""
    assert 6.5 <= keyring_report.volume_cm3 <= 6.6


def test_acceptance_six_distinct_surface_levels(keyring):
    """
    Measured off the mesh rather than clustered out of the height map, because
    the camera dot is 0.43 mm2 and disappears into the noise floor of any pixel
    clustering.
    """
    levels = surface_levels(keyring, axis="z")
    assert len(levels) == 6
    heights = [round(lv.height_mm, 3) for lv in levels]
    assert heights == [7.000, 6.600, 6.450, 6.150, 6.000, 5.700]


def test_acceptance_every_level_is_visible_in_the_height_map(keyring):
    levels = surface_levels(keyring, axis="z")
    hmap = height_map(keyring, nx=500, ny=500)
    assert all(levels_present_in(hmap, levels))


def test_acceptance_no_degenerate_faces(keyring_report):
    assert keyring_report.degenerate_faces == 0


def test_acceptance_reference_part_has_no_problems(keyring_report):
    assert keyring_report.problems == []


# -- mesh -------------------------------------------------------------------


def test_missing_file_raises_with_the_path(tmp_path):
    missing = tmp_path / "nope.stl"
    with pytest.raises(FileNotFoundError) as exc:
        check_mesh(missing)
    assert str(missing) in str(exc.value)


def test_open_mesh_is_reported_as_a_problem():
    """A single triangle is watertight in no sense at all."""
    m = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )
    r = report_for(m)
    assert not r.watertight
    assert any("watertight" in p for p in r.problems)


def test_two_bodies_are_counted():
    a = trimesh.creation.box(extents=(2, 2, 2))
    b = trimesh.creation.box(extents=(2, 2, 2))
    b.apply_translation((10, 0, 0))
    r = report_for(trimesh.util.concatenate([a, b]))
    assert r.body_count == 2


# -- features ---------------------------------------------------------------


def test_feature_below_the_nozzle_is_too_fine():
    r = check_features({"hair": 0.20}, nozzle_mm=0.40)
    assert r.checks[0].status == TOO_FINE
    assert not r.ok


def test_feature_just_above_the_nozzle_is_marginal():
    r = check_features({"bezel": 0.41}, nozzle_mm=0.40)
    assert r.checks[0].status == MARGINAL
    assert r.ok, "marginal still prints, so it is not a failure"


def test_feature_comfortably_above_the_nozzle_passes():
    assert check_features({"wall": 1.2}, nozzle_mm=0.40).checks[0].status == PASS


def test_exactly_at_the_threshold_is_marginal_not_too_fine():
    assert check_features({"edge": 0.40}, nozzle_mm=0.40).checks[0].status == MARGINAL


def test_features_are_sorted_smallest_first():
    r = check_features({"big": 3.0, "small": 0.3, "mid": 1.0}, nozzle_mm=0.4)
    assert [c.name for c in r.checks] == ["small", "mid", "big"]


def test_min_feature_multiple_raises_the_bar():
    r = check_features({"wall": 0.5}, nozzle_mm=0.40, min_feature_multiple=2.0)
    assert r.checks[0].threshold_mm == pytest.approx(0.8)
    assert r.checks[0].status == TOO_FINE


# -- probe ------------------------------------------------------------------


def test_surface_heights_reads_each_distinct_level(keyring):
    """
    One point on each of four different surfaces. This is the numeric backbone
    of geometry verification: it proves the recesses are the depths they are
    supposed to be without anyone squinting at a render.
    """
    points = [
        (-12.0, 20.0),   # body top face
        (0.0, 27.0),     # module pocket floor, i.e. the bezel step
        (0.0, 20.0),     # a raised UI card standing on the glass
        (-3.0, 10.0),    # the glass floor itself
    ]
    got = surface_heights(keyring, points)
    assert got == pytest.approx([7.00, 6.45, 6.15, 5.70], abs=1e-4)


def test_surface_heights_returns_nan_off_the_part(keyring):
    assert np.isnan(surface_heights(keyring, [(100.0, 100.0)])[0])


def test_surface_heights_and_height_map_agree(keyring):
    """Two entry points, one meaning. If they disagree, one of them is lying."""
    from bpcad.render.raster import Bounds
    from bpcad.verify.probe import _tris, grid_coords

    tu, tv, _ = _tris(keyring, "z")
    b = Bounds(float(tu.min()), float(tu.max()), float(tv.min()), float(tv.max()))
    nx = ny = 200
    hmap = height_map(keyring, nx=nx, ny=ny, bounds=b)
    us, vs = grid_coords(b, nx, ny)

    rng = np.random.default_rng(0)
    idx = [(int(rng.integers(0, ny)), int(rng.integers(0, nx))) for _ in range(300)]
    direct = np.array(surface_heights(keyring, [(us[i], vs[j]) for j, i in idx]))
    grid = np.array([hmap[j, i] for j, i in idx])

    assert (np.isfinite(direct) == np.isfinite(grid)).all()
    both = np.isfinite(direct)
    assert np.abs(direct[both] - grid[both]).max() < 1e-9


def test_ray_cast_uses_no_rtree():
    """
    trimesh.ray hard-depends on rtree, which is not installed. If this ever
    starts passing by accident it means probe grew a dependency it should not
    have.
    """
    import importlib.util

    assert importlib.util.find_spec("rtree") is None
    import bpcad.verify.probe as p

    assert "rtree" not in p.__dict__


def test_surface_heights_on_an_empty_point_list(keyring):
    assert surface_heights(keyring, []) == []


def test_levels_exclude_a_chamfer_ramp():
    """
    A chamfer is a ramp, not a level. Clustering height values cannot tell the
    two apart; a normal test can.
    """
    box = trimesh.creation.box(extents=(10, 10, 4))
    levels = surface_levels(box, axis="z")
    assert len(levels) == 1
    assert levels[0].height_mm == pytest.approx(2.0)


# -- overhang ---------------------------------------------------------------


def test_reference_keyring_needs_no_support(keyring):
    """
    The keyring's whole design premise: constant-depth extrusion printed flat,
    so every surface is horizontal or vertical. Zero overhang is the claim, and
    this is the check on it.
    """
    r = overhang_report(keyring, print_axis="z", max_deg=45.0)
    assert r.overhang_area_mm2 == 0.0
    assert not r.supports_needed
    assert r.problems == []


def test_a_real_overhang_is_detected():
    """A sphere has undersides at every angle up to 90 degrees."""
    s = trimesh.creation.icosphere(subdivisions=3, radius=5.0)
    r = overhang_report(s, print_axis="z", max_deg=45.0)
    assert r.supports_needed
    assert r.worst_overhang_deg > 80.0
    assert r.overhang_area_mm2 > 0.0


def test_bed_faces_are_not_flagged_as_overhangs():
    """A flat bottom points straight down but the bed is holding it up."""
    box = trimesh.creation.box(extents=(10, 10, 4))
    r = overhang_report(box, print_axis="z", max_deg=45.0)
    assert r.bed_area_mm2 == pytest.approx(100.0)
    assert r.overhang_area_mm2 == 0.0


def test_print_in_place_gap_is_recognised_as_bridged():
    """
    Two plates 0.30 mm apart: the top one is a 90-degree underside, and it
    prints fine because the layer above closes a gap that small. This is the
    louvre vent's whole mechanism and a face normal cannot see it.
    """
    lower = trimesh.creation.box(extents=(10, 10, 2))          # z -1 .. 1
    upper = trimesh.creation.box(extents=(10, 10, 2))
    upper.apply_translation((0, 0, 2.3))                       # z 1.3 .. 3.3
    part = trimesh.util.concatenate([lower, upper])

    r = overhang_report(part, print_axis="z", max_deg=45.0, max_bridge_gap_mm=0.50)
    assert r.overhang_area_mm2 == pytest.approx(100.0)   # the underside is real
    assert r.bridged_area_mm2 == pytest.approx(100.0)    # ...and it is bridged
    assert r.unsupported_area_mm2 == 0.0
    assert not r.supports_needed
    assert r.max_drop_mm == pytest.approx(0.30, abs=1e-6)


def test_a_long_drop_is_not_treated_as_bridged():
    """The same two plates, moved far apart. Now it is a real fall."""
    lower = trimesh.creation.box(extents=(10, 10, 2))
    upper = trimesh.creation.box(extents=(10, 10, 2))
    upper.apply_translation((0, 0, 12.0))
    part = trimesh.util.concatenate([lower, upper])

    r = overhang_report(part, print_axis="z", max_deg=45.0, max_bridge_gap_mm=0.50)
    assert r.bridged_area_mm2 == 0.0
    assert r.unsupported_area_mm2 == pytest.approx(100.0)
    assert r.supports_needed
    assert r.max_drop_mm == pytest.approx(10.0, abs=1e-6)


def test_an_overhang_over_nothing_falls_to_the_bed():
    """With nothing underneath, the drop is the full height above the bed."""
    post = trimesh.creation.box(extents=(2, 2, 10))
    arm = trimesh.creation.box(extents=(10, 2, 2))
    arm.apply_translation((6, 0, 4))            # cantilever off the side, mid-air
    part = trimesh.util.concatenate([post, arm])

    r = overhang_report(part, print_axis="z", max_deg=45.0)
    assert r.supports_needed
    assert r.max_drop_mm > 5.0


def test_the_vent_print_in_place_gaps_are_found():
    """
    The reference part this whole feature exists for. Its 0.30 mm shoulder gaps
    must come back as bridged, not as overhangs needing support.
    """
    vent = load_mesh(Path(__file__).resolve().parent.parent / "reference" / "vent_louvre.stl")
    r = overhang_report(vent, print_axis="z", max_deg=45.0, max_bridge_gap_mm=0.50)
    assert r.bridged_area_mm2 > 250.0
    assert r.bridged_area_mm2 + r.unsupported_area_mm2 == pytest.approx(r.overhang_area_mm2)


def test_bridge_gap_of_zero_bridges_nothing():
    lower = trimesh.creation.box(extents=(10, 10, 2))
    upper = trimesh.creation.box(extents=(10, 10, 2))
    upper.apply_translation((0, 0, 2.3))
    part = trimesh.util.concatenate([lower, upper])
    r = overhang_report(part, max_bridge_gap_mm=0.0)
    assert r.bridged_area_mm2 == 0.0


def test_surface_below_finds_nothing_under_the_bed(keyring):
    from bpcad.verify.probe import surface_below

    assert np.isnan(surface_below(keyring, [(-12.0, 20.0)], [0.0])[0])


def test_surface_below_ignores_the_face_asking(keyring):
    """A face must not find itself as the thing it is standing on."""
    from bpcad.verify.probe import surface_below

    assert surface_below(keyring, [(-12.0, 20.0)], [7.0])[0] == pytest.approx(0.0)


def test_surface_below_rejects_mismatched_lengths(keyring):
    from bpcad.verify.probe import surface_below

    with pytest.raises(ValueError):
        surface_below(keyring, [(0.0, 0.0), (1.0, 1.0)], [7.0])


def test_overhang_rejects_an_unknown_axis(keyring):
    with pytest.raises(ValueError):
        overhang_report(keyring, print_axis="w")


# -- regression -------------------------------------------------------------


def test_first_run_writes_a_baseline(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    result = check_regression(keyring_report, path)
    assert result.status == "new"
    assert path.is_file()
    assert result.ok


def test_second_run_matches(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    check_regression(keyring_report, path)
    assert check_regression(keyring_report, path).status == "match"


def test_a_changed_volume_is_caught(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    check_regression(keyring_report, path)

    changed = report_for(load_mesh(REFERENCE_STL))
    changed.volume_cm3 += 0.5
    result = check_regression(changed, path)
    assert result.status == "changed"
    assert not result.ok
    assert any("volume" in d for d in result.differences)


def test_update_baseline_accepts_the_change(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    check_regression(keyring_report, path)

    changed = report_for(load_mesh(REFERENCE_STL))
    changed.volume_cm3 += 0.5
    assert check_regression(changed, path, update=True).status == "new"
    assert check_regression(changed, path).status == "match"


def test_noise_below_tolerance_does_not_trip_it(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    check_regression(keyring_report, path)

    noisy = report_for(load_mesh(REFERENCE_STL))
    noisy.volume_cm3 += 1e-6           # a rounding wobble, not a change
    assert check_regression(noisy, path).status == "match"


def test_baseline_round_trips(keyring_report, tmp_path):
    path = tmp_path / "regression.json"
    sig = signature_of(keyring_report)
    save_baseline(path, sig)
    assert load_baseline(path) == sig


# -- does the part resemble what was asked for? -----------------------------
#
# Everything else in this file answers "can this be made?". A 573 cm3 solid
# slab answers that perfectly well while not being the birdhouse that was
# requested, and nothing was looking.


def test_stated_dimensions_are_read_out_of_a_request():
    from bpcad.verify.intent import stated_dimensions

    dims = stated_dimensions(
        "a birdhouse, 120 mm wide, 140 mm tall, 100 mm deep, "
        "with a 32 mm entrance hole and a sloped roof"
    )
    assert dims == [140.0, 120.0, 100.0]
    assert 32.0 not in dims, "an entrance hole is not an envelope dimension"


def test_inner_features_are_not_matched_against_the_envelope():
    from bpcad.verify.intent import stated_dimensions

    for phrase in ("a 32 mm entrance hole", "5 mm wall thickness",
                   "a 12 mm bore", "0.3 mm clearance"):
        assert stated_dimensions("a box, " + phrase) == []


def test_the_triple_form_is_understood():
    from bpcad.verify.intent import stated_dimensions

    assert stated_dimensions("a box 120 x 140 x 100") == [140.0, 120.0, 100.0]


def test_a_dropped_dimension_is_caught():
    """The exact case: 100 mm deep was asked for and 40 mm was built."""
    from bpcad.verify.intent import check_intent

    r = check_intent(
        "a birdhouse, 120 mm wide, 140 mm tall, 100 mm deep",
        (134.4, 174.3, 40.0),
    )
    assert not r.ok
    assert 100.0 in r.missing
    assert "not the part that was asked for" in r.problems[0]


def test_a_part_that_matches_stays_quiet():
    """
    A check that fires on good parts gets switched off. A flange or a chamfer
    legitimately adds a few mm and must not trip it.
    """
    from bpcad.verify.intent import check_intent

    assert check_intent("a louvre vent 76 mm wide and 30 mm tall",
                        (86.0, 31.0, 35.0)).ok
    assert check_intent("a keyring 30 mm wide", (34.6, 44.3, 7.0)).ok


def test_a_request_with_no_dimensions_is_not_second_guessed():
    from bpcad.verify.intent import check_intent

    r = check_intent("a small birdhouse", (100.0, 100.0, 100.0))
    assert r.ok and not r.checked


def test_the_intent_problem_reaches_the_report():
    from bpcad.verify.intent import check_intent
    from bpcad.verify.mesh import MeshReport
    from bpcad.verify.overhang import OverhangReport
    from bpcad.verify.report import VerifyReport

    report = VerifyReport(
        path="x", nozzle_mm=0.4, print_axis="z",
        mesh=MeshReport("x", True, True, True, 1, 10, 10, 1.0, (1, 1, 1), (0, 0, 0), 0),
        overhang=OverhangReport(
            print_axis="z", max_deg=45.0, max_bridge_gap_mm=0.5,
            worst_overhang_deg=0.0, overhang_area_mm2=0.0, bridged_area_mm2=0.0,
            unsupported_area_mm2=0.0, max_drop_mm=0.0, downward_area_mm2=0.0,
            total_area_mm2=1.0, bed_area_mm2=1.0, overhang_face_count=0,
            unsupported_face_count=0,
        ),
        intent=check_intent("a box 100 mm deep", (10.0, 10.0, 10.0)),
    )
    assert report.warnings
    assert "asked for" in report.warnings[0]


def test_a_suspiciously_solid_part_is_flagged():
    """
    Asked for a birdhouse, the DSL path produced a 120 x 100 x 145 mm block
    that was 96% solid - correct on the outside, 2.1 kg of filament, and
    useless as a birdhouse because nothing was hollow. Nothing was looking.
    """
    from bpcad.verify.mesh import report_for

    block = trimesh.creation.box(extents=(120, 100, 145))
    r = report_for(block)
    assert r.solidity > 0.99
    assert r.warnings
    assert "hollow" in r.warnings[0]
    assert r.problems == [], "a solid block is legal, just worth saying"


def test_the_real_parts_are_not_flagged_as_bulk(keyring):
    """A check that fires on good parts gets switched off."""
    from bpcad.verify.mesh import report_for

    assert report_for(keyring).warnings == []


def test_a_small_solid_part_is_left_alone():
    """A spacer or a wedge is legitimately solid and nobody needs telling."""
    from bpcad.verify.mesh import report_for

    assert report_for(trimesh.creation.box(extents=(20, 20, 20))).warnings == []


def test_a_hollow_part_of_the_same_size_is_left_alone():
    from bpcad.verify.mesh import report_for

    outer = trimesh.creation.box(extents=(120, 100, 145))
    inner = trimesh.creation.box(extents=(110, 90, 135))
    inner.invert()
    shell = trimesh.util.concatenate([outer, inner])
    r = report_for(shell)
    assert r.solidity < 0.5
    assert r.warnings == []


def test_axis_labels_are_read_from_the_request():
    """
    "120 mm wide, 140 mm tall, 100 mm deep" names the axes. Ignoring that let a
    birdhouse come back with the right three numbers on the wrong three axes -
    a squat wide box instead of a tall one - and pass, because every number
    appeared somewhere.
    """
    from bpcad.verify.intent import labelled_dimensions

    d = labelled_dimensions(
        "a birdhouse, 120 mm wide, 140 mm tall, 100 mm deep, with a 32 mm entrance hole"
    )
    assert d == {0: 120.0, 1: 100.0, 2: 140.0}


def test_the_label_search_stops_at_the_next_number():
    """
    "140 mm tall, 100 mm deep" must not read "deep" as the label for 140. The
    first version searched 22 characters and did exactly that.
    """
    from bpcad.verify.intent import labelled_dimensions

    assert labelled_dimensions("80 mm tall, 60 mm deep") == {2: 80.0, 1: 60.0}


def test_the_first_label_by_position_wins_not_by_dictionary_order():
    from bpcad.verify.intent import labelled_dimensions

    assert labelled_dimensions("a box 90 mm tall")[2] == 90.0
    assert labelled_dimensions("a box 90 mm wide")[0] == 90.0


def test_transposed_dimensions_are_caught():
    from bpcad.verify.intent import check_intent

    req = "a birdhouse, 120 mm wide, 140 mm tall, 100 mm deep"
    assert not check_intent(req, (140.0, 120.0, 100.0)).ok
    assert check_intent(req, (120.0, 100.0, 140.0)).ok


def test_unlabelled_dimensions_are_not_second_guessed():
    """
    A request that does not say which way round it means must not be told it
    got the axes wrong.
    """
    from bpcad.verify.intent import check_intent

    assert check_intent("a box 120 x 100 x 140", (140.0, 120.0, 100.0)).ok


# ---------------------------------------------------------------------------
# The intent guard was reading almost nothing, and nobody could tell, because
# a guard that extracts no dimensions reports no problems and looks content.
# ---------------------------------------------------------------------------

def test_the_word_by_is_a_dimension_separator():
    """
    "80 by 40 by 6 mm" yielded NOTHING. _TRIPLE matched only x and the times
    sign, so the commonest way a person writes three dimensions was invisible,
    and check_intent - the guard against being handed a slab instead of a
    birdhouse - had nothing to check for any request written that way. The
    drilled-plate prompt this project has been tested against all along is
    exactly that form.
    """
    from bpcad.verify.intent import stated_dimensions

    assert stated_dimensions("a flat plate 80 by 40 by 6 mm") == [80.0, 40.0, 6.0]
    assert stated_dimensions("a box 120 by 140 by 100") == [140.0, 120.0, 100.0]
    # The symbol still works, and mixing them is still read.
    assert stated_dimensions("a box 120 x 140 by 100") == [140.0, 120.0, 100.0]


def test_an_inner_feature_does_not_poison_the_dimension_beside_it():
    """
    The exclusion window was a flat 26 characters either side, which reaches
    into the NEXT number and takes its qualifier: in "40 mm wide and 5 mm
    thick" the word "thick" belongs to the 5, and the 40 was thrown away with
    it. One inner-feature word silenced every dimension near it.
    """
    from bpcad.verify.intent import stated_dimensions

    assert stated_dimensions("a hinge 40 mm wide and 5 mm thick") == [40.0]
    assert stated_dimensions("a plate 80 mm long with a 6 mm bore") == [80.0]


def test_a_number_naming_something_the_part_receives_is_not_the_envelope():
    """
    A rod, a cable, a neck: if it goes INTO or THROUGH the part, its size is a
    bore. Three corpus entries whose specs are provably correct were reported
    as the wrong size for want of these words.
    """
    from bpcad.verify.intent import stated_dimensions

    assert stated_dimensions("a clamp that holds an 8 mm rod, 40 mm wide") == [40.0]
    assert stated_dimensions("a clip that holds two 5 mm cables") == []
    assert stated_dimensions("a funnel with a 60 mm mouth and a 20 mm neck") == [60.0]


def test_deep_is_allowed_to_mean_vertical():
    """
    A shelf 70 mm deep is 70 front to back. A bowl 70 mm deep is 70 top to
    bottom. Both are ordinary English, AXIS_WORDS has to pick one, and a
    correct 180 x 180 x 70 bowl was reported as having its dimensions on the
    wrong axes.
    """
    from bpcad.verify.intent import check_intent

    bowl = check_intent("a round bowl 180 mm across and 70 mm deep",
                        (180.0, 180.0, 70.0))
    assert bowl.ok, bowl.problems

    # A shelf where "deep" really is front to back still checks out.
    shelf = check_intent("a shelf 200 mm wide and 120 mm deep",
                         (200.0, 120.0, 18.0))
    assert shelf.ok, shelf.problems

    # And a part that genuinely has the numbers on the wrong axes still fails.
    wrong = check_intent("a box 120 mm wide and 40 mm tall",
                         (40.0, 40.0, 120.0))
    assert not wrong.ok


def test_every_corpus_spec_satisfies_its_own_request():
    """
    THE ORACLE FOR THIS MODULE. A corpus entry's spec is correct by
    construction - it meets every dimensional assertion in its `expect` block,
    which is what the fit-rate gate measures. So an intent problem on a corpus
    entry cannot be the part's fault; it is this module misreading the request.

    That makes the corpus a two-sided test: it catches an extractor that reads
    too little (nothing to check, silent pass) only through the count below,
    and an extractor that reads too much (false alarms on good parts) through
    the assertion.
    """
    import yaml

    from bpcad.build.compile import compile_spec
    from bpcad.spec.schema import PartSpec
    from bpcad.verify.intent import check_intent, stated_dimensions

    root = Path(__file__).resolve().parent.parent
    entries = yaml.safe_load((root / "eval" / "corpus.yaml").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries

    checkable = 0
    for entry in entries:
        block = entry.get("spec")
        if not block:
            continue
        request = entry.get("request", "")
        if stated_dimensions(request):
            checkable += 1
        spec = PartSpec(name=entry["id"], material="petg", nozzle_mm=0.4,
                        layer_mm=0.2, **block)
        result = compile_spec(spec)
        bb = result.solid.val().BoundingBox()
        envelope = result.nominal_mm or (bb.xlen, bb.ylen, bb.zlen)
        report = check_intent(request, envelope)
        assert report.ok, "%s: %s" % (entry["id"], report.problems)

    # If this drops, the extractor has gone quiet again and the assertion above
    # stops meaning anything. It was ZERO for the "by" form before this.
    assert checkable >= 15, "only %d requests carry checkable dimensions" % checkable


# ---------------------------------------------------------------------------
# A part the request called round has to BE round.
# ---------------------------------------------------------------------------

def _meshed(ops, name="r"):
    """Ops -> exported mesh vertices, which is what roundness is measured on."""
    import tempfile

    import trimesh

    from bpcad.build.compile import compile_spec, export_solid
    from bpcad.spec.schema import PartSpec

    result = compile_spec(PartSpec(name=name, level=2, material="petg",
                                   nozzle_mm=0.4, layer_mm=0.2, ops=ops))
    out = Path(tempfile.mkdtemp()) / ("%s.stl" % name)
    export_solid(result.print_solid, out, 0.005, 0.05)
    return np.asarray(trimesh.load(out).vertices)


def test_a_circle_and_a_square_are_told_apart_by_their_plan_view():
    """
    pi/4 against 1. This is the whole mechanism, and it is worth asserting on
    its own so the threshold below has something to stand on.
    """
    from bpcad.verify.intent import footprint_fill

    disc = _meshed([{"op": "disc", "diameter_mm": 40, "height_mm": 10}], "disc")
    box = _meshed([{"op": "rounded_prism", "width_mm": 40, "depth_mm": 40,
                    "height_mm": 10}], "box")
    assert footprint_fill(disc) == pytest.approx(0.785, abs=0.01)
    assert footprint_fill(box) == pytest.approx(1.0, abs=0.01)


def test_a_square_knob_is_refused_for_a_round_request():
    """
    The real reply. Asked for "a round knob 40 mm across with a 6 mm hole for
    a shaft", the model emitted `rounded_prism 40 x 40 x 20, corner_r 5` - a
    square knob with the corners taken off - and every check passed, because
    40 across is 40 across whichever way you square it. It is the
    pot/planter mistake from enclosure.py one level down, where there is no
    template routing to catch a shape word.
    """
    from bpcad.verify.intent import check_roundness

    square = _meshed([
        {"op": "rounded_prism", "width_mm": 40, "depth_mm": 40, "height_mm": 20,
         "corner_r_mm": 5},
        {"op": "disc", "diameter_mm": 6, "height_mm": 24, "z_mm": -2, "mode": "cut"},
    ], "sq")
    problem = check_roundness("a round knob 40 mm across with a 6 mm hole", square)
    assert problem and "not" in problem
    assert "disc" in problem, "the critique has to say what to use instead"


def test_a_round_part_passes_and_a_request_with_no_round_word_is_not_judged():
    from bpcad.verify.intent import check_roundness

    round_knob = _meshed([{"op": "disc", "diameter_mm": 40, "height_mm": 20}], "rk")
    assert check_roundness("a round knob 40 mm across", round_knob) is None

    plate = _meshed([{"op": "rounded_prism", "width_mm": 80, "depth_mm": 40,
                      "height_mm": 6}], "pl")
    assert check_roundness("a flat plate 80 by 40 by 6 mm", plate) is None


def test_a_thing_the_part_merely_holds_does_not_make_it_round():
    """
    "a clamp that holds an 8 mm ROD" is not a round part, and the corpus entry
    for it fills 99% of its bounding box. Words naming what the part receives
    are deliberately absent from ROUND_WORDS - _INNER already carries them.
    """
    from bpcad.verify.intent import round_words_in

    assert round_words_in("a clamp that holds an 8 mm rod against a surface") == []
    assert round_words_in("a clip that holds two 5 mm cables") == []
    # And a keyring is not a ring, on word boundaries.
    assert round_words_in("a keyring tag 40 by 20 by 3 mm") == []


def test_no_corpus_entry_is_called_the_wrong_shape():
    """
    The same oracle the dimension checks use: a corpus spec is correct by
    construction, so anything this flags is the check being wrong. Measured
    over the whole corpus, every round entry fills 0.785 and the roundest
    entry that is not round is the birdhouse at 0.930 - the threshold sits
    between them with room on both sides.
    """
    import tempfile

    import trimesh
    import yaml

    from bpcad.build.compile import compile_spec, export_solid
    from bpcad.spec.schema import PartSpec
    from bpcad.verify.intent import check_roundness

    root = Path(__file__).resolve().parent.parent
    entries = yaml.safe_load((root / "eval" / "corpus.yaml").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries
    tmp = Path(tempfile.mkdtemp())

    for entry in entries:
        block = entry.get("spec")
        if not block:
            continue
        spec = PartSpec(name=entry["id"], material="petg", nozzle_mm=0.4,
                        layer_mm=0.2, **block)
        result = compile_spec(spec)
        out = tmp / ("%s.stl" % entry["id"])
        export_solid(result.print_solid, out, 0.02, 0.2)
        vertices = np.asarray(trimesh.load(out).vertices)
        problem = check_roundness(entry.get("request", ""), vertices)
        assert problem is None, "%s: %s" % (entry["id"], problem)


# ---------------------------------------------------------------------------
# As many holes as the request asked for.
# ---------------------------------------------------------------------------

def _solid(ops):
    """A level-2 ops list, compiled to a solid."""
    from bpcad.build.compile import compile_spec
    from bpcad.spec.schema import PartSpec

    return compile_spec(PartSpec(name="t", level=2, material="petg",
                                 nozzle_mm=0.4, layer_mm=0.2, ops=ops)).solid


def _built(name, block):
    """Any corpus spec block - level 1 or 2 - compiled to a solid."""
    from bpcad.build.compile import compile_spec
    from bpcad.spec.schema import PartSpec

    return compile_spec(PartSpec(name=name, material="petg", nozzle_mm=0.4,
                                 layer_mm=0.2, **block)).solid


def test_hole_counts_are_read_out_of_a_request():
    from bpcad.verify.intent import stated_holes

    assert stated_holes("a plate with two 5 mm holes 60 mm apart") == [(2, 5.0)]
    assert stated_holes("four 4 mm holes 80 mm apart") == [(4, 4.0)]
    assert stated_holes("two countersunk screw holes") == [(2, None)]
    assert stated_holes("a keyring tag with a 5 mm hole") == [(1, 5.0)]
    # Cables are not holes, however many of them there are.
    assert stated_holes("a clip that holds two 5 mm cables") == []


def test_a_rounded_corner_is_not_a_hole():
    """
    A bore wraps the full circle; a rounded corner covers a quarter of it, and
    both are cylindrical faces of some radius. Without the arc filter a plate
    with corner_r_mm 2 reads as having four 4 mm holes in its corners - which
    is how a part with NO holes satisfied a request for two.
    """
    from bpcad.verify.assertions import cylindrical_faces

    faces = cylindrical_faces(_solid([
        {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6,
         "corner_r_mm": 2},
        {"op": "disc", "diameter_mm": 5, "height_mm": 10, "x_mm": -30,
         "z_mm": -2, "mode": "cut"},
    ]))
    corners = [f for f in faces if f["arc_deg"] < 179]
    bores = [f for f in faces if f["arc_deg"] >= 179]
    assert len(corners) == 4 and len(bores) == 1


def test_a_dimple_does_not_pass_for_two_countersunk_holes():
    """
    The real reply to "a rectangular plate 80 by 40 by 6 mm with two
    countersunk screw holes": ONE cone, pointed, 3 mm deep, nowhere near
    through. A conical dent, no bore, and one of the two asked for.
    """
    from bpcad.verify.intent import check_hole_counts

    solid = _solid([
        {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6,
         "corner_r_mm": 2},
        {"op": "cone", "bottom_d_mm": 10, "top_d_mm": 0, "height_mm": 3,
         "z_mm": -2, "mode": "cut"},
    ])
    problem = check_hole_counts(
        "a plate 80 by 40 by 6 mm with two countersunk screw holes", solid)
    assert problem and "two ops" in problem.lower()


def test_a_real_countersunk_pair_passes():
    from bpcad.verify.intent import check_hole_counts

    solid = _solid([
        {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6},
        {"op": "pattern_linear", "count": 2, "dx_mm": 50,
         "step": {"op": "disc", "diameter_mm": 4, "height_mm": 10, "x_mm": -25,
                  "z_mm": -2, "mode": "cut"}},
        {"op": "pattern_linear", "count": 2, "dx_mm": 50,
         "step": {"op": "cone", "bottom_d_mm": 4, "top_d_mm": 8,
                  "height_mm": 2.2, "x_mm": -25, "z_mm": 3.8, "mode": "cut"}},
    ])
    assert check_hole_counts(
        "a plate 80 by 40 by 6 mm with two countersunk screw holes", solid) is None


def test_fewer_holes_than_asked_is_the_only_complaint():
    """
    One-sided on purpose. A part may carry holes the request never mentioned -
    a drain, a vent, a fixing - and complaining about those is noise.
    """
    from bpcad.verify.intent import check_hole_counts

    solid = _solid([
        {"op": "rounded_prism", "width_mm": 80, "depth_mm": 40, "height_mm": 6},
        {"op": "pattern_linear", "count": 4, "dx_mm": 18,
         "step": {"op": "disc", "diameter_mm": 5, "height_mm": 10, "x_mm": -27,
                  "z_mm": -2, "mode": "cut"}},
    ])
    assert check_hole_counts("a plate with two 5 mm holes", solid) is None


def test_no_corpus_entry_is_told_it_has_too_few_holes():
    """The same oracle: a corpus spec is right, so a flag here is this check."""
    import yaml

    from bpcad.verify.intent import check_hole_counts, stated_holes

    root = Path(__file__).resolve().parent.parent
    entries = yaml.safe_load((root / "eval" / "corpus.yaml").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries

    checked = 0
    for entry in entries:
        block = entry.get("spec")
        request = entry.get("request", "")
        if not block or not stated_holes(request):
            continue
        checked += 1
        problem = check_hole_counts(request, _built(entry["id"], block))
        assert problem is None, "%s: %s" % (entry["id"], problem)
    assert checked >= 8, "only %d requests state a hole count" % checked


def test_a_solid_block_is_not_a_plant_pot():
    """
    The real reply to "a plant pot 100 mm across with drainage holes in the
    bottom": `rounded_prism 100 x 100 x 20` and one `disc` cut. A solid square
    slab with a hole in it - watertight, one sound body, every check green,
    and a coaster. Nothing asked whether a container was hollow.
    """
    import tempfile

    import trimesh

    from bpcad.build.compile import export_solid
    from bpcad.verify.intent import check_hollowness

    def mesh_of(ops, name):
        out = Path(tempfile.mkdtemp()) / ("%s.stl" % name)
        export_solid(_solid(ops), out, 0.02, 0.2)
        return trimesh.load(out)

    slab = mesh_of([
        {"op": "rounded_prism", "width_mm": 100, "depth_mm": 100,
         "height_mm": 20, "corner_r_mm": 5},
        {"op": "disc", "diameter_mm": 6, "height_mm": 8, "z_mm": -2, "mode": "cut"},
    ], "slab")
    problem = check_hollowness("a plant pot 100 mm across with drainage holes",
                               slab)
    assert problem and "hollow" in problem

    real = mesh_of([
        {"op": "disc", "diameter_mm": 100, "height_mm": 90},
        {"op": "hollow", "wall_mm": 2.4, "opening": "top_face", "floor_mm": 3},
    ], "pot")
    assert check_hollowness("a plant pot 100 mm across", real) is None

    # A request with no container word is never judged, however solid it is.
    plate = mesh_of([{"op": "rounded_prism", "width_mm": 80, "depth_mm": 40,
                      "height_mm": 6}], "plate")
    assert check_hollowness("a flat plate 80 by 40 by 6 mm", plate) is None


def test_no_corpus_container_is_called_solid():
    """
    The oracle again. Measured over the corpus, every container fills 0.20 of
    its convex hull or less - bowl 0.081, plant pot 0.135, pen pot 0.148, tray
    0.192, enclosure 0.200 - and the nearest thing that is not a container is
    the funnel at 0.244. The limit sits at 0.50, which is far enough away that
    this can only fire on something plainly not hollow.
    """
    import tempfile

    import trimesh
    import yaml

    from bpcad.build.compile import export_solid
    from bpcad.verify.intent import check_hollowness

    root = Path(__file__).resolve().parent.parent
    entries = yaml.safe_load((root / "eval" / "corpus.yaml").read_text())
    entries = entries["entries"] if isinstance(entries, dict) else entries
    tmp = Path(tempfile.mkdtemp())

    for entry in entries:
        block = entry.get("spec")
        if not block:
            continue
        out = tmp / ("%s.stl" % entry["id"])
        export_solid(_built(entry["id"], block), out, 0.02, 0.2)
        problem = check_hollowness(entry.get("request", ""), trimesh.load(out))
        assert problem is None, "%s: %s" % (entry["id"], problem)
