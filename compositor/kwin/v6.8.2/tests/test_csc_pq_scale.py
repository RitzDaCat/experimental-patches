import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "0021-selectable-mandatory-csc-pq-scale.patch"


class MandatoryCscPqScaleTest(unittest.TestCase):
    """The mandatory NVIDIA CSC stages are fixed hardware functions whose PQ
    convention cannot be read back. Patch 0021 makes KWin's assumption
    runtime-selectable so one controlled experiment can resolve it, while
    keeping the UAPI assumption as the fail-safe default."""

    @classmethod
    def setUpClass(cls):
        cls.source = PATCH.read_text()

    def test_defaults_to_uapi_scale(self):
        added_lines = [line[1:] for line in self.source.splitlines() if line.startswith("+")]
        added_source = "\n".join(added_lines)
        self.assertIn("return 125.0;", added_source)

    def test_selectable_via_named_environment_variable(self):
        self.assertIn("KWIN_DRM_NVIDIA_CSC_PQ_SCALE", self.source)
        self.assertIn('value == "1"', self.source)

    def test_bypassable_curves_keep_uapi_scale(self):
        # Only mandatory fixed stages may follow the selected convention;
        # bypassable named curves stay driver-bridged to the UAPI.
        self.assertIn("m_bypass ? 125.0 : mandatoryCscPqScale()", self.source)

    def test_all_scaling_paths_route_through_the_helper(self):
        added_lines = [line[1:] for line in self.source.splitlines() if line.startswith("+")]
        added_source = "\n".join(added_lines)
        self.assertIn("transferFunctionScale(type)", added_source)
        self.assertIn("this->transferFunctionScale(tf->tf.type)", added_source)
        # no remaining hardcoded PQ-125 selection inside DrmNamed1DLut additions
        self.assertNotIn("? 125 : 1;", added_source)


if __name__ == "__main__":
    unittest.main()
