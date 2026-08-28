"""
Machine profile resolution and the degradation ladder.

MODEL SELECTION IS A MACHINE PROFILE, NOT A PROVIDER CHOICE.
There is one provider - a local Ollama daemon - and the only thing that varies
between machines is which model fits and how long to wait for it.

THE LADDER, AND WHAT IT DELIBERATELY DOES NOT CONTAIN
-----------------------------------------------------
When the primary model cannot produce a valid spec:

  1. Retry the same model with the structured failure fed back, to the
     profile's cap.
  2. Drop to model_small - smaller and faster, and sometimes BETTER at plain
     schema-filling because it improvises less.
  3. Hand off to a person, with a spec.draft.yaml whose every failed field is
     annotated with the validation error and the legal range.

There is no step involving a remote model, because there is no remote model.
Step 3 is the important one and it is easy to under-build: a good handoff is
the difference between this system being useful on a slow machine and being
abandoned.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from bpcad.config import Config
from bpcad.models.null import NullBackend
from bpcad.models.ollama import CallRecord, OllamaBackend, OllamaError

ENV_MACHINE = "BPCAD_MACHINE"
UNSET = "UNSET"


class ProfileError(RuntimeError):
    """The machine profile is missing, unknown, or not usable as configured."""


def has_cuda_device() -> bool:
    """
    Whether this machine looks like it has a working NVIDIA GPU.

    MUST NEVER CRASH on a machine with no NVIDIA driver, which is the common
    case here - the work laptop has none, and `nvidia-smi` is simply absent. So
    this checks for the device nodes rather than shelling out, and treats every
    error as "no".
    """
    try:
        if any(
            os.path.exists(p)
            for p in ("/dev/nvidiactl", "/dev/nvidia0", "/proc/driver/nvidia/version")
        ):
            return True
    except Exception:
        return False
    return False


def detect_machine(cfg: Config) -> str:
    """
    Pick a machine profile: the env var wins, then CUDA detection, then the
    single profile if there is only one.
    """
    env = os.environ.get(ENV_MACHINE)
    if env:
        if env not in cfg.machine_names:
            raise ProfileError(
                "%s is set to %r, which is not a configured profile. Configured: %s."
                % (ENV_MACHINE, env, ", ".join(cfg.machine_names))
            )
        return env

    if has_cuda_device() and "desktop" in cfg.machine_names:
        return "desktop"
    if not has_cuda_device() and "laptop" in cfg.machine_names:
        return "laptop"
    if len(cfg.machine_names) == 1:
        return cfg.machine_names[0]
    raise ProfileError(
        "cannot tell which machine this is. Configured profiles: %s. Pass "
        "--machine, or set %s." % (", ".join(cfg.machine_names), ENV_MACHINE)
    )


@dataclass
class Profile:
    """One machine's resolved settings."""

    name: str
    backend_kind: str
    host: str
    model_primary: str
    model_small: str
    num_ctx: int
    timeout_s: float
    max_attempts_per_level: int
    allowed_hosts: tuple[str, ...] = ()

    def models(self) -> list[str]:
        """Primary first, then small if it is a different model."""
        out = [self.model_primary]
        if self.model_small and self.model_small != self.model_primary:
            out.append(self.model_small)
        return out

    def describe(self) -> str:
        return (
            "machine %s: backend %s at %s, primary %s, small %s, ctx %d, "
            "timeout %.0fs, %d attempts per level"
            % (self.name, self.backend_kind, self.host, self.model_primary,
               self.model_small, self.num_ctx, self.timeout_s,
               self.max_attempts_per_level)
        )


def load_profile(cfg: Config, machine: str | None = None) -> Profile:
    """Resolve a machine profile, with the UNSET sentinel enforced."""
    name = machine or detect_machine(cfg)
    table = cfg.machine(name)

    for key in ("model_primary", "model_small"):
        if table.get(key, UNSET) == UNSET:
            raise ProfileError(
                "machine %r has no %s set. Model tags are deliberately UNSET "
                "until they have been benchmarked on the actual hardware - "
                "nothing gets pinned before that. Run `bpcad models list` to "
                "see what this daemon has, then set it in %s under "
                "[machines.%s]." % (name, key, cfg.path, name)
            )

    # Check the host HERE, at profile load, not later at backend construction.
    # Later still raises - that is the guarantee - but it raises from inside the
    # generation loop, which prints a traceback and, worse, prints the profile
    # banner with the offending URL in it first, as though it were about to be
    # used. Failing at load means the refusal is the first thing you see.
    from bpcad.models.base import assert_local_endpoint

    if table["backend"].strip().lower() == "ollama":
        assert_local_endpoint(table["host"], cfg.allowed_model_hosts)

    return Profile(
        name=name,
        backend_kind=table["backend"],
        host=table["host"],
        model_primary=table["model_primary"],
        model_small=table["model_small"],
        num_ctx=int(table["num_ctx"]),
        timeout_s=float(table["timeout_s"]),
        max_attempts_per_level=int(table["max_attempts_per_level"]),
        allowed_hosts=tuple(cfg.allowed_model_hosts),
    )


