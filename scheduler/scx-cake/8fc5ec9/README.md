# scx_cake kernel experiment companion

This source snapshot supplies scx_cake's consumer and comparison flags for
kernel patches 1 and 3. It is included so testers do not need unpublished code.

**Base:** public [RitzDaCat/scx](https://github.com/RitzDaCat/scx) commit
`8fc5ec9b105198286f7c9f7c53e2bf40308c3a4a`.
**Source snapshot:** committed revision
`6dce0901f151beb6a4d8875b5cf0af3cd9dd5643`, restricted to
`scheds/rust/scx_cake/src/`. No uncommitted source is included.
**License:** GPL-2.0-only, matching scx_cake.

## What it changes

Adds automatic kernel CTZ/POPCNT use with portable fallback, the
`--portable-bitops` comparison switch, and opt-in input/fence wake-signal and
IRQ-time support (`--kernel-signals off|observe|on`, `--signal-report`).
The snapshot also contains the intervening committed scheduler changes; it is
not a minimal patch isolating one performance mechanism.

## Why and expected result

The kernel cannot improve scheduling through these kfuncs unless a consumer
actually calls them. This companion makes that consumer reproducible. Existing
kernel microbenchmarks do not prove a game gain from this full snapshot.
Keep this **same scheduler build** in both arms when comparing kernel features.

## Build and test

From a fresh public source checkout at the exact base, run from the collection's
root:

```bash
scripts/apply.sh scheduler/scx-cake/8fc5ec9 /path/to/scx --check
scripts/apply.sh scheduler/scx-cake/8fc5ec9 /path/to/scx
cd /path/to/scx
cargo build --locked --release -p scx_cake
cargo test --locked -p scx_cake
sha256sum target/release/scx_cake
```

Install the build prerequisites and initialize submodules according to that
public scx checkout's README. A release build does not grant BPF privileges or
prove verifier acceptance. Follow your distribution's scheduler-management
workflow; keep its prior configuration and a way back to native scheduling.
Record startup capability messages and the scheduler's active state.

For bitops, compare automatic selection against `--portable-bitops` on the
matching patched kernel. For wake signals, read the kernel's known boot warning
first, then start with `--kernel-signals observe --signal-report NEW.csv`.
Observe mode counts signals without enabling the new placement policy. Do not
interpret zero tagged wakes or unavailable capability as a successful test of
the placement mechanism.

The `--lean-idle` consumer for kernel patch 4 is uncommitted and excluded.

## Tested on

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-08 | Apply and source identity | Patch applies to the pinned public base; all five resulting files exactly reproduce the committed snapshot |

This exported companion has not been rebuilt, verifier-loaded, activated or
game-benchmarked during repository preparation. Earlier kernel evidence is
documented in the [kernel guide](../../../kernel/sched-ext/cachyos-7.2.9/).
