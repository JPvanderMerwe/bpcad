# bpcad — Product & Technical Direction Brief

**Owner:** JP van der Merwe / Bit Primitive Pty Ltd
**Audience:** Claude Code, working on the bpcad repository
**Status:** Direction-setting. Supersedes any conflicting assumption in `bpcad_build_brief.md`.
**Revision:** 3 — freemium monetisation from launch, Meshy-style. Metering, accounts and billing are now in scope.
**Date:** September 2026

---

## 0. How to use this document

Read this whole file before writing anything.

Then, before any edit:

1. Read the existing bpcad codebase in full. Follow its existing patterns, naming, and structure exactly. This brief sets direction; it does not authorise a rewrite.
2. State `UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS` and wait for approval before touching files.
3. Where this brief conflicts with existing working code, say so and ask. Do not silently refactor.
4. Change only what is asked. No adjacent edits.
5. Never push, commit, or deploy unless the literal word "push" is given.

Four decisions are not yet made and are listed in section 14. Do not guess them.

---

## 1. What bpcad is

bpcad turns a plain-language description of a **functional part** into **parametric CAD** that prints correctly the first time.

Not a mesh generator. Not an art tool. A part-maker for people who need a bracket that fits an 8 mm rod, a mount that clears an existing screw boss, or an enclosure sized to a real PCB.

The one-line positioning:

> Describe the part. Get parametric CAD that actually fits. On your phone, or in your browser.

---

## 2. Delivery targets

Three surfaces, one product, built in this order:

| # | Surface | Form | Priority |
|---|---|---|---|
| 1 | **Android** | Downloadable app — Google Play, plus a direct APK from bitprimitive.com | First |
| 2 | **Web** | Full experience in the browser, no install | Ships alongside Android |
| 3 | **iOS** | Downloadable app — App Store | After Android is stable |

**Android first** is deliberate: Play review is faster than Apple's, a sideloadable APK gives a distribution channel independent of any store, and JP tests on Android hardware daily.

**There is no desktop target.** Geometry and inference therefore run on servers, which costs real money per user — and that cost is what section 4 exists to cover.

---

## 3. Business context

Every technical decision below follows from these facts. If a proposed feature violates one, it does not ship.

### 3.1 The model: free usage, then paid usage

bpcad runs like Meshy: a genuinely useful free tier with a metered monthly allowance, paid tiers above it for people who generate often, and revenue that covers the inference and compute the free tier consumes.

This replaces the "reach first, revenue later" position in revisions 1 and 2, and it is the better call. Revision 2 had an unfunded free tier held back only by a spend ceiling, which meant the reward for a clip doing well was a bill and a shut-off switch. Charging from launch fixes that: growth pays for itself, and it becomes possible to learn in year one whether anyone actually values this rather than finding out in year three.

The cost is real and should be planned for. Accounts, metering and billing add weeks of build time, and a signup step will reduce raw user numbers compared with a no-account product. Both are worth it.

### 3.2 Unit economics

The metered unit is **one generation**: a spec turned into a validated part.

What is metered:

- A generation that produces a part passing validation

What is **not** metered, ever:

- A generation that **fails** validation. Meshy does not charge failed tasks, and bpcad can do this more precisely because failure is detected programmatically against the spec (section 9.4). A part that does not meet the requested dimensions is our defect, not the user's spend. Say so in the interface — it is the single strongest trust signal available.
- Adjusting parameter sliders. These re-execute geometry with no inference (section 9.5), so they are effectively free to serve and must be free to use. This is a real advantage over credit-metered mesh tools where every iteration burns budget.
- Re-exporting or re-downloading a part already generated, in any format.
- Reopening and viewing anything in the library.

What *is* metered, matching Meshy: re-rolling a successful generation because the user wants a different result. That consumes inference, so it consumes allowance.

Every generation must be logged with tokens consumed, CPU seconds and cost from the very first commit. The pricing in section 4 is a guess until there is real data behind it; the instrumentation is what turns it into a decision.

### 3.3 Audience

Functional 3D printing hobbyists and makers, globally, English-speaking. Technically capable enough to install an app, read an error, and file a coherent bug report. They already use PrusaSlicer, Bambu Studio, OrcaSlicer, OpenSCAD, FreeCAD.

