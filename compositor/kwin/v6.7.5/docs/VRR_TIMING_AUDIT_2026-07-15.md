# KWin / DRM / VRR timing audit — 2026-07-15

## Engineering question

For the live CachyOS + KDE Wayland + NVIDIA system, identify timing quantization,
avoidable latency, or scheduling design issues between compositor repaint,
render completion, atomic commit, and VRR page-flip delivery. Optimize latency and
frame-time consistency without trading them for missed flips or tearing.

## Live system identity

- Kernel: `7.1.3-2-cachyos`, package `linux-cachyos 7.1.3-2`, built 2026-07-08.
- Kernel base: Linux 7.1.3 with CachyOS packaging/patches. The local Torvalds tree
  is newer (`4a50a141f05a`, v7.2-rc1 era), so it is reference source, not exact
  installed-source identity.
- Compositor: `kwin_wayland`, package `kwin 6.7.2-1.1`, KDE Wayland session.
- GPU: RTX 4090, NVIDIA 610.43.03; `nvidia_drm` 610.43.03.
- Outputs: DP-2 at 3840x2160@240.02, logical 2560x1440 at 1.5x; DP-3 at
  1920x1080@240.00. HDR/WCG and VRR `Always` are enabled on both.
- Presentation clock: `CLOCK_MONOTONIC`; kernel clocksource: TSC.
- Kernel timing config: PREEMPT_DYNAMIC currently resolves to preemptible behavior,
  HZ=1000, NO_HZ_FULL, high-resolution timers. CPU governor observed as performance.
- KWin main, per-output commit, and libinput threads run SCHED_RR priority 1.
- No page-flip timeout, invalid-presentation-timestamp, VRR-setting-failure, or
  graphics-reset messages were found in this boot's KWin journal.

## Source path and timing model

Installed KWin 6.7.2 is represented exactly by local tag `v6.7.2` at
`e34ec104bd373692eeb167947654e8411ccb1c1c` in
a local upstream KWin checkout.

1. `src/core/renderloop.cpp:44-113` estimates render cost from the render journal,
   adds the DRM safety margin and another 1 ms for scheduler/timer uncertainty, and
   schedules the next repaint before the target presentation time.
2. In VRR mode, it allows one pending frame and targets no earlier than one maximum-
   refresh interval after the last presentation (`renderloop.cpp:98-108,256-274`).
3. `src/compositor.cpp:711-722` selects AdaptiveSync because both outputs use the
   `Always` policy.
4. `src/backends/drm/drm_commit_thread.cpp:331-345` submits immediately under VRR
   once at least one minimum-vblank interval has passed; otherwise it predicts the
   next possible vblank.
5. The commit worker sleeps until target minus safety margin. Its base margin is
   hardware vblank time plus 1 ms; it adds an adaptive 0..min(3 ms, half-frame)
   correction after late commits (`drm_commit_thread.cpp:150-180,360-371`).
6. The DRM core queues and delivers vblank events; the NVIDIA driver supplies the
   actual display-engine implementation. Generic Linux DRM is an interface/event
   layer here, not the place where NVIDIA scanout timing policy is implemented.

## Confirmed issue / highest-value improvement

KWin 6.7.2 converts the desired wake-up delta to whole milliseconds before starting
a `QBasicTimer`:

```cpp
compositeTimer.start(std::chrono::duration_cast<std::chrono::milliseconds>(...))
```

This discards 0..almost 1 ms of timing resolution. At 240 Hz the frame interval is
about 4.166 ms, so the quantization is as much as 24% of one interval. It generally
wakes early rather than directly adding input latency, but waking early increases
the age of input sampled for a frame and consumes part of the carefully tuned
just-in-time rendering design.

KWin upstream already fixed this in commit
`cd46f9c9c34910a95b5ba8c83d8daffc248f4bb4` (2026-06-29),
`core/renderloop: use timerfd for compositor wakeups`. It replaces QBasicTimer with
KWin's absolute timerfd-backed `PreciseTimer` and schedules directly at the
nanosecond timestamp. The commit is after v6.7.2 and is not contained in a released
tag in the current local repository.

