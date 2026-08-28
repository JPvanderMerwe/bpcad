"""
Phase 2: measurement.

The acceptance test is re-deriving the reference session's pixel measurements
from the reference render. Every number the keyring and the six-part assembly
are built from came out of that image, so if this drifts, every part drifts.

WHERE THE MEASUREMENTS LAND, AND WHY THEY ARE NOT ALL EXACT
----------------------------------------------------------
The render's edges are antialiased over about one pixel, so any integer edge is
a convention rather than a fact. Two of the reference numbers come back one
pixel different and the tolerances below say so explicitly rather than being
widened until everything passes. One pixel at the keyring's 0.0529 mm/px is
0.05 mm - an eighth of a nozzle width.
"""

from pathlib import Path

import numpy as np
import pytest

from bpcad.measure.contour import trace
from bpcad.measure.fit import arc_through, circle
from bpcad.measure.profile import edges_subpixel, profile, spans, spans_subpixel, transitions
from bpcad.measure.segment import (
    Box,
    as_array,
    auto_threshold,
    bbox,
    by_colour,
    by_luminance,
    background_cut,
    by_saturation,
    coverage,
    edge_profile,
    fill_holes,
    largest_component,
    luminance,
    runs,
    saturation,
)

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "reference" / "loop_render_650x855.png"
LOGO_JSON = ROOT / "reference" / "loop_logo.json"

# The cut is derived from the image border, not chosen. See
# segment.background_cut - a cut picked by eye at 235 lands inside the
# transparency checkerboard's darker tile (luminance 234) and reads seven
# columns of background as part of the device.
BACKGROUND_CUT = None      # filled in by the `cut` fixture


@pytest.fixture(scope="module")
def render():
    return as_array(RENDER)


@pytest.fixture(scope="module", autouse=True)
def cut(render):
    """Derive the foreground cut from the image once, and share it."""
    global BACKGROUND_CUT
    BACKGROUND_CUT = background_cut(render)
    assert BACKGROUND_CUT == pytest.approx(233.5), (
        "the reference render's darkest border pixel is luminance 234"
    )
    return BACKGROUND_CUT


@pytest.fixture(scope="module")
def derived(render):
    """
    The reference derivation, once, in the order the measurements depend on
    each other. Widths are read off scanlines rather than global column
    coverage, which is what the reference itself did - it quotes specific rows.
    """
    a = render
    fg = by_luminance(a, 0, BACKGROUND_CUT)

    body_rows = runs(fg, "row", 0.5)
    top, bot = body_rows[0]

    band = np.zeros_like(fg)
    band[top : bot + 1] = True
    neutral = by_saturation(a, 0, 15) & fg
    trim = runs(neutral & band, "row", 0.55)

    notrim = band.copy()
    for s, e in trim:
        notrim[s : e + 1] = False
    module = bbox(largest_component(neutral & notrim))

    return {
        "fg": fg,
        "neutral": neutral,
        "body_rows": (top, bot),
        "trim": trim,
        "module": module,
        "module_mask": largest_component(neutral & notrim),
    }


# -- acceptance: the body ----------------------------------------------------


def test_body_width_is_exactly_the_reference(render):
    """567 px, measured across a solid trim row. Reference L43 R609."""
    sp = spans(render, 288, BACKGROUND_CUT)
    left, right = sp[0][0], sp[-1][1]
    assert (left, right) == (43, 609)
    assert right - left + 1 == 567


def test_body_top_matches_the_reference(derived):
    assert derived["body_rows"][0] == 283


def test_body_bottom_is_within_one_pixel(derived):
    """
    Reference 835, measured 836. The bottom trim cap tapers, so rows 834, 835
    and 836 each cover less of the width than the last and the final row is
    part-covered. Which integer you call the edge is a convention. Not widened
    to hide it: the assertion is that it is one pixel, not that it is exact.
    """
    assert derived["body_rows"][1] in (835, 836)
    assert abs(derived["body_rows"][1] - 835) <= 1


