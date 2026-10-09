# Experimental patches

> [!WARNING]
> **AI-assisted.** I use AI tools to help develop these patches. Read each
> patch set's evidence and known issues before you test it.

> [!CAUTION]
> **Experimental. Use at your own risk.** These patches are for testing only:
> to find out whether they improve game performance and latency on Linux. Do
> not run them on a machine you depend on.

Patches for the Linux desktop and gaming stack: the kernel, compositor, audio
and tools. This is a standalone testing collection: patch files, supporting
scheduler changes, KWin lifecycle tools and tester guides are included here.
Build dependencies and the matching public upstream sources are still needed.

The purpose is to collect reproducible improvements, unchanged results and
regressions across machines, then use that evidence to propose changes upstream.
Some entries are fixes or upstream backports; most experiments have no proven
game-performance benefit yet. Each patch set states its evidence and limitations.

## Risks

- **Kernel patches** change the scheduler and core wake-up paths. A bad one
  can stop the machine from booting, freeze it or crash it. Anything unsaved
  is lost when that happens.
- **Compositor patches** can leave you at a black screen with no desktop.
- **Audio and tool patches** can cause audio dropouts, a crashing daemon or a
  broken overlay.
- This collection has not been reviewed as a whole by the upstream projects.
  Hardware experience so far comes from the author's Ryzen 7 9800X3D and
  RTX 4090. Other hardware needs independent reports.
- There is no warranty. If something breaks, you fix it by going back to
  stock.

Before you test:

- Keep a way back that you have tried: a stock kernel in your boot menu, or
  the stock package in your package cache. See [TESTING.md](TESTING.md).
- Save your work and back up anything you care about.
- Do not test on a work machine or one you need the next day.

## Patch sets

| Area | Patch set | Base | In short | Status |
| --- | --- | --- | --- | --- |
| Kernel | [sched-ext](kernel/sched-ext/cachyos-7.2.9/) | CachyOS 7.2.9-1 / -2 | Cheaper, better-informed sched_ext scheduling | Default: 1–2. Patch 3 has a known boot warning and requires explicit selection; 4 never booted |
| Scheduler | [scx_cake companion](scheduler/scx-cake/8fc5ec9/) | Public scx commit `8fc5ec9b` | Consumer and comparison flags for kernel patches 1 and 3 | Source snapshot included; patch 4's consumer is not included |
| Compositor | [kwin](compositor/kwin/) | KWin 6.7.5 | Compositor wakes later and more precisely | 21 patches, installer, opt-in, capture and rollback tools included; input-to-photon gain not shown |
| Audio | [goxlr-utility](audio/goxlr-utility/v1.2.4/) | v1.2.4 | No buffer allocation per sampler read | Builds; not live-tested |
| Tools | [mangohud](tools/mangohud/v0.8.4/) | v0.8.4 | Control socket fixes | In daily use on the author's machine |

## How each patch set is laid out

```
<area>/<component>/<base version>/
    README.md    one section per patch
    series       default apply order
    base.json    exact public source identity
    base.sha256  pristine hashes of touched files
    0001-*.patch
```

Patch descriptions cover four questions:

- **What it changes:** the code change, in plain words.
- **Why:** the problem it addresses.
- **Expected result:** what should improve, and what has been shown so far.
- **How to test:** a concrete way to compare with and without it.

Each README also has a **Tested on** table: which version was tested, on what
machine, and how far it got (applies, compiles, boots, daily use, measured).
Kernel patch sets add **Compatibility** and **Known issues**.

Status uses one vocabulary: **measured** (numbers exist), **shown** (from
reading the source) or **not shown** (no evidence yet). A patch that builds is
not a speedup.

## Start testing

1. Choose one patch set and read its compatibility and known issues.
2. Follow [TESTING.md](TESTING.md), including a tested rollback path.
3. Get the exact public source base listed in that patch set's guide.
4. Check, apply and build; then verify which build and feature are actually active.
5. Submit a **Test result** or **Bug / regression** issue using the included forms.

For kernel, scheduler, audio and MangoHud sources, run from this repo's root:

```bash
scripts/apply.sh <patch-set-directory> <source-directory> --check
scripts/apply.sh <patch-set-directory> <source-directory>
```

The helper needs Bash, Git, GNU patch and coreutils. It verifies the touched
source files against `base.sha256` and preflights the whole selected series
without fuzzy matching before editing your tree. Its temporary copies contain
only touched files and are removed on exit. Use a disposable source tree: an
unexpected write failure during the final apply can still leave partial changes.

For **KWin**, follow the [bundled guide](compositor/kwin/v6.7.5/TESTING.md)
and installer. It preserves the compositor's install and recovery checks.

## Rules for this repo

- All files needed specifically for these experiments belong here. Tester
  instructions must not depend on access to a private development repository.
- One folder per area, component and base version. A new base gets a new folder.
- Only current candidates are kept. Older versions live in git history.
- Export source changes with `git format-patch` or `git diff --binary`; record
  the base and source identity. Regenerate context from matching source instead
  of editing patch bodies by hand.
- Include a project's needed installer, verification and rollback tooling.
- Keep upstream licenses and attribution; see [LICENSING.md](LICENSING.md).

See [CONTRIBUTING.md](CONTRIBUTING.md) for refreshing patches, validating this
collection and preparing evidence for upstream review.

Results and bugs: see [TESTING.md](TESTING.md#reporting) for what to include.
