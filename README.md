# Experimental patches

> [!WARNING]
> **AI-assisted.** I use AI tools to help develop these patches. Read each
> patch set's evidence and known issues before you test it.

> [!CAUTION]
> **Experimental. Use at your own risk.** For testing only: to find out whether these
> improve game performance and latency on Linux. Do not run them on a machine you depend on.

Patches for the Linux desktop and gaming stack — kernel, compositor, audio and tools — as a
standalone testing collection: patch files, supporting scheduler changes, KWin lifecycle
tools and tester guides. Build dependencies and matching public upstream sources are still
needed.

```mermaid
flowchart LR
    T[testers on many machines] --> E[reproducible results:<br/>wins · no change · regressions]
    E --> U[evidence for upstream proposals]
```

Some entries are fixes or upstream backports; most have **no proven game-performance benefit
yet**. Each patch set states its evidence and limitations.

**Current pass (2026-10-22):** full kernel ports are available for CachyOS
`7.3.0-3` and TJ's `for-7.4` / `for-next` development branches. They pass strict
application and affected-object build checks; boot/runtime tests remain open.
KWin `6.8.1-1.1` still needs a port. GoXLR and MangoHud match current package
sources. See the [compatibility matrix](compatibility/) and
[kernel test tracks](kernel/). There is no published CachyOS 7.4 tag yet.
The final mirror check advertised package `7.3.0-4` without a corresponding
published source identity; the tested 7.3 source pin remains `7.3.0-3`.

---

## ⚠️ Risks

| Area | Worst case |
|---|---|
| 🐧 Kernel | scheduler and wake-path changes: no boot, freeze or crash · unsaved work is lost |
| 🪟 Compositor | black screen, no desktop |
| 🔊 Audio / 🛠️ tools | audio dropouts, a crashing daemon, a broken overlay |
| 🌐 Whole collection | not reviewed by upstream as a whole · hardware so far: Ryzen 7 9800X3D + RTX 4090 · **no warranty**: if it breaks, go back to stock |

**Before you test** ✅ a stock kernel in your boot menu or stock package in your cache, tried
([TESTING.md](TESTING.md)) · ✅ work saved and backed up · ✅ not a work machine or one you need tomorrow.

---

## 📦 Patch sets

| Area | Patch set | Base | In short | Status |
| --- | --- | --- | --- | --- |
| Kernel | [sched-ext 7.3](kernel/sched-ext/cachyos-7.3.0/) | CachyOS 7.3.0-3 | bitops, lean idle, DSQ indexing, wake signals | `series.all` = all features; strict apply + affected objects + BPF test object build; unbooted, unmeasured |
| Kernel | [TJ development tracks](kernel/sched-ext-tj/) | pinned `for-7.4` and `for-next` | all four features rebased onto upstream development | strict apply + affected-object builds; separate source pins; unbooted |
| 🐧 Kernel | [sched-ext upstream candidates](kernel/sched-ext/upstream/) | CachyOS 7.2.9-1 | the two measured wins (bitops kfuncs, lean idle), each standalone, for review | applies + compiles alone · not for testers: no identity patch |
| Scheduler | [scx_cake release identity](scheduler/scx-cake/v1.2.2/) | scx-scheds 1.1.4 / Cake 1.2.2 | current CachyOS release source; identity only | strict application passes; refreshed series not built |
| Scheduler | [scx_cake nightly identity](scheduler/scx-cake/nightly/) | public scx `scx_cake-nightly` `4b6d2c424` / Cake 1.2.1 | experimental consumer for kernel patches 1, 2, 4; falls back on a stock kernel | refreshed pin applies; earlier pin built |
| 🪟 Compositor | [kwin](compositor/kwin/) | KWin 6.7.5 | compositor wakes later and more precisely | 21 patches + installer, opt-in, capture and rollback tools · input-to-photon gain not shown |
| 🔊 Audio | [goxlr-utility](audio/goxlr-utility/v1.2.4/) | v1.2.4 | no buffer allocation per sampler read | builds · not live-tested |
| 🛠️ Tools | [mangohud](tools/mangohud/v0.8.4/) | v0.8.4 | control socket fixes | daily use on the author's machine |

