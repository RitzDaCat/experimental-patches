# Package versioning policy

The project must not outrank future CachyOS KWin packages merely to identify an
internal experiment revision.

## Pacman-visible version

The patched package uses the same `pkgver-pkgrel` as the CachyOS package it was
built to replace. For the current source boundary that is:

```text
pkgver=6.7.5
pkgrel=1.1
```

This intentionally compares equal to the current CachyOS package. A later
repository release such as `6.7.5-1.2`, `6.7.5-2.1`, `6.7.6-1.1`, or
`6.8.0-1.1` therefore supersedes it during a normal system upgrade.

`tests/test_package_versioning.py` reads the boundary from `pacman -Si kwin`
rather than a literal, because CachyOS rebuilds KWin for unrelated ABI bumps.

## Project revision

The experiment revision is separate:

```text
_kwin_latency_revision=24
```

It is recorded in `pkgdesc`, package extended metadata, the artifact checksum
manifest, and the repository documentation. It must not be encoded as a larger
`pkgrel`, an epoch, or a suffix on `pkgver`; each of those can hide legitimate
distribution updates from pacman.

## Required checks

Before publishing or installing a candidate:

1. Read the preferred repository version with `pacman -Si kwin`.
2. Require the candidate version to compare equal to that version.
3. Verify representative future repository versions compare newer with
   `vercmp`.
4. Preserve the signed CachyOS package in `/var/cache/pacman/pkg/` or refresh it
   with `pacman -Sw kwin` before testing.
5. Keep `IgnorePkg=kwin` out of pacman configuration.

If CachyOS advances KWin, rebase and rebuild the patch series. Do not force the
older experiment back over the newer compositor.
