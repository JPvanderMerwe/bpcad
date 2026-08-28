"""
Does the part fit on the printer?

The most basic printability question there is, and it was missing. A refinement
asked for "a more complex birdhouse" and produced a 1248 x 590 x 600 mm print
layout - eighteen kilograms of filament - and every other check passed it,
because it was a perfectly sound object that simply would not fit on any
machine in the building.

CHECKED IN PRINT ORIENTATION, and that matters: a two-piece part laid out side
by side is wider than either piece, so the assembled size is the wrong thing to
measure. The layout is what goes on the bed.

The part is tried in both flat rotations, because a 300 x 100 part fits a
220 x 220 bed one way round and not the other, and a checker that only tries
one is wrong half the time.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _one_fits(size: tuple[float, float, float],
              bed: tuple[float, float, float]) -> bool:
    """One piece, tried both ways round on the bed."""
    w, d, h = (float(v) for v in size)
    bw, bd, bh = bed
    return h <= bh and ((w <= bw and d <= bd) or (d <= bw and w <= bd))


@dataclass
class BedReport:
    part_mm: tuple[float, float, float]
    bed_mm: tuple[float, float, float]
    fits: bool
    rotated: bool = False
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_bed(
    part_mm: tuple[float, float, float],
    bed_mm: tuple[float, float, float],
    snug_fraction: float = 0.95,
    body_sizes: list[tuple[float, float, float]] | None = None,
) -> BedReport:
    """
    Whether the print layout fits the build volume.

    A LAYOUT THAT DOES NOT FIT IS NOT THE SAME AS A PART THAT CANNOT BE MADE.
    A birdhouse and its roof laid side by side are 288 mm across, over a 220 mm
    bed - but they are two separate pieces and each fits easily, so the answer
    is "print them in two goes", not "impossible". A single 600 mm-tall object
    is impossible. Passing `body_sizes` lets this tell them apart; without it,
    anything oversized is treated as a failure, which is the safe assumption.

    Height is not rotatable - the part prints the way it was oriented, and this
    project keeps print orientation deliberate. Width and depth are tried both
    ways round, because that costs nothing and a bed is usually square-ish.
    """
    pw, pd, ph = (float(v) for v in part_mm)
    bw, bd, bh = (float(v) for v in bed_mm)

    fits_direct = pw <= bw and pd <= bd
    fits_turned = pd <= bw and pw <= bd
    fits = (fits_direct or fits_turned) and ph <= bh

    report = BedReport(
        part_mm=(pw, pd, ph), bed_mm=(bw, bd, bh),
        fits=fits, rotated=(not fits_direct and fits_turned),
    )

    if not fits:
        over = []
        if not (fits_direct or fits_turned):
            over.append("footprint %.0f x %.0f mm on a %.0f x %.0f mm bed"
                        % (pw, pd, bw, bd))
        if ph > bh:
            over.append("%.0f mm tall in a %.0f mm build height" % (ph, bh))

        # Do the individual pieces fit, even though the layout does not?
        pieces_fit = bool(body_sizes) and len(body_sizes) > 1 and all(
            _one_fits(size, (bw, bd, bh)) for size in body_sizes
        )
        if pieces_fit:
            report.fits = True
            report.warnings.append(
                "the %d pieces do not fit the bed all at once (%s), but each "
                "one fits on its own - print them in separate runs"
                % (len(body_sizes), "; ".join(over))
            )
        else:
            report.problems.append(
                "this does not fit the printer: %s. It is a sound part, it just "
                "cannot be made on this machine - make it smaller, or split it."
                % "; ".join(over)
            )
        return report

    if report.rotated:
        report.warnings.append(
            "it fits only turned 90 degrees on the bed (%.0f x %.0f mm on "
            "%.0f x %.0f mm) - rotate it in the slicer" % (pw, pd, bw, bd)
        )

    snug = max(pw / bw, pd / bd, ph / bh)
    if snug > snug_fraction:
        report.warnings.append(
            "it fills %.0f%% of the build volume in its longest direction - "
            "check your printer's real usable area, which is often smaller "
            "than the number on the box" % (100 * snug)
        )
    return report
