#!/usr/bin/env python3
"""
bpcad brand asset generator.

Emits the icon (master + small-size variant + transparent mark), platform icon
exports for iOS / Android / web, a wordmark, a splash logo and a social image.

Single source of truth for geometry and colour so every asset stays identical.
Regenerate with:  python3 build_brand.py
"""

import io
import math
import os

import cairosvg
from PIL import Image, ImageDraw
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

# PATHS RESOLVED AGAINST THIS FILE, NOT THE MACHINE IT WAS WRITTEN ON.
#
# These were absolute paths into the sandbox that produced the first assets
# (/mnt/user-data/outputs and /home/claude/jbm), which do not exist on any
# other computer - so the generator could not be re-run, and the README's
# instruction to re-run it was untrue. The assets now land in `build/` beside
# this script.
#
# The font is only needed for the wordmark, whose glyphs are converted to
# outlines so the font is never redistributed. It is looked for in a few
# ordinary places and the wordmark is skipped with a message if it is not
# found, rather than taking the whole run down with it.
import glob as _glob

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build")


def _find_font(name):
    candidates = [
        os.path.join(HERE, "fonts", name),
        os.path.expanduser("~/.local/share/fonts/%s" % name),
        "/usr/share/fonts/truetype/jetbrains-mono/%s" % name,
    ]
    for pattern in ("/snap/*/*/jbr/lib/fonts/%s" % name,
                    os.path.expanduser("~/Downloads/**/jbr/lib/fonts/%s" % name)):
        candidates.extend(sorted(_glob.glob(pattern, recursive=True)))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


FONT_BOLD = _find_font("JetBrainsMono-Bold.ttf")
FONT_REG = _find_font("JetBrainsMono-Regular.ttf")

# ---------------------------------------------------------------- tokens
CASE = "#0B0F0D"      # app background / icon field
BEZEL = "#151B18"     # panels
ETCH = "#2A322D"      # rules and borders
GRID = "#182019"      # graticule
PHOSPHOR = "#FFB000"  # amber accent
SCREEN = "#DCE3DC"    # the printable part, primary text
DIM = "#7C8880"       # secondary text
PEN_DIM = "#4A554E"   # construction geometry

ISO = math.tan(math.radians(30))  # 0.5774, isometric y-drop per unit of x

S = 1024  # master canvas


def iso_cube(cx, cy, w):
    """Vertices of an isometric cube of half-width w, centred on (cx, cy)."""
    h = w * ISO
    return {
        "T": (cx, cy - 2 * h),
        "UR": (cx + w, cy - h),
        "LR": (cx + w, cy + h),
        "B": (cx, cy + 2 * h),
        "LL": (cx - w, cy + h),
        "UL": (cx - w, cy - h),
        "C": (cx, cy),
    }


def pts(*p):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in p)


