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
| 🐧 Kernel | [sched-ext](kernel/sched-ext/cachyos-7.2.10/) | CachyOS 7.2.10-1 (7.2.9 kept) | cheaper, better-informed sched_ext scheduling | default 1–2 + identity 5 · patch 3 opt-in (warning fix not yet booted) · patch 4 boots; `lazy` measured win in KovaaK's |
| 🐧 Kernel | [sched-ext upstream candidates](kernel/sched-ext/upstream/) | CachyOS 7.2.9-1 | the two measured wins (bitops kfuncs, lean idle), each standalone, for review | applies + compiles alone · not for testers: no identity patch |
| 🍰 Scheduler | [scx_cake identity](scheduler/scx-cake/nightly/) | public scx `scx_cake-nightly` `fe076988` | nightly already uses kernel patches 1, 3, 4; falls back on a stock kernel | identity patch only · builds |
| 🪟 Compositor | [kwin](compositor/kwin/) | KWin 6.7.5 | compositor wakes later and more precisely | 21 patches + installer, opt-in, capture and rollback tools · input-to-photon gain not shown |
| 🔊 Audio | [goxlr-utility](audio/goxlr-utility/v1.2.4/) | v1.2.4 | no buffer allocation per sampler read | builds · not live-tested |
| 🛠️ Tools | [mangohud](tools/mangohud/v0.8.4/) | v0.8.4 | control socket fixes | daily use on the author's machine |

**Status words** · **measured** = numbers exist · **shown** = from reading the source · **not shown** = no evidence yet. A patch that builds is not a speedup.

<details>
<summary><b>📁 How each patch set is laid out</b></summary>

```
<area>/<component>/<base version>/
    README.md    one section per patch
    series       default apply order
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
