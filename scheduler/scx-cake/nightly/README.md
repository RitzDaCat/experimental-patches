# scx_cake — experimental build identity

The public `scx_cake-nightly` branch already contains every consumer for the kernel patches.
This folder only adds the identity patch, so a build names itself experimental.

**Base:** public [RitzDaCat/scx](https://github.com/RitzDaCat/scx) branch `RitzDaCat/scx_cake-nightly`,
pinned commit `fe076988f7fc1fdc0f42ea1278f89bed62b64a01` (`base.json`). The patch only touches the version line, so it
applies to later nightly commits too; the pin moves when the version changes. **License:** GPL-2.0-only, matching scx_cake.

## One build, any kernel

scx_cake checks each kernel feature by name once at start and falls back when it is missing. The
answer is a read-only constant, so the BPF verifier drops the unused path: no runtime check, no
cost on a stock kernel.

| Kernel patch | Cake detects | Without it |
|---|---|---|
| 1 native bitops | `bpf_ctz64` / `bpf_popcnt64` kfuncs + CPU BMI1 / POPCNT | portable builtins |
| 2 DSQ direct index | nothing to detect (kernel-side) | hash lookup |
| 3 wake signals | `SCX_OPS_WAKE_SIGNAL` in BTF + `scx_bpf_task_wake_signal_v1` | `--kernel-signals` unavailable |
| 4 lean idle | `SCX_OPS_LEAN_IDLE`, `_LAZY_SMT` in BTF (by name, not bit number) | regular idle claim |

Kernel patches are per CachyOS version (`kernel/sched-ext/cachyos-<ver>/`); this scheduler patch
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
| 2026-10-13 | Apply, build | Applies to `fe076988f`; `cargo build --locked --release` builds, `--version` prints `scx_cake 1.2.1-exp` · not loaded during preparation |
