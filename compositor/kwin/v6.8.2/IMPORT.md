# Standalone KWin bundle

Imported from the author's committed KWin experiment revision 24, source
revision `9ab1ecc9e540a559a0dee8581836ad30de88ea80`, on 2026-10-08, and synced
to revision 25 (`dea7b6d4b0d461caa635a622501beb5af32a8341`) on 2026-10-09:
`--kernel REL` for the baked gate and a `check()` that avoids the live DRM node.
Synced to revision 26 (`a2e77692460ded2ac03cf2840b541557d81093fc`) on
2026-11-02: the port to KWin 6.8.2, with this directory moved from
`v6.7.5/` to `v6.8.2/`.
The files required to build, verify, install, activate, compare, capture and
recover are included in this directory. The development repository is not a
tester dependency.

The public base is KWin 6.8.2, archive SHA-256
`ea5e68d957c7d70abed97222a592d4445fda29129e20942658badd224ee138b4`.
The package recipe downloads that public release and distribution dependencies;
all patches and package helper scripts are supplied locally.

Standalone adaptations:

- The patches are byte-identical to the development repository's; every one
  applies to the 6.8.2 tarball with no fuzz. The package recipe and the
  source-reference verification forbid fuzzy matching.
- Package version `6.8.2-1.1` matches the CachyOS repository on 2026-11-02.
  The installer still requires that equality at install time; future
  repository version changes need a recipe update before testing.
- `kwin-latencyctl test --source-only` verifies the source/model/graph gates
  without requiring an already-built package. Model tests use standard-library
  unittest and do not create Python or pytest caches.
- Local package hashes start empty and are recorded by `install.sh` after a
  build. No author's binary packages, source archives or machine captures are
  included.
- The observer microbenchmark's source is included; its helper writes only
  to the ignored `artifacts/observer-bench/` folder.

The copied dated research documents describe their original observations and
may cover older bases. The current build base and experiment revision are
specified by `PKGBUILD` and `artifacts/RELEASE`. The revision 26 series was
compiled in full against KWin 6.8.2 and its patched-path tests pass; no
package has been built, installed or visually tested.
