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
                "The first op must be one that creates geometry: rounded_prism, "
                "disc or arc_rod." % op_name
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


class DslOp(BaseModel):
    """Base for every operation. Subclasses implement apply()."""

    model_config = ConfigDict(extra="forbid")

    def apply(self, scene: Scene) -> Scene:  # pragma: no cover - abstract
        raise NotImplementedError


# ---------------------------------------------------------------------------
# creators
# ---------------------------------------------------------------------------


class RoundedPrism(DslOp):
    """A rectangular prism with rounded vertical corners. The usual starting point."""

    op: Literal["rounded_prism"]
    width_mm: float = Field(..., gt=0, le=1000, description="X extent.")
    depth_mm: float = Field(..., gt=0, le=1000, description="Y extent.")
    height_mm: float = Field(..., gt=0, le=1000, description="Z extent, from z=0 up.")
    corner_r_mm: float = Field(0.0, ge=0, le=500, description="Vertical corner radius.")

    def apply(self, scene: Scene) -> Scene:
        solid = rrect(
            self.width_mm, self.depth_mm, self.corner_r_mm,
            -self.depth_mm / 2.0, self.height_mm,
        )
        scene.solid = solid if scene.solid is None else scene.solid.union(solid)
        return scene


class Disc(DslOp):
    """A cylinder standing on z0, axis along Z."""

    op: Literal["disc"]
    diameter_mm: float = Field(..., gt=0, le=1000)
    height_mm: float = Field(..., gt=0, le=1000)
    x_mm: float = Field(0.0, ge=-1000, le=1000)
    y_mm: float = Field(0.0, ge=-1000, le=1000)
    z_mm: float = Field(0.0, ge=-1000, le=1000, description="Base height.")

    def apply(self, scene: Scene) -> Scene:
        solid = _disc(self.diameter_mm, self.x_mm, self.y_mm, self.height_mm, z0=self.z_mm)
        scene.solid = solid if scene.solid is None else scene.solid.union(solid)
        return scene


class ArcRod(DslOp):
    """
    A rod following a circular arc, lying in the XY plane and extruded in Z.

    Built as an annulus trimmed to a half-plane, which is how the reference
    keyring's fused handle is made: it gives exactly the render's arc without
    a sweep or a revolve.
    """

    op: Literal["arc_rod"]
    arc_r_mm: float = Field(..., gt=0, le=1000, description="Centreline radius.")
    rod_d_mm: float = Field(..., gt=0, le=500, description="Rod section diameter.")
    thickness_mm: float = Field(..., gt=0, le=1000, description="Extrusion in Z.")
    centre_x_mm: float = Field(0.0, ge=-1000, le=1000)
    centre_y_mm: float = Field(0.0, ge=-1000, le=1000)
    z_mm: float = Field(0.0, ge=-1000, le=1000)
    trim_below_y_mm: float | None = Field(
        None, description="Keep only the part of the arc above this y. Omit to keep the ring."
    )

    def apply(self, scene: Scene) -> Scene:
        if self.rod_d_mm / 2.0 >= self.arc_r_mm:
            raise DslError(
                "arc_rod: rod_d_mm %.3f is too thick for arc_r_mm %.3f - the "
                "inner radius would be negative and the rod would close into a "
                "disc. Legal: rod_d_mm under %.3f."
                % (self.rod_d_mm, self.arc_r_mm, 2 * self.arc_r_mm)
            )
        outer = _disc(2 * (self.arc_r_mm + self.rod_d_mm / 2.0),
                      self.centre_x_mm, self.centre_y_mm, self.thickness_mm, z0=self.z_mm)
        inner = _disc(2 * (self.arc_r_mm - self.rod_d_mm / 2.0),
                      self.centre_x_mm, self.centre_y_mm, self.thickness_mm, z0=self.z_mm)
        ring = outer.cut(inner)
        if self.trim_below_y_mm is not None:
            from bpcad.build.helpers import clip

            ring = clip(ring, "y", self.trim_below_y_mm, keep="above")
        scene.solid = ring if scene.solid is None else scene.solid.union(ring)
        return scene


# ---------------------------------------------------------------------------
# modifiers
# ---------------------------------------------------------------------------


def _place_on_anchor(scene: Scene, anchor: str, local: cq.Workplane) -> cq.Workplane:
    """Move a solid built around the local origin onto a named anchor face."""
    plane = scene.anchor_plane(anchor)
    moved = local.val().moved(cq.Location(plane))
    return cq.Workplane("XY").newObject([moved])


class Pocket(DslOp):
    """
    Cut a rounded rectangular recess into a named face.

    Positive `depth_mm` goes INTO the part. Position is in the face's own
    coordinates: u to the right and v up, both measured from the face centre.
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
    step: "AnyOp" = Field(..., description="The op to repeat.")

    def apply(self, scene: Scene) -> Scene:
        full = abs(self.total_deg - 360.0) < 1e-9
        divisor = self.count if full else max(self.count - 1, 1)
        for i in range(self.count):
            angle = math.radians(self.start_deg + self.total_deg * i / divisor)
            shifted = self.step.model_copy(deep=True)
            _shift_op(
                shifted,
                self.centre_x_mm + self.radius_mm * math.cos(angle),
                self.centre_y_mm + self.radius_mm * math.sin(angle),
                0.0,
            )
            scene = shifted.apply(scene)
        return scene


def _shift_op(op: DslOp, dx: float, dy: float, dz: float) -> None:
    """
    Offset whatever positional fields an op has.

    Deliberately explicit rather than clever: an op that gains a new position
    field and is not listed here will pattern in the wrong place, and a loud
    failure beats a silently misplaced copy.
    """
    if isinstance(op, Disc):
        op.x_mm += dx
        op.y_mm += dy
        op.z_mm += dz
    elif isinstance(op, ArcRod):
        op.centre_x_mm += dx
        op.centre_y_mm += dy
        op.z_mm += dz
    elif isinstance(op, (Pocket, EmbossPolygon)):
        op.u_mm += dx
        op.v_mm += dy
    elif isinstance(op, RoundedPrism):
        raise DslError(
            "pattern: rounded_prism has no position of its own, so patterning it "
            "would stack every copy in the same place. Pattern a disc, a pocket "
            "or an emboss_polygon instead."
        )
    else:
        raise DslError(
            "pattern: op %r cannot be patterned - it has no position to offset."
            % getattr(op, "op", type(op).__name__)
        )


AnyOp = Annotated[
    Union[
        RoundedPrism, Disc, ArcRod, Pocket, EmbossPolygon,
        BlendEdges, Hollow, PatternLinear, PatternPolar,
    ],
    Field(discriminator="op"),
]

PatternLinear.model_rebuild()
PatternPolar.model_rebuild()

OP_NAMES = (
    "rounded_prism", "disc", "arc_rod", "pocket", "emboss_polygon",
    "blend_edges", "hollow", "pattern_linear", "pattern_polar",
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
        try:
            scene = op.apply(scene)
        except DslError:
            raise
        except Exception as exc:
            raise DslError(
                "op %d (%r) failed: %s" % (i, data.get("op"), exc)
            ) from exc
    if scene.solid is None:
        raise DslError("the op list produced no geometry")
    return scene
