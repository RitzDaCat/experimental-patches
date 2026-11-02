# SPDX-License-Identifier: GPL-2.0-only
"""Exercise target provenance and complete-stack checks on disposable source trees."""
import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_compatibility.py"
spec = importlib.util.spec_from_file_location("compatibility_checker", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="compatibility-test-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "value.txt").write_text("original\n")
        self.directory = self.root / "component/v1"
        self.directory.mkdir(parents=True)
        self.root_patch = mock.patch.object(checker, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.base = {"repository": "https://example.org/source.git", "commit": "a" * 40}
        (self.directory / "base.json").write_text(json.dumps(self.base))
        self.target = {
            "id": "fixture", "patch_set": "component/v1", "status": "port-required",
            "base": dict(self.base),
            "files": {"value.txt": hashlib.sha256(b"original\n").hexdigest()},
            "absent_files": [], "patches": {},
            "tracking": [{"kind": "git", "repository": self.base["repository"],
                          "ref": "refs/heads/main", "commit": "a" * 40}],
        }

    def patch(self, name, before, after, path="value.txt", new=False):
        text = "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile="/dev/null" if new else "a/" + path, tofile="b/" + path,
        ))
        (self.directory / name).write_text(text)
        self.target["patches"][name] = hashlib.sha256(text.encode()).hexdigest()
        (self.directory / "series").write_text("\n".join(sorted(self.target["patches"])) + "\n")

    def manifest(self):
        path = self.root / "targets.json"
        path.write_text(json.dumps({"schema": 1, "targets": [self.target]}))
        return path

    def test_dependent_stack_can_pass_while_isolated_probe_fails(self):
        self.patch("0001.patch", "original\n", "first\n")
        self.patch("0002.patch", "first\n", "second\n")
        result = checker.check_target(self.target, self.source)
        self.assertTrue(result["compatible"])
        self.assertEqual([p["status"] for p in result["stack"]], ["applies", "applies"])
        self.assertEqual([p["status"] for p in result["isolated_pristine_probes"]],
                         ["applies", "fails"])
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_failure_blocks_stack_but_every_remaining_patch_is_probed(self):
        self.patch("0001.patch", "original\n", "first\n")
        self.patch("0002.patch", "wrong\n", "second\n")
        self.patch("0003.patch", "", "created\n", "new.txt", new=True)
        self.target["absent_files"] = ["new.txt"]
        result = checker.check_target(self.target, self.source)
        self.assertFalse(result["compatible"])
        self.assertEqual([p["status"] for p in result["stack"]],
                         ["applies", "fails", "blocked"])
        self.assertEqual(result["stack"][2]["blocked_by"], "0002.patch")
        self.assertEqual(result["isolated_pristine_probes"][2]["status"], "applies")
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), ["value.txt"])
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_recorded_full_series_overrides_identity_only_default(self):
        self.patch("0001.patch", "original\n", "feature\n")
        self.patch("0002.patch", "", "identity\n", "new.txt", new=True)
        self.target["absent_files"] = ["new.txt"]
        (self.directory / "series.all").write_text("0001.patch\n0002.patch\n")
        (self.directory / "series").write_text("0002.patch\n")
        self.target["series"] = "series.all"
        checker.load_manifest(self.manifest())
        result = checker.check_target(self.target, self.source)
        self.assertTrue(result["compatible"])
        self.assertEqual(result["series"], "series.all")
        self.assertEqual(len(result["stack"]), 2)

    def test_wrong_preimage_and_symlink_are_rejected_before_patching(self):
        self.patch("0001.patch", "original\n", "changed\n")
        path = self.source / "value.txt"
        path.write_text("local work\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            checker.check_target(self.target, self.source)
        outside = self.root / "outside.txt"
        outside.write_text("original\n")
        path.unlink()
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlinked"):
            checker.check_target(self.target, self.source)
        self.assertEqual(outside.read_text(), "original\n")

    def test_explicit_upstream_patch_retains_its_reason(self):
        self.patch("0001.patch", "wrong preimage\n", "changed\n")
        self.target["skip_patches"] = {
            "0001.patch": {"status": "upstream", "reason": "Already in this exact base."},
        }
        result = checker.check_target(self.target, self.source)
        self.assertTrue(result["compatible"])
        self.assertEqual(result["stack"][0]["status"], "upstream")
        self.assertEqual(result["isolated_pristine_probes"][0]["reason"],
                         "Already in this exact base.")

    def test_changed_patch_invalidates_recorded_target_audit(self):
        self.patch("0001.patch", "original\n", "changed\n")
        manifest = self.manifest()
        checker.load_manifest(manifest)
        with (self.directory / "0001.patch").open("a") as stream:
            stream.write("\nChanged patch description\n")
        with self.assertRaisesRegex(ValueError, "patch hash changed"):
            checker.load_manifest(manifest)

    def test_target_cannot_be_promoted_with_an_older_donor_base(self):
        self.patch("0001.patch", "original\n", "changed\n")
        self.target["status"] = "applies"
        self.target["base"]["commit"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "different source base"):
            checker.load_manifest(self.manifest())

    def test_report_output_cannot_overwrite_a_supplied_source_file(self):
        self.patch("0001.patch", "original\n", "changed\n")
        args = [str(SCRIPT), "fixture", str(self.source), "--output", str(self.source / "value.txt")]
        error = io.StringIO()
        with mock.patch.object(checker, "load_manifest", return_value={"targets": [self.target]}), \
                mock.patch("sys.argv", args), contextlib.redirect_stderr(error):
            self.assertEqual(checker.main(), 2)
        self.assertIn("outside the supplied source tree", error.getvalue())
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_package_listing_excludes_related_packages_and_signatures(self):
        page = """
        <a href="linux-cachyos-7.3.0-3-x86_64_v4.pkg.tar.zst">pkg</a>
        <a href="linux-cachyos-7.3.0-3-x86_64_v4.pkg.tar.zst.sig">sig</a>
        <a href="linux-cachyos-headers-7.3.0-3-x86_64_v4.pkg.tar.zst">headers</a>
        <a href="linux-cachyos-rc-7.4.rc1-1-x86_64_v4.pkg.tar.zst">rc</a>
        """
        self.assertEqual(checker.package_versions(page, "linux-cachyos"), ["7.3.0-3"])

    def test_unchanged_tracking_does_not_clear_a_required_port(self):
        with mock.patch.object(checker, "remote_commit", return_value="a" * 40):
            result = checker.check_updates({"targets": [self.target]})
        self.assertTrue(result["targets"][0]["tracking_current"])
        self.assertFalse(result["all_current"])

    def test_remote_failure_does_not_report_current(self):
        self.target["status"] = "applies"
        with mock.patch.object(checker, "remote_commit", side_effect=OSError("unreachable")):
            result = checker.check_updates({"targets": [self.target]})
        self.assertFalse(result["all_current"])
        self.assertIn("unreachable", result["targets"][0]["checks"][0]["error"])


if __name__ == "__main__":
    unittest.main()
