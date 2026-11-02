# Observer cost audit

Date: 2026-07-17

Host scope: the local CachyOS system used to build KWin 6.7.3-3.7

## Engineering constraint

Adaptive control must retain every compositor wake sample, while diagnostic
observers must not perform full-rate clock and histogram work at 240 Hz display
rates or 8 kHz input rates.

## Hot-path result

The adaptive controller remains full-rate. Its incremental measurement work is
one `std::chrono::steady_clock::now()` at timer dispatch followed by bounded
integer comparisons and state updates. It performs no allocation, lock, or file
I/O. Sampling this controller would weaken its reaction to repeated tail events,
so only its diagnostic CSV is sampled.

Input diagnostics use countdown sampling with a default divisor of 64. Exact
event/batch/depth counters remain integer increments. Pointer buttons and
keyboard keys remain full-rate because their event rates are low and their tails
matter directly. Diagnostic file output occurs outside the input queue mutex no
more often than every five seconds and may be delayed until the next sampled
consumer pass.

## Local microbenchmark

Run:

```bash
scripts/run_observer_bench.sh 10000000 64
```

Result from this host:

```text
steady_clock_now_ns_per_call=16.79
full_observer_ns_per_event=17.78
sampled_observer_ns_per_event=0.39
observer_cost_reduction_percent=97.79
```

The benchmark uses the same clock, countdown, fixed histogram, sum, maximum, and
counter mechanisms, compiled with `-O3`. It shows the CPU-side mechanism cost,
not input-to-photon latency. It excludes mutex contention, libinput work, cache
interference, scheduler preemption, filesystem stalls, and compositor rendering.
Those require live enabled/disabled A/B captures.

## Operating modes

For an evidence capture:

```text
KWIN_LOG_PERFORMANCE_DATA=1
KWIN_COMPOSITOR_TELEMETRY_SAMPLE_DIVISOR=16
KWIN_INPUT_LATENCY_TELEMETRY=1
KWIN_INPUT_LATENCY_TELEMETRY_SAMPLE_DIVISOR=64
KWIN_INPUT_LATENCY_TELEMETRY_INTERVAL_MS=5000
```

For the lowest-observer gaming run after evidence is collected:

```text
KWIN_LOG_PERFORMANCE_DATA=0
KWIN_INPUT_LATENCY_TELEMETRY=0
```

The adaptive compositor controller can remain at mode 2 in the second profile;
its control path does not depend on either diagnostic output.