This is the first patch to test. It is small, upstream-authored, and targets this
exact mechanism. Do not lower `KWIN_DRM_OVERRIDE_SAFETY_MARGIN` first: KWin's source
explicitly retains the 1 ms base because NVIDIA may not have applied an atomic
commit when the ioctl returns. Reducing it without traces risks missed flips.

## Measurement gate before keeping a patched build

Run the same deterministic 240 Hz workload on stock and patched KWin, preserving
both output configurations. Capture:

- KWin `KWIN_LOG_PERFORMANCE_DATA=1` CSV per output: target flip, actual flip,
  render start/end, learned safety margin, VRR flag, predicted render time.
- KWin's exact-kernel-gated in-process DRM commit telemetry: queue time, IOCTL
  start/end, readiness retries, callback arrival, and page-flip timestamp.
- `/proc/<pid>/task/<tid>/schedstat` deltas for KWin and its per-output commit
  threads, sampled around rather than inside the precision window.
- PresentMon/MangoHud game frame times plus an external latency method if available.

Do not enable the kernel `dma_fence` tracepoint family on a live graphical
session. It caused a kernel NULL-pointer fault on `7.1.4-1-cachyos`; see
`INCIDENT_2026-07-23_DMA_FENCE_TRACE_KERNEL_OOPS.md`.

Primary comparisons: repaint wake-up error distribution, input-to-render-start
opportunity, render-end-to-commit, commit-to-vblank-event, missed target rate,
safety-margin convergence, and p50/p95/p99 frame interval. Test both one-output and
two-output configurations because independent 240 Hz commit threads and HDR color
processing may change the result.

## Decision

Status: partial investigation, with one confirmed code-level timing improvement.
The live configuration and exact compositor source are verified, but there is not
yet an A/B runtime capture. The next code-shaped step is a minimal v6.7.2 backport
of `cd46f9c9c3`, packaged separately for rollback, followed by the measurement gate
above. Kernel or safety-margin changes should wait for the safe in-process
evidence above.

## Follow-up stack review after the 6.7.3 package update

The installed package is now `kwin 6.7.3-1.1`, but KWin's live support-information
endpoint still reports `6.7.2`. This is expected until the graphical session is
logged out and back in; conclusions about live behavior currently describe the old
process.

### Findings by severity

1. **Actionable, measured only by source bounds: millisecond compositor timer.**
   The two-commit backport in this repository addresses this. It includes both
   `797d0820e6` (the timerfd-backed `PreciseTimer`) and `cd46f9c9c3` (render-loop
   conversion). Both are master/Plasma 6.8 only, not on the Plasma/6.7 branch.
2. **Moderate reliability concern, not a normal-frame latency defect:** upstream
   `8921b6dda3` fixes release synchronization when deleting OpenGL/Vulkan
   swapchains. The stated failure mode is visual glitches or a possible GPU hang
   when intermediary buffers are destroyed before GPU work completes. There are
   no NVRM Xids, GPU hangs, graphics resets, or relevant KWin errors in this boot,
   so there is no evidence that this machine is hitting it. It is master/6.8-only
   and should not be bundled into the timer experiment without reproducing the
   failure or reviewing its wider helper refactor.
3. **Low severity / visible smoothness:** `0e4fd91bfb` and follow-up `b3d0b71450`
   allow asynchronous hardware-cursor image repaints and correctly prepare the
   cursor hotspot. They fix dropped cursor-image-change frames, not ordinary cursor
   position latency. Both must travel together if ever backported.
4. **Low severity under VRR:** `fa4fd70b05` re-enables KWin's adaptive triple
   buffering on NVIDIA after a multi-GPU synchronization bug was fixed. KWin forces
   the effective pending-frame count to one in AdaptiveSync/AdaptiveAsync mode, so
   this does not change the normal VRR path. It can improve non-VRR frame delivery
   when rendering cannot fit inside one refresh interval.
5. **Design debt worth tracing, not patching blindly:** mixed cursor/primary VRR
   commits can poll at 50 microsecond intervals while waiting for a higher-priority
   commit (`drm_commit_thread.cpp:98-129`). The source itself has a TODO to poll
   buffer readiness instead. This interval can cause short bursts of wakeups, but
   the all-delayed case uses one timed wait and no current trace proves harmful CPU
   contention.
