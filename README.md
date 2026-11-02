# Experimental patches

Patches for the Linux desktop and gaming stack: kernel scheduler,
compositor, audio and tools. Each patch set is a series of patch files for
an exact public source, with its supporting scheduler changes, install and
rollback tools, evidence, known issues and test history. You still need the
build dependencies and the matching public source.

These patches are experimental and for testing only: the point is to find
out whether they improve game performance and latency on Linux. Do not run
them on a machine you depend on. I use AI tools to help develop them, so
read each set's evidence and known issues before you test it.

The aim is reproducible results from testers on many machines (gains, no
change and regressions alike), which then become evidence for upstream
proposals. Some entries are fixes or upstream backports; most have no
proven game-performance benefit yet. Each patch set states its evidence and
limits.

Current pass, 2026-11-02:

- The CachyOS kernel set covers all of 7.3 and is pinned to 7.3.1-1. It
  applies strictly and the affected objects build; it has not been booted.
- The TJ for-7.4 and for-next tracks are rebased onto their current heads.
- The scx_cake nightly identity patch follows the nightly to Cake 1.3.0.
- KWin 6.8 still needs a port; the included bundle is for KWin 6.7.5.
- There is no published CachyOS 7.4 tag yet.

See the [compatibility matrix](compatibility/) and the
[kernel test tracks](kernel/).

## Risks

| Area | Worst case |
| --- | --- |
| Kernel | scheduler and wake-path changes: no boot, a freeze or a crash; unsaved work is lost |
| Compositor | black screen, no desktop |
| Audio and tools | audio dropouts, a crashing daemon, a broken overlay |
| Whole collection | not reviewed upstream as a whole; tested so far only on a Ryzen 7 9800X3D with an RTX 4090; no warranty: if it breaks, go back to stock |

Before you test, make sure that:

- a stock kernel is in your boot menu, or the stock package is in your
  package cache, and you have tried going back to it ([TESTING.md](TESTING.md));
- your work is saved and backed up;
- this is not a work machine or one you need tomorrow.

## Patch sets

| Area | Patch set | Base | In short | Status |
| --- | --- | --- | --- | --- |
| Kernel | [sched-ext 7.3](kernel/sched-ext/cachyos-7.3/) | CachyOS 7.3.1-1 | bitops, lean idle, direct DSQ index, wake signals | series.all applies and its affected objects build on 7.3.1-1; BPF test object built on 7.3.0-3; not booted or measured |
| Kernel | [TJ development tracks](kernel/sched-ext-tj/) | TJ for-7.4 and for-next | the same four features on upstream development | applies and affected objects build; not booted |
| Kernel | [sched-ext upstream candidates](kernel/sched-ext/upstream/) | CachyOS 7.2.9-1 | the two measured wins (bitops kfuncs, lean idle), each standalone, for review | each applies and compiles alone; not for testers: no identity patch |
| Scheduler | [scx_cake release identity](scheduler/scx-cake/v1.2.2/) | scx-scheds 1.1.4, Cake 1.2.2 | CachyOS release source; identity only | applies; refreshed series not built |
| Scheduler | [scx_cake nightly identity](scheduler/scx-cake/nightly/) | public scx_cake-nightly ff4212ae14a3, Cake 1.3.0 | uses kernel patches 1, 2 and 4; falls back on a stock kernel | applies and builds |
| Compositor | [kwin](compositor/kwin/) | KWin 6.7.5 | the compositor wakes later and more precisely | 21 patches with installer, opt-in, capture and rollback tools; no input-to-photon gain shown |
| Audio | [goxlr-utility](audio/goxlr-utility/v1.2.4/) | v1.2.4 | no buffer allocation per sampler read | builds; not tested live |
| Tools | [mangohud](tools/mangohud/v0.8.4/) | v0.8.4 | control socket fixes | in daily use on the author's machine |

Status words: measured means numbers exist; shown means shown by reading
the source; not shown means there is no evidence yet. A patch that builds
is not a speedup.

## Layout

Each patch set has its own directory:

```
<area>/<component>/<base version or branch>/
    README.md    one section per patch
    series       default apply order (series.<name>: opt-in variants)
    base.json    exact public source identity
    base.sha256  pristine hashes of the touched files
    0001-*.patch
    NNNN-identify-experimental-build.patch
```

Every series ends with an identity patch, so a patched build says what it
is: uname -r, --version or the overlay ends in -exp. KWin marks its package
description and experiment revision instead. See
[Know what you are running](TESTING.md#know-what-you-are-running).

Each patch description says what it changes, why, the expected result and
how to test it; kernel sets add compatibility and known issues. Each README
has a test history: version, machine, and how far it got (applies,
compiles, boots, daily use, measured).

The kernel patches are developed as commits on the exp/* branches of
[RitzDaCat/linux-exp](https://github.com/RitzDaCat/linux-exp), a fork of
CachyOS/linux, and exported here with scripts/export_series.py.

Distributions and scripts should read [index.json](index.json), not folder
names. Each entry gives component, version, path, current (the newest set
of that component), base (repository and commit or tag, or archive and
SHA-256) and series (patch lists in apply order). kernel/sched-ext/upstream/
and research/ are not patch sets and are not listed. Whether a set still
fits the current distribution or development source is recorded in
[compatibility/targets.json](compatibility/targets.json).

```bash
jq -r '.sets[] | select(.component == "kernel/sched-ext" and .current) | .path' index.json
```

## Start testing

1. Pick a patch set and read its known issues.
2. Read [TESTING.md](TESTING.md) and try your rollback first.
3. Get the exact public source the set names as its base.
4. Check, apply and build, then verify the -exp identity and that the
   feature is active.
5. File a Test result or a Bug / regression issue.

For the kernel, scheduler, audio and MangoHud sets, from the root of this
collection:

```bash
scripts/apply.sh <patch-set-directory> <source-directory> --check
scripts/apply.sh <patch-set-directory> <source-directory>
```

apply.sh needs Bash, Git, GNU patch and coreutils. It checks the touched
files against base.sha256 and test-applies the whole series first, with no
fuzzy matching. Its temporary copies hold only the touched files and are
removed on exit. Use a source tree you can throw away: a write failure
during the final apply can leave partial changes.

New kernel ports apply the identity patch only by default while boot tests
are pending. Pass --series series.all for every feature.

For KWin, follow its [bundled guide](compositor/kwin/v6.7.5/TESTING.md) and
use its installer, which keeps the install and recovery checks.

## Rules for this repo

- Everything these experiments need lives here; tester steps never depend
  on a private repo.
- One directory per area, component and base version; a new base gets a
  new directory.
- Only current candidates are kept; older versions live in git history.
- Patches are exported with git format-patch or git diff --binary, with the
  base and source identity recorded. Context is regenerated from matching
  source; patch bodies are never edited by hand.
- Each project's installer, verification and rollback tools are included.
- Upstream licenses and attribution are kept ([LICENSING.md](LICENSING.md)).

[CONTRIBUTING.md](CONTRIBUTING.md) covers refreshing patches, validation and
upstream evidence. Report results and bugs as described in
[TESTING.md](TESTING.md#reporting).
