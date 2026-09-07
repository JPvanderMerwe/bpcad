# bpcad — Product Brief (v3)

Sits alongside `bpcad_build_brief.md`. Where the two disagree, this document wins for scope, platforms, UI and the two generation pipelines. The build brief still governs anything this document does not mention.

Owner: JP (Bit Primitive)
Audience for this brief: Claude Code
Status: scope definition, not an instruction to start coding

Changes from v2: web and native mobile are now built in parallel rather than web first. The design direction is now retro technical CAD rather than drafting paper.

---

## 0. How to work on this

Read before doing anything:

1. The entire existing `bpcad` repo. Map the current CadQuery pipeline, the Ollama call sites, the output paths, and any existing UI.
2. `bpcad_build_brief.md`.
3. This document, end to end.

Then open your reply with:

```
UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS
```

State understanding in plain terms before editing any file. No edits until UNDERSTOOD is stated and agreed.

Working rules that apply to every task in this brief:

- Change only what the task asks for. Zero adjacent edits.
- Complete file rebuilds, not patches. All commands in one message, one command per block.
- Never push, commit or deploy unless JP writes the literal word `push`.
- Follow the existing repo patterns exactly. Study the codebase before proposing structure.
- Back up before any risky step. Try every automated path before asking JP to do something by hand.
- Apply `systematic-debug` (root cause first) and `verify-before-claim` (verification gate before claiming anything is done).
- One house style across web and native. A colour, spacing value or label that differs between the two clients is a bug.
- If a requirement here conflicts with something you find in the repo, raise it as a BLOCKER. Do not guess.

---

## 1. What bpcad is becoming

One product, two generation pipelines, one library, shipping as a web app and a native mobile app built in parallel.

**Pipeline A — Photo/image to mesh.** The Meshy-style capability. A user uploads or captures photos and gets a 3D mesh they can print. Decorative and organic shapes: figurines, models of real objects, ornaments, terrain.

**Pipeline B — Description to parametric part.** The existing bpcad path, extended. A user describes a functional part in words and numbers and gets a dimensionally correct, editable, printable solid built through CadQuery. Brackets, clamps, enclosures, adapters, mounts, jigs, and mechanisms with working joints.

**The rule that keeps the product honest:** the parametric model is the source of truth for anything functional. A mesh is never silently promoted to a functional part. The two pipelines meet in exactly one place, described in section 5.

Competitors sit at the two ends of this. Mesh generators produce assets that users report needing heavy cleanup before printing: silhouette correction, internal face deletion, retopology, print repair. The CAD-native tools produce real geometry for engineers at around $99/month. bpcad's claim is the middle: a maker with a printer gets a part that actually fits and actually moves, at a hobbyist price. Every decision below serves that claim.

---

## 2. Platform architecture

Both clients ship at the same time. The only way that is affordable is if neither client contains any geometry logic.

### 2.1 Split

- **Core API.** All geometry generation, validation, repair, export, metering and billing. CadQuery is Python and runs server-side only. Nothing about part generation is ever reimplemented in a client.
- **Web client.** Full-feature client, also installable as a PWA.
- **Native mobile client.** Thin client over the same API, iOS and Android from one codebase.

Every client feature is an API call plus a viewport plus forms. If a client needs logic the other client cannot have, that is a design smell and a BLOCKER.

### 2.2 Native framework

Recommendation: Flutter, because JP already ships Flutter and one codebase covers both stores. Confirm before starting. React Native is acceptable if the repo already leans that way.

### 2.3 The top technical risk: the 3D viewport on native

Interactive 3D in cross-platform mobile frameworks is the single most likely thing to sink the parallel timeline. Handle it as follows:

- **Phase 1 fallback, shipped first:** the server renders a turntable image sequence and a static annotated view for every part version. Native shows a swipeable turntable, the dimension report, the checks, and the download. No live 3D engine in the app. This is genuinely usable and removes the risk from the critical path.
- **Phase 2 upgrade:** glTF viewing through a platform view or an embedded renderer, with orbit and zoom.
- **Phase 3, only if justified:** live parameter editing with in-app re-render.

Do not attempt phase 3 in the first release. Note that the server-side turntable renderer is needed anyway for library thumbnails, so phase 1 costs almost nothing extra.

### 2.4 Payments across platforms

