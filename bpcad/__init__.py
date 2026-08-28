"""
bpcad - a fully local, fully offline text-and-image-to-3D-printable-part
pipeline. Bit Primitive.

Two things hold this package together and neither is negotiable:

  1. Inference is local or it does not happen. See bpcad.models.base for the
     enforcement, which is a code property rather than a thing to remember.
  2. spec.yaml is the durable artifact. Every capability must be reachable from
     a hand-written spec file with no model loaded at all.
"""

__version__ = "0.1.0"
