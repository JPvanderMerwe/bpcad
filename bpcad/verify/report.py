"""
One report object, three renderings: text, json, markdown.

Everything a verify run learned lands in VerifyReport and nowhere else. If a
check needs to say something, it says it here, so the terminal output, the
--json output and report.md can never drift apart.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from bpcad.verify.features import FeatureReport
from bpcad.verify.mesh import MeshReport
from bpcad.verify.overhang import OverhangReport
from bpcad.verify.probe import SurfaceLevel
from bpcad.verify.regression import RegressionResult


@dataclass
class VerifyReport:
    path: str
    nozzle_mm: float
    print_axis: str
    mesh: MeshReport
    overhang: OverhangReport
    levels: list[SurfaceLevel] = field(default_factory=list)
    features: FeatureReport | None = None
    regression: RegressionResult | None = None
    material: str | None = None
    notes: list[str] = field(default_factory=list)

    # -- verdict -----------------------------------------------------------

    @property
    def problems(self) -> list[str]:
        """
        Things that make the part WRONG, not merely inconvenient.

        Needing support is deliberately NOT here. Plenty of good parts need it -
        the louvre vent reference is one, and its top rail bridges the aperture
        by design. Calling that FAIL is both untrue and corrosive: a verdict that
        cries wolf on a known-good part teaches you to ignore the verdict.

        The overhang findings are still reported in full, under warnings.
        """
        out = list(self.mesh.problems)
        if self.features is not None:
            out += [
                "feature %r is %.3f mm, below the %.2f mm the nozzle can resolve"
                % (c.name, c.value_mm, c.threshold_mm)
                for c in self.features.too_fine
            ]
        if self.regression is not None and self.regression.status == "changed":
            out += ["geometry changed against the stored baseline: "
                    + "; ".join(self.regression.differences)]
        return out

    @property
    def warnings(self) -> list[str]:
        """Worth knowing before printing, but not defects in the geometry."""
        out = list(self.overhang.problems)
        if self.features is not None:
            out += [
                "feature %r is %.3f mm, within 10%% of the %.2f mm limit - it "
                "will print, but it is one tuning change away from not printing"
                % (c.name, c.value_mm, c.threshold_mm)
                for c in self.features.marginal
            ]
        return out

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def verdict(self) -> str:
        if self.problems:
            return "FAIL"
        return "PASS, with warnings" if self.warnings else "PASS"

    # -- renderings --------------------------------------------------------

    def as_text(self) -> str:
        m = self.mesh
        L: list[str] = []
        L.append("%s   %s" % (self.verdict, self.path))
        L.append("")
        L.append("MESH")
        L.append("  watertight            %s" % _yn(m.watertight))
        L.append("  is a volume           %s" % _yn(m.is_volume))
        L.append("  winding consistent    %s" % _yn(m.winding_consistent))
        L.append("  separate bodies       %d" % m.body_count)
        L.append("  faces                 %d" % m.face_count)
        L.append("  degenerate faces      %d" % m.degenerate_faces)
        L.append("  volume                %.4f cm3" % m.volume_cm3)
        L.append("  envelope              %.2f x %.2f x %.2f mm" % m.bbox_mm)
        L.append("")

        L.append("SURFACE LEVELS facing +%s   (%d)" % (self.print_axis, len(self.levels)))
        for lv in self.levels:
            L.append("  %8.3f mm   %10.2f mm2" % (lv.height_mm, lv.area_mm2))
        L.append("")

        o = self.overhang
        L.append("OVERHANG   print axis %s, threshold %.0f deg from vertical" % (o.print_axis, o.max_deg))
        L.append("  worst overhang        %.1f deg" % o.worst_overhang_deg)
        L.append("  underside past angle  %.2f mm2  (%.2f%% of the part)"
                 % (o.overhang_area_mm2, 100.0 * o.overhang_fraction))
        L.append("    falls under %.2f mm  %.2f mm2   closed by the layer above"
                 % (o.max_bridge_gap_mm, o.bridged_area_mm2))
        L.append("    falls further       %.2f mm2   (%.2f%% of the part)"
                 % (o.unsupported_area_mm2, 100.0 * o.unsupported_fraction))
        L.append("  worst drop            %.2f mm" % o.max_drop_mm)
        L.append("  bed contact area      %.2f mm2" % o.bed_area_mm2)
        L.append("  supports needed       %s" % _yn(o.supports_needed))
        if o.unsupported_area_mm2 > 0.0:
            L.append("  NOTE: a long drop may still be a bridge anchored both sides.")
            L.append("        This check does not analyse span - look at the cutaway.")
        L.append("")

        if self.features is not None:
            f = self.features
            L.append("FEATURE SIZES against a %.2f mm nozzle (threshold %.2f mm)"
                     % (f.nozzle_mm, f.threshold_mm))
            for c in f.checks:
                L.append("  %-26s %7.3f mm   %s" % (c.name, c.value_mm, c.status))
            L.append("")

        if self.regression is not None:
            r = self.regression
            L.append("REGRESSION   %s" % r.status.upper())
            L.append("  baseline              %s" % r.baseline_path)
            L.append("  signature             %s" % r.signature.digest())
            for d in r.differences:
                L.append("  %s" % d)
            L.append("")

        if self.warnings:
            L.append("WARNINGS - printable, but know about these")
            for w in self.warnings:
                L.append("  - %s" % w)
            L.append("")

        if self.notes:
            L.append("NOTES")
            for n in self.notes:
                L.append("  %s" % n)
            L.append("")

        if self.problems:
            L.append("PROBLEMS")
            for p in self.problems:
                L.append("  - %s" % p)
        else:
            L.append("No problems found.")
        return "\n".join(L)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "verdict": self.verdict,
            "ok": self.ok,
            "nozzle_mm": self.nozzle_mm,
            "print_axis": self.print_axis,
            "material": self.material,
            "mesh": asdict(self.mesh),
            "overhang": asdict(self.overhang),
            "surface_levels": [asdict(lv) for lv in self.levels],
            "notes": list(self.notes),
            "warnings": self.warnings,
            "problems": self.problems,
        }
        data["overhang"]["supports_needed"] = self.overhang.supports_needed
        data["overhang"]["overhang_fraction"] = self.overhang.overhang_fraction
        data["overhang"]["unsupported_fraction"] = self.overhang.unsupported_fraction
        if self.features is not None:
            data["features"] = {
                "nozzle_mm": self.features.nozzle_mm,
                "threshold_mm": self.features.threshold_mm,
                "checks": [asdict(c) for c in self.features.checks],
            }
        if self.regression is not None:
            data["regression"] = {
                "status": self.regression.status,
                "baseline_path": self.regression.baseline_path,
                "signature": asdict(self.regression.signature),
                "digest": self.regression.signature.digest(),
                "baseline": asdict(self.regression.baseline) if self.regression.baseline else None,
                "differences": list(self.regression.differences),
            }
        return data

    def as_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def as_markdown(self) -> str:
        m = self.mesh
        L: list[str] = []
        L.append("# Verify report - %s" % self.path)
        L.append("")
        L.append("**%s**" % self.verdict)
        L.append("")
        L.append("## Envelope and volume")
        L.append("")
        L.append("| | |")
        L.append("|---|---|")
        L.append("| Envelope | %.2f x %.2f x %.2f mm |" % m.bbox_mm)
        L.append("| Volume | %.4f cm3 |" % m.volume_cm3)
        L.append("| Watertight | %s |" % _yn(m.watertight))
        L.append("| Separate bodies | %d |" % m.body_count)
        L.append("| Faces | %d |" % m.face_count)
        L.append("| Degenerate faces | %d |" % m.degenerate_faces)
        L.append("")

        o = self.overhang
        L.append("## Print orientation")
        L.append("")
        L.append("Print axis **%s**, overhang threshold %.0f degrees from vertical."
                 % (o.print_axis, o.max_deg))
        L.append("")
        L.append("| | |")
        L.append("|---|---|")
        L.append("| Worst overhang | %.1f deg |" % o.worst_overhang_deg)
        L.append("| Underside past threshold | %.2f mm2 |" % o.overhang_area_mm2)
        L.append("| ...falling under %.2f mm | %.2f mm2 |" % (o.max_bridge_gap_mm, o.bridged_area_mm2))
        L.append("| ...falling further | %.2f mm2 |" % o.unsupported_area_mm2)
        L.append("| Worst drop | %.2f mm |" % o.max_drop_mm)
        L.append("| Bed contact area | %.2f mm2 |" % o.bed_area_mm2)
        L.append("| Supports needed | %s |" % _yn(o.supports_needed))
        L.append("")

        L.append("## Surface levels facing +%s" % self.print_axis)
        L.append("")
        L.append("| Height (mm) | Area (mm2) |")
        L.append("|---|---|")
        for lv in self.levels:
            L.append("| %.3f | %.2f |" % (lv.height_mm, lv.area_mm2))
        L.append("")

        if self.features is not None:
            f = self.features
            L.append("## Feature sizes")
            L.append("")
            L.append("Against a %.2f mm nozzle, threshold %.2f mm."
                     % (f.nozzle_mm, f.threshold_mm))
            L.append("")
            L.append("| Feature | Size (mm) | Status |")
            L.append("|---|---|---|")
            for c in f.checks:
                L.append("| %s | %.3f | %s |" % (c.name, c.value_mm, c.status))
            L.append("")

        if self.regression is not None:
            r = self.regression
            L.append("## Regression")
            L.append("")
            L.append("Status **%s**, signature `%s`, baseline `%s`."
                     % (r.status, r.signature.digest(), r.baseline_path))
            if r.differences:
                L.append("")
                for d in r.differences:
                    L.append("- %s" % d)
            L.append("")

        if self.notes:
            L.append("## Notes")
            L.append("")
            for n in self.notes:
                L.append("- %s" % n)
            L.append("")

        L.append("## Problems")
        L.append("")
        if self.problems:
            for p in self.problems:
                L.append("- %s" % p)
        else:
            L.append("None.")
        return "\n".join(L)


def _yn(value: bool) -> str:
    return "yes" if value else "no"