- Credit packs and subscriptions are purchasable on the web.
- The native apps read entitlement from the same account.
- Store rules on in-app purchase for digital goods change, and the commission is material to the unit economics. Confirm the current App Store and Play requirements before implementing any purchase flow in the apps, and raise the answer as a BLOCKER rather than assuming a link-out is allowed.

### 2.5 Feature parity

Deliberate asymmetry, documented in the app:

- **Native-first:** camera capture for Pipeline A, printer-side viewing, push notification when a generation finishes, offline access to already-downloaded files.
- **Web-only in v1:** CadQuery script view and edit, STEP export, part family generator pages, account and billing management.
- **Everywhere:** prompt composer, parameter editing, dimension report, checks, library, STL download.

### 2.6 Shared design tokens

The palette, type scale, spacing scale and radii in section 6 live in one source file and are exported to CSS custom properties and to Dart constants by a build step. Neither client hardcodes a colour. This is what keeps one house style across two codebases.

---

## 3. Pipeline A — photo to mesh

### 3.1 Inputs

- Single image, or 2–20 photos of the same object.
- Native camera capture with a capture guide overlay showing the next angle to shoot.
- Accepted: JPEG, PNG, HEIC, WebP. Strip EXIF before storage except focal length and dimensions.

### 3.2 Inference

- **Do not ship local Ollama to production.** Local inference does not survive concurrent users and makes cost per generation unmeasurable. Move mesh generation behind a hosted inference provider called through a single adapter interface so the provider can be swapped without touching application code.
- Wrap every generation in a job queue with status, timeout, retry policy, and a hard per-user spend cap.
- Log for every job: provider, model, input size, wall time, cost, outcome. Cost per successful generation is a headline product metric and must be queryable from day one.

### 3.3 Scale is a first-class problem

Photos carry no absolute scale. A mesh with no known dimension is useless for anything that has to fit something.

- Every mesh result starts in an explicit `unscaled` state.
- To leave that state the user supplies one real measurement: "the base is 84 mm across", or a caliper reading against any picked edge.
- Until scaled, the download offers the mesh at a user-chosen size and labels it as an estimate.
- A mesh may not be used anywhere in Pipeline B while `unscaled`.

### 3.4 Print preparation, not just generation

Mesh output passes through automatic repair and checks before it is offered as a download:

- Watertight check and hole filling.
- Non-manifold edge and self-intersection repair.
- Internal face and floating shell removal.
- Decimation to a sane triangle count with a user-visible control.
- Orientation to a flat base where one exists.
- Wall thickness scan against the user's nozzle diameter, thin regions highlighted.
- Overhang scan against a configurable angle, shown as an overlay.
- Bed fit check against the user's printer profile.

Each check reports pass, warning or fail with the specific geometry highlighted. A warning never blocks download.

### 3.5 Labelling

Mesh outputs are labelled in the UI and in file metadata as decorative and not dimension-accurate. This is a trust feature, not a disclaimer. It is the reason a user will believe the parametric numbers when they do appear.

---

## 4. Pipeline B — parametric parts, including moving parts

### 4.1 Output requirements

Every parametric generation returns:

- A CadQuery script that reproduces the part exactly, visible and downloadable on web.
- A named parameter set with type, unit, range and default for each parameter.
- STL and STEP exports. STEP is a paid-tier feature but is generated and stored regardless.
- A dimension report: overall bounding box, every user-facing feature dimension, mass estimate for the selected material.
- The printer profile the part was validated against.

### 4.2 Moving parts

The hardest and most differentiating part of the product. Treat it as its own subsystem, not a prompt trick.

Build a **joint library** as parametric primitives with validated motion, not generated one-offs:

- Pin-in-socket revolute joint
- Print-in-place hinge (barrel and living hinge variants)
- Ball and socket
- Sliding rail and captive slider
- Screw thread pair (internal and external, pitch and profile as parameters)
- Snap-fit cantilever hook and annular snap
- Spur gear pair with meshing check
- Print-in-place chain link
- Compliant spring element

Each primitive exposes nominal size, clearance, wall thickness, range of motion, and whether it prints in place or assembles after printing.

### 4.3 Clearance must be calibrated, never hardcoded

Print-in-place clearance depends on printer, nozzle, material, layer height and shrinkage. Any single hardcoded gap fails on most machines.