6. **Intentional NVIDIA margin:** KWin retains vblank time plus a 1 ms base DRM
   commit margin and learns up to an additional 3 ms/half-frame margin. The source
   explicitly says atomic-commit return is not a reliable applied-to-hardware
   signal on NVIDIA. Lowering this is unsafe without commit-to-vblank traces.
7. **No kernel scheduling alarm found:** TSC, high-resolution timers, PREEMPT,
   1000 Hz ticks, performance governor, and SCHED_RR priority 1 for the compositor,
   DP-2, DP-3, and libinput threads are all appropriate. Since boot, involuntary
   switches are about 0.5% for the main KWin thread and 0.1-0.3% for output threads;
   migrations exist but are not by themselves evidence of missed deadlines.
8. **The DRM/VRR contract is live:** both active CRTCs expose `VRR_ENABLED=1`, both
   connectors report VRR capable, and KWin uses EGL/OpenGL on NVIDIA 610.43.03.
   Linux DRM provides atomic properties and vblank events, but NVIDIA display-engine
   policy ultimately crosses into the NVIDIA driver/GSP boundary, so generic DRM
   source alone cannot prove hardware scanout latency.

### Recommendation after review

Keep the experiment narrow: timerfd backport only, then collect stock/patched
performance CSV and DRM/scheduler traces. Do not stack the synchronization,
cursor, triple-buffering, safety-margin, IRQ-affinity, or CPU-affinity changes into
the first A/B. If the traces show cursor image drops, swapchain-related Xids/hangs,
or repeatable commit lateness, promote the corresponding item into its own isolated
experiment.

## Optimization roadmap beyond the timerfd backport

This section identifies intentional latency/safety tradeoffs that can be redesigned,
not current correctness bugs. Expected wins are hypotheses until traced.

### 1. Replace the fixed compositor scheduler allowance with measured wakeup error

`RenderLoopPrivate::scheduleRepaint()` adds a fixed 1 ms after predicted render
time and the DRM presentation safety margin. The upstream timerfd conversion removes
millisecond quantization but leaves this allowance unchanged. KWin should record
`actual_dispatch_time - requested_timerfd_deadline` per output, maintain a quickly
rising/slowly falling high percentile, and use that plus a small floor instead.

The KWin main and output threads are already SCHED_RR and the timer becomes an
absolute timerfd. If observed p99 wake lateness is, for example, 100-200 us, this
could reclaim roughly 0.8-0.9 ms while preserving a measured tail-risk budget.
Keep instant escalation on a late wake and slow decay, analogous to the existing
DRM safety learner. This is the highest-value KWin-only follow-up.

### 2. Make render prediction conditional and quantile-based

`RenderJournal` predicts `EWMA(render time) + 2 * positive-only variance`. A single
slow frame immediately becomes the variance floor and then decays with a six-second
time constant. That is safe, but can cause many subsequent frames to start early,
making input/surface content older than necessary. It also combines different frame
classes (direct scanout, composited game, effects, HDR/color work, cursor-only).

A better design is a small rolling quantile estimator keyed by presentation path
and damage/frame class, with instant miss escalation and bounded decay. Compare
p95/p99 render prediction error and missed-flip count against the current journal.
This can reclaim more than 1 ms for seconds after isolated spikes, but only on
workloads whose render-time distribution is actually multimodal or spiky.

### 3. Learn the NVIDIA commit margin from hardware-visible completion

At both active modes the physical vblank is approximately 0.46 ms. KWin adds a
fixed 1 ms because the NVIDIA atomic ioctl may return before the commit is applied,
then learns an additional 0..min(3 ms, half-frame) from ioctl-return timing. That
learner optimizes syscall completion relative to a target, not actual hardware
application.

Use DRM page-flip timestamps and, where reliable, OUT_FENCE completion to build a
per-CRTC model of submit-to-apply behavior. Keep an immediate penalty for a missed
target and decay only after a large clean sample. This might reclaim part of the
second fixed millisecond, but it is higher risk than item 1 because the existing
comment specifically records NVIDIA behavior that defeated simpler timing.

