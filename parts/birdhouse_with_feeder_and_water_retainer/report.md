# birdhouse_with_feeder_and_water_retainer

## Envelope and volume

| | |
|---|---|
| Envelope | 348.00 x 140.00 x 180.00 mm |
| Volume | 454.675 cm3 |
| Watertight | yes |
| Separate bodies | 2 |
| Triangles | 17296 |

## Filament estimate

Roughly **577.4 g** / **189.1 m** of 1.75 mm PETG at 100% infill.

An estimate from the solid volume. It does not model walls,
infill pattern, supports or purge, so treat it as an upper bound
below 100% infill.

## Print orientation

Build direction **Z**. Export is already in print orientation - do not rotate.

| | |
|---|---|
| Supports needed | YES |
| Worst overhang | 90.0 deg from vertical |
| Underside past 45 deg | 481.6 mm2 |
| ...bridged by the layer above | 0.0 mm2 |
| ...falling further | 481.6 mm2 |
| Bed contact | 41418.2 mm2 |

A long drop may still be a **bridge** anchored on both sides, which
prints fine. This check measures the fall, not the span - look at
the section render before adding supports.

## Feature sizes

Against a 0.40 mm nozzle, threshold 0.40 mm.

| Feature | Size (mm) | Status |
|---|---|---|
| wall | 3.000 | PASS |
| floor | 3.000 | PASS |
| vent slot | 3.600 | PASS |
| roof thickness | 6.000 | PASS |

## Assumptions

These dimensions could **not** be measured. Each is a named
parameter standing in for something unknown.

- **entrance_height_mm** = 123.4 mm above the floor
  Not stated, so it is placed in the upper third of the cavity - high enough that a cat reaching through cannot get to chicks on the floor, low enough that the bird can get in. Set it explicitly if you have a species in mind.

## Departures from true scale

None - this part is at true scale throughout.

## Recommended slicer settings

- printer        Creality i7  (260 x 260 x 255 mm)
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

Spec written by **qwen2.5-coder:7b** on machine **laptop**, 1 attempt(s), 294.5s.

The model filled in a validated specification. It did not write
CAD code - the geometry comes from a template in bpcad, and every
number above was measured off the exported mesh.

## Build log

- outside corners          fillet 0.90 mm
- roof corners             SKIPPED, OCC rejected it
- outside corners          fillet 0.90 mm
- roof corners             SKIPPED, OCC rejected it
- the cavity opens upward, so it prints with no support and no ceiling to bridge
- the roof prints FLAT beside the box and is set on at 18 degrees - modelling the pitch in place would be an overhang across its whole area