Be realistic about willingness to pay: this ecosystem runs on free and open tooling, and a large fraction of these users will never pay for anything. That is fine — the free tier is the marketing channel (section 4.3), not a loss to be minimised. The paid conversion will come from the minority who generate parts weekly.

### 3.4 Distribution: no sales, no ads, no budget

Growth must come from the product itself:

- Google Play and App Store search (ASO on "text to CAD", "AI bracket generator", "free STL generator")
- r/functionalprint, r/3Dprinting, Printables, Thingiverse, MakerWorld
- GitHub, if the core is open sourced (section 14)
- **Screenshot and clip sharing** — a fifteen-second phone clip of "typed a sentence → printed it → it fits" is the marketing strategy
- **Free-tier attribution** — see 4.3, which turns the licence terms themselves into a distribution mechanism

Mobile-first helps here in a way desktop never did: the phone is the camera and the sharing device. Someone measures a rod with calipers, photographs it, describes the bracket, and posts the result without leaving the device. Build for that loop explicitly (section 8.1).

### 3.5 Competitive position

**Mesh generators** (Meshy, Tripo, Rodin, Sloyd) produce triangle meshes — right for organic shapes, wrong for anything that has to fit. bpcad does not compete here and should never try. Meshy is the business-model reference, not the product reference.

**Text-to-CAD** (Zoo, Adam CAD, Leo AI) produce precise solid geometry. Zoo outputs editable STEP with parameter sliders and shipped a conversational design agent in early 2026. Adam CAD has a dimension-driven parametric mode. These are funded and ahead on polish.

bpcad will not win on novelty. It wins, if it wins, on three things:

1. **Price.** Commercial text-to-CAD subscriptions are widely described as prohibitive for hobbyists, students and independent makers. bpcad's paid tier must sit clearly below them, and its free tier must be genuinely usable rather than a demo.
2. **It is on the phone, at the bench, next to the printer.** None of the funded players are mobile-native. This is the sharpest differentiator.
3. **First-try dimensional correctness on ordinary maker parts.** What the audience actually cares about, and where the funded players are weakest.

### 3.6 Non-goals

Do not build, scaffold, or leave hooks for:

- Organic / decorative / character models
- Assemblies, kinematics, simulation, FEA
- Teams, seats, shared pools, collaboration, social feeds
- A hosted marketplace or model library
- Print-service integration
- Rendering, texturing, materials beyond one neutral shading

Note what has been **removed** from this list since revision 2: accounts, metering and billing are now in scope. They cannot be avoided — usage cannot be metered without identity.

---

## 4. Monetisation

### 4.1 Tiers

Indicative, not final. Section 14 needs JP's numbers; these exist so the entitlement system can be built against a real shape.

| Tier | Price | Generations / month | Licence on output | Other |
|---|---|---|---|---|
| **Free** | $0 | ~15 | CC BY 4.0 — credit bpcad when publishing the model | All export formats, full resolution, unlimited slider edits and re-exports |
| **Maker** | ~$7/mo | ~150 | Full commercial rights, no attribution | Priority queue, private parts |
| **Workshop** | ~$20/mo | ~600 | Full commercial rights | Best model, highest concurrency |
| **Own key / own Ollama** | $0 | Unlimited | Full commercial rights | User supplies their own model access |

Design notes on this shape, each with a reason:

**Do not cripple downloads on the free tier.** Meshy restricts downloads on free, which works for them because a preview render still demonstrates value. It does not work here: the STL *is* the product, and a part you cannot print is worthless. Meter generations, never exports.

**The free allowance is small but the parts are real.** Fifteen genuinely usable parts a month is enough for a hobbyist who prints occasionally and not enough for someone designing weekly. That is exactly where the upgrade line should sit.

**Allowance resets monthly and does not roll over**, as Meshy's does. Simple to explain, simple to implement.

**When the free allowance runs out**, do not dead-end the user. Meshy's free plan cannot top up mid-month — the user waits or upgrades. bpcad offers a third door: add your own API key and carry on for nothing. That converts a frustrated user into a retained one, and it costs us nothing.

**Regional pricing is mandatory, not optional.** Meshy prices by region with a currency selector and offers a lower-cost Starter tier in select developing countries. bpcad is built by a South African company for a global audience; $20/month is unaffordable in much of that audience, including at home. Build purchasing-power-adjusted price bands in from the start rather than retrofitting them.

