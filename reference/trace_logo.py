"""
Trace the loop wordmark out of a raster crop into normalised polygons.

Run this again if you ever get a higher-resolution logo asset - the keyring
script reads loop_logo.json and needs no other change. Output coordinates are
normalised so that the logo's total WIDTH is 1.0, x to the right, y up, origin
at the bottom-left of the logo's bounding box.

  python3 trace_logo.py path/to/logo.png
"""
import json
import sys

import numpy as np
from PIL import Image, ImageFilter
from skimage import measure

SRC = sys.argv[1] if len(sys.argv) > 1 else "logo.png"
UP = 10             # upsample factor, gives sub-pixel contour placement
BLUR = UP * 1.1     # kills the fabric weave, which is high frequency
LEVEL = 0.55        # iso level on the normalised luminance
TOL = UP * 0.055    # polygon simplification. Lower = smoother, more vertices.


def main():
    im = Image.open(SRC).convert("RGB")
    big = (im.resize((im.width * UP, im.height * UP), Image.LANCZOS)
             .filter(ImageFilter.GaussianBlur(BLUR)))
    lum = np.array(big).astype(float).sum(axis=2)
    lo, hi = np.percentile(lum, 2), np.percentile(lum, 98)
    norm = (lum - lo) / (hi - lo)

    polys = []
    for c in measure.find_contours(norm, LEVEL):
        if len(c) < 50:
            continue
        p = measure.approximate_polygon(c, tolerance=TOL)
        if len(p) < 6:
            continue
        area = 0.5 * abs(np.dot(p[:, 1], np.roll(p[:, 0], 1))
                         - np.dot(p[:, 0], np.roll(p[:, 1], 1)))
        if area < (UP * 2.0) ** 2:
            continue
        polys.append(p)

    def inside(pt, poly):
        y, x = pt
        c = False
        for i in range(len(poly)):
            y1, x1 = poly[i]
            y2, x2 = poly[(i + 1) % len(poly)]
            if (x1 > x) != (x2 > x):
                if y1 + (x - x1) * (y2 - y1) / (x2 - x1) > y:
                    c = not c
        return c

    depth = [sum(1 for j, q in enumerate(polys) if j != i and inside(p[0], q))
             for i, p in enumerate(polys)]

    allp = np.vstack(polys)
    r0, r1 = allp[:, 0].min(), allp[:, 0].max()
    c0, c1 = allp[:, 1].min(), allp[:, 1].max()
    wn = c1 - c0

    shapes = []
    for p, d in zip(polys, depth):
        pts = [[round(float((x - c0) / wn), 5), round(float((r1 - y) / wn), 5)]
               for y, x in p]
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        shapes.append({"hole": bool(d % 2), "pts": pts})

    data = {"source": SRC, "aspect_h": round(float((r1 - r0) / wn), 5),
            "shapes": shapes}
    json.dump(data, open("loop_logo.json", "w"))
    print("outers %d  holes %d  height/width %.4f  -> loop_logo.json"
          % (sum(not s["hole"] for s in shapes),
             sum(s["hole"] for s in shapes), data["aspect_h"]))


if __name__ == "__main__":
    main()
