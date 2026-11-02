# sched_ext experiments: TJ for-7.4

All four kernel experiments, plus build identity, against public TJ sched_ext
branch `for-7.4` at `1f5dde349ac2fca1f119ae8de3f0d2f1c2a8d338`.
This is a 7.4 development target. Its source Makefile says `7.3.0-rc1`;
there is no claim of a released Linux or CachyOS 7.4 kernel.

Source: [TJ sched_ext](https://git.kernel.org/pub/scm/linux/kernel/git/tj/sched_ext.git/).
The same commit/ref was checked through the
[kernel.googlesource mirror](https://kernel.googlesource.com/pub/scm/linux/kernel/git/tj/sched_ext/).
`base.json` records the canonical source and exact commit; hashes bind the
pristine touched files.

From this collection's root, with a disposable checkout of that commit:

```bash
scripts/apply.sh kernel/sched-ext-tj/for-7.4 /path/to/tj-for-7.4 --series series.all --check
scripts/apply.sh kernel/sched-ext-tj/for-7.4 /path/to/tj-for-7.4 --series series.all
```

`series.all` selects bitops, lean idle, direct DSQ index, wake signals and
identity, in that order.
The default `series` is identity only until these ports have boot evidence.
`series.proven` selects bitops, lean idle and identity; its feature evidence
comes from older CachyOS builds, not this target.

The [kernel track guide](../../README.md) explains the port. TJ's upstream
flag bits 9/10 are preserved; experimental flags use 11/12/13 and must be
resolved through BTF by name. Wake tokens clear after actual proxy-donor
running callbacks. Lean claims retain current caller validation. The upstream
typed DSQ compare is already present and is not reapplied.

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-22 | Complete `series.all` | Applies with zero fuzz |
| 2026-10-22 | Affected kernel objects | All 12 targets compile with Clang 23.1.3, with proxy execution disabled and enabled; sub-schedulers and IRQ accounting enabled |
| 2026-10-22 | Scalar-bitops BPF test | Object and skeleton build; verifier/runtime execution not performed |

Patched touched-file bytes were checked against a fresh full-series application.
No full link, VM/hardware boot, install, scheduler activation or performance
measurement was performed. See the [TJ test section](../README.md) and
[remaining gates](../../README.md#build-and-remaining-gates).
