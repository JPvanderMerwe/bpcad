"""
Config loads, validates, and refuses to hand back a number it does not have.
"""

from pathlib import Path

import pytest

from bpcad.config import (
    Config,
    ConfigError,
    UnsetConfigError,
    format_config,
    load_config,
)

CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.toml"


@pytest.fixture
def cfg() -> Config:
    return load_config(CONFIG)


def test_config_loads(cfg):
    assert cfg.path == CONFIG


def test_print_settings_present(cfg):
    assert cfg.print_settings["nozzle_mm"] == 0.40
    assert cfg.print_settings["layer_mm"] == 0.20


def test_limits_present(cfg):
    limits = cfg.limits
    assert limits["min_feature_multiple"] == 1.0
    assert limits["min_engrave_stroke_mm"] == 0.45
    assert limits["min_pin_mm"] == 2.40
    assert limits["max_overhang_deg"] == 45.0
    assert limits["max_bridge_gap_mm"] == 0.50


def test_export_tolerances_are_the_ones_that_stay_watertight(cfg):
    assert cfg.export["stl_tolerance"] == 0.005
    assert cfg.export["stl_angular_tolerance"] == 0.05


def test_the_three_materials_are_configured(cfg):
    assert cfg.material_names == ["petg", "pla", "tpu"]


def test_harvested_material_numbers_are_readable(cfg):
    """
    PLA and PETG carry clearances harvested from reference parts that printed
    and worked, so reading them succeeds.
    """
    assert cfg.material("petg")["clearance_mm"] == 0.30    # PIVOT_CLEAR / PIN_CLEAR
    assert cfg.material("pla")["clearance_mm"] == 0.20     # REGISTER_CLEAR
    for name in ("pla", "petg"):
        assert cfg.material(name)["shrink_pct"] == 0.0


def test_unset_material_raises_and_names_the_field(cfg):
    """
    bpcad must never substitute a plausible-looking tolerance. TPU is flexible,
    no reference part uses it, and a clearance guessed for a flexible material
    is worse than none.
    """
    with pytest.raises(UnsetConfigError) as exc:
        cfg.material("tpu")
    message = str(exc.value)
    assert "clearance_mm" in message
    assert "shrink_pct" in message
    assert str(CONFIG) in message


def test_unknown_material_raises(cfg):
    with pytest.raises(ConfigError):
        cfg.material("nylon")


def test_both_machine_profiles_are_configured(cfg):
    assert cfg.machine_names == ["desktop", "laptop"]


def test_machine_hosts_are_loopback(cfg):
    from bpcad.models.base import assert_local_endpoint

    for name in cfg.machine_names:
        assert_local_endpoint(
            cfg.machine(name)["host"], allowed_hosts=cfg.allowed_model_hosts
        )


def test_no_tailscale_host_is_whitelisted(cfg):
    assert cfg.allowed_model_hosts == []


def test_machine_profile_shapes(cfg):
    desktop = cfg.machine("desktop")
    laptop = cfg.machine("laptop")
    assert desktop["backend"] == laptop["backend"] == "ollama"
    # The laptop is slower, so it gets longer to answer and fewer attempts.
    assert laptop["timeout_s"] > desktop["timeout_s"]
    assert laptop["max_attempts_per_level"] < desktop["max_attempts_per_level"]
    assert laptop["num_ctx"] < desktop["num_ctx"]


def test_no_model_tag_is_pinned_before_it_is_benchmarked(cfg):
    """
    A tag may be set ONLY on a machine whose measurements are recorded in the
    config beside it. The laptop was benchmarked on 2026-08-27 (100% CPU, three
    models timed) so it is pinned; the desktop has not been touched yet, so it
    must still be UNSET.
    """
    text = CONFIG.read_text()
    for name in cfg.machine_names:
        table = cfg.machine(name)
        pinned = table["model_primary"] != "UNSET"
        section = text.split("[machines.%s]" % name, 1)[1].split("[machines.", 1)[0]
        has_measurements = "MEASURED" in section
        assert pinned == has_measurements, (
            "machine %r: model_primary is %s but the config %s measurements "
            "beside it. Benchmark it with `bpcad models bench` and record the "
            "numbers, or set it back to UNSET."
            % (name, "pinned" if pinned else "UNSET",
               "has" if has_measurements else "has no")
        )


def test_the_desktop_is_still_unbenchmarked(cfg):
    """8 GB VRAM, and nothing has been run on it. Nothing may be pinned."""
    assert cfg.machine("desktop")["model_primary"] == "UNSET"


def test_unset_fields_are_listed(cfg):
    unset = cfg.unset_fields()
    assert "materials.tpu.clearance_mm" in unset
    assert "materials.pla.clearance_mm" not in unset
    assert "machines.desktop.model_primary" in unset
    assert "machines.laptop.model_primary" not in unset   # benchmarked and pinned
    assert len(unset) == 4         # TPU x 2, desktop x 2


def test_format_config_flags_every_unset_value(cfg):
    text = format_config(cfg)
    assert "UNSET" in text
    assert "supply before use" in text
    for field in cfg.unset_fields():
        assert field in text


def test_missing_config_file_raises_with_the_path(tmp_path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError) as exc:
        load_config(missing)
    assert str(missing) in str(exc.value)