### 4.2 Why the own-key tier does not cannibalise the paid tiers

It looks like giving the product away, and it is — to the small minority who will paste an API key into a phone app. Most users will not, and will happily pay $7 to have it just work. Meanwhile the tier does three useful things: it caps our exposure to heavy users, it earns credibility with exactly the technical crowd whose word of mouth matters most, and it means no one can accuse bpcad of holding their designs hostage.

### 4.3 The free tier is a distribution channel

Meshy's free outputs are licensed CC BY 4.0, requiring attribution for commercial use. Copy this, and understand *why* it is clever in bpcad's specific context.

bpcad's users publish their parts. They upload to Printables, MakerWorld and Thingiverse. If free-tier output requires crediting bpcad, every published part becomes a link back, in front of precisely the audience bpcad wants — and the user gets a legitimate way to remove the attribution by paying.

This is the closest thing to self-marketing available, and it is a licence term rather than a marketing budget. Make the attribution requirement clear, easy to comply with (offer copy-paste attribution text and a one-tap credit line on export), and never sneaky.

### 4.4 Where money is collected

**Recommended: sell on the web only. Sell nothing inside the apps.**

The apps read the user's tier and remaining allowance from their account. Upgrading happens in a browser, on bitprimitive.com.

The reason is in section 10.2: in-app selling drags in store commissions, region-specific rules and payment code that a solo developer should not be maintaining. Web-only checkout avoids all of it, at the cost of some conversion friction. For a one-person operation that trade is worth making.

**Payment processing:** use a merchant of record that handles global VAT and sales tax registration on your behalf. Bit Primitive is a South African company selling digital services worldwide, and tax compliance across dozens of jurisdictions is not a thing to hand-roll. Confirm the current terms of whichever provider is chosen before committing; do not assume.

### 4.5 What the system needs

- **Accounts.** Minimal: email with a magic link, or OAuth. No profiles, no usernames, no social. Identity exists to attach entitlement, nothing more.
- **Entitlement service.** One source of truth for tier and remaining allowance, read by all three clients. Never let a client decide its own entitlement.
- **Usage ledger.** Append-only, idempotent. A retried request must never double-charge. Failed validations must never charge at all.
- **Payment webhooks.** Subscription created, renewed, cancelled, payment failed. Handle each explicitly, including the dunning path.
- **Cost telemetry.** Tokens and CPU seconds per generation, aggregated per user and globally, visible on a dashboard JP can actually read.
- **Graceful exhaustion.** A clear screen that states what ran out, when it resets, and offers both the upgrade and the own-key paths.

---

## 5. The metric that decides everything

**First-try fit rate:** of a corpus of realistic part requests with known-correct dimensions, what fraction produce a part whose measured critical dimensions match the spec, with no human editing?

This is the product, and it is now also the business. Because failed validations are not charged (3.2), a low fit rate means bpcad burns inference it cannot bill for. Every point of fit rate is directly a point of margin.

Build the evaluation harness (section 12.6) **before** polishing the interface. Report the number. Optimise it.

---

## 6. Product principles, borrowed from Meshy

Meshy reached over 10 million users. "As easy as Meshy" is the interaction bar.

**A single obvious loop: input → generate → refine → export.** No project setup, no file dialogs before the first result.

**Multiple entry points.** Text, a photo, or both. On mobile the camera is right there — use it.

**The agent asks a couple of short clarifying questions with tappable options.** Meshy's agent asks about style and key details with pickable answers rather than demanding a perfect prompt. For bpcad this is the core of the fit-rate strategy. Nobody types tolerances unprompted:

> What does it attach to?  `A rod`  `A flat surface`  `A screw hole`  `Something else`
> Measured diameter of the rod?  `[ 8.0 ] mm`
> Slide on, or press on tight?  `Slide on (clearance)`  `Press fit (tight)`

Three taps and one number beats a paragraph. On a phone keyboard it is the difference between finishing and giving up.

**Kill credit anxiety, which is the main reason people abandon metered AI tools.** Meshy addresses it with free retries on previews so premium credits are only spent on commitment. bpcad's version is stronger and must be stated plainly wherever the allowance is shown:

