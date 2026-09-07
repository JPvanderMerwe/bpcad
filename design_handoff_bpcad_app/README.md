# Handoff: bpcad client UI — mobile app and web workspace

For: Claude Code, working in `JPvanderMerwe/bpcad`.
From: the design pass in the Omelette project "BPCAD mobile app design".
Source of truth for scope: `bpcad_product_brief.md` (v3) in the repo. This document
covers **only** section 6 (design direction) and the client screens in section 2.5.

---

## 0. Read this first

Per section 0 of the product brief: read the repo, `bpcad_build_brief.md`, the product
brief and this document end to end, then reply with

```
UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS
```

before editing any file. Nothing below overrides the brief. Where this document and the
brief disagree, **the brief wins** and the disagreement is a BLOCKER to raise, not a
decision to make.

Two things in this handoff are new relative to the brief and need JP's yes before they
are built:

1. **Glassmorphic floating chrome.** The brief's section 6.6 lists allowed retro
   treatments and does not mention translucency. JP asked for it verbally after seeing
   the design. Section 6 below specifies it. Treat it as an amendment pending
   confirmation.
2. **Live 3D on mobile.** The prototype shows an orbitable model on the phone. The brief
   (2.3) says **phase 1 native ships a server-rendered turntable, not a live engine**.
   Build the turntable first. The prototype's viewport is the phase 2 target, not the
   first release.

## About the design files

`prototype/` contains **design references written as HTML**, not production code. They
are a single streaming HTML component plus a plain-JS three.js viewer. Do not port them
into the repo. Recreate the screens in the real clients:

- **Native:** Flutter under `mobile/` (framework confirmation is still open question 1
  in brief section 10 — if it is not Flutter, raise a BLOCKER).
- **Web:** the existing web client under `bpcad/web/`.

Both must read from `design/tokens.json` via `tools/tokens.py`. No client hardcodes a
colour, a spacing value or a radius — brief section 2.6, acceptance criterion 10.

To open the prototype: serve `prototype/` over HTTP (`python3 -m http.server`) and open
`bpcad App.dc.html`. It needs network access for Google Fonts and the three.js CDN.

## Fidelity

**High fidelity.** Colours, type sizes, spacing and radii are exact and all come from
`design/tokens.json`. Copy is final unless a check message needs a real number
substituted. Layout proportions are exact at 390 × 844 (mobile) and at the three-zone
desktop grid. Recreate pixel-accurately using the tokens, not by eyedropping the HTML.

---

## 1. What is in the prototype

A platform toggle at the top switches between the two clients.

**Mobile — 11 states**, reachable from the flow index rail on the left:

| # | Screen | Route intent |
|---|---|---|
| 01 | Boot & self-test | cold launch, once |
| 02 | Printer profile | onboarding, once |
| 03 | Library | tab 1 |
| 04 | Composer | modal from the centre FAB |
| 05 | Building | full screen, replaces composer |
| 06 | Result & viewport, sheet at peek | full screen |
| 07 | Result, parameters sheet | same screen, sheet state |
| 08 | Result, checks sheet | same screen, sheet state |
| 09 | Result, export sheet | same screen, sheet state |
| 10 | Account & credits | tab 2 |
| 11 | Plans | pushed from account |

**Web — one workspace**: three zones over a persistent status line, exactly the ASCII
diagram in brief 6.3.

---

## 2. Design tokens

All of these already exist in `design/tokens.json`. Do not re-derive them; export them.

Core: `case #0B0F0D`, `bezel #151B18`, `etch #2A322D`, `phosphor #FFB000`,
`screen #DCE3DC`, `dim #7C8880`.

Pens (inside the 3D canvas and annotation only): `solid #DCE3DC`, `dim #4A554E`,
`ref #35C6E8`, `pass #5BE37D`, `warn #FFB000`, `fail #E8489B`.

Type: mono = IBM Plex Mono (labels, numbers, buttons, command line, all UI chrome);
prose = Inter (anything over two lines: onboarding body, check explanations, plan
features). Scale in px: micro 10.5 / label 12 / body 13.5 / reading 15 / figure 17 /
title 21 / display 27. Weights 400 / 500 / 600.

Spacing: 2 / 4 / 8 / 12 / 16 / 24 / 32 / 48.

Radius: `none 0`, `edge 3`, `panel 6`, `card 10`. **Amendment:** floating glass surfaces
use a larger radius than the token scale carries — sheet 16, cards and composer 10–12,
pills 7. If that is accepted, add a `radius.float: 16` token rather than hardcoding.

