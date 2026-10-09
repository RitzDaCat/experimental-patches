#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Preflight the complete series on a temporary copy of only its touched files.
set -euo pipefail

usage() {
    echo "usage: $0 <patch-set-dir> <source-dir> [--check] [--series series.NAME]" >&2
    exit 2
}
die() { echo "error: $*" >&2; exit 1; }
[[ $# -ge 2 ]] || usage
set_dir=$(realpath -- "$1")
src=$(realpath -- "$2")
shift 2
check=0
series=series
while (( $# )); do
    case $1 in
        --check) (( check == 0 )) || usage; check=1; shift ;;
        --series) [[ $# -ge 2 ]] || usage; series=$2; shift 2 ;;
        *) usage ;;
    esac
done
[[ $series == series || $series =~ ^series\.[a-z-]+$ ]] || usage
[[ -d $src && $src != / ]] || die "expected a source directory"
[[ -f $set_dir/$series ]] || die "no $series file in $set_dir"
[[ -f $set_dir/base.sha256 ]] || die "no base.sha256 in $set_dir"
for tool in git patch sha256sum; do
    command -v "$tool" >/dev/null || die "$tool is required"
done

safe_path() {
    [[ -n $1 && $1 != /* && $1 != -* && $1 != *[[:space:]]* &&
       /$1/ != *'/../'* && /$1/ != *'/./'* && /$1/ != *'/.git/'* ]]
}

declare -A base_paths=() touched=()
while IFS= read -r line || [[ -n $line ]]; do
    [[ -z $line || $line == \#* ]] && continue
    [[ $line =~ ^[0-9a-f]{64}\ \ (.+)$ ]] || die "invalid base.sha256 entry"
    relative=${BASH_REMATCH[1]}
    safe_path "$relative" || die "invalid source path: $relative"
    [[ ! ${base_paths[$relative]+present} ]] || die "duplicate base path: $relative"
    base_paths[$relative]=1
done < "$set_dir/base.sha256"
(( ${#base_paths[@]} )) || die "empty base.sha256"

patches=()
while IFS= read -r p || [[ -n $p ]]; do
    [[ -z $p || $p == \#* ]] && continue
    [[ $p != */* && $p == *.patch && -f $set_dir/$p && ! -L $set_dir/$p ]] \
        || die "invalid or missing patch: $p"
    patches+=("$p")
    stats=$(git apply --numstat -- "$set_dir/$p") || die "invalid patch: $p"
    [[ -n $stats ]] || die "empty patch: $p"
    while IFS=$'\t' read -r added removed relative; do
        safe_path "$relative" || die "unsupported patch path: $relative"
        touched[$relative]=1
    done <<< "$stats"
done < "$set_dir/$series"
(( ${#patches[@]} )) || die "empty $series"

# Reject symlinks and out-of-tree paths before reading or modifying source.
for relative in "${!base_paths[@]}" "${!touched[@]}"; do
    resolved=$(realpath -m -- "$src/$relative")
    [[ $resolved == "$src/"* && ! -L $src/$relative ]] \
        || die "source path is a symlink or escapes the tree: $relative"
    if [[ ${base_paths[$relative]+present} ]]; then
        [[ -f $src/$relative ]] || die "missing base file: $relative"
    else
        [[ ! -e $src/$relative ]] || die "expected new file to be absent: $relative"
    fi
done
verify_base() {
    (cd -- "$src" && sha256sum --check --quiet "$set_dir/base.sha256") \
        || die "source files differ from the documented base; use fresh matching sources"
}
verify_base

tmp=$(mktemp -d /tmp/experimental-patches.XXXXXX)
trap 'rm -rf -- "$tmp"' EXIT
for relative in "${!touched[@]}"; do
    mkdir -p -- "$tmp/$(dirname -- "$relative")"
    if [[ ${base_paths[$relative]+present} ]]; then
        cp --preserve=mode,timestamps -- "$src/$relative" "$tmp/$relative"
    fi
done
apply_one() {
    patch -d "$1" -Np1 --batch --forward --fuzz=0 --no-backup-if-mismatch \
        --reject-file=- -s < "$set_dir/$2"
}
for p in "${patches[@]}"; do
    echo "checking $p"
    apply_one "$tmp" "$p" || die "series failed preflight; source tree was not changed"
done
if (( check )); then
    echo "all patches apply (check only; source tree unchanged)"
    exit 0
fi
verify_base
for p in "${patches[@]}"; do
    echo "applying $p"
    apply_one "$src" "$p" || die "unexpected apply failure; discard this disposable tree and start fresh"
done
echo "all patches applied"
