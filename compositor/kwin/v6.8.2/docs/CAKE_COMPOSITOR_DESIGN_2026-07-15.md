# CakeRender: a state-reactive deadline controller for KWin

## Objective

Make KWin begin each display transaction as late as it safely can, use the newest
available input and client buffer, and still reach the intended scanout deadline.
The success criterion is lower end-to-end age at scanout with no increase in
missed flips, tearing, or frame-time tails. Lower CPU use or a prettier timer
trace is useful but is not sufficient evidence.

The timerfd package in this repository is the observer and precision prerequisite,
not the final scheduler. Its manually configurable 1000 microsecond allowance is
there to measure the safe range before a controller is allowed to move it.

## What carries over from scx_cake

| scx_cake design rule | Compositor equivalent |
| --- | --- |
| One master policy, minimal knobs | One deadline controller; environment variables are experiment controls only |
| Route from current system state, not task identity | Select a budget from the current presentation path, never a game/application name |
| Per-CPU local state | Per-output, cache-isolated state owned by its render/commit path |
| Virtual-time frontier and debt | Presentation-deadline frontier and stage-specific slack debt |
| Cheap prefilter, exact confirmation | Cheap direct-scanout/readiness eligibility, then the required atomic test |
| One-shot marks for otherwise invisible causes | One-frame miss reason: wake, render, fence, commit, or unknown |
| Boundary-exact accounting | Timestamp timer dispatch, render completion, fence readiness, atomic submit, and page flip |
| Structural progress instead of rescue machinery | Bounded conservative fallback after a miss or mode transition |
| Hot-path minimalism | Integer duration operations; no allocation, locks, logging, sorting, or general statistics in production |
| Promote only on whole-workload evidence | Stock/candidate ABBA with end-to-end latency and frame-delivery gates |

The analogy should not be copied literally. A CPU scheduler can derive much of its
decision from current runnable state. A compositor must predict GPU and display
work that has not completed yet, so a small amount of bounded history is necessary.
It should be path-local, cause-specific, and disposable rather than a long-lived
identity model.

## The controller

For each output and prospective frame, calculate:

```text
wake_deadline = presentation_deadline
              - render_budget[current_path]
              - fence_budget[current_path]
              - commit_budget
              - wake_budget
```

`current_path` is presentation state, for example:

- direct scanout;
- normal composition;
- composition with effects or color conversion;
- cursor-only update;
- modeset/cold transition.

It is not the executable, window title, Steam app ID, or foreground process. A
fullscreen game that stops being direct-scanout eligible immediately uses the
composition state.

### State and update rule

Each output owns a compact `DeadlineState` with a budget and clean-run counter for
each stage/path plus the last one-shot miss reason. On the critical path, budget
selection is a few bounded integer operations.

For the stage that actually missed:

```text
budget = min(cap, max(budget, observed_cost + guard))
clean_run = 0
```

For a successful stage, decrease only when there is proven excess slack:

```text
if slack > hysteresis:
    clean_run += 1
if clean_run reaches decay_interval:
    budget = max(floor, budget - decay_step)
    clean_run = 0
```

This gives the important asymmetry: one deadline miss makes the responsible stage
safe immediately; many clean frames are required to become more aggressive. It is
adaptive without an expensive generic predictor, without oscillating every frame,
and without allowing one slow GPU frame to inflate unrelated timer or KMS margins.

Mode changes, DPMS, refresh-rate changes, HDR/color-pipeline changes, and direct-
scanout transitions either select separate state or begin from conservative
defaults. Invalid or missing timestamps force the stock-safe budget.

### Miss attribution

The existing performance record must gain these boundaries before live adaptation:

1. requested and actual compositor wake;
2. render submission and GPU completion where available;
3. client/render fence readable;
4. atomic commit begin and return;
5. OUT_FENCE signal where reliable;
6. DRM page-flip timestamp.

The frame receives exactly one primary reason mark:

```text
WakeLate -> RenderLate -> FenceLate -> CommitLate -> Unknown
```

The order is causal, not an assertion that later stages do not matter. If the wake
was already late, growing every downstream reserve would make the next frame much
earlier without addressing the cause. Unknown misses temporarily increase a small
global guard and retain stock behavior until they are attributable.

## Fast paths that matter more than shaving another timer microsecond

### Direct scanout as a structural lane

A direct-scanout frame does not need a compositor-render prediction. Its deadline
contains client readiness plus KMS submission only. KWin should count attempts,
successes, and bounded rejection reasons per output. The exact atomic test remains
authoritative; counters never weaken color, capture, or security correctness.

