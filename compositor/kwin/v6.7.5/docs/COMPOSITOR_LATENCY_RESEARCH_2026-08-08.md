# Compositor latency research: routes to a faster KWin

Date: 2026-08-08
Method: five research tracks — compositor frame scheduling, Windows DWM
and Reflex, Wayland/DRM latency protocols, low-latency systems patterns, and a
full audit of this repository's own measured numbers.

Goal under test: Linux esports input-to-photon competing with Windows.

## 1. Headline

The largest compositor lever is the render-time predictor, not CPU work. Three
independent records agree.

| Source | Finding |
| --- | --- |
| farnoy.dev LDAT study | KWin predicts 11.35 ms render, actual 2.06 ms — 9.23 ms slack at p50 |
| This repository | stock composited early-start budget about 6.46 ms; DRM safety 2.461 ms untouched |
| KWin source | `RenderJournal::result()` returns `m_result + m_variance * 2` |

Correction against the excitement this number invites: 9.23 ms of slack is not
9.23 ms of latency. The same study measured only 1.1-1.2 ms actually recovered
by patching. Slack sets how early the compositor wakes; recovering it moves the
client's submission deadline later, which returns a fraction, not the whole
window.

## 2. The honest ladder

| Rank | Lever | Realistic prize | Status |
| --- | --- | --- | --- |
| 1 | Render-prediction slack | 1-2 ms | patch 0009 written, OFF, carries a BLOCKER |
| 2 | Reflex-class latency sleep | 2-18 ms, GPU-bound only | installed in Proton, not enabled |
| 3 | XWayland avoidance | 3.13 ms | measured by marco-nett.de |
| 4 | `wp_commit_timing_v1` | unmeasured | **KWin does not implement it** |
| 5 | Direct scanout | 0.29-1.6 ms | blocked by the color transform |
| 6 | Adaptive wake margin | about 0.98 ms | ON, never measured live |
| 7 | Lock-free input queue | 15 ns | noise — do not build it |

## 3. The gap worth attacking: commit-timing-v1

A grep over the vendored `kwin-6.7.4` tree for `commit.timing`, `commit_timer`,
and `wp_commit` returns zero hits. `wayland/CMakeLists.txt` lists `fifo-v1.xml`
and no `commit-timing-v1.xml`.

Eleven other compositors implement it: Mutter, Sway, Weston, GameScope,
Hyprland, COSMIC, Mir, Wayfire, Muffin, Jay, Cage.

What it does: lets a client say "present this content as closely as possible to,
but not before, time T" in the presentation clock domain. That is precisely the
client-side answer to an over-conservative compositor deadline — the client
renders late and still hits the target vblank.

The Vulkan counterpart is already landing: `VK_EXT_present_timing` merged into
Mesa 26.2, and `VK_EXT_present_mode_fifo_latest_ready` removes plain FIFO's
queue-depth latency.

This is the single clearest piece of missing upstream work found in the sweep.

## 4. Defect found in the predictor

`renderjournal.cpp:41-44` returns `m_result + m_variance * 2`, and `m_variance`
is a max-tracking EWMA that cannot fall below its latest positive excursion
(lines 33-34). The journal is per-output. One occasionally slow window therefore
inflates the wake-up deadline for every window on that monitor, and the
inflation persists.

The DRM safety margin has the same asymmetry: `drm_commit_thread.cpp:166-181`
adds the full lateness immediately and removes surplus at 1/10 per frame,
clamped to `[0, min(3 ms, vblank/2)]`. One late commit costs roughly ten frames
of extra margin.

Both are correctness defects in the estimator, not tuning constants.

## 5. Windows comparison — the gap is smaller than assumed

One rigorous same-hardware study exists: farnoy.dev, using a Teensy flashed as a
USB HID mouse plus a light sensor, hundreds of samples per condition.

| Case | Linux | Windows |
| --- | ---: | ---: |
| Doom Eternal, Vulkan, vsync + cap | 11 ms | 10 ms |
| Doom Eternal, Vulkan, no vsync | 10 ms | 10 ms |
| Borderlands 3, DX11, vsync uncapped | 12-13 ms | 9 ms |
| Borderlands 3, DX11, capped | 9-10 ms | 9 ms |

The gap is configuration-dependent, not architectural. Vulkan is already at
parity. Caveat: that study's "patched KWin" section describes this
repository's own work, so it is not independent validation of these patches.

Windows' structural advantage is Independent Flip and multi-plane overlay, which
remove the composition frame entirely. Linux's equivalent is direct scanout plus
tearing control — both already exist.

## 6. The ceiling nobody should ignore

Mutter's dynamic render-time work (merge request 1762) measured about 10 ms
median improvement across terminals and editors, and explicitly little gain on
an SDL2 game because the GPU was saturated.

Compositor scheduling wins are largest on desktop applications and smallest on
GPU-bound games. An esports title is the second case. Plan accordingly: the
compositor is worth 1-4 ms here, while render-queue control is worth more.

## 7. Zero-build levers available now

| Lever | Mechanism | Cost |
| --- | --- | --- |
| `PROTON_VKD3D_LOWLATENCY` / `PROTON_DXVK_LOWLATENCY` | Reflex-class latency sleep; `proton` script lines 1871-1872 | Steam launch option, game restart |
| `LOW_LATENCY_LAYER` | implicit Vulkan layer; `proton` line 1949-1951 | same |
| `KWIN_DRM_OVERRIDE_SAFETY_MARGIN` | replaces the `vblankTime + 1000 µs` base; farnoy used `-150` | logout |
| Tearing | `AllowTearing` defaults true; game must request async present | in-game vsync off |

`dxvk-low-latency/` and `vkd3d-low-latency/` are both present in the installed
`proton-cachyos-slr`. Helldivers 2 has no Steam launch options set — checked by
grep for `LaunchOptions` near appid 553850.

## 8. What to skip, with reasons

- **Lock-free SPSC queue for throughput.** Measured difference versus an
  uncontended mutex is about 15 ns per event. At 1 kHz that is 15 µs per second.
  Noise against a 4.167 ms frame.
- **`isolcpus` / `nohz_full` on a gaming desktop.** Wins about 18 µs of jitter
  and costs the game a core.
- **USB IRQ affinity pinning.** Every source found was a Windows enthusiast
  forum using LatencyMon, with contradictory advice. No Linux measurement.
- **`SCHED_DEADLINE`.** Blocked three ways: `fork()` returns `EAGAIN`,
  `sched_setaffinity` fails for deadline tasks, and the period is not constant
  under VRR. No compositor has shipped it.

The one input-path change worth making is not the queue type. It is the priority
inversion: a `SCHED_RR` producer blocking on a non-priority-inheriting mutex held
by a preempted main thread that drains while holding the lock. Fix by swapping
the container out under the lock and processing outside it.

## 9. What remains unmeasured

1. Input-to-photon, anywhere in this project.
2. Any stock-versus-patched A/B. Every trace in `artifacts/results/` is a
   patched build.
3. The 0.7-0.9 ms wake saving — derived, never observed.
4. Eleven of eighteen patches have no measurement behind them.

Until item 1 exists, every number in this document is someone else's
measurement or this project's own estimate.

## 10. Recommended order

1. Build the Tier 1 input-to-presented client from
   `docs/INPUT_TO_PHOTON_MEASUREMENT_PLAN.md`. Nothing below is provable without
   it.
2. Turn on the Proton latency-sleep flags and measure the delta.
3. Fix the `RenderJournal` variance floor and the DRM margin decay asymmetry.
4. Implement `wp_commit_timing_v1`.
5. Return to direct scanout only after the color transform is correct.
