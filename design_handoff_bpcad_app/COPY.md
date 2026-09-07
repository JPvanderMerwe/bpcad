# Copy

Verbatim, as designed. Tone: plain and friendly, technical where it must be, never
apologetic. Sentence case. Numbers always with their unit.

## Boot
```
bpcad
self-test .... ok
kernel ....... cadquery
profile ...... sparkx i7
link ......... api.bpcad
Start
bit primitive — 0.9.4
```

## Printer profile
- step 2 of 2
- Your printer
- "Set this once. Every part gets checked against it — bed fit, wall thickness, joint clearance — and we never ask again."
- Printer / Another printer… / Nozzle / Layer / Material
- Joint clearance not calibrated
- "Until you print the calibration strip we use a conservative 0.35 mm gap. Moving parts will work, but looser than they need to be."
- Get the calibration strip / Save profile / Skip for now

## Library
- Your parts
- Search parts and versions
- All · Parametric · From photo · Moving
- Badges: moves · ok · no scale · ref
- Fit a part to something on your bench
- "Photograph the object, give it one real measurement, and we build a cradle or clamp around it."
- Start from a photo

## Composer
- New part
- Prompt shown: "A hinged clamp for a 32 mm pipe, wall 3 mm, four M4 tabs, prints in place"
- camera · files
- Reading this as a functional part
- "Parametric solid, dimension-accurate, editable. The photo becomes a reference body — it is measured, not printed."
- we picked these up → 32 mm tube ⌀ · M4 × 4 · wall 3.0 · print in place
- we assumed — tap to change → Clamp height 46.0 · Hinge barrels 3 · Tab spacing 26.0
- Generate part · 1 credit
- no account needed for your first part

## Building
- building
- Hinged clamp for 32 mm pipe
- Parsed the description — units, fasteners
- Resolved standards — M4, 32 mm tube
- Built the solid — cadquery
- Swept the joint — 24 steps
- Ran your printer checks — sparkx i7
- "You can leave — we push a notification when it lands."
- Cancel

## Result
- Hinged pipe clamp / parametric · v4
- dims · motion · bloom
- Legend: printable part · reference body — not printed · check passed · tolerance risk
- 7 checks pass · 1 warning
- bbox 78.0 × 46.0 × 21.0 · mass 18.4 g
- Edit · Checks · Export

## Parameters
- Parameters / rebuilding… / up to date
- Bore — tube outer ⌀ (10–80)
- Wall — min 0.8 nozzle (1–8)
- Joint clearance — calibrated (0.10–0.60)
- Tab thickness — M4 tabs (2–10)
- Rebuild · v3

## Checks
- Watertight — "Closed manifold, 0 holes, 0 self-intersections."
- Motion sweep — "Swept 0–124° in 24 steps. Clearance held at 0.28 mm at every step."
- Self-supporting joint — "No overhang inside the barrel exceeds 45°, so no support material lands in the hinge."
- Bed fit — "78 × 46 × 21 mm inside your 256 mm bed."
- Wall thickness, pass — "Thinnest section 3.0 mm — at least three passes everywhere."
- Wall thickness, warn — "Wall is 2.6 mm at the tab root — under three passes of your 0.8 mm nozzle. Raise wall to 3.0 or thicken the tab."
- Fix the warning

Failure copy pattern, from brief 6.7 — measured value, why it fails, what to change:
"Wall is 0.6 mm at the tab, thinner than your 0.8 mm nozzle. Raise wall thickness or
thicken the tab." No apology, no vagueness, never "something went wrong".

## Export
- Export
- "Validated against SPARKX i7 · PLA · 0.8 mm nozzle."
- STL — "Repaired, oriented to a flat base" — 412 KB
- 3MF — "With your printer profile embedded" — 388 KB
- STEP — "Real solid geometry for CAD" — Workshop
- .py — "CadQuery script — web only" — Open
- Download STL
- STEP export is on Workshop — see plans

## Account
- Maker plan · 12 credits left · Top up
- 18 of 30 used this month · resets 1 Oct
- printer profile → printer · bed · nozzle · layer · material · calibrated clearance
- settings → Phosphor bloom in viewport · Notify when a build finishes · Units (mm / in)

## Plans
- First part — free — 1 part, no account — One generated part · STL download · All printer checks — You are here
- Maker — R149 — 30 credits / month — Parametric and photo pipelines · Moving-part joints and motion checks · Version history — Current plan
- Workshop — R399 — 120 credits / month — STEP export · CadQuery script access · Part family generators · Reference-body fitting — Upgrade
- "Buy credits on the web and they show up here — the apps read the same account."

## Command line
- Placeholder, mobile: `hole m4 x4`
- Placeholder, web: `hole m4 x4   ·   wall 3   ·   fillet 2   ·   clearance ?`
- Echo examples:
  - `wall thickness → 3.0 mm · rebuilt`
  - `added 4 × M4 clearance holes (⌀4.6)`
  - `clearance 0.28 mm — from your calibration strip, PLA @ 0.20`
  - `sweeping joint 0–124° in 24 steps · no interpenetration`
  - `wall N · bore N · hole mN xN · fillet N · clearance ? · motion`
  - `read as a new prompt — generating a fresh version`

Echoes use the same words as the panel controls, both directions — brief 6.4.
