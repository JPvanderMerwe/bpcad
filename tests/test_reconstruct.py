"""
Photo to mesh to spec, and the three things it must never claim.

The reconstructor itself is 2.5 GB of torch and weights and is NOT installed
here - so these tests exercise the seam, the scale arithmetic and the refusal,
which is everything except the forward pass. That is deliberate: the whole
path has to be testable on a machine that will never download a model, or it
stops being tested.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from bpcad.reconstruct import make_reconstructor, scale_to_mm
from bpcad.reconstruct.base import (
    Reconstruction,
    ReconstructionError,
    ReconstructorUnavailable,
)

ROOT = Path(__file__).resolve().parent.parent


def _dimensionless(extent=(2.0, 1.0, 0.5)) -> Reconstruction:
    """What comes out of a network: a shape, in no units at all."""
    return Reconstruction(
        mesh_path=Path("/tmp/x.glb"),
        source_image=Path("/tmp/x.jpg"),
        backend="test",
        extent=extent,
    )


# ---------------------------------------------------------------------------
# The default is off, and it refuses in a way somebody can act on.
# ---------------------------------------------------------------------------

def test_the_default_backend_is_null():
    """
    bpcad installs and runs with no torch, no weights and no network. A
    reconstructor that was required would break that, and the offline rebuild
    guarantee is the reason this program is trustworthy.
    """
    from bpcad import api

    cfg = api.config(ROOT / "config" / "default.toml")
    assert cfg.data["reconstruct"]["backend"] == "null"
    assert make_reconstructor(cfg).name == "null"


def test_the_null_backend_says_what_to_do_instead():
    reconstructor = make_reconstructor(None)
    with pytest.raises(ReconstructorUnavailable) as exc:
        reconstructor.reconstruct("whatever.jpg", "/tmp")

    message = str(exc.value)
    # Names the alternative that needs no weights...
    assert "bpcad measure" in message
    # ...and the command that turns this on.
    assert "reconstruct" in message


def test_an_unknown_backend_is_refused_by_name():
    """
    A typo in a config file that silently disables a feature is worse than an
    error: the feature looks broken rather than switched off.
    """
    with pytest.raises(ReconstructionError) as exc:
        make_reconstructor(None, backend="meshy")
    assert "meshy" in str(exc.value)
    assert "null, triposr" in str(exc.value)


# ---------------------------------------------------------------------------
# No photograph contains scale. This is the arithmetic that fixes that, and
# the refusals that stop it being guessed.
# ---------------------------------------------------------------------------

def test_a_reconstruction_has_no_size_until_a_real_dimension_is_given():
    result = _dimensionless()
    assert not result.has_scale
    assert result.extent_mm() is None
    assert result.to_json()["extent_mm"] is None


def test_one_measured_dimension_scales_the_whole_thing():
    """
    Calipers on the longest axis, and everything else follows proportionally.
    The longest is the default because it is the one a person reaches for
    without being told which way round the model is.
    """
    result = scale_to_mm(_dimensionless((2.0, 1.0, 0.5)), 80.0)

    assert result.has_scale
    assert result.scale_mm_per_unit == pytest.approx(40.0)
    x, y, z = result.extent_mm()
    assert (x, y, z) == pytest.approx((80.0, 40.0, 20.0))
    assert "80 mm" in result.scale_source


def test_a_named_axis_can_carry_the_measurement():
    """The widest point is not always the one that was measured."""
    result = scale_to_mm(_dimensionless((2.0, 1.0, 0.5)), 10.0, axis="z")
    assert result.scale_mm_per_unit == pytest.approx(20.0)
    assert result.extent_mm()[0] == pytest.approx(40.0)


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_a_nonsense_dimension_is_refused(bad):
    with pytest.raises(ReconstructionError):
        scale_to_mm(_dimensionless(), bad)


def test_scale_is_refused_when_there_is_nothing_to_scale():
    with pytest.raises(ReconstructionError) as exc:
        scale_to_mm(_dimensionless((0.0, 0.0, 0.0)), 40.0)
    assert "no measured extent" in str(exc.value)


def test_an_unknown_axis_is_refused_rather_than_assumed():
    with pytest.raises(ReconstructionError):
        scale_to_mm(_dimensionless(), 40.0, axis="diagonal")


# ---------------------------------------------------------------------------
# What a reconstruction is allowed to claim about itself.
# ---------------------------------------------------------------------------

def test_a_fresh_reconstruction_is_not_printable():
    """
    `printable` is set by the geometry side of the house after bpcad's own
    verify pass, never by a reconstructor. Neural meshes are routinely
    non-manifold - meshy publishes 55% fully watertight - so a mesh existing
    is not a mesh that will slice.
    """
    assert _dimensionless().printable is False


def test_the_record_carries_the_provenance_a_part_would_need():
    result = _dimensionless()
    result.model = "stabilityai/TripoSR/model.ckpt"
    result.seconds = 92.4
    data = result.to_json()

    for key in ("backend", "model", "seconds", "source_image", "extent",
                "scale_mm_per_unit", "printable", "problems", "notes"):
        assert key in data, key
    assert data["seconds"] == 92.4


def test_the_api_entry_point_exists_and_refuses_cleanly():
    """
    The chain is photo -> mesh -> scale -> spec, and with no reconstructor the
    first link fails. It must fail as an ApiError with the instructions in it,
    not as a traceback out of a torch import.
    """
    from bpcad import api

    cfg = api.config(ROOT / "config" / "default.toml")
    with pytest.raises(api.ApiError) as exc:
        api.model_from_photo(ROOT / "files" / "keyring_heightmap.png",
                             known_mm=40.0, cfg=cfg)
    assert "reconstructor is configured" in str(exc.value)


def test_the_triposr_backend_can_be_constructed_without_torch():
    """
    Constructing a backend must not import torch: a program that merely has
    it configured should not pay two gigabytes and several seconds for it
    until a photograph actually arrives.
    """
    from bpcad.reconstruct.triposr import TripoSRReconstructor

    backend = TripoSRReconstructor(None)
    assert backend.name == "triposr"
    # With no torch installed, device resolution falls back rather than raising.
    assert backend.device() in ("cpu", "cuda")


def test_device_can_be_pinned_without_hardware_present():
    from bpcad.reconstruct.triposr import TripoSRReconstructor

    assert TripoSRReconstructor(None, device="cuda").device() == "cuda"
    assert TripoSRReconstructor(None, device="cpu").device() == "cpu"
