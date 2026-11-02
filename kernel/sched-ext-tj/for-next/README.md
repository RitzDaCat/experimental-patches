# sched_ext experiments — TJ for-next

Complete feature series for TJ's integration branch `for-next`, pinned at
`6de3fab67de6b6765f8d7146dc03eda38f8ffc79`. Its Makefile says `7.3.0-rc1`;
branch names do not establish a released kernel version.

Source: [TJ sched_ext](https://git.kernel.org/pub/scm/linux/kernel/git/tj/sched_ext.git/).
This directory has its own exact base hashes and regenerated patch contexts;
it is separate from [the for-7.4 track](../for-7.4/).

```bash
# From this collection's root, with the pinned pristine checkout:
scripts/apply.sh kernel/sched-ext-tj/for-next /path/to/tj-for-next --series series.all --check
scripts/apply.sh kernel/sched-ext-tj/for-next /path/to/tj-for-next --series series.all
```

`series.all` includes bitops, lean idle, DSQ direct indexing, wake signals and
identity. Default `series` is identity only. `series.proven` is the bitops/idle
subset whose measurements come from older CachyOS builds, not this port.

Port behavior and ABI details match the [kernel track guide](../../README.md):
preserve upstream flags 9/10, use experimental bits 11/12/13, retain caller
validation, preserve proxy-donor callback semantics and keep upstream DSQ
comparison code.

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-22 | Complete series | Applies with zero fuzz to exact source hashes |
| 2026-10-22 | Affected kernel objects | All 12 targets compile with Clang 23.1.3; proxy execution, sub-schedulers and IRQ accounting enabled |

No full kernel link, verifier test execution, boot, install or performance
measurement was performed. Follow the [TJ test section](../README.md) and
[remaining gates](../../README.md#build-and-remaining-gates).
