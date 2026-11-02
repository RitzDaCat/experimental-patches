# scx_cake — experimental build identity

The public `scx_cake-nightly` branch already contains every consumer for the kernel patches.
This folder only adds the identity patch, so a build names itself experimental.

**Base:** public [RitzDaCat/scx](https://github.com/RitzDaCat/scx) branch `RitzDaCat/scx_cake-nightly`,
pinned commit `4b6d2c4240a558624ddd705eec8627f54a0ce240` (`base.json`), the latest public
branch head checked on 2026-10-22. The helper checks the pinned Cargo manifest and lockfile
hashes. Refresh the pin and verify those hashes when the branch advances.
**License:** GPL-2.0-only, matching scx_cake.

This nightly reports Cake 1.2.1. The current CachyOS release source, Cake 1.2.2 in
scx-scheds 1.1.4, has a separate [identity series](../v1.2.2/). That release does not
contain this nightly's experimental kernel consumers.

## One build, any kernel

scx_cake checks each kernel feature by name once at start and falls back when it is missing. The
answer is a read-only constant, so the BPF verifier drops the unused path: no runtime check, no
cost on a stock kernel.

| Kernel patch | Cake detects | Without it |
|---|---|---|
| 1 native bitops | `bpf_ctz64` / `bpf_popcnt64` kfuncs + CPU BMI1 / POPCNT | portable builtins |
| 2 lean idle | `SCX_OPS_LEAN_IDLE`, `_LAZY_SMT` in BTF (by name, not bit number) | regular idle claim |
| 3 DSQ direct index | nothing to detect (kernel-side) | hash lookup |
| 4 wake signals | `SCX_OPS_WAKE_SIGNAL` in BTF + `scx_bpf_task_wake_signal_v1` | `--kernel-signals` unavailable |

Kernel patches are per CachyOS minor release (`kernel/sched-ext/cachyos-<minor>/`); this scheduler patch
is the same for all of them.

## Build and test

From a fresh checkout of the base, at this collection's root:

```bash
scripts/apply.sh scheduler/scx-cake/nightly /path/to/scx --check
scripts/apply.sh scheduler/scx-cake/nightly /path/to/scx
cd /path/to/scx
cargo build --locked --release -p scx_cake
./target/release/scx_cake --version   # scx_cake 1.2.1-exp…
```

The startup log names each kernel feature it found. On a patched kernel the defaults are native
bitops and lean idle `lazy`; `--portable-bitops` and `--lean-idle off` give the comparison arm.

## Tested on

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-22 | Apply | Identity series applies with zero fuzz to public head `4b6d2c424`; pristine hashes unchanged. Refreshed pin not rebuilt or loaded |
| 2026-10-13 | Apply, build | Applies to `fe076988f`; `cargo build --locked --release` builds, `--version` prints `scx_cake 1.2.1-exp` · not loaded during preparation |
