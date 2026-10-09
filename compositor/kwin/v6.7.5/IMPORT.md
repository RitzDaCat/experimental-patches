# Standalone KWin bundle

Imported from the author's committed KWin experiment revision 24, source
revision `9ab1ecc9e540a559a0dee8581836ad30de88ea80`, on 2026-10-08.
The files required to build, verify, install, activate, compare, capture and
recover are included in this directory. The development repository is not a
tester dependency.

The public base is KWin 6.7.5, archive SHA-256
`6baa910b732d93c48c90f9c1cc685cc93d0b8de0cdf138c24192c045bc3a48e2`.
The package recipe downloads that public release and distribution dependencies;
all patches and package helper scripts are supplied locally.

Standalone adaptations:

- Patch 0003's context was regenerated from the exact base and preceding
  patches, because its original context required fuzzy matching on 6.7.5.
  All 35 final source files exactly match the retained revision-24 overlay;
  the code changes are unchanged.
- The package recipe now takes both upstream backports from the included files,
  pins the regenerated patch hash, and forbids fuzzy matching. Source-reference
  verification uses the same strict application.
- Package version `6.7.5-3.1` matches the configured distribution repository
  verified on 2026-10-08. The installer still requires that equality at install
  time; future repository version changes need a recipe update before testing.
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
specified by `PKGBUILD` and `artifacts/RELEASE`. The imported source has not been
rebuilt, installed or visually tested as this standalone bundle during preparation.