- Clearance is a parameter of the **printer profile**, not of the part.
- Ship a **clearance calibration part**: one small print containing a row of test joints stepping through a range of gaps. The user prints it once, finds the smallest gap that still moves freely, and enters that number. Every joint in every subsequent part uses it.
- Store a calibrated clearance per profile per material.
- Until calibration is done, use a conservative default, show clearly that it is a default, and prompt the user to calibrate.
- Do not invent clearance figures in this brief or in code comments. The calibration print is the source of the number.

### 4.4 Motion validation

A part with a joint is not done when it renders. Before it is offered as a download:

- Sweep the moving body through its full declared range of motion in discrete steps.
- Assert no interpenetration at any step.
- Assert the declared clearance is maintained at every step, not only at rest.
- Assert no zero-thickness or degenerate faces are produced by the joint geometry.
- Check that enclosed joint cavities are self-supporting at the configured overhang angle, so no support material is needed inside a joint.
- Report the result as a motion check, with the failing step and location if it fails.

A part that fails motion validation is never presented as working. It is presented as failed, with the reason.

### 4.5 Prompt and command handling

- Parse numbers, units and fasteners out of natural language: "32 mm pipe", "four M4 holes", "3 mm wall".
- Never silently invent a dimension. Anything not stated becomes a visible assumption the user can accept or edit, with the assumed value shown.
- Support imperial input with mm output, explicit unit toggle, mm default.
- Maintain a standards table for fasteners, bearings and common tube and pipe sizes, so "M4 clearance hole" and "608 bearing seat" resolve correctly rather than by guess.
- Accept typed commands as well as prose, per section 6.4.

---

## 5. Where the two pipelines meet

Exactly one integration, and it is the feature most worth building:

**Fit a parametric part to a photographed object.**

Flow: the user photographs the thing on their bench, the mesh is generated and scaled with one real measurement, then the mesh becomes a **reference body** in the parametric workspace. The user asks for a bracket, cradle, clamp or lid for it. bpcad measures the reference body, derives the contact geometry, and builds a parametric part around it with a user-controlled fit offset.

Requirements:

- The reference body is visible in the viewport in a distinct, obviously non-printable treatment (see the pen set in 6.1).
- The reference body is never exported.
- The generated part states which reference dimensions it took from the mesh and at what fit offset, so a user can correct a bad measurement instead of reprinting blindly.
- Fit offset is a printer-profile-aware parameter with press, sliding and loose presets.

Nothing else crosses between pipelines. No mesh-to-solid conversion is in scope.

---

## 6. Design direction

The UI is not a wrapper around the pipelines. For this product it is most of the product, because what is being sold is confidence that the part will work.

**Direction: retro technical CAD.** The reference points are amber and green phosphor CRTs, 1980s vector CAD workstations, pen plotters, and the command-line era of drafting software. Not neon cyberpunk, not Matrix pastiche, not a novelty terminal skin over a normal SaaS app. The retro grammar has to be functional: a coordinate readout because coordinates matter, a command line because typing `hole m4 x4` is genuinely faster, a plotter pen palette because different line types mean different things.

### 6.1 Tokens

Core palette, six values:

| Name | Hex | Use |
|---|---|---|
| `case` | `#0B0F0D` | app background, the machine's shell |
| `bezel` | `#151B18` | panels, cards, raised surfaces |
| `etch` | `#2A322D` | rules, borders, grid lines, inactive strokes |
| `phosphor` | `#FFB000` | primary accent, active state, primary actions, focused input |
| `screen` | `#DCE3DC` | primary text |
| `dim` | `#7C8880` | secondary text, labels, disabled |

`#FFB000` is the amber phosphor value, chosen over the more obvious terminal green so the product does not read as a generic hacker skin. Green appears only as a state colour.

Viewport pen set, used exclusively inside the 3D canvas and for annotation:

| Pen | Hex | Meaning |
|---|---|---|
| `pen-solid` | `#DCE3DC` | the printable part |
| `pen-dim` | `#4A554E` | grid, graticule, construction geometry |
| `pen-ref` | `#35C6E8` | reference body from a photo, never printed |
| `pen-pass` | `#5BE37D` | passed check, confirmed dimension, joint clearance OK |
| `pen-warn` | `#FFB000` | tolerance risk, uncalibrated default, thin wall |
| `pen-fail` | `#E8489B` | failed check, interpenetration, out of bed bounds |

