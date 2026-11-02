# scx_cake nightly: experimental build identity

The public scx_cake-nightly branch already has the code that uses every
kernel patch. This folder adds only the identity patch, so a build names
itself experimental.

Base: branch RitzDaCat/scx_cake-nightly of
[RitzDaCat/scx](https://github.com/RitzDaCat/scx), pinned at commit
ff4212ae14a3abb778f561a9ecb093c276ea79e7 in base.json. That was the branch
head on 2026-11-02. The helper checks the pinned Cargo manifest and lockfile
hashes; refresh the pin and the hashes when the branch moves.

License: GPL-2.0-only, the same as scx_cake.

This nightly reports Cake 1.3.0. The CachyOS release source, Cake 1.2.2 in
scx-scheds 1.1.4, has its own [identity series](../v1.2.2/). That release
does not have the nightly's experimental kernel features.

## One build, any kernel

scx_cake looks up each kernel feature by name once at start and falls back
when it is missing. The answer is a read-only constant, so the BPF verifier
drops the unused path: no runtime check and no cost on a stock kernel.

| Kernel patch | Cake detects | Without it |
| --- | --- | --- |
| 1 native bitops | bpf_ctz64 and bpf_popcnt64 kfuncs, CPU BMI1 and POPCNT | portable builtins |
| 2 lean idle | SCX_OPS_LEAN_IDLE and SCX_OPS_LEAN_IDLE_LAZY_SMT in BTF, by name | regular idle claim |
| 3 direct DSQ index | nothing; the change is inside the kernel | hash lookup |
| 4 wake signals | SCX_OPS_WAKE_SIGNAL in BTF and scx_bpf_task_wake_signal_v1 | --kernel-signals unavailable |

The kernel patches are per CachyOS minor release, in
kernel/sched-ext/cachyos-<minor>/. This scheduler patch is the same for all
of them.

## Build and test

From a fresh checkout of the base, at the root of this collection:

```bash
scripts/apply.sh scheduler/scx-cake/nightly /path/to/scx --check
scripts/apply.sh scheduler/scx-cake/nightly /path/to/scx
cd /path/to/scx
cargo build --locked --release -p scx_cake
./target/release/scx_cake --version   # scx_cake 1.3.0-exp ...
```

The startup log names each kernel feature it found. On a patched kernel the
defaults are native bitops and lean idle lazy; --portable-bitops and
--lean-idle off give the comparison arm.

## Test history

| Date | Check | Result |
| --- | --- | --- |
| 2026-11-02 | apply, build | applies with no fuzz to ff4212ae14a3; the locked release build works and --version prints scx_cake 1.3.0-exp; not loaded |
| 2026-10-22 | apply | applies with no fuzz to 4b6d2c4240a5; pristine hashes unchanged; not rebuilt or loaded |
| 2026-10-13 | apply, build | applies to fe076988f; the locked release build works and --version prints scx_cake 1.2.1-exp; not loaded |
