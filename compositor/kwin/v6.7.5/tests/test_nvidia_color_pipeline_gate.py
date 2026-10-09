import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "patches" / "0013-exact-kernel-nvidia-color-pipeline.patch"


class NvidiaColorPipelineGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = PATCH.read_text()

    def test_reuses_exact_kernel_gate(self):
        self.assertIn("KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE", self.source)
        self.assertIn("expectedRelease == systemInfo.release", self.source)

    def test_requires_tested_nvidia_driver_floor(self):
        self.assertIn("m_drmDevice->isNvidia()", self.source)
        self.assertIn("Version(610, 43, 3)", self.source)

    def test_adds_no_project_configuration_variable(self):
        added_lines = [line[1:] for line in self.source.splitlines() if line.startswith("+")]
        added_environment_names = {
            token
            for line in added_lines
            for token in line.replace('"', " ").split()
            if token.startswith("KWIN_")
        }
        self.assertEqual(
            added_environment_names,
            {"KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE"},
        )

    def test_preserves_upstream_explicit_override(self):
        self.assertIn("s_colorPipelineEnv.value_or", self.source)


if __name__ == "__main__":
    unittest.main()