def test_trim_bands_are_about_ten_rows_deep(derived):
    """
    Reference (284, 293) and (825, 834), ten rows each. Measured one row deeper
    at each outer edge, which is the antialiased boundary again - the partly
    covered row is neutral grey too, so it reads as trim.
    """
    trim = derived["trim"]
    assert len(trim) == 2
    assert abs(trim[0][0] - 284) <= 1 and trim[0][1] == 293
    assert trim[1][0] == 825 and abs(trim[1][1] - 834) <= 2
    for s_, e_ in trim:
        assert 10 <= (e_ - s_ + 1) <= 12


def test_waist_is_narrower_than_the_trim_caps(render):
    """
    The caps really are wider than the fabric waist, which is why the keyring
    keeps the width step. Reference waist L52 R596 against body L43 R609.

    The right edge is exact once the cut comes from the image. With a
    hand-picked 235 it read 602, because the checkerboard's darker tile is 234.
    """
    waist = spans(render, 780, BACKGROUND_CUT)
    left, right = waist[0][0], waist[-1][1]
    assert right == 596
    assert abs(left - 52) <= 1
    assert left > 43 and right < 609


# -- acceptance: the display module ------------------------------------------


def test_module_width_is_exactly_the_reference(derived):
    """227 px. Reference L216 R442."""
    m = derived["module"]
    assert (m.left, m.right) == (216, 442)
    assert m.width == 227


def test_module_height_is_within_one_pixel(derived):
    """Reference T294 B729 is 436 px; measured 435 on an antialiased edge."""
    m = derived["module"]
    assert m.top == 294
    assert abs(m.height - 436) <= 1


def test_module_corner_radius(derived):
    """
    Reference MODULE_CORNER_R_PX = 55, fitted to the bottom corner profile.
    Measured 53.9 with an rms residual of 0.34 px - within 2%, and the residual
    is what says the corner really is a circular arc rather than a spline.
    """
    mask = derived["module_mask"]
    m = derived["module"]
    left = edge_profile(mask, "left")
    ys = np.arange(m.bottom - 55, m.bottom + 1)
    pts = [(left[y], y) for y in ys if np.isfinite(left[y])]
    f = circle(pts)
    assert 52.0 <= f.r <= 57.0
    assert f.rms_residual < 0.5


# -- acceptance: the handle -------------------------------------------------


def test_handle_rod_diameter_at_the_apex(render):
    """Reference HANDLE_ROD_D_PX = 17, measured at the arc apex."""
    fg = by_luminance(render, 0, BACKGROUND_CUT)
    rod_top = int(np.flatnonzero(fg[:283].any(axis=1)).min())
    apex_col = int(np.mean(np.flatnonzero(fg[rod_top])))
    sp = spans_subpixel(render, apex_col, BACKGROUND_CUT, axis="col")
    assert abs((sp[0][1] - sp[0][0]) - 17.0) < 1.0


def test_handle_apex_centreline_row(render):
    """Reference HANDLE_APEX_ROW = 20, the centreline of the apex section."""
    fg = by_luminance(render, 0, BACKGROUND_CUT)
    rod_top = int(np.flatnonzero(fg[:283].any(axis=1)).min())
    apex_col = int(np.mean(np.flatnonzero(fg[rod_top])))
    sp = spans_subpixel(render, apex_col, BACKGROUND_CUT, axis="col")
    assert abs((sp[0][0] + sp[0][1]) / 2.0 - 20.0) < 0.5


def test_pivot_row_is_exactly_the_reference(render):
    """
    Reference PIVOT_ROW = 337, found from the pivot bosses - the widest warm
    protrusion at each side.
    """
    a = render.astype(int)
    warm = ((a[:, :, 0] - a[:, :, 2]) > 40) & by_luminance(a, 0, BACKGROUND_CUT)
    centres = []
    for from_left in (True, False):
        widths = {}
        for y in range(283, 430):
            idx = np.flatnonzero(warm[y])
            if not idx.size:
                continue
            s = set(idx.tolist())
            if from_left:
                a0 = int(idx[0]); b0 = a0
                while b0 + 1 in s:
                    b0 += 1
            else:
                b0 = int(idx[-1]); a0 = b0
                while a0 - 1 in s:
                    a0 -= 1
            widths[y] = b0 - a0 + 1
        peak = max(widths.values())
        wide = [y for y, w in widths.items() if w >= 0.95 * peak]
        centres.append((min(wide) + max(wide)) / 2.0)
    assert abs(sum(centres) / 2.0 - 337.0) < 1.0


