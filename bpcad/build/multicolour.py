"""
Splitting a multi-body part into one file per colour.

WHY NOT A COLOURED 3MF
----------------------
CadQuery cannot write one. Its 3MF export carries geometry only, and the single
format in reach that does carry colour is VRML, which no slicer will print.

That turns out not to matter, because a coloured 3MF is not what a
multi-material printer wants anyway. Creality Print, Orca and PrusaSlicer all
work the same way: you load the objects, and you assign a filament to each. So
this writes ONE STL PER BODY, named for what the body is, and the report says
which filament goes with which. "roof.stl in the second colour" is a usable
instruction; a hex value buried in a file format is not.

A named body also survives the round trip. Open the folder in six months and
`birdhouse_roof.stl` still says what it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Suggested filament slots, in the order bodies are usually loaded. These are
# slot numbers, not colours - the printer decides what is actually in them.
SLOT_NAMES = ("first", "second", "third", "fourth")


@dataclass
class ColourPlan:
    """Which body goes in which filament slot, and where each file is."""

    files: dict[str, Path] = field(default_factory=dict)      # role -> stl
    slots: dict[str, int] = field(default_factory=dict)       # role -> 1-based
    notes: list[str] = field(default_factory=list)

    @property
    def colours(self) -> int:
        return len(set(self.slots.values()))

    def summary(self) -> list[str]:
        out = []
        for role, slot in sorted(self.slots.items(), key=lambda kv: kv[1]):
            out.append("  filament %d   %-14s %s"
                       % (slot, role, self.files[role].name))
        return out + ["  " + n for n in self.notes]


def plan_slots(roles: tuple[str, ...]) -> dict[str, int]:
    """
    Assign filament slots to body roles.

    Bodies that are the same KIND share a slot - four blades of a vent are one
    colour, not four - because the point of a slot is a filament, and loading
    four identical blades into four slots wastes the printer's whole capacity
    on a part that wanted two colours.
    """
    slots: dict[str, int] = {}
    kinds: dict[str, int] = {}
    for role in roles:
        # blade_1, blade_2 ... are all "blade".
        kind = role.rsplit("_", 1)[0] if role.rsplit("_", 1)[-1].isdigit() else role
        if kind not in kinds:
            kinds[kind] = len(kinds) + 1
        slots[role] = kinds[kind]
    return slots


def split_bodies(
    stl_path: str | Path,
    roles: tuple[str, ...],
    out_dir: str | Path,
    stem: str,
) -> ColourPlan:
    """
    Write one STL per body, named for its role.

    Bodies come back from the mesh in an arbitrary order, so they are sorted
    LEFT TO RIGHT along X - which is the order the print layout puts them in,
    and the order the roles are declared. Without that the roof could be named
    the box, and the report would tell you to print the wrong thing in the
    wrong colour.
    """
    import trimesh

    from bpcad.verify.mesh import load_mesh

    plan = ColourPlan()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    mesh = load_mesh(stl_path)
    pieces = mesh.split(only_watertight=False) if mesh.body_count > 1 else [mesh]
    if len(pieces) != len(roles):
        plan.notes.append(
            "the part has %d bodies and the template named %d - not split, "
            "because a wrong name is worse than no name"
            % (len(pieces), len(roles))
        )
        return plan

    ordered = sorted(pieces, key=lambda m: float(m.bounds[0][0]))

    # Left-to-right ordering only identifies a body if the bodies really are
    # laid out left to right. The louvre vent's tie bar runs ACROSS all four
    # blades, so it sorts among them and every name after it is wrong - and a
    # file called roof.stl that is not the roof is worse than no file at all.
    for earlier, later in zip(ordered, ordered[1:]):
        if float(later.bounds[0][0]) < float(earlier.bounds[1][0]) - 1e-6:
            plan.notes.append(
                "the bodies overlap along X, so left-to-right does not say "
                "which is which - not split, because a wrong name is worse "
                "than no name"
            )
            return plan

    plan.slots = plan_slots(roles)

    for role, piece in zip(roles, ordered):
        target = out / ("%s_%s.stl" % (stem, role))
        piece.export(str(target))
        plan.files[role] = target

    if plan.colours > 1:
        plan.notes.append(
            "load these as separate objects and assign a filament to each - "
            "that is how a multi-material slicer expects them, and it is why "
            "they are separate files rather than one coloured model"
        )
    return plan
