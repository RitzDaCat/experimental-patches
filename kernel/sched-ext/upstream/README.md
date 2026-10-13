# Upstream candidates — proven patches, one per file

Each patch stands alone on clean CachyOS `cachyos-7.2.9-1`
([CachyOS/linux `65a94cb5c158`](https://github.com/CachyOS/linux/commit/65a94cb5c1587a19242fe5a219f03343671f372e)).
Neither needs the other, the DSQ index or the wake-signal patches.

| # | Patch | Tree | What it does | Result (Ryzen 7 9800X3D) |
|---|---|---|---|---|
| 1 | [bpf: native scalar bit kfuncs](0001-bpf-add-native-scalar-bit-operation-kfuncs.patch) | bpf | `bpf_ctz64` / `bpf_popcnt64` / `bpf_clz64` / `bpf_mulhi64`; x86 JIT emits TZCNT / POPCNT / LZCNT / MUL inline; return bounds 0..64 | `running` −2.31 ns, `select_cpu` −0.2…−4.11 ns; no frame change |
| 2 | [sched_ext: lean idle claim](0002-sched_ext-add-lean-idle-claim-SCX_OPS_LEAN_IDLE.patch) | sched_ext | `SCX_OPS_LEAN_IDLE`: one-word claim on a dedicated cache line · `_LAZY_SMT`: core stays whole-idle until the claimed CPU runs | KovaaK's (CPU-limited): 1 % low +7.5 %, p99 −5.1 %, avg FPS +1.4 %; `select_cpu` 81.9 → 68.2 ns |

## Checks

| | 1 bitops | 2 lean idle |
|---|---|---|
| Applies alone to 7.2.9-1 | ✅ | ✅ |
| Compiles, running config, 0 warnings | ✅ `helpers.o` `verifier.o` `bpf_jit_comp.o` | ✅ `build_policy.o` |
| `checkpatch.pl` | 2 warnings: MAINTAINERS for new selftest files, `volatile` in the selftest | ✅ clean |
| Booted and measured | ✅ (as part of the 1–4 series) | ✅ (as part of the 1–4 series) |
| Applies to mainline 7.3-rc5 | ❌ port needed | ❌ port needed |

These match patches 1 and 2 of the tester sets (`cachyos-<ver>/`), commit message aside: lean idle
uses ops-flag bits 9 and 10 in both, and cake reads them from BTF by name.

## Open before a mailing-list send

- ⏳ `Signed-off-by:` — the author adds it; none is written here.
- ⏳ Port to current `sched_ext/for-next` and `bpf-next`.
- ⏳ Lean idle: GPU-limited game A/B; the `nr_cpu_ids <= 64` limit needs a multi-word answer upstream.

Cake-side wins that need no kernel change go upstream as a normal scx PR instead:
cached rq clock in `ops.running` (`567715cc8`) and wide-host idle popcount + `update_idle` interlock.