Failure uses magenta rather than red, because it comes from the plotter pen set and because red is reserved for destructive confirmation only.

### 6.2 Type

Two families, clearly distinct:

- **Interface and data:** a squared monospace with genuine character. IBM Plex Mono or JetBrains Mono are acceptable. Used for all labels, parameters, numbers, dimensions, the command line, the coordinate readout, and buttons. Monospace is functional here, not decorative: parameter digits must not shift width while a slider moves.
- **Prose:** a neutral grotesque for anything longer than two lines, including onboarding, errors, help and the family pages. Monospace paragraphs are hostile to read.

Set `font-variant-numeric: tabular-nums` on every numeric field. Sentence case throughout. No tracked-out all-caps labels.

### 6.3 Layout

Desktop, three zones, viewport dominant, with a persistent status line:

```
+---------------+------------------------------+------------------+
| PROMPT        |                              | PARAMETERS       |
| + photos      |                              | dimensions       |
|               |          VIEWPORT            | checks           |
| assumptions   |                              |                  |
| versions      |                              | export           |
+---------------+------------------------------+------------------+
| > hole m4 x4                        X 42.0  Y 18.0  Z 6.0   mm  |
+-----------------------------------------------------------------+
```

Native, viewport first, status line docked above the keyboard, controls in a bottom sheet snapping to three heights: peek (prompt), half (parameters), full (checks and export). Viewport never smaller than half the screen. All primary actions reachable one-handed.

Content is left aligned throughout. No centred body text.

### 6.4 The command line

The single most characteristic element, and it must be real.

- Always present at the bottom of the workspace on both platforms.
- Accepts natural language ("a clamp for a 32 mm pipe") and terse commands (`hole m4 x4`, `fillet 2`, `wall 3`, `clearance ?`).
- Autocompletes parameter names and standards values.
- Echoes what it did, in the same vocabulary as the UI controls, so typing teaches the interface and clicking teaches the commands.
- Keeps a scrollback the user can page through and re-run.
- Shows live coordinate and dimension readout on the right of the same line.

This is where the theme and the utility are the same thing. Spend the boldness here.

### 6.5 Motion demonstration

For any part with a joint, the viewport animates the joint through its range of motion on request. This is the most persuasive thing the product can show, and the reason someone believes a print-in-place part will work before spending three hours printing it. On native phase 1 this is a rendered loop rather than live geometry.

### 6.6 Retro treatments: what is allowed, and the limit

Allowed, used once each and no more:

- A single boot moment on first load: a brief vector self-test sweep across the viewport with a version string. One orchestrated moment, not a per-section effect.
- A very subtle scanline or phosphor bloom on the viewport only, off by default, toggleable in settings, always off under `prefers-reduced-motion`.
- Drafting annotation drawn properly: extension lines, arrowheads, dimension text broken into the line.
- A graticule with a visible origin marker and axis labels in the viewport.

Not allowed:

- Full-screen CRT curvature, flicker or chromatic aberration.
- Fake typing animations on text the user did not type.
- ASCII art logos, block-character borders, or falling character effects.
- Green-on-black everything. Amber is the accent, not the whole palette.
- Skeuomorphic beige plastic chrome or fake CRT bezels around the browser viewport.

### 6.7 Interaction requirements

- **First part with no signup.** A web visitor generates one part and downloads the STL before creating an account. Product requirement, not a growth experiment.
- **One composer for words and photos.** Typed description and dropped or captured images in the same input.
- Parameter edits re-run and update the viewport without a full page transition. Progress shown on the affected geometry, not a global spinner.
- Every previous version one click away. Editing never destroys the last good result.
- Printer profile set once in onboarding (bed size, nozzle, layer height, material, calibrated clearance) and applied everywhere silently. Never ask twice.
- Dimensions shown on the model as annotated callouts, toggleable, in the current unit.
- Keyboard: every action reachable, visible focus rings in `phosphor`, viewport orbit and zoom on keys as well as pointer.
- Empty states are invitations with a real starting action.
- Failures state what went wrong and what to change, in the interface's voice, no apologies, never vague. "Wall is 0.6 mm at the tab, thinner than your 0.8 mm nozzle. Raise wall thickness or thicken the tab."
- Quality floor on both platforms: responsive to 380 px, visible keyboard focus, reduced motion respected, contrast checked against the dark palette, no colour-only status signalling. Every pen colour is paired with an icon or label.

