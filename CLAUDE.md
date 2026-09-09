# CLAUDE.md - working rules for bpcad

These are not style preferences. Most of them are a bug that cost real
debugging time, written down so it does not happen twice.

## Process

1. **Open every response with UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS.**
   No edits before stating UNDERSTOOD.
2. **Complete file rebuilds, not patches.** Never "change this line".
3. **Change only what was asked.** The request is the exact scope. Zero
   adjacent edits.
4. **Nothing gets committed or pushed without the literal word `push`.**
5. **Try every automated path before asking for a manual step.**
6. **Honest feedback, no flattery.** Flag flawed reasoning and needlessly
   negative reasoning alike. Back claims with evidence.
7. **Plain language** unless technical terms are asked for.
8. **Build phase by phase.** Run the phase's acceptance criteria, show the
   output, stop. Do not start the next phase unsolicited.
9. **Never guess.** If a dimension, tolerance or API signature is not certain,
   ask or check the source. Do not invent one.

## Architecture

10. **Local by default, remote only by explicit opt-in.** Inference runs on
    loopback unless someone has deliberately configured otherwise.
    `assert_local_endpoint` stays, and a non-loopback host must be named in
    `allowed_model_hosts` in config - never reached by silent fallback, never
    by an environment variable, never because loopback was down. A host that
    was not opted into raises `NonLocalEndpointError` at construction, as it
    always did.

    **The system must still work with no network at all.** That is not
    sentiment about privacy, it is the reason the program is trustworthy: a
    build that only succeeds when a server answers is a build you cannot
    repeat. Every part in `parts/` must remain rebuildable offline from its
    `spec.yaml`.

    Backends: `ollama` and `null` locally. A remote backend is allowed when
    the hosted product needs one, under the same opt-in rule and the same
    spec contract - it fills a validated spec, it does not write CAD code.

    *Changed 2026-08-31 on the owner's explicit decision to build a hosted,
    phone-reachable product. The previous rule said "no hosted endpoint,
    ever".*
11. **The system must stay fully usable with zero model.** `spec.yaml` is the
    durable artifact. Never put logic in the agent layer that is not reachable
    from a spec file.
12. **The model does not write CAD code.** It fills in a validated spec.
    Level 3 (raw CadQuery) is off by default, capped at one attempt, and
    anything it produces is marked REVIEW REQUIRED.

## Measurement

13. **Measure, never estimate.** Any dimension derived from an image comes from
    `measure/`, not from an eyeball read.
14. **Unmeasurable dimensions become named parameters marked ASSUMPTION** and
    appear in the report under a heading that says so.
15. **Report every deliberate departure from true scale with its numeric
    factor.** For example: handle section 2.67x oversize because true scale
    falls below the nozzle width.
16. **Fits return residuals.** A circle fit without its residual is just a
    number. The residual is what proves the source really was a circular arc.

## Geometry

17. **`isValid()` is not proof.** A chamfer once produced a solid that reported
    valid and then broke every subsequent boolean. Probe with a real throwaway
    boolean: `probe(solid)`.
18. **Cosmetic edge operations are attempt-and-revert, applied last**, after
    every pocket is cut, and their outcome is recorded in the report. A failed
    fillet must never break a build or corrupt earlier detail.
19. **Fillet radius must be smaller than half the smallest dimension by a real
    margin of 0.03 mm**, not an epsilon. `h/2 - 0.001` produces degenerate
    faces or hard failure.
20. **`Workplane.revolve(angle, axisStart, axisEnd)` takes the axis in the
    workplane's LOCAL coordinates.** `.center(x, y)` moves the local origin onto
    the profile, putting the axis through it and making the revolve fail. Use
    `.moveTo(x, y)` so the origin stays on the axis.
21. **Print orientation and assembled orientation are separate functions.**
    Never derive one from the other by rotation - it put a part 1.2 mm off its
    mating face. Pattern: `build_x_core()` returns assembled, `build_x()`
    returns print orientation.
22. **Rounded at one end, square at the other: fillet all four corners**, extend
    the square end beyond the region of interest, and let the boolean trim the
    unwanted fillets away.
23. **Hollow cavities must open in the print direction.** A cavity opening
    downward creates a ceiling needing support. This is a lint rule, not a
    preference.
24. **STL export tolerance 0.005, angular 0.05.** Finer produces tens of
    thousands of degenerate facets and a non-watertight mesh. Verify
    watertightness after every export.

## Rendering

25. **No `matplotlib` `Poly3DCollection`.** It cannot depth-sort across
    interpenetrating parts and renders straight through a shell. Use the
    z-buffer rasteriser.
26. **Verify the z-test direction of any renderer against a deliberately
    asymmetric part.** The first rasteriser rendered the back of the device and
    it was not obvious.
27. **The height map is the primary geometry-verification visual**, not the
    shaded render. A flat-shaded renderer cannot show a recess whose floor
    shares a normal with the surrounding face.
28. **No part is done until `bpcad verify` passes and a height map has been
    generated and looked at.**

## Config

29. **A value with no measured source is written `"UNSET"` and reading it
    raises.** bpcad does not substitute a plausible number. A wrong tolerance is
    worse than no tolerance.
30. **`reference/` is read-only.** It holds working, verified code and it is the
    source of truth for the algorithms. Port and generalise it; do not rewrite
    it and do not "improve" the algorithms. Where it is generalised, keep the
    existing behaviour as the default and prove equivalence with a test.

## Coverage

31. **A template is an optimisation, never the boundary of the product.**
    bpcad is a parametric modeller you talk to. It is not a template catalogue
    with a chat box on the front, and any change that makes it more of one is
    the wrong change.

    So: **"no template fits" is never an acceptable end state.** It is the
    normal case. Most things a person wants have no template and never will -
    the catalogue is five entries and the space of parts is not. A template is
    a shortcut for a shape that comes up often enough to be worth pinning, with
    bounds a builder can enforce. Everything else has to be composed, and the
    composition path is the product rather than the fallback.

    Which means the DSL is the thing to invest in. When a request cannot be
    made, the fix is a missing OPERATION - a loft, a sweep along a path, a
    revolve of a drawn profile, a shell, a print-in-place joint, a pattern
    around a curve - not a missing template. Adding a template to close a gap a
    primitive should have closed is borrowing against the next request.

    This does not loosen rule 12. The model still does not write CAD code: it
    fills a validated spec, and the answer to a shape the spec cannot express
    is to teach the spec that shape, with bounds and a verifier, not to hand
    the model a Python prompt.

    *Written 2026-09-09, after "a mini articulated dragon that prints in place"
    exhausted level 1 in seconds because nothing in the catalogue claims a
    dragon. The measured geometry was never the problem - the same build
    produces an 80 x 40 x 6 mm plate whose bores measure 4.9998 mm at 59.998 mm
    centres, watertight, 0.0001% off the analytic volume. What it cannot do is
    describe a shape nobody wrote a template for.*
