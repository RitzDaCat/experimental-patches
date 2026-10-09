# SPDX-License-Identifier: GPL-2.0-only
"""Exercise patch preflight failures against disposable source trees."""
import difflib
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

APPLY = Path(__file__).resolve().parents[1] / "scripts/apply.sh"


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="patch-helper-test-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source tree"
        self.source.mkdir()
        self.patch_set = self.root / "patch set"
        self.patch_set.mkdir()
        (self.source / "value.txt").write_text("original\n")
        self.pin_base()

    def pin_base(self):
        digest = hashlib.sha256((self.source / "value.txt").read_bytes()).hexdigest()
        (self.patch_set / "base.sha256").write_text(f"{digest}  value.txt\n")

    def patch(self, name, before, after, path="value.txt", new=False):
        header = f"diff --git a/{path} b/{path}\n"
        diff = "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True),
            fromfile="/dev/null" if new else f"a/{path}", tofile=f"b/{path}",
        ))
        (self.patch_set / name).write_text(header + diff)

    def run_helper(self, *args, expected=0):
        result = subprocess.run(
            [str(APPLY), str(self.patch_set), str(self.source), *args],
            cwd=self.root, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertFalse(list(self.source.rglob("*.rej")))
        self.assertFalse(list(self.source.rglob("*.orig")))
        return result

    def series(self, text, name="series"):
        (self.patch_set / name).write_text(text)

    def test_check_handles_dependent_patches_and_does_not_modify_source(self):
        self.patch("0001.patch", "original\n", "first\n")
        self.patch("0002.patch", "first\n", "second\n")
        self.series("# comment\n\n0001.patch\n0002.patch")
        self.run_helper("--check")
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")
        self.run_helper()
        self.assertEqual((self.source / "value.txt").read_text(), "second\n")

    def test_later_failure_preserves_original_tree(self):
        self.patch("0001.patch", "original\n", "first\n")
        self.patch("0002.patch", "wrong preimage\n", "second\n")
        self.series("0001.patch\n0002.patch\n")
        result = self.run_helper(expected=1)
        self.assertIn("failed preflight", result.stderr)
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_wrong_base_is_rejected_even_if_hunk_would_apply(self):
        self.patch("0001.patch", "original\n", "updated\n")
        self.series("0001.patch\n")
        (self.source / "value.txt").write_text("original\nextra local work\n")
        self.run_helper(expected=1)
        self.assertEqual((self.source / "value.txt").read_text(), "original\nextra local work\n")

    def test_missing_later_patch_is_rejected_before_source_changes(self):
        self.patch("0001.patch", "original\n", "updated\n")
        self.series("0001.patch\nmissing.patch\n")
        self.run_helper(expected=1)
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_new_files_and_unrelated_work_are_preserved_in_check(self):
        self.patch("0001.patch", "", "created\n", "nested/new.txt", new=True)
        self.series("0001.patch\n")
        (self.source / "unrelated.txt").write_text("local work\n")
        self.run_helper("--check")
        self.assertFalse((self.source / "nested").exists())
        self.run_helper()
        self.assertEqual((self.source / "nested/new.txt").read_text(), "created\n")
        self.assertEqual((self.source / "unrelated.txt").read_text(), "local work\n")

    def test_existing_new_file_is_not_overwritten(self):
        self.patch("0001.patch", "", "created\n", "new.txt", new=True)
        self.series("0001.patch\n")
        (self.source / "new.txt").write_text("local work\n")
        self.run_helper(expected=1)
        self.assertEqual((self.source / "new.txt").read_text(), "local work\n")

    def test_explicit_series_does_not_apply_other_candidates(self):
        self.patch("0001.patch", "original\n", "default\n")
        self.patch("0002.patch", "original\n", "optional\n")
        self.series("0001.patch\n")
        self.series("0002.patch\n", "series.research")
        self.run_helper("--series", "series.research")
        self.assertEqual((self.source / "value.txt").read_text(), "optional\n")

    def test_source_symlink_cannot_write_outside_tree(self):
        self.patch("0001.patch", "original\n", "updated\n")
        self.series("0001.patch\n")
        outside = self.root / "outside.txt"
        outside.write_text("original\n")
        (self.source / "value.txt").unlink()
        (self.source / "value.txt").symlink_to(outside)
        self.run_helper(expected=1)
        self.assertEqual(outside.read_text(), "original\n")

    def test_patch_path_escape_is_rejected(self):
        self.series("../outside.patch\n")
        self.run_helper(expected=1)
        self.assertEqual((self.source / "value.txt").read_text(), "original\n")

    def test_reapplication_fails_without_reversing(self):
        self.patch("0001.patch", "original\n", "updated\n")
        self.series("0001.patch\n")
        self.run_helper()
        self.run_helper(expected=1)
        self.assertEqual((self.source / "value.txt").read_text(), "updated\n")


if __name__ == "__main__":
    unittest.main()
