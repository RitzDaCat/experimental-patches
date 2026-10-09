# Ultra-low-latency KWin stack, revision 3.9

## Outcome

Revision 3.9 keeps the active game repaint path immediate and replaces KWin's
fixed 30 Hz fallback for unrelated damage on an active VRR output with a
deadline derived from that output's measured foreground cadence. The deadline
is phase-aligned to the last presentation and cannot be later than the next
expected foreground frame. If that deadline has already passed, the repaint is
requested immediately.

This is intentionally narrower than a new compositor scheduler. It improves a
real stall and transition tail without putting foreground rendering behind a
new queue.

## Original stack

```mermaid
flowchart LR
    I["Mouse / keyboard"] --> LI["libinput"]
    LI --> K["KWin main thread"]
    G["Game buffer damage"] --> S["Wayland surface"]
    U["Overlay / decoration damage"] --> R["Per-output RenderLoop"]
    S --> R
    R --> Q["QBasicTimer, whole-ms scheduling"]
    Q --> C["Composite() on shared main thread"]
    C --> DS{"Direct scanout accepted?"}
    DS -->|"yes"| D["DRM commit"]
    DS -->|"no"| GPU["GPU composition"]
    GPU --> D
    D --> P["Page flip / VRR presentation"]
```

Each output owns a RenderLoop and chooses VRR independently, but both outputs
ultimately call `Compositor::composite()` on KWin's shared main thread.

```mermaid
flowchart TB
    A["Active window"] --> O1{"Intersects output 1?"}
    A --> O2{"Intersects output 2?"}
    O1 -->|"fullscreen / VRR rule"| V1["Output 1: AdaptiveSync"]
    O1 -->|"no"| F1["Output 1: VSync"]
    O2 -->|"fullscreen / VRR rule"| V2["Output 2: AdaptiveSync"]
    O2 -->|"no"| F2["Output 2: VSync"]
    V1 --> M["Shared KWin main thread"]
    F1 --> M
    V2 --> M
    F2 --> M
    M --> G["Shared GPU / DRM resources"]
```

KWin does not currently have a global "game output" scheduler. Desktop output
priority controls layout, not render-loop service order. Adding a new global
arbiter would require queuing ready frames and could add latency, so revision
3.9 does not do that.

## Fixed fallback problem

In KWin 6.7.3, unrelated damage on an output whose active surface is driving
VRR arms a `1000 ms / 30` `QBasicTimer`. Foreground surface damage cancels that
timer and schedules normally, so a continuously rendering game is not normally
held for 33.3 ms. The fixed fallback matters when the foreground cadence stalls,
drops, or changes while other content needs repainting. Repeated unrelated
damage can also keep restarting the fixed timer.

![VRR fallback ceiling across foreground cadences](assets/vrr-fallback-ceiling.svg)

The chart is a policy ceiling, not an input-to-photon result. At 240 Hz, the
candidate's maximum wait is one phase-aligned 4.17 ms output interval for a
240+ FPS foreground cadence. If part of that interval has already elapsed, the
actual fallback is shorter. Foreground game damage remains immediate.

## Revision 3.9 stack

```mermaid
flowchart LR
    D["Damage"] --> P{"Foreground surface?"}
    P -->|"yes"| FAST["Immediate existing repaint path"]
    P -->|"no"| VRR{"Active VRR cadence available?"}
    VRR -->|"no"| FAST
    VRR -->|"yes"| G{"Exact kernel + explicit opt-in?"}
    G -->|"no"| STOCK["Stock 30 Hz fallback"]
    G -->|"yes"| C["cadence = max(measured frame time, output interval)"]
    C --> DL["deadline = max(last presentation + cadence, now)"]
    DL --> T["Absolute timerfd"]
    T --> FAST
    FAST --> B["Per-output / per-path render budget"]
    B --> W["Per-output / per-path wake reserve"]
    W --> COMP["Composite or direct scanout"]
```

```mermaid
sequenceDiagram
    participant U as Unrelated damage
    participant R as Output RenderLoop
    participant T as PreciseTimer
    participant G as Foreground game
    U->>R: repaint request
    R->>T: arm next measured-cadence deadline
    alt game produces the next frame
        G->>R: foreground damage
        R->>T: cancel fallback
        R->>R: schedule immediately
    else foreground stalls
        T->>R: phase-aligned timeout
        R->>R: schedule immediately
    end
```

## scx_cake principles applied

| scx_cake lesson | KWin application |
| --- | --- |
| Fast path by construction | Foreground damage never enters a new queue or controller |
| Route from current state | Uses active-output intersection, measured surface cadence, output refresh, and last presentation |
| Per-domain state | Existing wake and render controllers remain per output and presentation path |
| Bounded work | Constant comparisons and integer chrono arithmetic; no loop, sort, or search added |
| Avoid shared hot state | No process-global game flag, mutex, atomic counter, or cross-output queue |
| Hysteresis and asymmetric debt | Existing controllers pay repeated tail debt immediately and consume clean safety credit gradually |
| Fail closed | Exact kernel mismatch or missing opt-in preserves the stock fallback |
| Measure tails, not only means | Acceptance requires p95/p99/p99.9 presentation and stability evidence |

## Hot-path cost boundary

The foreground test already called `recursiveFrameTimeEstimation()` in stock
KWin. Revision 3.9 returns that existing result instead of converting it to a
boolean and recomputing it. The foreground path adds no allocation, mutex,
clock read, telemetry, or timer arm. Stopping an inactive timer is a boolean
test and no timerfd syscall.

Only unrelated VRR damage in enabled mode takes the colder path: one monotonic
clock read, fixed chrono arithmetic, and one absolute `timerfd_settime()`.
`PreciseTimer` objects are allocated once per output at RenderLoop construction,
not per repaint.

## Safety and scope

- `KWIN_VRR_REPAINT_COALESCING=1` is required.
- `KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE` must exactly match `uname -r`.
- A missing or mismatched gate uses stock KWin behavior.
- State is naturally per output because every output owns its RenderLoop.
- The change does not alter direct-scanout acceptance, NVIDIA fence handling,
  DRM commit safety margins, input dispatch, or kernel scheduling.
- Diagnostic telemetry can remain off; this policy does not depend on it.

The candidate cannot yet claim lower input-to-photon latency. It has source,
model, compile, and package proof. Real acceptance still needs controlled A/B
testing and, for an end-to-end claim, an external optical measurement.

## Test gates

1. Compare stock fallback and revision 3.9 with the same game, scene, cap,
   monitor layout, VRR policy, kernel, driver, and power state.
2. Exercise continuous rendering, loading stalls, alt-tab, overlays,
   notifications, cursor movement, and focus changes across both outputs.
3. Reject on any increase in flicker, page-flip timeout, NVIDIA Xid, target
   misses, or p99.9 frame delivery.
4. Confirm direct scanout, HDR/color, tearing, capture, and recovery-kernel
   behavior separately.

## Deliberately deferred ideas

| Candidate | Why it is not in revision 3.9 |
| --- | --- |
| Cross-output EDF/game-first arbitration | Requires a new shared queue or deferral point on KWin's main thread; could add foreground latency |
| Lower DRM commit safety margin | NVIDIA's userspace fence wait and commit timing need attributable shadow measurements before reducing safety reserve |
| Input queue redesign | Existing measurements did not justify changing the mutex/dispatch semantics; a wrong handoff optimization can worsen tails |
| Always-on telemetry | Useful for experiments but not free; lowest-overhead gaming profile keeps it disabled |

These remain candidates only after a measurement identifies the exact losing
path. Revision 3.9 does not trade correctness or stability for a smaller
constant on paper.