def mark_svg(cx, cy, w, stroke, inner, cut=0.46, mono=False):
    """The bpcad mark: an isometric solid with a quarter section cut away, the
    exposed internal faces lit in amber.

    A section view is the drawing convention for showing what is inside a part,
    which is exactly what the product does. The silhouette stays a clean hexagon
    so it still reads at 16 px; the amber notch carries the recognition.

    mono=True renders one colour for Android themed icons.
    """
    part = "#FFFFFF" if mono else SCREEN
    h = w * ISO
    C = (cx, cy)                     # near-top corner, where the cut is taken
    u = (-w, -h)                     # C -> upper-left
    v_ = (w, -h)                     # C -> upper-right
    d = (0.0, 2 * h)                 # C -> bottom

    def P(*terms):
        x, y = C
        for vec, k in terms:
            x += vec[0] * k
            y += vec[1] * k
        return (x, y)

    f = cut
    UL, UR, T = P((u, 1)), P((v_, 1)), P((u, 1), (v_, 1))
    B = P((d, 1))
    LL, LR = P((u, 1), (d, 1)), P((v_, 1), (d, 1))
    inner_pt = P((u, f), (v_, f), (d, f))

    if mono:
        a_up, a_right, a_left = "#FFFFFF", "#FFFFFF", "#FFFFFF"
        f_top = f_left = f_right = "none"
    else:
        a_up, a_right, a_left = PHOSPHOR, "#C98A08", "#8F6206"
        f_top, f_left, f_right = "#1F2723", "#161D19", "#0F1512"

    g = []
    # remaining outer faces, each an L-shape where the cut bit off a corner
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((u, f)), UL, T, UR, P((v_, f)), P((u, f), (v_, f))), f_top))
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((u, f)), UL, LL, B, P((d, f)), P((u, f), (d, f))), f_left))
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((v_, f)), UR, LR, B, P((d, f)), P((v_, f), (d, f))), f_right))
    # the three exposed internal faces of the cut
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((d, f)), P((d, f), (u, f)), inner_pt, P((d, f), (v_, f))), a_up))
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((u, f)), P((u, f), (v_, f)), inner_pt, P((u, f), (d, f))), a_left))
    g.append('<polygon points="%s" fill="%s"/>' % (
        pts(P((v_, f)), P((v_, f), (u, f)), inner_pt, P((v_, f), (d, f))), a_right))
    if mono:  # alpha tiers keep the cut readable once the system tints it flat
        g[-2] = g[-2].replace('/>', ' fill-opacity="0.34"/>')
        g[-1] = g[-1].replace('/>', ' fill-opacity="0.62"/>')
    # what is left of the three edges that met at the cut corner
    for end, start in ((UL, P((u, f))), (UR, P((v_, f))), (B, P((d, f)))):
        g.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" x2="{end[0]:.2f}" '
            f'y2="{end[1]:.2f}" stroke="{part}" stroke-width="{inner}" '
            f'stroke-linecap="round"/>'
        )
    # silhouette
    g.append(
        f'<polygon points="{pts(T, UR, LR, B, LL, UL)}" fill="none" '
        f'stroke="{part}" stroke-width="{stroke}" stroke-linejoin="round"/>'
    )
    return "\n".join(g)


def graticule(size, step=96):
    lines = []
    n = int(size / step)
    for i in range(1, n + 1):
        p = i * step
        lines.append(
            f'<line x1="{p}" y1="0" x2="{p}" y2="{size}" stroke="{GRID}" stroke-width="2"/>'
        )
        lines.append(
            f'<line x1="0" y1="{p}" x2="{size}" y2="{p}" stroke="{GRID}" stroke-width="2"/>'
        )
    c = size / 2
    lines.append(
        f'<line x1="{c}" y1="0" x2="{c}" y2="{size}" stroke="{ETCH}" stroke-width="3"/>'
    )
    lines.append(
        f'<line x1="0" y1="{c}" x2="{size}" y2="{c}" stroke="{ETCH}" stroke-width="3"/>'
    )
    return "\n".join(lines)


def dim_line(x1, x2, y, up_to_y):
    """Drafting dimension line with extension lines and end ticks."""
    o = []
    for x in (x1, x2):
        o.append(
            f'<line x1="{x:.2f}" y1="{up_to_y:.2f}" x2="{x:.2f}" y2="{y + 26:.2f}" '
            f'stroke="{PEN_DIM}" stroke-width="4"/>'
        )
        o.append(
            f'<line x1="{x:.2f}" y1="{y - 22:.2f}" x2="{x:.2f}" y2="{y + 22:.2f}" '
            f'stroke="{PHOSPHOR}" stroke-width="8" stroke-linecap="round"/>'
        )
    o.append(
        f'<line x1="{x1:.2f}" y1="{y:.2f}" x2="{x2:.2f}" y2="{y:.2f}" '
        f'stroke="{PHOSPHOR}" stroke-width="8" stroke-linecap="round"/>'
    )
    return "\n".join(o)


def icon_master():
    body = [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        graticule(S),
        mark_svg(512, 512, 280, stroke=24, inner=17, cut=0.46),
        f'<rect x="7" y="7" width="{S-14}" height="{S-14}" fill="none" '
        f'stroke="{ETCH}" stroke-width="7"/>',
    ]
    return svg_doc(S, body)


def icon_small():
    """Simplified for 16-128 px: no graticule, no dimension line, heavier strokes."""
    body = [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        mark_svg(512, 512, 300, stroke=34, inner=24, cut=0.50),
    ]
    return svg_doc(S, body)


def mark_only(mono=False, scale=1.0):
    """Transparent mark for adaptive foregrounds, splash and themed icons."""
    w = 290 * scale
    body = [mark_svg(512, 512, w, stroke=26 * scale, inner=18 * scale,
                     cut=0.48, mono=mono)]
    return svg_doc(S, body)


def svg_doc(size, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">\n' + "\n".join(body) + "\n</svg>\n"
    )


