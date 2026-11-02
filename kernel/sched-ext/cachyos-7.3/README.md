# sched_ext kernel patches for CachyOS 7.3

Four kernel changes that make sched_ext schedulers cheaper to run or better
informed, plus an identity patch that tags the build -exp. They were written
for scx_cake, but nothing in them is specific to it: any sched_ext scheduler
can use the new kfuncs and flags.

The set covers every CachyOS 7.3 release. base.json pins the newest one that
was checked; the table below lists every release the series was verified on.
The patches are exported from branch exp/7.3 of the kernel fork
[RitzDaCat/linux-exp](https://github.com/RitzDaCat/linux-exp) with
scripts/export_series.py, so do not edit them here by hand.

| CachyOS tag | Base commit | Result |
| --- | --- | --- |
| cachyos-7.3.1-1 | 36ae4c219cfb | touched files unchanged from 7.3.0-3; rebased with no changes |
| cachyos-7.3.0-3 | eb735bde0575 | full port from 7.2.10 |

## Patches

| # | Patch | What it does | Evidence |
| --- | --- | --- | --- |
| 1 | [bpf: add native scalar bitops](0001-bpf-add-native-scalar-bitops.patch) | bit counts as one CPU instruction | measured on 7.2: ops.running -2.31 ns, select_cpu -0.2 to -4.11 ns; no frame change in games |
| 2 | [sched_ext: add lean idle claim](0002-sched_ext-add-lean-idle-claim.patch) | cheaper idle-CPU claim, more cache-warm wakes | measured on 7.2: KovaaK's lazy vs off, 1% low +7.5%, p99 -5.1%, avg FPS +1.4% |
| 3 | [sched_ext: add direct DSQ index](0003-sched_ext-add-direct-DSQ-index.patch) | dispatch queue found by array index, not hash | runs daily on 7.2; no speedup shown |
| 4 | [sched: add wake signals](0004-sched-add-wake-signals.patch) | tells the scheduler a wake came from input or a GPU fence | runs daily on 7.2; 0 wakes tagged on KWin + NVIDIA |
| 5 | [localversion: identify experimental build](0005-localversion-identify-experimental-build.patch) | uname -r ends in -exp | in every series |

No 7.3 kernel with these patches has been booted or measured yet. The
measurements above are from 7.2 and do not carry over by themselves.

The patches stack in order: each assumes the ones before it.

| Series | Patches | For |
| --- | --- | --- |
| series (default) | 5 | identity only, a stock kernel that says it was built here |
| series.proven | 1, 2, 5 | the two measured wins |
| series.all | 1-5 | every feature; what the maintainer runs |

scx_cake uses patches 1, 2 and 4 from the public
[nightly with the identity patch](../../../scheduler/scx-cake/nightly/). It
detects each one at start and falls back to stock behaviour when one is
missing. Patch 3 needs no scheduler support.

## Apply

Use a clean checkout of the matching tag from
[CachyOS/linux](https://github.com/CachyOS/linux) and your distribution's
config and packaging. From this collection's root:

```bash
scripts/apply.sh kernel/sched-ext/cachyos-7.3 /path/to/cachyos-7.3.1-1 --series series.all --check
scripts/apply.sh kernel/sched-ext/cachyos-7.3 /path/to/cachyos-7.3.1-1 --series series.all
```

Leave out --series for identity only, or pass series.proven for the measured
wins. The helper checks the pinned hashes and test-applies copies of the
touched files in /tmp; it does not build or install a kernel.

The CachyOS Kernel Manager takes one patch file. Join a series into one:

```bash
cd kernel/sched-ext/cachyos-7.3
grep -v '^#' series.all | xargs cat > /tmp/sched-ext-cachyos-7.3.patch
```

After boot, uname -r ends in -exp. Keep a stock kernel in the boot menu and
see [TESTING.md](../../../TESTING.md).

## Requirements

Any x86-64 CPU. Patch 1 emits TZCNT, POPCNT and LZCNT inline when the CPU has
them (Haswell, Piledriver and later) and makes ordinary calls otherwise.
Patch 2 needs the global idle mask and at most 64 CPUs; otherwise its flags
are ignored.

The config needs BPF, BPF_SYSCALL, BPF_JIT, DEBUG_INFO_BTF and
SCHED_CLASS_EXT. Patch 4's IRQ time also needs IRQ_TIME_ACCOUNTING. The
CachyOS default config has all of them.

Patch 2 adds the experimental SCX_OPS bits 9 and 10, and patch 4 adds bit 11.
They may collide with future upstream flags, so a scheduler must resolve them
by name from the running kernel's BTF and never hard-code the numbers.

## Known issues

On 7.2.9, patch 4 logged one kernel warning per boot:

```
WARNING: kernel/sched/core.c:7620 at default_wake_function+0x1a/0x30
 pollwake <- __wake_up_locked_key_flags <- eventfd_signal_mask_flags
 <- syncobj_eventfd_entry_fence_func <- dma_fence_signal
```

The wake-cause bits ride the normal wake flags, and the stock
default_wake_function() warns on anything except WF_SYNC and WF_CURRENT_CPU.
The first poll() waiter on a GPU fence trips it, even with no scheduler
opted in. Wakeups still work, but the kernel is tainted W, and with
panic_on_warn=1 it panics at boot. Patch 4 now lets
default_wake_function() accept WF_SCX_SIGNAL_MASK. The fix is in this series
but has not been booted yet, so do not use panic_on_warn=1 with patch 4.

## 1. Native scalar bitops

Adds the kfuncs bpf_ctz64, bpf_popcnt64, bpf_clz64 and bpf_mulhi64. The
x86-64 JIT emits the counts as one TZCNT, POPCNT or LZCNT when the CPU has
them, and mulhi as MUL plus two moves. The verifier learns the results are
0 to 64, and the one-argument calls are marked fastcall. A BPF selftest is
included.

Schedulers scan bitmasks of idle CPUs and queues. BPF has no bit-count
instruction, so the compiler emits a dozen or more instructions instead, and
scx_cake does this on every wakeup and every task start.

scx_cake uses the native path automatically. --portable-bitops forces the
old path on the same boot for a comparison.

## 2. Lean idle claim

| Part | Change |
| --- | --- |
| K1 | claim an idle CPU with one atomic op on one word |
| K2 | idle and SMT masks in one 128-byte block (they sat 32 cache lines apart) |
| K3 | with SCX_OPS_LEAN_IDLE_LAZY_SMT, skip the SMT-mask write on a successful claim; the claimed CPU clears it when it goes busy |
| K4 | read before every write, so correct bits are not rewritten |

The scheduler opts in with SCX_OPS_LEAN_IDLE. Claiming an idle CPU is about
60% of scx_cake's select_cpu, and two far-apart masks dirty two shared cache
lines per claim. K1 and K2 cut select_cpu from 82 to 68 ns. K3 keeps a
just-claimed core "whole idle" until it runs, so about 6 points more wakes
return to their cache-warm CPU. Both halves are needed for the gain.

On 7.3 the claim sits inside scx_idle_test_and_clear_cpu(), after the
kfunc's caller lookup and CPU-membership checks. The 7.2 early bypass was not
carried over, because 7.3 changed the sub-scheduler contract.

Compare with the scx_cake nightly: --lean-idle off, on or lazy on one boot.
lazy is its default.

## 3. Direct DSQ index

Adds a 2048-entry array per scheduler (16 KiB), so a DSQ ID below 2048 is
found by one indexed read. Larger IDs keep the hash, with a cheaper typed
compare adapted from
[Usama Arif's patch](https://lore.kernel.org/all/20260921171928.1639407-1-usama.arif@linux.dev/),
which is upstream from 7.4. The direct index and its lifecycle are the local
experiment.

Every queue operation hashes and compares a usually small ID, and all of
scx_cake's IDs are below 2048. The expected gain is a few ns per queue
operation, but it has not been shown: the VM test passed, the timing was
inconclusive, and there is no hardware comparison yet.

To compare, boot once with sched_ext.dsq_direct=0. While a scheduler runs,
/sys/kernel/sched_ext/root/dsq_direct_entries reads 2048 when the index is on
and 0 when it is off.

## 4. Wake signals

Records whether a wake came from evdev input or a GPU fence (dma-fence,
sync_file, syncobj), and carries the cause through epoll, eventfd and wait
queues. Two kfuncs read the cause and each CPU's recent IRQ time. Causes are
recorded only for a scheduler that opts in with SCX_OPS_WAKE_SIGNAL, but the
bits travel the wake paths on every boot.

A wake from a mouse move or a finished frame is urgent, and a timer wake
usually is not. The idea is to send urgent wakes straight to a free CPU and
avoid IRQ-busy CPUs.

On KWin with NVIDIA, 0 of 8.4M wakes were tagged in 90 s: input arrives over
KWin's Wayland socket, and NVIDIA uses its own waits. So there is no benefit
there. AMD and Intel on Mesa are still an open question.

Run scx_cake --kernel-signals observe --signal-report report.csv to count
tagged wakes without changing placement. A report with tagged wakes above 0
from an AMD or Intel machine is the most useful result right now.

## 5. Experimental build identity

Adds localversion.30-exp. The PKGBUILD writes localversion.10-pkgrel and
localversion.20-pkgname, so -exp comes last, as in 7.3.1-1-cachyos-exp. The
release string and the /usr/lib/modules directory both end in -exp. There is
no code change. A KWin build from this collection gates on it with
./install.sh --kernel <release>.

## Test history

Newest first. Tester results get a row too. Rows before 7.3 name the patch
set of that time; the code of each feature is the same unless noted.

| Date | Kernel | Patches | How far | Machine | Result |
| --- | --- | --- | --- | --- | --- |
| 2026-11-02 | CachyOS 7.3.1-1 source | 1-5 | compiles | - | touched files identical to 7.3.0-3; series, series.proven and series.all apply; the 12 touched objects compile with the 7.3.0-5 CachyOS config (clang 23.1.4, LLVM=1, ThinLTO), 0 warnings; not linked or booted |
| 2026-10-22 | CachyOS 7.3.0-3 source | 1-5 | compiles | - | port from 7.2.10; applies with no fuzz; the 12 touched objects compile (clang 23.1.3); scalar_bitops BPF object and skeleton build; not loaded, linked or booted |
| 2026-10-13 | CachyOS 7.2.10-1 source | 1-5 | compiles | - | reordered proven first; same code, only the SCX_OPS bits move (lean idle 9, 10; wake signals 11); touched objects compile, 0 warnings; not booted |
| 2026-10-13 | CachyOS 7.2.10-1 source | 1-5 | compiles | - | regenerated from 7.2.9 (only bpf_jit_comp.c and ext.c changed upstream); 12 touched objects compile with the 7.2.9 config (clang 23.1.1), 0 warnings; not booted |
| 2026-10-12 | 7.2.9-2-cachyos-custom | bitops, DSQ index, wake signals, lean idle | bitops, game | 9800X3D, RTX 4090, KWin | KovaaK's, native vs --portable-bitops, 6x20 s runs in both orders plus one loaded: no frame difference (round 1 favoured portable's tails; round 2 did not repeat it); callback cost equal within 1-2 ns; JIT inlines |
| 2026-10-12 | 7.2.9-2-cachyos-custom | same | lean idle, loaded | 9800X3D, RTX 4090, KWin | 16 nice-10 hogs (98% busy), lazy vs off: p99.9 -2.4%, 0.1% low +6.6%, worst frame -16%, nothing worse |
| 2026-10-12 | 7.2.9-2-cachyos-custom | same | lean idle | 9800X3D, RTX 4090, KWin | KovaaK's 12x30 s ABBA, lazy vs off: avg FPS +1.4%, p99 -5.1%, 1% low +7.5% (16/16 pairs); on about equal to off; one scene, quiet host |
| 2026-10-12 | CachyOS 7.2.9-1 source | all | applies | - | wake signals with the default_wake_function() fix; applies with no fuzz; fix not compiled or booted |
| 2026-10-11 | 7.2.9-2-cachyos-custom | same, wake-signals fix not included | boots | 9800X3D, RTX 4090 | SCX_OPS_LEAN_IDLE in BTF; wake-signals warning still logged |
| 2026-10-09 | CachyOS 7.2.9-1 source | bitops, DSQ index, wake signals, identity | applies | - | no fuzz; uname -r 7.2.9-1-cachyos-exp |
| 2026-10-07 | CachyOS 7.3-rc6 | 7.2.9 set | applies | - | bitops, DSQ index and wake signals fail; lean idle applies with offsets; port needed |
| 2026-10-07 | CachyOS 7.2.9-2 source | 7.2.9 set | applies | - | no fuzz; touched files identical to 7.2.9-1 |
| 2026-10-07 | mainline 2709dd5ae32f (7.2.0) | 7.2.9 set | applies | - | bitops and wake signals fail; DSQ index and lean idle apply with offsets |
| 2026-10-05 | CachyOS 7.2.9-1 source | bitops, DSQ index, wake signals, lean idle | compiles | - | no fuzz; touched files compile (clang 23.1.1, ThinLTO); not linked or booted |
| 2026-10-04 | 7.2.9-1-cachyos-custom | bitops, DSQ index, wake signals | daily use | 9800X3D, RTX 4090 (NVIDIA 615.71.09) | works with scx_cake; one wake-signals warning per boot |
| 2026-10-02 | CachyOS 7.2.8-1, QEMU | bitops, DSQ index, wake signals | boots (VM) | QEMU, no KVM | scx_cake native and portable; 20,844 bitops checks; 393,216 DSQ create/destroy; 20-case wake-signal contract; 2 debug-kernel failures also happen without the patches |
| 2026-09-30, 10-01 | 7.2.8-1-cachyos-custom | early bitops | boots | 9800X3D | JIT emits TZCNT/POPCNT; scx_cake runs |

The 7.2.9 daily-use kernel was built from the 7.2.8 version of bitops, DSQ
index and wake signals, applied with offsets; the code is the same.

The 7.2 patch sets are in this collection's git history up to commit
be3386f.
