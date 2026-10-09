# Code review — 2026-08-07

Source: `/code-review` (xhigh effort, 10 inline angles, dedup, sweep). 15 findings,
correctness first. Two were fixed in the same session and are marked DONE.

Status legend: **BLOCKER** — fix before measuring · **REBUILD** — needs a patch
change and a KWin rebuild · **DONE** — fixed and verified.

---

## 1. `scripts/verify_reference_sources.sh:6` — provenance still pins 6.7.3 — BLOCKER

Hardcodes `kwin-6.7.3.tar.xz`, its URL, its sha, and `reference/upstream/kwin-6.7.3`,
while PKGBUILD builds 6.7.4. `./bin/kwin-latencyctl test` prints "reference
verification passed" AND "Verified package: kwin 6.7.4-1.1" in the same run. Any
patch that applies cleanly to 6.7.3 but differs on 6.7.4 ships unreviewed.

## 2. `reference/patched-overlay/src/core/renderloop.cpp:160` — emergency budget never decays — BLOCKER, REBUILD

`updateAdaptiveRenderBudget` returns on the `rawDuration <= 0ns` guard before
`state.emergencyFramesLeft--` and before `windowSampleCount` advances.
`queryRenderTime()` returns `RenderTimeSpan{}` on every fully direct-scanout frame,
so with `KWIN_ADAPTIVE_RENDER_BUDGET=2` a single 2 ms spike latches the emergency
budget, the game enters sustained direct scanout, and `renderPrediction()` returns
that latched value forever. The compositor then wakes up to two refresh intervals
early on every frame — the opposite of the feature's goal. Same defect at
`models/adaptive_render_budget.py:66`.

**Do not set `KWIN_ADAPTIVE_RENDER_BUDGET` until this is fixed.**

## 3. `reference/patched-overlay/src/core/renderloop.cpp:248` — 0ns deadline disarms the timer — REBUILD

`PreciseTimer::start` builds `itimerspec spec = {}`; `it_value = {0,0}` disarms the
timerfd, then `m_active = true` runs unconditionally. Line 681 already passes
`0ns`, safe today only because that branch takes the legacy QBasicTimer path. Any
future call reaching the coalescing branch with 0ns arms nothing while
`isActive()` reports it running. One-line fix: clamp to `std::max(deadline, 1ns)`.

## 4. `scripts/check_trace_safety.sh:32` — safety gate misses non-perf collectors — BLOCKER

Project policy forbids the dma_fence tracepoint family via "perf, tracefs, ftrace, BPF,
or another collector" after a kernel NULL-pointer fault in `perf_trace_dma_fence`.
The scan requires the regex `(^|/)(perf|perf_[^[:space:]]+)[[:space:]]+(record|trace)`,
so `trace-cmd record -e dma_fence:*` and `bpftrace -e 'tracepoint:dma_fence:*'`
report safe. The tracefs scan also misses `.../instances/*/events/dma_fence/enable`.

## 5. `tools/analyze_capture.py:119` — boot epoch wrong after suspend — BLOCKER

`boot_epoch = start_epoch - start_monotonic_ns // 1e9`. CLOCK_MONOTONIC does not
advance across suspend, so after a 2-hour suspend the derived floor is 2 hours
late and live telemetry is discarded as "stale from an earlier boot".
`capture_clock_sync.py` already samples CLOCK_BOOTTIME but
`capture_pipeline_window.sh` never records it into `window.txt`.

## 6. `tools/analyze_capture.py:219` — pageflip cadence deflated by duplicate rows — BLOCKER

`ordered_pageflips` is built from `rows`, not `wake_rows`, though the same function
computes `duplicate_wake_rows` precisely because several completion rows share one
presentation event. Each duplicate contributes a 0 ns interval, so with 20%
duplicates the reported cadence p50 collapses toward 0 ns.

## 7. `install.sh:50` — false "no pending kernel update" — **DONE**

`checkupdates 2>/dev/null | grep ... || true` reported success when
pacman-contrib was absent. Now requires the command and matches any `linux*`
package, so `linux-cachyos-lts` is caught.

## 8. `README.md:15` — docs describe a package nobody installs

README badges say 6.7.3-1.1 / revision 15; `reference/README.md:21` says patches
0001–0016; `docs/PACKAGE_VERSIONING.md` pins 6.7.3 / revision 16. Actual: PKGBUILD
6.7.4 / revision 17, patches 0001–0018, RELEASE 6.7.4-1.1 / 17. No test covers the
docs — `test_package_versioning.py` only compares PKGBUILD against RELEASE.

## 9. `patches/0001-precise-timer.patch:1` — all 18 patches exist twice

Tracked under `patches/` and byte-identical untracked copies at the repo root, with
no `.gitignore` rule. PKGBUILD and `verify_reference_sources.sh` read only the
tracked copy, so a root-copy edit is invisible to every hash check.

## 10. `tests/test_adaptive_margin.py:18` — tests recompute the implementation

`assertEqual(state.margin_ns, initial - max((initial - target) // 4, guard_ns))`
is the exact expression `AdaptiveMarginController.sample` evaluates. Changing
`// 4` to `// 2` in both places keeps the test green. Same tautology in
`test_one_large_stall_does_not_poison_window` and
`test_adaptive_render_budget.py::test_clean_window_decays_by_fraction_of_excess`.

## 11. `models/vrr_repaint_coalescing.py:10` — stock baseline off by 333 µs

`renderloop.cpp:250` uses `1'000ms / 30` = integer ms division = 33,000,000 ns.
The model uses `NS_PER_SECOND // 30` = 33,333,333 ns, and a test asserts the
model's value. `docs/assets/vrr-fallback-ceiling.svg` is generated from the same
wrong figure, so the claimed improvement over stock is misstated.

## 12. `reference/patched-overlay/src/core/renderloop.cpp:487` — two sources for refresh duration — REBUILD

The budget controller scales bounds from `frame->refreshDuration()` but bootstraps
from `d->refreshRate` and resets only from `RenderLoop::setRefreshRate`. During a
mode change the two disagree for at least one frame. The margin controller
consistently uses `d->refreshRate`; only the budget controller mixes them.

## 13. `reference/patched-overlay/src/core/renderloop.cpp:245` — one signature, two policies — REBUILD

`startDelayedVrrTimer(deadline)`'s `else` branch ignores the parameter and
hardcodes `1'000ms / 30`, forcing call site 681 to pass a meaningless `0ns` —
the same value that would disarm the timerfd on the other branch (finding 3).
Split into `startCoalescedVrrTimer(deadline)` / `startStockVrrTimer()`.

## 14. `bin/kwin-latencyctl:166` — SIGPIPE hazard under pipefail — **DONE**

`bsdtar | grep -m1` and `bsdtar | grep -Fxq` both replaced with variable capture,
matching the pattern PKGBUILD and install.sh already document.

## 15. `tools/replay_adaptive_margin.py:60` — duplicated if/elif bodies

`if controller is None:` and `elif row_refresh_ns != controller.refresh_ns:`
construct the controller identically. Collapse to one condition.