> Only parts that pass the dimension checks use your allowance. Slider changes and re-exports never do.

**Several variants, not one.** Three candidates per generation, on one charge, so the user picks rather than being stuck.

**A proper library.** Every earlier part reopens and re-parameterises, free, forever, on any tier.

**Speed.** Meshy's ~1 minute is the benchmark. Aim for a first draft under 20 seconds.

---

## 7. Mobile-first user journey

```
FIRST RUN
  Sign in (magic link) -- required, because usage is metered
  Printer profile: nozzle, layer height, bed size, material  [skippable]
  Inference: [ Free tier ]  [ My own key ]  [ My own Ollama ]
  -> straight to the prompt

MAIN LOOP
  1. Describe the part        "bracket to hold an 8mm rod to a wall"
     or tap the camera and photograph what it mounts to
  2. Agent asks 2-4 questions -- tappable chips, numeric steppers, defaults
  3. Three drafts arrive in the viewport, ~20s   [1 generation used]
  4. Swipe between them, tap to choose
  5. Drag sliders -- instant, free, no allowance used
  6. Read the printability strip; fix what is flagged
  7. Export -> share sheet: STEP / STL / 3MF / .py
     free tier: attribution line offered for copy-paste
  8. Saved to the library automatically

IF VALIDATION FAILS
  Nothing is charged. Say so on screen. Offer a retry.

IF ALLOWANCE IS EXHAUSTED
  State what ran out and when it resets.
  Offer: [ Upgrade ]  [ Use my own key ]
  Library, sliders and exports keep working.
```

Rules:

- Never block the first generation on profile setup. Ship defaults (0.4 mm nozzle, 0.2 mm layer, 220×220×250 bed).
- Never lose a version. Every generation is retained and comparable.
- Show remaining allowance where it is useful and nowhere else. A persistent counter creates the anxiety 6 is trying to remove; show it on the generate action and on exhaustion.
- Everything except generation works offline: library, viewer, re-export.

---

## 8. Feature scope

### 8.1 Mobile-specific features that justify a native app

Apple rejects apps that are thin web wrappers with no native value, and a phone-shaped bpcad should earn its install anyway:

| Feature | Why it must be native |
|---|---|
| Camera capture of the mating part, in-flow | The core mobile advantage: measure and photograph at the bench |
| Share-sheet export to Files, Drive, slicer and chat apps | How a part actually leaves the phone |
| On-device parts library, works offline | Useful with no signal, and no allowance needed |
| Push notification when a slow generation completes | Lets the user leave the app instead of waiting |
| Haptic confirmation on validation pass or fail | Physical feedback at the bench, hands dirty |
| Screen-record-friendly viewport | Feeds the clip-sharing loop in 3.4 |

### 8.2 v1 — must ship

| Feature | Why |
|---|---|
| Accounts with magic-link sign-in | Metering requires identity |
| Entitlement and usage ledger | Section 4.5 |
| Web checkout and subscription webhooks | Section 4.4 |
| Text prompt + optional camera photo | Two entry points, minimum typing |
| Clarifying-question step, tappable, numeric steppers | The fit-rate mechanism |
| Three candidate variants per generation | One charge, three options |
| 3D viewport with dimension annotations | Makes correctness visible and screenshots shareable |
| Auto-extracted parameter sliders, unmetered | Fast iteration with no allowance cost |
| Printability strip | Min wall vs nozzle, overhang angle, bed fit, unsupported bridges |
| Export STEP, STL, 3MF, `.py` via share sheet, unmetered | The STL is the product; never gate it |
| Free-tier attribution helper on export | Section 4.3 |
| On-device parts library | Retention, and free value on every tier |
| Printer profile | Turns generic checks into real ones |
| Inference tier picker (free / own key / own Ollama) | Sections 4.1 and 4.2 |

### 8.3 v2 — after fit rate is good and revenue exists

- Photo-to-dimension assist: estimate a measurement from an image with a reference object in frame
- A starter catalogue of proven parametric templates used as few-shot grounding
- Print-in-place clearance presets
- Version diff view
- Batch generation of a size family
- Annual billing at a discount, and a student rate

### 8.4 Never — see 3.6

---

## 9. Technical architecture

### 9.1 The central decision, unchanged: generate code, not geometry