Metrics: minimum tap target 44, minimum supported width 380.

Every numeric field sets `font-variant-numeric: tabular-nums`. Sentence case
everywhere. No tracked-out all-caps.

---

## 3. Screen specifications

### 01 Boot & self-test

Full-bleed `case` with a 26 px graticule at `#141a17`. App icon 72 px at radius 14,
wordmark "bpcad" at display 27 / weight 600 below it. Four mono lines at label 12 in
`dim`, dot-leadered, with the value in `pass` green except the printer profile which is
`phosphor`. The last line pulses opacity .25 → 1 → .25 over 1.4 s while the API link
resolves.

One amber hairline sweeps vertically down the screen, 2.4 s, `cubic-bezier(.5,0,.4,1)`,
looping — this is brief 6.6's single boot moment. It must not repeat on later screens
and must not run under `prefers-reduced-motion`.

Primary button full width, 48 px, `phosphor` fill, `case` text, radius 3.
Version string bottom left at micro 10.5 in `pen-dim`.

### 02 Printer profile

Step indicator "step 2 of 2" in `phosphor` at micro. Title at title 21. One prose
paragraph in Inter 13.5 / 1.55, `dim`, explaining that this is asked once.

Fields: printer row (selected state = 1 px `phosphor` border, 8 px amber square, bed
size right-aligned in tabular mono); nozzle as a three-way segmented control with the
selected cell filled `phosphor`; layer as a static readout; material as four chips,
selected one outlined and lettered in `phosphor`.

Clearance callout: 1 px `phosphor` border, background `phosphor` at 6 % alpha, a 12 px
bordered `!` mark, mono heading, Inter body. This is brief 4.3 — the copy must say the
default is conservative and prompt the calibration print. Never state a hardcoded
clearance figure as if it were calibrated.

Save is a 48 px `phosphor` button; skip is a ghost 40 px in `dim`.

### 03 Library

Header title 21 plus a credits pill (7 px amber square, tabular count) that pushes to
account. Search row. Four filter chips, selected outlined in `phosphor`.

Grid: two columns, 12 px gutter. Card = glass surface, radius 10, 1 px
`rgba(220,227,220,.10)`, inset top highlight `rgba(220,227,220,.07)`. Thumbnail band
104 px tall on `case` with a 13 px graticule, holding the server-rendered turntable
frame (brief 2.3 — the renderer exists for this). Kind label top-left at 9.5 px `dim`.
Status badge bottom-right, bordered in its pen colour with the word spelled out —
`moves`, `ok`, `no scale`, `ref`. **Colour never carries status alone** (brief 6.7).

Below the grid, a dashed-border invitation for the photo-fit flow, in `pen-ref` cyan.

### 04 Composer

One input for words and photos (brief 6.7). Container: 1 px `phosphor` at 65 % alpha,
radius 12, glass fill, drop shadow. Textarea in Inter 15 / 1.5. Beneath it a horizontal
strip of 56 px tiles: attached photos outlined in `pen-ref`, then camera and files
buttons outlined in `etch` that go `phosphor` on hover.

Pipeline banner: cyan-tinted, a bordered "B" mark, mono heading and Inter body stating
which pipeline the prompt was read as and what that means. This is a trust surface —
it must reflect the real router decision, not a guess.

"we picked these up" — parsed values as chips outlined in `pen-pass`, tabular.
"we assumed — tap to change" — one row per assumption, amber square, label left, value
right in `phosphor`, tapping opens the editor. Brief 4.5: never silently invent a
dimension.

Primary action states the credit cost inline. Below it, micro text: no account needed
for the first part (brief 6.7).

### 05 Building

Graticule background. Kicker "building" in `phosphor`, then the part title at figure 17.

Centre: a 230 px SVG line drawing of the part outline, stroked in `screen` at 1.6 px,
`stroke-dasharray` 900 drawing over 2.6 s and looping; a second amber pass at 1.2 px
starts 0.5 s later for the holes. A 2 px amber gradient bar scans down over the same
2.6 s. Under reduced motion both freeze at fully drawn.

Stage list, five rows: 9 px square dot — hollow `pen-dim` when pending, filled
`phosphor` and pulsing when live, filled `pen-pass` when done — label in mono 12.5,
right-hand note in micro `pen-dim`. Stages: parsed the description / resolved standards
/ built the solid / swept the joint / ran your printer checks.

Progress: 2 px `etch` track with a `phosphor` fill, `width` transitioning linearly at
.12 s. Percent and credit cost left, elapsed seconds right, both tabular.

