"""
The bundle: everything a successful run leaves behind.

    parts/<name>/
      spec.yaml            the durable artifact, this is what gets reordered
      model.py             generated CadQuery, for inspection
      out/<name>.stl
      out/<name>.step
      out/<name>.3mf
      out/preview.png
      out/heightmap.png
      report.md
      regression.json
      run.json

report.md follows a fixed order, set by the brief: envelope and volume,
filament estimate, print orientation and whether supports are needed, the
feature-size table against the nozzle, assumptions, deliberate departures from
true scale, recommended slicer settings, and which model produced the spec.

The order is not arbitrary. Envelope first because it answers "will this fit on
the bed". Assumptions and departures BEFORE slicer settings because they are the
things a reader must not skip, and a reader who has got what they came for stops
reading.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

# Filament density, g/cm3. Used only for the estimate in the report, which is
# labelled as an estimate.
DENSITY_G_CM3 = {"pla": 1.24, "petg": 1.27, "tpu": 1.21}

# A 1.75 mm filament is 2.405 mm2 in section, so 1 cm3 is this many mm of it.
MM_PER_CM3_175 = 1000.0 / 2.405


def write_spec(spec, path: Path) -> Path:
    """Write spec.yaml, the durable artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = spec.model_dump(exclude_none=True)
    # Empty collections are noise in a file meant to be read and edited.
    for key in ("ops", "assumptions", "scale_departures", "params"):
        if key in data and not data[key]:
            data.pop(key)
    path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    return path


def write_model_py(spec, path: Path) -> Path:
    """
    Write model.py: a runnable script that rebuilds this part.

    For a template spec this is NOT the template's source - it is a short script
    that calls the template with these parameters. That is the honest thing to
    write: the geometry really is produced by the template, and pasting a copy
    of it here would create a second version to drift out of step with the
    first.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if spec.level == 3:
        header = '"""%s - level 3, raw CadQuery. REVIEW REQUIRED."""\n\n' % spec.name
        path.write_text(header + (spec.script or ""))
        return path

    lines = [
        '"""',
        "%s - regenerate this part." % spec.name,
        "",
        "Written by bpcad for inspection. The geometry comes from the template,",
        "not from a copy of it pasted here - a second copy would drift.",
        "",
        "    python model.py",
        '"""',
        "",
        "import cadquery as cq",
        "",
        "from bpcad.build.compile import compile_spec, load_spec",
        "",
        "",
        "def main():",
        '    spec, base_dir = load_spec("spec.yaml")',
        "    result = compile_spec(spec, base_dir=base_dir)",
        '    cq.exporters.export(result.print_solid, "%s.stl",' % spec.name,
        "                        tolerance=%s, angularTolerance=%s)"
        % (spec.stl_tolerance or 0.005, spec.stl_angular_tolerance or 0.05),
        "    bb = result.print_solid.val().BoundingBox()",
        '    print("%.2f x %.2f x %.2f mm" % (bb.xlen, bb.ylen, bb.zlen))',
        "",
        "",
        'if __name__ == "__main__":',
        "    main()",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def filament_estimate(volume_cm3: float, material: str, infill: float = 1.0) -> tuple[float, float]:
    """
    Grams and metres of 1.75 mm filament. An ESTIMATE and labelled as one.

    Real usage depends on walls, infill pattern, supports and purge, none of
    which bpcad models. At 100% infill it is close; below that it is an upper
    bound.
    """
    density = DENSITY_G_CM3.get(material.strip().lower())
    if density is None:
        return (0.0, 0.0)
    grams = volume_cm3 * density * infill
    metres = volume_cm3 * infill * MM_PER_CM3_175 / 1000.0
    return (grams, metres)


def slicer_settings(spec, report, template_notes: tuple[str, ...] = ()) -> list[str]:
    """Recommended settings, derived from the spec and what verify found."""
    out = [
        "layer height   %.2f mm" % spec.layer_mm,
        "nozzle         %.2f mm" % spec.nozzle_mm,
        "material       %s" % spec.material.upper(),
        "orientation    as exported - do not rotate",
        "supports       %s" % ("required as oriented" if report.overhang.supports_needed else "none"),
    ]
    if report.mesh.body_count > 1:
        out.append(
            "print-in-place %d separate bodies, do not merge or union them"
            % report.mesh.body_count
        )
    out.extend(template_notes)
    return out


