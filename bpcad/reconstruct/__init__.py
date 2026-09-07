"""
Which reconstructor, chosen the way every other backend in bpcad is chosen.

Default `null`: bpcad installs and runs with no weights, no torch and no
network, and every part in `parts/` still rebuilds from its spec. A real
reconstructor is opted into in config - the same rule as a model host, for the
same reason (CLAUDE.md rule 10).
"""

from __future__ import annotations

from typing import Any

from bpcad.reconstruct.base import (  # noqa: F401  (re-exported)
    Reconstruction,
    ReconstructionError,
    Reconstructor,
    ReconstructorUnavailable,
    scale_to_mm,
)

BACKENDS = ("null", "triposr")


def make_reconstructor(cfg: Any = None, backend: str | None = None):
    """
    Build the configured reconstructor.

    `backend` overrides config, for a one-off run. An unknown name is refused
    by name rather than silently falling back to null: a typo in a config file
    that quietly disables a feature is worse than an error.
    """
    name = (backend or _configured(cfg) or "null").strip().lower()

    if name == "null":
        from bpcad.reconstruct.null import NullReconstructor

        return NullReconstructor()

    if name == "triposr":
        from bpcad.reconstruct.triposr import TripoSRReconstructor

        return TripoSRReconstructor(cfg)

    raise ReconstructionError(
        "unknown reconstruct backend %r. bpcad has: %s."
        % (name, ", ".join(BACKENDS))
    )


def _configured(cfg: Any) -> str | None:
    if cfg is None:
        return None
    try:
        return (cfg.data.get("reconstruct") or {}).get("backend")
    except Exception:
        return None
