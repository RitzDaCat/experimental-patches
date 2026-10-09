# Hardening flag runtime cost — researched report

Question: what do `-Wp,-D_GLIBCXX_ASSERTIONS`, `-Wp,-D_FORTIFY_SOURCE=3`,
`-fcf-protection`, and `-fstack-clash-protection` cost at runtime?

Method: 18 sources reviewed, 25 claims cross-checked (18 confirmed, 7
rejected), 9 findings.

Purpose: replace the 5% assumption used in the earlier ceiling arithmetic with
sourced per-flag numbers.

---

## 1. Per-flag results

| Flag | Measured cost | Evidence quality |
|---|---|---|
| `-fcf-protection` (IBT / endbr64) | 0%–1.46% SPEC CPU2017 intspeed; 0%–0.77% real server apps; **1.85 ±1.02% Phoronix Test Suite** | **High** — 3 independent primary sources on real CET silicon |
| `-fcf-protection` (shadow stack half) | 0.40%–0.99% when enforced — but **dormant on a stock Linux build** | **High** — verified empirically on this machine |
| `-D_GLIBCXX_ASSERTIONS` (class) | **0.30%** Google fleet average, vs a cited "up to 6%" from one HPC code | **Medium** — the 0.30% measures libc++, not libstdc++ |
| `-D_FORTIFY_SOURCE=3` | **No published measurement exists.** All distro claims are =3-vs-=2 deltas asserted without data; the circulating ~0.1% is uncited | **High** (that the gap exists) |
| `-fstack-clash-protection` | **No published measurement exists.** Only an unquantified implementer statement | **Medium** |

### Detail worth keeping

