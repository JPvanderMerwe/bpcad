"""
The null backend: raises a clear error on any attempt to infer.

This is not a stub or a placeholder. It exists so that "this code path never
touches a model" is a thing a test can PROVE rather than a thing a comment
claims. Configure it, run the deterministic pipeline, and if anything reaches
for inference the run fails loudly instead of quietly working on a machine that
happens to have Ollama up.
"""

from __future__ import annotations


class NullBackendError(RuntimeError):
    """
    Something tried to infer while the null backend was configured.

    If you are seeing this from `bpcad build`, `verify`, `render` or `measure`,
    that is a bug in bpcad, not in your setup: those commands must work with no
    model at all.
    """


class NullBackend:
    """Implements the Backend protocol by refusing to do anything."""

    def __init__(self, reason: str = "") -> None:
        self._reason = reason

    def complete(self, system: str, user: str, schema: dict | None) -> str:
        detail = " (%s)" % self._reason if self._reason else ""
        raise NullBackendError(
            "the null backend cannot generate anything%s. It is configured "
            "deliberately, to prove a code path never reaches for a model. "
            "Every deterministic command - build, verify, render, measure - "
            "must work with this backend in place; only `ask` and `gen` need a "
            "real one." % detail
        )

    def name(self) -> str:
        return "null"

    def available(self) -> bool:
        return False

    def endpoint(self) -> str:
        return "none"
