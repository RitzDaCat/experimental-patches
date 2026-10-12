# sched_ext kernel patches — CachyOS 7.2.9-1

Four kernel changes that make sched_ext schedulers cheaper to run or better
informed, plus an identity patch that tags the build `-exp`. They were written for
[scx_cake](https://github.com/sched-ext/scx/tree/main/scheds/rust/scx_cake),
but nothing in them is specific to it: any sched_ext scheduler can use the new
kfuncs and flags.

**Source:** the complete kernel patches are included here, split by feature.
The [scheduler companion](../../../scheduler/scx-cake/8fc5ec9/) supplies the
consumer for patches 1 and 3 from a pinned public scx base. Private development
repositories are not needed.

The default `series` contains **1–2** and the identity patch **5**. Patch 3 requires explicit selection
until its warning fix has booted. Patch 4 is available for source review and
expert development; it boots, but is unmeasured and its scheduler consumer is not bundled.

| # | Patch | In short | Status |
| --- | --- | --- | --- |
| 1 | [bpf-native-scalar-bitops](0001-bpf-native-scalar-bitops.patch) | Bit-counting as one CPU instruction instead of a software routine | **Measured** in microbenchmarks; in daily use on the author's machine |
| 2 | [sched-ext-dsq-direct-index](0002-sched-ext-dsq-direct-index.patch) | Find a dispatch queue by array index instead of a hash lookup | In daily use on the author's machine; speedup **not shown** |
| 3 | [sched-wake-signals](0003-sched-wake-signals.patch) | Tell the scheduler a task woke because of input or a finished GPU job | Excluded from default `series`: boot-warning fix not yet booted ([known issue](#known-issues)); no effect observed on KWin + NVIDIA |
| 4 | [sched-ext-lean-idle-claim](0004-sched-ext-lean-idle-claim.patch) | Cheaper way to claim an idle CPU | Boots; lazy mode gained in one game scene. Not in `series` |
| 5 | [identify-experimental-build](0005-identify-experimental-build.patch) | Kernel release ends in `-exp`, e.g. `7.2.9-1-cachyos-exp` | In both series; applies |

## Compatibility

| | Works with | Notes |
| --- | --- | --- |
| Kernel | CachyOS source tags `cachyos-7.2.9-1` and `cachyos-7.2.9-2` in [CachyOS/linux](https://github.com/CachyOS/linux) | `base.json` pins the `-1` commit; all touched pristine files also match `-2`. The helper checks those hashes and forbids fuzzy matching. Plain kernel.org 7.2.9 is untested. CachyOS 7.3 needs a port |
| CPU | Any x86-64; other architectures untested | Patch 1's single-instruction path needs TZCNT, POPCNT and LZCNT (Intel Haswell, AMD Piledriver or newer); otherwise the kfuncs are ordinary calls. Patch 4 only works with 64 CPUs or fewer and the global idle mask; otherwise its flags are ignored |
| Kernel config | `BPF`, `BPF_SYSCALL`, `BPF_JIT`, `DEBUG_INFO_BTF`, `SCHED_CLASS_EXT` | Patch 3's IRQ time also needs `IRQ_TIME_ACCOUNTING`. CachyOS's default config has all of these |
| Scheduler | Patch 2: any sched_ext scheduler; patches 1 and 3: [bundled scx_cake companion](../../../scheduler/scx-cake/8fc5ec9/) | An ordinary public scx_cake build without the companion does not consume 1 or 3. Patch 4's consumer is not included |
| Flag bits | Patches 3 and 4 add experimental `SCX_OPS` bits 9, 10 and 11 | These values may conflict with future upstream flags. Resolve their names through the exact running kernel's BTF, as the companion does; never hard-code the values |

## Tested on

Newest first. "How far" is the furthest step reached: applies, compiles,
boots, daily use, measured. Tester results get a row here too.

| Date | Kernel | Patches | How far | Machine | Result |
| --- | --- | --- | --- | --- | --- |
| 2026-10-12 | `7.2.9-2-cachyos-custom` | 1–4 | Measured (patch 1, game) | Ryzen 7 9800X3D, RTX 4090, KWin | KovaaK's menu, scx_cake native vs `--portable-bitops`, 6×20 s runs in both slot orders plus one loaded: native is **not** better in frames; portable showed better tails (1 % low +4.4 %, stddev −21 % pooled), unexplained since callback cost is equal (±1–2 ns) and the JIT does inline. Treat patch 1's game benefit as unproven |
| 2026-10-12 | `7.2.9-2-cachyos-custom` | 1–4 | Measured (patch 4, loaded) | Ryzen 7 9800X3D, RTX 4090, KWin | Same scene under 16 nice-10 CPU hogs (98 % busy), `lazy` vs `off`: p99.9 −2.4 %, 0.1 % low +6.6 %, worst frame −16 %; no metric worse. scx_cake now defaults to `lazy` |
| 2026-10-12 | `7.2.9-2-cachyos-custom` | 1–4 | Measured (patch 4) | Ryzen 7 9800X3D, RTX 4090, KWin | KovaaK's menu, 12×30 s ABBA, scx_cake `--lean-idle`: `lazy` vs `off` avg FPS +1.4 %, p99 frame time −5.1 %, 1 % low +7.5 %, all 16/16 pairs; `on` ≈ `off`. One scene, quiet host |
| 2026-10-12 | CachyOS 7.2.9-1 source (touched files) | 1–4, 5 | Applies | — | Patch 3 now includes the `default_wake_function()` warning fix; `series.wake-signals` and 1–4 stacked apply with no fuzz. Fix not compiled or booted yet |
| 2026-10-11 → now | `7.2.9-2-cachyos-custom` | 1–4 (patch 3 without the fix) | Boots | Ryzen 7 9800X3D, RTX 4090 | Boots with `SCX_OPS_LEAN_IDLE` in BTF; patch 3 warning still logged. `--lean-idle` A/B not run |
| 2026-10-09 | CachyOS 7.2.9-1 source (touched files) | 1–3, 5 | Applies | — | Both series apply with no fuzz. CachyOS's `setlocalversion` with the PKGBUILD's localversion files gives `7.2.9-1-cachyos-exp` |
| 2026-10-07 | CachyOS 7.3-rc6 source (`cachyos-7.3-rc6-1`) | 1–4 | Applies | — | 1, 2 and 3 fail; 4 applies with offsets. Needs a port before 7.3 |
| 2026-10-07 | CachyOS 7.2.9-2 source | 1–4 | Applies | — | Applies with no fuzz. Every file the patches touch is identical to 7.2.9-1 |
| 2026-10-07 | Mainline reference `2709dd5ae32f` (Makefile 7.2.0) | 1–4 | Applies | — | 1 and 3 fail; 2 and 4 apply with offsets |
| 2026-10-05 | CachyOS 7.2.9-1 source | 1–4 | Compiles | — | Applies with no fuzz; every touched file compiles (clang 23.1.1, `LLVM=1`, ThinLTO). Not linked or booted |
| 2026-10-04 → now | `7.2.9-1-cachyos-custom` | 1–3 | Daily use | Ryzen 7 9800X3D, RTX 4090 (NVIDIA 615.71.09) | Works, with scx_cake running. One kernel warning per boot from patch 3 ([known issue](#known-issues)) |
| 2026-10-02 | CachyOS 7.2.8-1, QEMU VMs | 1–3 | Boots (VM) | QEMU, no KVM | Passed: scx_cake loads in native and portable mode; 20,844 bitops checks; 393,216 DSQ create/destroy iterations; 20-case wake-signal contract. Debug kernels show two failures that also happen without the patches |
| 2026-09-30, 10-01 | `7.2.8-1-cachyos-custom` | Early version of 1 | Boots | Ryzen 7 9800X3D | JIT emits TZCNT/POPCNT; scx_cake loads and runs |

The 7.2.9 kernel in daily use was built from the 7.2.8 version of patches 1–3
(it applied with offsets). The code is the same as patches 1–3 here.

## Known issues

**Patch 3 logged a kernel warning once per boot (fixed, fix not yet booted).** It appears early in boot,
even with no scheduler opted in:

```
WARNING: kernel/sched/core.c:7620 at default_wake_function+0x1a/0x30
 pollwake <- __wake_up_locked_key_flags <- eventfd_signal_mask_flags
 <- syncobj_eventfd_entry_fence_func <- dma_fence_signal
```

- **Cause:** patch 3 passes its wake-cause bits (`WF_SCX_INPUT` 0x100,
  `WF_SCX_FENCE` 0x200) through the normal wake flags. Stock
  `default_wake_function()` warns on any flag other than `WF_SYNC` and
  `WF_CURRENT_CPU`, and patch 3 did not add its bits to that check. The first
  `poll()` waiter on a GPU fence trips it.
- **Effect:** one warning in `dmesg` per boot, and the kernel is marked
  tainted (`W`). Wakeups still work. With `panic_on_warn=1` the machine would
  panic at boot, so do not test patch 3 with that setting.
- **Fix (in patch 3 since 2026-10-12):** `default_wake_function()`'s check
  now allows `WF_SCX_SIGNAL_MASK`. Builds from an older patch 3 still warn.
  Keep avoiding `panic_on_warn=1` until a fixed build has booted.

**Patch 4 boots but is unmeasured.** See its section below.

## Apply

The patches stack: each assumes the ones before it. Obtain clean public source
from [CachyOS/linux](https://github.com/CachyOS/linux), at tag
`cachyos-7.2.9-1` (commit `65a94cb5c1587a19242fe5a219f03343671f372e`)
or `cachyos-7.2.9-2` (commit `09bc889a111715e4509b3819b628c9b9d9d09a0b`).
Use your distribution's matching configuration and kernel packaging workflow.
From this collection's root, apply the default patches 1–2 and 5:

```bash
scripts/apply.sh kernel/sched-ext/cachyos-7.2.9 /path/to/linux-7.2.9 --check
scripts/apply.sh kernel/sched-ext/cachyos-7.2.9 /path/to/linux-7.2.9
```

The helper checks the pinned pristine hashes and preflights only copies of
touched files in `/tmp`, removed on exit. It does not build or install a kernel.

For an explicit wake-signal research build, start from fresh source again and
read [Known issues](#known-issues) first. Do not use `panic_on_warn=1`:

```bash
scripts/apply.sh kernel/sched-ext/cachyos-7.2.9 /path/to/linux-7.2.9 --series series.wake-signals --check
scripts/apply.sh kernel/sched-ext/cachyos-7.2.9 /path/to/linux-7.2.9 --series series.wake-signals
```

CachyOS Kernel Manager takes one patch file. Combine the series into one:

```bash
cd kernel/sched-ext/cachyos-7.2.9
while IFS= read -r p; do
    case "$p" in ''|\#*) continue ;; esac
    cat -- "$p"
done < series > /tmp/sched-ext-cachyos-7.2.9.patch
```

Patch 5 makes `uname -r` end in `-exp`; check it after booting. Give the
kernel its own package name and keep your stock kernel in the boot menu. Remove the temporary combined patch after importing it. Build the
[scheduler companion](../../../scheduler/scx-cake/8fc5ec9/) if testing native
bitops or wake signals. See [TESTING.md](../../../TESTING.md).

---

## 1. Native scalar bit operations

**What it changes.** Adds four kfuncs that BPF programs can call: `bpf_ctz64`
(count trailing zeros), `bpf_popcnt64` (count set bits), `bpf_clz64` (count
leading zeros) and `bpf_mulhi64` (high half of a 64-bit multiply). On x86-64
the BPF JIT inlines the count calls as one instruction (`TZCNT`, `POPCNT`,
`LZCNT`) when supported; high-half multiplication uses `MUL` plus two register
moves. The verifier also learns that the count
results are 0–64, and the one-argument calls are marked fastcall so fewer
registers are saved around them. A BPF selftest is included.

**Why.** Schedulers find idle CPUs and pick from queues by scanning bitmasks,
which means counting bits. BPF has no instruction for that, so the compiler
falls back to a routine of a dozen or more instructions. scx_cake does this on
every wakeup and every time a task starts running. The CPU can do it in one.

**Expected result.** Slightly cheaper scheduling decisions: a few nanoseconds
per callback. Whether that translates into game FPS needs a separate comparison.
Measured in
scx_cake microbenchmarks: `ops.running` 2.31 ns faster per call, `select_cpu`
4.11 ns faster on one screen and 0.2 ns on another. The fastcall marking and
the 0–64 bounds showed **no effect**. CLZ and MULHI are included but scx_cake
no longer uses them (its division-free maths was slower overall and was
removed).

**How to test.** scx_cake picks the native operations on its own when the
kernel has them. `--portable-bitops` forces the old path on the same kernel, so
the two can be compared on one boot.

## 2. Direct DSQ index

**What it changes.** sched_ext keeps a scheduler's dispatch queues (DSQs) in a
hash table, looked up by ID every time a task is queued to or taken from one.
This patch adds a 2048-entry array per scheduler (16 KiB) so IDs below 2048
are found with one indexed read. Larger IDs still use the hash table, which
also gets a cheaper typed comparison (backported; upstream from 7.4).

The typed comparison is adapted from
[Usama Arif's upstream patch](https://lore.kernel.org/all/20260921171928.1639407-1-usama.arif@linux.dev/).
The direct index and its lifecycle handling are the local experiment.

**Why.** Every queue operation pays for hashing and comparing an ID that is
usually a small number. All of scx_cake's queue IDs are below 2048.

**Expected result.** Less work on every queue and dispatch operation, likely a
few nanoseconds. **Not shown:** a VM simulation passed but its timing was
inconclusive, and no hardware comparison has been run yet.

**How to test.** Same kernel, two boots: once as is, once with
`sched_ext.dsq_direct=0` on the kernel command line. Check which mode is
active with `cat /sys/kernel/sched_ext/root/dsq_direct_entries` while a
scheduler runs: 2048 means on, 0 means off.

## 3. Wake signals

**What it changes.** When a task wakes up, the kernel records whether the
cause was input (an evdev event) or a GPU fence completing (dma-fence,
sync_file, DRM syncobj). The cause is carried through epoll, eventfd and wait
queues, so a program waiting on those still gets it. Two new kfuncs let a
scheduler read the cause and each CPU's recent interrupt time. Causes are only
recorded for a scheduler that opts in (`SCX_OPS_WAKE_SIGNAL`), but the cause
bits travel through the wake paths on every boot, opted in or not.

**Why.** A scheduler sees a task wake but not why. A game thread woken by a
mouse movement or a finished frame is urgent; one woken by a timer usually is
not. With the cause, the scheduler can send urgent wakes straight to a free
CPU, and steer away from CPUs busy with interrupts.

**Expected result.** With `--kernel-signals on`, scx_cake places input- and
GPU-woken tasks without its usual co-location step, and avoids CPUs under
heavy interrupt load. In practice, on the author's KWin + NVIDIA desktop, **no
wakes were tagged** (0 of 8.4 million in a 90-second game run). Input reaches
the game through KWin's Wayland socket, not evdev, and NVIDIA's driver uses its
own waits instead of the generic fence paths. So no benefit is expected there.
Other setups (AMD or Intel GPUs on Mesa) may differ, and that is the open
question.

**How to test.** Run scx_cake with `--kernel-signals observe --signal-report
report.csv`. It counts tagged wakes without changing placement. A report from
an AMD or Intel system with tagged wakes above zero is the most useful result
this patch can get right now.

## 4. Lean idle claim (boots, not measured)

**What it changes.** Claiming an idle CPU means clearing its bit in the idle
mask, plus a bit in the whole-core (SMT) mask if both siblings were idle. This
patch, active only for schedulers that opt in (`SCX_OPS_LEAN_IDLE`) on systems
with at most 64 CPUs:

- **K1:** claims a CPU with one atomic operation on one word, before the
  scheduler lookup and CPU checks the stock path does first.
- **K2:** puts both masks together in one 128-byte block of their own. On the
  test machine they sat 32 cache lines apart.
- **K3** (`SCX_OPS_LEAN_IDLE_LAZY_SMT`): skips the SMT-mask write on a
  successful claim and leaves it to the claimed CPU when it goes busy.
- **K4:** reads before every write, so bits that are already right are not
  written again.

**Why.** In scx_cake, claiming an idle CPU is about 60 % of the cost of
choosing a CPU for a waking task. With the two masks far apart, one claim can
dirty two cache lines that every other CPU then has to fetch again.

**Expected result.** A cheaper `select_cpu`, with fewer cache-line transfers
between cores under load. **Not shown:** the patch boots on the author's
machine, but no comparison has been run.

**How to test.** Only if you are ready to fall back to your stock kernel:
apply it by hand after the other three in a disposable research tree. The
author's intended comparison is scx_cake `--lean-idle off`, `on` and `lazy`
on one boot, but that uncommitted consumer is **not included here**. The bundled
companion cannot perform this comparison. Treat patch 4 as source review and
build research, rather than a ready game-testing path.

## 5. Experimental build identity

**What it changes.** Adds a `localversion.30-exp` file containing `-exp`. The
kernel build appends `localversion*` files in name order, after the
`localversion.10-pkgrel` and `localversion.20-pkgname` files that the Arch and
CachyOS PKGBUILDs write. A build from this collection reports
`7.2.9-1-cachyos-exp` instead of `7.2.9-1-cachyos`.

**Why.** A tester must be able to tell the patched kernel from the stock one at
a glance, in `uname -r`, the boot menu's module tree and every bug report.

**Expected result.** No code change. The release string and the
`/usr/lib/modules` directory name end in `-exp`. A KWin build from this
collection must be gated on that name: `./install.sh --kernel <release>`.

**How to test.** `uname -r` after booting the patched kernel.
