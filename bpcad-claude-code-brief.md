# bpcad — work brief for Claude Code

Read all of this before touching anything. State your understanding back before
you change a file.

---

## 0. House rules (non-negotiable)

- Open every response with `UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS`. No
  edits until UNDERSTOOD is stated.
- Change only what a block below asks for. Zero adjacent edits.
- Complete file rebuilds, not patches. All commands in one message, one command
  per block.
- Never push, commit or deploy unless the word "push" appears in my message.
- Back up before any risky step. Try every automated path before asking me to do
  something by hand.
- Follow the repo's existing patterns exactly. Study the codebase before writing.
- Root-cause first; no fix without a stated cause. Verify before claiming done —
  the regression floor is **702 passed, 1 skipped** and **reachable fit rate
  19/19**. Both must still hold at the end of every block.
- Never guess a dimension, tolerance or API signature. Look it up or ask.

## 1. What bpcad is for

A text-and-image to 3D-printable-part generator. The market comparison is
meshy.ai, and the whole differentiator is **accuracy**: meshy publishes 55%
fully-watertight output and says outright it is not for engineering tolerances.
bpcad's parts are watertight, finer than Prusa's shipping MK3S parts, and
dimensionally exact to microns. That is the product claim and it is already true
and measured.

Where it is going: a web platform plus a downloadable Android app, then iOS,
freemium with metered free usage and paid tiers above it, global
English-speaking market. Non-technical users typing "a phone stand that tilts
back 60 degrees" and getting a printable file.

So judge every piece of work against two questions:

1. Does it raise the odds that an ordinary prompt from a stranger produces the
   part they asked for?
2. Does it survive a user who did not read the docs?

## 2. What is already solid — do not redo or re-litigate

- Mesh quality and dimensional accuracy. A 5 mm hole comes out at radius
  2.5000 ± 0.0000, chordal error 0.0002 mm. Nothing to fix here.
- The spec-first architecture. The model fills a validated Pydantic spec;
  deterministic Python makes the geometry. `spec.yaml` is the durable artifact.
- Export tolerance 0.005 mm / 0.05 angular. Pinned to a real bug. Leave it.
- `cell_bowl`'s 38 sliver triangles. Cosmetic, below export tolerance. Defer.
- Offline rebuild from `spec.yaml`. Keep it. Nothing below breaks it.

## 3. The real problem, named

Shape fidelity, not mesh quality. The parts are geometrically perfect and
sometimes not the thing that was asked for. Asked for a flat drilled plate the
ladder returned an 80×40×30 box with no holes and a PASS verdict. In a paid
product that single failure mode is the refund, the bad review and the churn.

Everything in the work order serves that.

## 4. Work order

Do these in order. Stop after each and report.

### Block 1 — One code path (prerequisite for everything else)

`cli.py`'s `gen` drives its own copy of the escalation ladder instead of calling
`api.generate`. A fix has already landed in one and not the other, and a bug
survived in the CLI while the web app was correct.

- Delete the CLI's ladder. `gen` calls `api.generate` and nothing else.
- Same block: fix `python -m bpcad.cli web` (the `__main__` block sits above the
  `@app.command("web")` registration — move it below). Add `out/` to
  `.gitignore`.

Acceptance: `bpcad gen`, `python -m bpcad.cli web`, the web app and the Qt app
all reach the same routing and escalation code, proven by a test that would fail
if either path diverged. Suite green.

Until this lands, no measurement of the pipeline means anything, because two
paths can measure differently.

### Block 2 — Make the first-try fit rate finishable, then finish it

This is the project's headline metric and nobody has ever seen the number. The
reason is mechanical: the run takes hours on CPU and there is nothing to resume
from, so it never gets to the end.

- Add per-prompt result caching / checkpointing to `tools/fitrate.py --first-try`
  so an interrupted run resumes instead of restarting.
- Record per run: prompt, level reached, verdict, failure class, wall time,
  model used. Write it somewhere durable, not just stdout.