### 4. Replace NVIDIA fence polling with readiness-driven commit wakeups

KWin omits `IN_FENCE_FD` on NVIDIA because atomic commits with it fail. It therefore
checks sync-file readability in userspace and, under VRR/tearing, advances the target
in 50 us steps until buffers are ready. Use epoll/QSocketNotifier-style readiness
notification plus an absolute deadline in the commit thread, eliminating periodic
polling and submitting immediately on fence signal. The direct latency bound is only
about 50 us, but this also reduces RT-thread wakeups and scheduling interference.

Separately, replace the permanent NVIDIA vendor exclusion with a once-per-device
capability probe if a safe atomic test can establish working `IN_FENCE_FD`; retain
the current path on failure. Kernel-managed input fences would be architecturally
cleaner and may allow earlier commits, but this depends on NVIDIA driver behavior.

### 5. Measure and maximize direct-scanout hit rate

Successful direct scanout removes KWin's composition render pass and is potentially
larger than micro-tuning timers. Add an inexpensive per-output reason counter for
attempts, successes, and rejection causes: format/modifier, scaling, color pipeline,
overlay/cursor, effects, capture, or atomic-test failure. The current 1.5x logical
scale and HDR/WCG path on DP-2 make this especially important to measure.

Do not weaken color correctness or capture/security rules merely to increase the
counter. Optimize the dominant safe rejection reason, if any. If fullscreen games
already scan out directly, this item has no remaining latency win.

### Quantified baseline for the active modes

- DP-2 3840x2160@240.016: frame interval about 4.166 ms; modeline vblank about
  0.461 ms.
- DP-3 1920x1080@240.000: frame interval 4.167 ms; modeline vblank about 0.463 ms.
- Before predicted render time, KWin's nominal early-start budget is therefore
  roughly 0.46 ms vblank + 1 ms DRM allowance + 1 ms compositor allowance, plus
  any learned DRM margin. The old timer adds up to almost another 1 ms of
  quantization; the timerfd patch removes only that last component.

Recommended sequence: timerfd A/B; measured compositor-slack prototype; render-
journal instrumentation and predictor replay; direct-scanout counters; only then
hardware-feedback DRM-margin work. Each stage needs a separately installable package
and rollback, with missed flips and p99 latency as hard keep/revert gates.

## Implemented adaptive wake candidate

Package `kwin 6.7.3-3.5` implements only the first roadmap item. Each output owns
four compositor wake-reserve states: VSync, adaptive sync, async, and adaptive
async. Each starts at the configured 1000 microsecond allowance. A 256-sample
window uses its second-largest valid timerfd wake lateness plus a 50 microsecond
guard, so one isolated spike does not inflate the controller. The reserve falls
by at most 50 microseconds per window, never below 100 microseconds, and raises
as soon as the tail repeats. Two wake
stalls larger than the configured reserve in one window immediately restore the
full reserve. Refresh-rate changes reset the states. Already-past and cold-start
schedules are excluded so render, commit, or power-state debt does not train the
wake estimate.

Modes are fixed (`0`), shadow (`1`), and live adaptive (`2`) through
`KWIN_ADAPTIVE_COMPOSITOR_MARGIN`. Performance CSVs contain applied and learned
margins, path/window state, and a timer-dispatch sequence that lets offline
analysis deduplicate repeated frame-completion rows. RenderJournal and the
DRM/NVIDIA safety learner are unchanged.

Revision 3.5 retains the fail-closed exact running-kernel gate introduced in 3.4.
Only `7.1.3-2-cachyos` uses the timerfd, telemetry, or adaptive path with the
current profile. Any other kernel uses the original QBasicTimer and fixed 1 ms
allowance; the `PreciseTimer` object is not constructed and telemetry is disabled.

The clean-built candidate is `kwin-6.7.3-3.5-x86_64.pkg.tar.zst`, SHA-256
`5591fa7d9fd5cee61a23f81752c81f4dccaaab929ea8ee5de99aa5b456877fce`.

Status remains experimental until it has run through the stock/candidate game gate.
