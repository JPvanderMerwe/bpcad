"""
Level-2 DSL: a composition of named primitive operations.

WHY THIS EXISTS RATHER THAN LETTING THE MODEL WRITE SELECTORS
-------------------------------------------------------------
Selector strings are the single thing a small model gets wrong most often.
`.edges("|Z")`, `.faces(">Z[-2]")`, `.edges("%CIRCLE and >Z")` - the syntax is
compact, unintuitive, and wrong selectors fail silently by selecting nothing
rather than raising. So no operation here takes one. Every op addresses
geometry through a NAMED ANCHOR that the scene declares, and an unknown anchor
name is an error listing the ones that exist.

The same reasoning applies to edge groups: "vertical", "top", "bottom" rather
than "|Z", ">Z", "<Z".

Level 2 carries no geometry risk in the sense level 3 does - every op is a
Python function that has been tested - but it is more expressive than picking a
template, which is the point.

WHAT COVERAGE COSTS, AND WHY THE CREATORS ALL LOOK THE SAME NOW
----------------------------------------------------------------
The first version of this layer could make nine kinds of thing and could not
make a hole. Not a round one: `pocket` cuts rectangles into faces and `disc`
only ever added material, so the birdhouse entrance - the single most obvious
feature on the single most obvious test part - was unreachable without a
template. `rounded_prism` had no position either, so no part could contain two
boxes in different places: no L-bracket, no tray divider, no wall hook, no
foot, no rib. That is not a DSL with gaps in it, that is a DSL that can build
almost nothing.

The fix is one idea applied uniformly rather than one new op per missing
shape. Every creator now carries the same five fields:

    x_mm, y_mm, z_mm    where it goes
    rotate_deg          turned about
    rotate_axis         one of x, y, z
    mode                add, cut or intersect

`mode` is what buys the coverage. A disc that can cut is a drilled hole. A
rounded prism that can cut is a slot, a rebate, a keyway. A cone that can cut
is a countersink. A rotated prism that can cut is a chamfer at any angle. Six
creators times three modes times free placement covers a range that no
reasonable number of hand-written ops would have.

The ops are deliberately uniform for a second reason: a 7B model composing
these has to hold the whole vocabulary in its head at once, and six shapes
sharing one placement convention is far less to remember than eighteen ops
each with their own.

ONE CONVENTION, STATED ONCE, BECAUSE GETTING IT WRONG IS SILENT
----------------------------------------------------------------
Everything is built at the origin, THEN rotated about the origin, THEN moved to
(x, y, z). Rotate-then-move, never move-then-rotate: moving first and rotating
after swings the body around the world origin on the end of a long arm, and
lands it somewhere nobody predicted.

Prisms, discs, cones, wedges and extruded profiles STAND ON their placement
point - the point is the centre of their base. Spheres are CENTRED on it. That
asymmetry is real and is repeated in every docstring that needs it, because a
sphere sitting on a surface and a sphere half-buried in it look equally
plausible in a render.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Union

import cadquery as cq
from pydantic import BaseModel, ConfigDict, Field

from bpcad.build.helpers import (
    BuildLog,
    MIN_FILLET_MM,
    disc as _disc,
    poly_prism,
    rrect,
    safe_fillet_radius,
    try_edge_op,
)

# Named faces, each with its outward normal and its two in-face axes.
# u is "right" looking at the face from outside, v is "up".
FACE_FRAMES: dict[str, tuple[tuple, tuple, tuple]] = {
    "top_face": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "bottom_face": ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
    "front_face": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "back_face": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "left_face": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "right_face": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
}

EDGE_GROUPS: dict[str, str] = {
    "vertical": "|Z",
    "top": ">Z",
    "bottom": "<Z",
    "all": "",
}

AXIS_VECTOR = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

MIRROR_PLANES = {"yz": "YZ", "xz": "XZ", "xy": "XY"}


class DslError(ValueError):
    """A DSL op could not be applied. The message says which and why."""


@dataclass
class Scene:
    """
    The solid being built, plus the named anchors addressable on it.

    Anchors are recomputed from the bounding box after every op that changes
    the shape, so "top_face" always means the top of what exists now.
    """

    solid: cq.Workplane | None = None
    log: BuildLog = field(default_factory=BuildLog)
    features: dict[str, float] = field(default_factory=dict)
    print_axis: str = "z"

    def require_solid(self, op_name: str) -> cq.Workplane:
        if self.solid is None:
            raise DslError(
                "op %r needs an existing solid, but nothing has been created yet. "
                "The first op must be one that creates geometry, in `add` mode: "
                "%s." % (op_name, ", ".join(CREATOR_NAMES))
            )
        return self.solid

    def anchor_names(self) -> list[str]:
        return sorted(FACE_FRAMES)

    def anchor_plane(self, name: str) -> cq.Plane:
        """
        A cadquery Plane sitting on the named face, origin at the face centre,
        x along the face's u axis and normal pointing outward.
        """
        if name not in FACE_FRAMES:
            raise DslError(
                "unknown anchor %r. This scene has: %s. Anchors are names, never "
                "CadQuery selector strings."
                % (name, ", ".join(self.anchor_names()))
            )
        solid = self.require_solid("anchor lookup")
        bb = solid.val().BoundingBox()
        n, u, _v = FACE_FRAMES[name]

        centre = [
            (bb.xmin + bb.xmax) / 2.0,
            (bb.ymin + bb.ymax) / 2.0,
            (bb.zmin + bb.zmax) / 2.0,
        ]
        extreme = {
            (0, 0, 1): (2, bb.zmax), (0, 0, -1): (2, bb.zmin),
            (0, -1, 0): (1, bb.ymin), (0, 1, 0): (1, bb.ymax),
            (-1, 0, 0): (0, bb.xmin), (1, 0, 0): (0, bb.xmax),
        }[n]
        centre[extreme[0]] = extreme[1]

        return cq.Plane(
            origin=cq.Vector(*centre), xDir=cq.Vector(*u), normal=cq.Vector(*n)
        )


# Anchors as a Literal, not a bare str. Two reasons, and the second is the one
# that matters: a bad name is then caught at PARSE time with the legal set in
# the message, and the JSON schema handed to the model carries the legal names
# so a constrained decoder cannot emit anything else. Putting the template
# names in an enum measurably stopped models inventing templates; this is the
# same fix one level down.
Anchor = Literal[
    "top_face", "bottom_face", "front_face", "back_face", "left_face", "right_face"
]
EdgeGroup = Literal["vertical", "top", "bottom", "all"]
Mode = Literal["add", "cut", "intersect"]
Axis = Literal["x", "y", "z"]


class DslOp(BaseModel):
    """Base for every operation. Subclasses implement apply()."""

    model_config = ConfigDict(extra="forbid")

    def apply(self, scene: Scene) -> Scene:  # pragma: no cover - abstract
        raise NotImplementedError


# ---------------------------------------------------------------------------
# creators
# ---------------------------------------------------------------------------


class Creator(DslOp):
    """
    A shape, placed, and either added to the part or cut out of it.

    Subclasses supply `_emit()`, which builds the shape at the origin in its
    own natural orientation and knows nothing about placement. Everything to do
    with where it goes and what it does to the part happens here, once, so
    every shape behaves identically.
    """

    x_mm: float = Field(0.0, ge=-2000, le=2000, description="Where to put it, X.")
    y_mm: float = Field(0.0, ge=-2000, le=2000, description="Where to put it, Y.")
    z_mm: float = Field(0.0, ge=-2000, le=2000, description="Where to put it, Z.")
    rotate_deg: float = Field(
        0.0, ge=-360, le=360,
        description="Turn about the origin BEFORE moving into place.",
    )
    rotate_axis: Axis = Field("z", description="Which axis to turn about: x, y or z.")
    mode: Mode = Field(
        "add",
        description=(
            "add fuses it on, cut removes it from the part, intersect keeps "
            "only the overlap. cut is how holes, slots and countersinks are "
            "made - there is no separate hole op."
        ),
    )

    def _emit(self) -> cq.Workplane:  # pragma: no cover - abstract
        raise NotImplementedError

    def _label(self) -> str:
        return getattr(self, "op", type(self).__name__)

    def _missed_cut_advice(self, scene, part, body) -> str:
        """
        Which placement field is wrong, for a cut that removed nothing.

        THE ADVICE HAS TO BE ABOUT THE RIGHT AXIS. Asked for "a hinge" the
        model put a bore at x_mm 20 on a part 30 mm wide, four times running,
        and the critique answered with "set z_mm to -2 and height_mm to 54" -
        true of a cut that is too SHORT and useless for one that is in the
        wrong PLACE. It handed off after four attempts having never been told
        the thing that was actually wrong.

        Rotation does not affect this: apply() rotates about the origin and
        THEN translates by (x_mm, y_mm, z_mm), so those fields are always
        world-axis offsets. Length is the only thing rotation reinterprets,
        which is why _through_cut_numbers still refuses to speak about a
        rotated cut and this does not.
        """
        fields = {"x": "x_mm", "y": "y_mm", "z": "z_mm"}
        offsets = {"x": self.x_mm, "y": self.y_mm, "z": self.z_mm}
        # SIDEWAYS AXES FIRST, and the print axis is left to the through-cut
        # advice below. Centring is the right correction for a cut that is
        # beside the part; along the print axis it is the wrong one - centring
        # a short cut inside a tall part turns a miss into a sealed internal
        # void, which then trips the ceiling check instead.
        axis_order = [a for a in "xyz" if a != (scene.print_axis or "z")]
        for axis in axis_order:
            p0, p1 = _axis_extent(part, axis)
            c0, c1 = _axis_extent(body, axis)
            if c1 < p0 or c0 > p1:
                # No overlap at all on this axis: this is the one that is wrong.
                middle = offsets[axis] - ((c0 + c1) / 2.0 - (p0 + p1) / 2.0)
                return (" It misses along %s: the cut spans %.2f..%.2f and the "
                        "part spans %.2f..%.2f. Set %s to %.2f to centre it on "
                        "the part, then adjust from there."
                        % (axis, c0, c1, p0, p1, fields[axis], middle))
        return self._through_cut_numbers(scene, part)

    def _through_cut_numbers(self, scene, part) -> str:
        """
        The two numbers that would make this cut go through, spelled out.

        WHY THIS IS NOT ADVICE. The first version said "start it below the
        bottom face and make it longer than the part is thick", which is true
        and got the following, twice, from two different models: the cut moved
        from z_mm -2 to z_mm -42 on a part 50 mm tall, with height_mm left
        alone. One fault became the other - a blind pocket became a cut that
        misses the part completely - and four attempts burned on it.

        The loop's own rule is that a critique names the parameter most likely
        responsible and the value it should take. A small model given a
        principle edits one number and hopes; given two numbers it sets two
        numbers. Both are computed off the measured part, so they are right
        for THIS part rather than generally sound.

        Only offered for a cut that is not rotated, because z_mm is then the
        cut's own base. On a rotated cut the placement fields do not line up
        with the print axis and naming them would be worse than saying
        nothing.
        """
        axis = scene.print_axis if scene.print_axis in "xyz" else "z"
        if self.rotate_deg or axis != "z":
            return ""
        p0, p1 = _axis_extent(part, axis)
        if p1 - p0 <= 0:
            return (" Set z_mm below the part's bottom face and height_mm "
                    "longer than the part is thick.")
        return (" Set z_mm to %.2f and height_mm to %.2f, which spans "
                "%.2f..%.2f and clears both faces by 2 mm. Change BOTH: "
                "moving z_mm down on its own only moves the same short cut "
                "further away." % (p0 - 2.0, (p1 - p0) + 4.0, p0 - 2.0, p1 + 2.0))

    def _record_through_cut_repair(self, scene, part) -> None:
        """
        The correction for a short cut, as data the pipeline can apply.

        WHY THIS IS NOT JUST THE PROSE. _through_cut_numbers already computes
        `z_mm` and `height_mm` off the measured part and writes them into the
        critique, in the exact form "Set z_mm to -2.00 and height_mm to 10.00".
        Across an eval of nineteen first-try prompts, thirty of the fifty-odd
        attempt failures were this one fault - the model was handed the answer
        and did not apply it, four attempts running, and the part was lost.

        The numbers are measured, not guessed: they come off the part that was
        just built. Recording them here lets compile_and_verify correct the
        spec deterministically instead of spending three more minutes of model
        time asking for two decimals to be copied.

        Only for a cut this can speak about honestly - unrotated, on a z print
        axis - which is the same condition _through_cut_numbers uses to decide
        whether to name the fields at all.
        """
        axis = scene.print_axis if scene.print_axis in "xyz" else "z"
        if self.rotate_deg or axis != "z":
            return
        # ONLY AN OP THAT HAS BOTH FIELDS TO CORRECT. `sphere` and `arc_rod`
        # are creators with no height_mm, and writing one onto them would make
        # the spec invalid - the rebuild would raise and the repair would be
        # rolled back, which works but spends a compile finding out something
        # knowable here.
        if not (hasattr(self, "height_mm") and hasattr(self, "z_mm")):
            return
        p0, p1 = _axis_extent(part, axis)
        if p1 - p0 <= 0:
            return
        scene.log.repairs.append({
            "index": None,               # stamped by run_ops
            "op": self._label(),
            "fields": {"z_mm": round(p0 - 2.0, 3),
                       "height_mm": round((p1 - p0) + 4.0, 3)},
            "why": "the cut stopped inside the part, leaving a blind pocket "
                   "opening downward where a hole was asked for",
        })

    def _note_if_it_leaves_a_ceiling(self, scene, part, body) -> None:
        """
        A cut that enters the bottom face and stops inside leaves a roof.

        CLAUDE.md 23: a cavity opening downward creates a ceiling needing
        support, and that is a lint rule, not a preference. Nothing enforced
        it, so this happened: asked for two 5 mm holes through a 6 mm plate,
        the model wrote `height_mm 7` at `z_mm -2`, spanning -2..5. Every
        number looks deliberate and the holes are 1 mm short of the top face.

        The part built, verified, and reported 39.3 mm2 of downward-facing
        area - which is exactly the two hole roofs, to a tenth of a
        millimetre - and shipped as PASS with two blind pockets where two
        holes were asked for. The volume gave it away and nothing else did,
        because "supports needed" is not a failure on its own: plenty of good
        parts need support, the vent reference among them.

        Which face counts as the bottom is the PRINT axis, not Z by habit.
        """
        axis = scene.print_axis if scene.print_axis in "xyz" else "z"
        p0, p1 = _axis_extent(part, axis)
        c0, c1 = _axis_extent(body, axis)
        if p1 - p0 <= 0:
            return

        eps = 0.001
        enters_the_bottom = c0 <= p0 + eps
        stops_short_of_the_top = c1 < p1 - eps
        if not (enters_the_bottom and stops_short_of_the_top):
            return

        # A CHANNEL IS NOT A HOLE THAT STOPPED SHORT.
        #
        # This flagged the rod channel of a saddle clamp, which opens downward
        # because the clamp goes OVER the rod - there is no other way to shape
        # it, and it is the corpus's rod_clamp_8mm. The discriminator is
        # whether the cut also leaves through a side: a blind hole sits wholly
        # inside the footprint and opens in one direction only, while a
        # channel runs out of the part and is a deliberate shape.
        footprint = {}
        for other in [a for a in "xyz" if a != axis]:
            q0, q1 = _axis_extent(part, other)
            d0, d1 = _axis_extent(body, other)
            footprint[other] = (d0, d1)
            if d0 <= q0 + eps or d1 >= q1 - eps:
                return
        cx0, cx1 = footprint.get("x", _axis_extent(body, "x"))
        cy0, cy1 = footprint.get("y", _axis_extent(body, "y"))

        # IS THERE ANYTHING ACTUALLY ABOVE IT? The test so far compares the
        # cut's top against the part's GLOBAL top, and a part is not a
        # rectangle. A 3.5 mm screw hole through the 3 mm foot of a clip whose
        # arch stands 12 mm tall elsewhere was reported as stopping 4 mm short
        # of the top - it goes straight through the foot and out into open
        # air, because at that x and y there is no arch above it. Under
        # strict_cuts that rejected a part that was completely correct.
        #
        # So ask the geometry instead of the bounding box: put a probe over
        # the cut's own footprint, from where the cut ends up to the top of
        # the part, and see whether any material is in there. One boolean, and
        # only on the path that was about to raise.
        try:
            probe_box = (
                cq.Workplane("XY")
                .box(max(cx1 - cx0, 1e-3), max(cy1 - cy0, 1e-3), max(p1 - c1, 1e-3),
                     centered=(True, True, False))
                .translate(((cx0 + cx1) / 2.0, (cy0 + cy1) / 2.0, c1))
            )
            if _volume(part.intersect(probe_box)) <= 1e-6:
                return
        except Exception:
            # A probe that cannot be built is no evidence either way, and a
            # lint must not fire on its own failure to measure.
            return

        scene.log.notes.append(
            "%s %s in cut mode enters the bottom face and stops %.2f mm short "
            "of the top, so it is a blind pocket opening DOWNWARD, not a hole "
            "through the part. It leaves a roof that has to print over air. "
            "The part spans %s %.2f..%.2f and the cut spans %.2f..%.2f. For a "
            "hole through it, the cut must clear both faces.%s If a recess on "
            "the underside really was wanted, put it on the top face instead."
            % (CUT_FAULT, self._label(), p1 - c1, axis, p0, p1, c0, c1,
               self._through_cut_numbers(scene, part))
        )
        # AND THE SAME TWO NUMBERS AS DATA. See BuildLog.repairs: the critique
        # already spells them out and small models copy them wrong, so the
        # pipeline is given them in a form it can apply itself.
        self._record_through_cut_repair(scene, part)

    def apply(self, scene: Scene) -> Scene:
        body = self._emit()

        # Rotate FIRST, about the origin, then move. The other order swings the
        # shape around the world origin on the end of a long arm and puts it
        # somewhere nobody intended.
        if self.rotate_deg:
            axis = AXIS_VECTOR[self.rotate_axis]
            body = body.rotate((0, 0, 0), axis, self.rotate_deg)
        if self.x_mm or self.y_mm or self.z_mm:
            body = body.translate((self.x_mm, self.y_mm, self.z_mm))

        if self.mode == "add":
            scene.solid = body if scene.solid is None else scene.solid.union(body)
            return scene

        solid = scene.require_solid(self._label())
        before = _volume(solid)
        if self.mode == "cut":
            result = solid.cut(body)
        else:
            result = solid.intersect(body)

        after = _volume(result)
        if after <= 1e-6:
            raise DslError(
                "%s in %s mode removed the entire part - nothing is left. Either "
                "it is far larger than the part, or it is positioned over all of "
                "it. The part was %.1f mm3 before."
                % (self._label(), self.mode, before)
            )
        if self.mode == "cut" and abs(after - before) < 1e-6:
            # STILL A NOTE HERE, DELIBERATELY. A person's own spec must not lose
            # a whole build over one cut that missed - see
            # test_a_cut_that_misses_is_reported_but_not_fatal.
            #
            # But the note now carries the numbers, because the agent DOES
            # treat this as a failure (compile_and_verify(strict_cuts=True))
            # and a critique that says only "removed nothing" gives a small
            # model nothing to change. It sat here as a bare sentence while a
            # drilled plate shipped with one hole instead of two.
            scene.log.notes.append(
                "%s %s in cut mode removed nothing - it does not touch the "
                "part. It sits at (%.1f, %.1f, %.1f) and the part spans %s.%s"
                % (CUT_FAULT, self._label(), self.x_mm, self.y_mm, self.z_mm,
                   _extent(solid), self._missed_cut_advice(scene, solid, body))
            )
        else:
            self._note_if_it_leaves_a_ceiling(scene, solid, body)
        scene.solid = result
        return scene


# TAG ON EVERY CUT FAULT. compile_and_verify(strict_cuts=True) keys off this
# rather than matching an English phrase, so rewording a note cannot silently
# switch the enforcement off.
CUT_FAULT = "cut fault:"


def _axis_extent(solid: cq.Workplane, axis: str) -> tuple[float, float]:
    """(min, max) of a solid along one axis, or (0, 0) if it cannot be read."""
    try:
        bb = solid.val().BoundingBox()
        return {
            "x": (bb.xmin, bb.xmax), "y": (bb.ymin, bb.ymax),
            "z": (bb.zmin, bb.zmax),
        }[axis]
    except Exception:
        return (0.0, 0.0)


def _extent(solid: cq.Workplane) -> str:
    """
    The part's bounding box, so a miss can be acted on.

    "it does not touch the part" says something is wrong. "it sits at
    (50.0, 0.0, 0.0) and the part spans x -40.0..40.0" says what.
    """
    try:
        bb = solid.val().BoundingBox()
        return ("x %.1f..%.1f, y %.1f..%.1f, z %.1f..%.1f"
                % (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax))
    except Exception:
        return "an extent that could not be read"


def _volume(solid: cq.Workplane) -> float:
    """Volume in mm3, or 0.0 for an empty result rather than an exception."""
    try:
        if not solid.vals():
            return 0.0
        return float(abs(solid.val().Volume()))
    except Exception:
        return 0.0


class RoundedPrism(Creator):
    """
    A rectangular block with rounded vertical corners. The usual starting point.

    Stands ON its placement point: (x, y, z) is the centre of its base.
    """

    op: Literal["rounded_prism"]
    width_mm: float = Field(..., gt=0, le=1000, description="X extent.")
    depth_mm: float = Field(..., gt=0, le=1000, description="Y extent.")
    height_mm: float = Field(..., gt=0, le=1000, description="Z extent, upward from the base.")
    corner_r_mm: float = Field(0.0, ge=0, le=500, description="Vertical corner radius.")

    def _emit(self) -> cq.Workplane:
        return rrect(
            self.width_mm, self.depth_mm, self.corner_r_mm,
            -self.depth_mm / 2.0, self.height_mm,
        )


class Disc(Creator):
    """
    A cylinder, axis along Z. In `cut` mode this is a round hole.

    Stands ON its placement point: (x, y, z) is the centre of its base. To
    drill right through a part, start below it and make it longer than the
    part - a cutter that stops exactly flush leaves a zero-thickness face that
    the mesher may or may not close.
    """

    op: Literal["disc"]
    diameter_mm: float = Field(..., gt=0, le=1000)
    height_mm: float = Field(..., gt=0, le=1000, description="Length along its axis.")

    def _emit(self) -> cq.Workplane:
        return _disc(self.diameter_mm, 0.0, 0.0, self.height_mm, z0=0.0)


class Cone(Creator):
    """
    A cone or a truncated cone, axis along Z. In `cut` mode, a countersink.

    Stands ON its placement point. `top_d_mm` of 0 gives a point.
    """

    op: Literal["cone"]
    bottom_d_mm: float = Field(..., ge=0, le=1000, description="Diameter at the base.")
    top_d_mm: float = Field(0.0, ge=0, le=1000, description="Diameter at the top. 0 is a point.")
    height_mm: float = Field(..., gt=0, le=1000)

    def _emit(self) -> cq.Workplane:
        if self.bottom_d_mm <= 0 and self.top_d_mm <= 0:
            raise DslError(
                "cone: both ends have zero diameter, which is a line and not a "
                "solid. At least one of bottom_d_mm and top_d_mm must be above 0."
            )
        solid = cq.Solid.makeCone(
            self.bottom_d_mm / 2.0, self.top_d_mm / 2.0, self.height_mm
        )
        return cq.Workplane("XY").newObject([solid])


class Sphere(Creator):
    """
    A ball. In `cut` mode, a spherical dish.

    CENTRED on its placement point, unlike every other creator, which stands on
    it. A sphere at z=0 is therefore half below the bed. To sit one on a
    surface, put z at the surface plus the radius.
    """

    op: Literal["sphere"]
    diameter_mm: float = Field(..., gt=0, le=1000)

    def _emit(self) -> cq.Workplane:
        return cq.Workplane("XY").sphere(self.diameter_mm / 2.0)


class Wedge(Creator):
    """
    A ramp: a triangular prism rising along +Y, flat underneath.

    This is what makes stands, gussets, brackets and any sloped face. In `cut`
    mode it is a chamfer of any angle, on any edge, which the fixed-size
    chamfer in blend_edges cannot do.

    Stands ON its placement point, which is the centre of its rectangular base.
    The slope runs from zero height at -depth/2 up to `height_mm` at +depth/2,
    so `rotate_deg: 180, rotate_axis: z` makes it fall the other way.
    """

    op: Literal["wedge"]
    width_mm: float = Field(..., gt=0, le=1000, description="X extent, the constant one.")
    depth_mm: float = Field(..., gt=0, le=1000, description="Y extent, the direction it rises in.")
    height_mm: float = Field(..., gt=0, le=1000, description="Z extent at the high end.")

    def _emit(self) -> cq.Workplane:
        half_d = self.depth_mm / 2.0
        # A YZ workplane's local x is world Y and local y is world Z, and it
        # extrudes along +X - which is exactly the axis the wedge is constant on.
        profile = (
            cq.Workplane("YZ")
            .moveTo(-half_d, 0)
            .lineTo(half_d, 0)
            .lineTo(half_d, self.height_mm)
            .close()
            .extrude(self.width_mm)
        )
        return profile.translate((-self.width_mm / 2.0, 0, 0))


class ProfileExtrude(Creator):
    """
    Any closed outline, extruded upward. The general-purpose shape maker.

    Points are (x, y) pairs in the outline's own units, multiplied by
    `scale_mm`. Give it the silhouette and it gives you the part: a hook, a
    bottle opener, a cam, a gear tooth, a traced logo. In `cut` mode it is a
    shaped hole.

    Stands ON its placement point, which corresponds to (0, 0) in the outline's
    own coordinates - NOT the centre of the outline, which is usually not the
    same place.
    """

    op: Literal["profile_extrude"]
    points: list[tuple[float, float]] = Field(
        ..., min_length=3, max_length=2000,
        description="Closed outline as (x, y) pairs. Do not repeat the first point at the end.",
    )
    scale_mm: float = Field(1.0, gt=0, le=1000, description="Multiplier from outline units to mm.")
    height_mm: float = Field(..., gt=0, le=1000, description="Extrusion in Z.")

    def _emit(self) -> cq.Workplane:
        return poly_prism(self.points, self.scale_mm, 0.0, 0.0, 0.0, self.height_mm)


class ArcRod(Creator):
    """
    A rod following a circular arc, lying in the XY plane and extruded in Z.

    Built as an annulus trimmed to a half-plane, which is how the reference
    keyring's fused handle is made: it gives exactly the render's arc without
    a sweep or a revolve. Whole rings, split rings, handles, hooks, clips.

    Stands ON its placement point, which is the centre of the arc.
    """

    op: Literal["arc_rod"]
    arc_r_mm: float = Field(..., gt=0, le=1000, description="Centreline radius.")
    rod_d_mm: float = Field(..., gt=0, le=500, description="Rod section diameter.")
    thickness_mm: float = Field(..., gt=0, le=1000, description="Extrusion in Z.")
    trim_below_y_mm: float | None = Field(
        None, description="Keep only the part of the arc above this y. Omit to keep the ring."
    )

    def _emit(self) -> cq.Workplane:
        if self.rod_d_mm / 2.0 >= self.arc_r_mm:
            raise DslError(
                "arc_rod: rod_d_mm %.3f is too thick for arc_r_mm %.3f - the "
                "inner radius would be negative and the rod would close into a "
                "disc. Legal: rod_d_mm under %.3f."
                % (self.rod_d_mm, self.arc_r_mm, 2 * self.arc_r_mm)
            )
        outer = _disc(2 * (self.arc_r_mm + self.rod_d_mm / 2.0),
                      0.0, 0.0, self.thickness_mm, z0=0.0)
        inner = _disc(2 * (self.arc_r_mm - self.rod_d_mm / 2.0),
                      0.0, 0.0, self.thickness_mm, z0=0.0)
        ring = outer.cut(inner)
        if self.trim_below_y_mm is not None:
            from bpcad.build.helpers import clip

            ring = clip(ring, "y", self.trim_below_y_mm, keep="above")
        return ring


# ---------------------------------------------------------------------------
# modifiers
# ---------------------------------------------------------------------------


def _place_on_anchor(scene: Scene, anchor: str, local: cq.Workplane) -> cq.Workplane:
    """Move a solid built around the local origin onto a named anchor face."""
    plane = scene.anchor_plane(anchor)
    moved = local.val().moved(cq.Location(plane))
    return cq.Workplane("XY").newObject([moved])


class LoftSection(BaseModel):
    """
    One cross-section of a loft, at a distance along its axis.

    `depth_mm` omitted means a circle. `x_mm` and `y_mm` shift this station
    sideways, which is what BENDS the loft - a stack of circles walking along
    x is a curved horn, not a straight cone.
    """

    model_config = ConfigDict(extra="forbid")

    at_mm: float = Field(
        ..., ge=0, le=1000,
        description="Distance from the base of the loft, along its axis.")
    width_mm: float = Field(
        ..., gt=0, le=1000, description="Across X at this station.")
    depth_mm: float | None = Field(
        None, gt=0, le=1000,
        description="Across Y at this station. Omit for a circle.")
    x_mm: float = Field(
        0.0, ge=-1000, le=1000,
        description="Shift this station sideways in X. This is what bends it.")
    y_mm: float = Field(
        0.0, ge=-1000, le=1000, description="Shift this station sideways in Y.")
    shape: Literal["ellipse", "rect"] = Field(
        "ellipse", description="ellipse is the organic one; rect is a slab.")


class Loft(Creator):
    """
    A solid blended through a stack of cross-sections: tapers, bulges, bends.

    THIS IS THE OP THAT MAKES ORGANIC SHAPES POSSIBLE. Everything else in this
    list is a box, a cylinder, a cone or a ball - shapes with one size all the
    way along. A body that is fat in the middle and thin at both ends, a horn
    that tapers as it curves, a tail segment, a fairing, a handle that swells
    where a hand goes: none of them can be made from primitives that do not
    change section, and before this op the honest answer to most of what a
    person wants to print was "no template fits".

    Sections are given in order from the base. Each one may be a different size
    AND in a different place, so the loft tapers and bends at the same time.
    Stands ON its placement point like every other creator.
    """

    op: Literal["loft"]
    sections: list[LoftSection] = Field(
        ..., min_length=2, max_length=64,
        description=(
            "Cross-sections from the base up, in increasing at_mm. Three or "
            "four is usually enough: base, widest point, tip"
        ),
    )
    ruled: bool = Field(
        False,
        description=(
            "true joins the sections with straight sides, like a stack of "
            "cones. false blends them smoothly, which is what an organic "
            "shape wants"
        ),
    )

    def _emit(self) -> cq.Workplane:
        stations = sorted(self.sections, key=lambda s: s.at_mm)
        for a, b in zip(stations, stations[1:]):
            if abs(b.at_mm - a.at_mm) < 1e-6:
                raise DslError(
                    "loft: two sections are both at %.3f mm along the axis, so "
                    "there is no distance between them to blend over. Move one."
                    % a.at_mm
                )

        wires = []
        for station in stations:
            depth = station.depth_mm if station.depth_mm is not None else station.width_mm
            centre = cq.Vector(station.x_mm, station.y_mm, station.at_mm)
            if station.shape == "rect":
                half_w, half_d = station.width_mm / 2.0, depth / 2.0
                points = [
                    (-half_w, -half_d), (half_w, -half_d),
                    (half_w, half_d), (-half_w, half_d), (-half_w, -half_d),
                ]
                wire = cq.Wire.makePolygon(
                    [cq.Vector(px, py, 0) for px, py in points])
            elif abs(station.width_mm - depth) < 1e-9:
                wire = cq.Wire.makeCircle(
                    station.width_mm / 2.0, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1))
            else:
                wire = cq.Wire.makeEllipse(
                    station.width_mm / 2.0, depth / 2.0,
                    cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), cq.Vector(1, 0, 0))
            wires.append(wire.translate(centre))

        try:
            solid = cq.Solid.makeLoft(wires, self.ruled)
        except Exception as exc:
            raise DslError(
                "loft: the sections could not be blended into a solid (%s). "
                "Mixing rect and ellipse sections, or a very sharp change in "
                "size between two stations, is the usual cause - try sections "
                "of the same shape, or put an extra one between them." % exc
            ) from exc
        return cq.Workplane("XY").newObject([solid])


class FreeJoint(Creator):
    """
    Cut a running gap around a ball and its stem, leaving two bodies that move.

    THIS IS WHAT MAKES A PART ARTICULATED, and nothing before it could.

    A print-in-place joint is not built by placing two objects near each other
    - a slicer fuses anything closer than a nozzle width. It is built by making
    ONE blob and then removing a thin shell inside it, so what is left is a
    ball trapped in a socket with a measured gap between them. That is the
    whole trick, and it is a subtraction rather than an assembly.

    So: build the segment that ends in a ball, build the segment that swallows
    it, let them overlap, and put this op at the ball's centre. It removes a
    `clearance_mm` shell around the ball AND a matching annulus around the
    stem, so the stem can swing in the socket's mouth instead of being welded
    into it. The stem itself is never cut, which is what keeps the ball
    attached to the segment it belongs to.

    The gap is a MEASURED value, per material, out of config - the same number
    a hinge's running fit comes from. It is required rather than defaulted
    because a joint built to a guessed clearance either binds solid or rattles,
    and both are a wasted print. The prompt carries the measured figure for the
    material in use.

    The stem runs along +Z from the ball centre before placement, so
    rotate_axis and rotate_deg aim the joint.
    """

    op: Literal["free_joint"]
    diameter_mm: float = Field(
        ..., gt=0, le=500, description="The ball's diameter.")
    clearance_mm: float = Field(
        ..., gt=0, le=2.0,
        description=(
            "The running gap, measured, from the material's config. Not a "
            "guess: too small binds solid and too large rattles"
        ),
    )
    stem_d_mm: float = Field(
        ..., gt=0, le=500,
        description=(
            "The neck joining the ball to its own segment. Must be smaller "
            "than the ball or the joint pulls straight out"
        ),
    )
    stem_len_mm: float = Field(
        ..., gt=0, le=500,
        description=(
            "How far the socket's mouth is opened up along the stem. About "
            "the ball's diameter is usually right"
        ),
    )

    mode: Mode = Field(
        "cut",
        description="Always cut - this op removes the gap that frees the ball.",
    )

    def _emit(self) -> cq.Workplane:
        if self.stem_d_mm >= self.diameter_mm:
            raise DslError(
                "free_joint: the stem is %.2f mm and the ball is %.2f mm, so "
                "there is no shoulder to hold the joint together and it would "
                "pull straight out. Make stem_d_mm smaller than diameter_mm - "
                "about half is usual."
                % (self.stem_d_mm, self.diameter_mm)
            )

        r = self.diameter_mm / 2.0
        c = self.clearance_mm
        stem_r = self.stem_d_mm / 2.0

        ball = cq.Solid.makeSphere(r, angleDegrees1=-90)
        ball_outer = cq.Solid.makeSphere(r + c, angleDegrees1=-90)

        # The stem runs +Z out of the ball. It is made longer than the mouth
        # so the annulus around it reaches clear of the socket material.
        reach = self.stem_len_mm + r + c
        stem = cq.Solid.makeCylinder(stem_r, reach, cq.Vector(0, 0, 0),
                                     cq.Vector(0, 0, 1))
        stem_outer = cq.Solid.makeCylinder(stem_r + c, reach, cq.Vector(0, 0, 0),
                                           cq.Vector(0, 0, 1))

        try:
            # ONE SUBTRACTION, NOT TWO FUSED SHELLS.
            #
            # The obvious build - (ball_outer - ball) fused to
            # (stem_outer - stem) - meets itself at a knife edge where the
            # stem leaves the ball, and a zero-thickness feature tessellates
            # into open edges: both bodies came out of it with holes in the
            # mesh and failed the watertight check.
            #
            # The gap is simply "everything within clearance of the moving
            # member's surface", so it is built that way: grow the whole
            # member, subtract the member. No seam, because there are no two
            # pieces to join. And the member itself is never removed, which is
            # what keeps the ball on its own stem.
            member = ball.fuse(stem).clean()
            grown = ball_outer.fuse(stem_outer).clean()
            shell = grown.cut(member).clean()
        except Exception as exc:
            raise DslError(
                "free_joint: could not build the clearance shell (%s). Check "
                "that clearance_mm is small next to the ball." % exc
            ) from exc
        return cq.Workplane("XY").newObject([shell])


class Pocket(DslOp):
    """
    Cut a rounded rectangular recess into a named face.

    Positive `depth_mm` goes INTO the part. Position is in the face's own
    coordinates: u to the right and v up, both measured from the face centre.

    This is the face-relative way to make a recess, and it stays because
    "10 mm in from the middle of the front" is how a person describes a
    feature. For anything that is not a rectangle on a flat outer face, use a
    creator in `cut` mode instead.
    """

    op: Literal["pocket"]
    anchor: Anchor = Field(..., description="Face to cut into. A name, not a selector.")
    width_mm: float = Field(..., gt=0, le=1000, description="Extent along the face's u axis.")
    height_mm: float = Field(..., gt=0, le=1000, description="Extent along the face's v axis.")
    depth_mm: float = Field(..., gt=0, le=1000, description="How far into the part.")
    u_mm: float = Field(0.0, ge=-1000, le=1000, description="Offset from the face centre, u.")
    v_mm: float = Field(0.0, ge=-1000, le=1000, description="Offset from the face centre, v.")
    corner_r_mm: float = Field(0.0, ge=0, le=500)
    name: str | None = Field(None, description="Record the pocket's smallest wall as a named feature.")

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("pocket")
        over = 1.0          # overshoot so the cutter breaks the surface cleanly
        local = rrect(
            self.width_mm, self.height_mm, self.corner_r_mm,
            -self.height_mm / 2.0, self.depth_mm + over, z0=-self.depth_mm,
        ).translate((self.u_mm, self.v_mm, 0))
        scene.solid = solid.cut(_place_on_anchor(scene, self.anchor, local))
        if self.name:
            scene.features[self.name] = min(self.width_mm, self.height_mm)
        return scene


class EmbossPolygon(DslOp):
    """
    Raise or cut a closed polygon on a named face.

    Points are in the polygon's own units and multiplied by `scale_mm`, which is
    how a traced logo outline - normalised to unit width - becomes geometry.
    """

    op: Literal["emboss_polygon"]
    anchor: Anchor = Field(..., description="Face to work on. A name, not a selector.")
    points: list[tuple[float, float]] = Field(..., min_length=3)
    scale_mm: float = Field(1.0, gt=0, le=1000, description="Multiplier from polygon units to mm.")
    depth_mm: float = Field(..., gt=0, le=100, description="Relief height, or cut depth if cut.")
    cut: bool = Field(False, description="True cuts into the face, False raises off it.")
    u_mm: float = Field(0.0, ge=-1000, le=1000)
    v_mm: float = Field(0.0, ge=-1000, le=1000)

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("emboss_polygon")
        over = 1.0 if self.cut else 0.0
        z0 = -self.depth_mm if self.cut else 0.0
        local = poly_prism(
            self.points, self.scale_mm, self.u_mm, self.v_mm, z0, self.depth_mm + over
        )
        placed = _place_on_anchor(scene, self.anchor, local)
        scene.solid = solid.cut(placed) if self.cut else solid.union(placed)
        return scene


class EmbossText(DslOp):
    """
    Raise or cut lettering on a named face.

    "with my name on it" is one of the most common things anyone asks a printer
    for, and it was unreachable. The glyph SIZE is recorded as a feature, not
    the stroke width: the stroke depends on the typeface and is not something
    this can measure, so it is not claimed. As a rule of thumb a stroke is
    around a tenth of the size, which means text under about 4 mm on a 0.4 mm
    nozzle will not resolve - but that is a rule of thumb and it is reported as
    one, not as a measurement.
    """

    op: Literal["emboss_text"]
    anchor: Anchor = Field(..., description="Face to letter. A name, not a selector.")
    text: str = Field(..., min_length=1, max_length=200)
    size_mm: float = Field(..., gt=0, le=500, description="Cap height of the lettering.")
    depth_mm: float = Field(..., gt=0, le=100, description="Relief height, or cut depth if cut.")
    cut: bool = Field(False, description="True engraves into the face, False raises off it.")
    u_mm: float = Field(0.0, ge=-1000, le=1000)
    v_mm: float = Field(0.0, ge=-1000, le=1000)

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("emboss_text")
        over = 1.0 if self.cut else 0.0
        z0 = -self.depth_mm if self.cut else 0.0
        try:
            local = (
                cq.Workplane("XY", origin=(self.u_mm, self.v_mm, z0))
                .text(self.text, self.size_mm, self.depth_mm + over)
            )
        except Exception as exc:
            raise DslError(
                "emboss_text could not letter %r: %s. This needs a system font "
                "and there may not be one - the part is buildable without the "
                "lettering." % (self.text, exc)
            ) from exc
        if not local.vals() or _volume(local) <= 0:
            raise DslError(
                "emboss_text produced no geometry for %r - every character came "
                "out empty." % self.text
            )
        placed = _place_on_anchor(scene, self.anchor, local)
        scene.solid = solid.cut(placed) if self.cut else solid.union(placed)
        scene.features["lettering cap height"] = self.size_mm
        scene.log.notes.append(
            "lettering %r at %.1f mm cap height - the STROKE is roughly a tenth "
            "of that and is not measured here, so check it resolves"
            % (self.text, self.size_mm)
        )
        return scene


class BlendEdges(DslOp):
    """
    Fillet or chamfer a named edge group. Always attempt-and-revert.

    Apply these LAST, after every pocket is cut. A cosmetic edge operation must
    never be able to break a build, and a failure partway through must not be
    able to corrupt detail that was already there.
    """

    op: Literal["blend_edges"]
    group: EdgeGroup = Field(..., description="Edge group name: vertical, top, bottom or all.")
    kind: Literal["fillet", "chamfer"] = "fillet"
    amount_mm: float = Field(..., gt=0, le=100)
    label: str = Field("blend", description="Name for the build report.")

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("blend_edges")
        if self.group not in EDGE_GROUPS:
            raise DslError(
                "unknown edge group %r. Legal: %s. Groups are names, never "
                "CadQuery selector strings."
                % (self.group, ", ".join(sorted(EDGE_GROUPS)))
            )
        bb = solid.val().BoundingBox()
        amount = safe_fillet_radius(self.amount_mm, bb.xlen, bb.ylen, bb.zlen)
        if amount < MIN_FILLET_MM:
            scene.log.notes.append(
                "%s: %.3f mm is below the %.2f mm worth attempting on a part this "
                "size, skipped" % (self.label, self.amount_mm, MIN_FILLET_MM)
            )
            return scene
        scene.solid = try_edge_op(
            solid, EDGE_GROUPS[self.group], self.kind, amount, self.label, scene.log
        )
        return scene


class Hollow(DslOp):
    """
    Hollow the part, leaving `wall_mm`, with the cavity opening on a named face.

    LINT RULE, NOT A PREFERENCE: the cavity must open in the print direction. A
    cavity opening downward creates a ceiling that needs support, and the whole
    reason to hollow a part is to save material without adding print time.
    """

    op: Literal["hollow"]
    wall_mm: float = Field(..., gt=0.2, le=100)
    opening: Anchor = Field("top_face", description="Which face the cavity opens through.")
    floor_mm: float | None = Field(
        None, gt=0, le=100, description="Solid floor under the cavity. Defaults to wall_mm."
    )

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("hollow")
        if self.opening not in FACE_FRAMES:
            raise DslError(
                "unknown opening %r. Legal: %s."
                % (self.opening, ", ".join(sorted(FACE_FRAMES)))
            )
        normal = FACE_FRAMES[self.opening][0]
        axis = AXIS_VECTOR[scene.print_axis]
        along = sum(a * b for a, b in zip(normal, axis))
        if along <= 0:
            raise DslError(
                "hollow: the cavity opens through %r, whose normal points %s, but "
                "the print axis is %s. A cavity opening against the print "
                "direction creates a ceiling that needs support. Open it through "
                "the face facing +%s instead."
                % (self.opening, normal, scene.print_axis, scene.print_axis)
            )

        floor = self.floor_mm if self.floor_mm is not None else self.wall_mm
        bb = solid.val().BoundingBox()
        smallest = min(bb.xlen, bb.ylen, bb.zlen)
        if 2 * self.wall_mm + 0.2 >= smallest:
            raise DslError(
                "hollow: wall_mm %.3f leaves no cavity - two walls plus clearance "
                "is %.3f mm and the part's smallest dimension is %.3f mm. Legal: "
                "wall_mm under %.3f."
                % (self.wall_mm, 2 * self.wall_mm + 0.2, smallest, (smallest - 0.2) / 2)
            )

        cavity = (
            cq.Workplane("XY")
            .box(bb.xlen - 2 * self.wall_mm, bb.ylen - 2 * self.wall_mm,
                 bb.zlen - floor + 1.0, centered=(True, True, False))
            .translate((
                (bb.xmin + bb.xmax) / 2.0,
                (bb.ymin + bb.ymax) / 2.0,
                bb.zmin + floor,
            ))
        )
        scene.solid = solid.cut(cavity)
        scene.features["hollow wall"] = self.wall_mm
        return scene


class Mirror(DslOp):
    """
    Reflect the part and keep both halves.

    Most things people ask for are symmetrical, and building half of something
    and mirroring it is both less to describe and impossible to get subtly
    lopsided. `plane` names the plane the part is reflected ACROSS: "yz" swaps
    left and right, "xz" swaps front and back, "xy" swaps top and bottom.
    """

    op: Literal["mirror"]
    plane: Literal["yz", "xz", "xy"] = Field(
        "yz", description="Reflect across this plane. yz swaps left/right."
    )
    at_mm: float = Field(
        0.0, ge=-2000, le=2000,
        description="Where the mirror plane sits along its normal. 0 is through the origin.",
    )
    keep_original: bool = Field(
        True, description="True keeps both halves. False replaces the part with its reflection."
    )

    def apply(self, scene: Scene) -> Scene:
        solid = scene.require_solid("mirror")
        normal = {"yz": (1, 0, 0), "xz": (0, 1, 0), "xy": (0, 0, 1)}[self.plane]
        base = tuple(c * self.at_mm for c in normal)
        flipped = solid.mirror(mirrorPlane=MIRROR_PLANES[self.plane], basePointVector=base)
        if not self.keep_original:
            scene.solid = flipped
            return scene
        joined = solid.union(flipped)
        if _volume(joined) <= 1e-6:
            raise DslError("mirror produced nothing - the union of the two halves is empty")
        scene.solid = joined
        return scene


# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------


class PatternLinear(DslOp):
    """Repeat one nested op along a straight line."""

    op: Literal["pattern_linear"]
    count: int = Field(..., ge=1, le=500)
    dx_mm: float = Field(0.0, ge=-1000, le=1000)
    dy_mm: float = Field(0.0, ge=-1000, le=1000)
    dz_mm: float = Field(0.0, ge=-1000, le=1000)
    step: "AnyOp" = Field(..., description="The op to repeat.")

    def apply(self, scene: Scene) -> Scene:
        if self.count > 1 and self.dx_mm == self.dy_mm == self.dz_mm == 0:
            raise DslError(
                "pattern_linear repeats %d times with no step, so every copy "
                "lands on the last. Set dx_mm, dy_mm or dz_mm." % self.count
            )
        for i in range(self.count):
            shifted = self.step.model_copy(deep=True)
            _shift_op(shifted, i * self.dx_mm, i * self.dy_mm, i * self.dz_mm)
            scene = shifted.apply(scene)
        return scene


class PatternPolar(DslOp):
    """Repeat one nested op around the Z axis."""

    op: Literal["pattern_polar"]
    count: int = Field(..., ge=1, le=500)
    radius_mm: float = Field(..., ge=0, le=1000)
    start_deg: float = Field(0.0, ge=-360, le=360)
    total_deg: float = Field(360.0, gt=0, le=360)
    centre_x_mm: float = Field(0.0, ge=-1000, le=1000)
    centre_y_mm: float = Field(0.0, ge=-1000, le=1000)
    turn_with_angle: bool = Field(
        False,
        description=(
            "True also turns each copy to face outward, which is what gear "
            "teeth, fan blades and knurling need. False keeps every copy "
            "upright, which is what a ring of screw holes needs."
        ),
    )
    step: "AnyOp" = Field(..., description="The op to repeat.")

    def apply(self, scene: Scene) -> Scene:
        full = abs(self.total_deg - 360.0) < 1e-9
        divisor = self.count if full else max(self.count - 1, 1)
        for i in range(self.count):
            deg = self.start_deg + self.total_deg * i / divisor
            angle = math.radians(deg)
            shifted = self.step.model_copy(deep=True)
            if self.turn_with_angle:
                if not isinstance(shifted, Creator):
                    raise DslError(
                        "pattern_polar: turn_with_angle needs a shape it can "
                        "turn, and %r is not one. Legal: %s."
                        % (getattr(shifted, "op", "?"), ", ".join(CREATOR_NAMES))
                    )
                shifted.rotate_axis = "z"
                shifted.rotate_deg = _wrap_deg(shifted.rotate_deg + deg)
            _shift_op(
                shifted,
                self.centre_x_mm + self.radius_mm * math.cos(angle),
                self.centre_y_mm + self.radius_mm * math.sin(angle),
                0.0,
            )
            scene = shifted.apply(scene)
        return scene


def _wrap_deg(deg: float) -> float:
    """Keep an angle inside the -360..360 the field allows."""
    return math.fmod(deg, 360.0)


def _shift_op(op: DslOp, dx: float, dy: float, dz: float) -> None:
    """
    Offset whatever positional fields an op has.

    Every creator shares one set of position fields now, so this is no longer
    a per-op lookup table that a new op could be forgotten from - which is what
    it used to be, and it was already wrong for two of them.
    """
    if isinstance(op, Creator):
        op.x_mm += dx
        op.y_mm += dy
        op.z_mm += dz
    elif isinstance(op, (Pocket, EmbossPolygon, EmbossText)):
        op.u_mm += dx
        op.v_mm += dy
    else:
        raise DslError(
            "pattern: op %r cannot be patterned - it has no position to offset. "
            "Pattern a shape or a face feature instead."
            % getattr(op, "op", type(op).__name__)
        )


AnyOp = Annotated[
    Union[
        RoundedPrism, Disc, Cone, Sphere, Wedge, ProfileExtrude, ArcRod,
        Loft, FreeJoint,
        Pocket, EmbossPolygon, EmbossText, BlendEdges, Hollow, Mirror,
        PatternLinear, PatternPolar,
    ],
    Field(discriminator="op"),
]

PatternLinear.model_rebuild()
PatternPolar.model_rebuild()

CREATOR_NAMES = (
    "rounded_prism", "disc", "cone", "sphere", "wedge", "profile_extrude", "arc_rod",
    "loft", "free_joint",
)

OP_NAMES = CREATOR_NAMES + (
    "pocket", "emboss_polygon", "emboss_text", "blend_edges", "hollow", "mirror",
    "pattern_linear", "pattern_polar",
)


def parse_op(data: dict[str, Any]) -> DslOp:
    """Validate one op dict into its model, with a readable error."""
    from pydantic import TypeAdapter, ValidationError

    from bpcad.spec.schema import format_validation_error

    if "op" not in data:
        raise DslError(
            "every op needs an `op` field naming the operation. Legal: %s."
            % ", ".join(OP_NAMES)
        )
    if data["op"] not in OP_NAMES:
        raise DslError(
            "unknown op %r. Legal: %s." % (data["op"], ", ".join(OP_NAMES))
        )
    try:
        return TypeAdapter(AnyOp).validate_python(data)
    except ValidationError as exc:
        raise DslError(format_validation_error(exc, "op %r is invalid:" % data["op"])) from exc


def run_ops(ops: list[dict[str, Any]], print_axis: str = "z") -> Scene:
    """Run a list of op dicts in order and return the finished scene."""
    scene = Scene(print_axis=print_axis)
    for i, data in enumerate(ops):
        op = parse_op(data)
        already = len(scene.log.repairs)
        try:
            scene = op.apply(scene)
            # An op cannot know where it sits in the list; this is the only
            # place that does, so any repair it just recorded is stamped here.
            for repair in scene.log.repairs[already:]:
                repair["index"] = i
        except DslError:
            raise
        except Exception as exc:
            raise DslError(
                "op %d (%r) failed: %s" % (i, data.get("op"), exc)
            ) from exc
    if scene.solid is None:
        raise DslError("the op list produced no geometry")
    return scene
