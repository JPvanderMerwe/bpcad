"""
bowl - regenerate this part.

Written by bpcad for inspection. The geometry comes from the template,
not from a copy of it pasted here - a second copy would drift.

    python model.py
"""

import cadquery as cq

from bpcad.build.compile import compile_spec, load_spec


def main():
    spec, base_dir = load_spec("spec.yaml")
    result = compile_spec(spec, base_dir=base_dir)
    cq.exporters.export(result.print_solid, "bowl.stl",
                        tolerance=0.005, angularTolerance=0.05)
    bb = result.print_solid.val().BoundingBox()
    print("%.2f x %.2f x %.2f mm" % (bb.xlen, bb.ylen, bb.zlen))


if __name__ == "__main__":
    main()
