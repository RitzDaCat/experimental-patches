# TJ sched_ext — complete-series testing

Requested source: [TJ sched_ext](https://git.kernel.org/pub/scm/linux/kernel/git/tj/sched_ext.git/).
All four kernel experiments are ported to two independently pinned development
bases. KWin, audio and MangoHud are userspace patches and do not apply here.

| Track | Commit | Result |
| --- | --- | --- |
| [for-7.4](for-7.4/) | `1f5dde349ac2fca1f119ae8de3f0d2f1c2a8d338` | Complete series applies; affected objects compile with proxy execution off/on; scalar-bitops BPF object/skeleton builds |
| [for-next](for-next/) | `f7008fb94ee033c8de9f42ae2bf2911db73c17f9` | Complete series applies; affected objects compile with proxy execution enabled |

The `for-7.4` Makefile reports `7.3.0-rc1` and `for-next` reports `7.3.0`. `for-7.4` names the development branch, not
a final release. No CachyOS 7.4 tag is published in this pass. Default `master`
is not silently substituted for either target.

## Get and check source

From the collection's root, with a disposable checkout:

```bash
git clone --depth 1 --single-branch --branch for-7.4 \
    https://git.kernel.org/pub/scm/linux/kernel/git/tj/sched_ext.git/ \
    /path/to/tj-for-7.4
target_commit=$(jq -r '.targets[] | select(.id == "tj-7-4") | .base.commit' \
    compatibility/targets.json)
git -C /path/to/tj-for-7.4 fetch --depth 1 origin "$target_commit"
git -C /path/to/tj-for-7.4 checkout --detach "$target_commit"
python3 scripts/check_compatibility.py tj-7-4 /path/to/tj-for-7.4 \
    --output artifacts/check-compatibility/tj-7-4.json
scripts/apply.sh kernel/sched-ext-tj/for-7.4 /path/to/tj-for-7.4 --series series.all
```

The [kernel.googlesource mirror](https://kernel.googlesource.com/pub/scm/linux/kernel/git/tj/sched_ext/)
provides the same pinned refs if the canonical Git transport is unavailable.
Verify the exact commit with either transport.

For `for-next`, use target ID `tj-sched-ext` and directory
`kernel/sched-ext-tj/for-next/` with its separate pinned pristine checkout.
The checker selects `series.all`, checks the complete ordered stack, and also
probes each patch in isolation. It leaves supplied sources unchanged. Expected
full-stack exit code is 0; isolated dependent failures are diagnostic.

## Select features

`series.all` is bitops → lean idle → DSQ index → wake signals → identity.
Default `series` is identity only until boot validation. `series.proven` is the
bitops/idle subset whose measurements come from older CachyOS builds, not these ports.

The [kernel guide](../README.md) documents port changes and build commands.
Upstream ops bits 9/10 are preserved; experimental flags use 11/12/13 and are
resolved through BTF by name. Internal wake tags preserve `WF_TTWU_RQ`, with
compile-time overlap checks. Lean claims retain caller/CPU validation, and
wake tokens clear after actual proxy-donor running callbacks.

## Remaining runtime gates

1. Fully link the kernel and resolve BTF IDs with a recorded config/toolchain.
2. Boot a disposable VM. Execute `test_progs -t scalar_bitops`, scheduler
   attach/detach, idle claims, DSQ create/destroy and input/fence wake tests.
   Check warnings and verify native scheduling restoration.
3. Boot hardware with a stock recovery kernel retained. Verify kernel/BTF and
   active features. Use the [experimental nightly](../../scheduler/scx-cake/nightly/);
   the distro-release identity series lacks the consumers.
4. Compare stock and patched builds of the same exact TJ commit, with identical
   config, compiler, scheduler binary and workloads; then isolate features.
   Follow [TESTING.md](../../TESTING.md), retaining null results, regressions,
   raw logs and rollback evidence.

No full link, VM/hardware boot, install, activation or performance measurement
was performed. Keep local per-target source/build receipts under gitignored
`artifacts/check-compatibility/`.
