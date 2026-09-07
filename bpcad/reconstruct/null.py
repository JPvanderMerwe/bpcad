"""
The reconstructor that refuses, and says what to do about it.

WHY THIS IS THE DEFAULT. bpcad has to install and run with no torch, no model
weights and no network: every part in `parts/` rebuilds from its `spec.yaml`
offline, and that guarantee is the reason the program is trustworthy rather
than a sentiment about privacy. A neural reconstructor is two and a half
gigabytes of dependencies and weights, and making it a requirement would mean
`pip install bpcad` no longer produces a working program on a machine with a
slow connection.

So this one is installed, and it fails with instructions instead of a
traceback. It is also what the test suite runs against, which is how the whole
photo-to-spec path is exercised on a machine that will never download a model.
"""

from __future__ import annotations

from pathlib import Path

from bpcad.reconstruct.base import Reconstruction, ReconstructorUnavailable


class NullReconstructor:
    """Answers every photograph the same way: not on this machine."""

    name = "null"

    def reconstruct(self, image: Path | str, out_dir: Path | str) -> Reconstruction:
        raise ReconstructorUnavailable(
            "no mesh reconstructor is configured, so a photograph cannot be "
            "turned into geometry on this machine.\n"
            "\n"
            "What still works with no reconstructor: `bpcad measure` reads a "
            "reference photo for dimensions, and `bpcad gen --image` hands "
            "those to the model as context. That path is accurate and needs "
            "no weights.\n"
            "\n"
            "To turn it on, set [reconstruct] backend = \"triposr\" in the "
            "config and install the extra:\n"
            "    pip install -e \".[reconstruct]\"\n"
            "It wants about 2.5 GB of torch and weights, and a GPU if you do "
            "not want to wait minutes per photograph."
        )