- Then run it to completion and report the number, broken down by level and by
  failure class.

Acceptance: a completed first-try number, plus a table of failure classes ranked
by frequency. That table decides what gets built after Block 5, so do not skip
the breakdown.

One caveat to build in: the 22-entry corpus is not a fair test set. The specs are
hand-written and the fidelity checks were tuned against it. Also run against
`eval/moving_prompts.txt` and against a fresh set of at least 30 prompts written
without looking at the corpus — phrasings a stranger would use ("cable tidy",
"GoPro mount", "shelf pin", "phone dock"). Report the two numbers separately.

### Block 3 — Move the intent checks to the layer that owns them

The three new shape-fidelity checks (roundness, hole counts, hollowness) all
measure the finished geometry and then refuse. Two problems: they will
false-reject correct parts in normal use (details in §5), and refusal is a bad
user experience in a consumer app.

The project's founding decision was: validate the spec, do not free-form the
output. These checks are fighting the wrong layer. Split it:

- **Spec layer answers "did the model try the right thing."** Does the spec
  contain N disc cuts of the asked diameter? Does it contain a `hollow`? Is the
  primary primitive round? This is deterministic, cheap, unambiguous, and the
  critique it produces names exactly what to add.
- **Geometry layer answers "did the build do what the spec said."** Keep the cut
  fault work from the last batch — a cut that removes nothing or that stops
  inside the part is a genuine geometric fault the spec cannot show. That work
  is correct; leave it.

Then change the response. In a paid app the ladder should retry with the critique
and only surface a failure after attempts are exhausted, and when it does, say in
plain language what was wrong and hand the user an editable spec. "Refused" with
a geometry statistic is not shippable copy.

Also fix the asymmetry: `strict_cuts=True` retries for model output but only logs
for a hand-written spec. That means the corpus cannot validate the path users
actually hit. Make the behaviour identical and let the caller choose.

Acceptance: the checks fire on the known bad cases (round knob delivered as a
40×40 prism, plant pot delivered as a solid slab, two holes satisfied by four
corner fillets) and do not fire on the false-positive set in §5. Reachable fit
rate still 19/19.

### Block 4 — Import round-trip lean bug

This blocks the upload feature. A flared pot bpcad built itself comes back as
"this profile leans 51°" and trips the vessel template's own 45° limit — the
template built it happily. Straight fails at 63°. Only an un-leaning cylinder
recovers.

Root-cause it before fixing. Two candidates, and the cause decides the fix:

- The recovery measures lean differently from the builder — segment-to-segment
  instead of overall, or including the rim rounding.
- The 45° limit is a build-time printability constraint being wrongly applied as
  an import validity gate.

If it is the second, the fix is a separation, not a threshold change:
**representability and printability are different questions.** An imported mesh
should come back measurable and editable even when it would not be a legal
vessel to generate from scratch, with the printability problem reported, not used
to reject the import.

Acceptance: every vessel in `parts/` round-trips — export, re-import, recover the
profile, rebuild — and lands within measured tolerance of the original. Report
the residuals.

### Block 5 — Web upload route and UI

Only after Block 4. The API exists (`api.import_stl()`, `api.imported()`,
`api.variants_of()`, `variations.build_scale_variants()`); the door into it from
the app does not. Follow the existing web app patterns exactly. Phone-first, same
house style as the rest of the app.

### Block 6 — Countersunk holes

"two countersunk screw holes" produced one pointed conical dimple and no bore.
The check catches it; the prompt has never been taught the recipe. Teach it: a
`disc` through plus a `cone` at the face. Add a corpus entry so it stays taught.

## 5. Where the last batch looks like the wrong fix

I want these treated as findings to verify, not orders. Each is a prediction that
a check will false-reject a correct part. Test each against a real spec before
changing anything.

**Roundness (plan view filling >86% of bounding box is refused).** Two failures:

- It measures the whole scene. Any correct part combining a round feature with a
  rectangular base — a cylindrical post on a square flange, a round vent in a
  rectangular louvre panel, a knob with a square foot — fills its bbox and gets
  refused.
- It cannot tell "round" the noun from "round" the adjective. "A plate with four
  round holes" names a round thing, fills 100% of its plan view, and gets
  refused. That is a common phrasing and a hard false positive.
- The threshold is also tighter than it looks. A 40×40 prism with a 15 mm corner
  radius fills 88% — refused — and a hexagon fills 75%, so it passes as round.

If a plan-view test survives at all it should measure circularity of the outline
(radial variance from the centroid, or perimeter²/area) on the primary body only,
and it should be a retry signal, never a refusal.

**Hole counts.** Prose number parsing plus cylindrical-face counting will break
on: counterbores (one hole, two cylindrical faces, reads as two), countersinks,
slots, hex or threaded holes, a through-hole that breaks a fillet, patterned
holes ("holes every 20 mm"), "a couple of holes", and faceted cylinders in
imported meshes. The arc-span filter that fixed corner fillets is a patch on a
heuristic. Keep the check only where the parse is unambiguous, and only as a
retry signal.

**Hollowness (container filling >50% of its convex hull is refused).** Thick
walls at small scale trip this while being exactly right. A 30×30×80 pen holder
with a 20 mm bore fills 66% — refused. A 15 mm cap with 2 mm walls fills ~52% —
refused. The measurable definition of a container is a cavity open in +Z with
depth over some fraction of height, which is what the lint rule already cares
about. Use that.

**The router's keyword gate.** Requiring a phrase from some template's `makes`
list is the right shape — decide the road before the model call — but it is
keyword matching, which is the brittleness this project avoids everywhere else.
Real users say "phone dock" and "cable tidy" and match nothing, so everything
goes to level 2 and the five templates become dead weight. Measure it: what
fraction of the fresh prompt set from Block 2 routes to each level? If templates
are near-never hit by unseen phrasing, that changes what to invest in.

**The corpus as a false-positive oracle is circular.** Checks tuned not to fire
on 19 specs the pipeline already builds correctly tell you nothing about false
rejections elsewhere. Block 2's fresh prompt set doubles as the false-positive
set. Nothing tuned on it.

## 6. Mechanisms — my recommendation, my call to confirm

Three vague moving-part prompts produced zero two-body mechanisms. Clearance
rules in prose did nothing. A worked example in the prompt got one success and it
was a verbatim copy of the example. Hand-written mechanisms work, so the DSL
vocabulary is proven — the gap is the model reasoning about op ordering plus
three simultaneous clearances at once.

That evidence says the model is retrieving, not composing. More examples buy
retrieval of those examples, so the failure returns on the next unseen mechanism
and costs tokens forever.

**Recommendation: add a `joint`/`clearance` op** so the gap and the op ordering
become deterministic Python's job, not the model's. That is the project's
founding decision — model fills a spec, code makes the geometry — applied one
level deeper, and it is the only option that generalises.

Do not start this until Blocks 1–5 are done and I have confirmed it.

## 7. Not yours to decide — flag, don't act

- **Hosted inference.** Local Ollama on CPU at 2–6 minutes per prompt cannot
  serve a freemium web and mobile product. That decision is mine. Meanwhile:
  keep the model backend behind its existing interface, do not deepen the
  coupling to Ollama specifics inside `bpcad.api`, and keep the offline-rebuild
  guarantee intact.
- **PWA vs native Android/iOS.** Mine.
- **Metering.** The run record in Block 2 is deliberately the same data a
  freemium meter needs. Build the record; build no billing.
- **Export tolerance coarsening.** Leave it alone.

## 8. First response I want from you

Not code. A short reply:

1. `UNDERSTOOD` — the work order in your own words.
2. Anything in §5 you think I have wrong, with the spec or geometry that shows it.
3. Anything in Block 1 that turns out to be bigger than it looks once you have
   read `cli.py` and `api.generate`.
4. `BLOCKERS`.