The model emits **CadQuery Python**, never mesh or geometry directly:

- Output is a real parametric solid via OCCT, exportable to STEP
- Named variables become sliders for free
- Re-running after a slider change needs no inference — which is what makes unmetered sliders economically possible
- Code is small, so failures are inspectable and repairable from a traceback
- The approach is well represented in model training data, which measurably helps generation quality

### 9.2 The hard constraint that shapes everything else

**CadQuery cannot run on a phone.** Its OCP binding layer to the OpenCascade kernel ships binary wheels for Linux, macOS and Windows only, supporting Python 3.9 through 3.12. There are no Android or iOS wheels.

The OCCT kernel itself *does* support Android and iOS on ARM, with official platform samples — but that is the C++ library, not the Python stack bpcad is built on. Bridging the gap means cross-compiling OCCT for mobile ARM, rebuilding the pybind11 bindings, and embedding CPython in both apps. That is months of work and it is not the project.

**Therefore: geometry executes server-side. The apps are clients.** Accept it, design for it well, and stop looking for a way around it.

### 9.3 The pipeline

```
device (Android / iOS / browser)
   text + photo + tapped answers + auth token
        |
        v  HTTPS
+---------------------------------------------------+
|  bpcad backend                                    |
|                                                   |
|  [0] ENTITLEMENT CHECK -> tier, remaining          |
|            |              allowance, model access  |
|            |              (reserve, do not charge)  |
|            v                                      |
|  [1] SPEC BUILDER  -> structured JSON spec:       |
|                       features, dimensions,       |
|                       tolerances, fit types,      |
|                       print constraints           |
|            |   (the contract; all checks use it)  |
|            v                                      |
|  [2] CODE GEN -> 3 candidate CadQuery scripts     |
|            |     via the caller's tier            |
|            v                                      |
|  [3] SANDBOX EXEC -> separate process, no net,    |
|            |          hard timeout, memory cap    |
|            v                                      |
|  [4] VALIDATE  (a) single valid manifold solid?   |
|            |   (b) measured dims match the spec?  |
|            |   (c) printable on this profile?     |
|            v                                      |
|  [5] REPAIR on failure: traceback + failed        |
|            |  assertion fed back, max 3 retries   |
|            v                                      |
|  [6] COMMIT: charge the reservation ONLY on pass. |
|            |  On final failure, release it and    |
|            |  log the cost as ours.               |
|            v                                      |
|  [7] RESPOND: mesh, extracted parameters,         |
|               STEP/STL/3MF, source, usage state   |
+---------------------------------------------------+
        |
        v
   device renders, caches locally, exports offline
```

Step 0 and step 6 are the money path. Reserve up front so concurrent requests cannot overspend an allowance; charge only on a validated pass; release on failure. Make the ledger idempotent so a client retry after a dropped connection cannot double-charge.

### 9.4 The spec is the contract

The highest-leverage part of the system, and the most under-invested in comparable tools.

The spec is a machine-checkable JSON object. From it, generate **assertions** and run them against the produced solid: "the user asked for an 8.2 mm hole" becomes a check that a cylindrical face of diameter 8.2 ± 0.05 exists.

This is what makes section 5's fit rate computable, and it is also what makes "we don't charge for failures" enforceable rather than a slogan.

### 9.5 Parameter extraction

Parse the generated script with Python's `ast`. Find module-level numeric assignments. Return them to the client as labelled controls, using the variable name and any trailing unit comment.

```python
ROD_DIAMETER = 8.0   # mm, measured
WALL = 3.0           # mm
SCREW_SPACING = 20.0 # mm
CLEARANCE = 0.2      # mm, slide fit
```

Four lines become four sliders. Adjusting one is a CadQuery re-execution well under a second, no model call, no allowance charged.

### 9.6 Slider latency, and the WASM escape hatch

Slider drags must feel instant, and a network round trip per drag will not. Two mitigations, in order:

1. **Debounce and preview.** Update a cheap client-side proxy (scaled bounding geometry) live during the drag, fire one server re-execution on release.
2. **Client-side geometry, later.** OCCT has been ported to JavaScript and WebAssembly via Emscripten, with maintained TypeScript geometry layers on top. Running geometry in the WebView would make sliders instant and cut server compute to near zero.

