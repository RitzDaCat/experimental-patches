import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_latency_game import install_stubs


ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "bin" / "kwin-latencyctl"
GAME = ROOT / "bin" / "kwin-latency-game"
TRACE = ROOT / "scripts" / "capture_pipeline_window.sh"
COLOR_TEST = ROOT / "scripts" / "run_color_validation.sh"


class LatencyControlTest(unittest.TestCase):
    def run_ctl(self, *arguments, config_home=None, stub_kconfig=None):
        environment = os.environ.copy()
        if config_home is not None:
            environment["XDG_CONFIG_HOME"] = str(config_home)
        if stub_kconfig is not None:
            # Never let a test reach the real kwriteconfig6: it would rewrite
            # the developer's own kwinrc and notify their live compositor.
            install_stubs(stub_kconfig / "stubs")
            (stub_kconfig / "state").mkdir(exist_ok=True)
            environment["PATH"] = os.pathsep.join(
                [str(stub_kconfig / "stubs"), environment["PATH"]]
            )
            environment["STUB_LOG"] = str(stub_kconfig / "argv.log")
            environment["STUB_STATE"] = str(stub_kconfig / "state")
        return subprocess.run(
            [str(CTL), *arguments],
            cwd=ROOT,
            env=environment,
            check=True,
            text=True,
            capture_output=True,
        )

    def test_script_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(CTL)], check=True)
        subprocess.run(["bash", "-n", str(TRACE)], check=True)
        subprocess.run(["bash", "-n", str(COLOR_TEST)], check=True)

    def test_help_exposes_one_policy_without_presets(self):
        output = self.run_ctl("help").stdout
        self.assertIn("one reviewed low-latency policy", output)
        self.assertIn("capture-on", output)
        self.assertIn("capture-off", output)
        self.assertIn("--capture", output)
        self.assertNotIn("preset", "\n".join(line for line in output.splitlines() if line.startswith("  ")))

    def test_install_can_stage_capture_before_the_same_restart(self):
        script = CTL.read_text()
        self.assertIn("--capture) capture=1", script)
        self.assertIn('write_policy "$kernel" "$capture"', script)

    def test_dry_run_enable_writes_only_three_effective_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            profile = config_home / "environment.d" / "90-kwin-latency.conf"
            profile.parent.mkdir(parents=True)
            original = "user-owned sentinel\n"
            profile.write_text(original)

            output = self.run_ctl(
                "--dry-run",
                "enable",
                "--kernel",
                "test-kernel",
                config_home=config_home,
            ).stdout

            rendered = output.split(f"Would write {profile}:\n", 1)[1].split("DRY RUN:", 1)[0]
            settings = [line for line in rendered.splitlines() if line.startswith("KWIN_")]
            self.assertEqual(
                settings,
                [
                    "KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=test-kernel",
                    "KWIN_ADAPTIVE_COMPOSITOR_MARGIN=2",
                    "KWIN_VRR_REPAINT_COALESCING=1",
                ],
            )
            self.assertEqual(profile.read_text(), original)

    def test_capture_is_one_master_switch_and_render_budget_is_shadow_only(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "--dry-run",
                "capture-on",
                "--kernel",
                "test-kernel",
                config_home=config_home,
            ).stdout
            settings = [line for line in output.splitlines() if line.startswith("KWIN_")]
            self.assertEqual(
                settings,
                [
                    "KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=test-kernel",
                    "KWIN_ADAPTIVE_COMPOSITOR_MARGIN=2",
                    "KWIN_VRR_REPAINT_COALESCING=1",
                    "KWIN_LATENCY_CAPTURE=1",
                    "KWIN_ADAPTIVE_RENDER_BUDGET=1",
                ],
            )
            self.assertIn("shadow-only", output)

    def test_esports_policy_activates_render_budget_control(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "--dry-run",
                "esports",
                "--kernel",
                "test-kernel",
                config_home=config_home,
            ).stdout
            settings = [line for line in output.splitlines() if line.startswith("KWIN_")]
            self.assertEqual(
                settings,
                [
                    "KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=test-kernel",
                    "KWIN_ADAPTIVE_COMPOSITOR_MARGIN=2",
                    "KWIN_VRR_REPAINT_COALESCING=1",
                    "KWIN_ADAPTIVE_RENDER_BUDGET=2",
                ],
            )
            self.assertIn("ACTIVE", output)
            set_environment = next(
                line for line in output.splitlines() if "--user set-environment" in line
            )
            self.assertNotIn("KWIN_LATENCY_CAPTURE", set_environment)

    def test_capture_off_preserves_performance_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            profile = config_home / "environment.d" / "90-kwin-latency.conf"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                "KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=test-kernel\n"
                "KWIN_LATENCY_CAPTURE=1\n"
            )
            output = self.run_ctl("--dry-run", "capture-off", config_home=config_home).stdout
            rendered = output.split(f"Would write {profile}:\n", 1)[1].split("DRY RUN:", 1)[0]
            self.assertNotIn("KWIN_LATENCY_CAPTURE", rendered)
            self.assertIn("KWIN_ADAPTIVE_COMPOSITOR_MARGIN=2", rendered)

    def test_dry_run_disable_preserves_existing_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            profile = config_home / "environment.d" / "90-kwin-latency.conf"
            profile.parent.mkdir(parents=True)
            original = "user-owned sentinel\n"
            profile.write_text(original)

            output = self.run_ctl("--dry-run", "disable", config_home=config_home).stdout

            self.assertIn(f"rm -f {profile}", output)
            self.assertEqual(profile.read_text(), original)

    def test_help_documents_the_opt_in_model_and_the_per_game_wrapper(self):
        output = self.run_ctl("help").stdout
        self.assertIn("game [--off] -- CMD", output)
        self.assertIn("kwin-latency-game -- %command%", output)
        self.assertIn("defaults OFF", output)
        self.assertIn("LatencyExperiment", output)

    def test_enable_dry_run_writes_the_live_kwinrc_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "--dry-run",
                "enable",
                "--kernel",
                "test-kernel",
                config_home=config_home,
                stub_kconfig=config_home,
            ).stdout
            self.assertIn(
                "DRY RUN: kwriteconfig6 --file kwinrc --group LatencyExperiment "
                "--key Enabled --notify true",
                output,
            )
            self.assertIn("Opt-in (kwinrc):  enabled", output)
            self.assertIn("live immediately on a revision 22 compositor", output)

    def test_esports_dry_run_adds_the_active_render_budget_to_kwinrc(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "--dry-run",
                "esports",
                "--kernel",
                "test-kernel",
                config_home=config_home,
                stub_kconfig=config_home,
            ).stdout
            self.assertIn(
                "DRY RUN: kwriteconfig6 --file kwinrc --group LatencyExperiment "
                "--key Enabled --notify true",
                output,
            )
            self.assertIn(
                "DRY RUN: kwriteconfig6 --file kwinrc --group LatencyExperiment "
                "--key RenderBudgetMode --notify 2",
                output,
            )

    def test_disable_dry_run_removes_every_kwinrc_key(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "--dry-run",
                "disable",
                config_home=config_home,
                stub_kconfig=config_home,
            ).stdout
            for key in (
                "Enabled",
                "SchedulerMarginMode",
                "RenderBudgetMode",
                "VrrRepaintCoalescing",
                "SchedulerMarginUs",
            ):
                self.assertIn(
                    "DRY RUN: kwriteconfig6 --file kwinrc --group LatencyExperiment "
                    f"--key {key} --notify --delete",
                    output,
                )
            # Deletion is a mutation, so --dry-run must not have performed it.
            self.assertFalse((config_home / "argv.log").exists())

    def test_status_states_the_opt_in_policy_unambiguously(self):
        with tempfile.TemporaryDirectory() as directory:
            config_home = Path(directory)
            output = self.run_ctl(
                "status", config_home=config_home, stub_kconfig=config_home
            ).stdout
            self.assertIn(
                "Opt-in (kwinrc):  disabled (stock policy; key absent, "
                "revision 22 defaults off)",
                output,
            )
            for key in ("Enabled", "SchedulerMarginMode", "SchedulerMarginUs"):
                self.assertIn(f"  LatencyExperiment/{key}: absent", output)

            (config_home / "state" / "Enabled").write_text("true")
            enabled = self.run_ctl(
                "status", config_home=config_home, stub_kconfig=config_home
            ).stdout
            self.assertIn("Opt-in (kwinrc):  enabled", enabled)
            self.assertIn("  LatencyExperiment/Enabled: true", enabled)

    def test_status_survives_a_machine_without_the_kconfig_tools(self):
        script = CTL.read_text()
        self.assertIn("command -v kreadconfig6 >/dev/null || return 0", script)
        self.assertIn('note "Opt-in (kwinrc):  unknown (kreadconfig6 not installed)"', script)

    def test_game_is_a_passthrough_that_bypasses_the_global_option_filter(self):
        script = CTL.read_text()
        self.assertTrue(GAME.exists() and os.access(GAME, os.X_OK))
        self.assertIn('if [[ ${1:-} == game ]]; then', script)
        self.assertLess(script.index("== game ]]"), script.index("filtered=()"))
        self.assertIn('exec "$GAME_WRAPPER" "$@"', script)

    def test_install_message_teaches_the_opt_in_model(self):
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("Installing enabled nothing", installer)
        self.assertIn("./bin/kwin-latencyctl enable", installer)
        self.assertIn("kwin-latency-game -- %command%", installer)

    def test_snapshot_covers_every_interactive_pipeline_domain(self):
        script = CTL.read_text()
        for artifact in (
            "scheduling.txt",
            "audio.txt",
            "usb-and-irqs.txt",
            "input.txt",
            "output-and-drm.txt",
        ):
            self.assertIn(artifact, script)

    def test_trace_is_fixed_duration_and_does_not_enable_telemetry(self):
        script = TRACE.read_text()
        self.assertIn("duration_seconds=10", script)
        self.assertIn("auxiliary_duration_seconds=10", script)
        self.assertNotIn("KWIN_LOG_PERFORMANCE_DATA=1", script)
        self.assertNotIn("KWIN_INPUT_LATENCY_TELEMETRY=1", script)
        self.assertIn("kwin\\ drm\\ timing", script)
        self.assertIn("nvidia-window.csv", script)
        self.assertLess(script.index('sleep "$duration_seconds"'), script.index("nvidia-window.csv"))
        self.assertIn("clock-correlation.tsv", script)
        self.assertIn("drm-color-before.txt", script)

    def test_trace_requires_the_corrected_revision15_live_schema(self):
        controller = CTL.read_text()
        self.assertIn("completion callback timestamp", controller)
        self.assertIn("scene frame and postpaint duration", controller)
        self.assertIn("queued_ns", controller)
        self.assertIn("not the corrected revision 15 schema", controller)

    def test_color_validation_uses_exact_nearest_neighbor_blocks(self):
        script = COLOR_TEST.read_text()
        self.assertIn("--scale=nearest", script)
        self.assertIn("--target-prim=bt.709", script)
        self.assertIn("--target-trc=srgb", script)
        self.assertTrue((ROOT / "tools" / "color-validation-pattern.ppm").exists())


if __name__ == "__main__":
    unittest.main()
