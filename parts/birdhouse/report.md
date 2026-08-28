# birdhouse

## Envelope and volume

| | |
|---|---|
| Envelope | 120.00 x 100.00 x 145.00 mm |
| Volume | 1668.731 cm3 |
| Watertight | yes |
| Separate bodies | 1 |
| Triangles | 2716 |

## Filament estimate

Roughly **2119.3 g** / **693.9 m** of 1.75 mm PETG at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | YES |
| Worst overhang | 90.0 deg from vertical |
| Underside past 45 deg | 1397.8 mm2 |
| ...bridged by the layer above | 0.0 mm2 |
| ...falling further | 1397.8 mm2 |
| Bed contact | 11914.1 mm2 |

A long drop may still be a **bridge** anchored on both sides, which
prints fine. This check measures the fall, not the span - look at
the section render before adding supports.

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| entrance | 32.000 | PASS |

## Assumptions

None - every dimension in this part was measured or specified.

## Departures from true scale

None - this part is at true scale throughout.

## Recommended slicer settings

- layer height   0.20 mm
- nozzle         0.40 mm
- material       PETG
- orientation    as exported - do not rotate
- supports       required as oriented

## Provenance

Spec written by **qwen2.5-coder:7b** on machine **laptop**, 2 attempt(s), 220.8s.

The model filled in a validated specification. It did not write
CAD code - the geometry comes from a template in bpcad, and every
number above was measured off the exported mesh.

## Build log

- roof_fillet              fillet 2.00 mm
