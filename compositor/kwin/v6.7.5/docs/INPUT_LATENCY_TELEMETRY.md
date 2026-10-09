# Input queue telemetry and redesign gate

Revision 3.7 adds sampled measurement only. It does not replace KWin's queue mutex,
change event ordering, change pointer-motion coalescing, or alter device
dispatch.

## Activation and safety

Telemetry starts only when both conditions are true when KWin starts:

```text
KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=<exact uname -r>
KWIN_INPUT_LATENCY_TELEMETRY=1
```

A missing or mismatched kernel release disables it. This preserves the same
fail-closed recovery/LTS behavior as the compositor experiment. The optional
`KWIN_INPUT_LATENCY_TELEMETRY_SAMPLE_DIVISOR` is clamped to 1-4096 and defaults
to 64. The flush interval is clamped to 1000-60000 ms and defaults to 5000 ms.

KWin writes `~/kwin input latency.csv`. Move or rename an old capture before
restarting because a new KWin session truncates the file.

## Measurements

Each CSV row is one aggregate interval and contains:

- producer and consumer queue-lock wait and hold time;
- events queued and processed, consumer batches, and maximum queue depth;
- pointer motions removed by KWin's existing last-motion coalescing;
- sampled queue age at drain start for motion and other high-rate events, plus
  full-rate pointer-button and keyboard-key queue age;
- count, sum, maximum, and 16 logarithmic histogram buckets for every timing
  distribution.

The buckets run from at most 1 us through at most 16 ms, plus an overflow
bucket. Percentiles reported by the analyzer are conservative bucket upper
bounds, not invented point estimates.

`other` includes touch, tablet, switch, gesture, scroll-axis, and device
lifecycle events. USB audio is not in KWin's libinput path and requires a
separate ALSA/PipeWire measurement campaign.

## Bounded overhead

With telemetry disabled, the added path is a cached boolean branch. With it
enabled, exact counters use integer increments. Queue timing and high-rate event
age take a clock sample once per configured divisor; buttons and keys are always
sampled. Countdown branches avoid integer division in the per-event decision.
There are no per-event file writes or allocations for statistics. One aggregate
CSV row is written after releasing the queue mutex no more often than the
configured interval; at low activity it waits for the next sampled consumer
pass.

That design keeps the observer bounded, but it is not zero overhead. Any
candidate redesign must be compared with telemetry both enabled and disabled,
and ultimately with an external input-to-photon method.

## Capture sequence

After installing revision 3.7 and restarting:

```bash
pacman -Q kwin
test -s "$HOME/kwin input latency.csv" && head -n 2 "$HOME/kwin input latency.csv"
python3 tools/analyze_input_telemetry.py "$HOME/kwin input latency.csv"
```

Use matched 5-10 minute blocks:

1. Desktop idle, then normal desktop interaction.
2. Continuous high-rate mouse motion with repeated clicks.
3. Keyboard-heavy interaction.
4. The same reproducible game scene and frame cap used for compositor tests.
5. If available, repeat with each mouse polling rate while holding all other
   settings constant.

Record the exact package, kernel, input device and polling rate, CPU power
profile, monitor topology, refresh/VRR state, game scene, and duration.

## Candidate redesign decision

The candidate is a two-stage queue:

1. The libinput thread builds a thread-local event batch without owning the
   shared queue mutex.
2. A short lock appends or swaps that batch into a shared queue.
3. The compositor thread swaps the shared queue into a local batch under a
   short lock, then performs device updates, signal emission, and motion
   coalescing after releasing it.

This could make lock hold time independent of event decoding and downstream
signal work. It must preserve exact event order, device lifetime, wakeup
semantics, and KWin's current motion-coalescing boundary.

Do not implement it merely because a mutex exists. It becomes a worthwhile
candidate when repeated matched captures show one or more of:

- producer-wait p99 above 25 us or p99.9 above 125 us under gaming input;
- recurring queue depth above one with button/key age tails following it;
- consumer-hold p99 above 125 us;
- clear scaling of contention with device polling rate.

These are investigation triggers, not universal latency limits. If wait time is
mostly within the first histogram buckets and queue age is dominated elsewhere,
the better target is downstream input dispatch, client scheduling, game
sampling, or presentation rather than this mutex.

## What this can and cannot prove

The capture can identify KWin queue contention and queue residence time for all
libinput devices. It cannot measure USB interrupt latency, evdev-to-libinput
translation, application input sampling, game simulation, render queues, scanout,
or display response. A claimed gaming improvement still needs matched frame
telemetry and, ideally, external input-to-photon measurement.
