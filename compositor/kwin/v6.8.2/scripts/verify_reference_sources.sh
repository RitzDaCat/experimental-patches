#!/usr/bin/env bash

# Modified 2026-10-08 for strict application in the standalone bundle.
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

# Derive the version from PKGBUILD instead of hardcoding it. A 6.7.3 literal here
# meant this script kept printing "reference verification passed" while PKGBUILD
# built 6.7.4 -- the 18-patch chain was only ever proven against a tree nobody
# installs. Reading pkgver and the tarball hash from PKGBUILD ties the proof to
# the artifact. Sourcing matches how tests/test_package_versioning.py reads it.
eval "$(bash -c 'source "$1"/PKGBUILD; printf "pkgver=%s\nexpected_archive_sha=%s\n" \
    "$pkgver" "${sha256sums[0]}"' _ "$project_root")"
[[ -n ${pkgver-} && -n ${expected_archive_sha-} ]] \
    || { printf 'could not read pkgver/sha256sums from PKGBUILD\n' >&2; exit 1; }

# The series is the PKGBUILD source list, in its order, so this proof cannot
# drift from what makepkg applies.
mapfile -t patches < <(bash -c 'source "$1"/PKGBUILD; for s in "${source[@]}"; do
    [[ $s == file://*/patches/*.patch ]] && printf "%s\n" "${s##*/}"; done' _ "$project_root")
(( ${#patches[@]} )) || { printf 'no patches in the PKGBUILD source list\n' >&2; exit 1; }

archive="$project_root/artifacts/sources/kwin-$pkgver.tar.xz"
archive_url="https://download.kde.org/stable/plasma/$pkgver/kwin-$pkgver.tar.xz"
upstream="$project_root/reference/upstream/kwin-$pkgver"
overlay="$project_root/reference/patched-overlay"

# The vendored pristine tree is optional. Every proof below runs against the
# tree extracted from the archive whose SHA-256 already matched PKGBUILD, so a
# local copy only re-proves that the copy equals that archive. It is 55 MB and
# 3245 files, which is why it is not carried in Git. Check it when it is here
# and skip it when it is not; never verify a tree vendored for another release.
verify_vendored_tree=0
if [[ -d $upstream ]]; then
    verify_vendored_tree=1
fi

workdir=$(mktemp -d)
trap 'rm -rf -- "$workdir"' EXIT
if [[ ! -f $archive ]]; then
    archive="$workdir/kwin-$pkgver.tar.xz"
    curl --fail --location --silent --show-error "$archive_url" --output "$archive"
fi

actual_archive_sha=$(sha256sum "$archive" | cut -d' ' -f1)
if [[ $actual_archive_sha != "$expected_archive_sha" ]]; then
    printf 'archive hash mismatch: expected %s, got %s\n' "$expected_archive_sha" "$actual_archive_sha" >&2
    exit 1
fi

bsdtar -xf "$archive" -C "$workdir"
clean="$workdir/kwin-$pkgver"

# Count before patching. The series adds files, so counting afterwards would
# report a larger tree than the release actually ships.
pristine_file_count=$(find "$clean" -type f | wc -l)

if (( verify_vendored_tree )); then
    diff -qr "$clean" "$upstream" >/dev/null
fi

for patch_name in "${patches[@]}"; do
    patch -d "$clean" -Np1 --batch --forward --fuzz=0 --no-backup-if-mismatch -i "$project_root/patches/$patch_name" >/dev/null
done

# The overlay holds exactly the files the series touches.
mapfile -t patched_files < <(cd "$project_root/patches" &&
    sed -n 's|^+++ b/||p' "${patches[@]}" | sort -u)
for relative_path in "${patched_files[@]}"; do
    cmp "$clean/$relative_path" "$overlay/$relative_path"
done

mapfile -t actual_overlay_files < <(cd "$overlay" && find . -type f -printf '%P\n' | sort)
mapfile -t expected_overlay_files < <(printf '%s\n' "${patched_files[@]}" | sort)
if [[ ${actual_overlay_files[*]} != "${expected_overlay_files[*]}" ]]; then
    printf 'patched overlay contains an unexpected file set\n' >&2
    printf 'expected:\n%s\n' "${expected_overlay_files[*]}" >&2
    printf 'actual:\n%s\n' "${actual_overlay_files[*]}" >&2
    exit 1
fi

printf 'reference verification passed\n'
printf '  archive: %s\n' "$actual_archive_sha"
if (( verify_vendored_tree )); then
    printf '  pristine files: %s (vendored tree matched)\n' "$pristine_file_count"
else
    printf '  pristine files: %s (from archive; no vendored tree)\n' "$pristine_file_count"
fi
printf '  patched overlay files: %s\n' "${#patched_files[@]}"