- **IBT** — FineIBT (Gaidis et al., RAID '23, three Intel co-authors), Tiger Lake
  i7-1185G7 pinned to 3 GHz, Turbo/DVFS off, 10 ref runs: 600.perlbench 1.46%,
  605.mcf 0.51%, 625.x264 0.05%, 602.gcc 0.03%; 8 of 9 benchmarks under 0.51%.
  Applications: nginx 100KB 0.77%, Redis 0.39%, MariaDB 0.55%.
  HEK-CFI (ACM 2024) on Alder Lake: 0.17 ±0.23% SPEC CPU2017, **1.85 ±1.02%
  Phoronix Test Suite** — the closest thing in the corpus to a desktop workload,
  and the highest CET figure found.
- **Shadow stack** — ARES 2025 (Springer LNCS 15993), Raptor Lake i7-1360P:
  0.99% intrate, 0.40% intspeed. But the workflow verified on *this* machine that
  a `-fcf-protection=full` binary shows `x86 feature: IBT, SHSTK` under
  `readelf -n`, while `arch_prctl(ARCH_SHSTK_STATUS)` returns `0x0` — shadow
  stack is NOT active without `GLIBC_TUNABLES=glibc.cpu.hwcaps=SHSTK`, despite
  glibc 2.44, CPU flag `user_shstk`, and `CONFIG_X86_USER_SHADOW_STACK=y`.
  So this half contributes ~0% to your build.
- **Bounds checks** — Google, Nov 2024, republished ACM Queue 23(5) 2025 and
  cited in WG21 P3471R4: "Hardening libc++ resulted in an average 0.30%
  performance impact across our services", deployed across Search, Gmail, Drive,
  YouTube, Maps, alongside a 30% drop in baseline segfault rate. The measurement
  was precise enough to resolve one redundant bounds check as 0.35% → 0.30%.
  The competing "up to 6%" is OpenSSF's single citation to one 2021 HPC
  particle-accelerator code; the source was unreachable during verification
  (`gitlab.psi.ch` does not resolve) and is five years old.
- **Unmeasured distro claims** — Fedora calls `_GLIBCXX_ASSERTIONS` "cheap",
  Arch RFC 0017 says costs are "likely overblown", OpenSSF says CET is
  "typically mild due to hardware assistance". None carries a benchmark. All
  were downranked as evidence **in either direction**.

---

## 2. Recomputed ceiling against your measured frame

Denominators are your own telemetry, unchanged:
`artifacts/results/20260722-114310-palworld-r13-120-trace/summary.md`, DP-2 at
3840x2160@240.02.

```
Frame interval        4166.4 us
Render p50             295.3 us   (7.1% of frame)
Render p99            1660.0 us   (39.8% of frame)
Wake lateness p50       13.1 us   <-- telemetry noise floor

Aggregate tax, best-supported:  1.85% (IBT, Phoronix)
                              + 0.30% (bounds, Google)
                              + 0.00% (shadow stack, verified dormant)
                              +    ?  (FORTIFY=3, stack-clash: unmeasured)
                              = 2.15% + unknown

Aggregate tax, pessimistic:     1.85% + 6.00% = 7.85%
                                (uses the weak, unreachable HPC outlier)

           best-supported        pessimistic
  p50      6.4 us  (0.15%)      23.2 us  (0.56%)   of frame
  p99     35.7 us  (0.86%)     130.3 us  (3.13%)   of frame
```

**Both columns remain ceilings.** They treat the entire render span as CPU code,
which it is not — GPU work and driver time inside that span cannot be taxed by
codegen flags.

**The headline:** the best-supported p50 figure, 6.4 us, sits **below your own
measured wake-lateness p50 of 13.1 us**. You could not resolve it with the
telemetry you have.

The earlier 5% assumption sat between the two columns, so the ceiling
arithmetic it produced was not misleading.

---

## 3. Caveats that limit all of the above

1. **No graphics workload anywhere.** Not one source measures a compositor,
   game, or per-frame-latency workload.
2. **No tail latency anywhere.** Every figure is a mean, geometric mean, or
   throughput delta. For a per-frame budget the metric that matters — p99 frame
   time, worst-case bounds-check cost in a hot path — is unreported by everyone.
3. **Optimisation-level mismatch.** All measurements are at `-O2`. This build is
   `-O3 -march=native`. No source measures any of these flags at `-O3`.
4. **Toolchain mismatch.** FineIBT used modified LLVM 12 + musl; ARES used Clang
   18.1.8; Google measured libc++. Not one headline figure comes from
   GCC + glibc + libstdc++, which is what this machine uses.
5. **Baseline mismatch on FORTIFY.** Every FORTIFY claim compares =3 against =2,
   never against an unfortified build.
6. **The secondary angle went unanswered.** Whether `_GLIBCXX_ASSERTIONS` costs
   differ between `-O2` and `-O3`, and its cost in `std::vector`/`std::span`
   indexing hot loops, is not answered by any source located. Every claim that
   tried to link the low cost to optimizer behaviour was **refuted** in
   verification.
7. **The two highest-cost datapoints are the least verified.** The "up to 6%"
   OPAL merge request was unreachable, and an "arbor ~25%" report reached
   verification only as a search snippet. Do not build a decision on either.

---

## 4. What would actually answer it for KWin

An A/B build on this machine: rebuild `libkwin` with the four flags stripped,
re-run a Palworld capture, compare render-duration p50/p99 from the same
telemetry pipeline. That is the only path to a number that describes *your*
compositor rather than SPEC or a server RPC fleet.

Cost: one full KWin build plus a repeat gaming capture session.

---

## 5. Sources

Primary measurements:
- https://arxiv.org/abs/2303.16353 — FineIBT (RAID '23)
- https://cs.brown.edu/~vpk/papers/fineibt.raid23.pdf
- https://arxiv.org/abs/2412.16343 — shadow stack (ARES 2025)
- https://link.springer.com/chapter/10.1007/978-3-032-00627-1_10
- https://dl.acm.org/doi/pdf/10.1145/3634737.3661135 — HEK-CFI
- https://cseweb.ucsd.edu/~dstefan/cse227-spring20/papers/shanbhogue:cet.pdf — Intel HASP'19 (simulation)
- https://security.googleblog.com/2024/11/retrofitting-spatial-safety-to-hundreds.html
- https://queue.acm.org/detail.cfm?id=3773097 — ACM Queue republication
- https://research.google/pubs/practical-security-in-production-hardening-c-standard-library-at-massive-scale/

Unmeasured / downranked:
- https://fedoraproject.org/wiki/Changes/HardeningFlags28
- https://fedoraproject.org/wiki/Changes/ShadowStack
- https://fedoraproject.org/wiki/Changes/Add_FORTIFY_SOURCE=3_to_distribution_build_flags
- https://rfc.archlinux.page/0017-increase-fortification-level/
- https://best.openssf.org/Compiler-Hardening-Guides/Compiler-Options-Hardening-Guide-for-C-and-C++.html
- https://blog.llvm.org/posts/2021-01-05-stack-clash-protection/
- https://developers.redhat.com/articles/2023/02/06/how-improve-application-security-using-fortifysource3
- https://developers.redhat.com/articles/2022/09/17/gccs-new-fortification-level
- https://gotplt.org/posts/fortify-source-3-performance.html
- https://libcxx.llvm.org/Hardening.html
- https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2025/p3471r4.html
