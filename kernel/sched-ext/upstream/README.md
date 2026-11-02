# Upstream candidates: the measured patches, one per file

Each patch stands alone on clean CachyOS cachyos-7.2.9-1
([CachyOS/linux 65a94cb5c158](https://github.com/CachyOS/linux/commit/65a94cb5c1587a19242fe5a219f03343671f372e)).
Neither needs the other, the direct DSQ index or the wake-signal patches.

| # | Patch | Tree | What it does | Result (Ryzen 7 9800X3D) |
| --- | --- | --- | --- | --- |
| 1 | [bpf: native scalar bit kfuncs](0001-bpf-add-native-scalar-bit-operation-kfuncs.patch) | bpf | bpf_ctz64, bpf_popcnt64, bpf_clz64 and bpf_mulhi64; the x86 JIT emits TZCNT, POPCNT, LZCNT and MUL inline; return bounds 0..64 | ops.running -2.31 ns, select_cpu -0.2 to -4.11 ns; no frame change |
| 2 | [sched_ext: lean idle claim](0002-sched_ext-add-lean-idle-claim-SCX_OPS_LEAN_IDLE.patch) | sched_ext | SCX_OPS_LEAN_IDLE: a one-word claim on its own cache line; SCX_OPS_LEAN_IDLE_LAZY_SMT: the core stays whole-idle until the claimed CPU runs | KovaaK's (CPU-limited): 1% low +7.5%, p99 -5.1%, average FPS +1.4%; select_cpu 81.9 to 68.2 ns |

## Checks

| Check | 1 bitops | 2 lean idle |
| --- | --- | --- |
| Applies alone to 7.2.9-1 | yes | yes |
| Compiles with the running config, 0 warnings | yes: helpers.o, verifier.o, bpf_jit_comp.o | yes: build_policy.o |
| checkpatch.pl | 2 warnings: MAINTAINERS for the new selftest files, volatile in the selftest | clean |
| Booted and measured | yes, as part of the 1-4 series | yes, as part of the 1-4 series |
| Applies to mainline 7.3-rc5 | no, port needed | no, port needed |

Apart from the commit messages, these match patches 1 and 2 of the CachyOS
tester sets (cachyos-<minor>/). Lean idle uses ops-flag bits 9 and 10 in
both, and scx_cake looks the flags up in BTF by name.

## Open before a mailing-list submission

- Signed-off-by: the author adds it; none is written here.
- Port to the current sched_ext for-next and bpf-next.
- Lean idle: a GPU-limited game A/B is still missing, and the
  nr_cpu_ids <= 64 limit needs a multi-word answer upstream.

scx_cake improvements that need no kernel change go upstream as a normal
scx pull request instead: the cached rq clock in ops.running (567715cc8)
and the wide-host idle popcount with the update_idle interlock.
