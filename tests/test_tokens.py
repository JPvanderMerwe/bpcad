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


# ---------------------------------------------------------------------------
# The source says what the brief says.
# ---------------------------------------------------------------------------

def test_the_core_palette_is_the_briefs_six_values():
    core = {k: v["hex"] for k, v in tokens()["core"].items()
            if not k.startswith("$")}
    assert core == BRIEF_CORE


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