def write_report(
    spec,
    result,
    report,
    out_path: Path,
    model_used: str = "",
    machine: str = "",
    attempts: int = 0,
    elapsed_s: float = 0.0,
    template_notes: tuple[str, ...] = (),
    review_required: bool = False,
) -> Path:
    """Write report.md, in the order the brief sets."""
    m = report.mesh
    L: list[str] = []

    L.append("# %s" % spec.name)
    L.append("")
    if review_required:
        L.append("> **REVIEW REQUIRED** - this part was produced by raw CadQuery")
        L.append("> (level 3), not by a validated template. Check the geometry")
        L.append("> before printing it.")
        L.append("")

    # 1. envelope and volume
    L.append("## Envelope and volume")
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append("| Envelope | %.2f x %.2f x %.2f mm |" % m.bbox_mm)
    L.append("| Volume | %.3f cm3 |" % m.volume_cm3)
    L.append("| Watertight | %s |" % ("yes" if m.watertight else "NO"))
    L.append("| Separate bodies | %d |" % m.body_count)
    L.append("| Triangles | %d |" % m.face_count)
    L.append("")

    # 2. filament estimate
    grams, metres = filament_estimate(m.volume_cm3, spec.material)
    L.append("## Filament estimate")
    L.append("")
    if grams:
        L.append("Roughly **%.1f g** / **%.1f m** of 1.75 mm %s at 100%% infill."
                 % (grams, metres, spec.material.upper()))
        L.append("")
        L.append("An estimate from the solid volume. It does not model walls,")
        L.append("infill pattern, supports or purge, so treat it as an upper bound")
        L.append("below 100% infill.")
    else:
        L.append("No density on file for %r, so no estimate." % spec.material)
    L.append("")

    # 3. print orientation and supports
    o = report.overhang
    L.append("## Print orientation")
    L.append("")
    L.append("Build direction **%s**. Export is already in print orientation - do not rotate."
             % spec.print_axis.upper())
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append("| Supports needed | %s |" % ("YES" if o.supports_needed else "no"))
    L.append("| Worst overhang | %.1f deg from vertical |" % o.worst_overhang_deg)
    L.append("| Underside past %.0f deg | %.1f mm2 |" % (o.max_deg, o.overhang_area_mm2))
    L.append("| ...bridged by the layer above | %.1f mm2 |" % o.bridged_area_mm2)
    L.append("| ...falling further | %.1f mm2 |" % o.unsupported_area_mm2)
    L.append("| Bed contact | %.1f mm2 |" % o.bed_area_mm2)
    L.append("")
    if o.unsupported_area_mm2 > 0:
        L.append("A long drop may still be a **bridge** anchored on both sides, which")
        L.append("prints fine. This check measures the fall, not the span - look at")
        L.append("the section render before adding supports.")
        L.append("")

    # 4. feature sizes against the nozzle
    L.append("## Feature sizes")
    L.append("")
    if report.features is not None:
        f = report.features
        L.append("Against a %.2f mm nozzle, threshold %.2f mm." % (f.nozzle_mm, f.threshold_mm))
        L.append("")
        L.append("| Feature | Size (mm) | Status |")
        L.append("|---|---|---|")
        for c in f.checks:
            L.append("| %s | %.3f | %s |" % (c.name, c.value_mm, c.status))
        L.append("")
        if f.marginal:
            L.append("MARGINAL means it will print but is within 10% of the limit -")
            L.append("one tuning change away from not printing.")
            L.append("")
    else:
        L.append("This template declares no named features.")
        L.append("")

    # 5. assumptions
    L.append("## Assumptions")
    L.append("")
    if result.assumptions:
        L.append("These dimensions could **not** be measured. Each is a named")
        L.append("parameter standing in for something unknown.")
        L.append("")
        for a in result.assumptions:
            L.append("- **%s** = %s %s" % (a.name, a.value, a.units))
            L.append("  %s" % a.why)
        L.append("")
    else:
        L.append("None - every dimension in this part was measured or specified.")
        L.append("")

    # 6. deliberate departures from true scale
    L.append("## Departures from true scale")
    L.append("")
    if result.scale_departures:
        L.append("| Feature | Factor | True (mm) | Built (mm) | Why |")
        L.append("|---|---|---|---|---|")
        for sd in result.scale_departures:
            L.append("| %s | %.2fx | %.3f | %.3f | %s |"
                     % (sd.name, sd.factor, sd.true_mm, sd.used_mm, sd.why))
        L.append("")
    else:
        L.append("None - this part is at true scale throughout.")
        L.append("")

    # 7. recommended slicer settings
    L.append("## Recommended slicer settings")
    L.append("")
    for line in slicer_settings(spec, report, template_notes):
        L.append("- %s" % line)
    L.append("")

    # 8. which model produced the spec
    L.append("## Provenance")
    L.append("")
    if model_used:
        L.append("Spec written by **%s** on machine **%s**, %d attempt(s), %.1fs."
                 % (model_used, machine, attempts, elapsed_s))
        L.append("")
        L.append("The model filled in a validated specification. It did not write")
        L.append("CAD code - the geometry comes from a template in bpcad, and every")
        L.append("number above was measured off the exported mesh.")
    else:
        L.append("Spec written by hand. No model was involved at any point.")
    L.append("")

    if result.log.lines():
        L.append("## Build log")
        L.append("")
        for line in result.log.lines():
            L.append("- %s" % line)
        L.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L))
    return out_path