def test_handle_arc_radius_from_three_points():
    """
    The reference's own construction: two pivot centres and an apex.

    Its numbers give R = (285.5^2 + 317^2) / (2 * 317) = 287.065 px, which is
    the 287.07 quoted. arc_through must reproduce that exactly.
    """
    f = arc_through((-285.5, 0.0), (285.5, 0.0), (0.0, 317.0))
    assert f.r == pytest.approx(287.065, abs=0.01)
    assert f.residual < 1e-9


def test_three_point_residual_is_not_evidence_of_anything():
    """
    Three points always determine a circle exactly, so this residual is
    arithmetic closure and nothing more. It is asserted here so nobody later
    reads a tiny number off arc_through and calls it proof of circularity -
    see the next test for what proof actually looks like.
    """
    wobbly = arc_through((-100.0, 0.0), (100.0, 0.0), (0.0, 3.0))
    assert wobbly.residual < 1e-9


def test_the_renders_handle_is_not_one_circular_arc(render):
    """
    The finding that the residual discipline exists to catch.

    Fitted over 510 traced edge points, one circle leaves an rms residual of
    about 0.7 px with a 1.8 px worst case. Fitted per limb, each limb comes
    back at nearly the same radius but with centres about 22 px apart, and the
    residual drops by more than half. Equal radii with offset centres is what a
    three-dimensional arc viewed off-axis projects to, not a flat circle.
    """
    outer = []
    for y in range(30, 271):
        sp = spans_subpixel(render, y, BACKGROUND_CUT, axis="row")
        if len(sp) != 2:
            continue
        outer += [(sp[0][0], y), (sp[1][1], y)]

    one = circle(outer)
    pts = np.array(outer)
    left = pts[:, 0] < one.cx
    per_limb = [circle(pts[left]), circle(pts[~left])]

    assert one.rms_residual > 0.5, "one circle should fit BADLY"
    assert all(f.rms_residual < 0.35 for f in per_limb), "each limb fits well"
    assert abs(per_limb[0].r - per_limb[1].r) < 1.0, "same radius on both limbs"
    assert abs(per_limb[0].cx - per_limb[1].cx) > 15.0, "but offset centres"


# -- acceptance: the logo trace ---------------------------------------------


def test_logo_trace_round_trips_the_stored_outlines(tmp_path):
    """
    The source crop is gone - loop_logo.json records it as a temp upload path
    that no longer exists - so the tracer is validated by round trip: render
    the stored outlines back to a raster, trace that, and see whether the same
    shapes come back. Seven outers and three holes is the reference's own
    recorded result.
    """
    import json

    from PIL import Image, ImageDraw

    d = json.loads(LOGO_JSON.read_text())
    assert sum(not s["hole"] for s in d["shapes"]) == 7
    assert sum(s["hole"] for s in d["shapes"]) == 3

    W, PAD = 400, 60
    H = int(round(W * d["aspect_h"]))
    im = Image.new("RGB", (W + 2 * PAD, H + 2 * PAD), (235, 235, 235))
    dr = ImageDraw.Draw(im)

    def to_px(pts):
        return [(PAD + x * W, PAD + (d["aspect_h"] - y) * W) for x, y in pts]

    for s in d["shapes"]:
        if not s["hole"]:
            dr.polygon(to_px(s["pts"]), fill=(40, 40, 40))
    for s in d["shapes"]:
        if s["hole"]:
            dr.polygon(to_px(s["pts"]), fill=(235, 235, 235))

    r = trace(im)
    assert len(r.outers) == 7
    assert len(r.holes) == 3
    assert r.normalised()["aspect_h"] == pytest.approx(d["aspect_h"], abs=0.002)


