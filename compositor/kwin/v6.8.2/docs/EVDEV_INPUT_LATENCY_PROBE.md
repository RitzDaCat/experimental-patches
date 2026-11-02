# Evdev input-latency probe

The current hardware and OS baseline on 2026-07-15 is already strong:

- Logitech X2 SUPERSTRIKE reports an active 8000 Hz profile.
- The receiver is directly attached to USB controller `0000:0c:00.0` at 480 Mb/s.
- Its interrupt endpoints advertise `bInterval 1`, or one 125 microsecond
  high-speed USB microframe.
- Runtime USB power management is disabled for the receiver (`power/control=on`,
  `autosuspend=-1`).
- `usbhid.mousepoll=0`, so Linux honors the device endpoint instead of forcing a
  slower polling interval.
- KWin's libinput thread and main thread run as `SCHED_RR` priority 1.
- The kernel is fully preemptible and configured at 1000 Hz.

Run the non-grabbing evdev probe from a terminal, then continuously move the
mouse in circles and click several times:

```bash
python3 tools/evdev_latency_probe.py --start-delay 5 --duration 15
```

The probe applies the same exact-release gate as the compositor experiment and
refuses to run on an LTS or upgraded kernel. It sets the evdev clock to
`CLOCK_MONOTONIC`, then measures time from the kernel event timestamp to the
diagnostic reader. It does not measure sensor, wireless, game-loop, GPU, scanout,
or display latency.

Linux evdev filters unchanged state. Therefore `SYN_REPORT` cadence is a changed-
report cadence, not proof that the USB host sent a transaction on every poll.
Continuous fast movement is required for a meaningful active-rate sample.

## KWin source finding

KWin 6.7.3 and upstream commit `ed1ee4fda4deae010624bf01efa5b7a44669d7cb`
use the same design:

1. The realtime `libinput-connection` thread dispatches libinput and appends
   events to `Connection::m_eventQueue`.
2. It emits `eventsRead()` only on the empty-to-nonempty transition.
3. A queued Qt connection wakes the compositor main thread.
4. `Connection::processEvents()` combines consecutive pointer-motion events,
   forwards their summed delta, and preserves the newest libinput timestamp.

Coalescing prevents an 8 kHz mouse from creating an unbounded stale-motion
backlog. The unmeasured quantity is the age of the newest event when the main
thread processes and forwards it. Instrument this boundary before attempting
thread-priority, CPU-affinity, or event-coalescing changes.

`Connection::processEvents()` currently keeps `m_mutex` locked while it drains
the queue and emits the whole batch. The realtime producer thread takes the same
mutex in `handleEvent()` before it can append newly arrived events. This is a
credible producer-blocking boundary under an 8 kHz workload, but it is not yet a
measured latency regression.

The smallest behavior candidate is to swap `m_eventQueue` into a local deque
while holding the mutex, release the mutex immediately, and process the local
deque with the existing ordering and motion-coalescing rules. Gate that path to
the exact CachyOS kernel and retain the original locked-drain path for LTS. Its
keep/revert decision needs queue-wait telemetry before and after the change.

## Experiment order

1. Establish evdev kernel-to-reader latency under idle and game-load conditions.
2. Add kernel-gated KWin counters for queue depth, newest-event age, number of
   coalesced motions, button-event age, and time waiting for `m_mutex`. Keep
   counters in memory; export only periodic aggregates so telemetry cannot
   become the latency source.
3. Correlate KWin forwarding with the game's input sample and frame submission.
   Native Wayland and XWayland must be measured separately.
4. Correlate the submitted frame with KWin's render/commit/pageflip telemetry.
5. Only then A/B scheduler placement, CPU affinity, or a KWin fast path.

If the shared-mutex wait is visible at p99/p99.9, A/B the local-deque swap as the
first KWin fast path. Do not remove motion coalescing: folding stale motion while
preserving the newest timestamp is the correct freshness-first behavior.

Do not keep a change unless p99/p99.9 improves under game load without dropped
input, frame-time regression, missed flips, or worse idle power.
