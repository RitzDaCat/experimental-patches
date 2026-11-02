# Kernel test tracks

| Track | Exact base | Series | Last validation |
| --- | --- | --- | --- |
| [CachyOS 7.3](sched-ext/cachyos-7.3/) | `cachyos-7.3.1-1`, `36ae4c219cfb` | `series.all` | 2026-11-02: strict apply; 12 affected kernel objects compile. 2026-10-22 on 7.3.0-3: also the scalar-bitops BPF object and skeleton |
| [TJ for 7.4](sched-ext-tj/for-7.4/) | `for-7.4`, `1f5dde349ac2` | `series.all` | 2026-10-22: same checks as CachyOS 7.3.0-3; kernel objects checked with proxy execution off and on |
| [TJ integration](sched-ext-tj/for-next/) | `for-next`, `f7008fb94ee0` | `series.all` | 2026-11-02: strict apply and affected-object build; proxy execution enabled |

There is no published CachyOS 7.4 tag in this pass. The 7.4 track uses TJ's
explicit `for-7.4` development branch. Its source Makefile still says
`7.3.0-rc1`; this is not a released Linux or CachyOS 7.4 kernel.

All tracks contain the same four experiments, rebased separately onto their
exact source. The CachyOS 7.2 sets are in git history; their evidence is in
the 7.3 set's test history.
The standalone [upstream proposals](sched-ext/upstream/) remain separate.

## Features and series

| Patch | Feature | Consumer or comparison |
| --- | --- | --- |
| 1 | Native CTZ, POPCNT, CLZ and MULHI kfuncs, x86 JIT paths and return bounds | Experimental Cake nightly detects native CTZ/POPCNT; `--portable-bitops` compares the portable path |
| 2 | Single-word lean idle claims, paired idle/SMT masks, lazy SMT clearing and test-before-write transitions | Opt-in flags; Cake `--lean-idle off`, `on`, `lazy` |
| 3 | Direct index for DSQ IDs below 2048, with hash fallback | Kernel-side; `sched_ext.dsq_direct=0` selects hash-only lookup |
| 4 | Input/fence wake tokens and cumulative IRQ-time kfunc | Root scheduler opt-in; Cake `--kernel-signals observe` or `on` |
| 5 | Experimental kernel identity | `make kernelrelease`, then verify the `-exp` identity after a future boot |

New, unbooted ports keep feature changes outside the default apply path:

| Series | Contents |
| --- | --- |
| `series` | Identity only; no feature patches |
| `series.all` | All four features plus identity; use this for the requested complete-stack tests |
| `series.proven` | Bitops, lean idle and identity; the name refers to features measured on 7.2, not evidence for these new ports |

The [compatibility checker](../compatibility/) records `series.all` for these
targets. It does not mistake an identity-only application for a complete-stack pass.

From the collection's root, with matching pristine source:

```bash
scripts/apply.sh kernel/sched-ext/cachyos-7.3 /path/to/cachyos-7.3.1-1 --series series.all --check
scripts/apply.sh kernel/sched-ext/cachyos-7.3 /path/to/cachyos-7.3.1-1 --series series.all

scripts/apply.sh kernel/sched-ext-tj/for-7.4 /path/to/tj-for-7.4 --series series.all --check
scripts/apply.sh kernel/sched-ext-tj/for-7.4 /path/to/tj-for-7.4 --series series.all
```

Use the public [Cake nightly](../scheduler/scx-cake/nightly/) for feature tests.
It resolves flag values from the running BTF by name. The separate
[distro-release identity series](../scheduler/scx-cake/v1.2.2/) does not contain
these consumers. Their successful activation on the new kernels remains untested.

## Port-specific changes

The bitops port uses `bpf_call_arg_meta` and the current kfunc ID list, and
preserves the newer x86 arena-argument call setup. The lean-idle port retains
the implicit caller lookup and CPU-membership validation before making a claim;
it does not copy the older kfunc's early bypass across the sub-scheduler contract.
Lean tracking still requires global masks and at most 64 CPUs.

The direct DSQ index follows current scheduler allocation, DSQ removal and
deferred freeing. TJ already has the upstream typed hash comparison, so its
patch adds only the direct index and lifecycle changes, without duplicating
that upstream backport.

| Flag | CachyOS 7.3 bit | TJ development bit |
| --- | --- | --- |
| `SCX_OPS_LEAN_IDLE` | 9 | 11 |
| `SCX_OPS_LEAN_IDLE_LAZY_SMT` | 10 | 12 |
| `SCX_OPS_WAKE_SIGNAL` | 11 | 13 |

TJ uses bits 9 and 10 for upstream lazy rescheduling and blocked-donor enqueue.
The port preserves both. It clears a wake token after the actual
`scx_start_task_running()` callback, including deferred proxy-donor starts,
rather than clearing it on a provisional pick. Wake-signal sub-schedulers
require root opt-in through the current ancestor contract. The historical
`default_wake_function()` warning fix is retained.

Internal wake tags use `0x200` and `0x400`, shifted by 9 when packed into the
token. This preserves token cause bits 0/1 and leaves TJ's upstream
`WF_TTWU_RQ=0x100` intact. Compile-time assertions reject overlap with known
upstream wake flags.

## Build and remaining gates

Object checks used Clang 23.1.3, x86-64, sched_ext, sub-schedulers, group
scheduling, BPF/JIT, IRQ accounting, off-stack cpumasks and `NR_CPUS=8192`.
The BPF selftest objects compile with `-Wall -Werror`, and bpftool generates
their skeletons. These are compile checks; the verifier tests were not executed.

After applying the selected series, configure an out-of-tree build with the
required options and run these affected-object targets:

```bash
make LLVM=1 O=/path/to/build -j8 \
    arch/x86/net/bpf_jit_comp.o kernel/bpf/helpers.o kernel/bpf/verifier.o \
    kernel/sched/core.o kernel/sched/build_policy.o kernel/sched/wait.o \
    drivers/dma-buf/dma-fence.o drivers/dma-buf/sync_file.o \
    drivers/gpu/drm/drm_syncobj.o drivers/input/evdev.o fs/eventfd.o fs/eventpoll.o
```

`kernel/sched/build_policy.o` includes both sched_ext core and idle tracking.
Always run `make LLVM=1 O=/path/to/build olddefconfig` after config changes,
and verify that the requested options survived dependency resolution.
For TJ proxy coverage, enable `EXPERT` and `SCHED_PROXY_EXEC`, with `PREEMPT_RT`
disabled; an enabled request alone is not proof that Kconfig accepted it.

Remaining gates: full kernel link and BTF-ID resolution; VM boot; execution
of `test_progs -t scalar_bitops` on that patched kernel; scheduler attach/detach,
idle/DSQ lifecycle and wake-path tests; hardware boot and stability; then paired
performance measurements. No install or boot was performed in this pass.
Keep a stock recovery kernel and follow [TESTING.md](../TESTING.md).