# ---------------------------------------------------------------- wordmark
def glyph_paths(text, font_path, letterspace=0.0):
    font = TTFont(font_path)
    upem = font["head"].unitsPerEm
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    d = []
    x = 0.0
    for ch in text:
        gname = cmap[ord(ch)]
        spen = SVGPathPen(gs)
        tpen = TransformPen(spen, (1, 0, 0, -1, x, 0))
        gs[gname].draw(tpen)
        p = spen.getCommands()
        if p:
            d.append(p)
        x += hmtx[gname][0] + letterspace * upem
    return " ".join(d), x, upem


def wordmark_svg(colour=SCREEN, cursor=PHOSPHOR, height=200):
    d, adv, upem = glyph_paths("bpcad", FONT_BOLD, letterspace=-0.01)
    scale = height / upem
    cap = upem * 0.73
    pad = height * 0.18
    text_w = adv * scale
    cur_w = height * 0.52
    cur_gap = height * 0.16
    total_w = text_w + cur_gap + cur_w + pad * 2
    total_h = height + pad * 2
    baseline = pad + cap * scale
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" '
        f'height="{total_h:.0f}" viewBox="0 0 {total_w:.0f} {total_h:.0f}">\n'
        f'<g transform="translate({pad:.2f},{baseline:.2f}) scale({scale:.5f})">\n'
        f'<path d="{d}" fill="{colour}"/>\n</g>\n'
        f'<rect x="{pad + text_w + cur_gap:.2f}" y="{pad + (cap*scale) - height*0.62:.2f}" '
        f'width="{cur_w:.2f}" height="{height*0.62:.2f}" fill="{cursor}"/>\n'
        f'</svg>\n'
    )


# ---------------------------------------------------------------- raster
def png(svg_str, path, w, h=None, bg=None):
    cairosvg.svg2png(
        bytestring=svg_str.encode(), write_to=path,
        output_width=w, output_height=h or w, background_color=bg,
    )


def rounded(path_in, path_out, radius_ratio=0.22):
    im = Image.open(path_in).convert("RGBA")
    w, h = im.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=int(w * radius_ratio), fill=255
    )
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    out.save(path_out)


def pad_canvas(svg_str, path, size, inner_ratio):
    """Render the mark inside a safe zone on a full-bleed field (maskable icons)."""
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=svg_str.encode(), write_to=buf,
                     output_width=int(size * inner_ratio),
                     output_height=int(size * inner_ratio))
    fg = Image.open(buf).convert("RGBA")
    base = Image.new("RGBA", (size, size), CASE)
    off = (size - fg.width) // 2
    base.alpha_composite(fg, (off, off))
    base.save(path)


