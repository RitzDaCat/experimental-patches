# KWin source reference

This directory preserves the exact source boundary for the latency experiment.

## Pristine upstream snapshot

`upstream/kwin-6.8.2/` is the complete, unmodified extraction of KDE's
`kwin-6.8.2.tar.xz` release archive. It is not committed;
`scripts/verify_reference_sources.sh` extracts it from the hash-checked archive.
To keep a local copy for browsing:

```bash
bsdtar -xf artifacts/sources/kwin-6.8.2.tar.xz -C reference/upstream/
```

- Source URL: `https://download.kde.org/stable/plasma/6.8.2/kwin-6.8.2.tar.xz`
- SHA-256: `ea5e68d957c7d70abed97222a592d4445fda29129e20942658badd224ee138b4`
- Files in archive snapshot: 3,248

The upstream licenses, copyright notices, build system, tests, backends, render
loop, DRM code, input stack, effects, and Wayland implementation are retained
as shipped so design questions can be answered against the exact baseline.

## Patched-source overlay

`patched-overlay/` contains every source file the series changes, after
applying the patches in PKGBUILD order. It is intentionally an overlay rather
than a second 55 MB source copy. The file set is exactly the set of files the
patches touch; list it with:

```bash
ls -R reference/patched-overlay
```

For an existing upstream file, compare the baseline and experiment directly:

```bash
git diff --no-index \
  reference/upstream/kwin-6.8.2/src/core/renderloop.cpp \
  reference/patched-overlay/src/core/renderloop.cpp
```

Run `scripts/verify_reference_sources.sh` to independently extract the archive,
reapply the series from the PKGBUILD source list, and byte-compare the pristine
tree (when vendored) and the patched overlay.