def test_traced_mark_is_a_wave_over_two_bars(tmp_path):
    """
    The trace is what revealed the mark is a wave over two straight bars, not
    three equal bars. Three bar-shaped outers, and they are not all the same
    height.
    """
    import json

    d = json.loads(LOGO_JSON.read_text())
    bars = []
    for sh in d["shapes"]:
        if sh["hole"]:
            continue
        xs = [p[0] for p in sh["pts"]]
        ys = [p[1] for p in sh["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if h > 1e-6 and w / h > 2.5:
            bars.append(h)
    assert len(bars) == 3
    assert max(bars) - min(bars) > 0.005, "the three bars are not identical"


def test_min_stroke_matches_the_stored_mark():
    """The thinnest bar decides whether the wordmark needs drawing oversize."""
    import json

    from PIL import Image, ImageDraw

    d = json.loads(LOGO_JSON.read_text())
    strokes = []
    for sh in d["shapes"]:
        if sh["hole"]:
            continue
        xs = [p[0] for p in sh["pts"]]
        ys = [p[1] for p in sh["pts"]]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if h > 1e-6 and w / h > 2.5:
            strokes.append(h)
    assert min(strokes) == pytest.approx(0.0492, abs=0.001)


# -- the primitives ---------------------------------------------------------


def test_box_dimensions_are_inclusive():
    """43..609 is 567 columns, not 566. The reference measurements read that way."""
    b = Box(left=43, right=609, top=283, bottom=835)
    assert b.width == 567
    assert b.height == 553


def test_bbox_of_an_empty_mask_raises():
    with pytest.raises(ValueError):
        bbox(np.zeros((4, 4), dtype=bool))


def test_by_colour_needs_three_channels(render):
    with pytest.raises(ValueError):
        by_colour(render, (1, 2), 10)


def test_by_colour_rejects_a_negative_tolerance(render):
    with pytest.raises(ValueError):
        by_colour(render, (1, 2, 3), -1)


def test_by_luminance_rejects_a_reversed_range(render):
    with pytest.raises(ValueError):
        by_luminance(render, 200, 10)


def test_saturation_separates_the_bezel_from_the_fabric(render):
    """
    The measurement that made the module findable. Luminance cannot do it: the
    grey bezel and the green fabric overlap almost completely in brightness.
    """
    sat = saturation(render)
    bezel = np.median(sat[300:320, 230:430])
    fabric = np.median(sat[400:700, 60:200])
    assert bezel <= 2.0
    assert fabric >= 30.0


def test_auto_threshold_puts_the_body_bottom_on_the_reference_row(render):
    t = auto_threshold(render)
    col = luminance(render)[:, 300]
    assert int(np.flatnonzero(col < t)[-1]) == 835


def test_fill_holes_closes_an_enclosed_gap():
    mask = np.ones((9, 9), dtype=bool)
    mask[4, 4] = False
    assert fill_holes(mask).all()


def test_fill_holes_leaves_a_gap_open_to_the_border():
    mask = np.ones((9, 9), dtype=bool)
    mask[4:, 4] = False
    assert not fill_holes(mask).all()


def test_largest_component_drops_a_stray_blob():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:12, 2:12] = True
    mask[18, 18] = True
    keep = largest_component(mask)
    assert keep.sum() == 100
    assert not keep[18, 18]


def test_runs_finds_nothing_when_coverage_is_too_low():
    mask = np.zeros((10, 10), dtype=bool)
    mask[5, 0] = True
    assert runs(mask, "row", 0.5) == []


def test_coverage_rejects_a_bad_axis():
    with pytest.raises(ValueError):
        coverage(np.ones((3, 3), dtype=bool), axis="diagonal")


def test_subpixel_edges_beat_integer_edges():
    """
    A synthetic edge at a known fractional position. The integer crossing can
    only ever be right to half a pixel; the interpolated one gets it back.
    """
    true_edge = 5.7
    x = np.arange(12).astype(float)
    ramp = np.clip((x - true_edge) * 200.0 + 128.0, 0.0, 255.0)
    img = np.stack([np.tile(ramp, (3, 1))] * 3, axis=-1).astype(np.uint8)

    integer = transitions(img, 1, 128.0)
    sub = edges_subpixel(img, 1, 128.0)
    assert len(sub) == 1
    assert abs(sub[0] - true_edge) < 0.05
    assert abs(integer[0] - true_edge) >= abs(sub[0] - true_edge)


def test_profile_rejects_an_out_of_range_line(render):
    with pytest.raises(IndexError):
        profile(render, 99999, axis="row")


def test_spans_subpixel_drops_a_clipped_span(render):
    """
    A span running off the edge of the image has one edge missing, and
    reporting it would be reporting where the picture stops, not where the
    object does.
    """
    row = profile(render, 288, axis="row")
    assert row[0] >= BACKGROUND_CUT          # this row does start in background
    assert len(spans_subpixel(render, 288, BACKGROUND_CUT)) == len(spans(render, 288, BACKGROUND_CUT))


def test_circle_refuses_a_three_point_fit():
    """
    Three points determine a circle exactly, so a three-point fit always has
    zero residual and proves nothing. Refusing it is the point.
    """
    with pytest.raises(ValueError) as exc:
        circle([(0, 0), (1, 1), (2, 0)])
    assert "arc_through" in str(exc.value)


def test_circle_recovers_a_known_radius():
    t = np.linspace(0.4, 2.7, 400)
    pts = np.column_stack([325.0 + 287.07 * np.cos(t), 500.0 + 287.07 * np.sin(t)])
    f = circle(pts)
    assert f.r == pytest.approx(287.07, abs=1e-6)
    assert f.max_residual < 1e-6


def test_circle_reports_a_real_residual_under_noise():
    rng = np.random.default_rng(0)
    t = np.linspace(0.4, 2.7, 400)
    pts = np.column_stack([325.0 + 287.07 * np.cos(t), 500.0 + 287.07 * np.sin(t)])
    f = circle(pts + rng.normal(0, 0.25, pts.shape))
    assert f.r == pytest.approx(287.07, abs=0.1)
    assert 0.1 < f.rms_residual < 0.5, "the residual must reflect the noise put in"


def test_circle_rejects_collinear_points():
    """
    lstsq returns a least-norm answer for a singular system rather than
    failing, so without a rank check this hands back a confident nonsense
    radius.
    """
    with pytest.raises(ValueError):
        circle([(0, 0), (1, 0), (2, 0), (3, 0)])


def test_points_off_any_circle_show_up_in_the_residual():
    """
    No heuristic refuses these - the residual reports them. A shallow arc has a
    genuinely huge radius and a tiny residual, so refusing large radii would
    throw away real measurements.
    """
    f = circle([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0)])
    assert f.rms_residual > 0.1


