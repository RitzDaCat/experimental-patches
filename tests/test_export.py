# SPDX-License-Identifier: GPL-2.0-only
"""Pin the export contract: pristine base hashes, new files absent, series names checked."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

EXPORT = Path(__file__).resolve().parents[1] / "scripts/export_series.py"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


class ExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="export-test-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.repo, self.out = root / "fork", root / "set"
        self.repo.mkdir()
        self.out.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / "value.txt").write_text("original\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.git("tag", "base-1")
        (self.repo / "value.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("new\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "area: change value")
        (self.out / "base.json").write_text('{"repository": "https://example.org/fork"}\n')

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, timeout=10,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(self.repo), **IDENTITY})

    def export(self, expected=0):
        result = subprocess.run(
            ["python3", str(EXPORT), "--repo", str(self.repo), "--base", "base-1",
             "--head", "main", str(self.out)], capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_pins_pristine_base(self):
        self.export()
        digest = hashlib.sha256(b"original\n").hexdigest()
        self.assertEqual((self.out / "base.sha256").read_text(), f"{digest}  value.txt\n")
        self.assertEqual((self.out / "series.all").read_text(), "0001-area-change-value.patch\n")
        self.assertEqual(json.loads((self.out / "base.json").read_text())["tag"], "base-1")

    def test_rejects_stale_series_name(self):
        (self.out / "series").write_text("0001-old-name.patch\n")
        self.assertIn("0001-old-name.patch is not an exported patch", self.export(expected=1).stderr)


if __name__ == "__main__":
    unittest.main()
