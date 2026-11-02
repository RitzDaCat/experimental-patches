import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "bin" / "kwin-latency-game"
CTL = ROOT / "bin" / "kwin-latencyctl"
BASH = shutil.which("bash") or "/bin/bash"

KWRITECONFIG_STUB = """#!/usr/bin/env bash
# Record the exact argv, then apply the write to a directory of key files so a
# later kreadconfig6 sees what this call did. Absent key == absent file, which
# is the distinction the wrapper's restore path depends on.
printf '%s ' "$@" >> "$STUB_LOG"
printf '\\n' >> "$STUB_LOG"
key=
value=
delete=0
arguments=("$@")
index=0
while (( index < ${#arguments[@]} )); do
    case ${arguments[index]} in
        --key) key=${arguments[index + 1]}; index=$(( index + 2 )) ;;
        --file|--group|--type) index=$(( index + 2 )) ;;
        --notify) index=$(( index + 1 )) ;;
        --delete) delete=1; index=$(( index + 1 )) ;;
        *) value=${arguments[index]}; index=$(( index + 1 )) ;;
    esac
done
if (( delete )); then
    rm -f "$STUB_STATE/$key"
else
    printf '%s' "$value" > "$STUB_STATE/$key"
fi
exit 0
"""

KREADCONFIG_STUB = """#!/usr/bin/env bash
printf '%s ' "$@" >> "$STUB_LOG"
printf '\\n' >> "$STUB_LOG"
key=
arguments=("$@")
index=0
while (( index < ${#arguments[@]} )); do
    case ${arguments[index]} in
        --key) key=${arguments[index + 1]}; index=$(( index + 2 )) ;;
        --file|--group|--type) index=$(( index + 2 )) ;;
        *) index=$(( index + 1 )) ;;
    esac
done
if [[ -f $STUB_STATE/$key ]]; then
    cat "$STUB_STATE/$key"
    printf '\\n'
fi
exit 0
"""


def install_stubs(directory, tools=("kwriteconfig6", "kreadconfig6")):
    """Place fake KConfig tools on a directory destined for PATH."""
    bodies = {"kwriteconfig6": KWRITECONFIG_STUB, "kreadconfig6": KREADCONFIG_STUB}
    directory.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        path = directory / tool
        path.write_text(bodies[tool])
        path.chmod(0o755)


class LatencyGameWrapperTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        base = Path(self.directory.name)
        self.stubs = base / "stubs"
        self.state = base / "state"
        self.log = base / "argv.log"
        install_stubs(self.stubs)
        self.state.mkdir()
        self.log.touch()

    def environment(self, isolated_path=False, session=True):
        environment = os.environ.copy()
        if isolated_path:
            environment["PATH"] = str(self.stubs)
        else:
            environment["PATH"] = os.pathsep.join([str(self.stubs), environment["PATH"]])
        environment["STUB_LOG"] = str(self.log)
        environment["STUB_STATE"] = str(self.state)
        environment["XDG_CONFIG_HOME"] = str(Path(self.directory.name) / "config")
        if session:
            environment["WAYLAND_DISPLAY"] = "wayland-test"
        else:
            environment.pop("WAYLAND_DISPLAY", None)
            environment.pop("DISPLAY", None)
        return environment

    def run_wrapper(self, *arguments, isolated_path=False, session=True):
        return subprocess.run(
            [BASH, str(WRAPPER), *arguments],
            cwd=ROOT,
            env=self.environment(isolated_path=isolated_path, session=session),
            text=True,
            capture_output=True,
        )

    def writes(self):
        """Every logged kwriteconfig6 argv line, in call order."""
        return [
            line.strip()
            for line in self.log.read_text().splitlines()
            if "--notify" in line
        ]

    def stored(self, key):
        path = self.state / key
        return path.read_text() if path.exists() else None

    def test_wrapper_is_executable_standalone_bash(self):
        subprocess.run([BASH, "-n", str(WRAPPER)], check=True)
        self.assertTrue(os.access(WRAPPER, os.X_OK))
        text = WRAPPER.read_text()
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        # Installed to /usr/bin later, so it must not reach back into the repo.
        self.assertNotIn("BASH_SOURCE", text)
        self.assertNotIn("$ROOT", text)

    def test_enables_then_restores_a_previously_absent_key_by_deleting_it(self):
        result = self.run_wrapper("--", "/bin/true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.writes(),
            [
                "--file kwinrc --group LatencyExperiment --key Enabled --notify true",
                "--file kwinrc --group LatencyExperiment --key Enabled --notify --delete",
            ],
        )
        self.assertIsNone(self.stored("Enabled"))

    def test_restores_a_previously_set_value_instead_of_deleting_it(self):
        (self.state / "Enabled").write_text("false")
        result = self.run_wrapper("--", "/bin/true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.writes(),
            [
                "--file kwinrc --group LatencyExperiment --key Enabled --notify true",
                "--file kwinrc --group LatencyExperiment --key Enabled --notify false",
            ],
        )
        self.assertEqual(self.stored("Enabled"), "false")

    def test_failing_command_still_restores_and_propagates_its_status(self):
        result = self.run_wrapper("--", "/bin/sh", "-c", "exit 7")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            self.writes()[-1],
            "--file kwinrc --group LatencyExperiment --key Enabled --notify --delete",
        )
        self.assertIsNone(self.stored("Enabled"))

    def test_off_writes_false_for_one_command_and_restores_the_session_value(self):
        (self.state / "Enabled").write_text("true")
        result = self.run_wrapper("--off", "--", "/bin/true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.writes(),
            [
                "--file kwinrc --group LatencyExperiment --key Enabled --notify false",
                "--file kwinrc --group LatencyExperiment --key Enabled --notify true",
            ],
        )
        self.assertEqual(self.stored("Enabled"), "true")

    def test_only_the_keys_it_changes_are_touched(self):
        (self.state / "RenderBudgetMode").write_text("2")
        self.run_wrapper("--", "/bin/true")
        self.assertEqual(self.stored("RenderBudgetMode"), "2")
        for write in self.writes():
            self.assertNotIn("RenderBudgetMode", write)

    def test_command_arguments_pass_through_unmangled(self):
        result = self.run_wrapper(
            "--", "/bin/sh", "-c", 'printf "%s|" "$@"', "sh", "--off", "--dry-run", "a b"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--off|--dry-run|a b|", result.stdout)

    def test_missing_separator_or_command_is_refused(self):
        missing_separator = self.run_wrapper("/bin/true")
        self.assertNotEqual(missing_separator.returncode, 0)
        self.assertIn("unknown option", missing_separator.stderr)

        empty = self.run_wrapper("--")
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("no command given", empty.stderr)

    def test_missing_kwriteconfig6_is_a_clear_error(self):
        install_stubs(self.stubs, tools=("kreadconfig6",))
        (self.stubs / "kwriteconfig6").unlink()
        result = self.run_wrapper("--", "/bin/true", isolated_path=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kwriteconfig6 not found", result.stderr)

    def test_absent_session_warns_but_still_runs_the_command(self):
        result = self.run_wrapper("--", "/bin/sh", "-c", "printf ran", session=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ran", result.stdout)
        self.assertIn("no Wayland or X11 session", result.stderr)


class LatencyControlGamePassthroughTest(LatencyGameWrapperTest):
    def run_wrapper(self, *arguments, isolated_path=False, session=True):
        return subprocess.run(
            [str(CTL), "game", *arguments],
            cwd=ROOT,
            env=self.environment(isolated_path=isolated_path, session=session),
            text=True,
            capture_output=True,
        )

    def test_wrapper_is_executable_standalone_bash(self):
        self.skipTest("file-level assertions belong to the wrapper's own test case")

    def test_missing_kwriteconfig6_is_a_clear_error(self):
        self.skipTest("an isolated PATH cannot resolve the controller's own helpers")

    def test_game_passthrough_reaches_the_wrapper(self):
        result = self.run_wrapper("--", "/bin/echo", "wrapper-reached")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("wrapper-reached", result.stdout)
        self.assertIn("kwin-latency-game:", result.stdout)


if __name__ == "__main__":
    unittest.main()
