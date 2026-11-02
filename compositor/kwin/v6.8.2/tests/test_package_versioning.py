import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageVersioningTest(unittest.TestCase):
    def values(self):
        script = """
            source PKGBUILD
            printf '%s\n' "$pkgver-$pkgrel" "$_kwin_latency_revision"
        """
        output = subprocess.run(
            ["bash", "-c", script],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
        return output[0], output[1]

    def repository_version(self):
        # The literal boundary went stale twice when CachyOS rebuilt KWin
        # without touching the source, so read it from pacman instead.
        output = subprocess.run(
            ["pacman", "-Si", "kwin"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        return next(
            line.split(":", 1)[1].strip()
            for line in output.splitlines()
            if line.startswith("Version")
        )

    def future_versions(self, version):
        pkgver, pkgrel = version.split("-", 1)
        distro, local = pkgrel.split(".", 1)
        major, minor, patch = (int(part) for part in pkgver.split("."))
        return (
            f"{pkgver}-{distro}.{int(local) + 1}",
            f"{pkgver}-{int(distro) + 1}.1",
            f"{major}.{minor}.{patch + 1}-1.1",
            f"{major}.{minor + 1}.0-1.1",
        )

    def release_values(self):
        values = {}
        for line in (ROOT / "artifacts" / "RELEASE").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
        return values

    def test_source_revision_is_not_pacman_pkgrel(self):
        version, revision = self.values()
        self.assertRegex(version, r"^\d+\.\d+\.\d+-\d+\.\d+$")
        self.assertGreater(int(revision), 0)
        self.assertNotIn(revision, version)

    @unittest.skipUnless(shutil.which("pacman"), "pacman is required to read the repository version")
    def test_candidate_matches_repository_version(self):
        version, _ = self.values()
        # Equal, never greater: the patched package must not outrank a later
        # CachyOS release during a normal system upgrade.
        self.assertEqual(version, self.repository_version())

    @unittest.skipUnless(shutil.which("bsdtar"), "bsdtar is required to inspect the package")
    def test_promoted_revision_matches_source_and_candidate_package(self):
        _, source_revision = self.values()
        release = self.release_values()
        package = ROOT / "artifacts" / "packages" / release["CANDIDATE_PACKAGE"]
        if not package.is_file():
            # Built packages are deliberately not committed, so a fresh clone or
            # a CI checkout has nothing to inspect. The source-side assertion
            # below still runs; only the package pairing is unprovable here.
            self.assertGreaterEqual(int(source_revision), int(release["PROJECT_REVISION"]))
            self.skipTest(f"candidate package not built: {package.name}")
        metadata = subprocess.run(
            ["bsdtar", "-xOf", package, ".PKGINFO"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        package_revision = next(
            line.split("=", 2)[2]
            for line in metadata.splitlines()
            if line.startswith("xdata = kwin-latency-revision=")
        )
        # The promoted revision must describe the package that is actually
        # installable; that pairing is what went stale before.
        self.assertEqual(release["PROJECT_REVISION"], package_revision)
        # PKGBUILD may stage a later revision than the promoted one, but it must
        # never fall behind it, or the source stops reproducing the package.
        self.assertGreaterEqual(int(source_revision), int(release["PROJECT_REVISION"]))

    @unittest.skipUnless(shutil.which("vercmp"), "vercmp is provided by pacman")
    def test_future_repository_releases_supersede_candidate(self):
        version, _ = self.values()
        for future in self.future_versions(version):
            result = subprocess.run(
                ["vercmp", version, future],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertLess(int(result.stdout), 0, future)


if __name__ == "__main__":
    unittest.main()
