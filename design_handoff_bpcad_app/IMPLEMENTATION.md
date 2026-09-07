# Implementation order

Against brief section 9. Client work only — Track 2. Nothing here starts before the
foundation tasks (token exports, API skeleton, turntable renderer) are done, and no
task puts geometry logic in a client.

Confirm each phase with JP before starting it, per brief section 9.

## C0 · Tokens and the glass layer

Add `radius.control`, `radius.float`, `glass.*` and `grid` to `design/tokens.json`,
regenerate both exports, extend `tests/test_tokens.py` to cover them.

Build one glass primitive per client — a surface widget/component taking an alpha step
and a radius step — and one ambient-light background. Everything else composes those
two. If a screen sets `backdrop-filter` inline, that is the bug this task prevents.

**Done when:** a token change moves the same surface on web and native, and the
no-backdrop-filter fallback renders the flat `bezel` variant.

## C1 · Web workspace shell

Three-zone grid, status line, the command line wired to the real parser, viewport
mounting a glTF from the API. Left column: prompt, photos, assumptions, versions,
scrollback. Right: parameters, dimension report, checks, export.

**Done when:** acceptance criterion 1 — a visitor with no account types a description,
generates a part and downloads a valid STL.

## C2 · Native shell

Auth, printer profile onboarding, library, composer with camera capture, the
server-rendered turntable viewer, checks, download, and the bottom sheet with its three
snap heights. **Turntable, not a live 3D engine** — brief 2.3 phase 1.

**Done when:** acceptance criterion 11 — installs and runs on a physical iOS and
Android device with capture, turntable, checks and offline access to downloaded files.

## C3 · The composer and the assumption contract

One input for words and photos on both clients. Parsed values render as pass chips,
inferred values as editable amber assumptions, and the detected pipeline is stated
before the user commits a credit.

**Done when:** no generated part contains a dimension the user was not shown, and
brief 4.5's standards table resolves "M4 clearance hole" and "608 bearing seat" without
guessing.

## C4 · Checks, and failure as a first-class state

The check list, the pen legend, the geometry highlight, and the failure copy pattern in
COPY.md. A part that fails motion validation is presented as failed with the reason —
never as a working part.

**Done when:** acceptance criterion 6 — a failing part shows the specific geometry and
a stated fix.

## C5 · Parameters and incremental rebuild

Sliders, tabular values, dirty indicator, rebuild without a page transition, progress on
the affected geometry rather than a global spinner, and version history where editing
never destroys the last good result.

**Done when:** acceptance criterion 3's dimension report matches measurements taken on
the exported solid, at every parameter value.

## C6 · Scaling and the reference body

The mesh `unscaled` gate, the one-real-measurement flow, and the cyan reference body in
its obviously non-printable treatment, never exported.

**Done when:** acceptance criteria 2 and 7.

## C7 · Motion demonstration

The joint sweeping its declared range in the viewport. Rendered loop on native phase 1,
live geometry on web.

**Done when:** acceptance criterion 4 — every joint primitive can be seen moving on both
platforms.

## C8 · Quality floor

Usable one-handed at 380 px, keyboard reachable on desktop with `phosphor` focus rings,
viewport orbit and zoom on keys, correct under `prefers-reduced-motion`, contrast checked
against the dark palette, and no status carried by colour alone.

**Done when:** acceptance criterion 12.

## C9 · Then

Web library and part-family generator pages, native push on completion, the native glTF
viewer upgrade (brief 2.3 phase 2), PWA install and offline shell.

---

## Things to raise as BLOCKERS rather than decide

1. Flutter or React Native (brief question 1).
2. Store IAP rules for credit purchases in the apps (brief 2.4, question 3) — do not
   build a purchase or a link-out before this is answered.
3. Whether the CadQuery script is visible to free users (question 5).
4. Whether the glass amendment and the two new radius tokens are accepted into
   brief 6.6 and `design/tokens.json`.
5. Live 3D on native is phase 2. If the prototype's orbitable viewport is expected in
   the first release, that contradicts brief 2.3 and needs JP's call.
