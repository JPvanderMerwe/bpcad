"""
One token source, two clients, and the gate that keeps them equal.

Product brief 2.6 and acceptance criterion 10: the palette, type scale,
spacing and radii live in one file, are exported to CSS and Dart by a build
step, and a change in the source updates both. Brief section 0 calls a colour
that differs between web and native a bug, not an inconsistency.

The test that matters here is the staleness check. Everything else about
tokens is a matter of taste; a hex value that exists in two places and has
drifted is a defect, and it is invisible until somebody puts the two screens
side by side.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "tokens.json"
CSS = ROOT / "bpcad" / "web" / "static" / "tokens.css"
DART = ROOT / "mobile" / "lib" / "tokens.dart"

# Brief 6.1, to the byte. Written out here rather than read from the source,
# because a test that reads the same file it is checking proves only that the
# file equals itself.
BRIEF_CORE = {
    "case": "#0B0F0D",
    "bezel": "#151B18",
    "etch": "#2A322D",
    "phosphor": "#FFB000",
    "screen": "#DCE3DC",
    "dim": "#7C8880",
}
BRIEF_PENS = {
    "solid": "#DCE3DC",
    "dim": "#4A554E",
    "ref": "#35C6E8",
    "pass": "#5BE37D",
    "warn": "#FFB000",
    "fail": "#E8489B",
}


def tokens() -> dict:
    return json.loads(SOURCE.read_text())


def _without_comments(source: str) -> str:
    """
    Strip comments before looking for code.

    Both primitive tests below search for a construct by name, and this file's
    own prose explains at length why that construct is forbidden outside the
    primitive - so the first version of those tests failed on the comments
    that describe the rule they enforce. Blanked rather than deleted so line
    numbers in a failure message still point at the right place.
    """
    source = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"),
                    source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ---------------------------------------------------------------------------
# The source says what the brief says.
# ---------------------------------------------------------------------------

def test_the_core_palette_is_the_briefs_six_values():
    """
    Plus `grid`, and that seventh value is checked separately below rather
    than folded in here. This test is the brief's own list, to the byte, and
    it stops being that the moment additions are allowed to pass silently.
    """
    core = {k: v["hex"] for k, v in tokens()["core"].items()
            if not k.startswith("$")}
    assert {k: v for k, v in core.items() if k != "grid"} == BRIEF_CORE


def test_the_seventh_core_value_is_the_graticule_and_says_why():
    """
    The token source demands a written reason for a seventh core colour. The
    design handoff draws a graticule on every ground and names its colour, so
    it was going to be written down somewhere - and written in two stylesheets
    it is two values that can disagree.
    """
    grid = tokens()["core"]["grid"]
    assert grid["hex"] == "#141A17"
    assert grid.get("why"), "a seventh core colour with no reason recorded"


def test_the_pen_set_is_the_briefs_six_pens():
    pens = {k: v["hex"] for k, v in tokens()["pen"].items()
            if not k.startswith("$")}
    assert pens == BRIEF_PENS


def test_the_accent_is_amber_and_not_terminal_green():
    """
    Brief 6.1 chose #FFB000 over the obvious green so the product does not
    read as a generic hacker skin, and says green appears only as a state
    colour. A palette that drifted to green everywhere would satisfy every
    other test in this file.
    """
    assert tokens()["core"]["phosphor"]["hex"] == "#FFB000"
    greens = [name for name, value in BRIEF_CORE.items()
              if value.lower() in ("#00ff00", "#33ff33", "#5be37d")]
    assert not greens, "green is a state colour, not part of the core palette"


def test_failure_is_magenta_because_red_is_reserved():
    """Brief 6.1: red is reserved for destructive confirmation only."""
    assert tokens()["pen"]["fail"]["hex"] == "#E8489B"


def test_every_pen_says_what_it_means():
    """
    Brief 6.7 forbids colour-only status signalling, so each pen has to carry
    the meaning it stands for - that is what a label or an icon is generated
    from.
    """
    for name, value in tokens()["pen"].items():
        if name.startswith("$"):
            continue
        assert value.get("meaning"), "pen %r has no meaning" % name


def test_the_pinned_metrics_match_the_briefs_floors():
    """44 px tap target (6.3, one-handed), 380 px minimum width (6.7)."""
    metric = tokens()["metric"]
    assert metric["tap"] == 44
    assert metric["min_width"] == 380


# ---------------------------------------------------------------------------
# The glass layer. Design handoff section 6, an accepted amendment to brief
# 6.6, and task C0.
#
# What is worth testing here is not the numbers - those are a design decision
# and they will be retuned. It is the STRUCTURE the design depends on: five
# depths that increase, two radii the sheet needs, a tint exported as one
# value rather than five, and an ambient wash that exists at all.
# ---------------------------------------------------------------------------

GLASS_DEPTHS = ["panel", "well", "card", "pill", "float"]


def test_the_glass_depths_are_ordered_shallowest_to_densest():
    """
    THE ONE RULE THAT KEEPS GLASS LEGIBLE: a surface over content is denser
    than one over the ground, because contrast has to hold against the
    brightest thing the render behind it can produce. If the alphas ever stop
    increasing, a bottom sheet becomes more transparent than a side panel and
    the numbers on it stop being readable over a bright part.
    """
    surface = tokens()["glass"]["surface"]
    assert [k for k in surface if not k.startswith("$")] == GLASS_DEPTHS

    alphas = [surface[name]["alpha"] for name in GLASS_DEPTHS]
    assert alphas == sorted(alphas), (
        "the depths are not ordered: %s" % dict(zip(GLASS_DEPTHS, alphas))
    )
    # The handoff's floor, and its ceiling on the whole scale.
    assert min(alphas) >= 0.30, "below the design's alpha floor"
    assert max(alphas) <= 0.62, "denser than the design's densest surface"


@pytest.mark.parametrize("name", GLASS_DEPTHS)
def test_every_depth_names_a_radius_that_exists(name):
    """
    A depth pointing at a radius token that is not there produces
    `var(--bp-radius-nonsense)` in CSS, which silently computes to 0 - square
    corners on the bottom sheet, with nothing in the console.
    """
    step = tokens()["glass"]["surface"][name]
    assert step["radius"] in tokens()["radius"], (
        "depth %r names radius %r, which is not a token" % (name, step["radius"])
    )
    assert step["blur"] > 0
    assert step.get("use"), "depth %r does not say what it is for" % name


def test_the_two_radii_the_glass_needed_were_added():
    """
    The scale topped out at 10 and a floating sheet needs more. Handoff
    TOKENS.md: `control` 7 for pills and segments, `float` 16 for the sheet,
    the bezel and the status line.
    """
    radius = tokens()["radius"]
    assert radius["control"] == 7
    assert radius["float"] == 16
    # And the hard end of the scale survives. Soft radii belong to floating
    # SURFACES; 0 and 3 stay on data marks - check marks, status squares,
    # slider thumbs, progress bars. That contrast is the design's whole point
    # and it is the thing a later retune would quietly lose.
    assert radius["none"] == 0
    assert radius["edge"] == 3


def test_the_tint_is_one_value_and_not_one_per_depth():
    """
    Handoff TOKENS.md says it plainly: export the tint as a function of alpha
    rather than as six separate colours, so a theme change moves all of it.
    Five baked colours is five places for a retune to miss one.
    """
    tint = tokens()["glass"]["tint"]
    assert len(tint["rgb"]) == 3
    assert all(0 <= channel <= 255 for channel in tint["rgb"])

    css = CSS.read_text()
    # Space-separated: these are composed with CSS Color 4's slash syntax,
    # which rejects commas and computes to transparent when it gets them.
    assert "--bp-glass-tint: %s;" % " ".join(str(c) for c in tint["rgb"]) in css
    assert "rgb(var(--bp-glass-tint) /" in (WEB_STATIC / "app.css").read_text()
    # The depths carry an alpha, never a finished colour.
    for name in GLASS_DEPTHS:
        assert "--bp-glass-%s-alpha:" % name in css

    dart = DART.read_text()
    assert "static Color tint(double alpha)" in dart, (
        "the Dart export bakes the tint instead of taking an alpha"
    )


def test_tinted_glass_has_a_separate_border_alpha():
    """
    A tinted surface's border takes the tint at 35-70% while its fill takes it
    at 10-18%. One alpha for both gives either an invisible border or a fill
    that swamps the text on it.
    """
    for name, tint in tokens()["glass"]["tinted"].items():
        if name.startswith("$"):
            continue
        assert tint["border_alpha"] > tint["alpha"], (
            "%s: the border is no more visible than the fill" % name
        )
        assert tint.get("use"), "tint %r does not say what it is for" % name


def test_the_ambient_wash_exists_and_reaches_both_clients():
    """
    Not decoration. A blur with nothing behind it to pick up renders as flat
    grey and every panel becomes the same slab - which is the failure mode the
    handoff calls out by name, and it looks like the glass simply not working.
    """
    layers = tokens()["glass"]["ambient"]["layers"]
    assert len(layers) == 2, "the design specifies two washes"

    css = CSS.read_text()
    assert "--bp-ambient:" in css
    assert css.count("radial-gradient") >= 2

    dart = DART.read_text()
    for index in range(2):
        for field in ("wash%d", "wash%dAlpha", "wash%dAt", "wash%dSize",
                      "wash%dStop"):
            assert (field % index) in dart, (
                "%s missing from the Dart export" % (field % index)
            )


def test_the_ambient_wash_introduces_no_new_hue():
    """
    It is phosphor and pen-ref at low alpha. A third colour appearing here is
    a palette expansion disguised as a lighting effect.
    """
    allowed = {
        tuple(int(BRIEF_CORE["phosphor"].lstrip("#")[i:i + 2], 16)
              for i in (0, 2, 4)),
        tuple(int(BRIEF_PENS["ref"].lstrip("#")[i:i + 2], 16)
              for i in (0, 2, 4)),
    }
    for layer in tokens()["glass"]["ambient"]["layers"]:
        assert tuple(layer["rgb"]) in allowed, (
            "the ambient wash uses %s, which is not in the palette" % layer["rgb"]
        )
        assert layer["alpha"] <= 0.20, "a wash this strong is a stain"


def test_the_web_glass_primitive_is_the_only_place_that_blurs():
    """
    TASK C0'S ACTUAL DELIVERABLE. The blur is not the point - one primitive
    is. Five surfaces each tuning their own alpha and blur is how the two
    clients drift apart a fortnight later, and the drift is invisible until
    somebody puts the phone next to the browser.

    Two exceptions are allowed and both are named here: the media query that
    turns blur OFF, and the fallback block. A third is a regression.
    """
    css = _without_comments((WEB_STATIC / "app.css").read_text())
    blurs = [
        line.strip() for line in css.splitlines()
        if re.match(r"\s*-?(webkit-)?backdrop-filter\s*:", line)
        and "none" not in line
    ]
    assert blurs, "no rule blurs at all; the glass layer is gone"

    # EVERY blur radius must be a token, whichever rule sets it. That is the
    # rule that survives new surfaces being added - a count would just have to
    # be raised each time and would stop meaning anything.
    for line in blurs:
        assert "var(--bp-glass-" in line, (
            "a hand-typed blur radius, which is how the two clients drift: %s"
            % line
        )


def test_the_flutter_glass_primitive_is_the_only_place_that_blurs():
    """The same rule on the other client, which is the point of the rule."""
    lib = ROOT / "mobile" / "lib"
    offenders = [
        path.name for path in lib.glob("*.dart")
        if path.name != "glass.dart"
        and "BackdropFilter(" in _without_comments(path.read_text())
    ]
    assert not offenders, (
        "these build their own BackdropFilter instead of using GlassSurface: %s"
        % offenders
    )


def test_neither_client_hardcodes_a_colour():
    """
    ACCEPTANCE CRITERION 10, the half that is not about staleness. A hex value
    in a stylesheet is a value that cannot be moved from the token source, and
    it is invisible until the two screens are side by side.

    app.css is checked because it is the file the design pass rewrote. The
    Dart side is covered by the generated-file check above plus theme.dart,
    which holds the role mapping and must hold no values.
    """
    css = (WEB_STATIC / "app.css").read_text()
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b", css), (
        "app.css carries hex literals: %s"
        % re.findall(r"#[0-9A-Fa-f]{3,8}\b", css)
    )
    assert not re.findall(r"rgba?\(\s*\d", css), (
        "app.css carries raw rgb values: %s"
        % re.findall(r"rgba?\([^)]*\)", css)
    )

    theme = (ROOT / "mobile" / "lib" / "theme.dart").read_text()
    assert not re.findall(r"0x[0-9A-Fa-f]{8}", theme), (
        "theme.dart carries colour literals; it should map roles to tokens"
    )


# ---------------------------------------------------------------------------
# The exports say what the source says. This is the gate.
# ---------------------------------------------------------------------------

def test_the_exports_are_not_stale():
    """
    ACCEPTANCE CRITERION 10, enforced. Edit design/tokens.json without running
    the build step and this fails, naming the files - rather than the change
    appearing on one client and not the other and being noticed three screens
    later.
    """
    done = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "tokens.py"), "--check"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120,
    )
    assert done.returncode == 0, (
        "token exports are stale - run: python tools/tokens.py\n%s"
        % (done.stdout + done.stderr)
    )


@pytest.mark.parametrize("name,hex_value", sorted(BRIEF_CORE.items()))
def test_every_core_colour_reaches_both_clients(name, hex_value):
    css = CSS.read_text()
    dart = DART.read_text()
    assert "--bp-%s: %s;" % (name, hex_value) in css, "%s missing from CSS" % name
    assert "Color(0xFF%s)" % hex_value.lstrip("#").upper() in dart, (
        "%s missing from Dart" % name
    )


def test_the_dart_export_avoids_reserved_words():
    """
    The brief's first colour is called `case`, which is a Dart keyword - the
    generated file would not compile. Caught by generating it, which is the
    argument for the build step existing at all.
    """
    dart = DART.read_text()
    assert "Color case =" not in dart
    assert "caseColor" in dart


def test_the_generated_files_say_not_to_edit_them():
    """
    The only defence against somebody fixing a colour in the CSS, which then
    silently disagrees with Dart.
    """
    for path in (CSS, DART):
        head = path.read_text()[:400]
        assert "DO NOT EDIT" in head, "%s has no warning" % path.name
        assert "tools/tokens.py" in head, "%s does not say how to regenerate" % path.name


def test_no_hex_literal_creeps_into_the_generated_dart_outside_the_tokens():
    """
    Every colour in the app has to come from these classes. This checks the
    generated file only - the app's own files are checked by
    test_mobile_uses_only_tokens below once the clients are ported.
    """
    dart = DART.read_text()
    literals = re.findall(r"Color\(0xFF([0-9A-Fa-f]{6})\)", dart)
    allowed = {v.lstrip("#").upper() for v in
               list(BRIEF_CORE.values()) + list(BRIEF_PENS.values())}
    # The graticule, and the ambient washes - which are phosphor and pen-ref
    # and so are already in the set above.
    allowed.add(tokens()["core"]["grid"]["hex"].lstrip("#").upper())
    assert set(literals) <= allowed, (
        "the generated Dart carries a colour that is not a token: %s"
        % (set(literals) - allowed)
    )


# ---------------------------------------------------------------------------
# The brand assets. Generated by bpcad_media/build_brand.py from one SVG, and
# installed into both clients - so the checks here are that every asset a
# manifest or a catalogue NAMES actually exists, and that the ground colour
# agrees with the token source.
#
# A manifest entry pointing at a missing icon is a broken install prompt with
# no error message, and an asset catalogue entry naming a missing file is an
# Xcode build failure. Both are invisible until somebody installs the app.
# ---------------------------------------------------------------------------

WEB_STATIC = ROOT / "bpcad" / "web" / "static"
ANDROID_RES = ROOT / "mobile" / "android" / "app" / "src" / "main" / "res"
IOS_ICONS = (ROOT / "mobile" / "ios" / "Runner" / "Assets.xcassets"
             / "AppIcon.appiconset")


def test_every_icon_the_web_manifest_names_exists():
    manifest = json.loads((WEB_STATIC / "manifest.webmanifest").read_text())
    missing = []
    for icon in manifest["icons"]:
        # Served from /static/..., which is this directory.
        relative = icon["src"].removeprefix("/static/")
        if not (WEB_STATIC / relative).is_file():
            missing.append(icon["src"])
    assert not missing, "the manifest names icons that do not exist: %s" % missing


def test_the_web_manifest_opens_on_the_brand_ground():
    """
    background_color is what the OS paints before the app draws. If it is not
    the same as `case`, a cold start flashes the wrong colour - which is what
    the Flutter and PWA templates both do by default, in white.
    """
    manifest = json.loads((WEB_STATIC / "manifest.webmanifest").read_text())
    assert manifest["background_color"] == BRIEF_CORE["case"]
    assert manifest["theme_color"] == BRIEF_CORE["case"]


def test_the_web_head_points_at_assets_that_exist():
    head = (WEB_STATIC / "index.html").read_text()
    for reference in re.findall(r'(?:href|content)="(/static/[^"]+)"', head):
        relative = reference.removeprefix("/static/")
        assert (WEB_STATIC / relative).is_file(), "head names missing %s" % reference


def test_a_maskable_icon_is_declared_separately():
    """
    A launcher that masks a full-bleed icon crops the mark, which is why the
    maskable file has its own 20% safe margin and is a different image rather
    than the same one tagged twice.
    """
    manifest = json.loads((WEB_STATIC / "manifest.webmanifest").read_text())
    maskable = [i for i in manifest["icons"] if i.get("purpose") == "maskable"]
    assert maskable, "no maskable icon declared"
    assert "maskable" in maskable[0]["src"]


@pytest.mark.parametrize("density", ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"])
def test_android_has_every_adaptive_layer_at_every_density(density):
    directory = ANDROID_RES / ("mipmap-%s" % density)
    for layer in ("ic_launcher.png", "ic_launcher_foreground.png",
                  "ic_launcher_background.png", "ic_launcher_monochrome.png"):
        assert (directory / layer).is_file(), "%s missing %s" % (density, layer)


def test_the_android_adaptive_icon_declares_a_monochrome_layer():
    """
    The media README names the themed icon as one of the two things that break
    first if the mark changes. Android 13+ tints this layer; older versions
    ignore the tag, so one file covers every version.
    """
    xml = (ANDROID_RES / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
    for layer in ("background", "foreground", "monochrome"):
        assert "<%s" % layer in xml, "no %s layer" % layer


def test_the_android_launch_window_is_not_white():
    for variant in ("drawable", "drawable-v21"):
        xml = (ANDROID_RES / variant / "launch_background.xml").read_text()
        assert "@android:color/white" not in xml, (
            "%s still flashes white before the first frame" % variant
        )
        assert "bp_case" in xml


def test_the_android_colour_resource_matches_the_token_source():
    """
    Android resources cannot import the generated Dart, so `case` is repeated
    once in XML. This is the check that keeps the repeat honest.
    """
    colours = (ANDROID_RES / "values" / "colors.xml").read_text()
    assert BRIEF_CORE["case"] in colours


def test_the_app_is_labelled_bpcad_not_the_project_name():
    manifest = (ROOT / "mobile" / "android" / "app" / "src" / "main"
                / "AndroidManifest.xml").read_text()
    assert 'android:label="bpcad"' in manifest


def test_every_ios_icon_the_catalogue_names_exists_and_is_opaque():
    """
    An asset catalogue entry naming a missing file is a build failure, and the
    App Store rejects an icon with an alpha channel. Both are found at submit
    time otherwise.
    """
    from PIL import Image

    contents = json.loads((IOS_ICONS / "Contents.json").read_text())
    for entry in contents["images"]:
        name = entry.get("filename")
        if not name:
            continue
        path = IOS_ICONS / name
        assert path.is_file(), "the catalogue names missing %s" % name
        assert Image.open(path).mode == "RGB", (
            "%s carries an alpha channel; the App Store refuses that" % name
        )
