# Refresh-relative compositor timing controller

Revision 3.8 adds an exact-kernel-gated controller for the two timing terms KWin
can safely learn inside each output's `RenderLoop`: render prediction and timer
wake reserve. The live policy has no fixed millisecond tuning constant. All
durations are stored and evaluated as integer nanoseconds.

## Design boundary

The controller changes when KWin starts a compositing cycle. It does not change
game render queues, DRM atomic-commit semantics, NVIDIA fences, scanout
eligibility, cursor handling, or the output backend's presentation safety
margin. Those remain separate terms in KWin's deadline:

```text
compositor start = presentation target
                 - adaptive render budget
                 - backend presentation safety margin
                 - adaptive wake reserve
```

Starting later can let KWin consume a newer client buffer and reduce compositor
buffer age. It cannot guarantee an equal input-to-photon gain, and it must not
be allowed to increase missed presentation deadlines.

## Per-output, per-path state

KWin already owns one `RenderLoop` per output. Revision 3.8 stores four fixed
state records in each loop, one for each presentation path:

- VSync;
- adaptive sync (VRR);
- async (tearing);
- adaptive async.

The 4K 240 Hz primary output therefore cannot learn from the 60 Hz secondary
output. Changing an output's refresh rate resets both controllers for that
output. Direct-scanout completions with no measured render work do not train the
render predictor.

## Refresh-derived bounds

Let `R` be the current output refresh duration in nanoseconds. The live bounds
are:

| Term | Formula |
| --- | ---: |
| Wake floor | `max(R / 256, 1 ns)` |
| Wake guard | `max(R / 2048, 1 ns)` |
| Wake hysteresis | `max(R / 1024, 1 ns)` |
| Wake ceiling | `max(R / 4, 1 ns)` |
| Render floor | `max(R / 64, 1 ns)` |
| Render guard | `max(R / 1024, 1 ns)` |
| Render hysteresis | `max(R / 256, 1 ns)` |
| First-frame render bootstrap | `max(R / 2, 1 ns)` |
| Render sample ceiling | `2 * R` |

Example values, rounded only for display:

| Output mode | Wake floor | Wake guard | Wake ceiling | Render floor | Render guard | First-frame bootstrap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 240 Hz | 16.3 us | 2.0 us | 1.042 ms | 65.1 us | 4.1 us | 2.083 ms |
| 60 Hz | 65.1 us | 8.1 us | 4.167 ms | 260.4 us | 16.3 us | 8.333 ms |

The displayed millisecond values are results of the refresh formulas, not
constants embedded in the controller.

## Render-budget update

The OpenGL timestamp query now exposes its raw start-to-end span. Its historic
2 ms minimum is retained only as `predictionFloor` metadata for stock, shadow,
kernel-mismatch, and recovery behavior. Exact-gated live mode never applies
that floor:

1. Before the first measured composited frame, use `R / 2`.
2. Adopt the first raw span plus the refresh-derived guard.
3. Track the largest and second-largest values in a 128-sample window using a
   fixed array-free state record.
4. Use the second-largest value as the persistent tail estimate, rejecting one
   isolated spike per window.
5. Give a new single overrun an emergency reserve for eight composited frames.
6. If a second high observation arrives, raise the persistent budget
   immediately.
7. After a clean window, remove one quarter of the excess, but at least one
   refresh-derived guard.

The hot update contains bounded integer arithmetic and comparisons. It performs
no allocation, sorting, locking, file I/O, environment lookup, or clock read.

## Wake-margin update

The existing v2 wake controller keeps its 256-sample, second-largest-tail
policy and external-stall rejection. Revision 3.8 replaces its fixed 100 us
floor, 50 us guard/decay, and 2 ms hard ceiling with the refresh formulas above.
Clean-window descent is proportional rather than a fixed time step.

## Modes and kernel gate

Both controls are evaluated only when
`KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE` exactly matches `uname -r` at KWin
startup.

| Variable | `0` | `1` | `2` |
| --- | --- | --- | --- |
| `KWIN_ADAPTIVE_COMPOSITOR_MARGIN` | Configured fixed wake reserve | Learn only | Apply refresh-relative wake reserve |
| `KWIN_ADAPTIVE_RENDER_BUDGET` | Stock render prediction | Learn only | Apply refresh-relative render prediction |

On an LTS or recovery kernel with a different release, KWin uses the original
timer, configured fixed wake allowance, and stock render predictor. Telemetry
is not required for either live controller and can remain disabled.

## Test progression

Use shadow mode first to validate raw durations and state transitions. Then run
fixed/live/fixed blocks with identical game scene, output topology, VRR policy,
frame cap, power state, and background load. Reject the candidate if live mode
worsens target misses, page-flip lateness, p99/p99.9 delivery, direct scanout,
VRR behavior, or GPU/DRM errors. An external high-speed or LDAT-style
input-to-photon measurement is required for a latency claim.
