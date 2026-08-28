# Level-1 success-rate baseline

Measured before any prompt tuning, as the build brief requires. Raw rows in
`baseline/results.jsonl`, prompts in `baseline/prompts.txt`.

    machine      laptop - Intel Core Ultra 7 258V, 32 GB, 100% CPU inference
    models       qwen2.5-coder:7b primary, hermes3:latest small
    code         fingerprint 42744ae2dd8e
    date         2026-08-27
    command      bpcad gen "<prompt>" --no-render

Every row records the code fingerprint. An earlier attempt at this measurement
was discarded because the source changed while it ran, so runs 1-2 and runs 3+
were testing different programs. A measurement taken while the code moves is
not a measurement.

## Result

    SUCCESS RATE   5/10   (50%)

    median wall-clock   all runs    267.6s
                        successes   124.0s   (1-2 attempts)
                        failures    371.7s   (7-8 attempts)
                        range       92s to 864s

    by template         vent        2/5   (40%)
                        keyring     3/5   (60%)

## Every run

| # | prompt | result | attempts | seconds |
|---|---|---|---|---|
| 1 | a louvre vent 76 mm wide and 30 mm tall for a wall | ok | 2 | 211 |
| 2 | a small louvre vent for a cupboard door, 60 mm wide | FAIL | 8 | 441 |
| 3 | an adjustable air vent, 100 mm wide, 40 mm tall, six blades | ok | 2 | 155 |
| 4 | a louvre vent with thick 6 mm walls for outdoor use | FAIL | 7 | 865 |
| 5 | a wide vent 120 mm across with eight blades | FAIL | 8 | 372 |
| 6 | a keyring in the shape of the loop device, 30 mm wide | ok | 2 | 124 |
| 7 | a small keyring 25 mm wide, no logo | ok | 1 | 93 |
| 8 | a chunky keyring 40 mm wide and 9 mm thick | FAIL | 8 | 334 |
| 9 | a keyring with the screen detail but no wordmark | ok | 1 | 98 |
| 10 | a thin keyring 28 mm wide, 5 mm thick, plain | FAIL | 8 | 324 |

## What actually failed

Not the model, and not its understanding of the request. Every one of the five
failures is a TEMPLATE DEFAULT that is only valid at the reference part's
dimensions. Zero failures were the model misreading the prompt, inventing a
template, or producing unparseable output.

Three defaults are pinned to the reference geometry:

| default | valid only near | breaks when |
|---|---|---|
| `blade_chord_mm = 14.0` | `frame_w_mm = 76` | any narrower frame, or more blades |
| `crank_r_mm = 5.0` | `blade_chord_mm = 14` | any shorter chord |
| `logo_on = True` | - | always: it requires a `logo_json` path a model cannot know |

The vent failures are a CASCADE. The model shrinks the frame, so the default
chord exceeds the blade pitch. It shrinks the chord as instructed, and now the
default crank radius pokes past the blade trailing edge. Two validators, one
after the other, neither default having moved with the frame.

The keyring failures are all `logo_on is true but logo_json is not set`. Note
that three keyring prompts SUCCEEDED on this same trap: runs 6, 7 and 9. Runs 7
and 9 said "no logo" and "no wordmark" in the prompt, so the model set the flag
immediately. Run 6 hit the trap and recovered on attempt 2. Runs 8 and 10 lead
with dimensions, so the model spends its attention there and never addresses
the flag at all.

## What this says about the architecture

The failure mode is a validator refusing an impossible part, which is the
schema doing its job - no broken geometry was produced, at any point, in any
run. Every failure left an annotated `spec.draft.yaml` naming the offending
field and its legal range.

A successful run costs about two minutes. A failed run costs about six and
leaves a draft where one number needs changing.

## The fix this points to

Not prompt tuning. The three defaults should be derived rather than fixed:

  * `blade_chord_mm` default from the blade pitch
  * `crank_r_mm` default from the chord
  * `logo_on` default False, with the reference spec opting in

Each reference `spec.yaml` would state its value explicitly, so both reference
parts keep reproducing bit-identically. NOT DONE - see the open questions in
the handover notes.