Copy tells the user they can leave and will be notified (brief 2.5 native-first).
Cancel is a ghost button that goes `pen-fail` magenta on hover.

**Progress must be driven by real job status from the queue** (brief 3.2), not a timer.
The prototype fakes it at 90 ms ticks.

### 06–09 Result and the bottom sheet

Viewport fills the screen. Floating chrome over it, all glass:

- Top row: back button 32 px, a title chip with the part name at 11.5 and
  "parametric · v4" at 9.5 in `dim`, then `dims` and `motion` toggle pills.
- Pen legend bottom-left: one row per pen, a 10 × 2 px dash of the pen colour and the
  meaning in words at 9.5 `dim`. It sits 12 px above the sheet and moves with it.
- Dimension callouts are DOM labels projected from 3D anchor points, mono 10.5,
  tabular, in the pen colour of what they describe, on a `case`-at-82 % chip with a
  matching hairline border. They fade in once the entrance finishes.

Sheet snaps to three heights (brief 6.3): peek ≈ 252, half ≈ 396, and the sheet must
never take more than half the screen — the viewport stays ≥ 422 px of 844. Grab handle
38 × 3 in `etch`, tappable.

- **Peek**: check summary chips (pass count in `pen-pass`, warnings in `pen-warn`, each
  with a mark), bbox and mass in tabular mono, then three 44 px buttons — Edit, Checks,
  Export, the last filled `phosphor`.
- **Parameters (07)**: one row per parameter — label left, value right at figure 17 in
  `phosphor` tabular, unit after it; a range slider with a 2 px `etch` track and a
  12 px square `phosphor` thumb; min, a hint, and max beneath at 9.5. A "rebuilding… /
  up to date" indicator sits in the header and pulses while dirty. Rebuild is
  incremental — progress shows on the affected geometry, never a global spinner
  (brief 6.7).
- **Checks (08)**: 16 px bordered mark in the pen colour carrying `✓` or `!`, name in
  mono 12.5, a spelled-out pass/warn/fail tag, and an Inter explanation. Failure copy
  states the measured number and the fix, in the interface's voice, no apology — e.g.
  "Wall is 0.6 mm at the tab, thinner than your 0.8 mm nozzle. Raise wall thickness or
  thicken the tab."
- **Export (09)**: one row per format — a 44 px bordered extension tag, filename in
  mono, an Inter note, and the size or a gate word on the right. STEP is gated to
  Workshop and its tag and right-hand word are `phosphor`, not disabled grey. Primary
  Download STL plus a 44 px share button. A ghost footer line links to plans.

Docked at the bottom of the sheet on every state: the command line.

### The command line (brief 6.4)

Always present. Amber `>`, mono 12.5 input, live coordinate readout right-aligned in
tabular mono. On web it lives in the status line with a blinking 1 px amber caret.

It must genuinely parse. The prototype recognises `wall N`, `bore N`, `hole mN xN`,
`fillet N`, `clearance ?`, `motion`, `help`, and treats anything else as a new prompt.
Real implementation: the same parser as the composer (brief 4.5), autocomplete on
parameter names and standards values, scrollback the user can page and re-run, and an
echo in the same vocabulary the sliders use.

Scrollback lines: input in `screen`, success in `pen-pass`, anything provisional in
`phosphor`.

### 10 Account & credits

Avatar square 44 px, name at reading 15, plan at 11 `dim`. Credits panel: count at
display 27 in `phosphor` tabular, "credits left", top-up button; a 2 px usage bar; a
micro line with the reset date.

Printer profile as a key/value list — values tabular, the calibrated clearance in
`pen-pass` to show it is measured rather than assumed. Settings rows with 38 × 20
square-cornered switches; the phosphor-bloom toggle is brief 6.6's viewport-only
scanline, off by default and forced off under reduced motion.

### 11 Plans

Three cards, the current plan outlined in `phosphor` over a 5 % amber tint. Price at
figure 17 tabular. Features as 6 px `pen-pass` squares plus Inter lines. Only the
upgrade card takes a filled button.

Purchases happen on the web; the apps read entitlement from the same account
(brief 2.4). **Store IAP rules are an open BLOCKER — do not implement a purchase or a
link-out in the apps before that is answered.**

### Web workspace

Grid `minmax(0,270px) minmax(0,1fr) minmax(0,290px)`, minimum height 660.