The catch: a WASM kernel is not CadQuery, so the generation target would change from CadQuery Python to a JavaScript geometry API. That is a significant fork, it discards the training-data advantage in 9.1, and it drags in the OCCT licensing problem in 10.3. **Not a v1 decision.** Keep the geometry layer behind an interface so the swap stays possible.

### 9.7 App shells

One web frontend codebase, three deliveries. Do not maintain three UIs.

- **Web:** the canonical build, and the only place money is collected.
- **Android:** the same frontend in a native shell (Capacitor or equivalent), native capabilities from 8.1 exposed as plugins. Ship a Play listing and a direct APK from bitprimitive.com.
- **iOS:** the same shell, after Android is stable.

Choose the shell by which gives clean camera, share-sheet, push, haptics and offline storage access with the least native code. State the reasoning before committing.

### 9.8 Privacy and data

- Accounts hold an email and an entitlement. Nothing else.
- Own-key and own-Ollama credentials never leave the device.
- Prompts and photos transit to the backend for generation. Say so plainly in the interface; do not bury it. Do not retain them beyond the request unless the user opts in for debugging.
- Parts are stored on the device, not on the server.
- No telemetry beyond the cost and usage data section 4.5 requires. Anything further is opt-in and documented in the README before it ships.

---

## 10. Store, payment and licensing constraints

Real gates. Deal with them before Phase 5, not during review.

### 10.1 Apple minimum functionality

An app that is essentially a website in a wrapper gets rejected. The native features in 8.1 are the answer and must be genuinely present at first submission.

### 10.2 Selling digital goods, and why bpcad sells only on the web

This is the messiest area in the project and the reason for the recommendation in 4.4.

The landscape as it stands:

- Standard commission is 30% on both stores, reduced to 15% for developers earning under $1M a year from in-app purchases, and for subscriptions after their first year. Bit Primitive qualifies for the reduced rate.
- Apple was ordered in April 2025 to stop charging commission on US external payment links. In December 2025 the Ninth Circuit largely affirmed the contempt findings but vacated the total ban and sent it back for a commission rate tied to Apple's actual costs. Apple lost its rehearing bid in March 2026, and the Supreme Court granted certiorari on a limited question in June 2026. **A fee will probably return; the rate is unknown.**
- The external-link allowance applies to the **US storefront only.** The same link UI in a globally distributed app is a 3.1.1 violation in Japan, Canada, Australia, the UK and most other regions. The EU operates under separate DMA terms with its own reduced-commission structure. Compliance requires region-aware behaviour, not one global switch.
- Google now charges service fees on external "alternative billing" transactions and requires reporting, where Apple currently does not in the US.

For a solo developer this is a maintenance liability with a moving legal target. Selling only on the web avoids the entire surface: no in-app purchase, no external-link entitlement, no region gating, no store commission.

**Verify this against the current App Store Review Guidelines before submission.** The multiplatform-service pattern — content bought elsewhere being usable in-app — is well established, but this area is under active litigation and the rules have changed repeatedly. Do not assume it still reads the way this brief describes.

### 10.3 OCCT licensing

OpenCascade is LGPL 2.1 with an exception, and its documentation addresses store distribution directly: where an application is distributed in a form the user cannot modify — statically linked, or via the App Store or Google Play — the application must also be provided separately in a modifiable form with everything needed to run it against a modified OCCT, or a commercial licence must be obtained.

With geometry server-side this does not bite, because OCCT is not in the shipped binary. **It bites immediately if the WASM path in 9.6 is taken.** Flag it then; do not discover it at submission.

### 10.4 Tax

Bit Primitive is a South African company selling digital services globally. Use a merchant of record that assumes VAT and sales tax registration and remittance. Confirm current terms with the chosen provider; this brief does not name one.

### 10.5 Android target API level

Google Play enforces a yearly minimum target API level. Check the current deadline before first submission and target accordingly.

### 10.6 Permissions

Camera and network. Nothing else. No overlay permission, no accessibility service, no background services. A short permission list also converts better.

---

## 11. Design direction

Glassmorphism, dark, information-dense. Fixed. What follows makes it survive a phone screen and a live 3D viewport.

### 11.1 Grounding

The subject is **precision and measurement** — calipers, tolerances, dimension lines, build plates, layer lines, anodised aluminium. Not generic dark app chrome. The interface should feel like a measuring instrument, and dimensions should be the best-treated element on screen.

