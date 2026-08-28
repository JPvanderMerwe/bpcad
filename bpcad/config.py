"""
Configuration loading, validation and display.

This module is a small addition to the layout in the brief. `bpcad config show`
has to load and validate config/default.toml, and stuffing TOML parsing into
cli.py would put logic somewhere the spec path cannot reach it. Machine profile
SELECTION - the --machine flag, the env var, the CUDA auto-detect - is not here;
that belongs to models/selector.py at Phase 4.

The one rule this module enforces is the "UNSET" sentinel. A config value with
no measured source is written as the string "UNSET", and reading it raises
UnsetConfigError rather than handing back something plausible. Wrong tolerances
are worse than no tolerances.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UNSET = "UNSET"

ENV_CONFIG = "BPCAD_CONFIG"

REQUIRED_SECTIONS = ("print", "bed", "limits", "export", "models", "materials", "machines")
REQUIRED_PRINT = ("nozzle_mm", "layer_mm")
REQUIRED_BED = ("width_mm", "depth_mm", "height_mm")
REQUIRED_LIMITS = (
    "min_feature_multiple",
    "min_engrave_stroke_mm",
    "min_pin_mm",
    "max_overhang_deg",
    "max_bridge_gap_mm",
)
REQUIRED_EXPORT = ("stl_tolerance", "stl_angular_tolerance")
REQUIRED_MATERIAL = ("clearance_mm", "shrink_pct")
REQUIRED_MACHINE = (
    "backend",
    "host",
    "model_primary",
    "model_small",
    "num_ctx",
    "timeout_s",
    "max_attempts_per_level",
)


class ConfigError(RuntimeError):
    """The config file is missing, unparseable, or structurally wrong."""


class UnsetConfigError(RuntimeError):
    """
    Something read a value that is deliberately UNSET.

    The message always names the exact dotted path so you know which line of
    config/default.toml to fill in.
    """


def default_config_path() -> Path:
    """
    Where config/default.toml lives, in order of precedence:

      1. $BPCAD_CONFIG, if set.
      2. ./config/default.toml relative to the working directory.
      3. config/default.toml beside the installed package.
    """
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env).expanduser()

    cwd = Path.cwd() / "config" / "default.toml"
    if cwd.is_file():
        return cwd

    return Path(__file__).resolve().parent.parent / "config" / "default.toml"


@dataclass(frozen=True)
class Config:
    """Parsed configuration plus the path it came from."""

    data: dict[str, Any]
    path: Path

    # -- sections ----------------------------------------------------------

    @property
    def print_settings(self) -> dict[str, Any]:
        return dict(self.data["print"])

    @property
    def bed(self) -> dict[str, Any]:
        return dict(self.data["bed"])

    @property
    def bed_mm(self) -> tuple[float, float, float]:
        b = self.data["bed"]
        return (float(b["width_mm"]), float(b["depth_mm"]), float(b["height_mm"]))

    @property
    def limits(self) -> dict[str, Any]:
        return dict(self.data["limits"])

    @property
    def export(self) -> dict[str, Any]:
        return dict(self.data["export"])

    @property
    def allowed_model_hosts(self) -> list[str]:
        return list(self.data["models"].get("allowed_model_hosts", []))

    @property
    def material_names(self) -> list[str]:
        return sorted(self.data["materials"])

    @property
    def machine_names(self) -> list[str]:
        return sorted(self.data["machines"])

    # -- guarded accessors -------------------------------------------------

    def material(self, name: str) -> dict[str, Any]:
        """
        A material's numbers, or UnsetConfigError naming every field that has
        no source yet. Nothing downstream gets to invent a tolerance.
        """
        key = name.strip().lower()
        if key not in self.data["materials"]:
            raise ConfigError(
                "unknown material %r. Configured materials are: %s"
                % (name, ", ".join(self.material_names))
            )
        table = dict(self.data["materials"][key])
        missing = [f for f in REQUIRED_MATERIAL if table.get(f, UNSET) == UNSET]
        if missing:
            raise UnsetConfigError(
                "material %r has no value for %s. These are deliberately UNSET "
                "because no measured source was supplied. Set them in %s "
                "(section [materials.%s]) before using this material - bpcad "
                "will not substitute a guess."
                % (key, " and ".join(missing), self.path, key)
            )
        return table

    def machine(self, name: str) -> dict[str, Any]:
        """A machine profile. Model tags may be UNSET; that is checked later."""
        key = name.strip().lower()
        if key not in self.data["machines"]:
            raise ConfigError(
                "unknown machine profile %r. Configured profiles are: %s"
                % (name, ", ".join(self.machine_names))
            )
        return dict(self.data["machines"][key])

    # -- reporting ---------------------------------------------------------

    def unset_fields(self) -> list[str]:
        """Every dotted path still marked UNSET, so `config show` can list them."""
        out: list[str] = []
        for mat in self.material_names:
            table = self.data["materials"][mat]
            for field in REQUIRED_MATERIAL:
                if table.get(field, UNSET) == UNSET:
                    out.append("materials.%s.%s" % (mat, field))
        for mach in self.machine_names:
            table = self.data["machines"][mach]
            for field in REQUIRED_MACHINE:
                if table.get(field, UNSET) == UNSET:
                    out.append("machines.%s.%s" % (mach, field))
        return out


def _require(table: dict[str, Any], keys: tuple[str, ...], where: str, path: Path) -> None:
    missing = [k for k in keys if k not in table]
    if missing:
        raise ConfigError(
            "%s in %s is missing: %s" % (where, path, ", ".join(missing))
        )


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """
    Read and structurally validate the config. Raises ConfigError with the file
    path and the offending key rather than a KeyError three modules later.
    """
    p = Path(path).expanduser() if path is not None else default_config_path()
    if not p.is_file():
        raise ConfigError(
            "no config file at %s. Set %s, or run bpcad from a directory that "
            "has config/default.toml in it." % (p, ENV_CONFIG)
        )

    try:
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("could not parse %s: %s" % (p, exc)) from exc

    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise ConfigError(
            "%s is missing these sections: %s" % (p, ", ".join(missing))
        )

    _require(data["print"], REQUIRED_PRINT, "[print]", p)
    _require(data["bed"], REQUIRED_BED, "[bed]", p)
    _require(data["limits"], REQUIRED_LIMITS, "[limits]", p)
    _require(data["export"], REQUIRED_EXPORT, "[export]", p)

    if not data["materials"]:
        raise ConfigError("%s defines no materials" % p)
    for name, table in data["materials"].items():
        _require(table, REQUIRED_MATERIAL, "[materials.%s]" % name, p)

    if not data["machines"]:
        raise ConfigError("%s defines no machine profiles" % p)
    for name, table in data["machines"].items():
        _require(table, REQUIRED_MACHINE, "[machines.%s]" % name, p)

    return Config(data=data, path=p)


def _fmt(value: Any) -> str:
    if value == UNSET:
        return "UNSET   <- no source yet, supply before use"
    if isinstance(value, list):
        return "(none)" if not value else ", ".join(str(v) for v in value)
    return str(value)


def format_config(cfg: Config, machine: str | None = None) -> str:
    """Plain-text rendering of the config for `bpcad config show`."""
    lines: list[str] = []
    lines.append("config file   %s" % cfg.path)
    lines.append("")

    for section in ("print", "limits", "export"):
        lines.append("[%s]" % section)
        for k, v in cfg.data[section].items():
            lines.append("  %-24s %s" % (k, _fmt(v)))
        lines.append("")

    lines.append("[models]")
    hosts = cfg.allowed_model_hosts
    lines.append("  %-24s %s" % ("allowed_model_hosts", _fmt(hosts)))
    lines.append("  loopback (127.0.0.0/8, ::1, localhost) is always permitted")
    lines.append("  anything else raises NonLocalEndpointError at construction")
    lines.append("")

    lines.append("[materials]")
    for name in cfg.material_names:
        lines.append("  %s" % name)
        for k, v in cfg.data["materials"][name].items():
            lines.append("    %-22s %s" % (k, _fmt(v)))
    lines.append("")

    names = [machine] if machine else cfg.machine_names
    lines.append("[machines]")
    for name in names:
        table = cfg.machine(name)
        lines.append("  %s" % name)
        for k, v in table.items():
            lines.append("    %-22s %s" % (k, _fmt(v)))
    lines.append("")

    unset = cfg.unset_fields()
    if unset:
        lines.append("UNSET VALUES (%d) - bpcad raises rather than guessing:" % len(unset))
        for field in unset:
            lines.append("  %s" % field)
    else:
        lines.append("No unset values.")

    return "\n".join(lines)