**Status words** · **measured** = numbers exist · **shown** = from reading the source · **not shown** = no evidence yet. A patch that builds is not a speedup.

<details>
<summary><b>📁 How each patch set is laid out</b></summary>

```
<area>/<component>/<base version or branch>/
    README.md    one section per patch
    series       default apply order (series.<name>: opt-in variants)
    base.json    exact public source identity
    base.sha256  pristine hashes of touched files
    0001-*.patch
    NNNN-identify-experimental-build.patch
```

Every series ends with an **identity patch**, so a patched build says so: `uname -r`,
`--version` or the overlay ends in `-exp` (KWin marks its package description and experiment
revision instead) — see [Know what you are running](TESTING.md#know-what-you-are-running).

| Each patch description answers | Kernel sets add |
|---|---|
| **What it changes** · **Why** · **Expected result** · **How to test** | **Compatibility** · **Known issues** |

Each README also has a **Tested on** table: version, machine, how far (applies → compiles → boots → daily use → measured).

**For distributions and scripts** · read [`index.json`](index.json), not folder names. Each entry
gives `component`, `version`, `path`, `current` (newest set of that component), `base` (repository
+ commit/tag, or archive + SHA-256) and `series` (patch lists in apply order). Apply with
`scripts/apply.sh <path> <source> [--series series.<name>]`, which checks the pinned hashes first.
`kernel/sched-ext/upstream/` and `research/` are not patch sets and are not listed.
`current` selects the newest available collection series. Consult
[`compatibility/targets.json`](compatibility/targets.json) for distro/development target
versions and whether they still need a port.

```bash
jq -r '.sets[] | select(.component == "kernel/sched-ext" and .current) | .path' index.json
```
</details>

---

## 🧪 Start testing

```mermaid
flowchart LR
    A[1 · pick a set,<br/>read known issues] --> B[2 · TESTING.md,<br/>tested rollback] --> C[3 · exact public<br/>source base] --> D[4 · check · apply · build ·<br/>verify -exp + feature] --> E[5 · file a Test result or<br/>Bug / regression issue]
```

Kernel, scheduler, audio and MangoHud — from this repo's root:

```bash
scripts/apply.sh <patch-set-directory> <source-directory> --check
scripts/apply.sh <patch-set-directory> <source-directory>
```

| `apply.sh` | |
|---|---|
| Needs | Bash, Git, GNU patch, coreutils |
| Checks | touched files against `base.sha256`; preflights the whole series, no fuzzy matching |
| Temp files | touched files only, removed on exit |
| ⚠️ | use a disposable source tree: a write failure during the final apply can leave partial changes |

🪟 **KWin:** follow its [bundled guide](compositor/kwin/v6.7.5/TESTING.md) and installer (keeps the install and recovery checks).

**New kernel ports:** explicitly add `--series series.all` for the complete
feature stack. Their default `series` applies identity only while boot testing
is pending. The compatibility checker records the full-series selection.

---

## 📜 Rules for this repo

| Rule |
|---|
| Everything these experiments need lives here — tester steps never depend on a private repo |
| One folder per area, component and base version; a new base gets a new folder |
| Only current candidates are kept; older versions live in git history |
| Export with `git format-patch` or `git diff --binary`; record base and source identity; regenerate context from matching source, never hand-edit patch bodies |
| Include each project's installer, verification and rollback tooling |
| Keep upstream licenses and attribution ([LICENSING.md](LICENSING.md)) |

[CONTRIBUTING.md](CONTRIBUTING.md): refreshing patches, validating, preparing upstream evidence
· results and bugs: [TESTING.md](TESTING.md#reporting).