Left: prompt (amber-bordered glass), photo tiles, assumptions, versions, scrollback.
Version rows show the id, a note, and a pen dot; the active one is amber-bordered.
Centre: viewport, model switcher top-left, view toggles top-right, both in one wrapping
flex row so they can never collide; pen legend bottom-left; an affordance hint
bottom-right.
Right: parameters, dimension report, checks, export. Panels are glass over `case`; the
two column dividers are the only 1 px rules on the page.
Bottom: the status line, full width.

---

## 4. Interactions and motion

| Where | What | Timing |
|---|---|---|
| Boot | vertical amber sweep | 2.4 s loop, `cubic-bezier(.5,0,.4,1)` |
| Building | outline stroke draw | 2.6 s loop, ease-in-out; amber pass offset 0.5 s |
| Building | scan bar | 2.6 s linear |
| Building | live stage dot | 1 s opacity pulse |
| Viewport | entrance | 0.9 s, cubic ease-out on scale 0.92 → 1 and opacity 0 → 1 |
| Viewport | idle auto-orbit | starts 2.5 s after last input, ~0.0032 rad/frame |
| Viewport | joint motion | sine sweep through the declared range, ~0.9 rad/s |
| Sheet | open | 0.22 s, 18 px rise plus fade |
| Progress bar | width | 0.12 s linear |
| Command caret | blink | 1.1 s step-end |

Every one of these is suppressed under `prefers-reduced-motion` — the prototype does
this with a global media query that collapses animation duration.

Viewport input: drag to orbit (0.008 rad/px horizontal, 0.006 vertical, phi clamped to
0.12–π−0.12), wheel to dolly between 0.45× and 1.9× the fit distance. Brief 6.7 also
requires keyboard orbit and zoom — **not in the prototype, must be built.**

---

## 5. The 3D viewport

`prototype/part-viewport.js` is a plain custom element over three.js. Read it for the
intended look; do not ship it.

Rendering model: each solid is a dark `bezel` face mesh with `polygonOffset` plus a
`LineSegments` of its `EdgesGeometry` in `pen-solid`. Holes are drawn as 48-segment
circle line loops on both faces. The graticule is a 180-unit, 18-division grid in
`pen-dim` at 50 % with three `phosphor` axis lines and an origin sphere — brief 6.6's
graticule with a visible origin marker.

Camera framing is the part that matters and the part that is easy to get wrong. Fixed
distances break in narrow columns and behind the sheet. The rule:

```
radius   = boundingSphere(model).radius * 1.18
band     = viewportHeight - bottomInset        // inset = sheet height + margin
tanV     = tan(fov/2) * band / viewportHeight
tanH     = tan(fov/2) * aspect
distance = radius / sin(atan(min(tanV, tanH)))
target.y = center.y - (inset / 2) * worldPerPixel
```

Recompute on resize and on model change. Vertical fov is 34°.

Three models are demonstrated: a bracket, a print-in-place hinge that sweeps its range,
and the photo-fit case — a translucent cyan reference body with a parametric cradle
built around it. The reference body is never exported and is always visibly
non-printable (brief section 5).

---

## 6. Glassmorphism — confirmed, and it applies throughout

JP confirmed this after review. It is an accepted amendment to brief 6.6 and must be
reflected there. Treat it as part of the house style, not an experiment.

**Every raised surface is glass.** Panels, cards, sheets, pills, segmented controls,
field wells, the device bezel, the rail, the plan cards, the web side columns and the
status line all take the recipe below. What stays flat is only this:

- the app ground itself (`case`, plus its graticule),
- the 3D canvas,
- **ink** — text, numbers, dimension callouts, sliders and check marks are full-opacity
  and never translucent. Glass is the surface under them, never the value itself.

The one rule that keeps it legible: a glass surface that sits over content is denser
than one that sits over the ground. Alphas are listed below; do not go lower.

Recipe:

```css
background: rgba(30, 38, 34, 0.34–0.62);   /* denser the more it overlaps content */
backdrop-filter: blur(14–26px) saturate(150%);
border: 1px solid rgba(220, 227, 220, 0.10–0.16);
box-shadow: inset 0 1px 0 rgba(220, 227, 220, 0.08);
```

Alpha by surface, over the ground → over content:

| Surface | Alpha | Blur | Radius |
|---|---|---|---|
| Web side columns, scrollback, photo-fit invitation | .34–.36 | 14–20 | 10–12 |
| Rail items, field wells, segmented controls | .30–.40 | 14 | 8 |
| Library cards, plan cards, notes, credits panel, avatar | .40–.46 | 14–18 | 10–12 |
| Composer, viewport pills, browser chrome | .44–.50 | 16–20 | 7–12 |
| Device bezel, tab bar, bottom sheet, web status line | .50–.62 | 20–26 | 16 |