def test_a_shallow_arc_is_measured_not_refused():
    t = np.linspace(-0.05, 0.05, 200)
    pts = np.column_stack([5000.0 * np.sin(t), 5000.0 * (1 - np.cos(t))])
    f = circle(pts)
    assert f.r == pytest.approx(5000.0, rel=1e-3)
    assert f.max_residual < 0.01


def test_arc_through_rejects_collinear_points():
    with pytest.raises(ValueError):
        arc_through((0, 0), (2, 0), (1, 0))


def test_arc_sweep_exceeds_a_half_turn_for_a_deep_arc():
    """The keyring handle sweeps past 180 degrees, which the reference relies on."""
    f = arc_through((-285.5, 0.0), (285.5, 0.0), (0.0, 317.0))
    assert f.sweep_deg > 180.0


def test_trace_rejects_a_flat_image():
    flat = np.full((40, 40, 3), 128, dtype=np.uint8)
    with pytest.raises(ValueError):
        trace(flat)


def test_trace_finds_a_hole():
    """A ring: one outer, one hole. If parity flips, a counter fills in solid."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (200, 200), (240, 240, 240))
    dr = ImageDraw.Draw(im)
    dr.ellipse([20, 20, 180, 180], fill=(30, 30, 30))
    dr.ellipse([70, 70, 130, 130], fill=(240, 240, 240))
    r = trace(im, upsample=4)
    assert len(r.outers) == 1
    assert len(r.holes) == 1


def test_trace_normalises_to_unit_width():
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (200, 120), (240, 240, 240))
    ImageDraw.Draw(im).rectangle([20, 20, 180, 100], fill=(30, 30, 30))
    d = trace(im, upsample=4).normalised()
    xs = [p[0] for sh in d["shapes"] for p in sh["pts"]]
    assert min(xs) == pytest.approx(0.0, abs=1e-4)
    assert max(xs) == pytest.approx(1.0, abs=1e-4)
