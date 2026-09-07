# bowl

## Envelope and volume

| | |
|---|---|
| Envelope | 139.98 x 139.98 x 60.00 mm |
| Volume | 93.760 cm3 |
| Watertight | yes |
| Separate bodies | 1 |
| Triangles | 89204 |

## Filament estimate

Roughly **119.1 g** / **39.0 m** of 1.75 mm PETG at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | no |
| Worst overhang | 14.7 deg from vertical |
| Underside past 45 deg | 0.0 mm2 |
| ...bridged by the layer above | 0.0 mm2 |
| ...falling further | 0.0 mm2 |
| Bed contact | 11308.6 mm2 |

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| rim round | 1.200 | PASS |
| floor | 2.000 | PASS |
| wall | 3.000 | PASS |

## Assumptions

None - every dimension in this part was measured or specified.

## Departures from true scale

None - this part is at true scale throughout.

## Recommended slicer settings

- printer        Creality i7  (260 x 260 x 255 mm)
- layer height   0.20 mm
- nozzle         0.40 mm
- material       PETG
- orientation    as exported - do not rotate
- supports       none
- Orientation: standing upright, exactly as modelled. The cavity opens upward, so there is nothing to support.
- No supports. If the profile needed them the spec would have been refused - the wall lean is checked against 45 degrees.
- Vase mode / spiralised outer contour suits this well if the wall is a single extrusion wide and there are no drainage holes.
- PETG for anything that holds water. PLA is fine dry and will soften in a hot car or a dishwasher.
- 3 walls minimum. On a thin turned wall the walls ARE the part.

## Provenance

Spec written by **qwen2.5-coder:7b** on machine **laptop**, 1 attempt(s), 266.7s.

The model filled in a validated specification. It did not write
CAD code - the geometry comes from a template in bpcad, and every
number above was measured off the exported mesh.

## Build log

- rim                      fillet 1.20 mm
- outer wall leans 14.7 degrees from vertical at its steepest (45 is the limit for printing without support)