Tinted glass keeps its hue and gains alpha: the amber clearance callout is
`rgba(255,176,0,.10)`, the cyan pipeline banner `rgba(53,198,232,.10)`, the active
plan card `rgba(255,176,0,.10)`, an active pill `rgba(255,176,0,.18)` — each over the
same blur. Borders on tinted glass take the tint at 35–70 % rather than the neutral
hairline.

Radius amendment: the token scale tops out at 10. Glass needs more. Add
`radius.float: 16` and `radius.control: 7` to `design/tokens.json` and use them —
sheet and bezel 16, cards and panels 10–12, pills and segments 7. The squared 0/3
radii stay on **data** chrome: check marks, status squares, slider thumbs, progress
bars, dot indicators. That contrast — soft floating surfaces, hard data marks — is the
point, and it is what stops the glass reading as a generic consumer app.

Glass needs something behind it or it reads as flat grey. Both viewport containers
carry ambient light:

```css
background-image:
  radial-gradient(120% 60% at 78% 4%,  rgba(255,176,0,.16), transparent 62%),
  radial-gradient(90% 44% at 10% 96%, rgba(53,198,232,.10), transparent 66%);
```

Limits, so this stays inside brief 6.6: no full-screen curvature, no flicker, no
chromatic aberration, no fake CRT bezel. `backdrop-filter` is a progressive
enhancement — with `@supports not (backdrop-filter: blur(1px))` fall back to the flat
`bezel` fill at full opacity. On Flutter this is `BackdropFilter` + `ImageFiltered`;
watch the raster cost on a scrolling list and consider capping it to the sheet, the tab
bar and the floating pills only.

---

## 7. State

Client state only — no geometry logic in either client (brief 2.1, 7).

- `screen`, and on the result screen a separate `sheet` of peek / params / checks /
  export. Sheet height feeds the viewport's bottom inset and the legend offset.
- `job` — id, stage, percent, elapsed, outcome — polled or pushed from the queue.
- `part` — id, version, parameter set, dimension report, check results, export URLs,
  and for meshes a `scaled | unscaled` flag that gates everything downstream (brief 3.3).
- `printerProfile` — bed, nozzle, layer, material, calibrated clearance and whether it
  is calibrated or a default.
- `viewport` — dims on/off, motion on/off, bloom on/off, camera spherical coords.
- `commandHistory` — scrollback plus a cursor for paging and re-running.
- `entitlement` — plan, credits, what is gated.

Parameter edits mark the part dirty, fire a rebuild request, and show progress on the
affected geometry. Editing never destroys the last good version (brief 6.7).

---

## 8. Assets

- `prototype/assets/app-icon.png` — copied from `bpcad_media/AppIcon-1024.png` in the
  repo. Everything else the clients need already exists in `bpcad_media/`; regenerate
  with `build_brand.py` rather than editing PNGs.
- Fonts: IBM Plex Mono and Inter. The prototype loads them from Google Fonts; the
  clients should vendor them. Check the OFL note in `bpcad_media/README.md`.
- Icons: the prototype draws its few marks as bordered CSS boxes rather than pulling an
  icon set, so nothing is faked. Pick a real set when you build, and keep every pen
  colour paired with a mark or a word.

## 9. Files in this bundle

```
README.md             this document — implement from it
TOKENS.md             token → CSS var → Dart constant mapping, including the
                      glass and radius additions this design needs
COPY.md               every UI string in the design, verbatim
IMPLEMENTATION.md     the work broken into tasks against brief section 9,
                      each with its acceptance check
screenshots/
  index.md            which file is which screen
  01…12-bpcad-screen.png
prototype/
  bpcad App.dc.html   the whole design — both platforms, all 11 mobile states
  part-viewport.js    the three.js viewport: framing, pens, entrance, joint motion
  support.js          runtime for the HTML prototype; irrelevant to the repo
  assets/app-icon.png
```

Screenshots are the reference for **look**; this README is the reference for
**values**. Where a screenshot and a number here disagree, the number wins — the
captures are DOM re-renders and soften blur and shadow slightly.

## 10. Known gaps

Designed but not yet drawn — worth asking JP whether they are in this slice:

- Camera capture with the next-angle guide overlay (brief 3.1).
- The mesh scaling step: entering one real measurement to leave `unscaled` (brief 3.3).
- The clearance calibration print flow end to end (brief 4.3).
- Keyboard orbit and zoom in the viewport (brief 6.7).
- Empty states for a library with no parts.
- Error and offline states.
