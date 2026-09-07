# Tokens

Everything here already lives in `design/tokens.json` except the four additions marked
**NEW**. Regenerate exports with `python tools/tokens.py`; `tests/test_tokens.py`
fails if an export is stale. Neither client hardcodes a value — brief 2.6, acceptance
criterion 10.

## Core

| Token | Hex | CSS | Dart | Used for in this design |
|---|---|---|---|---|
| case | #0B0F0D | `--case` | `Tokens.case_` | app ground, phone screen, graticule base |
| bezel | #151B18 | `--bezel` | `Tokens.bezel` | the flat fallback when backdrop-filter is unsupported |
| etch | #2A322D | `--etch` | `Tokens.etch` | slider tracks, progress tracks, hairlines on flat chrome |
| phosphor | #FFB000 | `--phosphor` | `Tokens.phosphor` | primary action, active state, focus ring, assumptions, credits |
| screen | #DCE3DC | `--screen` | `Tokens.screen` | primary text |
| dim | #7C8880 | `--dim` | `Tokens.dim` | labels, secondary text, inactive |

Graticule line colour in the prototype is `#141a17` — that is `case` lightened, and it
should become a token (`grid`) since `bpcad_media/README.md` already names it.

## Pens — inside the 3D canvas and annotation only

| Pen | Hex | Meaning | Paired mark in the UI |
|---|---|---|---|
| solid | #DCE3DC | the printable part | — |
| dim | #4A554E | grid, graticule, construction | — |
| ref | #35C6E8 | reference body, never printed | word "ref", "not printed" |
| pass | #5BE37D | check passed | `✓` |
| warn | #FFB000 | tolerance risk, uncalibrated | `!` |
| fail | #E8489B | failed check, out of bounds | `✗` |

Never borrow a pen for chrome, and never let a pen carry status alone — brief 6.7.

## Type

| Step | px | Where in this design |
|---|---|---|
| micro | 10.5 | section labels, notes, version strings, badges |
| label | 12 | field labels, chips, tags, buttons, stage notes |
| body | 13.5 | primary buttons, prose body, command line on web |
| reading | 15 | composer textarea, account name |
| figure | 17 | parameter values in the sheet, plan prices, screen titles |
| title | 21 | screen headings |
| display | 27 | wordmark, credit count |

Mono = IBM Plex Mono for all chrome, labels, numbers, buttons and the command line.
Prose = Inter for anything over two lines. `tabular-nums` on every numeric field.
Sentence case. No tracked-out caps.

## Spacing, radius, metrics

Spacing 2 / 4 / 8 / 12 / 16 / 24 / 32 / 48 — density 1.25×, do not tighten.

| Radius | px | Applies to |
|---|---|---|
| none | 0 | status squares, slider thumbs, progress bars, check marks |
| edge | 3 | flat data chrome |
| panel | 6 | legacy — superseded by `control`/`card` on glass |
| card | 10 | glass cards and panels |
| **control** | **7** | **NEW** — pills, segments, small glass controls |
| **float** | **16** | **NEW** — bottom sheet, device bezel, status line |

Tap target 44 minimum. Supported width 380 minimum.

## Glass — **NEW**

```
glass.tint      rgba(30, 38, 34, α)
glass.hairline  rgba(220, 227, 220, 0.10 … 0.16)
glass.highlight inset 0 1px 0 rgba(220, 227, 220, 0.08)
glass.blur      14 … 26 px, saturate(150%)
```

Alpha per surface is tabulated in README section 6. Export `glass.tint` as a function
of alpha rather than as six separate colours, so a theme change moves all of it.

Ambient light behind glass (both viewport containers):

```
radial-gradient(120% 60% at 78%  4%, rgba(255,176,0,.16), transparent 62%)
radial-gradient( 90% 44% at 10% 96%, rgba(53,198,232,.10), transparent 66%)
```

Without it the blur has nothing to pick up and every panel reads as flat grey.

Fallback: `@supports not (backdrop-filter: blur(1px))` → flat `bezel` at full opacity
with the `etch` hairline. On Flutter this is `BackdropFilter`; cap it to the sheet, tab
bar, bezel and pills if a scrolling library list drops frames.
