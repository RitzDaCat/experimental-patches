#!/usr/bin/env bash
# alpm hook helper for the kwin latency experiment. Two modes:
#
#   kernel    PostTransaction after a linux* package change. Warns when the
#             module tree for the baked gate kernel is gone, because the next
#             boot then cannot run the release the experiment is gated on and
#             every patch fails closed to stock -- silently, unless this says so.
#
#   replaced  PreTransaction before the kwin package changes. One neutral line:
#             this fires for the repository package replacing the patched build
#             AND for a new experiment build replacing the old one, and the
#             hook cannot tell which, so it only points at status.
#
# Runs as root inside a pacman transaction. It must never fail the transaction,
# so every path exits 0, and missing tools degrade to silence rather than error.

set -u

# Same extraction as kwin-latencyctl status: the baked release is the only
# strings(1) line shaped like x.y.z-N-name in libkwin. Empty means a stock
# library or no strings(1); both mean there is nothing to warn about.
baked_release() {
    local library
    library=$(ls -1 /usr/lib/libkwin.so.[0-9]*.[0-9]*.[0-9]* 2>/dev/null | head -n 1)
    [[ -n $library ]] || return 0
    command -v strings >/dev/null || return 0
    strings -a "$library" 2>/dev/null \
        | grep -m1 -xE '[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?-[0-9]+-[A-Za-z0-9._+-]+' \
        || true
}

case ${1:-} in
    kernel)
        baked=$(baked_release)
        [[ -n $baked ]] || exit 0
        if [[ ! -d /usr/lib/modules/$baked ]]; then
            echo "==> WARNING: kwin latency experiment gate kernel '$baked' has no module tree left."
            echo "    After a reboot the compositor falls back to stock behavior on every patch."
            echo "    Rebuild and reinstall from the repo checkout to re-gate: ./install.sh"
        fi
        ;;
    replaced)
        echo "==> kwin is being replaced. If this is the repository package, the latency"
        echo "    experiment is removed with it. Run kwin-latencyctl status afterwards."
        ;;
esac
exit 0
