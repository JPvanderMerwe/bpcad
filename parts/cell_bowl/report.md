# cell_bowl

## Envelope and volume

| | |
|---|---|
| Envelope | 179.92 x 179.92 x 70.00 mm |
| Volume | 68.043 cm3 |
| Watertight | yes |
| Separate bodies | 1 |
| Triangles | 105110 |

## Filament estimate

Roughly **86.4 g** / **28.3 m** of 1.75 mm PETG at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | YES |
| Worst overhang | 77.6 deg from vertical |
| Underside past 45 deg | 2575.0 mm2 |
| ...bridged by the layer above | 18.9 mm2 |
| ...falling further | 2556.1 mm2 |
| Bed contact | 6880.1 mm2 |

A long drop may still be a **bridge** anchored on both sides, which
prints fine. This check measures the fall, not the span - look at
the section render before adding supports.

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| rim round | 1.200 | PASS |
| wall | 2.600 | PASS |
| cell strut | 3.000 | PASS |
| floor | 3.900 | PASS |

## Assumptions

None - every dimension in this part was measured or specified.

## Departures from true scale

None - this part is at true scale throughout.

## Recommended slicer settings

- printer        Creality i7  (260 x 260 x 255 mm)
- layer height   0.24 mm
- nozzle         0.40 mm
- material       PETG
- orientation    as exported - do not rotate
- supports       required as oriented
- Orientation: standing upright, exactly as modelled. The cavity opens upward, so there is nothing to support.
- No supports. If the profile needed them the spec would have been refused - the wall lean is checked against 45 degrees.
- Vase mode / spiralised outer contour suits this well if the wall is a single extrusion wide and there are no drainage holes.
- PETG for anything that holds water. PLA is fine dry and will soften in a hot car or a dishwasher.
- 3 walls minimum. On a thin turned wall the walls ARE the part.

## Provenance

Spec written by hand. No model was involved at any point.

## Build log

- rim                      fillet 1.20 mm
- 108 cells cut, 62% of the patterned band is open, 3.0 mm struts
- outer wall leans 44.1 degrees from vertical at its steepest (45 is the limit for printing without support)