This may be the largest safe latency improvement on fullscreen games. It also
prevents expensive composited frames from teaching the direct-scanout path to wake
early.

### Event-driven fence readiness

The NVIDIA fallback currently checks readiness in short intervals under relevant
VRR conditions. The target design waits for sync-file readability and the absolute
deadline in one event-driven operation. That removes RT-thread wakeups and a
roughly 50 microsecond polling granularity. `IN_FENCE_FD` remains capability-tested
and the existing fallback remains available if NVIDIA rejects it.

### Latest-frame admission

Keep at most one frame pending on the VRR path and latch the newest eligible client
buffer before the deadline. A newly arriving buffer can replace older unsubmitted
work, but it must not repeatedly move the same presentation deadline. This reduces
queue age without inventing extra preemption or buffering machinery.

### Hardware-visible commit feedback

Do not reduce NVIDIA's fixed DRM allowance from atomic-ioctl return time alone.
Train `commit_budget` from page-flip and reliable OUT_FENCE evidence per CRTC. An
ioctl returning quickly does not prove the hardware accepted the update in time.

## What not to do

- Do not add game-specific priorities, CPU pinning, or foreground-process rules.
- Do not use `SCHED_DEADLINE` as the first fix; it can mask a bad budget model and
  introduces admission/privilege failure modes. Existing RT execution should be
  measured before scheduling policy changes.
- Do not lower all margins together. A win cannot be attributed and a regression
  cannot be diagnosed.
- Do not optimize mean wake time. p99/p99.9 delivery and missed targets are the
  safety gates.
- Do not log or calculate quantiles in the production hot path. Export raw bounded
  counters/samples and analyze them outside KWin.
- Do not treat reduced CPU cycles or a synthetic timer win as gaming-latency proof.

## Implementation sequence

### Phase 0: precision and baseline (available now)

Package `kwin 6.7.3-3.5` implements the second bounded controller candidate on top
of the absolute timerfd and requested/armed/actual wake timestamps. Mode 0 keeps
the 1000 microsecond fixed baseline, mode 1 learns in shadow, and mode 2 applies
the per-output, per-presentation-path result. Every state starts at 1000
microseconds. A 256-sample window estimates the tail from its second-largest
wake lateness plus 50 microseconds, descends by at most 50 microseconds per
window, and ignores one isolated spike. A second tail observation can raise the
reserve immediately. Two wake stalls above the configured
reserve in one window immediately restore that reserve. Refresh changes reset
the output's four path states. Render and DRM prediction remain unchanged so the
result stays attributable. The whole experiment is additionally fail-closed
behind an exact `uname -r` match. Non-matching kernels use the original fixed 1
ms and `QBasicTimer` path, without constructing the timerfd or writing telemetry.

### Phase 1: offline replay

The reference model and deterministic safety cases now cover bounded descent,
outlier rejection, repeated-tail learning, two-stall fallback, path isolation,
refresh reset, and cold-start exclusion. The next replay step is to run actual
3.5 CSV captures through stock and candidate deadline calculations. Reject
parameter sets that would have missed any target that stock met.

### Phase 2: shadow mode

KWin calculates the adaptive budgets and records them, but continues using the
stock budget. Verify that controller state is bounded, mode transitions reset or
select the right state, and miss attribution agrees with traces.

### Phase 3: bounded live candidate

Enable only adaptive `wake_budget`, retaining the stock render and DRM learners.
Package it separately with an immediate rollback. If successful, test path-aware
render prediction, event-driven fences, and hardware-visible commit feedback as
independent candidates in that order.

## Keep/revert gates

Use repeated stock-candidate-candidate-stock blocks with the same output topology,
VRR policy, game scene, cap, and warm-up. Test single-output and the current
dual-240-Hz configuration.

Keep a change only if all of these hold:

- target-miss and >250 microsecond / >1 millisecond presentation-lateness rates do
  not regress;
- p95/p99/p99.9 frame delivery does not regress;
- measured wake-to-render opportunity moves later by the expected amount;
- external input-to-photon or trustworthy game latency improves across blocks;
- direct-scanout correctness, HDR/color, cursor, capture, and mode transitions stay
  correct;
- no NVIDIA Xid, graphics reset, page-flip timeout, or compositor instability.

The likely first production win is not a universally smaller constant. It is a
per-output and per-presentation-path wake reserve that commonly settles below 1
ms, responds to a repeated tail, restores the safe reserve on recurrent external
stalls, and cannot contaminate render or commit reserves.
The larger follow-on wins are separating direct scanout from composition and using
actual hardware completion to stop paying safety budgets that the current frame
does not need.
