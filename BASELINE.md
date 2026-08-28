# Level-1 success-rate baseline

Measured before any tuning, as the build brief requires, then measured again
after the one change it pointed to. Raw rows in `baseline/results.jsonl`, the
first measurement in `baseline/results-before-fix.jsonl`, prompts in
`baseline/prompts.txt` (identical between the two runs).

    machine   laptop - Intel Core Ultra 7 258V, 32 GB, 100% CPU inference
    models    qwen2.5-coder:7b primary, hermes3:latest small
    command   bpcad gen "<prompt>" --no-render

## Result

|                     | before      | after        |
|---------------------|-------------|--------------|
| code fingerprint    | 42744ae2dd8e | 2a64f25a3ab9 |
| **success rate**    | **5/10 (50%)** | **10/10 (100%)** |
| vent                | 2/5         | 5/5          |
| keyring             | 3/5         | 5/5          |
| median wall-clock   | 267.6s      | **102.0s**   |
| median attempts     | 4.5         | **1.0**      |
| slowest run         | 864.5s      | **132.1s**   |

Every one of the ten parts verified: watertight, expected body count, sensible
volume. Eight of ten now succeed on the FIRST attempt; the two that take two
attempts (runs 3 and 5) are both cases where the model asked for a blade count
the frame cannot fit, and recovered from an error that named what would fit.

## What changed

Nothing in the prompts, the model, or the agent loop. Six template defaults
that were pinned to the reference part's dimensions now derive from the frame:

| default | derives from | at the reference |
|---|---|---|
| `n_blades` | aperture width, capped at what the linkage fits | 4 |
| `blade_chord_mm` | 0.82 x blade pitch | 13.94 (spec pins 14.0) |
| `crank_r_mm` | chord/2 - 2.0 | exactly 5.00 |
| `grip_len_mm` | frame depth, floored AND capped | 20.08 (spec pins 20.0) |
| `grip_blade` | the most central blade | exactly 2 |
| `logo_on` | - | now false |

Both reference parts still reproduce their stored STL bit for bit, because each
`spec.yaml` states its values explicitly.

## Why the first measurement mattered

The 50% run is the reason this fix exists and the reason it is the right one.
Before it, the obvious diagnosis was "a 7B model at 7 tokens/sec is not good
enough". The data said otherwise: not one of the five failures was the model
misreading a prompt, inventing a template, or emitting unparseable JSON. Every
single one was a fixed default that only held at one frame size.

It also showed the cascade. Deriving the chord alone would have fixed nothing -
the model shrinks the frame, the chord is corrected, and the fixed crank radius
then fails; correct that and the fixed blade count fails. Four levels, only
visible by running it.

## Two measurement faults, both corrected

**The first attempt at the before-run was discarded.** Two harnesses were
running at once and the source changed while they ran, so early and late runs
were testing different programs. The harness now fingerprints the source and
records it on every row.

**One after-run reported 73066 seconds.** The machine suspended overnight and
`time.time()` counted the sleep. bpcad's own `run.json` times with
`time.monotonic()`, which excludes suspend, and gives 100.1 seconds for that
run - 1 attempt, valid part. The analysis prefers the in-process timing and
prints the discrepancy rather than quietly substituting it.

## The honest limits of this number

Ten prompts is a small sample and they are all near the two templates' home
ground. 100% means "these ten worked", not "this always works". A part neither
template covers still has to go through level 2, which is a harder task for a
small model and is not exercised here at all.

The two-attempt runs cost about 132 seconds against 91 for a clean first hit,
so the cost of a wrong turn is now one cheap retry rather than a six-minute
dead end.