### 6.8 Process for UI work

Before writing UI code for a screen, produce a short design plan: tokens in use, type scale with weights, layout concept with an ASCII wireframe, and the three principles that make this screen specific to bpcad. Review it against this section and revise anything that would look identical on any other AI tool. Only then write code. Screenshot and critique your own output as you go. Build the web screen and the native screen from the same plan in the same task, so they cannot drift.

---

## 7. Non-goals for this version

Do not build:

- Community sharing, comments, follows, or a public feed.
- Assemblies of more than one printed body, beyond the joint primitives in 4.2.
- Slicing, G-code generation, or printer control.
- Mesh-to-solid reverse engineering.
- Texturing, PBR materials, or presentation rendering.
- Team accounts or seats.
- Live in-app parameter re-rendering on native (phase 3 in 2.3).
- Any geometry logic inside either client.

---

## 8. Acceptance criteria

Done when all of the following are demonstrably true, each verified by running it, not by reading the code:

1. A web visitor with no account types a description, generates a part, and downloads a valid STL.
2. A photo captured in the native app produces a printable, watertight, repaired mesh, and cannot be scaled without the user supplying one real dimension.
3. A described functional part returns a CadQuery script, parameter set, STL and STEP, and a dimension report whose numbers match measurements taken on the exported solid.
4. Every joint primitive in 4.2 generates, passes motion validation, and can be seen moving through its range on both platforms.
5. The clearance calibration part generates and prints, and entering a calibrated value changes the clearance in subsequently generated joints.
6. A part that fails a check is presented as failed, with the specific geometry highlighted and a stated fix.
7. A photographed object can be scaled, used as a reference body, and a bracket generated around it that states which reference dimensions it used.
8. Cost per successful generation is queryable per provider and per pipeline.
9. Every part family page on the web has a working generator on it.
10. Web and native render the same part with the same tokens, and a token change in the shared source updates both.
11. Native builds install and run on a physical iOS device and a physical Android device, with camera capture, turntable view, checks and download working offline for already-downloaded files.
12. The app is usable one-handed at 380 px, keyboard accessible on desktop, correct with reduced motion enabled, and passes contrast checks on the dark palette.

---

## 9. Suggested build order

Two tracks after a shared foundation. Confirm with JP before starting any phase.

**Foundation (both tracks blocked until done)**

1. Design token source file with CSS and Dart exports. Palette, type scale, spacing, radii.
2. Core API skeleton: accounts, printer profile, storage, job queue, cost logging.
3. Server-side turntable and thumbnail renderer.

**Track 1 — Core and geometry**

4. Pipeline B hardening: parameter sets, dimension report, STL and STEP export, check framework.
5. Joint library and motion validation, including the calibration part.
6. Pipeline A: hosted inference adapter, repair and check stage, scaling flow.
7. Reference-body fitting.
8. Library data model: my parts with versioning, then part families.

**Track 2 — Clients**

9. Web workspace: composer, viewport, parameters, checks, command line.
10. Native shell: auth, printer profile, camera capture, turntable viewer, checks, download.
11. Web library and part family generator pages.
12. Native library and push notification on generation complete.
13. Native glTF viewer upgrade (phase 2 in 2.3).
14. PWA install and offline shell.

Each client task consumes an API contract that already exists. If Track 2 is ever blocked waiting on Track 1, that is a sequencing error to raise, not a reason to put logic in a client.

---

## 10. Open questions for JP

Raise these as BLOCKERS rather than deciding them:

1. Flutter or React Native for the native client?
2. Which hosted inference provider for Pipeline A, and is there a monthly budget ceiling during development?
3. Which payment processor, given a South African company, and what do the current App Store and Play rules require for digital credit purchases?
4. Which printer profiles ship as presets besides the SPARKX i7?
5. Is the CadQuery script visible to free users, or is it a paid-tier feature?
6. Are both apps published under Bit Primitive Pty Ltd, and are the developer accounts already registered? Store enrolment and review time sit on the critical path for a parallel launch.
7. Does the existing repo structure support a single API with two clients, or does it need restructuring before the foundation phase?
