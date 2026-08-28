# birdhouse

## Envelope and volume

| | |
|---|---|
| Envelope | 708.00 x 350.00 x 400.00 mm |
| Volume | 4917.318 cm3 |
| Watertight | yes |
| Separate bodies | 2 |
| Triangles | 26976 |

## Filament estimate

Roughly **6245.0 g** / **2044.6 m** of 1.75 mm PETG at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | YES |
| Worst overhang | 90.0 deg from vertical |
| Underside past 45 deg | 214413.8 mm2 |
| ...bridged by the layer above | 0.0 mm2 |
| ...falling further | 214413.8 mm2 |
| Bed contact | 2978.8 mm2 |

A long drop may still be a **bridge** anchored on both sides, which
prints fine. This check measures the fall, not the span - look at
the section render before adding supports.

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| predator guard | 6.000 | PASS |
| floor | 8.000 | PASS |
| wall | 10.000 | PASS |
| back plate | 10.000 | PASS |
| roof lip | 10.000 | PASS |
| roof thickness | 12.000 | PASS |
| vent slot | 12.000 | PASS |

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
- print-in-place 2 separate bodies, do not merge or union them
- Two pieces: the box upright, the roof flat beside it. Do not rotate.
- No supports. The cavity opens upward and the entrance is a horizontal bore.
- Layer height 0.2 to 0.28 mm. This is a big part and detail is not the point.
- PETG or ASA outdoors. PLA goes brittle in UV within a season.
- 3 walls and 15% infill is plenty - the walls carry it, not the infill.
- Glue the roof on at the stated pitch, or leave it loose to clean the box out.
- No perch, deliberately: nest-box birds do not need one and it gives a predator somewhere to stand.

## Provenance

Spec written by **qwen2.5-coder:7b** on machine **laptop**, 1 attempt(s), 64.6s.

The model filled in a validated specification. It did not write
CAD code - the geometry comes from a template in bpcad, and every
number above was measured off the exported mesh.

## Build log

- outside corners          fillet 1.00 mm
- roof corners             SKIPPED, OCC rejected it
- outside corners          fillet 1.00 mm
- roof corners             SKIPPED, OCC rejected it
- the cavity opens upward, so it prints with no support and no ceiling to bridge
- the roof prints FLAT beside the box and is set on at 30 degrees - modelling the pitch in place would be an overhang across its whole area