### 11.2 Tokens

```css
/* Surfaces */
--bp-bed:        #101720;                   /* canvas behind the viewport */
--bp-bed-deep:   #0A0F16;                   /* recessed wells, source view */
--bp-glass:      rgba(28, 40, 54, 0.62);    /* panel fill — never below 0.45 alpha */
--bp-glass-lift: rgba(40, 56, 74, 0.72);    /* raised / pressed */
--bp-edge:       rgba(150, 180, 210, 0.18); /* hairline edge */

/* Ink */
--bp-ink:        #E8EEF4;
--bp-ink-dim:    #93A6B8;
--bp-ink-faint:  #5E7286;

/* Semantic — two accents, two jobs, never swapped */
--bp-dim:        #5BC8D6;   /* measurement, dimension lines, numerals */
--bp-act:        #F2A33C;   /* the generate / commit action, sparingly */
--bp-pass:       #6FC98A;   /* validation passed */
--bp-fail:       #E06060;   /* validation failed */
```

Amber is the action colour and appears on **one** element per screen. Cyan belongs to measurement data only. Neither is decorative. Billing and allowance UI uses ink tones, never amber — the generate button is the only amber thing, and an upgrade prompt must not compete with it.

### 11.3 Type

- **UI and headings:** a grotesque with real character — Archivo or Space Grotesk. Not Inter.
- **Dimensions, numerals, source:** JetBrains Mono. Monospace here is functional — dimension figures must align and be unambiguous at a glance.

Bundle both as local font files in all three builds. No CDN font loads; the apps must render offline.

Sentence case throughout. No tracked-out all-caps labels above headings.

### 11.4 Mobile layout

The viewport is the hero and gets the screen. Everything else is a bottom sheet.

```
+---------------------------+
|  bpcad        [profile]   |   <- minimal top bar
+---------------------------+
|                           |
|                           |
|        VIEWPORT           |   <- dominant, full width
|    part on a build-plate  |      pinch/rotate, dimension
|    grid, cyan dimension   |      lines always legible
|    lines                  |
|                           |
|   < o o o >               |   <- swipe between 3 variants
+---------------------------+
| PRINTABILITY: 3 passed  ^ |   <- one-line strip, tap to expand
+---------------------------+
|  BOTTOM SHEET (glass)     |
|  drag handle              |
|                           |
|  rod dia   [====o--] 8.0  |   <- params, thumb-height, free
|  wall      [==o----] 3.0  |
|                           |
|  [ Generate ]  [ Export ] |   <- Generate is the only amber
+---------------------------+
```

Rules:

- All primary controls in the lower third, thumb-reachable.
- The bottom sheet has three states: collapsed to a prompt bar, half for parameters, full for conversation and history.
- Slider hit targets minimum 44 px. Numeric values are also directly tappable for keyboard entry — never slider-only, because a maker knows the exact number.
- Respect safe areas and the keyboard inset. Test on a small phone, not just a large one.

### 11.5 Glass rules — non-negotiable, stricter on mobile

`backdrop-filter` over a live WebGL canvas is expensive on desktop GPUs and worse on phone GPUs:

1. **Never float glass over the part silhouette.** Panels hug edges, each with a solid gradient scrim behind so text never sits on unpredictable model colour.
2. **Minimum 0.45 alpha tint floor on every glass surface.** Contrast must hold against the brightest backdrop the model can produce.
3. **One blur layer, maximum 16px radius on mobile.** Never nest `backdrop-filter`.
4. **Drop blur to a flat tint while the model is rotating or a slider is being dragged.** Restore on settle. Measure framerate; do not assume.
5. **Numeric dimension fields get solid backgrounds, never glass.** A misread digit produces a part that does not fit. No exceptions.
6. Text on glass must clear 4.5:1 contrast. Verify it.
7. Respect `prefers-reduced-transparency` and `prefers-reduced-motion`, and offer a manual "reduce effects" toggle for low-end devices.

### 11.6 Motion

One orchestrated moment: the part resolving into the viewport when generation completes. No fade-and-slide entrances on panels, no transition on every card.

### 11.7 Copy, including money copy

