# Current CachyOS and upstream test targets

Checked 2026-10-22 against public package listings and exact source identities.
Kernel ports are available for CachyOS 7.3 and TJ development. **KWin still
requires a port.** `current` in `index.json` means the newest available collection
series; current distro compatibility is tracked here separately.

| Target ID | Source | Selected series | Result |
| --- | --- | --- | --- |
| `cachyos` | CachyOS `7.3.1-1`, `36ae4c219cfb` | [7.3 `series.all`](../kernel/sched-ext/cachyos-7.3/) | Strict apply; affected objects build |
| `tj-7-4` | TJ `for-7.4`, `1f5dde349ac2` | [for-7.4 `series.all`](../kernel/sched-ext-tj/for-7.4/) | Same checks; affected objects with proxy execution off/on |
| `tj-sched-ext` | TJ `for-next`, `f7008fb94ee0` | [for-next `series.all`](../kernel/sched-ext-tj/for-next/) | Strict apply; affected objects with proxy execution enabled |
| `scx-cake` | Cake `1.2.2` in scx-scheds `1.1.4-1` | [Release identity](../scheduler/scx-cake/v1.2.2/) | Strict apply; Cargo manifest/lockfile identity matches |
| `scx-cake-nightly` | Public nightly `ff4212ae14a3`, Cake `1.3.0` | [Nightly identity](../scheduler/scx-cake/nightly/) | Public pin refreshed; applies and builds |
| `kwin` | `6.8.1-1.1` | KWin 6.7.5 donor | Port required; reduced stack fails at wake instrumentation |
| `goxlr` | Package `1.2.4-2`, source `v1.2.4` | [v1.2.4](../audio/goxlr-utility/v1.2.4/) | Current source; complete series applies |
| `mangohud` | Package `0.8.4-1.1`, source `v0.8.4` | [v0.8.4](../tools/mangohud/v0.8.4/) | Current source; complete series applies |

There is no published CachyOS 7.4 tag in this pass. TJ's `for-7.4` is an explicit
development target whose Makefile still reports `7.3.0-rc1`. See the
[kernel guide](../kernel/) for port changes, build commands and remaining gates.
No refreshed kernel was fully linked, installed, booted, activated or benchmarked.
Earlier measurements apply to their recorded versions only.

Only the experimental nightly contains the kernel feature consumers. New kernel
defaults are identity only; target audits explicitly select `series.all`.

## Repeat the pass

[`targets.json`](targets.json) records exact source identities, public tracking
refs/packages, pristine touched-file hashes, absent files, selected series and
patch hashes. KWin's `patch_set` is explicitly an older donor, not support for 6.8.1.

```bash
# From this collection's root:
python3 scripts/check_compatibility.py --list
python3 scripts/check_compatibility.py --updates \
    --output artifacts/check-compatibility/updates.json
python3 scripts/check_compatibility.py cachyos /path/to/cachyos-7.3.1-1 \
    --output artifacts/check-compatibility/cachyos.json
python3 scripts/check_compatibility.py tj-7-4 /path/to/tj-for-7.4 \
    --output artifacts/check-compatibility/tj-7-4.json
python3 scripts/check_compatibility.py tj-sched-ext /path/to/tj-for-next \
    --output artifacts/check-compatibility/tj-sched-ext.json
```

`--updates` exits 1 when a tracking pin moved, a source could not be checked,
or a target requires a port. It remains nonzero for KWin. Exit 0 means tracking
pins match and every target records application support; it is not a build or
runtime certificate. Multiple package versions on a mirror require review.

Source checks require pristine matching source. They verify its own Git HEAD
when present, every file hash and every expected absent file. Verify release
archive checksums before extraction. Only touched files are copied into
automatically deleted temporary directories; supplied sources are unchanged.

Reports contain `stack` (ordered selected series; failure blocks later entries)
and `isolated_pristine_probes` (every applicable patch attempted on a fresh copy).
Dependent patches can fail isolated probes despite a passing full stack; those
probes are diagnostic. Explicit `upstream`/`superseded` entries retain reasons.
No fuzzy retry or partially applied patch counts as success. Exit codes: 0 =
stack applies; 1 = incompatible; 2 = invalid input/source. Keep reports, logs,
configs and build receipts under gitignored `artifacts/check-compatibility/`.

## Source authority

- Kernel: [CachyOS 7.3.1-1 source](https://github.com/CachyOS/linux/tree/cachyos-7.3.1-1), [release](https://github.com/CachyOS/linux/releases/tag/cachyos-7.3.1-1), [znver4 packages](https://mirror.cachyos.org/repo/x86_64_v4/cachyos-znver4/).
- TJ: [canonical source](https://git.kernel.org/pub/scm/linux/kernel/git/tj/sched_ext.git/) and [kernel.googlesource mirror](https://kernel.googlesource.com/pub/scm/linux/kernel/git/tj/sched_ext/). Branches and commits are explicit; default `master` is not substituted.
- KWin/MangoHud: [optimized packages](https://mirror.cachyos.org/repo/x86_64_v4/cachyos-extra-znver4/), [KWin release](https://download.kde.org/stable/plasma/6.8.1/), [MangoHud v0.8.4](https://github.com/flightlessmango/MangoHud/tree/v0.8.4).
- GoXLR: [CachyOS packages](https://mirror.cachyos.org/repo/x86_64/cachyos/) and [v1.2.4](https://github.com/GoXLR-on-Linux/goxlr-utility/tree/v1.2.4).
- Scheduler: [CachyOS recipe](https://github.com/CachyOS/CachyOS-PKGBUILDS/blob/master/scx/scx-scheds/scx-scheds/PKGBUILD), [scx v1.1.4](https://github.com/sched-ext/scx/tree/v1.1.4), [public nightly](https://github.com/RitzDaCat/scx/tree/RitzDaCat/scx_cake-nightly).

On 2026-11-02 the znver4 mirror ships `linux-cachyos 7.3.1-1`, which matches
the published tag `cachyos-7.3.1-1`, the pinned source. Package releases such
as `7.3.0-4` and `7.3.0-5` had no source tag of their own; a package release
without a tag is checked against the nearest tag before it.

## Remaining KWin port

All 21 entries were accounted for against exact 6.8.1 source. Patches 1/2 are
upstream; 13 is superseded by upstream plane-color pipeline enablement. The
reduced ordered stack fails at 3. Patch 7 applies in isolation; the other 17
applicable isolated probes fail, including dependent patches. The older
[6.8 assessment](../compositor/kwin/v6.7.5/docs/PATCH_REVIEW_6.8_2026-10-07.md)
provides context; current application results use 6.8.1.

Port in dependency order: render-loop telemetry/controllers/opt-in while
preserving `presentNotBefore`; CPU/GPU render-time and VRR plumbing; capture,
scanout and commit correlation; color fixes/caches and explicit compensation
opt-in; then dependencies, package identity, overlays and installer gates.
Compensation needs its own gate now that plane pipelines are enabled upstream.
Do not use the 6.7.5 bundle to replace a Plasma 6.8 compositor.

## Organization

Runnable sets have their own base/version directories, source metadata, hashes
and series. Research stays under `research/`, standalone proposals under
`kernel/sched-ext/upstream/`, and TJ development under its [test section](../kernel/sched-ext-tj/).
For each port, export from matching pristine source, refresh target source/patch
hashes, run the complete selected series, then record `applies`. Build, full
link, boot, stability and performance remain separate gates. Regenerate
`index.json` with `python3 scripts/index.py`.
