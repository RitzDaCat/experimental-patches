import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_trace_safety.sh"
CAPTURE = ROOT / "scripts" / "capture_pipeline_window.sh"
CONTROL = ROOT / "bin" / "kwin-latencyctl"
DRM_COLOR_PROBE = ROOT / "tools" / "drm_color_pipeline_probe.cpp"


class TraceSafetyTest(unittest.TestCase):
    def test_guard_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(GUARD)], check=True)

    def test_guard_rejects_enabled_dma_fence_event(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "events" / "dma_fence" / "dma_fence_signaled"
            event.mkdir(parents=True)
            (event / "enable").write_text("1\n")

            result = subprocess.run(
                [str(GUARD), directory],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing latency capture", result.stderr)

    def test_guard_accepts_disabled_dma_fence_events(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "events" / "dma_fence" / "dma_fence_signaled"
            event.mkdir(parents=True)
            (event / "enable").write_text("0\n")

            subprocess.run([str(GUARD), directory], check=True, capture_output=True)

    def test_capture_preflights_before_creating_artifacts(self):
        script = CAPTURE.read_text()
        guard_call = '"$root/scripts/check_trace_safety.sh"'
        self.assertIn(guard_call, script)
        self.assertLess(script.index(guard_call), script.index('mkdir -p "$destination"'))

    def test_controller_preflights_before_capture_delay(self):
        script = CONTROL.read_text()
        function = script.split("trace_command() {", 1)[1].split("\nbuild_command() {", 1)[0]
        self.assertIn('"$ROOT/scripts/check_trace_safety.sh"', function)
        self.assertLess(
            function.index('"$ROOT/scripts/check_trace_safety.sh"'),
            function.index("sleep 5"),
        )

    def test_runtime_entrypoints_do_not_start_kernel_collectors(self):
        runtime_files = [CONTROL, CAPTURE]
        runtime_files.extend(
            path
            for path in (ROOT / "scripts").glob("*.sh")
            if path != GUARD
        )
        forbidden = (
            "perf record",
            "perf trace",
            "trace-cmd",
            "bpftrace",
            "/events/dma_fence/",
        )
        for path in runtime_files:
            source = path.read_text()
            for token in forbidden:
                self.assertNotIn(token, source, f"{path} contains forbidden collector token {token}")

    def test_drm_color_probe_has_no_state_mutation_entrypoints(self):
        source = DRM_COLOR_PROBE.read_text()
        for forbidden in (
            "drmModeAtomicCommit",
            "drmModeObjectSetProperty",
            "drmModeSetCrtc",
            "drmModeSetPlane",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
