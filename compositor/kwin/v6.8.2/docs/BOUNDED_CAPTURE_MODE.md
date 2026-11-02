# Bounded capture mode

Revision 15 extends the temporary measurement mode with exact completed-frame
IDs, per-phase compositor clocks, every DRM commit, exact pageflip correlation,
and cold HDR/color construction and hardware-matching wall-clock time.
Capture remains off in the reviewed gaming policy and exact-kernel gated. It
does not expose the individual telemetry internals as a public tuning matrix.

## Lifecycle

```bash
./bin/kwin-latencyctl capture-on
# reboot or fully log out and back in
# launch the game and reproduce a stable scene
./bin/kwin-latencyctl trace game-scene-a
./bin/kwin-latencyctl capture-off
# reboot or fully log out and back in
```

`capture-on` preserves the reviewed adaptive wake and VRR policy, adds
`KWIN_LATENCY_CAPTURE=1`, and runs the adaptive render-budget controller in
shadow mode. Shadow mode learns and reports a candidate budget but cannot use
that value to schedule a frame. `capture-off` removes both flags while keeping
the reviewed performance policy enabled.

## Captured boundaries

| Boundary | Evidence |
| --- | --- |
| KWin wake and render | desired/armed/actual wake, wake lateness, raw render duration, per-output and presentation path state |
| VRR repaint choice | immediate foreground, cadence-deferred, or stock-deferred reason and absolute fallback deadline |
| Direct scanout | accepted or a reason-coded rejection at the compositor probe |
| Presentation | atomic presentation-test duration, fallback count, and queue-call duration |
| DRM commit thread | IOCTL duration, commit queue age/depth, readiness retries, safety margins, result, and callback arrival |
| HDR/color cold path | exact source/destination/pipeline descriptions, construction and hardware-matching duration, assignment result, residual scaling, and mandatory-block compensation |
| Input queue | sampled mutex wait/hold, queue depth, coalescing, and event age by class |
| GPU and audio | NVIDIA utilization/clocks/power and a concurrent PipeWire graph window |
| Scheduling and interrupts | ten-second thread runtime/runqueue deltas and interrupt snapshots |

Direct-scanout reason codes are: `0` not attempted, `1` accepted, `2` view
hidden, `3` no candidate, `4` no buffer, `5` no DMA-BUF attributes, `6` early
checks failed, `7` format unsupported, `8` buffer import failed, `9` scanout
disabled, `10` non-primary plane disabled, `11` modeset pending, `12` shadow
buffer required, `13` color pipeline unsupported, `14` fractional source
rectangle, and `15` transform unsupported.

Repaint decision codes are: `0` immediate, `1` foreground immediate, `2`
cadence deferred, and `3` stock deferred.

## Cost boundary

When capture is off, revision 15 performs only predictable static-boolean
checks. It does not read a clock, allocate, lock, format a row, or write a file.
The fixed per-frame fields occupy a small amount of `OutputFrame` storage.
Existing adaptive timing work remains bounded integer arithmetic.

When capture is on, every completed compositor frame and every completed or
failed DRM commit is formatted into the per-output CSV. Each output owns its own
256-row flush counter; the analyzer only calls an in-window tail complete when a
later row proves that batch reached disk. Input observations remain aggregated.
Cold color logs flush immediately because cache misses and mode changes are rare.
No writer calls `fsync`.

This exact mode is an observer, not the optimized gaming configuration. Clock
reads, CSV integer formatting, memory copies, and occasional page-cache writes
can affect later frame scheduling. Use it to locate and attribute latency, then
turn capture off and use matched external or application-side A/B measurements
to prove the final performance result.

## Interpreting results

Each `trace` creates `artifacts/results/<timestamp>-<label>-trace/` with raw
files plus `summary.md` and `summary.json`. Compare repeatable scenes, identical
display modes, frame caps, game settings, and kernel/scheduler state. Treat
p50 as the usual path and p95/p99/max as jitter and stall evidence.
The analyzer uses the revision 15 completion-callback timestamp to select
completed compositor frames in the ten-second trace, and submit-start time for
DRM commits, while retaining the full session CSVs for auditability.
Because monotonic time resets at boot, the trace records the boot identity and
live KWin start time and rejects telemetry files that predate either boundary.
This prevents stale rows from a previous session from aliasing a new capture
window after reboot.

Exact frame IDs alone are not called a complete artifact. A post-window row from
the same output must be present on disk, and exact compositor-to-DRM join
coverage is reported as eligible, matched, unmatched, and percentage. With two
monitors, each output is analyzed and flush-proven separately; the global frame
sequence may interleave between their files.

The pageflip callback timestamp is the point where KWin receives the DRM event.
It is not proof of panel scanout or photon emission. True input-to-photon
measurement still requires an external high-speed camera or latency device.

## Kernel-trace safety boundary

Bounded capture intentionally does not start `perf`, ftrace, BPF, trace-cmd, or
kernel DRM/fence tracepoints. A `dma_fence` trace handler faulted the
`7.1.4-1-cachyos` kernel during development. Both the lifecycle command and the
capture worker now run a fixed preflight and refuse capture if active fence
tracing is visible. There is no override. See
`INCIDENT_2026-07-23_DMA_FENCE_TRACE_KERNEL_OOPS.md`.

The before/after DRM color probe only reads object properties and blobs through
its own file descriptor. It does not issue an atomic commit, modeset, or property
write.