def write_bundle(
    spec,
    result,
    report,
    stl: Path,
    part_dir: Path,
    model_used: str = "",
    machine: str = "",
    attempts: int = 0,
    elapsed_s: float = 0.0,
    render: bool = True,
) -> dict[str, Path]:
    """
    Write everything a successful run leaves behind. Returns what was written.

    A failure to render is recorded and does not lose the part: the STL and the
    spec are the things that matter, and a missing preview is not worth
    discarding a good build over.
    """
    import cadquery as cq

    from bpcad.spec import registry
    from bpcad.verify.regression import baseline_path_for, check_regression

    out_dir = part_dir / "out"
    written: dict[str, Path] = {"stl": stl}

    written["spec"] = write_spec(spec, part_dir / "spec.yaml")
    written["model_py"] = write_model_py(spec, part_dir / "model.py")

    for ext in ("step", "3mf"):
        try:
            target = out_dir / ("%s.%s" % (spec.name, ext))
            cq.exporters.export(result.print_solid, str(target))
            written[ext] = target
        except Exception as exc:
            result.log.notes.append("%s export failed: %s" % (ext.upper(), exc))

    if render:
        from bpcad.render import views as V
        from bpcad.verify.mesh import load_mesh

        try:
            mesh = load_mesh(stl)
            written["preview"] = V.render_view_to(mesh, out_dir / "preview.png")
            written["heightmap"] = V.height_map_image(
                mesh, out_dir / "heightmap.png", axis=spec.print_axis
            )
            written["section"] = V.section(mesh, out_dir / "section.png", axis="y")
        except Exception as exc:
            result.log.notes.append("render failed: %s" % exc)

    notes: tuple[str, ...] = ()
    if spec.template:
        try:
            notes = registry.get(spec.template).print_notes
        except Exception:
            notes = ()

    written["report"] = write_report(
        spec, result, report, part_dir / "report.md",
        model_used=model_used, machine=machine, attempts=attempts,
        elapsed_s=elapsed_s, template_notes=notes,
        review_required=any("REVIEW REQUIRED" in n for n in result.log.notes),
    )

    regression = check_regression(report.mesh, baseline_path_for(stl, part_dir))
    written["regression"] = Path(regression.baseline_path)

    return written