Plain verbs, sentence case, active voice. Name things as a maker would: "wall thickness", not "shell parameter". Buttons say what happens: "Generate", "Export STEP".

Failures are direction, not mood:

> The 8 mm hole came out at 7.6 mm. Regenerating with the clearance corrected — this attempt doesn't use your allowance.

Money copy is plain and never manipulative. No countdowns, no fake scarcity, no dark patterns on cancellation. State the allowance, the reset date, and the price. This audience will punish anything else publicly, in the same forums that are bpcad's distribution channel.

---

## 12. Engineering standards

1. **Study the codebase first.** Follow existing patterns exactly.
2. **Root-cause first.** Find why before changing anything. No speculative patches.
3. **Verify before claiming done.** Run it. Show the output. "Should work" is not a status.
4. **Complete file rebuilds, not fragments**, when a file changes substantially.
5. **All commands in one message, one command per block.**
6. **The eval harness is load-bearing.** A corpus of realistic part specs with known-correct dimensions, executed automatically, reporting first-try fit rate as one number. Build it early. Regressions block merges.
7. **The sandbox is a security boundary.** Generated code is untrusted and runs on our server. Separate process, no network, resource-capped, timeout enforced. Never `exec()` in the request handler.
8. **The billing path needs tests before it needs polish.** Double-charging a user, charging for a failed part, or letting an expired subscription keep generating are all trust-destroying bugs. Test the reserve/commit/release cycle, webhook replay, and concurrent requests against one allowance.
9. **Cost telemetry is a feature, not instrumentation.** Section 3.2 is unenforceable without it.
10. **Back up before risky steps.** Try every automated path before asking JP to do anything by hand.

---

## 13. Sequencing

Roughly 10–20 hours a week alongside a full-time job. Ordered by what de-risks fastest.

**Phase 1 — prove it fits.** Spec builder, code gen, sandbox, validation, repair loop, eval harness. Command line only, no UI, nothing public. Deliverable: a first-try fit rate on twenty real part requests, printed and measured with calipers.

If that number is bad, no app and no pricing page saves the project. Stop and fix the pipeline.

**Phase 2 — the backend as a service.** Wrap the pipeline in an API. Accounts, entitlement, usage ledger, reserve/commit/release, rate limits, the three inference tiers, cost telemetry. Deployed, no public client.

**Phase 3 — web client and checkout.** The canonical frontend, the full glass design system, and web billing with regional price bands. This is where the UI is built once for all three surfaces, and the first place revenue can arrive.

**Phase 4 — Android.** Native shell, the capabilities in 8.1, Play listing plus direct APK. Expect slippage; store review and native plumbing always take longer than estimated.

**Phase 5 — iOS.** Only once Android is stable and the section 10 gates are comfortably cleared.

bitprimitive.com becomes load-bearing at Phase 3, because it is where checkout lives. Build only what checkout and the APK download need — not a rebrand.

---

## 14. Open decisions — do not guess these

Ask JP before proceeding:

1. **Prices and allowances.** Section 4.1 is indicative. The free allowance, the paid price points, and the regional bands need JP's numbers. They cannot be set properly until Phase 2 cost telemetry shows what a generation actually costs.
2. **Licence for the code.** A permissive core maximises credibility and distribution with this audience, and open source is the norm in maker tooling. It also lets a funded competitor absorb the work — and it interacts with charging money for the hosted service. Not decided.
3. **Payment provider.** Merchant-of-record for global tax handling, per 10.4. Not decided.
4. **Shell technology for the native apps.** Pick on camera, share sheet, push, haptics and offline storage access with the least native code. Present the reasoning before committing. Not decided.

---

## 15. Summary

Generate parametric CadQuery code, not geometry. Verify every part against a machine-checkable spec, repair on failure, and never charge for a part that fails the check. Turn code variables into sliders that are instant and free. Run geometry on the server, because CadQuery cannot run on a phone. Meter generations only — never exports, never iterations. Give the free tier real parts under an attribution licence so published models advertise the product, and sell the attribution away for a low monthly price with regional bands. Collect money on the web only, and keep store billing out of the apps entirely. Ship web and Android together, iOS after. Wrap it in a measurement-grade dark glass interface built for one thumb, where the part is the hero and every dimension is legible. Prove the part fits before making it pretty. Let the clips do the selling.