def make_backend(profile: Profile, model: str | None = None):
    """
    Build the backend for a profile. Exactly two kinds exist.

    Do not add a third without asking - see CLAUDE.md rule 10.
    """
    kind = profile.backend_kind.strip().lower()
    if kind == "null":
        return NullBackend("machine profile %r selects the null backend" % profile.name)
    if kind != "ollama":
        raise ProfileError(
            "machine %r asks for backend %r. bpcad has exactly two: 'ollama' "
            "and 'null'. There is no cloud model, no API key and no hosted "
            "endpoint at any tier." % (profile.name, profile.backend_kind)
        )
    return OllamaBackend(
        model=model or profile.model_primary,
        host=profile.host,
        timeout_s=profile.timeout_s,
        num_ctx=profile.num_ctx,
        allowed_hosts=profile.allowed_hosts,
    )


@dataclass
class Attempt:
    """One trip round the ladder, whether it worked or not."""

    model: str
    step: str                  # "primary" | "small"
    index: int
    ok: bool
    elapsed_s: float
    error: str = ""
    raw: str = ""
    call: CallRecord | None = None

    def summary(self) -> str:
        status = "ok" if self.ok else "FAILED"
        line = "attempt %d  %-22s %-8s %6.1fs  %s" % (
            self.index, self.model, self.step, self.elapsed_s, status
        )
        if self.error:
            line += "\n           %s" % self.error.split("\n")[0][:160]
        return line


@dataclass
class LadderResult:
    """What the whole ladder produced, and everything it tried on the way."""

    value: Any = None
    ok: bool = False
    attempts: list[Attempt] = field(default_factory=list)
    exhausted: bool = False

    @property
    def total_elapsed_s(self) -> float:
        return sum(a.elapsed_s for a in self.attempts)

    @property
    def never_reached_a_model(self) -> bool:
        """
        True if no attempt ever got as far as generating.

        "The daemon is not running" and "the model produced nonsense" are
        different problems with different fixes, and they must not print the
        same message. The first is fixed by `ollama serve`; the second by
        editing YAML.
        """
        return bool(self.attempts) and not any(a.call for a in self.attempts)

    @property
    def last_error(self) -> str:
        for a in reversed(self.attempts):
            if a.error:
                return a.error
        return ""

    @property
    def best_raw(self) -> str:
        """The closest attempt's raw output, for the handoff draft."""
        for a in reversed(self.attempts):
            if a.raw:
                return a.raw
        return ""

    def report(self) -> str:
        lines = [a.summary() for a in self.attempts]
        lines.append("total %.1fs over %d attempt(s)" % (self.total_elapsed_s, len(self.attempts)))
        return "\n".join(lines)


def run_ladder(
    profile: Profile,
    ask: Callable[[Any], Any],
    on_attempt: Callable[[Attempt], None] | None = None,
) -> LadderResult:
    """
    Walk the degradation ladder until something validates or it is exhausted.

    `ask(backend)` does one generation and either returns a validated value or
    raises. Anything it raises is treated as a failure worth retrying, with the
    exception text fed back to the caller for the next prompt.

    Elapsed time is printed per attempt by the caller, because on a slow machine
    knowing what a run actually costs is the difference between trusting the
    tool and guessing.
    """
    import time

    result = LadderResult()
    index = 0

    for step, model in zip(("primary", "small"), profile.models()):
        backend = make_backend(profile, model)

        if not backend.available():
            index += 1
            attempt = Attempt(
                model=model, step=step, index=index, ok=False, elapsed_s=0.0,
                error=(
                    "model %r is not available on the daemon at %s. `ollama "
                    "list` shows what is. bpcad will not fall back to anything "
                    "remote." % (model, profile.host)
                ),
            )
            result.attempts.append(attempt)
            if on_attempt:
                on_attempt(attempt)
            continue

        for _ in range(profile.max_attempts_per_level):
            index += 1
            started = time.monotonic()
            try:
                value = ask(backend)
                attempt = Attempt(
                    model=model, step=step, index=index, ok=True,
                    elapsed_s=time.monotonic() - started,
                    call=backend.calls[-1] if getattr(backend, "calls", None) else None,
                )
                result.attempts.append(attempt)
                if on_attempt:
                    on_attempt(attempt)
                result.value = value
                result.ok = True
                return result
            except Exception as exc:
                attempt = Attempt(
                    model=model, step=step, index=index, ok=False,
                    elapsed_s=time.monotonic() - started,
                    error=str(exc),
                    raw=getattr(exc, "raw", ""),
                    call=backend.calls[-1] if getattr(backend, "calls", None) else None,
                )
                result.attempts.append(attempt)
                if on_attempt:
                    on_attempt(attempt)
                if isinstance(exc, OllamaError):
                    break      # daemon problem: a retry will not fix it

    result.exhausted = True
    return result
