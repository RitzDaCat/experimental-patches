# sched_ext experiments — CachyOS 7.3

Full four-feature port to public
[CachyOS `cachyos-7.3.0-3`](https://github.com/CachyOS/linux/tree/cachyos-7.3.0-3),
commit `eb735bde05756eed779c2e6f4b893a24a83d78e3`.
`base.json` pins the source; `base.sha256` covers pristine touched files.

The mirror subsequently advertised package `7.3.0-4` without a matching
published source identity in this pass. This series is verified against the
explicit `7.3.0-3` source above; see the [currentness report](../../../compatibility/).

| Series | Patches |
| --- | --- |
| `series` | 5, identity only |
| `series.all` | 1 bitops, 2 lean idle, 3 DSQ direct index, 4 wake signals, 5 identity |
| `series.proven` | 1, 2, 5; historical measured feature subset, unmeasured on this port |

From this collection's root:

```bash
scripts/apply.sh kernel/sched-ext/cachyos-7.3.0 /path/to/cachyos-7.3.0-3 --series series.all --check
scripts/apply.sh kernel/sched-ext/cachyos-7.3.0 /path/to/cachyos-7.3.0-3 --series series.all
```

The [kernel track guide](../../README.md) documents features, consumer,
comparison switches, ABI differences, build commands and remaining gates.
This port keeps caller/CPU validation before lean claims, uses current verifier
metadata, and validates wake-signal root opt-in through scheduler ancestry.
Experimental flag bits remain 9, 10 and 11 on this exact CachyOS base.

## Evidence

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-22 | Complete `series.all` | Applies with zero fuzz to exact pristine preimages |
| 2026-10-22 | Affected kernel objects | All 12 requested object targets build with Clang 23.1.3; sched_ext/sub-scheduler/IRQ/large off-stack-mask paths enabled |
| 2026-10-22 | Scalar-bitops BPF test | Object compiles with warnings as errors; skeleton generated; not loaded or executed |

Build source was the official release archive, whose SHA-256 matched the
publisher's asset digest:
`bfeeda277d5d39b6b8a47f3f341794c29ad9f86d1259d4519c7eedef56fb0fec`.
Patched touched-file bytes were compared with a fresh application of this series.
Local logs, config and hash receipts are under the gitignored
`artifacts/check-compatibility/` directory when produced by the maintainer pass.

Not fully linked, booted, installed, verifier-tested or benchmarked. Earlier
7.2 timing/game results are not measurements of this port. The wake-warning
fix is included, but there is no boot-time warning result for this source.
