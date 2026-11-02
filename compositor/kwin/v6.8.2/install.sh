#!/usr/bin/env bash
# Build and install the latest patched KWin.
#
# Usage: ./install.sh [--yes] [--kernel REL]
#
# Installs the build dependencies kwin-latencyctl preflights, builds the
# package, verifies the lock screen was compiled in, then installs it.
# Reboot afterwards -- a Wayland compositor cannot be replaced in place.
#
# --kernel REL bakes that release in as the experiment gate instead of the
# running kernel, for when the next boot is a different installed kernel.

set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

CTL=./bin/kwin-latencyctl
PROFILE="${XDG_CONFIG_HOME:-$HOME/.config}/environment.d/90-kwin-latency.conf"
GLOBAL=()
target=$(uname -r)
while (( $# )); do
    case $1 in
        --yes) GLOBAL=(--yes); shift ;;
        --kernel) [[ $# -ge 2 ]] || { echo "--kernel needs a release" >&2; exit 1; }; target=$2; shift 2 ;;
        *) echo "unknown option: $1 (usage: ./install.sh [--yes] [--kernel REL])" >&2; exit 1 ;;
    esac
done

# The package is an Arch PKGBUILD and every lifecycle path -- build, install,
# and above all rollback -- goes through pacman. Without it the first failure is
# "pacman: command not found" from a dependency probe, which reads like a broken
# script rather than an unsupported platform. Say so before touching anything.
if ! command -v pacman >/dev/null; then
    echo "ERROR: pacman not found; this package targets Arch-based systems only" >&2
    echo "       see 'Supported scope' in README.md before porting the patches" >&2
    exit 1
fi

# kwin-latencyctl checks these three up front and refuses to build without
# them. makepkg --syncdeps pulls in the rest of depends/makedepends itself.
readarray -t missing < <(pacman -T extra-cmake-modules plasma-wayland-protocols wayland-protocols || true)
if (( ${#missing[@]} )); then
    echo "==> Installing build dependencies: ${missing[*]}"
    sudo pacman -S --needed "${missing[@]}"
fi

# --- Preflight -------------------------------------------------------------
# Three cheap checks. Each one covers a failure that has already cost a session:
# no way back, a gate pointing at the wrong kernel, and a reboot that silently
# moves the kernel out from under the gate.
echo "==> Preflight"

# 1. A way back. Replacing the compositor with no stock package in the pacman
# cache leaves no offline rollback if the new one fails to start -- and a
# compositor that will not start is exactly when you cannot download one.
# Require a digit after "kwin-" so this matches kwin-6.7.4-... and not a
# different package that merely starts with the same prefix, such as kwin-x11.
rollback=$(ls -t /var/cache/pacman/pkg/kwin-[0-9]*.pkg.tar.zst 2>/dev/null | head -n 1 || true)
if [[ -z $rollback ]]; then
    echo "ERROR: no kwin package in /var/cache/pacman/pkg -- no offline rollback" >&2
    echo "       run: sudo pacman -Sw kwin" >&2
    exit 1
fi
echo "    rollback available: $(basename "$rollback")"
# The cache copy can vanish later -- paccache -r keeps three versions and a
# manual cache clean keeps none. Stash a copy the recovery instructions can
# name, so "the cache is empty" never strands a broken desktop. cp -n exits
# nonzero on newer coreutils when the file exists, so test instead.
mkdir -p artifacts/rollback
if [[ ! -e artifacts/rollback/$(basename "$rollback") ]]; then
    cp "$rollback" artifacts/rollback/
fi
echo "    rollback stashed: artifacts/rollback/$(basename "$rollback")"

# 2. A pending kernel update changes uname -r at the next reboot. Every patch
# is gated on an exact kernel release string, so installing now and rebooting
# into a different kernel disables the whole series -- silently, because the
# gate fails closed to stock behaviour rather than erroring.
# checkupdates must exist. With pacman-contrib absent the pipeline failed, the
# trailing `|| true` swallowed it, and this printed "no pending kernel update" --
# the exact false clearance the check is here to prevent.
command -v checkupdates >/dev/null \
    || { echo "ERROR: checkupdates not found; install pacman-contrib" >&2; exit 1; }
# checkupdates exits 2 when there is nothing to do, so tolerate a non-zero exit
# here but never conflate it with "no kernel update". Match any linux* package:
# a "linux(-cachyos)?" pattern misses linux-cachyos-lts, which this project
# tracks by name in kwin-latencyctl snapshot.
# checkupdates exits 2 for "nothing to do" and 1 for real failures -- notably
# `die 'Cannot fetch updates'` with no network (/usr/bin/checkupdates:151). A
# bare `|| true` collapses those two into each other, so an offline run reports
# "no pending kernel update" while a kernel upgrade is queued. Accept only 0
# and 2; anything else means we could not rule a kernel update out.
rc=0
updates=$(checkupdates) || rc=$?
if (( rc != 0 && rc != 2 )); then
    echo "ERROR: checkupdates failed (exit $rc) -- cannot rule out a kernel update" >&2
    echo "       a wrong-kernel install fails closed to stock and measures nothing." >&2
    exit 1
fi
pending=$(grep -E '^linux[^[:space:]]*[[:space:]]' <<<"$updates" || true)
if [[ -n $pending ]]; then
    echo "ERROR: kernel update pending -- rebooting would change uname -r:" >&2
    sed 's/^/       /' <<<"$pending" >&2
    echo "       apply it and reboot first, then re-run this script." >&2
    exit 1
fi
echo "    no pending kernel update"

# 3. The gate must name the kernel that will boot or nothing takes effect. That
# is the running kernel unless --kernel says otherwise. Delegate the profile fix
# to kwin-latencyctl so its own --yes/--dry-run handling and profile backup
# apply; this script does not edit the profile itself.
[[ -d /usr/lib/modules/$target ]] \
    || { echo "ERROR: no module tree for '$target' in /usr/lib/modules -- that kernel cannot boot" >&2; exit 1; }
gated=$(awk -F= '/^KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=/ { print $2; exit }' \
    "$PROFILE" 2>/dev/null || true)
if [[ ! -f $PROFILE ]]; then
    echo "    no profile installed -- the build bakes '$target' in as the default gate"
elif [[ $gated != "$target" ]]; then
    echo "    kernel gate is '${gated:-unset}', target kernel is '$target' -- re-gating"
    "$CTL" "${GLOBAL[@]}" enable --kernel "$target"
else
    echo "    kernel gate matches target kernel: $target"
fi

echo "==> Building package (kernel gate: $target)"
"$CTL" "${GLOBAL[@]}" build --kernel "$target"

package=$(ls -t artifacts/packages/*.pkg.tar.zst 2>/dev/null | head -n 1)
[[ -n $package ]] || { echo "no package found in artifacts/packages" >&2; exit 1; }

# rev16 shipped with KWIN_BUILD_SCREENLOCKER=OFF, which drops the KScreenLocker
# linkage from libkwin. On Wayland ksmserver defers locking to KWin, so nothing
# then registers org.freedesktop.ScreenSaver and Meta+L silently does nothing.
# The PKGBUILD guards the build tree; this guards the package about to install.
echo "==> Verifying lock screen support in $(basename "$package")"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
bsdtar -xf "$package" -C "$scratch" 'usr/lib/libkwin.so.6.*'
# Read into a variable rather than piping: grep -q exits on first match, which
# SIGPIPEs objdump, and under `set -o pipefail` that fails the whole pipeline.
headers=$(objdump -p "$scratch"/usr/lib/libkwin.so.6.*)
if ! grep -q libKScreenLocker <<<"$headers"; then
    echo "ERROR: $(basename "$package") has no KScreenLocker linkage; refusing to install" >&2
    echo "       the lock screen would be broken again -- check KWIN_BUILD_SCREENLOCKER" >&2
    exit 1
fi

# kwin-latencyctl refuses to install a package whose revision does not match
# artifacts/RELEASE, or whose hash is not pinned in artifacts/SHA256SUMS. Those
# pins are maintained by hand, so promote the package we just built and verified
# to be the validated candidate. This is the manual review gate -- if you would
# rather review before installing, stop using this script and update RELEASE and
# SHA256SUMS yourself, then run: make install
pkginfo=$(bsdtar -xOf "$package" .PKGINFO)
revision=$(awk -F= '/^xdata = kwin-latency-revision=/ { print $NF; exit }' <<<"$pkginfo")
[[ -n $revision ]] || { echo "could not read revision from $(basename "$package")" >&2; exit 1; }

pkgversion=$(awk -F' *= *' '/^pkgver = / { print $2; exit }' <<<"$pkginfo")
[[ -n $pkgversion ]] || { echo "could not read pkgver from $(basename "$package")" >&2; exit 1; }

echo "==> Recording revision $revision, version $pkgversion as the validated candidate"
sed -i "s/^PROJECT_REVISION=.*/PROJECT_REVISION=$revision/" artifacts/RELEASE
# PACMAN_VERSION and CANDIDATE_PACKAGE have to move with the package. Promoting
# only the revision is what broke the 6.7.3 -> 6.7.4 bump: verify_package
# compares the built version against PACMAN_VERSION and rejects the install as
# an "unsafe candidate" while every other step reports success.
sed -i "s/^PACMAN_VERSION=.*/PACMAN_VERSION=$pkgversion/" artifacts/RELEASE
sed -i "s|^CANDIDATE_PACKAGE=.*|CANDIDATE_PACKAGE=$(basename "$package")|" artifacts/RELEASE

checksum=$(sha256sum "$package" | awk '{ print $1 }')
entry="packages/$(basename "$package")"
if grep -q "  ${entry}\$" artifacts/SHA256SUMS; then
    sed -i "s|^[0-9a-f]\{64\}  ${entry}\$|${checksum}  ${entry}|" artifacts/SHA256SUMS
else
    printf '%s  %s\n' "$checksum" "$entry" >> artifacts/SHA256SUMS
fi

echo "==> Installing $(basename "$package")"
"$CTL" "${GLOBAL[@]}" install --package "$package"

cat <<'EOF'

==> Done. Reboot to start the new compositor.

    Installing enabled nothing. Revision 22 and later ship opted out, so the
    compositor you reboot into behaves exactly like stock until you opt in.

    To opt in for the whole session:

        ./bin/kwin-latencyctl enable

    To opt in for one game only, put this in its Steam launch options:

        kwin-latency-game -- %command%

    That sets the policy for the title, restores the previous state when it
    exits -- crash or kill included -- and leaves the rest of the session alone.

    Either way, confirm what is actually live:

        ./bin/kwin-latencyctl status

    Read the "Opt-in (kwinrc)" line, and check the baked gate matches uname -r.
    If the gate does not match, every patch fails closed to stock behaviour and
    any measurement you take is meaningless. Booting a different installed
    kernel than the one you built on? Rebuild with: ./install.sh --kernel REL

    Then confirm the lock screen is back:

        busctl --user list | grep -i screensaver

    That should show org.freedesktop.ScreenSaver owned by kwin_wayland.
    If it does, Meta+L works. To opt back out: ./bin/kwin-latencyctl disable
    To remove the patched compositor entirely: make rollback
EOF
