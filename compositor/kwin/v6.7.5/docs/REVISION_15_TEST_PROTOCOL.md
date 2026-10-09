# Revision 15 corrected capture test protocol

Revision 15 keeps the revision-14 NVIDIA HDR/WCG direct-scanout candidate and
corrects the diagnostic path used to evaluate it. It adds exact completed-frame
IDs, explicit compositor phase boundaries, compositor-to-DRM correlation,
per-output flush proof, and nanosecond cold color-pipeline timing. Capture is
temporary and remains off in the lowest-overhead gaming configuration.

## One-restart installation

From the project root:

```bash
./bin/kwin-latencyctl test
./bin/kwin-latencyctl install --capture
```

Restart once, then verify:

```bash
./bin/kwin-latencyctl status
```

The installed pacman version remains `6.7.3-1.1`; package metadata identifies
experiment revision 15. The exact running-kernel gate and capture state must
both report active. Booting a different kernel prevents the experimental
behavior and capture from activating.

## Controlled captures

Keep the same monitor layout, HDR/WCG state, VRR state, game settings, scene,
frame cap, scheduler, and background workload for each comparison. Let the
fullscreen scene settle before starting the command so Alt-Tab time is not
misclassified as steady-state game time.

At a 120 FPS cap:

```bash
./bin/kwin-latencyctl trace game-r15-hdr-120
```

Uncapped:

```bash
./bin/kwin-latencyctl trace game-r15-hdr-uncapped
```

Run at least two captures per condition. Test overlays, Alt-Tab, and
direct-scanout re-entry in a separate transition capture.

## Capture integrity

A usable result must satisfy all of these conditions:

- the controller accepts both the corrected compositor and DRM schemas;
- telemetry files belong to the currently running KWin process;
- every analyzed output has a later row proving its in-window buffered tail
  reached disk;
- the summary reports compositor-to-DRM eligible, matched, unmatched, and
  percentage counts;
- unmatched frames are investigated rather than silently excluded;
- compositor phases are treated as nested where documented and are not summed
  into a fabricated total; and
- no perf, ftrace, BPF, trace-cmd, or kernel fence tracepoint is active.

With two monitors, inspect each output independently. One output's rows do not
prove that the other output's buffer was flushed.

## Performance and correctness acceptance

- colors, SDR brightness, HDR metadata, Night Light, and black levels remain
  correct;
- no purple/green transform error, new flicker, KWin crash, NVIDIA Xid, atomic
  failure loop, or compositor startup delay appears;
- direct scanout is accepted where the exact color transform is representable,
  or the reason-coded blocker is reported;
- p50, p95, p99, and maximum values are compared in nanoseconds for wake,
  compositor phases, presentation tests, DRM queue/IOCTL/callback boundaries,
  and cold color construction/matching; and
- capture-off matched A/B or an external/application-side measurement confirms
  any final performance claim.

Exact capture is deliberately heavier than the gaming configuration: it reads
clocks and formats every completed frame and DRM commit. Use it to attribute
cost, then turn it off:

```bash
./bin/kwin-latencyctl capture-off
```

Restart KWin with a full logout/login or reboot. For an input-to-photon claim,
use a high-speed camera, photodiode, or dedicated latency device; a DRM
page-flip callback is not photon emission.

## Rollback

To restore the repository package and remove experimental state:

```bash
./bin/kwin-latencyctl rollback
```

The validated revision-14 package is archived under
`artifacts/packages/history/` for controlled regression work.
