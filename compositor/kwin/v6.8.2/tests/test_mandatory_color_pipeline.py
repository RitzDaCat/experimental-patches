import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "0016-compensate-mandatory-color-pipeline-curves.patch"


class MandatoryColorPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATCH.read_text()

    def test_compensates_both_sides_of_requested_pipeline(self):
        self.assertIn("bypassScaling(const ColorOp &nextOperation)", self.source)
        self.assertIn("bypassOutputScaling(const ColorOp &lastAppliedOp)", self.source)
        self.assertIn("compensatedNonBypassable", self.source)

    def test_uses_drm_pq_125_scale(self):
        self.assertIn("? 125.0 : 1.0", self.source)
        self.assertNotIn("10'000 / 125", self.source)

    def test_models_fixed_named_hardware_curves(self):
        self.assertIn("const TransferFunction fixedPq", self.source)
        self.assertIn("testNonBypassableNamedTransferFunctions", self.source)
        self.assertIn("(actual - expected).length() < 0.00001", self.source)

    def test_adds_no_configuration_surface(self):
        added_lines = [line[1:] for line in self.source.splitlines() if line.startswith("+")]
        added_source = "\n".join(added_lines)
        self.assertNotIn("environmentVariableBoolValue", added_source)
        self.assertNotIn("qEnvironmentVariable", added_source)
        self.assertNotIn("qgetenv", added_source)


if __name__ == "__main__":
    unittest.main()
