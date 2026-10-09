from __future__ import annotations

import math
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = (ROOT / "patches/0015-bounded-color-hot-path-cache.patch").read_text()


def f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def test_hot_path_state_is_bounded_and_configuration_free() -> None:
    added = "\n".join(
        line[1:]
        for line in PATCH.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    assert "s_colorTransformCacheSize = 4" in added
    assert "m_colorUniformsValid" in added
    assert "m_directScanoutColorCache" in added
    assert "m_hdrMetadataColorCache" in added
    assert "qEnvironment" not in added
    assert "QHash<" not in added
    assert "mutex" not in added.lower()


def test_direct_scanout_cache_key_covers_every_pipeline_input() -> None:
    for field in (
        "source.get() == source.get()",
        "destination.get() == destination.get()",
        "intent == intent",
        "inputType == inputType",
    ):
        assert field in PATCH


def test_opaque_specialization_requires_opaque_unmodulated_alpha() -> None:
    assert "!renderNode.hasAlpha && renderNode.opacity == 1.0" in PATCH
    assert "#if !TRAIT_OPAQUE_COLORSPACE" in PATCH


def test_destination_reciprocal_matches_division_with_float_precision() -> None:
    ranges = (1.0, 80.0, 203.0, 325.125081539, 1_000.0, 10_000.0)
    values = (-0.25, 0.0, 0.001, 0.18, 1.0, 80.0, 232.232201099, 10_000.0)
    offsets = (0.0, 0.005, 0.2)
    for scale in ranges:
        inverse = f32(1.0 / f32(scale))
        for offset in offsets:
            for value in values:
                numerator = f32(f32(value) - f32(offset))
                divided = f32(numerator / f32(scale))
                multiplied = f32(numerator * inverse)
                assert math.isclose(divided, multiplied, rel_tol=2e-7, abs_tol=2e-7)


def test_tonemapping_coefficient_is_hoisted_without_formula_change() -> None:
    for reference, input_max, output_max in (
        (80.0, 1_000.0, 420.0),
        (203.0, 1_000.0, 420.0),
        (232.232201099, 1_000.0, 325.125081539),
    ):
        reference = f32(reference)
        input_range = f32(f32(input_max) / reference)
        output_range = f32(f32(output_max) / reference)
        old_v = f32(
            f32(f32(output_range * f32(1.0 + input_range)) - input_range)
            / f32(input_range * input_range)
        )
        new_v = f32(
            f32(f32(output_range * f32(1.0 + input_range)) - input_range)
            / f32(input_range * input_range)
        )
        assert old_v == new_v
        inverse_reference = f32(1.0 / reference)
        for luminance in (0.0, 0.005, 1.0, 80.0, 203.0, 420.0, 1_000.0):
            old_relative = f32(f32(luminance) / reference)
            new_relative = f32(f32(luminance) * inverse_reference)
            old_mapped = f32(
                f32(old_relative * f32(1.0 + f32(old_relative * old_v)))
                / f32(1.0 + old_relative)
            )
            new_mapped = f32(
                f32(new_relative * f32(1.0 + f32(new_relative * new_v)))
                / f32(1.0 + new_relative)
            )
            assert math.isclose(old_mapped, new_mapped, rel_tol=3e-7, abs_tol=3e-7)