def social_image():
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), CASE)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=GRID, width=1)
    d.rectangle([24, 24, W - 25, H - 25], outline=ETCH, width=3)

    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark_only().encode(), write_to=buf,
                     output_width=300, output_height=300)
    mk = Image.open(buf).convert("RGBA")
    im.paste(mk, (96, (H - 300) // 2), mk)

    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=wordmark_svg(height=150).encode(), write_to=buf,
                     output_height=190)
    wm = Image.open(buf).convert("RGBA")
    im.paste(wm, (452, 214), wm)

    from PIL import ImageFont
    f = ImageFont.truetype(FONT_REG, 27)
    d.text((464, 400), "Describe a part. Print a part that fits.", font=f, fill=SCREEN)
    f2 = ImageFont.truetype(FONT_REG, 22)
    d.text((464, 444), "parametric CAD, working joints, real dimensions",
           font=f2, fill=DIM)
    im.save(f"{OUT}/social/og-image-1200x630.png")
    im.resize((600, 315), Image.LANCZOS).save(f"{OUT}/social/twitter-600x315.png")


# ---------------------------------------------------------------- main
def main():
    for sub in ("source", "ios", "android", "web", "splash", "social", "wordmark"):
        os.makedirs(f"{OUT}/{sub}", exist_ok=True)

    master, small = icon_master(), icon_small()
    mark, mark_mono = mark_only(), mark_only(mono=True)
    wm_light = wordmark_svg(colour=SCREEN)
    wm_dark = wordmark_svg(colour="#1A1D1B")

    # editable sources
    for name, s in (
        ("icon-master.svg", master), ("icon-small.svg", small),
        ("mark.svg", mark), ("mark-monochrome.svg", mark_mono),
    ):
        open(f"{OUT}/source/{name}", "w").write(s)
    open(f"{OUT}/wordmark/wordmark-light.svg", "w").write(wm_light)
    open(f"{OUT}/wordmark/wordmark-dark.svg", "w").write(wm_dark)
    png(wm_light, f"{OUT}/wordmark/wordmark-light-2400.png", 2400, None)
    png(wm_dark, f"{OUT}/wordmark/wordmark-dark-2400.png", 2400, None)

    def art(sz):
        return master if sz >= 512 else small

    # iOS
    for sz in (1024, 180, 167, 152, 120, 87, 80, 76, 60, 58, 40, 29):
        png(art(sz), f"{OUT}/ios/AppIcon-{sz}.png", sz)

    # Android
    png(art(512), f"{OUT}/android/play-store-512.png", 512)
    bg_only = svg_doc(S, [
        f'<rect width="{S}" height="{S}" fill="{CASE}"/>',
        graticule(S),
    ])
    png(bg_only, f"{OUT}/android/adaptive-background-432.png", 432)
    pad = 288 / 432  # 72dp safe zone inside a 108dp canvas
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark.encode(), write_to=buf,
                     output_width=int(432 * pad), output_height=int(432 * pad))
    fg = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    m = Image.open(buf).convert("RGBA")
    fg.alpha_composite(m, ((432 - m.width) // 2, (432 - m.height) // 2))
    fg.save(f"{OUT}/android/adaptive-foreground-432.png")
    buf = io.BytesIO()
    cairosvg.svg2png(bytestring=mark_mono.encode(), write_to=buf,
                     output_width=int(432 * pad), output_height=int(432 * pad))
    mo = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    m2 = Image.open(buf).convert("RGBA")
    mo.alpha_composite(m2, ((432 - m2.width) // 2, (432 - m2.height) // 2))
    mo.save(f"{OUT}/android/adaptive-monochrome-432.png")
    for sz in (192, 144, 96, 72, 48):
        png(art(sz), f"{OUT}/android/legacy-launcher-{sz}.png", sz)

    # Web
    for sz in (512, 192, 180, 48, 32, 16):
        png(art(sz), f"{OUT}/web/icon-{sz}.png", sz)
    rounded(f"{OUT}/web/icon-512.png", f"{OUT}/web/icon-512-rounded.png")
    rounded(f"{OUT}/web/icon-192.png", f"{OUT}/web/icon-192-rounded.png")
    pad_canvas(mark, f"{OUT}/web/maskable-512.png", 512, 0.66)
    ico = [Image.open(f"{OUT}/web/icon-{s}.png").convert("RGBA") for s in (48, 32, 16)]
    ico[0].save(f"{OUT}/web/favicon.ico", sizes=[(48, 48), (32, 32), (16, 16)])

    # Splash
    png(mark, f"{OUT}/splash/splash-logo-1152.png", 1152)
    png(mark, f"{OUT}/splash/splash-logo-android12-960.png", 960)
    for name, (w, h) in {
        "splash-1290x2796.png": (1290, 2796),
        "splash-1179x2556.png": (1179, 2556),
        "splash-1080x1920.png": (1080, 1920),
    }.items():
        base = Image.new("RGB", (w, h), CASE)
        d = ImageDraw.Draw(base)
        for x in range(0, w, 60):
            d.line([(x, 0), (x, h)], fill=GRID, width=1)
        for y in range(0, h, 60):
            d.line([(0, y), (w, y)], fill=GRID, width=1)
        side = int(min(w, h) * 0.42)
        buf = io.BytesIO()
        cairosvg.svg2png(bytestring=mark.encode(), write_to=buf,
                         output_width=side, output_height=side)
        mk = Image.open(buf).convert("RGBA")
        base.paste(mk, ((w - side) // 2, (h - side) // 2 - int(h * 0.04)), mk)
        buf = io.BytesIO()
        cairosvg.svg2png(bytestring=wordmark_svg(height=120).encode(),
                         write_to=buf, output_width=int(w * 0.44))
        wm = Image.open(buf).convert("RGBA")
        base.paste(wm, ((w - wm.width) // 2, (h + side) // 2 + int(h * 0.01)), wm)
        base.save(f"{OUT}/splash/{name}")

    social_image()
    print("done")


if __name__ == "__main__":
    main()
